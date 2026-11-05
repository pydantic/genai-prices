from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

from pydantic import ValidationError

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, PriceVariant, Tier, TieredPrices
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
# The request context each non-standard tab prices. Fast is the current name of Priority, and both values are accepted.
NON_STANDARD_TABS: dict[str, list[dict[str, str]]] = {
    'Batch': [{'processing': 'batch'}],
    'Flex': [{'service_tier': 'flex'}],
    'Fast': [{'service_tier': 'fast'}, {'service_tier': 'priority'}],
    'Priority': [{'service_tier': 'priority'}],
    'Ultrafast': [{'service_tier': 'ultrafast'}],
}
# Long context starts above 272K input tokens; the engines select a tier when the count is greater than `start`.
LONG_CONTEXT_START = 272_000
MODEL_CELL = re.compile(r'(?P<id>[\w.-]+)(?: \(<272K context length\))?')
# Whether a price column is a long context rate, and its price key (`None` for a column that isn't modeled).
Column = tuple[bool, str | None]


class TextTable(NamedTuple):
    tab: str
    model_column: int
    columns: list[Column]
    rows: list[list[str]]


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    """Parse the standard-tier text token rates, skipping the non-standard tabs; non-text units stay curated."""
    rates: dict[str, ModelPrice] = {}
    for tab, model_column, columns, rows in _text_tables(markdown):
        if tab in NON_STANDARD_TABS:
            continue
        for row in rows:
            parsed = _row_rates(model_column, columns, row)
            if parsed is None:
                continue
            model_id, prices = parsed
            if rates.setdefault(model_id, prices) != prices:
                raise RuntimeError(f'OpenAI pricing page lists {model_id} at conflicting standard rates')
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


def parse_price_variants(markdown: str) -> dict[str, list[PriceVariant]]:
    """Parse each model's text token rates on the non-standard tabs; unreadable rows and tables are logged and skipped."""
    variants: dict[str, list[PriceVariant]] = {}
    for tab, model_column, columns, rows in _text_tables(markdown):
        if tab not in NON_STANDARD_TABS:
            continue
        for row in rows:
            try:
                parsed = _row_rates(model_column, columns, row)
            except (RuntimeError, ValidationError):
                print(f'OpenAI: skipped an unreadable {tab} row; update them by hand: {row}')
                continue
            if parsed is None:
                continue
            model_id, prices = parsed
            # An all-dash row has no rates, and an empty variant would claim the tier costs the standard rate.
            if prices != ModelPrice():
                variants.setdefault(model_id, []).extend(
                    PriceVariant(when=when, prices=prices) for when in NON_STANDARD_TABS[tab]
                )
    return variants


def main(provider_path: Path | None = None) -> None:
    markdown = get_markdown(PRICING_URL)
    models = parse_pricing_markdown(markdown)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/openai.yml')
    added, updated = provider_yaml.upsert_models(models, source='OpenAI', min_count=MIN_MODEL_COUNT)
    provider_yaml.add_missing_price_variants(parse_price_variants(markdown), start=date.today())
    print(f'OpenAI prices updated: {added} added, {updated} updated')


def get_openai_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update OpenAI prices."""
    main()


def _text_tables(markdown: str) -> list[TextTable]:
    """Yield each text table with its tab: the line before a `###` heading, or a `####` heading naming another tab."""
    parts = re.split(r'^(#{3,4} .*)$', markdown, flags=re.MULTILINE)
    tables: list[TextTable] = []
    tab = ''
    for before, heading, section in zip(parts[::2], parts[1::2], parts[2::2]):
        if not heading.startswith('####'):
            tab = next((line.strip() for line in reversed(before.splitlines()) if line.strip()), '')
        elif (subheading := heading.removeprefix('####').strip()) in NON_STANDARD_TABS:
            tab = subheading
        try:
            section_tables = markdown_tables(section)
        except ValueError as error:
            if tab not in NON_STANDARD_TABS:
                raise
            # A malformed tier table must not hold back the standard rates.
            print(f'OpenAI: skipped an unreadable {tab} table; update them by hand: {error}')
            continue
        for header, rows in section_tables:
            if 'Model' in header[:2] and (columns := _columns(header[header.index('Model') + 1 :])):
                tables.append(TextTable(tab, header.index('Model'), columns, rows))
    return tables


def _row_rates(model_column: int, columns: list[Column], row: list[str]) -> tuple[str, ModelPrice] | None:
    """A table row's model id and rates, or `None` for a free row."""
    model_cell, cells = row[model_column], row[model_column + 1 :]
    if cells[0] == 'Free':
        return None
    prices = ModelPrice.model_validate(_prices(columns, cells, row))
    if not (match := MODEL_CELL.fullmatch(model_cell)):
        raise RuntimeError(f'Unexpected OpenAI pricing row: {row}')
    return match['id'], prices


def _columns(names: list[str]) -> list[Column] | None:
    """Map each column to whether it is a long context rate and its price key; `None` if any column is unknown."""
    columns: list[Column] = []
    for name in names:
        key = name.removeprefix('Short context ').removeprefix('Long context ').lower()
        if key not in COLUMN_KEYS:
            return None
        columns.append((name.startswith('Long context '), COLUMN_KEYS[key]))
    return columns


def _prices(columns: list[Column], cells: list[str], row: list[str]) -> dict[str, Decimal | TieredPrices]:
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
