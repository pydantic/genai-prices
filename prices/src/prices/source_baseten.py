from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

# The Markdown export renders this page's model table empty, so the catalog is read from the page's compiled MDX.
CATALOG_URL = 'https://docs.baseten.co/inference/model-apis/overview'
PRICING_URL = 'https://www.baseten.co/pricing'
MIN_MODEL_COUNT = 11
# The pricing table names models only by display name; most reduce to the same key as their catalog ID.
PRICING_NAME_ALIASES = {
    'Beam': 'reflection/Beam-1.0',
    'Nemotron 3.5 Super VL': 'nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B',
    'NVIDIA Nemotron 3 Ultra': 'nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B',
}
TOKEN_TABLE = re.compile(
    r'\\"columns\\":\[\\"Model\\",\\"Input\\",\\"Cache input\\",\\"Output\\"],\\"rows\\":\[(.*?)]]'
)
TABLE_ROW = re.compile(r'\[\\"([^"\\]+)\\",\\"([^"\\]+)\\",\\"([^"\\]+)\\",\\"([^"\\]+)\\"')
PRICE_CELL = re.compile(r'\$\$([0-9]+(?:\.[0-9]+)?)')


@dataclass(frozen=True)
class CatalogModel:
    id: str
    name: str
    context_window: int


def parse_catalog(page: str) -> list[CatalogModel]:
    table = re.search(r'SupportedModelsTable=\(\)=>\{[^\[]*?const rows=\[(.*?)\];', page)
    if table is None:
        raise RuntimeError('Baseten model catalog table was not found')
    rows = re.findall(r'\{model:`([^`]+)`,slug:`([^`]+)`,context:([0-9]+),maxOutput:[0-9]+\}', table.group(1))
    models = [
        CatalogModel(id=model_id, name=name, context_window=int(context) * 1000) for name, model_id, context in rows
    ]
    if len({model.id for model in models}) != len(models):
        raise RuntimeError('Baseten model catalog contains duplicate model IDs')
    return models


def parse_pricing_page(page: str) -> list[tuple[str, list[Decimal | None]]]:
    """Return the token pricing table's rows as display name and input, cached input and output rates."""
    table = TOKEN_TABLE.search(page)
    if table is None:
        raise RuntimeError('Baseten token pricing table was not found')
    return [(name, [_rate(cell) for cell in cells]) for name, *cells in TABLE_ROW.findall(table.group(1))]


def _rate(cell: str) -> Decimal | None:
    """Parse a `$$1.25` price cell; `—` marks a rate the table does not publish."""
    if cell == '—':
        return None
    if (price := PRICE_CELL.fullmatch(cell)) is None:
        raise RuntimeError(f'Unexpected Baseten price: {cell}')
    return Decimal(price.group(1))


def _name_key(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())


def parse_models(catalog_page: str, pricing_page: str) -> list[ModelInfo]:
    catalog = parse_catalog(catalog_page)
    ids = {_name_key(model.id.rsplit('/', 1)[-1]): model.id for model in catalog}
    prices: dict[str, ModelPrice] = {}
    for name, rates in parse_pricing_page(pricing_page):
        model_id = PRICING_NAME_ALIASES.get(name) or ids.get(_name_key(name))
        if model_id is None or model_id not in ids.values():
            continue
        if model_id in prices:
            raise RuntimeError(f'Duplicate Baseten pricing model: {model_id}')
        # The updater keeps a curated rate the source omits, so a rate that became free needs a manual edit.
        if Decimal(0) in rates:
            raise RuntimeError(f'Baseten lists a $0.00 rate for {model_id}; record the free rate by hand')
        input_mtok, cache_read_mtok, output_mtok = rates
        prices[model_id] = ModelPrice(input_mtok=input_mtok, cache_read_mtok=cache_read_mtok, output_mtok=output_mtok)
    # New models often reach the catalog before the pricing page, so price only what both list.
    if unpriced := sorted({model.id for model in catalog} - prices.keys()):
        print(f'Skipping Baseten models without published prices: {unpriced}')
    return [
        ModelInfo(
            id=model.id,
            name=model.name,
            match=ClauseEquals(equals=model.id),
            context_window=model.context_window,
            price_comments=(
                'The pricing table does not publish a separate cached-input rate for this model.'
                if prices[model.id].cache_read_mtok is None
                else None
            ),
            prices=prices[model.id],
            prices_checked=date.today(),
        )
        for model in catalog
        if model.id in prices
    ]


def main(provider_path: Path | None = None) -> None:
    catalog_response = httpx2.get(CATALOG_URL, timeout=30.0)
    catalog_response.raise_for_status()
    pricing_response = httpx2.get(PRICING_URL, timeout=30.0)
    pricing_response.raise_for_status()
    models = parse_models(catalog_response.text, pricing_response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/baseten.yml')
    models_added, models_updated = provider_yaml.upsert_models(
        models, source='Baseten sources', min_count=MIN_MODEL_COUNT
    )
    print(f'Baseten prices updated: {models_added} added, {models_updated} updated')


def get_baseten_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Baseten model prices."""
    main()


if __name__ == '__main__':
    main()
