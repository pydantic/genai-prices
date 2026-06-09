from datetime import datetime, timezone
from decimal import Decimal

import pytest

from prices.prices_types import ClauseEquals
from prices.source_openrouter import OpenRouterModel, OpenRouterPricing


def openrouter_model(model_id: str) -> OpenRouterModel:
    return OpenRouterModel(
        id=model_id,
        canonical_slug=model_id.lstrip('~'),
        name=f'Test: {model_id}',
        created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        description='Test description\n\nMore details',
        context_length=1_000_000,
        pricing=OpenRouterPricing(prompt=Decimal('0.000001'), completion=Decimal('0.000002')),
        supported_parameters=[],
    )


@pytest.mark.parametrize('model_id', ['google/gemini-3.5-flash', '~anthropic/claude-fable-latest'])
def test_openrouter_provider_model_info_preserves_api_model_id(model_id: str):
    model_info = openrouter_model(model_id).model_info(inc_description=False, strip_provider=False)

    assert model_info.id == model_id
    assert model_info.match == ClauseEquals(equals=model_id)
    assert model_info.description is None


@pytest.mark.parametrize(
    ('model_id', 'native_model_id'),
    [
        ('google/gemini-3.5-flash', 'gemini-3.5-flash'),
        ('~anthropic/claude-fable-latest', 'claude-fable-latest'),
    ],
)
def test_native_provider_model_info_uses_native_model_id(model_id: str, native_model_id: str):
    model_info = openrouter_model(model_id).model_info()

    assert model_info.id == native_model_id
    assert model_info.match == ClauseEquals(equals=native_model_id)
    assert model_info.description == 'Test description'
