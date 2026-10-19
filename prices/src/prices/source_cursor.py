from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_URL = 'https://cursor.com/docs/models-and-pricing.md'
MIN_MODEL_COUNT = 6
LONG_CONTEXT_START = 256_000
PRICE_KEYS = ('input_mtok', 'cache_write_mtok', 'cache_read_mtok', 'output_mtok')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    section_match = re.search(r'^#+ Cursor Models\s*$\n(.*?)(?=^#|\Z)', markdown, flags=re.M | re.S | re.I)
    if section_match is None:
        return []

    rows: dict[str, tuple[str, list[Decimal | None]]] = {}
    for line in section_match.group(1).splitlines():
        cells = line.split('|')
        if len(cells) < 8 or cells[2].strip() != 'Cursor':
            continue
        name = re.sub(r'\[([^]]+)]\([^)]*\)', r'\1', cells[1].strip()).replace(' (Fast)', ' Fast')
        model_id = name.lower().replace(' ', '-')
        if model_id in rows:
            raise RuntimeError(f'Duplicate Cursor model in pricing data: {model_id}')
        prices = [None if value.strip() == '-' else Decimal(value.strip().removeprefix('$')) for value in cells[3:7]]
        rows[model_id] = name, prices

    models: list[ModelInfo] = []
    for model_id, (name, prices) in rows.items():
        # "<model> 500k" rows are the rates for requests over 256k input tokens, not a separate model.
        if '-500k' in model_id:
            continue
        long_context = rows.get(re.sub(r'(-fast)?$', r'-500k\1', model_id, count=1))
        tiered: list[Decimal | TieredPrices | None] = list(prices)
        if long_context is not None:
            tiered = [
                TieredPrices(base=base, tiers=[Tier(start=LONG_CONTEXT_START, price=tier)])
                if base is not None and tier is not None
                else base
                for base, tier in zip(prices, long_context[1])
            ]
        models.append(
            ModelInfo(
                id=model_id,
                name=name,
                match=ClauseEquals(equals=model_id),
                prices=ModelPrice(**dict(zip(PRICE_KEYS, tiered))),
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(PRICING_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_pricing_markdown(response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/cursor.yml')
    models_added, models_updated = provider_yaml.upsert_models(
        models, source='Cursor pricing', min_count=MIN_MODEL_COUNT
    )
    print(f'Cursor prices updated: {models_added} added, {models_updated} updated')


def get_cursor_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Cursor model prices."""
    main()


if __name__ == '__main__':
    main()
