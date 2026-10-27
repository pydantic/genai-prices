from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

# The Markdown export renders this page's DocTables empty, so the prices are read from the page's compiled MDX.
PRICING_URL = 'https://platform.kimi.ai/docs/pricing/chat'
MIN_MODEL_COUNT = 2
PRICE_COLUMNS = {
    'Input': 'input_mtok',
    'Output': 'output_mtok',
    'Cached Input': 'cache_read_mtok',
    '5m writes': 'cache_write_mtok',
    '1h writes': 'cache_write_1h_mtok',
}
CONTEXT_WINDOW = re.compile(r'support a ([0-9,]+)-token context window')


def parse_pricing_page(page: str) -> list[ModelInfo]:
    tables = list(re.finditer(r'columns:\[(.*?)\],rows:\[\[(.*?)\]\]\}', page))
    if not tables:
        raise RuntimeError('Moonshot AI pricing page has no DocTable price tables')
    models: list[ModelInfo] = []
    for table in tables:
        # A tooltip title keeps its label in `children`, the last string before the column's width.
        columns = re.findall(r'`([^`]*)`(?:\}\))?,width:', table.group(1))
        if (
            columns[:1] != ['Model']
            or len(set(columns)) != len(columns)
            or not {'Input', 'Output'} <= set(columns[1:]) <= PRICE_COLUMNS.keys()
        ):
            raise RuntimeError(f'Unexpected Moonshot AI pricing columns: {columns}')
        if not (windows := CONTEXT_WINDOW.findall(page, 0, table.start())):
            raise RuntimeError(f'Moonshot AI pricing table has no context window: {columns}')
        context_window = int(windows[-1].replace(',', ''))
        for row in table.group(2).split('],['):
            cells = [cell for cell in re.findall(r'href:`[^`]*`|`([^`]*)`', row) if cell]
            if len(cells) != len(columns) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', cells[0]):
                raise RuntimeError(f'Unexpected Moonshot AI pricing row: {row}')
            prices: dict[str, Decimal] = {}
            for column, cell in zip(columns[1:], cells[1:]):
                if not (price := re.fullmatch(r'\$([0-9]+(?:\.[0-9]+)?) / MTok', cell)):
                    raise RuntimeError(f'Unexpected Moonshot AI {column} for {cells[0]}: {cell}')
                prices[PRICE_COLUMNS[column]] = Decimal(price.group(1))
            models.append(
                ModelInfo(
                    id=cells[0],
                    match=ClauseEquals(equals=cells[0]),
                    context_window=context_window,
                    prices=ModelPrice(**prices),
                    prices_checked=date.today(),
                )
            )
    return models


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(PRICING_URL, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    models = parse_pricing_page(response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/moonshotai.yml')
    added, updated = provider_yaml.upsert_models(models, source='Moonshot AI', min_count=MIN_MODEL_COUNT)
    print(f'Moonshot AI prices updated: {added} added, {updated} updated')


def get_moonshotai_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Moonshot AI (Kimi) prices."""
    main()
