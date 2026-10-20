from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, markdown_tables, package_dir

PRICING_URL = 'https://docs.perplexity.ai/docs/getting-started/pricing.md'
AGENT_MODELS_URL = 'https://docs.perplexity.ai/docs/agent-api/models.md'
MIN_MODEL_COUNT = 5
EMBEDDINGS_HEADER = ['Model', 'Dimensions', 'Price ($/1M tokens)']
DECISIONS_HEADER = ['Model', 'Price ($/1M input tokens)', 'Output tokens', 'Per-request fee']
AGENT_MODELS_HEADER = ['Model', 'Input (\\$/1M)', 'Output (\\$/1M)', 'Cache read (\\$/1M)', 'Service tiers', 'Docs']


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


def parse_agent_models_markdown(markdown: str) -> list[ModelInfo]:
    """The Agent API models Perplexity hosts itself; the others are resold at their creator's rates."""
    rows = [
        row
        for header, rows in markdown_tables(markdown)
        if header == AGENT_MODELS_HEADER
        for row in rows
        if row[0].startswith('`perplexity/')
    ]
    if not rows:
        raise RuntimeError('Perplexity Agent API models page no longer lists Perplexity-hosted models')
    models: list[ModelInfo] = []
    for model_cell, *rate_cells, tiers, _ in rows:
        model_id = re.fullmatch(r'`([^`]+)`', model_cell)
        rates = [re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', cell) for cell in rate_cells]
        if model_id is None or not all(rates) or tiers != '—':
            raise RuntimeError(
                f'Unexpected Perplexity Agent API model row: {model_cell} | {" | ".join(rate_cells)} | {tiers}'
            )
        input_mtok, output_mtok, cache_read_mtok = (Decimal(cell) for cell in rate_cells)
        models.append(
            ModelInfo(
                id=model_id.group(1),
                match=ClauseEquals(equals=model_id.group(1)),
                prices=ModelPrice(input_mtok=input_mtok, cache_read_mtok=cache_read_mtok, output_mtok=output_mtok),
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL)) + parse_agent_models_markdown(
        get_markdown(AGENT_MODELS_URL)
    )
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/perplexity.yml')
    added, updated = provider_yaml.upsert_models(models, source='Perplexity', min_count=MIN_MODEL_COUNT)
    print(f'Perplexity prices updated: {added} added, {updated} updated')


def get_perplexity_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Perplexity Decisions, Embeddings and Agent API prices."""
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
