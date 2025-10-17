"""Pricing data from https://www.llm-prices.com/current-v1.json."""

from __future__ import annotations

from decimal import Decimal

import httpx
from pydantic import BaseModel, OnErrorOmit, TypeAdapter

from . import source_prices
from .types import ModelPrice
from .update import get_providers_yaml


class SimonWModel(BaseModel):
    name: str
    input: Decimal
    output: Decimal


simonw_response_schema = TypeAdapter(dict[str, OnErrorOmit[SimonWModel]])


def get_simonw_prices():
    """Get prices from github.com/simonw/llm-prices."""
    url = 'https://www.llm-prices.com/current-v1.json'
    r = httpx.get(url)
    r.raise_for_status()
    response_data = simonw_response_schema.validate_json(r.content)

    prices: source_prices.SourcePricesType = {}
    providers_yml = get_providers_yaml()
    for key, model in response_data.items():
        provider_name = get_provider(key)
        if not provider_name:
            print(f'Unknown provider for {key}')
            continue

        assert provider_name in providers_yml, f'Unknown provider for {key}'

        price = ModelPrice(input_mtok=model.input, output_mtok=model.output)
        if provider_prices := prices.get(provider_name):
            provider_prices[key] = price
        else:
            prices[provider_name] = {key: price}

    source_prices.write_source_prices('simonw', prices)


lookup_provider = {
    'gemini': 'google',
    'claude': 'anthropic',
    'gpt': 'openai',
    'o1': 'openai',
    'o3': 'openai',
    'o4': 'openai',
    'amazon': 'aws',
    'deepseek': 'deepseek',
    'pixtral': 'mistral',
    'mistral': 'mistral',
    'magistral': 'mistral',
    'codestral': 'mistral',
    'ministral': 'mistral',
    'grok': 'x-ai',
}


def get_provider(key: str) -> str | None:
    start = key.split('-', 1)[0]

    if provider := lookup_provider.get(start):
        return provider

    if key.startswith(('open-mixtral', 'open-mistral')):
        return 'mistral'
