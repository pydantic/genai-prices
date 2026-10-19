from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from itertools import takewhile
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

PRICING_URL = 'https://platform.claude.com/docs/en/about-claude/pricing.md'
MIN_MODEL_COUNT = 10
TABLE_HEADER = [
    'Model',
    'Base input tokens',
    '5m cache writes',
    '1h cache writes',
    'Cache hits and refreshes',
    'Output tokens',
]
PRICE_KEYS = ('input_mtok', 'cache_write_mtok', 'cache_write_1h_mtok', 'cache_read_mtok', 'output_mtok')
# Older models whose public ids predate the `claude-<family>-<version>` naming.
MODEL_IDS = {
    'claude-opus-4': 'claude-opus-4-0',
    'claude-sonnet-4': 'claude-sonnet-4-0',
    'claude-haiku-3-5': 'claude-3-5-haiku-latest',
}
MODEL_CELL = re.compile(
    r'(?P<name>Claude [A-Z][a-z]+ \d+(?:\.\d+)?)'
    r'(?: \((?:for prompts (?P<op>up to|over) (?P<threshold>[\d,]+) tokens|(?P<note>.+))\))?'
)
PRICE_CELL = re.compile(r'\$(\d+(?:\.\d+)?) / MTok(?:<sup>\d+</sup>)?')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    lines = markdown.splitlines()
    header = next((i for i, line in enumerate(lines) if _cells(line) == TABLE_HEADER), None)
    if header is None:
        raise RuntimeError('Anthropic pricing page has no model pricing table')
    rows = takewhile(lambda line: line.startswith('|'), lines[header + 2 :])

    base_rows: dict[str, tuple[int | None, list[Decimal]]] = {}
    long_context_rows: dict[str, tuple[int, list[Decimal]]] = {}
    for line in rows:
        cells = _cells(line)
        match = MODEL_CELL.fullmatch(cells[0]) if len(cells) == len(TABLE_HEADER) else None
        if match is None:
            raise RuntimeError(f'Unexpected Anthropic pricing row: {line}')
        if match['note'] and match['note'].startswith('[limited availability'):
            continue
        model_id = re.sub(r'[ .]', '-', match['name'].lower())
        model_id = MODEL_IDS.get(model_id, model_id)
        threshold = int(match['threshold'].replace(',', '')) if match['threshold'] else None
        rates = [_dollars(cell, line) for cell in cells[1:]]
        target = long_context_rows if match['op'] == 'over' else base_rows
        if model_id in target:
            raise RuntimeError(f'Duplicate Anthropic pricing row: {line}')
        if match['op'] == 'over':
            assert threshold is not None
            long_context_rows[model_id] = (threshold, rates)
        else:
            base_rows[model_id] = (threshold, rates)

    models: list[ModelInfo] = []
    for model_id, (threshold, rates) in base_rows.items():
        long_context = long_context_rows.pop(model_id, None)
        if (long_context[0] if long_context else None) != threshold:
            raise RuntimeError(f'Anthropic pricing rows for {model_id} do not pair a base and a long-context rate')
        prices: list[Decimal | TieredPrices] = list(rates)
        if long_context:
            # Every token of a prompt over the threshold is billed at the higher rate.
            prices = [
                TieredPrices(base=base, tiers=[Tier(start=long_context[0], price=price)])
                for base, price in zip(rates, long_context[1])
            ]
        models.append(
            ModelInfo(
                id=model_id,
                match=ClauseEquals(equals=model_id),
                prices=ModelPrice.model_validate(dict(zip(PRICE_KEYS, prices))),
                prices_checked=date.today(),
            )
        )
    if long_context_rows:
        raise RuntimeError(f'Anthropic long-context rows without a base row: {", ".join(long_context_rows)}')
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/anthropic.yml')
    added, updated = provider_yaml.upsert_models(models, source='Anthropic', min_count=MIN_MODEL_COUNT)
    print(f'Anthropic prices updated: {added} added, {updated} updated')


def get_anthropic_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Anthropic prices."""
    main()


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


def _dollars(cell: str, line: str) -> Decimal:
    if not (match := PRICE_CELL.fullmatch(cell)):
        raise RuntimeError(f'Unexpected Anthropic price {cell!r} in row: {line}')
    return Decimal(match[1])
