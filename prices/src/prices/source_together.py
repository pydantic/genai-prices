from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from itertools import takewhile
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

MODELS_URL = 'https://docs.together.ai/docs/serverless/models.md'
MIN_MODEL_COUNT = 10
TABLE_HEADER = (
    '| Organization | Model name | API model string | Context length | Input pricing (per 1M tokens) '
    '| Cached input pricing (per 1M tokens) | Output pricing (per 1M tokens) | Quantization | Function calling '
    '| Structured outputs |'
)


def parse_models_markdown(markdown: str) -> list[ModelInfo]:
    section = re.search(r'^## Chat models$(.*?)(?=^## |\Z)', markdown, flags=re.MULTILINE | re.DOTALL)
    lines = section[1].strip().splitlines() if section else []
    if not lines or lines[0] != TABLE_HEADER:
        raise RuntimeError('Together models page has no chat models table in the expected shape')

    models: list[ModelInfo] = []
    for line in takewhile(lambda line: line.startswith('|'), lines[2:]):
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if len(cells) != 10:
            raise RuntimeError(f'Unexpected Together chat model row: {line}')
        _, name, model_id, context, input_price, cache_read_price, output_price = cells[:7]
        prices = ModelPrice(
            input_mtok=_price(input_price, line),
            cache_read_mtok=_price(cache_read_price, line),
            output_mtok=_price(output_price, line),
        )
        if prices.is_free():
            continue
        if not context.isdigit() and context != '-':
            raise RuntimeError(f'Unexpected Together context length {context!r} in row: {line}')
        models.append(
            ModelInfo(
                id=model_id,
                name=name,
                match=ClauseEquals(equals=model_id),
                context_window=int(context) if context.isdigit() else None,
                prices=prices,
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_models_markdown(get_markdown(MODELS_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/together.yml')
    added, updated = provider_yaml.upsert_models(models, source='Together', min_count=MIN_MODEL_COUNT)
    print(f'Together prices updated: {added} added, {updated} updated')


def get_together_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Together AI prices."""
    main()


def _price(cell: str, line: str) -> Decimal | None:
    if cell in ('-', 'Free'):
        return None
    if not (match := re.fullmatch(r'\\?\$(\d+(?:\.\d+)?)', cell)):
        raise RuntimeError(f'Unexpected Together price {cell!r} in row: {line}')
    return Decimal(match[1])
