from __future__ import annotations

import importlib
import json
import runpy
from decimal import Decimal
from unittest.mock import Mock

import pytest
from mypy_boto3_bedrock import BedrockClient
from mypy_boto3_pricing import PricingClient

from prices import source_aws
from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice


class FakeBedrockClient:
    def __init__(self, model_summaries: list[dict[str, object]]) -> None:
        self.model_summaries = model_summaries

    def list_foundation_models(self) -> dict[str, list[dict[str, object]]]:
        return {'modelSummaries': self.model_summaries}


class FakePaginator:
    def __init__(self, pages: list[dict[str, list[str]]]) -> None:
        self.pages = pages
        self.parameters: dict[str, object] = {}

    def paginate(self, **kwargs: object) -> list[dict[str, list[str]]]:
        self.parameters = kwargs
        return self.pages


class FakePricingClient:
    def __init__(self, pages: list[dict[str, list[str]]]) -> None:
        self.paginator = FakePaginator(pages)
        self.paginator_name = ''

    def get_paginator(self, name: str) -> FakePaginator:
        self.paginator_name = name
        return self.paginator


class FakeProviderYaml:
    def __init__(self, existing_model_ids: set[str]) -> None:
        self.existing_model_ids = existing_model_ids
        self.updated: list[str] = []
        self.added: list[str] = []
        self.saved = False

    def update_model(self, model_id: str, model: ModelInfo, *, set_prices: bool) -> None:
        assert set_prices is True
        if model_id not in self.existing_model_ids:
            raise LookupError(model_id)
        self.updated.append(model.id)

    def add_model(self, model: ModelInfo) -> int:
        self.added.append(model.id)
        return 1

    def save(self) -> None:
        self.saved = True


def model_summary(
    model_id: str,
    model_name: str,
    provider_name: str,
    *,
    status: str = 'ACTIVE',
    inference_types: list[str] | None = None,
) -> dict[str, object]:
    return {
        'modelId': model_id,
        'modelName': model_name,
        'providerName': provider_name,
        'modelLifecycle': {'status': status},
        'inferenceTypesSupported': inference_types or ['ON_DEMAND'],
    }


def price_data(usd: str = '0.001', unit: str = '1K tokens') -> dict[str, object]:
    return {'unit': unit, 'pricePerUnit': {'USD': usd}}


def product(attributes: dict[str, object], *dimensions: dict[str, object]) -> dict[str, object]:
    return {
        'product': {'attributes': attributes},
        'terms': {'OnDemand': {'term': {'priceDimensions': {str(i): price for i, price in enumerate(dimensions)}}}},
    }


def pricing_entry(model: str, provider: str, *, price: dict[str, object] | None = None) -> source_aws.PricingEntry:
    return source_aws.PricingEntry(
        model=model,
        provider=provider,
        attributes={},
        price_data=price or price_data(),
    )


def test_import_does_not_create_aws_clients(monkeypatch: pytest.MonkeyPatch):
    client = Mock()
    monkeypatch.setattr(source_aws.boto3, 'client', client)

    importlib.reload(source_aws)

    client.assert_not_called()


def test_get_available_models_filters_inactive_and_unsupported_models():
    client = FakeBedrockClient(
        [
            model_summary('inactive', 'Inactive', 'Example', status='LEGACY'),
            model_summary('unsupported', 'Unsupported', 'Example', inference_types=['PROVISIONED']),
            model_summary('on-demand', 'On demand', 'Example'),
            model_summary('profile', 'Profile', 'Example', inference_types=['INFERENCE_PROFILE']),
        ]
    )

    models = list(source_aws.get_available_models(client))  # pyright: ignore[reportArgumentType]

    assert [model['modelId'] for model in models] == ['on-demand', 'profile']
    assert all(model['prices'] == [] for model in models)


def test_get_bedrock_pricing_data_decodes_every_page():
    client = FakePricingClient(
        [
            {'PriceList': ['{"first": 1}']},
            {'PriceList': ['{"second": 2}']},
        ]
    )

    prices = list(source_aws.get_bedrock_pricing_data(client))  # pyright: ignore[reportArgumentType]

    assert prices == [{'first': 1}, {'second': 2}]
    assert client.paginator_name == 'get_products'
    assert client.paginator.parameters == {
        'ServiceCode': 'AmazonBedrock',
        'Filters': [
            {'Type': 'TERM_MATCH', 'Field': 'ServiceCode', 'Value': 'AmazonBedrock'},
            {'Type': 'TERM_MATCH', 'Field': 'regionCode', 'Value': 'us-east-1'},
        ],
        'FormatVersion': 'aws_v1',
    }


@pytest.mark.parametrize(
    'attributes,dimension',
    [
        ({'model': 'Test', 'feature': 'On-demand Inference'}, price_data(unit='requests')),
        ({'model': 'Test', 'featureType': 'Training', 'feature': 'On-demand Inference'}, price_data()),
        ({'model': 'Test', 'feature': 'Other'}, price_data()),
        ({'model': 'Test Latency Optimized', 'feature': 'On-demand Inference'}, price_data()),
        ({'model': 'Nova Sonic 2.0', 'feature': 'On-demand Inference'}, price_data()),
        ({'model': 'Claude 2.0', 'provider': 'Anthropic', 'feature': 'On-demand Inference'}, price_data()),
    ],
)
def test_parse_pricing_item_skips_unsupported_entries(attributes: dict[str, object], dimension: dict[str, object]):
    assert source_aws.parse_pricing_item(product(attributes, dimension)) == []


@pytest.mark.parametrize(
    'attributes,expected_provider',
    [
        ({'model': 'Nova Pro', 'feature': 'On-demand Inference'}, 'Amazon'),
        ({'model': 'Mistral Small', 'provider': 'Mistral', 'feature': 'On-demand Inference'}, 'Mistral AI'),
        ({'model': 'Other', 'provider': 'Example', 'feature': 'On-demand Inference'}, 'Example'),
    ],
)
def test_parse_pricing_item_extracts_supported_entries(attributes: dict[str, object], expected_provider: str):
    [parsed] = source_aws.parse_pricing_item(product(attributes, price_data()))

    assert parsed['model'] == attributes['model']
    assert parsed['provider'] == expected_provider
    assert parsed['price_data'] == price_data()


def test_parse_pricing_item_accepts_no_on_demand_terms():
    assert source_aws.parse_pricing_item({'product': {'attributes': {}}, 'terms': {}}) == []


def test_get_model_returns_none_for_known_unmatched_model():
    models = [model_summary('amazon.other-v1:0', 'Other', 'Amazon')]

    assert source_aws.get_model(pricing_entry('Titan Text G1 Lite', 'Amazon'), models) is None  # pyright: ignore[reportArgumentType]


def test_get_model_matches_names_in_both_directions():
    short_model = model_summary('example.short-v1:0', 'Example Short', 'Example')
    long_model = model_summary('example.long-v1:0', 'Example', 'Example')

    assert source_aws.get_model(pricing_entry('Example', 'Example'), [short_model]) == short_model  # pyright: ignore[reportArgumentType]
    assert source_aws.get_model(pricing_entry('Example Long', 'Example'), [long_model]) == long_model  # pyright: ignore[reportArgumentType]


def test_get_model_uses_the_legacy_mistral_large_model():
    legacy_input_price: dict[str, object] = {
        'appliesTo': [],
        'beginRange': '0',
        'description': '$0.004 per 1K tokens for Mistral Large input tokens in US East (N.Virginia)',
        'endRange': 'Inf',
        'pricePerUnit': {'USD': '0.0040000000'},
        'rateCode': '4JGB54U6JUKURPCS.JRTCKXETXF.6YS6EN2CT7',
        'unit': '1K tokens',
    }
    models = [
        model_summary('mistral.mistral-large-2402-v1:0', 'Mistral Large', 'Mistral AI'),
        model_summary('mistral.mistral-large-2411-v1:0', 'Mistral Large', 'Mistral AI'),
    ]

    model = source_aws.get_model(pricing_entry('Mistral Large', 'Mistral AI', price=legacy_input_price), models)  # pyright: ignore[reportArgumentType]

    assert model == models[0]


@pytest.mark.parametrize(
    ('inference_type', 'expected_attr'),
    [
        ('input audio cache token', 'cache_audio_read_mtok'),
        ('input audio token', 'input_audio_mtok'),
        ('input cache read token', 'cache_read_mtok'),
        ('input cache write token', 'cache_write_mtok'),
        ('input token', 'input_mtok'),
        ('output speech token', 'output_audio_mtok'),
        ('output token', 'output_mtok'),
    ],
)
def test_get_usage_attr_from_inference_type(inference_type: str, expected_attr: str):
    assert source_aws.get_usage_attr_from_inference_type(inference_type) == expected_attr


@pytest.mark.parametrize('inference_type', ['input audio cache write token', 'input cache token', 'other'])
def test_get_usage_attr_from_inference_type_rejects_unknown_types(inference_type: str):
    with pytest.raises(AssertionError):
        source_aws.get_usage_attr_from_inference_type(inference_type)


def test_canonical_model_name_normalizes_punctuation():
    assert source_aws.canonical_model_name('Mistral: Large_v2!') == 'mistral-large_v2'


def test_get_model_infos_fetches_prices_and_skips_unusable_entries():
    bedrock_client = FakeBedrockClient(
        [
            model_summary('example.model-one-v1:0', 'Model One', 'Example'),
            model_summary('example.audio-v1:0', 'Audio Model', 'Example'),
            model_summary('example.unused-v1:0', 'Unused Model', 'Example'),
        ]
    )
    pricing_client = FakePricingClient(
        [
            {
                'PriceList': [
                    json.dumps(
                        product(
                            {
                                'model': 'Model One',
                                'provider': 'Example',
                                'feature': 'On-demand Inference',
                                'inferenceType': 'Input Tokens',
                            },
                            price_data('0.001'),
                        )
                    ),
                    json.dumps(
                        product(
                            {
                                'model': 'Model One',
                                'provider': 'Example',
                                'feature': 'On-demand Inference',
                                'inferenceType': 'Output Tokens',
                            },
                            price_data('0.003'),
                        )
                    ),
                    json.dumps(
                        product(
                            {
                                'model': 'Model One',
                                'provider': 'Example',
                                'feature': 'On-demand Inference',
                                'inferenceType': 'Flex Input Tokens',
                            },
                            price_data('0.001'),
                        )
                    ),
                    json.dumps(
                        product(
                            {
                                'model': 'Model One',
                                'provider': 'Example',
                                'feature': 'On-demand Inference',
                                'inferenceType': 'Cache Read Input Tokens',
                            },
                            price_data('0'),
                        )
                    ),
                    json.dumps(
                        product(
                            {
                                'model': 'Audio Model',
                                'provider': 'Example',
                                'feature': 'On-demand Inference',
                                'inferenceType': 'Input Audio Tokens',
                            },
                            price_data('0.002'),
                        )
                    ),
                    json.dumps(
                        product(
                            {
                                'model': 'Titan Text G1 Lite',
                                'feature': 'On-demand Inference',
                                'inferenceType': 'Input Tokens',
                            },
                            price_data('0.001'),
                        )
                    ),
                ]
            }
        ]
    )

    model_infos = source_aws.get_model_infos(pricing_client, bedrock_client)  # pyright: ignore[reportArgumentType]

    assert [model.id for model in model_infos] == ['example.model-one-v1:0', 'example.audio-v1:0']
    assert model_infos[0].prices == ModelPrice(input_mtok=Decimal('1.000'), output_mtok=Decimal('3.000'))
    assert model_infos[1].prices == ModelPrice(input_audio_mtok=Decimal('2.000'))


def test_get_model_infos_rejects_duplicate_model_ids():
    client = FakeBedrockClient(
        [
            model_summary('example.duplicate-v1:0', 'One', 'Example'),
            model_summary('example.duplicate-v1:0', 'Two', 'Example'),
        ]
    )

    with pytest.raises(AssertionError, match='Duplicate model IDs found'):
        source_aws.get_model_infos(FakePricingClient([]), client)  # pyright: ignore[reportArgumentType]


def test_main_updates_existing_and_adds_missing_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    clients = iter([FakePricingClient([]), FakeBedrockClient([])])
    provider_yaml = FakeProviderYaml({'existing'})
    model_infos = [
        ModelInfo(id='existing', prices=ModelPrice(input_mtok=Decimal('1')), match=ClauseEquals(equals='existing')),
        ModelInfo(id='new', prices=ModelPrice(input_mtok=Decimal('2')), match=ClauseEquals(equals='new')),
    ]

    def fake_client(_service_name: str, **_kwargs: object) -> FakePricingClient | FakeBedrockClient:
        return next(clients)

    def get_fixed_model_infos(_pricing_client: PricingClient, _bedrock_client: BedrockClient) -> list[ModelInfo]:
        return model_infos

    monkeypatch.setattr(source_aws.boto3, 'client', fake_client)
    monkeypatch.setattr(source_aws, 'get_model_infos', get_fixed_model_infos)
    monkeypatch.setattr(source_aws, 'get_providers_yaml', lambda: {'aws': provider_yaml})

    source_aws.main()

    assert provider_yaml.updated == ['existing']
    assert provider_yaml.added == ['new']
    assert provider_yaml.saved is True
    assert capsys.readouterr().out == '  1 models added\n  1 models updated\n'


def test_main_does_not_save_without_models(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    clients = iter([FakePricingClient([]), FakeBedrockClient([])])
    provider_yaml = FakeProviderYaml(set())

    def fake_client(_service_name: str, **_kwargs: object) -> FakePricingClient | FakeBedrockClient:
        return next(clients)

    def get_no_model_infos(_pricing_client: PricingClient, _bedrock_client: BedrockClient) -> list[ModelInfo]:
        return []

    monkeypatch.setattr(source_aws.boto3, 'client', fake_client)
    monkeypatch.setattr(source_aws, 'get_model_infos', get_no_model_infos)
    monkeypatch.setattr(source_aws, 'get_providers_yaml', lambda: {'aws': provider_yaml})

    source_aws.main()

    assert provider_yaml.saved is False
    assert capsys.readouterr().out == ''


def test_main_saves_when_only_models_are_updated(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    clients = iter([FakePricingClient([]), FakeBedrockClient([])])
    provider_yaml = FakeProviderYaml({'existing'})
    model_infos = [ModelInfo(id='existing', prices=ModelPrice(), match=ClauseEquals(equals='existing'))]

    def fake_client(_service_name: str, **_kwargs: object) -> FakePricingClient | FakeBedrockClient:
        return next(clients)

    def get_fixed_model_infos(_pricing_client: PricingClient, _bedrock_client: BedrockClient) -> list[ModelInfo]:
        return model_infos

    monkeypatch.setattr(source_aws.boto3, 'client', fake_client)
    monkeypatch.setattr(source_aws, 'get_model_infos', get_fixed_model_infos)
    monkeypatch.setattr(source_aws, 'get_providers_yaml', lambda: {'aws': provider_yaml})

    source_aws.main()

    assert provider_yaml.saved is True
    assert capsys.readouterr().out == '  1 models updated\n'


def test_main_saves_when_only_models_are_added(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    clients = iter([FakePricingClient([]), FakeBedrockClient([])])
    provider_yaml = FakeProviderYaml(set())
    model_infos = [ModelInfo(id='new', prices=ModelPrice(), match=ClauseEquals(equals='new'))]

    def fake_client(_service_name: str, **_kwargs: object) -> FakePricingClient | FakeBedrockClient:
        return next(clients)

    def get_fixed_model_infos(_pricing_client: PricingClient, _bedrock_client: BedrockClient) -> list[ModelInfo]:
        return model_infos

    monkeypatch.setattr(source_aws.boto3, 'client', fake_client)
    monkeypatch.setattr(source_aws, 'get_model_infos', get_fixed_model_infos)
    monkeypatch.setattr(source_aws, 'get_providers_yaml', lambda: {'aws': provider_yaml})

    source_aws.main()

    assert provider_yaml.saved is True
    assert capsys.readouterr().out == '  1 models added\n'


def test_module_runs_main_only_when_executed_as_a_script(monkeypatch: pytest.MonkeyPatch):
    clients = iter([FakePricingClient([]), FakeBedrockClient([])])
    provider_yaml = FakeProviderYaml(set())
    requested_services: list[str] = []

    def fake_client(_service_name: str, **_kwargs: object) -> FakePricingClient | FakeBedrockClient:
        requested_services.append(_service_name)
        return next(clients)

    monkeypatch.setattr(source_aws.boto3, 'client', fake_client)
    monkeypatch.setattr('prices.update.get_providers_yaml', lambda: {'aws': provider_yaml})

    with pytest.warns(RuntimeWarning, match='found in sys.modules'):
        runpy.run_module('prices.source_aws', run_name='__main__')

    assert requested_services == ['pricing', 'bedrock']
    assert provider_yaml.saved is False
