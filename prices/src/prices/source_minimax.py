from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from prices.prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import get_markdown, markdown_tables, package_dir

PRICING_URL = 'https://platform.minimax.io/docs/pricing/overview.md'
MIN_MODEL_COUNT = 2
PRICE_COLUMNS = {
    'Input': 'input_mtok',
    'Output': 'output_mtok',
    'Prompt caching Read': 'cache_read_mtok',
    'Prompt caching Write': 'cache_write_mtok',
}

Rates = dict[str, Decimal]


def parse_pricing_markdown(markdown: str) -> list[ModelInfo]:
    section = re.search(r'^\s*## LLM\s*$(.*?)</section>', markdown, flags=re.MULTILINE | re.DOTALL)
    if section is None:
        raise RuntimeError('MiniMax pricing page has no LLM section')
    standard = re.sub(r'<Tab title="Priority\*?">.*?</Tab>', '', section.group(1), flags=re.DOTALL)
    if set(re.findall(r'<Tab title="([^"]*)"', standard)) - {'Standard'}:
        raise RuntimeError('MiniMax LLM pricing has a tab other than Standard and Priority')

    flat: dict[str, Rates] = {}
    tiered: dict[str, list[tuple[str, int, Rates]]] = {}
    for header, rows in markdown_tables(standard):
        if (
            header[0] != 'Model'
            or len(set(header)) != len(header)
            or not {'Input', 'Output'} <= set(header[1:]) <= PRICE_COLUMNS.keys()
        ):
            raise RuntimeError(f'Unexpected MiniMax LLM pricing columns: {header}')
        for row in rows:
            if not (model := re.fullmatch(r'\*\*([A-Za-z0-9.-]+)\*\*(.*)', row[0])):
                raise RuntimeError(f'Unexpected MiniMax model cell: {row[0]}')
            name, label = model.groups()
            rates = {PRICE_COLUMNS[column]: _price(cell) for column, cell in zip(header[1:], row[1:])}
            if band := re.match(r'<br />([≤>]) ([0-9]+)k input tokens', label):
                tiered.setdefault(name, []).append((band.group(1), int(band.group(2)) * 1000, rates))
            elif re.sub(r'<span[^>]*>[^<]*</span>', '', label).strip() or name in flat:
                raise RuntimeError(f'Unexpected MiniMax pricing row: {row[0]}')
            else:
                flat[name] = rates

    models = [_model(name, ModelPrice(**rates)) for name, rates in flat.items()]
    for name, bands in tiered.items():
        if name in flat or [(sign, start) for sign, start, _ in bands] != [('≤', bands[0][1]), ('>', bands[0][1])]:
            raise RuntimeError(f'Unexpected MiniMax context bands for {name}')
        (_, start, base), (_, _, above) = bands
        if base.keys() != above.keys():
            raise RuntimeError(f'MiniMax context bands for {name} price different units')
        prices = {key: TieredPrices(base=base[key], tiers=[Tier(start=start, price=above[key])]) for key in base}
        models.append(_model(name, ModelPrice(**prices)))  # pyright: ignore[reportArgumentType]
    return models


def main(provider_path: Path | None = None) -> None:
    models = parse_pricing_markdown(get_markdown(PRICING_URL))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/minimax.yml')
    # Several legacy page rows share one YAML model; they must agree or the shared entry would be mispriced.
    shared: dict[str, ModelInfo] = {}
    for index, model in enumerate(models):
        if (existing := provider_yaml.provider.find_model(model.id)) is not None:
            if existing.id in shared and shared[existing.id].prices != model.prices:
                raise RuntimeError(f'MiniMax prices {shared[existing.id].id} and {model.id} differently')
            shared[existing.id] = model
            # A tracked model keeps its curated match rather than gaining the page's case aliases.
            models[index] = model.model_copy(update={'match': ClauseEquals(equals=model.id)})
    added, updated = provider_yaml.upsert_models(models, source='MiniMax', min_count=MIN_MODEL_COUNT)
    print(f'MiniMax prices updated: {added} added, {updated} updated')


def get_minimax_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update MiniMax prices."""
    main()


def _model(name: str, prices: ModelPrice) -> ModelInfo:
    return ModelInfo(
        id=name,
        name=name,
        match=ClauseOr.model_validate({'or': [ClauseEquals(equals=name), ClauseEquals(equals=name.lower())]}),
        prices=prices,
        prices_checked=date.today(),
    )


def _price(cell: str) -> Decimal:
    if not (match := re.fullmatch(r'(?:~~\\\$[0-9.]+~~ )?\\\$([0-9]+(?:\.[0-9]+)?) / M tokens', cell)):
        raise RuntimeError(f'Unexpected MiniMax price cell: {cell}')
    return Decimal(match.group(1))
