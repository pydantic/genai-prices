"""Pricing data from https://www.llm-prices.com/current-v1.json."""

from __future__ import annotations

from decimal import Decimal

import httpx2
from pydantic import BaseModel, TypeAdapter

from . import source_prices
from .prices_types import ModelPrice
from .update import get_providers_yaml


class SimonWModel(BaseModel):
    id: str
    vendor: str
    name: str
    input: Decimal
    output: Decimal
    input_cached: Decimal | None = None


class SimonWResponse(BaseModel):
    updated_at: str
    prices: list[SimonWModel]


simonw_response_schema = TypeAdapter(SimonWResponse)


def get_simonw_prices():
    """Get prices from github.com/simonw/llm-prices."""
    url = 'https://www.llm-prices.com/current-v1.json'
    r = httpx2.get(url)
    r.raise_for_status()
    response_data = simonw_response_schema.validate_json(r.content)

    prices: source_prices.SourcePricesType = {}
    providers_yml = get_providers_yaml()
    for model in response_data.prices:
        provider_name = get_provider(model)
        if not provider_name:
            print(f'Unknown provider for {model.id} (vendor {model.vendor!r})')
            continue

        assert provider_name in providers_yml, f'Unknown provider {provider_name!r} for {model.id}'

        price = ModelPrice(input_mtok=model.input, output_mtok=model.output, cache_read_mtok=model.input_cached)
        prices.setdefault(provider_name, {})[model.id] = price

    source_prices.write_source_prices('simonw', prices)


# `vendor` values we deliberately don't map: models whose weights are served by many providers
# (meta-ai, qwen) have no single provider entry to attribute an upstream price to.
lookup_vendor = {
    'amazon': 'aws',
    'anthropic': 'anthropic',
    'deepseek': 'deepseek',
    'google': 'google',
    'minimax': 'minimax',
    'mistral': 'mistral',
    'moonshot-ai': 'moonshotai',
    'openai': 'openai',
    'xai': 'x-ai',
}


def get_provider(model: SimonWModel) -> str | None:
    return lookup_vendor.get(model.vendor)
