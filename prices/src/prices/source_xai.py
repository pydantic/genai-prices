from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from itertools import takewhile
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

PRICING_URL = 'https://docs.x.ai/developers/pricing.md'
MIN_MODEL_COUNT = 3
TABLE_HEADER = '| Model | Context | Input / 1M tokens | Cached input / 1M tokens | Output / 1M tokens |'
MODEL_CELL = re.compile(r'(?P<id>[\w.-]+)(?: \((?P<op><|≥) (?P<threshold>\d+)k prompt tokens\))?')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    lines = markdown.splitlines()
    if TABLE_HEADER not in lines:
        raise RuntimeError('xAI pricing page has no text pricing table')
    rows = takewhile(lambda line: line.startswith('|'), lines[lines.index(TABLE_HEADER) + 2 :])

    base_rows: dict[str, tuple[int | None, int, list[Decimal]]] = {}
    long_context_rows: dict[str, tuple[int, list[Decimal]]] = {}
    for line in rows:
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        match = MODEL_CELL.fullmatch(cells[0]) if len(cells) == 5 else None
        if match is None:
            raise RuntimeError(f'Unexpected xAI pricing row: {line}')
        model_id = match['id']
        threshold = int(match['threshold']) * 1000 if match['threshold'] else None
        rates = [_dollars(cell, line) for cell in cells[2:]]
        if model_id in (long_context_rows if match['op'] == '≥' else base_rows):
            raise RuntimeError(f'Duplicate xAI pricing row: {line}')
        if match['op'] == '≥':
            assert threshold is not None
            long_context_rows[model_id] = (threshold, rates)
        else:
            base_rows[model_id] = (threshold, _context(cells[1], line), rates)

    models: list[ModelInfo] = []
    for model_id, (threshold, context_window, rates) in base_rows.items():
        long_context = long_context_rows.pop(model_id, None)
        if (long_context[0] if long_context else None) != threshold:
            raise RuntimeError(f'xAI pricing rows for {model_id} do not pair a base and a long-context rate')
        prices: list[Decimal | TieredPrices] = list(rates)
        if long_context:
            # xAI bills a prompt of exactly the threshold at the long-context rate; tiers apply above `start`.
            start = long_context[0] - 1
            prices = [
                TieredPrices(base=base, tiers=[Tier(start=start, price=price)])
                for base, price in zip(rates, long_context[1])
            ]
        models.append(
            ModelInfo(
                id=model_id,
                match=ClauseEquals(equals=model_id),
                context_window=context_window,
                prices=ModelPrice(input_mtok=prices[0], cache_read_mtok=prices[1], output_mtok=prices[2]),
                prices_checked=date.today(),
            )
        )
    if long_context_rows:
        raise RuntimeError(f'xAI long-context rows without a base row: {", ".join(long_context_rows)}')
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/x_ai.yml')
    added, updated = provider_yaml.upsert_models(models, source='xAI', min_count=MIN_MODEL_COUNT)
    print(f'xAI prices updated: {added} added, {updated} updated')


def get_xai_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update xAI prices."""
    main()


def _dollars(cell: str, line: str) -> Decimal:
    if not (match := re.fullmatch(r'\$(\d+(?:\.\d+)?)', cell)):
        raise RuntimeError(f'Unexpected xAI price {cell!r} in row: {line}')
    return Decimal(match[1])


def _context(cell: str, line: str) -> int:
    if not (match := re.fullmatch(r'(\d+(?:\.\d+)?)([kM])', cell)):
        raise RuntimeError(f'Unexpected xAI context window {cell!r} in row: {line}')
    return int(Decimal(match[1]) * (1000 if match[2] == 'k' else 1_000_000))
