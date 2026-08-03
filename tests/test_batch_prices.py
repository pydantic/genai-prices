"""Tests for batch API pricing.

The provider payloads below are verbatim responses from real batch jobs run against those APIs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price, extract_usage
from genai_prices.data_snapshot import DataSnapshot, set_custom_snapshot
from genai_prices.types import (
    ClauseEquals,
    ConditionalPrice,
    ModelInfo,
    ModelPrice,
    Provider,
    StartDateConstraint,
)

# A batch of two requests against claude-haiku-4-5, the second of which read the cache the first wrote.
ANTHROPIC_BATCH_CACHE_WRITE = {
    'model': 'claude-haiku-4-5-20251001',
    'usage': {
        'input_tokens': 17,
        'cache_creation_input_tokens': 7082,
        'cache_read_input_tokens': 0,
        'cache_creation': {'ephemeral_5m_input_tokens': 7082, 'ephemeral_1h_input_tokens': 0},
        'output_tokens': 5,
        'service_tier': 'batch',
        'inference_geo': 'not_available',
    },
}
ANTHROPIC_BATCH_CACHE_READ = {
    'model': 'claude-haiku-4-5-20251001',
    'usage': {
        'input_tokens': 17,
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 7082,
        'cache_creation': {'ephemeral_5m_input_tokens': 0, 'ephemeral_1h_input_tokens': 0},
        'output_tokens': 5,
        'service_tier': 'batch',
        'inference_geo': 'not_available',
    },
}
# The body of an OpenAI batch output line, which is an ordinary chat completion.
OPENAI_BATCH_RESULT = {
    'model': 'gpt-5-nano-2025-08-07',
    'usage': {
        'prompt_tokens': 6382,
        'completion_tokens': 64,
        'total_tokens': 6446,
        'prompt_tokens_details': {'cached_tokens': 6272, 'audio_tokens': 0},
        'completion_tokens_details': {'reasoning_tokens': 64, 'audio_tokens': 0},
    },
    'service_tier': 'default',
}
# An OpenAI batch object, which totals the usage of every request in the batch.
OPENAI_BATCH_JOB = {
    'id': 'batch_6a7052e0088881909a136a909246f5b7',
    'object': 'batch',
    'endpoint': '/v1/chat/completions',
    'model': 'gpt-5-nano-2025-08-07',
    'status': 'completed',
    'request_counts': {'total': 2, 'completed': 2, 'failed': 0},
    'usage': {
        'input_tokens': 12764,
        'output_tokens': 128,
        'total_tokens': 12892,
        'input_tokens_details': {'cached_tokens': 6272},
        'output_tokens_details': {'reasoning_tokens': 128},
    },
}
GEMINI_BATCH_RESULT = {
    'modelVersion': 'gemini-3.1-flash-lite',
    'usageMetadata': {
        'promptTokenCount': 12,
        'candidatesTokenCount': 1,
        'totalTokenCount': 13,
        'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 12}],
        'serviceTier': 'standard',
    },
}
MISTRAL_BATCH_RESULT = {
    'model': 'mistral-small-latest',
    'usage': {
        'prompt_tokens': 26,
        'completion_tokens': 2,
        'total_tokens': 28,
        'prompt_tokens_details': {'cached_tokens': 0, 'audio_tokens': 0},
    },
}
GROQ_BATCH_RESULT = {
    'model': 'llama-3.3-70b-versatile',
    'usage': {'prompt_tokens': 46, 'completion_tokens': 2, 'total_tokens': 48},
    'service_tier': 'batch',
}


def test_anthropic_batch_cache_write():
    extracted = extract_usage(ANTHROPIC_BATCH_CACHE_WRITE, provider_id='anthropic')

    assert extracted.calc_price(batch=True).total_price == snapshot(Decimal('0.00444725'))
    assert extracted.calc_price().total_price == snapshot(Decimal('0.0088945'))


def test_anthropic_batch_cache_read():
    extracted = extract_usage(ANTHROPIC_BATCH_CACHE_READ, provider_id='anthropic')

    assert extracted.calc_price(batch=True).total_price == snapshot(Decimal('0.0003751'))
    assert extracted.calc_price().total_price == snapshot(Decimal('0.0007502'))


def test_openai_batch_result():
    extracted = extract_usage(OPENAI_BATCH_RESULT, provider_id='openai', api_flavor='chat')

    assert extracted.usage == snapshot(
        Usage(
            input_tokens=6382,
            cache_read_tokens=6272,
            input_audio_tokens=0,
            output_audio_tokens=0,
            output_tokens=64,
            output_reasoning_tokens=64,
        )
    )
    assert extracted.calc_price(batch=True).total_price == snapshot(Decimal('0.00003123'))
    assert extracted.calc_price().total_price == snapshot(Decimal('0.00006246'))


def test_openai_batch_job_totals():
    """An OpenAI batch object reports the whole job's usage in the shape the responses API uses."""
    extracted = extract_usage(OPENAI_BATCH_JOB, provider_id='openai', api_flavor='responses')

    assert extracted.calc_price(batch=True).total_price == snapshot(Decimal('0.00020358'))
    assert extracted.calc_price().total_price == snapshot(Decimal('0.00040716'))


@pytest.mark.parametrize(
    ('provider_id', 'response'),
    [
        ('google', GEMINI_BATCH_RESULT),
        ('mistral', MISTRAL_BATCH_RESULT),
        ('groq', GROQ_BATCH_RESULT),
    ],
)
def test_batch_result_halves_standard_price(provider_id: str, response: dict[str, object]):
    extracted = extract_usage(response, provider_id=provider_id)

    assert extracted.calc_price(batch=True).total_price == extracted.calc_price().total_price / 2


@pytest.mark.parametrize(
    ('provider_id', 'model_ref', 'expected_ratio'),
    [
        ('anthropic', 'claude-opus-5', Decimal('0.5')),
        ('openai', 'gpt-5.6-terra', Decimal('0.5')),
        ('google', 'gemini-3.6-flash', Decimal('0.5')),
        ('mistral', 'mistral-large-2512', Decimal('0.5')),
        ('groq', 'llama-3.3-70b-versatile', Decimal('0.5')),
        # xAI discounts batch by 20%, not 50%.
        ('x-ai', 'grok-4.3', Decimal('0.8')),
    ],
)
def test_batch_discount_ratio(provider_id: str, model_ref: str, expected_ratio: Decimal):
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000)
    standard = calc_price(usage, model_ref=model_ref, provider_id=provider_id)
    batch = calc_price(usage, model_ref=model_ref, provider_id=provider_id, batch=True)

    assert batch.total_price == standard.total_price * expected_ratio


def test_batch_prices_fall_through_for_undiscounted_units():
    """Anthropic halves every token rate but publishes no batch rate for web searches."""
    usage = Usage(input_tokens=1_000_000, web_searches=1_000)
    batch = calc_price(usage, model_ref='claude-opus-5', provider_id='anthropic', batch=True)

    assert batch.model_price.input_mtok == snapshot(Decimal('2.5'))
    assert batch.model_price.web_searches_kcount == snapshot(Decimal('10'))
    assert batch.total_price == snapshot(Decimal('12.5'))


def test_google_batch_keeps_standard_cache_read():
    """Google bills batch cache hits "at the standard context caching rates" on this model."""
    usage = Usage(input_tokens=100_000, cache_read_tokens=40_000)
    standard = calc_price(usage, model_ref='gemini-3.1-pro-preview', provider_id='google')
    batch = calc_price(usage, model_ref='gemini-3.1-pro-preview', provider_id='google', batch=True)

    # only the 60k uncached input tokens are discounted; the 40k cached ones cost the same either way
    assert standard.total_price == snapshot(Decimal('0.128'))
    assert batch.total_price == snapshot(Decimal('0.068'))


def test_batch_without_batch_prices_uses_standard_prices():
    usage = Usage(input_tokens=1_000, output_tokens=1_000)
    standard = calc_price(usage, model_ref='deepseek-v4-pro', provider_id='deepseek')
    batch = calc_price(usage, model_ref='deepseek-v4-pro', provider_id='deepseek', batch=True)

    assert batch.total_price == standard.total_price


def test_batch_prices_resolve_conditionals_independently():
    model = ModelInfo(
        id='test',
        match=ClauseEquals('test'),
        prices=[
            ConditionalPrice(prices=ModelPrice(input_mtok=Decimal(10))),
            ConditionalPrice(
                constraint=StartDateConstraint(datetime(2026, 1, 1).date()),
                prices=ModelPrice(input_mtok=Decimal(20)),
            ),
        ],
        batch_prices=[
            ConditionalPrice(prices=ModelPrice(input_mtok=Decimal(5))),
            ConditionalPrice(
                constraint=StartDateConstraint(datetime(2026, 6, 1).date()),
                prices=ModelPrice(input_mtok=Decimal(8)),
            ),
        ],
    )
    provider = Provider(id='test', name='Test', api_pattern='.*', models=[model])
    set_custom_snapshot(DataSnapshot(providers=[provider], from_auto_update=False))
    try:
        usage = Usage(input_tokens=1_000_000)
        for timestamp, expected_standard, expected_batch in (
            (datetime(2025, 6, 1, tzinfo=timezone.utc), Decimal(10), Decimal(5)),
            (datetime(2026, 3, 1, tzinfo=timezone.utc), Decimal(20), Decimal(5)),
            (datetime(2026, 8, 1, tzinfo=timezone.utc), Decimal(20), Decimal(8)),
        ):
            standard = calc_price(usage, model_ref='test', provider_id='test', genai_request_timestamp=timestamp)
            batch = calc_price(
                usage, model_ref='test', provider_id='test', genai_request_timestamp=timestamp, batch=True
            )
            assert standard.total_price == expected_standard
            assert batch.total_price == expected_batch
    finally:
        set_custom_snapshot(None)


@pytest.mark.parametrize('batch_prices', [None, [], ModelPrice()])
def test_empty_batch_prices_use_standard_prices(batch_prices: object):
    model = ModelInfo(
        id='test',
        match=ClauseEquals('test'),
        prices=ModelPrice(input_mtok=Decimal(10)),
        batch_prices=batch_prices,  # pyright: ignore[reportArgumentType]
    )

    assert model.get_prices(datetime.now(tz=timezone.utc), batch=True).input_mtok == Decimal(10)


def test_batch_prices_override_key_by_key():
    model = ModelInfo(
        id='test',
        match=ClauseEquals('test'),
        prices=ModelPrice(input_mtok=Decimal(10), output_mtok=Decimal(20), requests_kcount=Decimal(1)),
        # an unset key falls through to the standard price, exactly like an omitted one
        batch_prices=ModelPrice(input_mtok=None, output_mtok=Decimal(5)),
    )

    prices = model.get_prices(datetime.now(tz=timezone.utc), batch=True)

    assert prices.input_mtok == Decimal(10)
    assert prices.output_mtok == Decimal(5)
    assert prices.requests_kcount == Decimal(1)
    # the standard prices are not mutated by the overlay
    assert model.get_prices(datetime.now(tz=timezone.utc)).output_mtok == Decimal(20)
