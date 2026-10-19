from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

CATALOG_URL = 'https://quicksilverpro.io/pricing.json'
MIN_MODEL_COUNT = 20

# Catalog rates are already USD per million tokens, so no conversion is needed.
PRICE_KEYS = {
    'input_per_1m': 'input_mtok',
    'cached_input_per_1m': 'cache_read_mtok',
    'cache_write_per_1m': 'cache_write_mtok',
    'output_per_1m': 'output_mtok',
    'output_image_per_1m': 'output_image_mtok',
}


def get_model_infos(models: list[dict[str, Any]]):
    """Extract model information from the QuickSilver Pro catalog (`pricing.json`)."""
    for model in models:
        # Image generation is billed per image, which the registry has no unit for.
        if model.get('pricing_unit') != 'tokens':
            continue

        prices = {
            price_key: Decimal(str(model[catalog_key]))
            for catalog_key, price_key in PRICE_KEYS.items()
            if model.get(catalog_key)
        }
        if not prices:
            continue

        yield ModelInfo(
            id=model['id'],
            name=model.get('name') or model['id'],
            match=ClauseEquals(equals=model['id']),
            context_window=model.get('context_tokens'),
            deprecated=True if model.get('lifecycle') == 'deprecated' else None,
            prices=ModelPrice(**prices),
            prices_checked=date.today(),
        )


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(CATALOG_URL, timeout=30.0)
    response.raise_for_status()
    models = list(get_model_infos(response.json()['models']))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/quicksilverpro.yml')
    added, updated = provider_yaml.upsert_models(models, source='QuickSilver Pro catalog', min_count=MIN_MODEL_COUNT)
    print(f'QuickSilver Pro prices updated: {added} added, {updated} updated')


def get_quicksilverpro_prices():  # pragma: no cover - thin CLI alias for main
    """Download and update QuickSilver Pro provider prices."""
    main()


if __name__ == '__main__':
    main()
