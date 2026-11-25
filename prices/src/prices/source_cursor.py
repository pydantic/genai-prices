from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml, UnreadableRowError, report_manual_update, skipping_unreadable_row
from prices.utils import package_dir

PRICING_URL = 'https://cursor.com/docs/models-and-pricing.md'
MIN_MODEL_COUNT = 6
LONG_CONTEXT_START = 256_000
PRICE_KEYS = ('input_mtok', 'cache_write_mtok', 'cache_read_mtok', 'output_mtok')
PRICE_CELL = re.compile(r'\$?\d+(?:\.\d+)?')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    section_match = re.search(r'^#+ Cursor Models\s*$\n(.*?)(?=^#|\Z)', markdown, flags=re.M | re.S | re.I)
    if section_match is None:
        return []

    rows: dict[str, tuple[str, list[Decimal | None]]] = {}
    duplicates: set[str] = set()
    unreadable: set[str] = set()
    for line in section_match.group(1).splitlines():
        with skipping_unreadable_row('Cursor', unreadable) as row:
            cells = line.split('|')
            if len(cells) < 8 or cells[2].strip() != 'Cursor':
                continue
            name = re.sub(r'\[([^]]+)]\([^)]*\)', r'\1', cells[1].strip()).replace(' (Fast)', ' Fast')
            model_id = name.lower().replace(' ', '-')
            row.model_ids.add(model_id)
            if model_id in rows:
                duplicates.add(model_id)
                continue
            values = [value.strip() for value in cells[3:7]]
            if unexpected := [value for value in values if value != '-' and not PRICE_CELL.fullmatch(value)]:
                raise UnreadableRowError(f'Unexpected Cursor price {unexpected[0]!r} in row: {line}')
            rows[model_id] = name, [None if value == '-' else Decimal(value.removeprefix('$')) for value in values]

    models: list[ModelInfo] = []
    for model_id, (name, prices) in rows.items():
        # "<model> 500k" rows are the rates for requests over 256k input tokens, not a separate model.
        if '-500k' in model_id:
            continue
        long_context_id = re.sub(r'(-fast)?$', r'-500k\1', model_id, count=1)
        if repeated := sorted({model_id, long_context_id} & duplicates):
            report_manual_update(
                f'Cursor: kept {model_id} unchanged, the pricing page lists {" and ".join(repeated)} more than once; '
                'update it by hand'
            )
            continue
        # A model with an unreadable row keeps its current prices, long-context tier included.
        if {model_id, long_context_id} & unreadable:
            continue
        long_context = rows.get(long_context_id)
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
    response = httpx2.get(PRICING_URL, timeout=30.0, follow_redirects=True)
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
