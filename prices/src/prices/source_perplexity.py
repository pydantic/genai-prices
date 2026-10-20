from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, markdown_tables, package_dir

PRICING_URL = 'https://docs.perplexity.ai/docs/getting-started/pricing.md'
MIN_MODEL_COUNT = 4
EMBEDDINGS_HEADER = ['Model', 'Dimensions', 'Price ($/1M tokens)']
DECISIONS_HEADER = ['Model', 'Price ($/1M input tokens)', 'Output tokens', 'Per-request fee']


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    # The page escapes `$` in its tables as `\$`.
    tables = [
        ([cell.replace('\\$', '$') for cell in header], [[cell.replace('\\$', '$') for cell in row] for row in rows])
        for header, rows in markdown_tables(markdown)
    ]
    embeddings = [row for header, rows in tables if header == EMBEDDINGS_HEADER for row in rows]
    decisions = [row for header, rows in tables if header == DECISIONS_HEADER for row in rows]
    if not embeddings or not decisions:
        raise RuntimeError('Perplexity pricing page no longer has its Embeddings and Decisions price tables')
    if bad := next((row for row in decisions if row[2:] != ['Free', 'None']), None):
        raise RuntimeError(f'Perplexity now bills Decisions output tokens or requests: {bad}')
    return [_input_priced_model(row[0], row[2]) for row in embeddings] + [
        _input_priced_model(row[0], row[1]) for row in decisions
    ]


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/perplexity.yml')
    added, updated = provider_yaml.upsert_models(models, source='Perplexity', min_count=MIN_MODEL_COUNT)
    print(f'Perplexity prices updated: {added} added, {updated} updated')


def get_perplexity_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Perplexity Decisions and Embeddings prices."""
    main()


def _input_priced_model(model_cell: str, price_cell: str) -> ModelInfo:
    model_id = re.fullmatch(r'`([^`]+)`', model_cell)
    price = re.fullmatch(r'\$([0-9]+(?:\.[0-9]+)?)', price_cell)
    if model_id is None or price is None:
        raise RuntimeError(f'Unexpected Perplexity price row: {model_cell} | {price_cell}')
    return ModelInfo(
        id=model_id.group(1),
        match=ClauseEquals(equals=model_id.group(1)),
        prices=ModelPrice(input_mtok=Decimal(price.group(1))),
        prices_checked=date.today(),
    )
