from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import fetch_markdown, markdown_tables, package_dir

PRICING_URL = 'https://dev.meta.ai/docs/pricing-rate-limits.md'
MIN_MODEL_COUNT = 3
TOKEN_TABLE_HEADER = ['Usage', 'Standard mode (per 1M tokens)', 'Contributor mode (per 1M tokens)']
ROWS = {'Cached input': 'cache_read_mtok', 'Input': 'input_mtok', 'Output': 'output_mtok'}


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    web_search = re.search(r'\*\*\$([0-9]+(?:\.[0-9]+)?) per 1,000 search queries\*\*', markdown)
    section = re.search(r'^## Model pricing$(.*?)^## ', markdown, flags=re.MULTILINE | re.DOTALL)
    if web_search is None or section is None:
        raise RuntimeError('Meta pricing page no longer has a model pricing section with a web search rate')

    models: list[ModelInfo] = []
    for family in re.split(r'^### ', section.group(1), flags=re.MULTILINE)[1:]:
        model_line = re.search(r'^Models?: (.+)$', family, flags=re.MULTILINE)
        tables = [rows for header, rows in markdown_tables(family) if header == TOKEN_TABLE_HEADER]
        if model_line is None and not tables:
            continue
        family_name = family.split('\n', 1)[0]
        if model_line is None or len(tables) != 1 or sorted(row[0] for row in tables[0]) != sorted(ROWS):
            raise RuntimeError(f'Unexpected Meta pricing layout for {family_name}')
        model_ids = re.findall(r'`([^`]+)`', model_line.group(1))
        if not model_ids:
            raise RuntimeError(f'No Meta model ids listed for {family_name}')
        for model_id in model_ids:
            column = 2 if model_id.endswith('-contributor') else 1
            rates = {ROWS[row[0]]: _price(row[column], model_id) for row in tables[0]}
            rates['web_searches_kcount'] = Decimal(web_search.group(1))
            models.append(
                ModelInfo(
                    id=model_id,
                    match=ClauseEquals(equals=model_id),
                    prices=ModelPrice(**rates),
                    prices_checked=date.today(),
                )
            )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(fetch_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/meta.yml')
    added, updated = provider_yaml.upsert_models(models, source='Meta', min_count=MIN_MODEL_COUNT)
    print(f'Meta prices updated: {added} added, {updated} updated')


def get_meta_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Meta Model API prices."""
    main()


def _price(cell: str, model_id: str) -> Decimal:
    if not re.fullmatch(r'\$[0-9]+(?:\.[0-9]+)?', cell):
        raise RuntimeError(f'Unexpected Meta price for {model_id}: {cell}')
    return Decimal(cell[1:])
