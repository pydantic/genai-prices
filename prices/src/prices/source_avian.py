from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

MODELS_URL = 'https://api.avian.io/v1/models'
MIN_MODEL_COUNT = 10


def parse_models(models: list[dict[str, Any]]) -> list[ModelInfo]:
    model_infos: list[ModelInfo] = []
    for model in models:
        pricing: dict[str, Any] = model.get('pricing') or {}
        prices = ModelPrice(
            input_mtok=_decimal(pricing.get('input_per_million')),
            cache_read_mtok=_decimal(pricing.get('cache_read_per_million')),
            output_mtok=_decimal(pricing.get('output_per_million')),
        )
        if prices.input_mtok is None and prices.output_mtok is None:
            continue
        model_infos.append(
            ModelInfo(
                id=model['id'],
                name=model.get('display_name'),
                match=ClauseEquals(equals=model['id']),
                context_window=model.get('context_length'),
                prices=prices,
                prices_checked=date.today(),
            )
        )
    return model_infos


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(MODELS_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_models(response.json()['data'])
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/avian.yml')
    added, updated = provider_yaml.upsert_models(models, source='Avian', min_count=MIN_MODEL_COUNT)
    print(f'Avian prices updated: {added} added, {updated} updated')


def get_avian_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Avian prices."""
    main()


def _decimal(value: float | None) -> Decimal | None:
    # str() first so 0.1275 stays 0.1275 instead of its binary float expansion
    return Decimal(str(value)) if value else None
