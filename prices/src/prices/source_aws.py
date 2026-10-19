from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

OFFER_URL = 'https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{offer}/current/us-east-1/index.json'
MIN_MODEL_COUNT = 50
UNIT_SCALES = {'1K tokens': Decimal(1000), '1M tokens': Decimal(1)}
SKIPPED_USAGE = re.compile(r'batch|flex|priority|latencyoptimized|longctx|image|video|custom')

# Price-list model name -> (Bedrock id billed at the us-east-1 rate, Bedrock id billed at the global cross-Region rate).
MODEL_IDS: dict[str, dict[str, tuple[str, str | None]]] = {
    'AmazonBedrock': {
        'Nova Lite': ('amazon.nova-lite-v1:0', None),
        'Nova Micro': ('amazon.nova-micro-v1:0', None),
        'Nova Premier': ('amazon.nova-premier-v1:0', None),
        'Nova Pro': ('amazon.nova-pro-v1:0', None),
        'Nova Sonic': ('amazon.nova-sonic-v1:0', None),
        'Nova Sonic 2.0': ('amazon.nova-2-sonic-v1:0', None),
        'Nova 2.0 Lite': ('us.amazon.nova-2-lite-v1:0', 'global.amazon.nova-2-lite-v1:0'),
        'Titan Embeddings G1 Text': ('amazon.titan-embed-text-v1', None),
        'TitanEmbeddingsV2-Text-input': ('amazon.titan-embed-text-v2:0', None),
        'Titan Text G1 Express': ('amazon.titan-text-express-v1', None),
        'Titan Text G1 Lite': ('amazon.titan-text-lite-v1', None),
        'R1': ('deepseek.r1-v1:0', None),
        'Gemma 3 4B': ('google.gemma-3-4b-it', None),
        'Gemma 3 12B': ('google.gemma-3-12b-it', None),
        'Gemma 3 27B': ('google.gemma-3-27b-it', None),
        'Llama 3 8B': ('meta.llama3-8b-instruct-v1:0', None),
        'Llama 3 70B': ('meta.llama3-70b-instruct-v1:0', None),
        'Llama 3.1 8B': ('meta.llama3-1-8b-instruct-v1:0', None),
        'Llama 3.1 70B': ('meta.llama3-1-70b-instruct-v1:0', None),
        'Llama 3.2 1B': ('meta.llama3-2-1b-instruct-v1:0', None),
        'Llama 3.2 3B': ('meta.llama3-2-3b-instruct-v1:0', None),
        'Llama 3.2 11B': ('meta.llama3-2-11b-instruct-v1:0', None),
        'Llama 3.2 90B': ('meta.llama3-2-90b-instruct-v1:0', None),
        'Llama 3.3 70B': ('meta.llama3-3-70b-instruct-v1:0', None),
        'Llama 4 Maverick 17B': ('meta.llama4-maverick-17b-instruct-v1:0', None),
        'Llama 4 Scout 17B': ('meta.llama4-scout-17b-instruct-v1:0', None),
        'Devstral': ('mistral.devstral-2-123b', None),
        'Magistral Small 1.2': ('mistral.magistral-small-2509', None),
        'Ministral 3B 3.0': ('mistral.ministral-3-3b-instruct', None),
        'Ministral 8B 3.0': ('mistral.ministral-3-8b-instruct', None),
        'Ministral 14B 3.0': ('mistral.ministral-3-14b-instruct', None),
        'Mistral 7B': ('mistral.mistral-7b-instruct-v0:2', None),
        'Mistral Large': ('mistral.mistral-large-2402-v1:0', None),
        'Mistral Large 3': ('mistral.mistral-large-3-675b-instruct', None),
        'Mistral Small': ('mistral.mistral-small-2402-v1:0', None),
        'Mixtral 8x7B': ('mistral.mixtral-8x7b-instruct-v0:1', None),
        'Pixtral Large 25.02': ('mistral.pixtral-large-2502-v1:0', None),
        'Voxtral Mini 1.0': ('mistral.voxtral-mini-3b-2507', None),
        'Voxtral Small 1.0': ('mistral.voxtral-small-24b-2507', None),
        'NVIDIA Nemotron Nano 2': ('nvidia.nemotron-nano-9b-v2:0', None),
        'Nemotron Nano 3 30B': ('nvidia.nemotron-nano-3-30b:0', None),
        'NVIDIA Nemotron 3 Super 120B A12B': ('nvidia.nemotron-super-3-120b:0', None),
        'gpt-oss-20b': ('openai.gpt-oss-20b-1:0', None),
        'gpt-oss-120b': ('openai.gpt-oss-120b-1:0', None),
        'Qwen3 32B': ('qwen.qwen3-32b-v1:0', None),
        'Qwen3 Coder 30B A3B': ('qwen.qwen3-coder-30b-a3b-v1:0', None),
        'Qwen3 Coder 480B A35B': ('qwen.qwen3-coder-480b-a35b-v1:0', None),
        'Qwen3 VL 235B A22B': ('qwen.qwen3-vl-235b-a22b-v1:0', None),
    },
    'AmazonBedrockFoundationModels': {
        'Claude 3 Haiku': ('anthropic.claude-3-haiku-20240307-v1:0', None),
        'Claude 3 Opus': ('anthropic.claude-3-opus-20240229-v1:0', None),
        'Claude 3 Sonnet': ('anthropic.claude-3-sonnet-20240229-v1:0', None),
        'Claude 3.5 Haiku': ('anthropic.claude-3-5-haiku-20241022-v1:0', None),
        'Claude 3.5 Sonnet': ('anthropic.claude-3-5-sonnet-20240620-v1:0', None),
        'Claude 3.5 Sonnet v2': ('anthropic.claude-3-5-sonnet-20241022-v2:0', None),
        'Claude 3.7 Sonnet': ('anthropic.claude-3-7-sonnet-20250219-v1:0', None),
        'Claude Opus 4': ('anthropic.claude-opus-4-20250514-v1:0', None),
        'Claude Opus 4.1': ('anthropic.claude-opus-4-1-20250805-v1:0', None),
        **{
            name: (model_id, f'global.{model_id}')
            for name, model_id in {
                'Claude Fable 5': 'anthropic.claude-fable-5-v1:0',
                'Claude Fable 5.1': 'anthropic.claude-fable-5-1-v1:0',
                'Claude Haiku 4.5': 'anthropic.claude-haiku-4-5-20251001-v1:0',
                'Claude Haiku 5.5': 'anthropic.claude-haiku-5-5',
                'Claude Opus 4.5': 'anthropic.claude-opus-4-5-v1:0',
                'Claude Opus 4.6': 'anthropic.claude-opus-4-6-v1:0',
                'Claude Opus 4.7': 'anthropic.claude-opus-4-7-v1:0',
                'Claude Opus 4.8': 'anthropic.claude-opus-4-8-v1:0',
                'Claude Opus 5': 'anthropic.claude-opus-5',
                'Claude Opus 5.5': 'anthropic.claude-opus-5-5',
                'Claude Sonnet 4': 'anthropic.claude-sonnet-4-20250514-v1:0',
                'Claude Sonnet 4.5': 'anthropic.claude-sonnet-4-5-20250929-v1:0',
                'Claude Sonnet 4.6': 'anthropic.claude-sonnet-4-6-v1:0',
                'Claude Sonnet 5': 'anthropic.claude-sonnet-5-v1:0',
                'Claude Sonnet 5.5': 'anthropic.claude-sonnet-5-5',
                'OpenAI GPT-6 Astra': 'openai.gpt-6-astra',
            }.items()
        },
        'Palmyra X4': ('writer.palmyra-x4-v1:0', None),
        'Palmyra X5': ('writer.palmyra-x5-v1:0', None),
    },
}


def parse_price_lists(offers: dict[str, dict[str, Any]]) -> list[ModelInfo]:
    rates: dict[str, dict[str, Decimal]] = {}
    for offer_code, model_ids in MODEL_IDS.items():
        offer = offers[offer_code]
        for sku, terms in offer['terms']['OnDemand'].items():
            attributes: dict[str, str] = offer['products'][sku]['attributes']
            ids = model_ids.get(attributes.get('model') or attributes.get('titanModel') or '')
            if ids is None:
                continue
            usage = re.sub(r'[^a-z0-9]', '', re.sub(r'^USE1-(MP:USE1_)?', '', attributes['usagetype']).lower())
            model_id = ids[1] if 'global' in usage else ids[0]
            for term in terms.values():
                for dimension in term['priceDimensions'].values():
                    scale = UNIT_SCALES.get(dimension['unit'].replace('1k', '1K'))
                    price = Decimal(dimension['pricePerUnit']['USD'])
                    if model_id is None or scale is None or not price or SKIPPED_USAGE.search(usage):
                        continue
                    key = _price_key(usage)
                    price = (price * scale).normalize()
                    model_rates = rates.setdefault(model_id, {})
                    if model_rates.setdefault(key, price) != price:
                        raise RuntimeError(f'AWS price list has conflicting {key} rates for {model_id}')
    return [
        ModelInfo(
            id=model_id,
            match=ClauseEquals(equals=model_id),
            prices=ModelPrice(**model_rates),
            prices_checked=date.today(),
        )
        for model_id, model_rates in rates.items()
    ]


def main(provider_path: Path | None = None) -> None:
    offers: dict[str, dict[str, Any]] = {}
    for offer_code in MODEL_IDS:
        response = httpx2.get(OFFER_URL.format(offer=offer_code), timeout=30.0)
        response.raise_for_status()
        offers[offer_code] = response.json()
    models = parse_price_lists(offers)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/aws.yml')
    added, updated = provider_yaml.upsert_models(models, source='AWS', min_count=MIN_MODEL_COUNT)
    print(f'AWS prices updated: {added} added, {updated} updated')


def get_aws_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update AWS Bedrock prices."""
    main()


def _price_key(usage: str) -> str:
    if 'cacheread' in usage:
        return 'cache_read_mtok'
    if 'cachewrite' in usage:
        return 'cache_write_1h_mtok' if '1h' in usage else 'cache_write_mtok'
    if 'speechinput' in usage or 'inputaudio' in usage:
        return 'input_audio_mtok'
    if 'speechoutput' in usage or 'outputaudio' in usage:
        return 'output_audio_mtok'
    if 'input' in usage:
        return 'input_mtok'
    if 'output' in usage:
        return 'output_mtok'
    raise RuntimeError(f'Unrecognised AWS token usage type {usage!r}')
