from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2
from pydantic import BaseModel, ConfigDict, Field

from prices.prices_types import ModelInfo, Tier, TieredPrices
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


class LongContext(BaseModel):
    model_config = ConfigDict(extra='forbid')

    prompt_tokens_over: int = Field(strict=True, gt=0)
    input_per_1m: Decimal = Field(ge=0)
    output_per_1m: Decimal = Field(ge=0)
    cache_read_per_1m: Decimal | None = Field(default=None, ge=0)
    cache_write_per_1m: Decimal | None = Field(default=None, ge=0)


def get_model_infos(models: list[dict[str, object]]):
    """Extract model information from the QuickSilver Pro catalog (`pricing.json`)."""
    for model in models:
        # Image generation is billed per image, which the registry has no unit for.
        if model.get('pricing_unit') != 'tokens':
            continue

        prices: dict[str, Decimal | TieredPrices] = {
            price_key: Decimal(str(model[catalog_key]))
            for catalog_key, price_key in PRICE_KEYS.items()
            if model.get(catalog_key)
        }
        if not prices:
            continue
        if model.get('long_context') is not None:
            tier = LongContext.model_validate(model['long_context'])
            for price_key, rate in {
                'input_mtok': tier.input_per_1m,
                'output_mtok': tier.output_per_1m,
                'cache_read_mtok': tier.cache_read_per_1m,
                'cache_write_mtok': tier.cache_write_per_1m,
            }.items():
                if rate is None:
                    continue
                base = prices.get(price_key)
                if not isinstance(base, Decimal):
                    raise ValueError(f'{model["id"]}: long_context {price_key} has no base rate')
                prices[price_key] = TieredPrices(base=base, tiers=[Tier(start=tier.prompt_tokens_over, price=rate)])

        yield ModelInfo.model_validate(
            {
                'id': model['id'],
                'name': model.get('name') or model['id'],
                'match': {'equals': model['id']},
                'context_window': model.get('context_tokens'),
                'deprecated': True if model.get('lifecycle') == 'deprecated' else None,
                'prices': prices,
                'prices_checked': date.today(),
            }
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
