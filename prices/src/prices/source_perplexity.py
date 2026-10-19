from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import get_markdown, package_dir

PRICING_URL = 'https://docs.perplexity.ai/docs/getting-started/pricing.md'
MIN_MODEL_COUNT = 3
EXPECTED_UNITS = {
    'sonar.input/output/citation/reasoning': '$ per 1,000,000 tokens',
    'sonar.request.{low,medium,high}': '$ per 1,000 requests (varies by search context size)',
    'sonar.searchQueries': '$ per 1,000 searches (Deep Research only)',
}


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    marker = 'export const PRICING = '
    if marker not in markdown:
        raise RuntimeError('Perplexity pricing page has no PRICING data')
    pricing: dict[str, Any]
    pricing, _ = json.JSONDecoder().raw_decode(markdown, markdown.index(marker) + len(marker))
    units: dict[str, str] = pricing['_meta']['units']
    for key, unit in EXPECTED_UNITS.items():
        if units.get(key) != unit:
            raise RuntimeError(f'Perplexity changed the unit of {key} to {units.get(key)!r}')

    models: list[ModelInfo] = []
    for sonar in pricing['sonar']['models']:
        request: dict[str, Any] = sonar.get('request') or {}
        prices = ModelPrice.model_validate(
            {
                key: Decimal(str(sonar[field]))
                for key, field in [
                    ('input_mtok', 'input'),
                    ('output_mtok', 'output'),
                    ('output_reasoning_mtok', 'reasoning'),
                    ('output_citation_mtok', 'citation'),
                    ('web_searches_kcount', 'searchQueries'),
                ]
                if field in sonar
            }
            # A request's fee depends on its search context size, which usage doesn't report; take the highest.
            | ({'requests_kcount': Decimal(str(max(request.values())))} if request else {})
        )
        models.append(
            ModelInfo(
                id=sonar['id'],
                name=sonar['label'],
                match=ClauseEquals(equals=sonar['id']),
                prices=prices,
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/perplexity.yml')
    added, updated = provider_yaml.upsert_models(models, source='Perplexity', min_count=MIN_MODEL_COUNT)
    print(f'Perplexity prices updated: {added} added, {updated} updated')


def get_perplexity_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Perplexity Sonar prices."""
    main()
