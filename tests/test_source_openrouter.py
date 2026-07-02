from datetime import datetime, timezone
from decimal import Decimal

import pytest

from prices.prices_types import ClauseEquals, ClauseOr
from prices.source_openrouter import OpenRouterModel, OpenRouterPricing


def openrouter_model(model_id: str, *, canonical_slug: str | None = None) -> OpenRouterModel:
    return OpenRouterModel(
        id=model_id,
        canonical_slug=canonical_slug or model_id,
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


def test_openrouter_provider_model_info_matches_canonical_slug_alias():
    model_info = openrouter_model(
        'moonshotai/kimi-k2.7-code',
        canonical_slug='moonshotai/kimi-k2.7-code-20260612',
    ).model_info(inc_description=False, strip_provider=False)

    assert model_info.id == 'moonshotai/kimi-k2.7-code'
    assert model_info.match == ClauseOr(
        or_=[  # pyright: ignore[reportCallIssue]
            ClauseEquals(equals='moonshotai/kimi-k2.7-code'),
            ClauseEquals(equals='moonshotai/kimi-k2.7-code-20260612'),
        ]
    )
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
