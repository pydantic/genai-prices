from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

# The page-data behind https://www.databricks.com/product/pricing/foundation-model-serving.
PRICING_URL = (
    'https://www.databricks.com/en-pricing-assets/page-data/product/pricing/foundation-model-serving/page-data.json'
)
MIN_MODEL_COUNT = 10
TABLE_MARKER = 'Pay Per Token (DBU Per 1M Tokens)'
# The serverless real-time inference rate in AWS and Azure US regions and every GCP US region; see the YAML's comments.
USD_PER_DBU = Decimal('0.070')
# The page names models, not endpoints, so each row maps to the endpoints it prices.
MODEL_IDS: dict[str, list[str]] = {
    'BGE Large': ['databricks-bge-large-en'],
    'DeepSeek V4 Flash': ['databricks-deepseek-v4-flash-0731'],
    'DeepSeek V4 Pro': ['databricks-deepseek-v4-pro-0813'],
    'DeepSeek V4.1 Flash': ['databricks-deepseek-v4-1-flash'],
    'GLM-5.2, 5.3': ['databricks-glm-5-2', 'databricks-glm-5-3'],
    'GLM-5.3 Flash': ['databricks-glm-5-3-flash'],
    'GPT-OSS-120B': ['databricks-gpt-oss-120b'],
    'GPT-OSS-20B': ['databricks-gpt-oss-20b'],
    'GTE': ['databricks-gte-large-en'],
    'Gemma 3 12B': ['databricks-gemma-3-12b'],
    'Inkling': ['databricks-inkling'],
    'Kimi K2.7': ['databricks-kimi-k2-7-code'],
    'Kimi K3': ['databricks-kimi-k3'],
    'Llama 3.1 8B': ['databricks-meta-llama-3-1-8b-instruct'],
    'Llama 3.3 70B': ['databricks-meta-llama-3-3-70b-instruct'],
    'Llama 4 Maverick': ['databricks-llama-4-maverick'],
    'Qwen 3 0.6B Embedding': ['databricks-qwen3-embedding-0-6b'],
    'Qwen 3 80B Instruct': ['databricks-qwen3-next-80b-a3b-instruct'],
    'Qwen 3.5 122B': ['databricks-qwen35-122b-a10b'],
}


def parse_page_data(page_data: dict[str, Any]) -> list[ModelInfo]:
    """Parse the AWS and GCP Standard Pay Per Token DBU table into USD at `USD_PER_DBU`."""
    tables: list[str] = []
    for item in _walk(page_data):
        visibility: Any = item.get('fieldItem') or {}
        description: Any = item.get('fieldDescription') or {}
        text: Any = description.get('processed', '')
        if 'aws' in visibility.get('entity', {}).get('fieldPricingClouds', []) and TABLE_MARKER in text:
            tables.append(text)
    if len(tables) != 1:
        raise RuntimeError(f'Expected one Databricks AWS pay-per-token table, found {len(tables)}')
    table = re.search(r'<tbody>(.*?)</tbody>', tables[0], flags=re.S)
    if table is None:
        raise RuntimeError('Databricks pay-per-token table has no body')

    models: list[ModelInfo] = []
    for row in re.findall(r'<tr>(.*?)</tr>', table[1], flags=re.S):
        cells = [
            html.unescape(re.sub(r'<[^>]+>', '', cell)).strip() for cell in re.findall(r'<td[^>]*>(.*?)</td>', row)
        ]
        if len(cells) != 4:
            raise RuntimeError(f'Unexpected Databricks pricing row: {row}')
        name = cells[0].removesuffix('⌖').strip()
        if name not in MODEL_IDS:
            print(f'Databricks: skipped {name!r}, it has no known serving endpoint')
            continue
        input_mtok, output_mtok, cache_read_mtok = (_usd(cell, row) for cell in cells[1:])
        prices = ModelPrice(input_mtok=input_mtok, output_mtok=output_mtok, cache_read_mtok=cache_read_mtok)
        models += [
            ModelInfo(id=model_id, match=ClauseEquals(equals=model_id), prices=prices, prices_checked=date.today())
            for model_id in MODEL_IDS[name]
        ]
    return models


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(PRICING_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_page_data(response.json())
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/databricks.yml')
    added, updated = provider_yaml.upsert_models(models, source='Databricks', min_count=MIN_MODEL_COUNT)
    print(f'Databricks prices updated: {added} added, {updated} updated')


def get_databricks_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Databricks Foundation Model API prices."""
    main()


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    children: list[Any] = []
    if isinstance(node, dict):
        item = cast(dict[str, Any], node)
        yield item
        children = list(item.values())
    elif isinstance(node, list):
        children = cast(list[Any], node)
    for child in children:
        yield from _walk(child)


def _usd(cell: str, row: str) -> Decimal | None:
    if cell == '-':
        return None
    if not re.fullmatch(r'\d+(?:\.\d+)?', cell):
        raise RuntimeError(f'Unexpected Databricks DBU rate {cell!r} in row: {row}')
    return (Decimal(cell) * USD_PER_DBU).quantize(Decimal('0.001'))
