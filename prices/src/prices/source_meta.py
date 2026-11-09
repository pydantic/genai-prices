from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import get_markdown, markdown_tables, package_dir

PRICING_URL = 'https://dev.meta.ai/docs/pricing-rate-limits.md'
MIN_MODEL_COUNT = 6
STANDARD = 'Standard mode (per 1M tokens)'
CONTRIBUTOR = 'Contributor mode (per 1M tokens)'
# Meta bills a request over 200K input tokens, cached included, at the long-context rates in full.
LONG_CONTEXT_HEADER = ['Usage', 'Up to 200K input tokens (per 1M tokens)', 'Over 200K input tokens (per 1M tokens)']
LONG_CONTEXT_START = 200_000
ROWS = {'Cached input': 'cache_read_mtok', 'Input': 'input_mtok', 'Output': 'output_mtok'}


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    web_search = re.search(r'\*\*\$([0-9]+(?:\.[0-9]+)?) per 1,000 search queries\*\*', markdown)
    section = re.search(r'^## Model pricing$(.*?)^## ', markdown, flags=re.MULTILINE | re.DOTALL)
    if web_search is None or section is None:
        raise RuntimeError('Meta pricing page no longer has a model pricing section with a web search rate')

    models: list[ModelInfo] = []
    for family in re.split(r'^### ', section.group(1), flags=re.MULTILINE)[1:]:
        model_line = re.search(r'^Models?: (.+)$', family, flags=re.MULTILINE)
        tables = [
            (header, rows)
            for header, rows in markdown_tables(family)
            if header == LONG_CONTEXT_HEADER or sorted(header) == sorted(['Usage', STANDARD, CONTRIBUTOR])
        ]
        if model_line is None and not tables:
            continue
        family_name = family.split('\n', 1)[0]
        if model_line is None or len(tables) != 1 or sorted(row[0] for row in tables[0][1]) != sorted(ROWS):
            raise RuntimeError(f'Unexpected Meta pricing layout for {family_name}')
        header, rows = tables[0]
        model_ids = re.findall(r'`([^`]+)`', model_line.group(1))
        if not model_ids:
            raise RuntimeError(f'No Meta model ids listed for {family_name}')
        for model_id in model_ids:
            if any(model.id == model_id for model in models):
                raise RuntimeError(f'Duplicate Meta model in pricing data: {model_id}')
            contributor = model_id.endswith('-contributor')
            if header == LONG_CONTEXT_HEADER:
                if contributor:
                    raise RuntimeError(f'Meta lists no Contributor mode long-context prices for {model_id}')
                rates: dict[str, Decimal | TieredPrices] = {
                    ROWS[row[0]]: TieredPrices(
                        base=_price(row[1], model_id),
                        tiers=[Tier(start=LONG_CONTEXT_START, price=_price(row[2], model_id))],
                    )
                    for row in rows
                }
            else:
                column = header.index(CONTRIBUTOR if contributor else STANDARD)
                rates = {ROWS[row[0]]: _price(row[column], model_id) for row in rows}
            rates['web_searches_kcount'] = Decimal(web_search.group(1))
            models.append(
                ModelInfo(
                    id=model_id,
                    match=ClauseEquals(equals=model_id),
                    prices=ModelPrice.model_validate(rates),
                    prices_checked=date.today(),
                )
            )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
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
