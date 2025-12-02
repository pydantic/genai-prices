from __future__ import annotations

from decimal import Decimal

import httpx
from pydantic import BaseModel, OnErrorOmit, TypeAdapter

from . import source_prices
from .prices_types import ModelPrice
from .update import get_providers_yaml
from .utils import mtok


class LiteLLMModel(BaseModel):
    max_tokens: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    input_cost_per_token: Decimal | None = None
    output_cost_per_token: Decimal | None = None
    output_cost_per_reasoning_token: Decimal | None = None
    litellm_provider: str
    deprecation_date: str | None = None


lite_llm_response_schema = TypeAdapter(dict[str, OnErrorOmit[LiteLLMModel]])

lookup_provider = {
    'azure_ai': 'azure',
    'azure_text': 'azure',
    'bedrock': 'aws',
    'bedrock_converse': 'aws',
    'cohere_chat': 'cohere',
    'fireworks_ai': 'fireworks',
    'fireworks_ai-embedding-models': 'fireworks',
    'gemini': 'google',
    'together_ai': 'together',
    'vertex_ai-ai21_models': 'google',
    'vertex_ai-anthropic_models': 'google',
    'vertex_ai-chat-models': 'google',
    'vertex_ai-code-chat-models': 'google',
    'vertex_ai-code-text-models': 'google',
    'vertex_ai-embedding-models': 'google',
    'vertex_ai-language-models': 'google',
    'vertex_ai-llama_models': 'google',
    'vertex_ai-mistral_models': 'google',
    'vertex_ai-text-models': 'google',
    'vertex_ai-vision-models': 'google',
    'xai': 'x-ai',
}


def get_litellm_prices():
    """Get prices from LiteLLM code."""
    url = 'https://raw.githubusercontent.com/BerriAI/litellm/refs/heads/main/model_prices_and_context_window.json'
    r = httpx.get(url)
    r.raise_for_status()
    response_data = lite_llm_response_schema.validate_json(r.content)

    prices: source_prices.SourcePricesType = {}
    providers_yml = get_providers_yaml()
    for name, model in response_data.items():
        if model.input_cost_per_token is None or model.output_cost_per_token is None:
            continue

        provider_name = lookup_provider.get(model.litellm_provider, model.litellm_provider)
        if provider_name not in providers_yml:
            continue

        price = ModelPrice(
            input_mtok=mtok(model.input_cost_per_token),
            output_mtok=mtok(model.output_cost_per_token),
        )
        if provider_prices := prices.get(provider_name):
            provider_prices[name] = price
        else:
            prices[provider_name] = {name: price}

    source_prices.write_source_prices('litellm', prices)
