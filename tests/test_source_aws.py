from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from shutil import copyfile
from typing import Any

import pytest
from cassetter.cassette import RawResponse

from prices import source_aws
from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.utils import package_dir


def keep_priced_models(response: RawResponse) -> RawResponse:  # pragma: no cover - runs only when recording
    offer = json.loads(response.body or b'')
    model_ids = source_aws.MODEL_IDS[offer['offerCode']]
    terms = offer['terms']['OnDemand']
    offer['products'] = {
        sku: product
        for sku, product in offer['products'].items()
        if (product['attributes'].get('model') or product['attributes'].get('titanModel')) in model_ids
        and not source_aws.SKIPPED_USAGE.search(product['attributes']['usagetype'].lower().replace('_', ''))
        and any(
            dimension['unit'] in ('1K tokens', '1k tokens', '1M tokens')
            for term in terms.get(sku, {}).values()
            for dimension in term['priceDimensions'].values()
        )
    }
    offer['terms'] = {'OnDemand': {sku: terms[sku] for sku in offer['products']}}
    response.body = json.dumps(offer).encode()
    response.headers.pop('content-length', None)
    response.headers.pop('Content-Length', None)
    return response


@pytest.fixture(scope='module')
def vcr_config() -> dict[str, Any]:
    return {'before_record_response': keep_priced_models}


def offer(code: str, *rows: tuple[str, str, str, str]) -> dict[str, Any]:
    products: dict[str, Any] = {}
    terms: dict[str, Any] = {}
    for index, (model, usage_type, unit, usd) in enumerate(rows):
        sku = f'SKU{index}'
        products[sku] = {'sku': sku, 'attributes': {'model': model, 'usagetype': usage_type}}
        dimension = {'unit': unit, 'pricePerUnit': {'USD': usd}}
        terms[sku] = {f'{sku}.TERM': {'priceDimensions': {f'{sku}.TERM.RATE': dimension}}}
    return {'offerCode': code, 'products': products, 'terms': {'OnDemand': terms}}


def offers(
    bedrock: list[tuple[str, str, str, str]], foundation_models: list[tuple[str, str, str, str]]
) -> dict[str, dict[str, Any]]:
    return {
        'AmazonBedrock': offer('AmazonBedrock', *bedrock),
        'AmazonBedrockFoundationModels': offer('AmazonBedrockFoundationModels', *foundation_models),
    }


def model(model_id: str, **prices: str) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        match=ClauseEquals(equals=model_id),
        prices=ModelPrice(**{key: Decimal(value) for key, value in prices.items()}),
        prices_checked=date.today(),
    )


def test_aws_splits_in_region_and_global_rates_per_model() -> None:
    models = source_aws.parse_price_lists(
        offers(
            [
                ('Nova 2.0 Lite', 'USE1-Nova2.0Lite-input-tokens', '1K tokens', '0.00033'),
                ('Nova 2.0 Lite', 'USE1-Nova2.0Lite-input-tokens-cross-region-global', '1K tokens', '0.0003'),
                ('Nova 2.0 Lite', 'USE1-Nova2.0Lite-input-tokens-custom-model', '1K tokens', '0.0003'),
                ('Nova 2.0 Lite', 'USE1-Nova2.0Lite-cache-write-input-token-count', '1K tokens', '0'),
                ('Nova 2.0 Lite', 'USE1-Nova2.0Lite-ProvisionedThroughput-NoCommit-ModelUnits', 'hour', '60.5'),
                ('Nova Sonic', 'USE1-NovaSonic-speech-input-tokens', '1K tokens', '0.0034'),
                ('Nova Sonic', 'USE1-NovaSonic-speech-output-tokens', '1k tokens', '0.0136'),
                ('Nova Sonic', 'USE1-NovaSonic-text-output-tokens', '1K tokens', '0.00024'),
                ('Gemma 3 4B', 'USE1-Gemma-3-4B-IT-output-tokens', '1K tokens', '0.00008'),
                ('Gemma 3 4B', 'USE1-google.gemma-3-4b-it-mantle-output-tokens-standard', '1K tokens', '0.00008'),
                ('Gemma 3 4B', 'USE1-Gemma-3-4B-IT-output-tokens-batch', '1K tokens', '0.00004'),
                ('Kimi K3', 'USE1-moonshotai.kimi-k3-mantle-input-tokens-standard', '1K tokens', '0.0033'),
            ],
            [
                ('Claude Opus 4.1', 'USE1-MP:USE1_InputTokenCount_Global-Units', '1M tokens', '15'),
                ('Claude Haiku 4.5', 'USE1-MP:USE1_CacheWrite1hInputTokenCount_Global-Units', '1M tokens', '2'),
                ('Claude Haiku 4.5', 'USE1-MP:USE1_CacheWriteInputTokenCount-Units', '1M tokens', '1.375'),
                ('Claude Haiku 4.5', 'USE1-MP:USE1_CacheReadInputTokenCount-Units', '1M tokens', '0.11'),
                ('Claude Haiku 5.5', 'USE1-MP:USE1_input_tokens_standard-Units', '1M tokens', '0.11'),
                ('Claude Haiku 5.5', 'USE1-MP:USE1_input_tokens_long_ctx_standard-Units', '1M tokens', '0.55'),
                ('Claude Haiku 5.5', 'USE1-MP:USE1_output_tokens_global_flex-Units', '1M tokens', '0.25'),
                ('Claude Haiku 5.5', 'USE1-MP:USE1_cache_write_tokens_1h_global_standard-Units', '1M tokens', '0.2'),
            ],
        )
    )

    assert models == [
        model('us.amazon.nova-2-lite-v1:0', input_mtok='0.33'),
        model('global.amazon.nova-2-lite-v1:0', input_mtok='0.3'),
        model('amazon.nova-sonic-v1:0', input_audio_mtok='3.4', output_audio_mtok='13.6', output_mtok='0.24'),
        model('google.gemma-3-4b-it', output_mtok='0.08'),
        model('global.anthropic.claude-haiku-4-5-20251001-v1:0', cache_write_1h_mtok='2'),
        model('anthropic.claude-haiku-4-5-20251001-v1:0', cache_write_mtok='1.375', cache_read_mtok='0.11'),
        model('anthropic.claude-haiku-5-5', input_mtok='0.11'),
        model('global.anthropic.claude-haiku-5-5', cache_write_1h_mtok='0.2'),
    ]


def test_aws_rejects_conflicting_rates() -> None:
    rows = [
        ('Llama 3 8B', 'USE1-Llama3-8B-input-tokens', '1K tokens', '0.0003'),
        ('Llama 3 8B', 'USE1-meta.llama3-8b-instruct-mantle-input-tokens-standard', '1K tokens', '0.0004'),
    ]
    with pytest.raises(RuntimeError, match='conflicting input_mtok rates for meta.llama3-8b-instruct-v1:0'):
        source_aws.parse_price_lists(offers(rows, []))


def test_aws_rejects_an_unrecognised_token_usage_type() -> None:
    rows = [('Llama 3 8B', 'USE1-Llama3-8B-thinking-tokens', '1K tokens', '0.0003')]
    with pytest.raises(RuntimeError, match="Unrecognised AWS token usage type 'llama38bthinkingtokens'"):
        source_aws.parse_price_lists(offers(rows, []))


@pytest.mark.vcr()
def test_aws_main_fetches_recorded_price_lists(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'aws.yml'
    copyfile(package_dir / 'providers/aws.yml', provider_path)

    source_aws.main(provider_path)

    assert capsys.readouterr().out == 'AWS prices updated: 0 added, 92 updated\n'
