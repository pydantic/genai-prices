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
    """Parse each model's standard text token rates and its rates on the other tabs; non-text units stay curated."""
    rates: dict[str, ModelPrice] = {}
    variants: dict[str, list[PriceVariant]] = {}
    for tab, model_column, columns, rows in _text_tables(markdown):
        for row in rows:
            try:
                parsed = _row_rates(model_column, columns, row)
            except (RuntimeError, ValidationError):
                if tab not in NON_STANDARD_TABS:
                    raise
                # An unreadable tier row must not hold back the standard rates.
                print(f'OpenAI: skipped an unreadable {tab} row; update them by hand: {row}')
                continue
            if parsed is None:
                continue
            model_id, prices = parsed
            if tab not in NON_STANDARD_TABS:
                if rates.setdefault(model_id, prices) != prices:
                    raise RuntimeError(f'OpenAI pricing page lists {model_id} at conflicting standard rates')
            # An all-dash row has no rates, and an empty variant would claim the tier costs the standard rate.
            elif prices != ModelPrice():
                model_variants = variants.setdefault(model_id, [])
                for when in NON_STANDARD_TABS[tab]:
                    listed = next((variant for variant in model_variants if variant.when == when), None)
                    if listed is None:
                        model_variants.append(PriceVariant(when=when, prices=prices))
                    elif listed.prices != prices:
                        print(
                            f'OpenAI: kept the first {when} rates of {model_id}, {tab} lists others; update them by hand'
                        )
    if not rates:
        raise RuntimeError('OpenAI pricing page has no standard text pricing table')
    for model_id in sorted(variants.keys() - rates.keys()):
        print(f'OpenAI: skipped the tiers of {model_id}, which has no standard rates; update them by hand')
    return [
        ModelInfo(
            id=model_id,
            match=ClauseEquals(equals=model_id),
            prices=prices,
            price_variants=variants.get(model_id),
            prices_checked=date.today(),
        )
        for model_id, prices in rates.items()
    ]


def main(provider_path: Path | None = None) -> None:
    markdown = get_markdown(PRICING_URL)
    models = parse_pricing_markdown(markdown)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/openai.yml')
    # A new model is added with its tiers; a recorded model gets only the tiers it doesn't price yet.
    added, updated = provider_yaml.upsert_models(models, source='OpenAI', min_count=MIN_MODEL_COUNT)
    variants = {model.id: model.price_variants for model in models if model.price_variants}
    provider_yaml.add_missing_price_variants(variants, start=date.today(), source='OpenAI')
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
        elif tab in NON_STANDARD_TABS:
            # An unknown table under a tier tab could price another context, so it isn't read as that tier.
            print(f'OpenAI: skipped the {subheading} tables under {tab}; update them by hand')
            continue
        try:
            section_tables = markdown_tables(section)
        except ValueError as error:
            if tab not in NON_STANDARD_TABS:
                raise
            # A malformed tier table must not hold back the standard rates.
            print(f'OpenAI: skipped an unreadable {tab} table; update them by hand: {error}')
            continue
        for header, rows in section_tables:
            if 'Model' not in header[:2]:
                continue
            names = header[header.index('Model') + 1 :]
            if columns := _columns(names):
                tables.append(TextTable(tab, header.index('Model'), columns, rows))
            elif any(name.startswith(('Short context ', 'Long context ')) for name in names):
                print(f'OpenAI: skipped a {tab or "Standard"} table with unknown columns; update them by hand: {names}')
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
