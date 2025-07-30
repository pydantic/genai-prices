from datetime import datetime, timezone
from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price_async, calc_price_sync

pytestmark = pytest.mark.anyio


def test_sync_success_with_provider():
    price = calc_price_sync(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')

    assert price.input_price == snapshot(Decimal('0.0025'))
    assert price.output_price == snapshot(Decimal('0.001'))
    assert price.total_price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


def test_sync_success_with_url():
    price = calc_price_sync(
        Usage(input_tokens=1000, output_tokens=100, cache_write_tokens=1000, cache_read_tokens=1000),
        model_ref='claude-3.5-sonnet@abc',
        provider_api_url='https://api.anthropic.com/foo/bar',
    )
    assert price.input_price == snapshot(Decimal('0.00705'))
    assert price.output_price == snapshot(Decimal('0.0015'))
    assert price.total_price == snapshot(Decimal('0.00855'))
    assert price.model.name == snapshot('Claude Sonnet 3.5')
    assert price.provider.name == snapshot('Anthropic')
    assert price.auto_update_timestamp is None


def test_sync_success_with_model():
    price = calc_price_sync(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o')

    assert price.input_price == snapshot(Decimal('0.0025'))
    assert price.output_price == snapshot(Decimal('0.001'))
    assert price.total_price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


def test_sync_success_with_model_regex():
    price = calc_price_sync(Usage(input_tokens=1000, output_tokens=100), model_ref='o3')

    assert price.input_price == snapshot(Decimal('0.002'))
    assert price.output_price == snapshot(Decimal('0.0008'))
    assert price.total_price == snapshot(Decimal('0.0028'))
    assert price.model.name == snapshot('o3')
    assert price.provider.id == snapshot('openai')


async def test_async_success_with_provider():
    price = await calc_price_async(
        Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai'
    )
    assert price.input_price == snapshot(Decimal('0.0025'))
    assert price.output_price == snapshot(Decimal('0.001'))
    assert price.total_price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


def test_tiered_prices():
    price = calc_price_sync(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='google')
    # from providers/google.yml: (0.075 * 128000 + 0.15 * (500000 - 128000)) / 1_000_000 = 0.0654

    assert price.input_price == snapshot(Decimal('0.0654'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.0654'))
    assert price.model.name == snapshot('gemini 1.5 flash')
    assert price.provider.id == snapshot('google')


def test_requests_kcount_prices():
    # request count defaults to 1
    price = calc_price_sync(Usage(), model_ref='sonar', provider_id='perplexity')
    assert price.input_price == snapshot(Decimal('0'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.012'))
    assert price.model.name == snapshot('Sonar')
    assert price.provider.name == snapshot('Perplexity')


def test_price_constraint_before():
    price = calc_price_sync(Usage(input_tokens=1000), model_ref='o3', genai_request_timestamp=datetime(2025, 6, 1))
    assert price.input_price == snapshot(Decimal('0.01'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.01'))
    assert price.model.name == snapshot('o3')
    assert price.provider.name == snapshot('OpenAI')


def test_price_constraint_after():
    price = calc_price_sync(Usage(input_tokens=1000), model_ref='o3')
    assert price.input_price == snapshot(Decimal('0.002'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.002'))
    assert price.model.name == snapshot('o3')
    assert price.provider.name == snapshot('OpenAI')


def test_price_constraint_time_of_date():
    price = calc_price_sync(
        Usage(input_tokens=100_000_000),
        model_ref='deepseek-chat',
        genai_request_timestamp=datetime(2025, 6, 1, 16, tzinfo=timezone.utc),
    )
    assert price.input_price == snapshot(Decimal('27.00'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('27'))
    assert price.model.name == snapshot('DeepSeek Chat')
    assert price.provider.name == snapshot('Deepseek')
    price = calc_price_sync(
        Usage(input_tokens=100_000_000),
        model_ref='deepseek-chat',
        genai_request_timestamp=datetime(2025, 6, 1, 17, tzinfo=timezone.utc),
    )
    assert price.input_price == snapshot(Decimal('13.500'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('13.5'))
    assert price.model.name == snapshot('DeepSeek Chat')
    assert price.provider.name == snapshot('Deepseek')


def test_provider_not_found_id():
    with pytest.raises(LookupError, match="Unable to find provider provider_id='foobar'"):
        calc_price_sync(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='foobar')


def test_provider_not_found_url():
    with pytest.raises(LookupError, match="Unable to find provider provider_api_url='foobar'"):
        calc_price_sync(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_api_url='foobar')


def test_provider_not_found_model_ref():
    with pytest.raises(LookupError, match="Unable to find provider with model matching 'llama2-70b-4096'"):
        calc_price_sync(Usage(input_tokens=500_000), model_ref='llama2-70b-4096')


def test_model_not_found():
    with pytest.raises(LookupError, match="Unable to find model with model_ref='wrong' in google"):
        calc_price_sync(Usage(input_tokens=500_000), model_ref='wrong', provider_id='google')


EXAMPLES: list[tuple[str, str]] = [
    # ('openrouter', 'amazon/us.amazon.nova-micro-v1:0'),
    # ('openrouter', 'amazon/us.amazon.nova-pro-v1:0'),
    ('anthropic', 'anthropic.claude-v2'),
    ('anthropic', 'claude-3-5-haiku-123'),
    ('anthropic', 'claude-3-5-haiku-20241022'),
    ('anthropic', 'claude-3-5-haiku-latest'),
    ('anthropic', 'claude-3-5-sonnet-20241022'),
    ('anthropic', 'claude-3-5-sonnet-latest'),
    ('anthropic', 'claude-3-7-sonnet-20250219'),
    ('anthropic', 'claude-3-7-sonnet-latest'),
    ('anthropic', 'claude-3-opus-20240229'),
    ('anthropic', 'claude-opus-4-20250514'),
    ('anthropic', 'claude-opus-4-20250514'),
    ('anthropic', 'claude-opus-4-0'),
    ('cohere', 'command-r7b-12-2024'),
    ('deepseek', 'deepseek-r1-distill-llama-70b'),
    ('google', 'gemini-1.5-flash-002'),
    ('google', 'gemini-1.5-flash-123'),
    ('google', 'gemini-1.5-flash'),
    ('google', 'gemini-1.5-pro-002'),
    ('google', 'gemini-2.0-flash-exp'),
    ('google', 'gemini-2.0-flash-thinking-exp-01-21'),
    ('google', 'gemini-2.0-flash'),
    ('google', 'gemini-2.5-pro-preview-03-25'),
    # ('openrouter', 'meta-llama/llama-3.3-70b-versatile'),
    # ('openrouter', 'meta-llama/llama-4-scout-17b-16e-instruct'),
    ('mistral', 'mistral-small-latest'),
    ('mistral', 'pixtral-12b-latest'),
    ('openai', 'gpt-3.5-turbo-0125'),
    ('openai', 'gpt-3.5-turbo-instruct:20230824-v2'),
    ('openai', 'gpt-4-0613'),
    ('openai', 'gpt-4.1-2025-04-14'),
    ('openai', 'gpt-4.1-mini-2025-04-14'),
    ('openai', 'gpt-4.1-mini'),
    ('openai', 'gpt-4.1-nano-2025-04-14'),
    ('openai', 'gpt-4.5-preview-2025-02-27'),
    ('openai', 'gpt-4o-2024-08-06'),
    ('openai', 'gpt-4o-2024-11-20'),
    ('openai', 'gpt-4o-audio-preview-2024-10-01'),
    ('openai', 'gpt-4o-audio-preview-2024-12-17'),
    ('openai', 'gpt-4o-mini-2024-07-18'),
    ('openai', 'gpt-4o-mini'),
    ('openai', 'gpt-4o'),
    ('openai', 'o3-mini-2025-01-31'),
    ('openai', 'text-embedding-3-small'),
]


@pytest.mark.parametrize('provider,model', EXAMPLES)
def test_models_found(provider: str, model: str):
    calc_price_sync(Usage(input_tokens=1000, output_tokens=100), model_ref=model, provider_id=provider)
