from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

MODELS_URL = 'https://api.cerebras.ai/public/v1/models'
MIN_MODEL_COUNT = 1


def parse_models(models: list[dict[str, Any]]) -> list[ModelInfo]:
    model_infos: list[ModelInfo] = []
    for model in models:
        pricing: dict[str, Any] = model.get('pricing') or {}
        input_mtok = _per_mtok(pricing.get('prompt'))
        output_mtok = _per_mtok(pricing.get('completion'))
        if input_mtok is None and output_mtok is None:
            continue
        model_infos.append(
            ModelInfo(
                id=model['id'],
                name=model.get('name'),
                match=ClauseEquals(equals=model['id']),
                context_window=model.get('limits', {}).get('max_context_length'),
                prices=ModelPrice(input_mtok=input_mtok, output_mtok=output_mtok),
                prices_checked=date.today(),
            )
        )
    return model_infos


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(MODELS_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_models(response.json()['data'])
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/cerebras.yml')
    added, updated = provider_yaml.upsert_models(models, source='Cerebras', min_count=MIN_MODEL_COUNT)
    print(f'Cerebras prices updated: {added} added, {updated} updated')


def get_cerebras_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Cerebras prices."""
    main()


def _per_mtok(per_token: str | None) -> Decimal | None:
    if not per_token or Decimal(per_token) == 0:
        return None
    return (Decimal(per_token) * 1_000_000).normalize()
