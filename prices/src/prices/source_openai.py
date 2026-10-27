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
# Price columns by name, without their `Short context`/`Long context` prefix.
COLUMN_KEYS: dict[str, str | None] = {
    'input': 'input_mtok',
    'cached input': 'cache_read_mtok',
    '30m write': 'cache_write_mtok',
    # The 12-hour cache retention rate isn't modeled; cache writes use the 30-minute rate.
    '12h write': None,
    'output': 'output_mtok',
}
NON_STANDARD_TABS = {'Batch', 'Flex', 'Fast', 'Ultrafast', 'Priority'}
# Long context starts above 272K input tokens; the engines select a tier when the count is greater than `start`.
LONG_CONTEXT_START = 272_000
MODEL_CELL = re.compile(r'(?P<id>[\w.-]+)(?: \(<272K context length\))?')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    """Parse the standard-tier text token rates; batch, flex and fast tabs and non-text units stay curated."""
    rates: dict[str, ModelPrice] = {}
    for model_column, columns, rows in _standard_tables(markdown):
        for row in rows:
            model_cell, cells = row[model_column], row[model_column + 1 :]
            if cells[0] == 'Free':
                continue
            prices = ModelPrice.model_validate(_prices(columns, cells, row))
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


def _standard_tables(markdown: str) -> list[tuple[int, list[tuple[bool, str | None]], list[list[str]]]]:
    """Yield the text tables outside a Batch, Flex or Fast tab; the tab label is the line before each heading."""
    sections = re.split(r'^### .*$', markdown, flags=re.MULTILINE)
    tables: list[tuple[int, list[tuple[bool, str | None]], list[list[str]]]] = []
    for before, section in zip(sections, sections[1:]):
        tab = next((line.strip() for line in reversed(before.splitlines()) if line.strip()), '')
        if tab in NON_STANDARD_TABS:
            continue
        for header, rows in markdown_tables(section):
            if 'Model' in header[:2] and (columns := _columns(header[header.index('Model') + 1 :])):
                tables.append((header.index('Model'), columns, rows))
    return tables


def _columns(names: list[str]) -> list[tuple[bool, str | None]] | None:
    """Map each column to whether it is a long context rate and its price key; `None` if any column is unknown."""
    columns: list[tuple[bool, str | None]] = []
    for name in names:
        key = name.removeprefix('Short context ').removeprefix('Long context ').lower()
        if key not in COLUMN_KEYS:
            return None
        columns.append((name.startswith('Long context '), COLUMN_KEYS[key]))
    return columns


def _prices(
    columns: list[tuple[bool, str | None]], cells: list[str], row: list[str]
) -> dict[str, Decimal | TieredPrices]:
    short: dict[str, Decimal] = {}
    long: dict[str, Decimal] = {}
    for (is_long, key), cell in zip(columns, cells):
        if key and (price := _dollars(cell, row)) is not None:
            (long if is_long else short)[key] = price
    if long and short.keys() != long.keys():
        raise RuntimeError(f'OpenAI pricing row has a short or long context rate without its pair: {row}')
    return {
        key: TieredPrices(base=base, tiers=[Tier(start=LONG_CONTEXT_START, price=long[key])]) if long else base
        for key, base in short.items()
    }


def _dollars(cell: str, row: list[str]) -> Decimal | None:
    if cell == '-':
        return None
    if not (match := re.fullmatch(r'\$(\d+(?:\.\d+)?)', cell)):
        raise RuntimeError(f'Unexpected OpenAI price {cell!r} in row: {row}')
    return Decimal(match[1])
