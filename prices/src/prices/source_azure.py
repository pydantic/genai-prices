from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICES_URL = 'https://prices.azure.com/api/retail/prices'
REGION = 'eastus'
MIN_MODEL_COUNT = 10
UNIT_SCALES = {'1K': Decimal(1000), '1M': Decimal(1)}
# OpenAI models use the Global deployment meters, which the YAML's base rates represent; Phi models are serverless.
METERS: dict[str, dict[str, str]] = {
    'ada': {'input_mtok': 'embedding-ada-glbl Tokens'},
    'o1': {
        'input_mtok': 'o1 1217 Inp glbl Tokens',
        'cache_read_mtok': 'o1 1217 cached Inp glbl Tokens',
        'output_mtok': 'o1 1217 Outp glbl Tokens',
    },
    'o1-mini': {
        'input_mtok': 'o1 mini input glbl Tokens',
        'cache_read_mtok': 'o1 mini cached input glbl Tokens',
        'output_mtok': 'o1 mini output glbl Tokens',
    },
    'o3-2025-04-16': {
        'input_mtok': 'o3 0416 Inp glbl Tokens',
        'cache_read_mtok': 'o3 0416 cached Inp glbl Tokens',
        'output_mtok': 'o3 0416 Outp glbl Tokens',
    },
    'o3-mini': {
        'input_mtok': 'o3 mini 0131 input glbl Tokens',
        'cache_read_mtok': 'o3 mini 0131 cached input glbl Tokens',
        'output_mtok': 'o3 mini 0131 output glbl Tokens',
    },
    'o4-mini': {
        'input_mtok': 'o4-mini 0416 Inp glbl Tokens',
        'cache_read_mtok': 'o4-mini 0416 cached Inp glbl Tokens',
        'output_mtok': 'o4-mini 0416 Outp glbl Tokens',
    },
    'phi-3-medium-128k-instruct': {
        'input_mtok': 'Phi-3-Medium-128K-Instruct-Input Tokens',
        'output_mtok': 'Phi-3-Medium-128K-Instruct-Output Tokens',
    },
    'phi-3-mini-128k-instruct': {
        'input_mtok': 'Phi-3-Mini-128K-Instruct-Input Tokens',
        'output_mtok': 'Phi-3-Mini-128K-Instruct-Output Tokens',
    },
    'phi-3.5-mini-128k-instruct': {
        'input_mtok': 'Phi-3.5-Mini-128K-Instruct-Input Tokens',
        'output_mtok': 'Phi-3.5-Mini-128K-Instruct-Output Tokens',
    },
    'phi-4': {'input_mtok': 'Phi-4-Input Tokens', 'output_mtok': 'Phi-4-Output Tokens'},
    'phi-4-mini-instruct': {'input_mtok': 'Phi-4-Mini-Input Tokens', 'output_mtok': 'Phi-4-Mini-Output Tokens'},
    'phi-4-multimodal-instruct': {
        'input_mtok': 'Phi-4-Mini MM-Input Tokens',
        'input_audio_mtok': 'Phi-4-Mini MM-Audio-In Tokens',
        'output_mtok': 'Phi-4-Mini MM-Output Tokens',
    },
    'phi-4-reasoning-plus': {
        'input_mtok': 'Phi-4-reasoning-plus-input Tokens',
        'output_mtok': 'Phi-4-reasoning-plus-output Tokens',
    },
    'text-embedding-3-large': {'input_mtok': 'text-embedding-3-large-glbl Tokens'},
    'text-embedding-3-small': {'input_mtok': 'text-embedding-3-small-glbl Tokens'},
}


def parse_retail_prices(items: list[dict[str, Any]]) -> list[ModelInfo]:
    per_mtok: dict[str, Decimal] = {}
    for item in items:
        meter = item['meterName']
        if meter in per_mtok:
            raise RuntimeError(f'Azure retail prices list meter {meter!r} more than once')
        if (scale := UNIT_SCALES.get(item['unitOfMeasure'])) is None:
            raise RuntimeError(f'Unexpected Azure unit {item["unitOfMeasure"]!r} for meter {meter!r}')
        rate = Decimal(str(item['retailPrice'])) * scale
        per_mtok[meter] = rate.quantize(Decimal(1)) if rate == rate.to_integral_value() else rate.normalize()

    models: list[ModelInfo] = []
    for model_id, meters in METERS.items():
        if missing := [meter for meter in meters.values() if meter not in per_mtok]:
            raise RuntimeError(f'Azure retail prices have no meter {missing[0]!r} for {model_id}')
        models.append(
            ModelInfo(
                id=model_id,
                match=ClauseEquals(equals=model_id),
                prices=ModelPrice(**{key: per_mtok[meter] for key, meter in meters.items()}),
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    items: list[dict[str, Any]] = []
    meters = [meter for model_meters in METERS.values() for meter in model_meters.values()]
    # The API rejects a filter with more than about 20 clauses, and rate-limits one query per model.
    for start in range(0, len(meters), 15):
        meter_filter = ' or '.join(f"meterName eq '{meter}'" for meter in meters[start : start + 15])
        url: str | None = PRICES_URL
        params: dict[str, str] | None = {
            '$filter': f"serviceName eq 'Foundry Models' and armRegionName eq '{REGION}' "
            f"and type eq 'Consumption' and ({meter_filter})"
        }
        while url:
            response = httpx2.get(url, params=params, timeout=30.0)
            response.raise_for_status()
            page = response.json()
            items += page['Items']
            url, params = page.get('NextPageLink'), None
    models = parse_retail_prices(items)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/azure.yml')
    added, updated = provider_yaml.upsert_models(models, source='Azure', min_count=MIN_MODEL_COUNT)
    print(f'Azure prices updated: {added} added, {updated} updated')


def get_azure_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Microsoft Azure prices."""
    main()
