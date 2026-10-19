from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

LIBRARY_URL = 'https://modal.com/library'
MIN_MODEL_COUNT = 2
PRICE_KEYS = {'promptMtok': 'input_mtok', 'cachedPromptMtok': 'cache_read_mtok', 'completionMtok': 'output_mtok'}


def parse_library_data(data: dict[str, Any]) -> list[str]:
    """Return the model page paths listed in the library's SvelteKit `__data.json`."""
    values = _page_values(data)
    entries = _get(values, values[0], 'models')
    if not isinstance(entries, list):
        raise RuntimeError('Modal library page has no models')
    paths = [_get(values, values[index], 'href') for index in cast(list[int], entries)]
    if not all(isinstance(path, str) and path.startswith('/library/') for path in paths):
        raise RuntimeError(f'Unexpected Modal library model links: {paths}')
    return paths


def parse_model_data(data: dict[str, Any]) -> ModelInfo | None:
    """Parse a model page's `__data.json`; models without a Shared Endpoint have no token rates."""
    values = _page_values(data)
    model = _get(values, values[0], 'model')
    if not isinstance(model, dict):
        raise RuntimeError('Modal model page has no model')
    if _get(values, model, 'hasSharedEndpoint') is not True:
        return None
    rates = _get(values, model, 'tokenRates')
    model_id = _get(values, model, 'baseModelRepoId')
    if not isinstance(rates, dict) or not isinstance(model_id, str):
        raise RuntimeError(f'Modal Shared Endpoint model has no token rates: {model}')
    prices: dict[str, Decimal] = {}
    for source_key, price_key in PRICE_KEYS.items():
        rate = _get(values, rates, source_key)
        if not isinstance(rate, str) or not re.fullmatch(r'\d+(?:\.\d+)?', rate):
            raise RuntimeError(f'Unexpected Modal {source_key} rate {rate!r} for {model_id}')
        prices[price_key] = Decimal(rate)
    # An empty reasoning rate means reasoning tokens bill as completion tokens.
    if _get(values, rates, 'reasoningMtok') not in ('', _get(values, rates, 'completionMtok')):
        raise RuntimeError(f'Modal prices reasoning tokens separately for {model_id}')
    return ModelInfo(
        id=model_id,
        name=_get(values, model, 'displayName'),
        match=ClauseEquals(equals=model_id),
        prices=ModelPrice(**prices),
        prices_checked=date.today(),
    )


def main(provider_path: Path | None = None) -> None:
    with httpx2.Client(base_url='https://modal.com', timeout=30.0) as client:
        models: list[ModelInfo] = []
        for path in parse_library_data(_get_json(client, '/library/__data.json')):
            if model := parse_model_data(_get_json(client, f'{path}/__data.json')):
                models.append(model)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/modal.yml')
    added, updated = provider_yaml.upsert_models(models, source='Modal', min_count=MIN_MODEL_COUNT)
    print(f'Modal prices updated: {added} added, {updated} updated')


def get_modal_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Modal Shared Endpoint prices."""
    main()


def _get_json(client: httpx2.Client, path: str) -> dict[str, Any]:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def _page_values(data: dict[str, Any]) -> list[Any]:
    # SvelteKit serializes the page's own load data, the last node, with devalue: a flat list of values indexed by
    # position, where the first value is the root object and negative indices encode `undefined` and other sentinels.
    return data['nodes'][-1]['data']


def _get(values: list[Any], node: Any, key: str) -> Any:
    index = node.get(key, -1)
    return values[index] if index >= 0 else None
