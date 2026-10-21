from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import get_markdown, markdown_tables, package_dir

PRICING_URL = 'https://developers.openai.com/api/docs/pricing.md'
MIN_MODEL_COUNT = 30
CONTEXT_TIER_HEADER = [
    'Model',
    'Short context input',
    'Short context cached input',
    'Short context cache writes',
    'Short context output',
    'Long context input',
    'Long context cached input',
    'Long context cache writes',
    'Long context output',
]
SPECIALIZED_HEADER = ['Category', 'Model', 'Input', 'Cached input', 'Output']
FLAT_HEADER = ['Model', 'Input', 'Cached input', 'Output']
NON_STANDARD_TABS = {'Batch', 'Flex', 'Fast', 'Ultrafast', 'Priority'}
KEYS = ('input_mtok', 'cache_read_mtok', 'cache_write_mtok', 'output_mtok')
# Long context starts above 272K input tokens; the engines select a tier when the count is greater than `start`.
LONG_CONTEXT_START = 272_000
MODEL_CELL = re.compile(r'(?P<id>[\w.-]+)(?: \(<272K context length\))?')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    """Parse the standard-tier text token rates; batch, flex and fast tabs and non-text units stay curated."""
    rates: dict[str, ModelPrice] = {}
    for header, rows in _standard_tables(markdown):
        for row in rows:
            if header == CONTEXT_TIER_HEADER:
                model_cell, prices = row[0], ModelPrice.model_validate(_context_tier_prices(row))
            else:
                model_cell, cells = (row[1], row[2:]) if header == SPECIALIZED_HEADER else (row[0], row[1:])
                if cells[0] == 'Free':
                    continue
                prices = ModelPrice.model_validate(
                    {
                        key: _dollars(cell, row)
                        for key, cell in zip(('input_mtok', 'cache_read_mtok', 'output_mtok'), cells)
                    }
                )
            if not (match := MODEL_CELL.fullmatch(model_cell)):
                raise RuntimeError(f'Unexpected OpenAI pricing row: {row}')
            if rates.setdefault(match['id'], prices) != prices:
                raise RuntimeError(f'OpenAI pricing page lists {match["id"]} at conflicting standard rates')
    if not rates:
        raise RuntimeError('OpenAI pricing page has no standard text pricing table')
    return [
        ModelInfo(
            id=model_id,
            match=ClauseEquals(equals=model_id),
            prices=prices,
            prices_checked=date.today(),
        )
        for model_id, prices in rates.items()
    ]


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/openai.yml')
    added, updated = provider_yaml.upsert_models(models, source='OpenAI', min_count=MIN_MODEL_COUNT)
    print(f'OpenAI prices updated: {added} added, {updated} updated')


def get_openai_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update OpenAI prices."""
    main()


def _standard_tables(markdown: str) -> list[tuple[list[str], list[list[str]]]]:
    """Yield the text tables outside a Batch, Flex or Fast tab; the tab label is the line before each heading."""
    sections = re.split(r'^### .*$', markdown, flags=re.MULTILINE)
    tables: list[tuple[list[str], list[list[str]]]] = []
    for before, section in zip(sections, sections[1:]):
        tab = next((line.strip() for line in reversed(before.splitlines()) if line.strip()), '')
        if tab in NON_STANDARD_TABS:
            continue
        tables += [
            (header, rows)
            for header, rows in markdown_tables(section)
            if header in (CONTEXT_TIER_HEADER, SPECIALIZED_HEADER, FLAT_HEADER)
        ]
    return tables


def _context_tier_prices(row: list[str]) -> dict[str, Decimal | TieredPrices]:
    short = [_dollars(cell, row) for cell in row[1:5]]
    long = [_dollars(cell, row) for cell in row[5:9]]
    has_long_context = any(price is not None for price in long)
    prices: dict[str, Decimal | TieredPrices] = {}
    for key, base, tier in zip(KEYS, short, long):
        if base is None and tier is None:
            continue
        if base is None or (has_long_context and tier is None):
            raise RuntimeError(f'OpenAI pricing row has a short or long context rate without its pair: {row}')
        prices[key] = (
            TieredPrices(base=base, tiers=[Tier(start=LONG_CONTEXT_START, price=tier)]) if tier is not None else base
        )
    return prices


def _dollars(cell: str, row: list[str]) -> Decimal | None:
    if cell == '-':
        return None
    if not (match := re.fullmatch(r'\$(\d+(?:\.\d+)?)', cell)):
        raise RuntimeError(f'Unexpected OpenAI price {cell!r} in row: {row}')
    return Decimal(match[1])
