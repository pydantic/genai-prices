from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import fetch_markdown, markdown_tables, package_dir

PRICING_URL = (
    'https://docs.github.com/api/article/body?pathname=/en/copilot/reference/copilot-billing/models-and-pricing'
)
MIN_MODEL_COUNT = 20
PRICE_COLUMNS = {
    'Input': 'input_mtok',
    'Cached input': 'cache_read_mtok',
    'Cache write': 'cache_write_mtok',
    'Output': 'output_mtok',
}
OTHER_COLUMNS = {'Model', 'Release status', 'Category', 'Tier', 'Threshold (input tokens)'}

Rates = dict[str, Decimal | None]


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    names: dict[str, str] = {}
    defaults: dict[str, tuple[int | None, Rates]] = {}
    long_context: dict[str, list[tuple[int, Rates]]] = {}
    for header, rows in markdown_tables(markdown):
        if unknown := set(header) - PRICE_COLUMNS.keys() - OTHER_COLUMNS:
            raise RuntimeError(f'Unexpected GitHub Copilot pricing columns: {sorted(unknown)}')
        for row in rows:
            cells = dict(zip(header, row))
            name = re.sub(r'\[\^[^]]*]', '', cells['Model']).replace(' (preview)', '').strip()
            model_id = name.lower().replace(' (fast mode)', '-fast').replace(' ', '-')
            if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', model_id):
                raise RuntimeError(f'Cannot map GitHub Copilot model name to an id: {cells["Model"]}')
            names[model_id] = name
            rates = {key: _price(cells.get(column)) for column, key in PRICE_COLUMNS.items()}
            tier = cells.get('Tier', 'Default')
            threshold = cells.get('Threshold (input tokens)', 'Not applicable')
            if tier == 'Default' and (threshold == 'Not applicable' or threshold.startswith('≤ ')):
                if model_id in defaults:
                    raise RuntimeError(f'Duplicate GitHub Copilot model in pricing data: {model_id}')
                defaults[model_id] = (None if threshold == 'Not applicable' else _tokens(threshold), rates)
            elif tier == 'Long context' and threshold.startswith('> '):
                long_context.setdefault(model_id, []).append((_tokens(threshold), rates))
            else:
                raise RuntimeError(f'Unexpected GitHub Copilot tier for {model_id}: {tier} {threshold}')

    models: list[ModelInfo] = []
    for model_id, name in names.items():
        if model_id not in defaults:
            raise RuntimeError(f'GitHub Copilot model has long-context rates but no default rates: {model_id}')
        limit, base = defaults[model_id]
        tiers = long_context.get(model_id, [])
        if tiers and [start for start, _ in tiers] != [limit]:
            raise RuntimeError(f'GitHub Copilot tier thresholds do not line up for {model_id}')
        prices: dict[str, Decimal | TieredPrices | None] = dict(base)
        for key, base_rate in base.items():
            if base_rate is not None and tiers:
                tier_prices = [
                    Tier(start=start, price=rate) for start, rates in tiers if (rate := rates[key]) is not None
                ]
                if len(tier_prices) != len(tiers):
                    raise RuntimeError(f'GitHub Copilot long-context tier is missing {key} for {model_id}')
                prices[key] = TieredPrices(base=base_rate, tiers=tier_prices)
        models.append(
            ModelInfo(
                id=model_id,
                name=name,
                match=ClauseEquals(equals=model_id),
                prices=ModelPrice(**prices),  # pyright: ignore[reportArgumentType]
                prices_checked=date.today(),
            )
        )
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(fetch_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/github_copilot.yml')
    if unknown := [model.id for model in models if provider_yaml.provider.find_model(model.id) is None]:
        raise RuntimeError(f'GitHub Copilot pricing lists models missing from the provider YAML: {", ".join(unknown)}')
    added, updated = provider_yaml.upsert_models(models, source='GitHub Copilot', min_count=MIN_MODEL_COUNT)
    print(f'GitHub Copilot prices updated: {added} added, {updated} updated')


def get_github_copilot_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update GitHub Copilot prices."""
    main()


def _price(cell: str | None) -> Decimal | None:
    if cell is None or cell == 'Not applicable':
        return None
    if not re.fullmatch(r'\$[0-9]+(?:\.[0-9]+)?', cell):
        raise RuntimeError(f'Unexpected GitHub Copilot price cell: {cell}')
    return Decimal(cell[1:])


def _tokens(threshold: str) -> int:
    if not (match := re.fullmatch(r'[≤>] ([0-9]+)K', threshold)):
        raise RuntimeError(f'Unexpected GitHub Copilot threshold: {threshold}')
    return int(match.group(1)) * 1000
