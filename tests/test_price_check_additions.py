from datetime import UTC, datetime
from decimal import Decimal

import pytest

from genai_prices import Usage, calc_price
from genai_prices.types import PriceContext


@pytest.mark.parametrize(
    ('model', 'context', 'totals'),
    [
        ('gemini-3.8-flash-tts', {}, ('9.5', '19')),
        ('gemini-3.8-flash-tts', {'processing': 'batch'}, ('4.75', '9.5')),
        ('gemini-3.8-flash-tts', {'service_tier': 'flex'}, ('4.75', '9.5')),
        ('gemini-3.8-flash-tts', {'service_tier': 'priority'}, ('17.1', '34.2')),
        ('gemini-3.8-flash-lite-tts', {}, ('6.5', '13')),
        ('gemini-3.8-flash-lite-tts', {'processing': 'batch'}, ('3.25', '6.5')),
        ('gemini-3.8-flash-lite-tts', {'service_tier': 'flex'}, ('3.25', '6.5')),
        ('gemini-3.8-flash-lite-tts', {'service_tier': 'priority'}, ('11.7', '23.4')),
    ],
)
@pytest.mark.parametrize(('timestamp', 'period'), [(datetime(2026, 12, 31, 23, 59), 0), (datetime(2027, 1, 1), 1)])
def test_gemini_38_tts_rates(
    model: str, context: PriceContext, totals: tuple[str, str], timestamp: datetime, period: int
) -> None:
    price = calc_price(
        Usage(input_tokens=1_000_000, output_tokens=1_000_000, output_audio_tokens=1_000_000),
        model,
        provider_id='google',
        price_context=context,
        genai_request_timestamp=timestamp,
    )
    assert price.model.id == model
    assert price.total_price == Decimal(totals[period])


@pytest.mark.parametrize(
    ('model', 'total'), [('kimi-k2.6', '4.7525'), ('kimi-k2.7-code', '4.76'), ('kimi-k2.7-code-highspeed', '9.52')]
)
def test_moonshot_verified_rates(model: str, total: str) -> None:
    price = calc_price(
        Usage(input_tokens=1_000_000, cache_read_tokens=250_000, output_tokens=1_000_000),
        model,
        provider_id='moonshotai',
        genai_request_timestamp=datetime(2026, 10, 17, tzinfo=UTC),
    )
    assert price.total_price == Decimal(total)


@pytest.mark.parametrize('model', ['jev-1.14.0', 'jev-preview'])
def test_typesafe_114_default_context(model: str) -> None:
    price = calc_price(
        Usage(input_tokens=1_000_000), model, provider_id='typesafe', genai_request_timestamp=datetime(2026, 10, 18)
    )
    assert price.model.id == 'jev-1.14.0'
    assert price.model.context_window == 32_000
    assert price.total_price == Decimal('0.042')


def test_grok_multi_agent_dated_id_takes_its_published_long_context_rate() -> None:
    dated = calc_price(
        Usage(input_tokens=200_000, output_tokens=1_000_000),
        'grok-4.20-multi-agent-0309',
        provider_id='x-ai',
        genai_request_timestamp=datetime(2026, 10, 17),
    )
    assert dated.model.id == 'grok-4.20-multi-agent-0309'
    assert dated.total_price == Decimal('5.5')
    for alias in ('grok-4.20-multi-agent-beta-0309', 'grok-4.20-multi-agent-latest'):
        assert calc_price(Usage(input_tokens=1), alias, provider_id='x-ai').model.id == 'grok-4.20-multi-agent-0309'
    batch = calc_price(
        Usage(input_tokens=200_000, output_tokens=1_000_000),
        'grok-4.20-multi-agent-0309',
        provider_id='x-ai',
        genai_request_timestamp=datetime(2026, 10, 17),
        price_context={'processing': 'batch'},
    )
    assert batch.total_price == Decimal('4.4')
    price = calc_price(
        Usage(input_tokens=200_000, output_tokens=1_000_000),
        'grok-4.20-multi-agent',
        provider_id='x-ai',
        genai_request_timestamp=datetime(2026, 10, 17),
    )
    assert price.model.id == 'grok-4.20-multi-agent-0309'
    assert price.total_price == Decimal('5.5')


@pytest.mark.parametrize('model', ['grok-4.20', 'grok-4.20-multi-agent'])
@pytest.mark.parametrize(('day', 'total'), [(29, Decimal('12.8')), (30, Decimal('5.5'))])
def test_grok_4_20_price_cut(model: str, day: int, total: Decimal) -> None:
    price = calc_price(
        Usage(input_tokens=200_000, output_tokens=1_000_000),
        model,
        provider_id='x-ai',
        genai_request_timestamp=datetime(2026, 4, day, tzinfo=UTC),
    )
    assert price.total_price == total
