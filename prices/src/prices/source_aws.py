from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any, TypedDict

import boto3
from mypy_boto3_bedrock.type_defs import FoundationModelSummaryTypeDef

from prices.prices_types import ClauseContains, ModelInfo, ModelPrice
from prices.update import get_providers_yaml

pricing_client = boto3.client('pricing', region_name='us-east-1')  # pyright: ignore[reportUnknownMemberType]

# TODO other regions (pricing client region will still be us-east-1)
target_region = 'us-east-1'
bedrock_client = boto3.client('bedrock', region_name=target_region)  # pyright: ignore[reportUnknownMemberType]


class PricingEntry(TypedDict):
    model: str
    provider: str
    attributes: dict[str, Any]
    price_data: dict[str, Any]


class ExtendedFoundationModelSummaryTypeDef(FoundationModelSummaryTypeDef):
    prices: list[PricingEntry]
    providerName: str  # pyright: ignore[reportGeneralTypeIssues]
    modelName: str  # pyright: ignore[reportGeneralTypeIssues]


def get_available_models():
    response = bedrock_client.list_foundation_models()
    for m in response['modelSummaries']:
        status = m.get('modelLifecycle', {}).get('status')
        # TODO check other statuses
        if status != 'ACTIVE':
            continue
        # TODO check other inferenceTypesSupported values
        if not {'ON_DEMAND', 'INFERENCE_PROFILE'}.intersection(m.get('inferenceTypesSupported', [])):
            continue
        yield ExtendedFoundationModelSummaryTypeDef(**m, prices=[])


def get_bedrock_pricing_data():
    paginator = pricing_client.get_paginator('get_products')
    page_iterator = paginator.paginate(
        ServiceCode='AmazonBedrock',
        Filters=[
            {'Type': 'TERM_MATCH', 'Field': 'ServiceCode', 'Value': 'AmazonBedrock'},
            {'Type': 'TERM_MATCH', 'Field': 'regionCode', 'Value': target_region},
        ],
        FormatVersion='aws_v1',
    )

    for page in page_iterator:
        for product_str in page['PriceList']:
            yield json.loads(product_str)


def parse_pricing_item(product: dict[str, Any]):
    product_info = product.get('product', {})
    attributes = product_info.get('attributes', {})

    # Extract pricing terms (On-Demand only)
    terms = product.get('terms', {})
    on_demand = terms.get('OnDemand', {})

    pricing_entries: list[PricingEntry] = []
    for term_data in on_demand.values():
        price_dimensions = term_data.get('priceDimensions', {})
        for price_data in price_dimensions.values():
            unit = price_data['unit']
            if (
                'token' not in unit.lower()
                or attributes.get('featureType') == 'Training'
                or attributes.get('feature') != 'On-demand Inference'
            ):
                continue
            assert unit == '1K tokens'

            model_keys = [k for k in attributes if 'model' in k.lower()]
            assert len(model_keys) == 1, attributes
            [model_key] = model_keys
            assert model_key in {'model', 'titanModel'}, model_key
            model = attributes[model_key]
            if model.endswith(' Latency Optimized'):
                # TODO investigate more
                continue

            if model == 'Nova Sonic 2.0':
                # Currently this is missing the correct model to match against,
                # which causes it to match against 'Nova Sonic' (v1) incorrectly.
                continue

            provider = attributes.get('provider', 'Amazon')
            if provider == 'Mistral':
                provider = 'Mistral AI'
            if provider == 'Anthropic':
                # These are all legacy models.
                # Anthropic models prices aren't available via the API so aren't automated.
                assert model in {
                    'Claude 2.0',
                    'Claude 2.1',
                    'Claude 3 Sonnet',
                    'Claude 3 Haiku',
                    'Claude Instant',
                }, model
                continue
            pricing_entries.append(
                PricingEntry(model=model, provider=provider, attributes=attributes, price_data=price_data)
            )

    return pricing_entries


def get_model(price: PricingEntry) -> ExtendedFoundationModelSummaryTypeDef | None:
    provider_models = [m for m in models if m.get('providerName') == price['provider']]
    matches = [
        m
        for m in provider_models
        if any(
            canonical_model_name(price['model']) in canonical_model_name(model_name)
            or canonical_model_name(model_name) in canonical_model_name(price['model'])
            for model_name in [m['modelId'], m['modelName']]
        )
    ]
    assert (
        price['model']
        in {
            'Titan Embeddings G1 Image',
            'Titan Text G1 Premier',
            'Titan Text G1 Lite',
            'Titan Text G1 Express',
            'TitanEmbeddingsV2-Text-input',
            'Nova 2.0 Omni',
            'Nova 2.0 Pro',
            'Nova 2.0 Lite',
        }
    ) == (not matches), (price, matches, provider_models)
    if not matches:
        return None
    if price['model'] == 'Mistral Large':
        # Currently there are two Mistral Large models with different prices,
        # but the prices of the newer model aren't available via the API yet.
        assert len(matches) == 2
        assert price['price_data'] in [
            {
                'appliesTo': [],
                'beginRange': '0',
                'description': '$0.004 per 1K tokens for Mistral Large input tokens in US East (N.Virginia)',
                'endRange': 'Inf',
                'pricePerUnit': {'USD': '0.0040000000'},
                'rateCode': '4JGB54U6JUKURPCS.JRTCKXETXF.6YS6EN2CT7',
                'unit': '1K tokens',
            },
            {
                'appliesTo': [],
                'beginRange': '0',
                'description': '$0.012 per 1K tokens for Mistral Large output tokens in US East (N.Virginia)',
                'endRange': 'Inf',
                'pricePerUnit': {'USD': '0.0120000000'},
                'rateCode': 'WHNSGG64M5QAAPU7.JRTCKXETXF.6YS6EN2CT7',
                'unit': '1K tokens',
            },
        ]
        matches = [m for m in matches if m['modelId'] == 'mistral.mistral-large-2402-v1:0']
    assert len(matches) == 1, (price, matches, provider_models)
    return matches[0]


models = list(get_available_models())


def get_model_infos():
    raw_prices = list(get_bedrock_pricing_data())
    parsed_prices = [x for p in raw_prices for x in parse_pricing_item(p)]
    models_by_id = {m['modelId']: m for m in models}
    assert len(models_by_id) == len(models), 'Duplicate model IDs found'
    for p in parsed_prices:
        model = get_model(p)
        if not model:
            continue
        model['prices'].append(p)
    model_infos: list[ModelInfo] = []
    for model in models:
        if not model['prices']:
            continue
        model_price = ModelPrice()
        for price in model['prices']:
            price_mtok = Decimal(price['price_data']['pricePerUnit']['USD']) * 1000
            if not price_mtok:
                continue
            attributes = price['attributes']
            inference_type = attributes.get('inferenceType', '').lower()
            assert 'token' in inference_type, attributes
            if 'flex' in inference_type or 'priority' in inference_type or 'batch' in inference_type:
                # TODO
                continue
            key = get_usage_attr_from_inference_type(inference_type)
            assert getattr(model_price, key) is None, (model_price, model, key, price)
            setattr(model_price, key, price_mtok)
        model_id = model['modelId']
        simple_model_id = re.sub(r'(:\d)?$', '', model_id)
        model_info = ModelInfo(
            id=model_id, name=model['modelName'], prices=model_price, match=ClauseContains(contains=simple_model_id)
        )
        model_infos.append(model_info)

    for model_info in model_infos:
        assert model_info.match.is_match(model_info.id)
        for other in model_infos:
            if model_info is other:
                continue
            assert other.name
            assert not model_info.match.is_match(other.id)
            assert not model_info.match.is_match(other.name)

    return model_infos


def get_usage_attr_from_inference_type(inference_type: str) -> str:
    attr = None
    audio = 'audio' in inference_type or 'speech' in inference_type
    if 'input' in inference_type:
        if audio:
            if 'cache' in inference_type:
                assert 'write' not in inference_type
                attr = 'cache_audio_read_mtok'
            else:
                attr = 'input_audio_mtok'
        elif 'cache' in inference_type:
            if 'read' in inference_type:
                attr = 'cache_read_mtok'
            elif 'write' in inference_type:
                attr = 'cache_write_mtok'
        else:
            attr = 'input_mtok'
    elif 'output' in inference_type:
        if audio:
            attr = 'output_audio_mtok'
        else:
            attr = 'output_mtok'
    assert attr, inference_type
    return attr


def canonical_model_name(name: str):
    return re.sub(r'\W+', '-', name).lower().strip('-')


def main():
    model_infos = get_model_infos()
    providers_yaml = get_providers_yaml()

    provider_yaml = providers_yaml['aws']
    models_added = 0
    models_updated = 0
    for model_info in model_infos:
        assert isinstance(model_info.prices, ModelPrice)
        try:
            provider_yaml.update_model(model_info.id, model_info, set_prices=True)
        except LookupError:
            models_added += provider_yaml.add_model(model_info)
        else:
            models_updated += 1

    if models_added or models_updated:
        if models_added:
            print(f'  {models_added} models added')
        if models_updated:
            print(f'  {models_updated} models updated')
        provider_yaml.save()


main()
