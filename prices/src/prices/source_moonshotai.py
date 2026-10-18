from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

PRICING_URL = 'https://platform.kimi.ai/docs/pricing/chat.md'
MIN_MODEL_COUNT = 2
PRICE_COLUMNS = {
    'Cache Write Price (TTL 5min)': 'cache_write_mtok',
    'Cache Write Price (TTL 1h)': 'cache_write_1h_mtok',
    'Cached Input Price': 'cache_read_mtok',
    'Input Price (Cache Hit)': 'cache_read_mtok',
    'Input Price': 'input_mtok',
    'Input Price (Cache Miss)': 'input_mtok',
    'Output Price': 'output_mtok',
}
INFO_COLUMNS = {'Model', 'Unit', 'Context Window'}
CELL = re.compile(r'<>\{"\$"\}([0-9]+(?:\.[0-9]+)?)</>|"([^"]*)"')


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    tables = re.findall(r'<DocTable\s+columns=\{\[(.*?)\]\}\s+rows=\{\[(.*?)\]\}\s*/>', markdown, flags=re.DOTALL)
    if not tables:
        raise RuntimeError('Moonshot AI pricing page has no DocTable price tables')
    models: list[ModelInfo] = []
    for columns_source, rows_source in tables:
        columns = re.findall(r'title: "([^"]+)"', columns_source)
        if set(columns) - PRICE_COLUMNS.keys() != INFO_COLUMNS:
            raise RuntimeError(f'Unexpected Moonshot AI pricing columns: {columns}')
        for row_source in rows_source.strip().splitlines():
            row = row_source.strip().removeprefix('[').removesuffix('],')
            matches = list(CELL.finditer(row))
            if len(matches) != len(columns) or CELL.sub('', row).replace(',', '').strip():
                raise RuntimeError(f'Unexpected Moonshot AI pricing row: {row_source}')
            cells = dict(zip(columns, matches))
            model_id, unit, context = (cells[column].group(2) for column in ('Model', 'Unit', 'Context Window'))
            context_match = re.fullmatch(r'([0-9,]+) tokens', context or '')
            if not model_id or unit != '1M tokens' or context_match is None:
                raise RuntimeError(f'Unexpected Moonshot AI model, unit or context window: {row_source}')
            prices: dict[str, Decimal] = {}
            for column, key in PRICE_COLUMNS.items():
                if column in cells:
                    if (price := cells[column].group(1)) is None:
                        raise RuntimeError(f'Unexpected Moonshot AI {column} for {model_id}: {cells[column].group()}')
                    prices[key] = Decimal(price)
            models.append(
                ModelInfo(
                    id=model_id,
                    match=ClauseEquals(equals=model_id),
                    context_window=int(context_match.group(1).replace(',', '')),
                    prices=ModelPrice(**prices),
                    prices_checked=date.today(),
                )
            )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/moonshotai.yml')
    added, updated = provider_yaml.upsert_models(models, source='Moonshot AI', min_count=MIN_MODEL_COUNT)
    print(f'Moonshot AI prices updated: {added} added, {updated} updated')


def get_moonshotai_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Moonshot AI (Kimi) prices."""
    main()
