import json
import re
from typing import Any

import boto3

# Pricing API client (must be us-east-1)
pricing_client = boto3.client('pricing', region_name='us-east-1')

# Bedrock client (use target region)
target_region = 'us-east-1'  # or your preferred region
bedrock_client = boto3.client('bedrock', region_name=target_region)


def canonical_model_name(name: str):
    return re.sub(r'\W+', '-', name).lower().strip('-')


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
        yield m


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
    """Extract pricing information from a single product"""
    product_info = product.get('product', {})
    attributes = product_info.get('attributes', {})

    # Extract pricing terms (On-Demand only)
    terms = product.get('terms', {})
    on_demand = terms.get('OnDemand', {})

    pricing_entries = []
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

            inference_type = attributes.get('inferenceType', '').lower()
            assert 'token' in inference_type, attributes
            assert 'input' in inference_type or 'output' in inference_type, attributes
            if 'cache' in inference_type:
                assert 'read' in inference_type or 'write' in inference_type, attributes

            model_keys = [k for k in attributes if 'model' in k.lower()]
            assert len(model_keys) == 1, attributes
            [model_key] = model_keys
            assert model_key in {'model', 'titanModel'}, model_key
            model = attributes[model_key]
            if model.endswith(' Latency Optimized'):
                # TODO investigate more
                continue

            provider = attributes.get('provider', 'Amazon')
            if provider == 'Mistral':
                provider = 'Mistral AI'
            pricing_entries.append(dict(model=model, provider=provider, attributes=attributes, price_data=price_data))

    return pricing_entries


def get_model(price):
    provider_models = [m for m in models if m.get('providerName') == price['provider']]
    matches = [
        m
        for m in provider_models
        if any(
            canonical_model_name(price['model']) in canonical_model_name(m.get(k))
            or canonical_model_name(m.get(k)) in canonical_model_name(price['model'])
            for k in ['modelId', 'modelName']
        )
    ]
    if not matches:
        # TODO
        assert price['model'] in [
            'Claude 2.0',
            'Claude 2.1',
            'Claude 3 Sonnet',
            'Claude Instant',
            'Titan Embeddings G1 Image',
            'Titan Text G1 Premier',
            'Titan Text G1 Premier',
            'TitanEmbeddingsV2-Text-input',
        ]
        return
    assert len(matches) == 1, (price, matches, provider_models)


raw_prices = list(get_bedrock_pricing_data())
parsed_prices = [x for p in raw_prices for x in parse_pricing_item(p)]
models = list(get_available_models())
for p in parsed_prices:
    get_model(p)
