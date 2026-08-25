from __future__ import annotations

import importlib
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from prices import source_aws, update
from prices.prices_types import ModelInfo, ModelPrice


class FakeBedrockClient:
    def __init__(self, model_summaries: list[dict[str, object]]) -> None:
        self.model_summaries = model_summaries

    def list_foundation_models(self) -> dict[str, list[dict[str, object]]]:
        return {'modelSummaries': self.model_summaries}


class FakePaginator:
    def __init__(self, pages: list[dict[str, list[str]]]) -> None:
        self.pages = pages

    def paginate(self, **_kwargs: object) -> list[dict[str, list[str]]]:
        return self.pages


class FakePricingClient:
    def __init__(self, pages: list[dict[str, list[str]]]) -> None:
        self.paginator = FakePaginator(pages)

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == 'get_products'
        return self.paginator


class FakeProviderYaml:
    def __init__(self, existing_model_ids: set[str]) -> None:
        self.existing_model_ids = existing_model_ids
        self.updated: list[ModelInfo] = []
        self.added: list[ModelInfo] = []
        self.saved = False

    def update_model(self, model_id: str, model: ModelInfo, *, set_prices: bool) -> None:
        assert set_prices is True
        if model_id not in self.existing_model_ids:
            raise LookupError(model_id)
        self.updated.append(model)

    def add_model(self, model: ModelInfo) -> int:
        self.added.append(model)
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


def product(
    model_name: str,
    inference_type: str,
    price: str,
    *,
    provider: str = 'Example',
    feature: str = 'On-demand Inference',
    unit: str = '1K tokens',
) -> str:
    price_data: dict[str, object] = {'unit': unit, 'pricePerUnit': {'USD': price}}
    return json.dumps(
        {
            'product': {
                'attributes': {
                    'model': model_name,
                    'provider': provider,
                    'feature': feature,
                    'inferenceType': inference_type,
                }
            },
            'terms': {'OnDemand': {'term': {'priceDimensions': {'price': price_data}}}},
        }
    )


def install_clients(
    monkeypatch: pytest.MonkeyPatch,
    pricing_client: FakePricingClient,
    bedrock_client: FakeBedrockClient,
) -> None:
    clients = {'pricing': pricing_client, 'bedrock': bedrock_client}

    def client(service_name: str, **_kwargs: object) -> FakePricingClient | FakeBedrockClient:
        return clients[service_name]

    monkeypatch.setattr(source_aws.boto3, 'client', client)


def test_import_does_not_create_aws_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Mock()
    monkeypatch.setattr(source_aws.boto3, 'client', client)

    importlib.reload(source_aws)

    client.assert_not_called()


def test_main_imports_aws_catalog(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    provider_yaml = FakeProviderYaml({'example.text-v1:0'})
    bedrock_client = FakeBedrockClient(
        [
            model_summary('inactive', 'Inactive', 'Example', status='LEGACY'),
            model_summary('unsupported', 'Unsupported', 'Example', inference_types=['PROVISIONED']),
            model_summary('example.text-v1:0', 'Text Model', 'Example'),
            model_summary('example.audio-v1:0', 'Audio Model', 'Example', inference_types=['INFERENCE_PROFILE']),
            model_summary('example.unpriced-v1:0', 'Unpriced', 'Example'),
            model_summary('mistral.small-v1:0', 'Mistral Small', 'Mistral AI'),
        ]
    )
    pricing_client = FakePricingClient(
        [
            {
                'PriceList': [
                    product('Text Model', 'Input Tokens', '0.001'),
                    product('Text Model', 'Output Tokens', '0.003'),
                    product('Text Model', 'Cache Read Input Tokens', '0.0002'),
                    product('Text Model', 'Cache Write Input Tokens', '0.0004'),
                    product('Text Model', 'Input Audio Cache Tokens', '0.0005'),
                    product('Text Model', 'Flex Input Tokens', '0.004'),
                    product('Text Model', 'Priority Input Tokens', '0'),
                    product('Audio Model', 'Input Audio Tokens', '0.002'),
                    product('Audio Model', 'Output Speech Tokens', '0.005'),
                    product('Ignored', 'Input Tokens', '1', feature='Training'),
                    product('Ignored', 'Input Tokens', '1', unit='requests'),
                    product('Ignored Latency Optimized', 'Input Tokens', '1'),
                    product('Nova Sonic 2.0', 'Input Tokens', '1', provider='Amazon'),
                    product('Claude 2.0', 'Input Tokens', '1', provider='Anthropic'),
                    product('Titan Text G1 Lite', 'Input Tokens', '0.001', provider='Amazon'),
                    product('Mistral Small', 'Input Tokens', '0.001', provider='Mistral'),
                ]
            },
            {'PriceList': []},
        ]
    )
    install_clients(monkeypatch, pricing_client, bedrock_client)
    monkeypatch.setattr(source_aws, 'get_providers_yaml', lambda: {'aws': provider_yaml})

    source_aws.main()

    assert [model.id for model in provider_yaml.updated] == ['example.text-v1:0']
    assert [model.id for model in provider_yaml.added] == ['example.audio-v1:0', 'mistral.small-v1:0']
    assert provider_yaml.updated[0].prices == ModelPrice(
        input_mtok=Decimal('1'),
        output_mtok=Decimal('3'),
        cache_read_mtok=Decimal('0.2'),
        cache_write_mtok=Decimal('0.4'),
        cache_audio_read_mtok=Decimal('0.5'),
    )
    assert provider_yaml.added[0].prices == ModelPrice(input_audio_mtok=Decimal('2'), output_audio_mtok=Decimal('5'))
    assert provider_yaml.saved
    assert capsys.readouterr().out == '  2 models added\n  1 models updated\n'


def test_main_does_not_write_an_empty_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_yaml = FakeProviderYaml(set())
    install_clients(monkeypatch, FakePricingClient([]), FakeBedrockClient([]))
    monkeypatch.setattr(source_aws, 'get_providers_yaml', lambda: {'aws': provider_yaml})

    source_aws.main()

    assert not provider_yaml.saved


def test_main_updates_a_provider_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'aws.yml'
    provider_path.write_text(
        """\
id: aws
name: AWS
api_pattern: aws
models:
  - id: example.known-v1:0
    match:
      or:
        - contains: example.known-v1
    prices: {input_mtok: 9}
  - id: example.legacy-v1:0
    match:
      or:
        - contains: legacy-text
    prices:
      - prices: {input_mtok: 9}
  - id: example.text-v1:0
    match:
      contains: example.text-v1
    prices: {input_mtok: 9}
"""
    )
    provider_yaml = update.ProviderYaml(provider_path)
    models = [
        model_summary('example.known-v1:0', 'Known Model', 'Example'),
        model_summary('example.legacy-v1:0', 'Legacy Model', 'Example'),
        model_summary('example.text-v1:0', 'Text Model', 'Example'),
    ]
    prices = FakePricingClient(
        [
            {
                'PriceList': [
                    product('Known Model', 'Input Tokens', '0.001'),
                    product('Legacy Model', 'Input Tokens', '0.002'),
                    product('Text Model', 'Input Tokens', '0.003'),
                ]
            }
        ]
    )
    install_clients(monkeypatch, prices, FakeBedrockClient(models))
    monkeypatch.setattr(source_aws, 'get_providers_yaml', lambda: {'aws': provider_yaml})

    source_aws.main()

    saved = update.ProviderYaml(provider_path)
    model = saved.provider.models[2]
    assert model.name == 'Text Model'
    assert model.prices == ModelPrice(input_mtok=Decimal('3'))
    assert model.is_match('example.text-v1:0')


def test_main_adds_to_an_empty_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'aws.yml'
    provider_path.write_text('id: aws\nname: AWS\napi_pattern: aws\nmodels: []\n')
    provider_yaml = update.ProviderYaml(provider_path)
    models = [model_summary('example.text-v1:0', 'Text Model', 'Example')]
    prices = FakePricingClient([{'PriceList': [product('Text Model', 'Input Tokens', '0.001')]}])
    install_clients(monkeypatch, prices, FakeBedrockClient(models))
    monkeypatch.setattr(source_aws, 'get_providers_yaml', lambda: {'aws': provider_yaml})

    source_aws.main()

    assert [model.id for model in update.ProviderYaml(provider_path).provider.models] == ['example.text-v1:0']


def test_main_rejects_duplicate_model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    models = [
        model_summary('duplicate', 'One', 'Example'),
        model_summary('duplicate', 'Two', 'Example'),
    ]
    install_clients(monkeypatch, FakePricingClient([]), FakeBedrockClient(models))

    with pytest.raises(AssertionError, match='Duplicate model IDs found'):
        source_aws.main()


@pytest.mark.parametrize('inference_type', ['Other', 'Input Cache Tokens', 'Other Tokens'])
def test_main_rejects_unknown_inference_types(monkeypatch: pytest.MonkeyPatch, inference_type: str) -> None:
    models = [model_summary('example.text-v1:0', 'Text Model', 'Example')]
    prices = FakePricingClient([{'PriceList': [product('Text Model', inference_type, '0.001')]}])
    install_clients(monkeypatch, prices, FakeBedrockClient(models))

    with pytest.raises(AssertionError):
        source_aws.main()
