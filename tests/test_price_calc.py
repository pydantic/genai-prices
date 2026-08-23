import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price
from genai_prices.data import providers
from genai_prices.data_snapshot import DataSnapshot, get_snapshot, set_custom_snapshot
from genai_prices.types import (
    ClauseAnd,
    ClauseContains,
    ClauseEndsWith,
    ClauseEquals,
    ClauseOr,
    ClauseRegex,
    ClauseStartsWith,
    ConditionalPrice,
    MatchLogic,
    ModelInfo,
    ModelPrice,
    PriceCalculation,
    Provider,
    StartDateConstraint,
    Tier,
    TieredPrices,
    TimeOfDateConstraint,
    calc_unit_price,
)
from genai_prices.units import UnitDef, UnitRegistry, _get_registry

pytestmark = pytest.mark.anyio


def test_sync_success_with_provider():
    price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')

    assert price.input_price == snapshot(Decimal('0.0025'))
    assert price.output_price == snapshot(Decimal('0.001'))
    assert price.total_price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


@pytest.mark.parametrize(
    ('model_ref', 'expected_input_price'),
    [
        ('gpt-5.6-sol', Decimal('0.005')),
        ('gpt-5.6-terra', Decimal('0.0025')),
        ('gpt-5.6-luna', Decimal('0.00025')),
    ],
)
def test_gpt_5_6_cache_write_price(model_ref: str, expected_input_price: Decimal):
    price = calc_price(
        Usage(input_tokens=1_000, cache_write_tokens=1_000),
        model_ref=model_ref,
        provider_id='openai',
    )

    assert price.input_price == expected_input_price
    assert price.output_price == Decimal(0)
    assert price.total_price == expected_input_price


@pytest.mark.parametrize(
    ('model_ref', 'short_write_rate', 'long_write_rate'),
    [
        ('gpt-5.6-sol', Decimal('5'), Decimal('10')),
        ('gpt-5.6-terra', Decimal('2.5'), Decimal('5')),
        ('gpt-5.6-luna', Decimal('0.25'), Decimal('0.5')),
    ],
)
def test_gpt_5_6_cache_write_price_context_boundary(
    model_ref: str,
    short_write_rate: Decimal,
    long_write_rate: Decimal,
):
    for tokens, rate in ((272_000, short_write_rate), (272_001, long_write_rate)):
        price = calc_price(
            Usage(input_tokens=tokens, cache_write_tokens=tokens),
            model_ref=model_ref,
            provider_id='openai',
        )

        expected_input_price = rate * tokens / 1_000_000
        assert price.input_price == expected_input_price
        assert price.output_price == Decimal(0)
        assert price.total_price == expected_input_price


@pytest.mark.parametrize(
    ('model_ref', 'input_rate', 'cache_write_rate', 'cache_read_rate', 'output_rate'),
    [
        ('gpt-5.6-sol', Decimal('8'), Decimal('10'), Decimal('0.8'), Decimal('30')),
        ('gpt-5.6-terra', Decimal('4'), Decimal('5'), Decimal('0.4'), Decimal('18')),
        ('gpt-5.6-luna', Decimal('0.4'), Decimal('0.5'), Decimal('0.04'), Decimal('1.8')),
    ],
)
def test_gpt_5_6_long_context_mixed_price(
    model_ref: str,
    input_rate: Decimal,
    cache_write_rate: Decimal,
    cache_read_rate: Decimal,
    output_rate: Decimal,
):
    price = calc_price(
        Usage(
            input_tokens=300_000,
            cache_write_tokens=100_000,
            cache_read_tokens=50_000,
            output_tokens=10_000,
        ),
        model_ref=model_ref,
        provider_id='openai',
    )

    expected_input_price = (input_rate * 150_000 + cache_write_rate * 100_000 + cache_read_rate * 50_000) / 1_000_000
    expected_output_price = output_rate * 10_000 / 1_000_000
    assert price.input_price == expected_input_price
    assert price.output_price == expected_output_price
    assert price.total_price == expected_input_price + expected_output_price


@pytest.mark.parametrize(
    ('model_ref', 'usage', 'expected_input_price', 'expected_output_price'),
    [
        (
            'gpt-5.5',
            Usage(input_tokens=272_001, cache_read_tokens=100_000, output_tokens=1_000),
            Decimal('1.82001'),
            Decimal('0.045'),
        ),
        (
            'gpt-5.5-pro',
            Usage(input_tokens=272_001, output_tokens=1_000),
            Decimal('16.32006'),
            Decimal('0.27'),
        ),
    ],
)
def test_gpt_5_5_long_context_price(
    model_ref: str,
    usage: Usage,
    expected_input_price: Decimal,
    expected_output_price: Decimal,
) -> None:
    price = calc_price(usage, model_ref=model_ref, provider_id='openai')

    assert price.input_price == expected_input_price
    assert price.output_price == expected_output_price
    assert price.total_price == expected_input_price + expected_output_price


@pytest.mark.parametrize(
    ('model_ref', 'request_timestamp', 'expected_prices'),
    [
        (
            'gpt-5.6-sol',
            datetime(2026, 8, 20, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('5'), tiers=[Tier(start=272_000, price=Decimal('10'))]),
                cache_write_mtok=TieredPrices(base=Decimal('6.25'), tiers=[Tier(start=272_000, price=Decimal('12.5'))]),
                cache_read_mtok=TieredPrices(base=Decimal('0.5'), tiers=[Tier(start=272_000, price=Decimal('1'))]),
                output_mtok=TieredPrices(base=Decimal('30'), tiers=[Tier(start=272_000, price=Decimal('45'))]),
            ),
        ),
        (
            'gpt-5.6-sol',
            datetime(2026, 8, 21, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('4'), tiers=[Tier(start=272_000, price=Decimal('8'))]),
                cache_write_mtok=TieredPrices(base=Decimal('5'), tiers=[Tier(start=272_000, price=Decimal('10'))]),
                cache_read_mtok=TieredPrices(base=Decimal('0.4'), tiers=[Tier(start=272_000, price=Decimal('0.8'))]),
                output_mtok=TieredPrices(base=Decimal('20'), tiers=[Tier(start=272_000, price=Decimal('30'))]),
            ),
        ),
        (
            'gpt-5.6-luna',
            datetime(2026, 7, 29, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('1'), tiers=[Tier(start=272_000, price=Decimal('2'))]),
                cache_write_mtok=TieredPrices(base=Decimal('1.25'), tiers=[Tier(start=272_000, price=Decimal('2.5'))]),
                cache_read_mtok=TieredPrices(base=Decimal('0.1'), tiers=[Tier(start=272_000, price=Decimal('0.2'))]),
                output_mtok=TieredPrices(base=Decimal('6'), tiers=[Tier(start=272_000, price=Decimal('9'))]),
            ),
        ),
        (
            'gpt-5.6-luna',
            datetime(2026, 7, 30, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('0.2'), tiers=[Tier(start=272_000, price=Decimal('0.4'))]),
                cache_write_mtok=TieredPrices(base=Decimal('0.25'), tiers=[Tier(start=272_000, price=Decimal('0.5'))]),
                cache_read_mtok=TieredPrices(base=Decimal('0.02'), tiers=[Tier(start=272_000, price=Decimal('0.04'))]),
                output_mtok=TieredPrices(base=Decimal('1.2'), tiers=[Tier(start=272_000, price=Decimal('1.8'))]),
            ),
        ),
        (
            'gpt-5.6-terra',
            datetime(2026, 7, 29, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('2.5'), tiers=[Tier(start=272_000, price=Decimal('5'))]),
                cache_write_mtok=TieredPrices(
                    base=Decimal('3.125'), tiers=[Tier(start=272_000, price=Decimal('6.25'))]
                ),
                cache_read_mtok=TieredPrices(base=Decimal('0.25'), tiers=[Tier(start=272_000, price=Decimal('0.5'))]),
                output_mtok=TieredPrices(base=Decimal('15'), tiers=[Tier(start=272_000, price=Decimal('22.5'))]),
            ),
        ),
        (
            'gpt-5.6-terra',
            datetime(2026, 7, 30, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('2'), tiers=[Tier(start=272_000, price=Decimal('4'))]),
                cache_write_mtok=TieredPrices(base=Decimal('2.5'), tiers=[Tier(start=272_000, price=Decimal('5'))]),
                cache_read_mtok=TieredPrices(base=Decimal('0.2'), tiers=[Tier(start=272_000, price=Decimal('0.4'))]),
                output_mtok=TieredPrices(base=Decimal('12'), tiers=[Tier(start=272_000, price=Decimal('18'))]),
            ),
        ),
    ],
)
def test_gpt_5_6_price_change(model_ref: str, request_timestamp: datetime, expected_prices: ModelPrice) -> None:
    price = calc_price(
        Usage(input_tokens=0),
        model_ref=model_ref,
        provider_id='openai',
        genai_request_timestamp=request_timestamp,
    )

    assert price.model_price == expected_prices


@pytest.mark.parametrize(
    ('model_ref', 'request_timestamp', 'expected_prices'),
    [
        (
            'openai.gpt-5.6-sol',
            datetime(2026, 7, 29, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('5.5'), tiers=[Tier(start=272_000, price=Decimal('11'))]),
                cache_write_mtok=TieredPrices(
                    base=Decimal('6.875'), tiers=[Tier(start=272_000, price=Decimal('13.75'))]
                ),
                cache_read_mtok=TieredPrices(base=Decimal('0.55'), tiers=[Tier(start=272_000, price=Decimal('1.1'))]),
                output_mtok=TieredPrices(base=Decimal('33'), tiers=[Tier(start=272_000, price=Decimal('49.5'))]),
            ),
        ),
        (
            'openai.gpt-5.6-terra',
            datetime(2026, 7, 29, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=Decimal('2.75'),
                cache_write_mtok=Decimal('3.4375'),
                cache_read_mtok=Decimal('0.275'),
                output_mtok=Decimal('16.5'),
            ),
        ),
        (
            'openai.gpt-5.6-terra',
            datetime(2026, 7, 30, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('2.2'), tiers=[Tier(start=272_000, price=Decimal('4.4'))]),
                cache_write_mtok=TieredPrices(base=Decimal('2.75'), tiers=[Tier(start=272_000, price=Decimal('5.5'))]),
                cache_read_mtok=TieredPrices(base=Decimal('0.22'), tiers=[Tier(start=272_000, price=Decimal('0.44'))]),
                output_mtok=TieredPrices(base=Decimal('13.2'), tiers=[Tier(start=272_000, price=Decimal('19.8'))]),
            ),
        ),
        (
            'openai.gpt-5.6-luna',
            datetime(2026, 7, 29, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=Decimal('1.1'),
                cache_write_mtok=Decimal('1.375'),
                cache_read_mtok=Decimal('0.11'),
                output_mtok=Decimal('6.6'),
            ),
        ),
        (
            'openai.gpt-5.6-luna',
            datetime(2026, 7, 30, tzinfo=timezone.utc),
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal('0.22'), tiers=[Tier(start=272_000, price=Decimal('0.44'))]),
                cache_write_mtok=TieredPrices(
                    base=Decimal('0.275'), tiers=[Tier(start=272_000, price=Decimal('0.55'))]
                ),
                cache_read_mtok=TieredPrices(
                    base=Decimal('0.022'), tiers=[Tier(start=272_000, price=Decimal('0.044'))]
                ),
                output_mtok=TieredPrices(base=Decimal('1.32'), tiers=[Tier(start=272_000, price=Decimal('1.98'))]),
            ),
        ),
    ],
)
def test_aws_gpt_5_6_price_change(model_ref: str, request_timestamp: datetime, expected_prices: ModelPrice) -> None:
    price = calc_price(
        Usage(input_tokens=0),
        model_ref=model_ref,
        provider_id='aws',
        genai_request_timestamp=request_timestamp,
    )

    assert price.model_price == expected_prices


@pytest.mark.parametrize(
    ('model_ref', 'short_input_rate', 'long_input_rate'),
    [
        ('openai.gpt-5.6-sol', Decimal('5.5'), Decimal('11')),
        ('openai.gpt-5.6-terra', Decimal('2.2'), Decimal('4.4')),
        ('openai.gpt-5.6-luna', Decimal('0.22'), Decimal('0.44')),
    ],
)
def test_aws_gpt_5_6_context_boundary(model_ref: str, short_input_rate: Decimal, long_input_rate: Decimal) -> None:
    for tokens, rate in ((272_000, short_input_rate), (272_001, long_input_rate)):
        price = calc_price(
            Usage(input_tokens=tokens),
            model_ref=model_ref,
            provider_id='aws',
        )

        expected_input_price = rate * tokens / 1_000_000
        assert price.input_price == expected_input_price
        assert price.output_price == Decimal(0)
        assert price.total_price == expected_input_price


@pytest.mark.parametrize(
    'model_ref,request_timestamp,expected_prices',
    [
        (
            'gemini-3.6-flash',
            datetime(2026, 12, 31, tzinfo=timezone.utc),
            ModelPrice(input_mtok=Decimal('0.75'), cache_read_mtok=Decimal('0.075'), output_mtok=Decimal('3.75')),
        ),
        (
            'gemini-3.6-flash',
            datetime(2027, 1, 1, tzinfo=timezone.utc),
            ModelPrice(input_mtok=Decimal('1.5'), cache_read_mtok=Decimal('0.15'), output_mtok=Decimal('7.5')),
        ),
        (
            'gemini-3.7-flash',
            datetime(2026, 12, 31, tzinfo=timezone.utc),
            ModelPrice(input_mtok=Decimal('0.75'), cache_read_mtok=Decimal('0.075'), output_mtok=Decimal('3.75')),
        ),
        (
            'gemini-3.7-flash',
            datetime(2027, 1, 1, tzinfo=timezone.utc),
            ModelPrice(input_mtok=Decimal('1.5'), cache_read_mtok=Decimal('0.15'), output_mtok=Decimal('7.5')),
        ),
    ],
)
def test_gemini_flash_introductory_price_expiry(
    model_ref: str, request_timestamp: datetime, expected_prices: ModelPrice
) -> None:
    """Introductory rates run through 2026-12-31, standard rates take over on 2027-01-01."""
    price = calc_price(
        Usage(input_tokens=0),
        model_ref=model_ref,
        provider_id='google',
        genai_request_timestamp=request_timestamp,
    )

    assert price.model_price == expected_prices


def test_sync_success_with_url():
    price = calc_price(
        Usage(input_tokens=1000, output_tokens=100, cache_write_tokens=20, cache_read_tokens=30),
        model_ref='claude-3.5-sonnet@abc',
        provider_api_url='https://api.anthropic.com/foo/bar',
    )
    assert price.input_price == snapshot(Decimal('0.002934'))
    assert price.output_price == snapshot(Decimal('0.0015'))
    assert price.total_price == snapshot(Decimal('0.004434'))
    assert price.model.name == snapshot('Claude Sonnet 3.5')
    assert price.provider.name == snapshot('Anthropic')
    assert price.auto_update_timestamp is None


def test_sync_success_with_model():
    price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o')

    assert price.input_price == snapshot(Decimal('0.0025'))
    assert price.output_price == snapshot(Decimal('0.001'))
    assert price.total_price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


def test_sync_success_with_model_regex():
    price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='o3')

    assert price.input_price == snapshot(Decimal('0.002'))
    assert price.output_price == snapshot(Decimal('0.0008'))
    assert price.total_price == snapshot(Decimal('0.0028'))
    assert price.model.name == snapshot('o3')
    assert price.provider.id == snapshot('openai')


def test_openrouter_deepseek_v32_price():
    price = calc_price(
        Usage(input_tokens=2_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000),
        model_ref='deepseek/deepseek-v3.2',
        provider_id='openrouter',
    )

    assert price.input_price == snapshot(Decimal('0.4576'))
    assert price.output_price == snapshot(Decimal('0.3432'))
    assert price.total_price == snapshot(Decimal('0.8008'))
    assert price.model.name == snapshot('DeepSeek V3.2')
    assert price.provider.id == snapshot('openrouter')


@pytest.mark.parametrize(
    ('model_ref', 'context_window', 'input_rate', 'cache_read_rate', 'output_rate'),
    [
        ('deepseek/deepseek-v4-flash', 1_000_000, Decimal('0.0805'), Decimal('0.0165'), Decimal('0.161')),
        ('deepseek/deepseek-v4-pro', 1_000_000, Decimal('1.305'), Decimal('0.10875'), Decimal('2.61')),
        ('deepseek/deepseek-v4-pro-0813', 1_000_000, Decimal('0.594'), Decimal('0.0198'), Decimal('1.782')),
        ('deepseek/deepseek-v3.2', 163_000, Decimal('0.23'), Decimal('0.012'), Decimal('0.33')),
        ('minimax/minimax-m2.5', 196_000, Decimal('0.27'), Decimal('0.15'), Decimal('1.08')),
        ('z-ai/glm-4.7', 202_000, Decimal('0.388'), Decimal('0.097'), Decimal('1.806')),
        ('z-ai/glm-5', 205_000, Decimal('0.516'), Decimal('0.129'), Decimal('2.322')),
        ('z-ai/glm-5.1', 202_000, Decimal('0.743'), Decimal('0.186'), Decimal('2.971')),
        ('z-ai/glm-5.2', 1_000_000, Decimal('0.495'), Decimal('0.124'), Decimal('1.733')),
        ('moonshotai/kimi-k2.5', 262_000, Decimal('0.45'), Decimal('0.225'), Decimal('2.2')),
        ('moonshotai/kimi-k2.6', 262_000, Decimal('0.95'), Decimal('0.16'), Decimal('4')),
        ('xiaomi/mimo-v2.5', 1_000_000, Decimal('0.2'), Decimal('0.05'), Decimal('0.4')),
        ('xiaomi/mimo-v2.5-pro', 1_000_000, Decimal('0.435'), Decimal('0.0036'), Decimal('0.87')),
    ],
)
def test_avian_prices(
    model_ref: str, context_window: int, input_rate: Decimal, cache_read_rate: Decimal, output_rate: Decimal
) -> None:
    price = calc_price(
        Usage(input_tokens=2_000_000, cache_read_tokens=1_000_000, output_tokens=1_000_000),
        model_ref=model_ref,
        provider_id='avian',
    )

    assert price.provider.id == 'avian'
    assert price.model.id == model_ref
    assert price.model.context_window == context_window
    assert price.input_price == input_rate + cache_read_rate
    assert price.output_price == output_rate
    assert price.total_price == input_rate + cache_read_rate + output_rate


@pytest.mark.parametrize(
    ('model_ref', 'input_rate', 'cache_read_rate', 'output_rate'),
    [
        ('accounts/fireworks/models/deepseek-v4-flash-0731', Decimal('0.14'), Decimal('0.028'), Decimal('0.28')),
        ('accounts/fireworks/models/inkling', Decimal('1'), Decimal('0.17'), Decimal('4.05')),
        ('accounts/fireworks/models/kimi-k3', Decimal('3'), Decimal('0.3'), Decimal('15')),
        ('accounts/fireworks/routers/glm-5p1-fast', Decimal('2.8'), Decimal('0.52'), Decimal('8.8')),
        ('accounts/fireworks/routers/glm-5p2-fast', Decimal('2.1'), Decimal('0.21'), Decimal('6.6')),
        ('accounts/fireworks/routers/glm-5p2-fast-us', Decimal('2.1'), Decimal('0.21'), Decimal('6.6')),
        ('accounts/fireworks/routers/kimi-k2p6-fast', Decimal('2'), Decimal('0.3'), Decimal('8')),
        ('accounts/fireworks/routers/kimi-k2p7-code-fast', Decimal('1.9'), Decimal('0.38'), Decimal('8')),
        ('accounts/fireworks/routers/kimi-k3-fast', Decimal('4.5'), Decimal('0.45'), Decimal('22.5')),
        ('accounts/fireworks/routers/kimi-k3-us', Decimal('3.3'), Decimal('0.33'), Decimal('16.5')),
        ('accounts/fireworks/models/gpt-oss-120b', Decimal('0.15'), Decimal('0.014'), Decimal('0.6')),
        ('accounts/fireworks/models/gpt-oss-20b', Decimal('0.07'), Decimal('0.035'), Decimal('0.3')),
    ],
)
def test_fireworks_serverless_prices(
    model_ref: str,
    input_rate: Decimal,
    cache_read_rate: Decimal,
    output_rate: Decimal,
) -> None:
    price = calc_price(
        Usage(input_tokens=2_000_000, cache_read_tokens=1_000_000, output_tokens=1_000_000),
        model_ref=model_ref,
    )

    assert price.provider.id == 'fireworks'
    assert price.input_price == input_rate + cache_read_rate
    assert price.output_price == output_rate
    assert price.total_price == input_rate + cache_read_rate + output_rate


def test_moonshotai_kimi_k27_code_price():
    price = calc_price(
        Usage(input_tokens=1_000, cache_read_tokens=100, output_tokens=100),
        model_ref='kimi-k2.7-code',
        provider_id='moonshotai',
    )

    assert price.model.id == 'kimi-k2.7-code'
    assert price.input_price == Decimal('0.000874')
    assert price.output_price == Decimal('0.0004')
    assert price.total_price == Decimal('0.001274')


def test_openrouter_kimi_k27_code_price():
    price = calc_price(
        Usage(input_tokens=1_000, cache_read_tokens=100, output_tokens=100),
        model_ref='moonshotai/kimi-k2.7-code',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'moonshotai/kimi-k2.7-code'
    assert price.input_price == Decimal('0.000691')
    assert price.output_price == Decimal('0.00035')
    assert price.total_price == Decimal('0.001041')


def test_openrouter_kimi_k27_code_dated_price():
    price = calc_price(
        Usage(input_tokens=2_038_030, output_tokens=13_034),
        model_ref='moonshotai/kimi-k2.7-code-20260612',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'moonshotai/kimi-k2.7-code'
    assert price.input_price == Decimal('1.5285225')
    assert price.output_price == Decimal('0.0456190')
    assert price.total_price == Decimal('1.5741415')


def test_modal_kimi_k3_price_by_provider_id() -> None:
    price = calc_price(
        Usage(input_tokens=2_000_000, cache_read_tokens=1_000_000, output_tokens=1_000_000),
        model_ref='moonshotai/Kimi-K3',
        provider_id='modal',
    )

    assert_modal_kimi_k3_price(price)


def test_modal_kimi_k3_price_by_api_url() -> None:
    price = calc_price(
        Usage(input_tokens=2_000_000, cache_read_tokens=1_000_000, output_tokens=1_000_000),
        model_ref='moonshotai/Kimi-K3',
        provider_api_url='https://example--kimi-k3.modal.run/v1',
    )

    assert_modal_kimi_k3_price(price)


def test_modal_api_url_does_not_match_spoofed_hostname() -> None:
    with pytest.raises(
        LookupError,
        match="Unable to find provider provider_api_url='https://example.modal.run.evil.test/v1'",
    ):
        calc_price(
            Usage(input_tokens=1),
            model_ref='moonshotai/Kimi-K3',
            provider_api_url='https://example.modal.run.evil.test/v1',
        )


def test_modal_inkling_nvfp4_price() -> None:
    price = calc_price(
        Usage(input_tokens=2_000_000, cache_read_tokens=1_000_000, output_tokens=1_000_000),
        model_ref='thinkingmachines/Inkling-NVFP4',
        provider_id='modal',
    )

    assert price.provider.id == 'modal'
    assert price.model.id == 'thinkingmachines/Inkling-NVFP4'
    assert price.input_price == Decimal('1.47')
    assert price.output_price == Decimal('5')
    assert price.total_price == Decimal('6.47')


def assert_modal_kimi_k3_price(price: PriceCalculation) -> None:
    assert price.provider.id == 'modal'
    assert price.model.id == 'moonshotai/Kimi-K3'
    assert price.input_price == Decimal('3.3')
    assert price.output_price == Decimal('15')
    assert price.total_price == Decimal('18.3')


def test_openrouter_glm_51_dated_price():
    price = calc_price(
        Usage(input_tokens=27_447, output_tokens=83),
        model_ref='z-ai/glm-5.1-20260406',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'z-ai/glm-5.1'
    assert price.input_price == Decimal('0.02689806')
    assert price.output_price == Decimal('0.00025564')
    assert price.total_price == Decimal('0.02715370')


def test_openrouter_glm_52_dated_price():
    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref='z-ai/glm-5.2-20260616',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'z-ai/glm-5.2'
    assert price.input_price == Decimal('0.0014')
    assert price.output_price == Decimal('0.00044')
    assert price.total_price == Decimal('0.00184')


def test_openrouter_glm_53_dated_price():
    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref='z-ai/glm-5.3-20260816',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'z-ai/glm-5.3'
    assert price.input_price == Decimal('0.0014')
    assert price.output_price == Decimal('0.00044')
    assert price.total_price == Decimal('0.00184')


def test_zhipuai_glm_52_price():
    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref='glm-5.2',
        provider_id='zhipuai',
    )

    assert price.model.id == 'GLM-5.2'
    assert price.input_price == Decimal('0.001103')
    assert price.output_price == Decimal('0.0003862')
    assert price.total_price == Decimal('0.0014892')


@pytest.mark.parametrize(
    'provider_api_url',
    [
        'https://api.z.ai/api/paas/v4',
        'https://api.z.ai/api/coding/paas/v4',
    ],
)
def test_zai_glm_52_price(provider_api_url: str):
    price = calc_price(
        Usage(input_tokens=1_000, cache_read_tokens=600, output_tokens=100),
        model_ref='glm-5.2',
        provider_api_url=provider_api_url,
    )

    assert price.provider.id == 'zai'
    assert price.model.id == 'GLM-5.2'
    assert price.input_price == Decimal('0.000716')
    assert price.output_price == Decimal('0.00044')
    assert price.total_price == Decimal('0.001156')


@pytest.mark.parametrize(
    'provider_api_url',
    [
        'https://api.z.ai/api/paas/v4',
        'https://api.z.ai/api/coding/paas/v4',
    ],
)
def test_zai_glm_53_price(provider_api_url: str):
    price = calc_price(
        Usage(input_tokens=1_000, cache_read_tokens=600, output_tokens=100),
        model_ref='glm-5.3',
        provider_api_url=provider_api_url,
    )

    assert price.provider.id == 'zai'
    assert price.model.id == 'GLM-5.3'
    assert price.input_price == Decimal('0.000716')
    assert price.output_price == Decimal('0.00044')
    assert price.total_price == Decimal('0.001156')


@pytest.mark.parametrize(
    ('model_ref', 'model_id'),
    [('glm-4.7', 'GLM-4.7'), ('glm-5.2', 'GLM-5.2')],
)
def test_zai_does_not_shadow_zhipuai_model_matching(model_ref: str, model_id: str):
    price = calc_price(Usage(input_tokens=1_000, output_tokens=100), model_ref=model_ref)

    assert price.provider.id == 'zhipuai'
    assert price.model.id == model_id


def test_bare_glm_53_ref_is_claimed_by_zhipuai():
    """zhipuai claims every `glm-*` ref, so GLM-5.3 needs an explicit provider until Zhipu publishes its CNY rates."""
    with pytest.raises(LookupError, match="Unable to find model with model_ref='glm-5.3' in zhipuai"):
        calc_price(Usage(input_tokens=1_000, output_tokens=100), model_ref='glm-5.3')


def test_openrouter_modern_dated_aliases_price():
    for model_ref, model_id, input_price, output_price, total_price in [
        (
            'minimax/minimax-m3-20260531',
            'minimax/minimax-m3',
            Decimal('0.0003'),
            Decimal('0.00012'),
            Decimal('0.00042'),
        ),
        (
            'qwen/qwen3.7-plus-20260602',
            'qwen/qwen3.7-plus',
            Decimal('0.0004'),
            Decimal('0.00016'),
            Decimal('0.00056'),
        ),
    ]:
        price = calc_price(
            Usage(input_tokens=1_000, output_tokens=100),
            model_ref=model_ref,
            provider_api_url='https://openrouter.ai/api/v1',
        )

        assert price.model.id == model_id
        assert price.input_price == input_price
        assert price.output_price == output_price
        assert price.total_price == total_price


@pytest.mark.parametrize('model_ref', ['deepseek/deepseek-v3.2', 'google/gemini-2.5-flash-lite'])
def test_openrouter_api_model_refs_priceable_by_api_url(model_ref: str):
    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref=model_ref,
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == model_ref
    assert price.provider.id == 'openrouter'


def test_tiered_prices():
    price = calc_price(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='google')
    # Google uses threshold-based pricing: if context > 128K, ALL tokens charged at tier price
    # (0.15 * 500000) / 1_000_000 = 0.075

    assert price.input_price == snapshot(Decimal('0.075'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.075'))
    assert price.model.name == snapshot('gemini 1.5 flash')
    assert price.provider.id == snapshot('google')


def test_model_price_str_tiered_prices_include_dollar_prefix():
    model_price = ModelPrice(input_mtok=TieredPrices(base=Decimal('2.5'), tiers=[]))
    assert str(model_price) == '$2.5/input MTok (+tiers)'


def test_model_price_str_requests_and_private_state() -> None:
    model_price = ModelPrice(requests_kcount=Decimal('2'))
    object.__setattr__(model_price, '_private_state', Decimal('3'))

    assert str(model_price) == '$2 / K requests'


@pytest.mark.parametrize(
    ('price', 'expected'),
    [
        (ModelPrice(web_searches_kcount=Decimal('10')), '$10/web searches K'),
        (ModelPrice(audio_hours=Decimal('1')), '$1/audio Hour'),
        (ModelPrice(input_gpixels=Decimal('2')), '$2/input pixels G'),
        (ModelPrice(input_document_kpages=Decimal('3')), '$3/input document pages K'),
        (
            ModelPrice(web_searches_kcount=TieredPrices(base=Decimal('10'), tiers=[])),
            '$10/web searches K (+tiers)',
        ),
    ],
)
def test_model_price_str_uses_registered_unit_labels(price: ModelPrice, expected: str) -> None:
    assert str(price) == expected


def test_model_price_str_preserves_tiered_unregistered_price_fallback() -> None:
    price = ModelPrice(hovercraft_mtok=TieredPrices(base=Decimal('1'), tiers=[]))

    assert str(price) == '$1/hovercraft MTok (+tiers)'


def test_calc_price_warns_and_ignores_unregistered_dynamic_extra() -> None:
    price = ModelPrice(hovercraft_mtok=Decimal('NaN'))

    with pytest.warns(UserWarning, match='Unsupported price key for standard pricing: hovercraft_mtok'):
        result = price.calc_price(Usage(input_tokens=1))

    assert result == {
        'input_price': Decimal(0),
        'output_price': Decimal(0),
        'total_price': Decimal(0),
    }


@pytest.mark.parametrize('price', [Decimal('-1'), Decimal('NaN'), Decimal('Infinity')])
def test_calc_price_rejects_invalid_recognized_flat_price(price: Decimal) -> None:
    with pytest.raises(
        ValueError,
        match='Invalid price value for input_mtok: expected a finite non-negative Decimal or valid tiered prices',
    ):
        ModelPrice(input_mtok=price).calc_price(Usage(input_tokens=1))


@pytest.mark.parametrize(
    'price',
    [
        TieredPrices(base=Decimal('-1'), tiers=[]),
        TieredPrices(base=Decimal('NaN'), tiers=[]),
        TieredPrices(base=Decimal('1'), tiers=[Tier(start=-1, price=Decimal('2'))]),
        TieredPrices(base=Decimal('1'), tiers=[Tier(start=100, price=Decimal('-2'))]),
        TieredPrices(base=Decimal('1'), tiers=[Tier(start=100, price=Decimal('Infinity'))]),
    ],
)
def test_calc_price_rejects_invalid_recognized_tiered_price(price: TieredPrices) -> None:
    with pytest.raises(
        ValueError,
        match='Invalid price value for input_mtok: expected a finite non-negative Decimal or valid tiered prices',
    ):
        ModelPrice(input_mtok=price).calc_price(Usage(input_tokens=1))


def test_calc_price_rejects_dynamic_descendant_without_ancestors() -> None:
    price = ModelPrice(cache_image_read_mtok=Decimal('1'))

    with pytest.raises(ValueError, match='Missing ancestor price for cache_image_read_tokens'):
        price.calc_price(Usage(cache_image_read_tokens=1))


def test_set_custom_snapshot_does_not_validate_dynamic_model_prices() -> None:
    snapshot = DataSnapshot(
        providers=[
            Provider(
                id='testing',
                name='Testing',
                api_pattern='testing',
                models=[
                    ModelInfo(
                        id='bad-extra',
                        match=ClauseEquals('bad-extra'),
                        prices=ModelPrice(hovercraft_mtok=Decimal('1')),
                    )
                ],
            )
        ],
        from_auto_update=False,
    )

    try:
        set_custom_snapshot(snapshot)
        assert get_snapshot() is snapshot
    finally:
        set_custom_snapshot(None)


def test_requests_kcount_prices():
    # request count defaults to 1
    price = calc_price(Usage(), model_ref='sonar', provider_id='perplexity')
    assert price.input_price == snapshot(Decimal('0'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.012'))
    assert price.model.name == snapshot('Sonar')
    assert price.provider.name == snapshot('Perplexity')


def test_claude_opus_5_web_search_price():
    price = calc_price(Usage(web_searches=2), model_ref='claude-opus-5', provider_id='anthropic')

    assert price.input_price == Decimal('0')
    assert price.output_price == Decimal('0')
    assert price.total_price == Decimal('0.02')


def test_claude_opus_5_one_hour_cache_write_price():
    price = calc_price(
        Usage(input_tokens=1_000_000, cache_write_tokens=1_000_000, cache_write_1h_tokens=1_000_000),
        model_ref='claude-opus-5',
        provider_id='anthropic',
    )

    assert price.input_price == Decimal('10')


def test_claude_opus_5_five_minute_cache_write_price():
    """No shipped model prices `cache_write_5m_mtok`, so a 5m breakdown bills at the generic cache write rate."""
    price = calc_price(
        Usage(input_tokens=1_000_000, cache_write_tokens=1_000_000, cache_write_5m_tokens=1_000_000),
        model_ref='claude-opus-5',
        provider_id='anthropic',
    )

    assert price.input_price == Decimal('6.25')


def test_five_minute_cache_write_price_decomposes_alongside_one_hour():
    price = ModelPrice(
        input_mtok=Decimal('5'),
        cache_write_mtok=Decimal('6.25'),
        cache_write_5m_mtok=Decimal('6.25'),
        cache_write_1h_mtok=Decimal('10'),
    ).calc_price(
        Usage(
            input_tokens=1_000_000,
            cache_write_tokens=1_000_000,
            cache_write_5m_tokens=600_000,
            cache_write_1h_tokens=400_000,
        )
    )

    # 600k at the 5m rate + 400k at the 1h rate, leaving nothing at the generic cache write or base input rates.
    assert price['input_price'] == Decimal('7.75')
    assert price['output_price'] == Decimal('0')
    assert price['total_price'] == Decimal('7.75')


def test_distinct_output_category_prices_replace_aggregate_output_rate():
    price = calc_price(
        Usage(output_tokens=100, output_reasoning_tokens=25, output_citation_tokens=10),
        model_ref='sonar-deep-research',
        provider_id='perplexity',
    )

    # 65 ordinary tokens at $8/MTok + 25 reasoning at $3/MTok + 10 citations at $2/MTok.
    assert price.output_price == Decimal('0.000615')
    assert price.total_price == Decimal('0.000615')


def test_custom_model_price_can_override_reasoning_rate():
    price = ModelPrice(output_mtok=Decimal('8'), output_reasoning_mtok=Decimal('3')).calc_price(
        Usage(output_tokens=100, output_reasoning_tokens=25)
    )

    assert price['output_price'] == Decimal('0.000675')
    assert price['total_price'] == Decimal('0.000675')


def test_calc_unit_price_handles_absent_price_or_count() -> None:
    assert calc_unit_price(None, 500, total_input_tokens=0, per=1_000) == Decimal(0)
    assert calc_unit_price(Decimal('2.5'), None, total_input_tokens=0, per=1_000) == Decimal(0)


def test_calc_unit_price_handles_tiered_prices() -> None:
    price = TieredPrices(base=Decimal('1'), tiers=[Tier(start=100, price=Decimal('2'))])

    assert calc_unit_price(price, 10, total_input_tokens=100, per=1_000) == Decimal('0.01')
    assert calc_unit_price(price, 10, total_input_tokens=101, per=1_000) == Decimal('0.02')


def test_calc_unit_price_uses_non_million_normalization_factor() -> None:
    assert calc_unit_price(Decimal('12'), 2, total_input_tokens=0, per=1_000) == Decimal('0.024')


def test_calc_unit_price_uses_shortest_decimal_fractional_count() -> None:
    assert calc_unit_price(Decimal('3.6'), 0.1, total_input_tokens=0, per=3_600) == Decimal('0.0001')


def test_calc_unit_price_uses_decimal_fractional_count_directly() -> None:
    assert calc_unit_price(Decimal('3.6'), Decimal('0.1'), total_input_tokens=0, per=3_600) == Decimal('0.0001')


def test_model_price_handles_fractional_duration() -> None:
    price = ModelPrice(audio_hours=Decimal('3.6')).calc_price(Usage(audio_seconds=0.1))

    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.0001'),
    }


def test_model_price_handles_decimal_duration() -> None:
    price = ModelPrice(audio_hours=Decimal('3.6')).calc_price(Usage(audio_seconds=Decimal('0.1')))

    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.0001'),
    }


# Rate for the unit under test, and a deliberately different rate for the ancestor prices it must be
# accompanied by: the unit under test consumes the whole reported count, so ancestors must bill nothing.
UNIT_UNDER_TEST_RATE = Decimal('3')
ANCESTOR_RATE = Decimal('7')

REGISTRY_USAGE_KEYS = sorted(_get_registry().units)
NON_DIRECTIONAL_USAGE_KEYS = sorted(
    usage_key for usage_key, unit in _get_registry().units.items() if 'direction' not in unit.dimensions
)


def _minimal_priced_units(unit: UnitDef, registry: UnitRegistry) -> list[UnitDef]:
    """`unit` plus every ancestor price the validator requires alongside it.

    Every join of two of those ancestors is itself an ancestor of `unit`, so ancestors alone satisfy
    `validate_priced_units`; this test fails if a newly registered unit breaks that.
    """
    ancestor_keys = sorted(registry.ancestor_usage_keys(unit.usage_key))
    return [unit, *(registry.units[ancestor_key] for ancestor_key in ancestor_keys)]


def _minimal_model_price(unit: UnitDef, priced_units: list[UnitDef]) -> ModelPrice:
    return ModelPrice(
        **{
            priced_unit.price_key: UNIT_UNDER_TEST_RATE if priced_unit is unit else ANCESTOR_RATE
            for priced_unit in priced_units
        }
    )


def _usage_of_one_unit(unit: UnitDef, priced_units: list[UnitDef]) -> Usage:
    """Report `unit.per` for the unit under test and every ancestor, so all of it decomposes to `unit`."""
    return Usage(
        **{priced_unit.usage_key: unit.per for priced_unit in priced_units if priced_unit.usage_key != 'requests'}
    )


def _expected_price(unit: UnitDef) -> Decimal:
    # `requests` is not a reportable usage key: the engine always prices exactly one request.
    count = 1 if unit.usage_key == 'requests' else unit.per
    return UNIT_UNDER_TEST_RATE * count / unit.per


@pytest.mark.parametrize('usage_key', REGISTRY_USAGE_KEYS)
def test_every_registry_unit_prices_end_to_end(usage_key: str) -> None:
    """Every unit in the registry produces a non-zero price, whether or not any shipped model uses it."""
    registry = _get_registry()
    unit = registry.units[usage_key]
    priced_units = _minimal_priced_units(unit, registry)
    expected = _expected_price(unit)

    price = _minimal_model_price(unit, priced_units).calc_price(_usage_of_one_unit(unit, priced_units))

    assert price['total_price'] == expected > Decimal(0)
    direction = unit.dimensions.get('direction')
    assert price['input_price'] == (expected if direction == 'input' else Decimal(0))
    assert price['output_price'] == (expected if direction == 'output' else Decimal(0))


def test_non_directional_units_inventory() -> None:
    assert NON_DIRECTIONAL_USAGE_KEYS == [
        'audio_seconds',
        'code_executions',
        'requests',
        'rerank_searches',
        'social_searches',
        'storage_searches',
        'web_searches',
    ]


@pytest.mark.parametrize('usage_key', NON_DIRECTIONAL_USAGE_KEYS)
def test_non_directional_units_excluded_from_input_and_output_price(usage_key: str) -> None:
    """A unit with no `direction` dimension bills into `total_price` only, so input + output < total."""
    registry = _get_registry()
    unit = registry.units[usage_key]
    priced_units = _minimal_priced_units(unit, registry)
    expected = _expected_price(unit)

    price = _minimal_model_price(unit, priced_units).calc_price(_usage_of_one_unit(unit, priced_units))

    assert price['input_price'] == Decimal(0)
    assert price['output_price'] == Decimal(0)
    assert price['total_price'] == expected > Decimal(0)
    assert price['input_price'] + price['output_price'] != price['total_price']


def test_price_constraint_before():
    price = calc_price(Usage(input_tokens=1000), model_ref='o3', genai_request_timestamp=datetime(2025, 6, 1))
    assert price.input_price == snapshot(Decimal('0.01'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.01'))
    assert price.model.name == snapshot('o3')
    assert price.provider.name == snapshot('OpenAI')


def test_price_constraint_after():
    price = calc_price(Usage(input_tokens=1000), model_ref='o3')
    assert price.input_price == snapshot(Decimal('0.002'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.002'))
    assert price.model.name == snapshot('o3')
    assert price.provider.name == snapshot('OpenAI')


def test_price_constraint_time_of_date():
    price = calc_price(
        Usage(input_tokens=100_000_000),
        model_ref='deepseek-chat',
        genai_request_timestamp=datetime(2025, 6, 1, 16, tzinfo=timezone.utc),
    )
    assert price.input_price == snapshot(Decimal('27.00'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('27'))
    assert price.model.name == snapshot('DeepSeek Chat')
    assert price.provider.name == snapshot('Deepseek')
    price = calc_price(
        Usage(input_tokens=100_000_000),
        model_ref='deepseek-chat',
        genai_request_timestamp=datetime(2025, 6, 1, 17, tzinfo=timezone.utc),
    )
    assert price.input_price == snapshot(Decimal('13.500'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('13.5'))
    assert price.model.name == snapshot('DeepSeek Chat')
    assert price.provider.name == snapshot('Deepseek')


@pytest.mark.parametrize(
    ('genai_request_timestamp', 'expected_input_mtok'),
    [
        # 02:00 on the start date at +05:00 is still 2026-08-31 in UTC, so the old price applies.
        pytest.param(
            datetime(2026, 9, 1, 2, tzinfo=timezone(timedelta(hours=5))),
            Decimal('2'),
            id='start-date-local-day-utc-day-before',
        ),
        pytest.param(
            datetime(2026, 8, 31, 21, tzinfo=timezone.utc),
            Decimal('2'),
            id='same-instant-expressed-in-utc',
        ),
        # 20:00 the day before the start date at -05:00 is already 2026-09-01 in UTC.
        pytest.param(
            datetime(2026, 8, 31, 20, tzinfo=timezone(timedelta(hours=-5))),
            Decimal('3'),
            id='start-date-local-day-before-utc-day-of',
        ),
        pytest.param(
            datetime(2026, 9, 1, 1, tzinfo=timezone.utc),
            Decimal('3'),
            id='same-instant-expressed-in-utc-after',
        ),
        pytest.param(datetime(2026, 8, 31, 23, 59), Decimal('2'), id='naive-before'),
        pytest.param(datetime(2026, 9, 1), Decimal('3'), id='naive-at-boundary'),
    ],
)
def test_start_date_constraint_compares_the_utc_date(
    genai_request_timestamp: datetime, expected_input_mtok: Decimal
) -> None:
    """The boundary is UTC midnight, not the caller's wall-clock midnight, matching the JS package."""
    model = ModelInfo(
        id='start-date-model',
        match=ClauseEquals('start-date-model'),
        prices=[
            ConditionalPrice(prices=ModelPrice(input_mtok=Decimal('2'))),
            ConditionalPrice(
                constraint=StartDateConstraint(start_date=date(2026, 9, 1)),
                prices=ModelPrice(input_mtok=Decimal('3')),
            ),
        ],
    )

    assert model.get_prices(genai_request_timestamp).input_mtok == expected_input_mtok


@pytest.mark.parametrize(
    ('provider_id', 'model_ref', 'expected_input_mtok'),
    [
        ('anthropic', 'claude-sonnet-5', Decimal('2')),
        ('aws', 'global.anthropic.claude-sonnet-5-v1:0', Decimal('2')),
        ('aws', 'us.anthropic.claude-sonnet-5-v1:0', Decimal('2.2')),
        ('openrouter', 'anthropic/claude-sonnet-5', Decimal('2')),
    ],
)
def test_claude_sonnet_5_price_does_not_increase(
    provider_id: str,
    model_ref: str,
    expected_input_mtok: Decimal,
) -> None:
    price = calc_price(
        Usage(input_tokens=1_000_000),
        model_ref=model_ref,
        provider_id=provider_id,
        genai_request_timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert price.input_price == expected_input_mtok
    assert price.total_price == expected_input_mtok


@pytest.mark.parametrize(
    ('model_ref', 'request_timestamp', 'expected_output_price'),
    [
        ('voxtral-small-2507', datetime(2026, 8, 10, tzinfo=timezone.utc), Decimal('0.3')),
        ('voxtral-small-latest', datetime(2026, 8, 11, tzinfo=timezone.utc), Decimal('0.4')),
    ],
)
def test_mistral_voxtral_small_price_change(
    model_ref: str,
    request_timestamp: datetime,
    expected_output_price: Decimal,
) -> None:
    price = calc_price(
        Usage(output_tokens=1_000_000),
        model_ref=model_ref,
        provider_id='mistral',
        genai_request_timestamp=request_timestamp,
    )

    assert price.model.id == 'voxtral-small-24b-2507'
    assert price.output_price == expected_output_price
    assert price.total_price == expected_output_price


@pytest.mark.parametrize(
    ('model_ref', 'request_timestamp', 'expected_model_id', 'expected_input_price', 'expected_output_price'),
    [
        (
            'ministral-8b-2410',
            datetime(2026, 8, 24, tzinfo=timezone.utc),
            'ministral-8b',
            Decimal('0.1'),
            Decimal('0.1'),
        ),
        (
            'ministral-8b-2512',
            datetime(2026, 8, 24, tzinfo=timezone.utc),
            'ministral-8b-2512',
            Decimal('0.15'),
            Decimal('0.15'),
        ),
        (
            'ministral-8b-latest',
            datetime(2025, 12, 1, tzinfo=timezone.utc),
            'ministral-8b-latest',
            Decimal('0.1'),
            Decimal('0.1'),
        ),
        (
            'ministral-8b-latest',
            datetime(2025, 12, 2, tzinfo=timezone.utc),
            'ministral-8b-latest',
            Decimal('0.15'),
            Decimal('0.15'),
        ),
        (
            'mistral-medium-2312',
            datetime(2025, 6, 15, tzinfo=timezone.utc),
            'mistral-medium-2312',
            Decimal('2.7'),
            Decimal('8.1'),
        ),
        (
            'mistral-medium-2505',
            datetime(2026, 8, 24, tzinfo=timezone.utc),
            'mistral-medium-3-1',
            Decimal('0.4'),
            Decimal('2'),
        ),
        (
            'mistral-medium-2508',
            datetime(2026, 8, 24, tzinfo=timezone.utc),
            'mistral-medium-3-1',
            Decimal('0.4'),
            Decimal('2'),
        ),
        (
            'mistral-medium-3.5',
            datetime(2026, 8, 24, tzinfo=timezone.utc),
            'mistral-medium-3-5',
            Decimal('1.5'),
            Decimal('7.5'),
        ),
        (
            'mistral-medium-3-5',
            datetime(2026, 8, 24, tzinfo=timezone.utc),
            'mistral-medium-3-5',
            Decimal('1.5'),
            Decimal('7.5'),
        ),
        (
            'mistral-medium-3',
            datetime(2026, 8, 24, tzinfo=timezone.utc),
            'mistral-medium-3-5',
            Decimal('1.5'),
            Decimal('7.5'),
        ),
        (
            'mistral-medium-latest',
            datetime(2026, 6, 15, tzinfo=timezone.utc),
            'mistral-medium-latest',
            Decimal('0.4'),
            Decimal('2'),
        ),
        (
            'mistral-medium-latest',
            datetime(2026, 6, 16, tzinfo=timezone.utc),
            'mistral-medium-latest',
            Decimal('1.5'),
            Decimal('7.5'),
        ),
    ],
)
def test_mistral_versioned_model_prices(
    model_ref: str,
    request_timestamp: datetime,
    expected_model_id: str,
    expected_input_price: Decimal,
    expected_output_price: Decimal,
) -> None:
    price = calc_price(
        Usage(input_tokens=1_000_000, output_tokens=1_000_000),
        model_ref=model_ref,
        provider_id='mistral',
        genai_request_timestamp=request_timestamp,
    )

    assert price.model.id == expected_model_id
    assert price.input_price == expected_input_price
    assert price.output_price == expected_output_price
    assert price.total_price == expected_input_price + expected_output_price


@pytest.mark.parametrize(
    ('model_ref', 'request_timestamp'),
    [
        ('mistral-medium-2508', datetime(2026, 8, 24, tzinfo=timezone.utc)),
        ('mistral-medium-latest', datetime(2026, 6, 15, tzinfo=timezone.utc)),
    ],
)
def test_mistral_medium_3_cached_input_price(model_ref: str, request_timestamp: datetime) -> None:
    price = calc_price(
        Usage(input_tokens=1_000_000, cache_read_tokens=1_000_000),
        model_ref=model_ref,
        provider_id='mistral',
        genai_request_timestamp=request_timestamp,
    )

    assert price.input_price == Decimal('0.04')
    assert price.total_price == Decimal('0.04')


@pytest.mark.parametrize(
    ('model_ref', 'request_timestamp', 'expected_model_id', 'expected_page_price', 'expected_annotated_page_price'),
    [
        (
            'mistral-ocr-2503-completion',
            datetime(2025, 3, 6, tzinfo=timezone.utc),
            'mistral-ocr-2503',
            Decimal('1'),
            Decimal('1'),
        ),
        (
            'mistral-ocr-2505',
            datetime(2025, 5, 22, tzinfo=timezone.utc),
            'mistral-ocr-2505',
            Decimal('1'),
            Decimal('3'),
        ),
        (
            'mistral-ocr-2512-completion',
            datetime(2025, 12, 18, tzinfo=timezone.utc),
            'mistral-ocr-2512',
            Decimal('2'),
            Decimal('3'),
        ),
        (
            'mistral-ocr-4-0',
            datetime(2026, 6, 23, tzinfo=timezone.utc),
            'mistral-ocr-4-0',
            Decimal('4'),
            Decimal('5'),
        ),
        (
            'mistral-ocr-4',
            datetime(2026, 7, 16, tzinfo=timezone.utc),
            'mistral-ocr-4-1',
            Decimal('4'),
            Decimal('5'),
        ),
        (
            'mistral-ocr-latest',
            datetime(2025, 3, 6, tzinfo=timezone.utc),
            'mistral-ocr-latest',
            Decimal('1'),
            Decimal('1'),
        ),
        (
            'mistral-ocr-latest',
            datetime(2025, 5, 22, tzinfo=timezone.utc),
            'mistral-ocr-latest',
            Decimal('1'),
            Decimal('3'),
        ),
        (
            'mistral-ocr-latest',
            datetime(2025, 12, 17, tzinfo=timezone.utc),
            'mistral-ocr-latest',
            Decimal('1'),
            Decimal('3'),
        ),
        (
            'mistral-ocr-latest',
            datetime(2025, 12, 18, tzinfo=timezone.utc),
            'mistral-ocr-latest',
            Decimal('2'),
            Decimal('3'),
        ),
        (
            'mistral-ocr-latest',
            datetime(2026, 6, 23, tzinfo=timezone.utc),
            'mistral-ocr-latest',
            Decimal('4'),
            Decimal('5'),
        ),
    ],
)
def test_mistral_ocr_prices(
    model_ref: str,
    request_timestamp: datetime,
    expected_model_id: str,
    expected_page_price: Decimal,
    expected_annotated_page_price: Decimal,
) -> None:
    page_price = calc_price(
        Usage(input_document_pages=1_000),
        model_ref=model_ref,
        provider_id='mistral',
        genai_request_timestamp=request_timestamp,
    )
    annotated_page_price = calc_price(
        Usage(input_document_pages=1_000, input_annotated_document_pages=1_000),
        model_ref=model_ref,
        provider_id='mistral',
        genai_request_timestamp=request_timestamp,
    )

    assert page_price.model.id == expected_model_id
    assert page_price.input_price == expected_page_price
    assert page_price.total_price == expected_page_price
    assert annotated_page_price.input_price == expected_annotated_page_price
    assert annotated_page_price.total_price == expected_annotated_page_price


def test_voxtral_provider_inference() -> None:
    price = calc_price(Usage(output_tokens=1), model_ref='voxtral-small-latest')

    assert price.provider.id == 'mistral'
    assert price.model.id == 'voxtral-small-24b-2507'


def test_qualified_openrouter_voxtral_model_does_not_infer_mistral() -> None:
    model_ref = 'mistralai/voxtral-small-24b-2507'

    with pytest.raises(LookupError, match=f"Unable to find provider with model matching '{model_ref}'"):
        calc_price(Usage(output_tokens=1), model_ref=model_ref)

    price = calc_price(
        Usage(output_tokens=1),
        model_ref=model_ref,
        provider_api_url='https://openrouter.ai/api/v1',
    )
    assert price.provider.id == 'openrouter'
    assert price.model.id == model_ref


@pytest.mark.parametrize(
    ('genai_request_timestamp', 'expected_input_price'),
    [
        # DeepSeek's off-peak window is 00:30:00Z-16:30:00Z; a naive timestamp is read as UTC.
        (datetime(2025, 6, 1, 16), Decimal('27.00')),
        (datetime(2025, 6, 1, 17), Decimal('13.500')),
    ],
)
def test_time_of_date_constraint_reads_naive_timestamp_as_utc(
    genai_request_timestamp: datetime, expected_input_price: Decimal
) -> None:
    price = calc_price(
        Usage(input_tokens=100_000_000),
        model_ref='deepseek-chat',
        genai_request_timestamp=genai_request_timestamp,
    )

    assert price.input_price == expected_input_price


def _midnight_spanning_model() -> ModelInfo:
    """A model whose off-peak window wraps around midnight; no shipped model has one."""
    return ModelInfo(
        id='wrapping-window',
        match=ClauseEquals('wrapping-window'),
        prices=[
            ConditionalPrice(prices=ModelPrice(input_mtok=Decimal('1'))),
            ConditionalPrice(
                TimeOfDateConstraint(
                    start_time=time(22, tzinfo=timezone.utc),
                    end_time=time(6, tzinfo=timezone.utc),
                ),
                prices=ModelPrice(input_mtok=Decimal('0.5')),
            ),
        ],
    )


@pytest.mark.parametrize(
    ('genai_request_timestamp', 'expected_input_mtok'),
    [
        (datetime(2026, 7, 30, 23, tzinfo=timezone.utc), Decimal('0.5')),
        (datetime(2026, 7, 30, 3, tzinfo=timezone.utc), Decimal('0.5')),
        (datetime(2026, 7, 30, 22, tzinfo=timezone.utc), Decimal('0.5')),
        (datetime(2026, 7, 30, 6, tzinfo=timezone.utc), Decimal('1')),
        (datetime(2026, 7, 30, 12, tzinfo=timezone.utc), Decimal('1')),
    ],
)
def test_time_of_date_constraint_spanning_midnight(
    genai_request_timestamp: datetime, expected_input_mtok: Decimal
) -> None:
    model = _midnight_spanning_model()

    assert model.get_prices(genai_request_timestamp) == ModelPrice(input_mtok=expected_input_mtok)


def test_time_of_date_constraint_spanning_midnight_reads_naive_timestamp_as_utc() -> None:
    model = _midnight_spanning_model()

    assert model.get_prices(datetime(2026, 7, 30, 23)) == ModelPrice(input_mtok=Decimal('0.5'))
    assert model.get_prices(datetime(2026, 7, 30, 12)) == ModelPrice(input_mtok=Decimal('1'))


def _naive_window_model() -> ModelInfo:
    return ModelInfo(
        id='naive-window',
        match=ClauseEquals('naive-window'),
        prices=[
            ConditionalPrice(prices=ModelPrice(input_mtok=Decimal('1'))),
            ConditionalPrice(
                TimeOfDateConstraint(start_time=time(0, 30), end_time=time(16, 30)),
                prices=ModelPrice(input_mtok=Decimal('0.5')),
            ),
        ],
    )


@pytest.mark.parametrize(
    'genai_request_timestamp',
    [
        datetime(2026, 7, 30, 12),
        datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
        # 18:00+02:00 is 16:00Z (inside). Local 18:00 is outside 00:30–16:30, so a wall-clock compare fails.
        datetime(2026, 7, 30, 18, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_time_of_date_constraint_naive_window_is_utc(genai_request_timestamp: datetime) -> None:
    """A naive constraint window is UTC, same as a naive request timestamp."""
    model = _naive_window_model()

    assert model.get_prices(genai_request_timestamp) == ModelPrice(input_mtok=Decimal('0.5'))
    assert model.get_prices(datetime(2026, 7, 30, 17)) == ModelPrice(input_mtok=Decimal('1'))


@pytest.mark.parametrize('offset_hours', [-11, -5, 0, 5, 9, 14])
@pytest.mark.parametrize('hour', range(24))
def test_time_of_date_constraint_is_offset_independent(offset_hours: int, hour: int) -> None:
    """The same instant must price the same however the caller's timezone expresses it.

    Comparing an offset-aware `timetz()` directly does not survive an offset that crosses midnight,
    which silently picked the wrong side of DeepSeek's off-peak window for non-UTC callers.
    """
    tz = timezone(timedelta(hours=offset_hours))
    local = datetime(2026, 1, 15, hour, tzinfo=tz)

    usage = Usage(input_tokens=1_000)
    local_price = calc_price(usage, model_ref='deepseek-chat', provider_id='deepseek', genai_request_timestamp=local)
    utc_price = calc_price(
        usage,
        model_ref='deepseek-chat',
        provider_id='deepseek',
        genai_request_timestamp=local.astimezone(timezone.utc),
    )

    assert local_price.total_price == utc_price.total_price


# An unanchored `api_pattern` must not match a provider host that merely appears inside the URL.
PROXIED_OPENAI_API_URL = 'http://localhost:8080/proxy?u=https://api.openai.com/v1'


def test_provider_api_url_matching_is_anchored():
    expected_error = re.escape(f"Unable to find provider provider_api_url='{PROXIED_OPENAI_API_URL}'")
    with pytest.raises(LookupError, match=expected_error):
        calc_price(Usage(input_tokens=1_000), model_ref='gpt-4o', provider_api_url=PROXIED_OPENAI_API_URL)


def test_provider_api_url_matches_at_the_start_of_the_url():
    price = calc_price(
        Usage(input_tokens=1_000),
        model_ref='gpt-4o',
        provider_api_url='https://api.openai.com/v1/chat/completions',
    )

    assert price.provider.id == 'openai'


@pytest.mark.parametrize(
    'model_ref,model_name,off_peak,peak',
    [
        ('deepseek-v4-flash', 'DeepSeek V4 Flash', Decimal('22.00'), Decimal('44.00')),
        ('deepseek-v4-pro', 'DeepSeek V4 Pro', Decimal('66.00'), Decimal('132.00')),
    ],
)
@pytest.mark.parametrize(
    'hour,is_peak',
    [
        (0, False),
        (1, True),
        (4, False),
        (5, False),
        (6, True),
        (9, True),
        (10, False),
        (23, False),
    ],
)
def test_price_constraint_two_time_of_date_windows(
    model_ref: str,
    model_name: str,
    off_peak: Decimal,
    peak: Decimal,
    hour: int,
    is_peak: bool,
):
    """Deepseek V4 charges peak rates in two disjoint daily windows, so it has two constrained prices."""
    price = calc_price(
        Usage(input_tokens=100_000_000),
        model_ref=model_ref,
        genai_request_timestamp=datetime(2026, 8, 20, hour, tzinfo=timezone.utc),
    )
    assert price.input_price == (peak if is_peak else off_peak)
    assert price.model.name == model_name
    assert price.provider.name == 'Deepseek'


@pytest.mark.parametrize(
    'model_ref,historic,peak',
    [
        ('deepseek-v4-flash', Decimal('14.00'), Decimal('44.00')),
        ('deepseek-v4-pro', Decimal('43.50'), Decimal('132.00')),
    ],
)
@pytest.mark.parametrize(
    'hour,in_peak_window',
    [
        (0, False),
        (2, True),
        (12, False),
        (23, False),
    ],
)
def test_price_deepseek_v4_before_repricing(
    model_ref: str,
    historic: Decimal,
    peak: Decimal,
    hour: int,
    in_peak_window: bool,
):
    """Before 2026-08-17 the V4 models were billed at a single flat rate.

    That rate is the unconstrained first price, so it is preserved for the 17 hours a day that fall
    outside the two peak windows. `constraint` is a union, so the peak entries cannot also be gated
    on a start date, and during those windows a pre-repricing request still resolves to the peak
    rate - see https://github.com/pydantic/genai-prices/issues/582.
    """
    price = calc_price(
        Usage(input_tokens=100_000_000),
        model_ref=model_ref,
        genai_request_timestamp=datetime(2026, 5, 1, hour, tzinfo=timezone.utc),
    )
    assert price.input_price == (peak if in_peak_window else historic)


@pytest.mark.parametrize(
    'model_ref,first_long_token,base_input,long_input',
    [
        ('grok-4.5', 200_000, Decimal('2'), Decimal('4')),
        ('grok-4.3', 200_000, Decimal('1.25'), Decimal('2.5')),
        ('grok-4.20', 200_000, Decimal('1.25'), Decimal('2.5')),
        ('grok-build-0.1', 200_000, Decimal('1'), Decimal('2')),
        ('gpt-5.5', 272_001, Decimal('5'), Decimal('10')),
        ('gpt-5.5-pro', 272_001, Decimal('30'), Decimal('60')),
    ],
)
def test_price_long_context_cliff(model_ref: str, first_long_token: int, base_input: Decimal, long_input: Decimal):
    """xAI and OpenAI bill long-context requests as a cliff, not a marginal tier."""
    under = calc_price(Usage(input_tokens=first_long_token - 1), model_ref=model_ref)
    assert under.input_price == (first_long_token - 1) * base_input / 1_000_000

    over = calc_price(Usage(input_tokens=first_long_token), model_ref=model_ref)
    assert over.input_price == first_long_token * long_input / 1_000_000
    assert over.input_price > under.input_price * Decimal('1.99')


def test_price_long_context_cliff_is_not_marginal():
    """Pin the cliff against the marginal reading on a request well past the threshold."""
    price = calc_price(Usage(input_tokens=1_000_000), model_ref='gpt-5.5')
    assert price.input_price == Decimal('10')
    marginal = Decimal('272000') * Decimal('5') / 1_000_000 + Decimal('728000') * Decimal('10') / 1_000_000
    assert price.input_price != marginal


def test_provider_not_found_id():
    with pytest.raises(LookupError, match="Unable to find provider provider_id='foobar'"):
        calc_price(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='foobar')


def test_provider_not_found_url():
    with pytest.raises(LookupError, match="Unable to find provider provider_api_url='foobar'"):
        calc_price(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_api_url='foobar')


def test_provider_not_found_model_ref():
    with pytest.raises(LookupError, match="Unable to find provider with model matching 'llama2-70b-4096'"):
        calc_price(Usage(input_tokens=500_000), model_ref='llama2-70b-4096')


@pytest.mark.parametrize(
    ('model_ref', 'expected_model_id', 'expected_total_price'),
    [
        ('pixtral-12b-latest', 'pixtral-12b', Decimal('0.000165')),
        ('pixtral-large-2411', 'pixtral-large', Decimal('0.0026')),
        ('mixtral-8x7b-instruct-v0.1', 'mixtral-8x7b', Decimal('0.00077')),
    ],
)
def test_mistral_models_found_without_provider(
    model_ref: str, expected_model_id: str, expected_total_price: Decimal
) -> None:
    price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref=model_ref)

    assert price.provider.id == 'mistral'
    assert price.model.id == expected_model_id
    assert price.total_price == expected_total_price


def test_model_not_found():
    with pytest.raises(LookupError, match="Unable to find model with model_ref='wrong' in google"):
        calc_price(Usage(input_tokens=500_000), model_ref='wrong', provider_id='google')


EXAMPLES: list[tuple[str, str, Decimal]] = [
    # ('openrouter', 'amazon/us.amazon.nova-micro-v1:0'),
    # ('openrouter', 'amazon/us.amazon.nova-pro-v1:0'),
    ('anthropic', 'anthropic.claude-v2', snapshot(Decimal('0.0104'))),
    ('anthropic', 'claude-3-5-haiku-123', snapshot(Decimal('0.0012'))),
    ('anthropic', 'claude-3-5-haiku-20241022', snapshot(Decimal('0.0012'))),
    ('anthropic', 'claude-3-5-haiku-latest', snapshot(Decimal('0.0012'))),
    ('anthropic', 'claude-3-5-sonnet-20241022', snapshot(Decimal('0.0045'))),
    ('anthropic', 'claude-3-5-sonnet-latest', snapshot(Decimal('0.0045'))),
    ('anthropic', 'claude-3-7-sonnet-20250219', snapshot(Decimal('0.0045'))),
    ('anthropic', 'claude-3-7-sonnet-latest', snapshot(Decimal('0.0045'))),
    ('anthropic', 'claude-3-opus-20240229', snapshot(Decimal('0.0225'))),
    ('anthropic', 'claude-opus-4-20250514', snapshot(Decimal('0.0225'))),
    ('anthropic', 'claude-opus-4-20250514', snapshot(Decimal('0.0225'))),
    ('anthropic', 'claude-opus-4-0', snapshot(Decimal('0.0225'))),
    ('cohere', 'command-r7b-12-2024', snapshot(Decimal('0.0000525'))),
    ('deepseek', 'deepseek-r1-distill-llama-70b', snapshot(Decimal('0.000769'))),
    ('google', 'gemini-1.5-flash-002', snapshot(Decimal('0.000105'))),
    ('google', 'gemini-1.5-flash-123', snapshot(Decimal('0.000105'))),
    ('google', 'gemini-1.5-flash', snapshot(Decimal('0.000105'))),
    ('google', 'gemini-1.5-pro-002', snapshot(Decimal('0.00175'))),
    ('google', 'gemini-2.0-flash-exp', snapshot(Decimal('0.00014'))),
    ('google', 'gemini-2.0-flash-thinking-exp-01-21', snapshot(Decimal('0.00014'))),
    ('google', 'gemini-2.0-flash', snapshot(Decimal('0.00014'))),
    ('google', 'gemini-2.5-pro-preview-03-25', snapshot(Decimal('0.00225'))),
    # ('openrouter', 'meta-llama/llama-3.3-70b-versatile'),
    # ('openrouter', 'meta-llama/llama-4-scout-17b-16e-instruct'),
    ('mistral', 'mistral-small-latest', snapshot(Decimal('0.00013'))),
    ('mistral', 'pixtral-12b-latest', snapshot(Decimal('0.000165'))),
    ('openai', 'gpt-3.5-turbo-0125', snapshot(Decimal('0.00065'))),
    ('openai', 'gpt-3.5-turbo-instruct:20230824-v2', snapshot(Decimal('0.0017'))),
    ('openai', 'gpt-4-0613', snapshot(Decimal('0.036'))),
    ('openai', 'gpt-4.1-2025-04-14', snapshot(Decimal('0.0028'))),
    ('openai', 'gpt-4.1-mini-2025-04-14', snapshot(Decimal('0.00056'))),
    ('openai', 'gpt-4.1-mini', snapshot(Decimal('0.00056'))),
    ('openai', 'gpt-4.1-nano-2025-04-14', snapshot(Decimal('0.00014'))),
    ('openai', 'gpt-4.5-preview-2025-02-27', snapshot(Decimal('0.090'))),
    ('openai', 'gpt-4o-2024-08-06', snapshot(Decimal('0.0035'))),
    ('openai', 'gpt-4o-2024-11-20', snapshot(Decimal('0.0035'))),
    ('openai', 'gpt-4o-audio-preview-2024-10-01', snapshot(Decimal('0.0035'))),
    ('openai', 'gpt-4o-audio-preview-2024-12-17', snapshot(Decimal('0.0035'))),
    ('openai', 'gpt-4o-mini-2024-07-18', snapshot(Decimal('0.00021'))),
    ('openai', 'gpt-4o-mini', snapshot(Decimal('0.00021'))),
    ('openai', 'gpt-4o', snapshot(Decimal('0.0035'))),
    ('openai', 'o3-mini-2025-01-31', snapshot(Decimal('0.00154'))),
    ('openai', 'gpt-5.4', snapshot(Decimal('0.0040'))),
    ('openai', 'gpt-5.4-pro', snapshot(Decimal('0.048'))),
    ('openai', 'gpt-5.6-sol', snapshot(Decimal('0.008'))),
    ('openai', 'gpt-5.6-terra', snapshot(Decimal('0.0032'))),
    ('openai', 'gpt-5.6-luna', snapshot(Decimal('0.00032'))),
    ('openai', 'text-embedding-3-small', snapshot(Decimal('0.00002'))),
]


@pytest.mark.parametrize('provider,model,expected_total_price', EXAMPLES)
def test_models_found(provider: str, model: str, expected_total_price: Decimal):
    price = calc_price(
        Usage(input_tokens=1000, output_tokens=100),
        model_ref=model,
        provider_id=provider,
        # Pinned so the snapshots stay stable: some of these models price by time of day or start date.
        genai_request_timestamp=datetime(2026, 7, 30, 12, tzinfo=timezone.utc),
    )

    assert price.total_price == expected_total_price


def test_all_bundled_models_have_a_priceable_public_ref():
    assert not _unpriceable_model_refs(providers)


def test_unpriceable_model_refs_reports_public_ref_errors():
    test_providers = [
        Provider(
            id='test-provider',
            name='Test Provider',
            api_pattern='https://example.com',
            models=[
                ModelInfo(
                    id='test-model',
                    match=ClauseRegex('^test-model$'),
                    prices=ModelPrice(input_mtok=Decimal('1')),
                )
            ],
        )
    ]

    assert _unpriceable_model_refs(test_providers) == [
        "test-provider/test-model: test-model: LookupError: Unable to find provider provider_id='test-provider'"
    ]


def _unpriceable_model_refs(test_providers: list[Provider]) -> list[str]:
    failures: list[str] = []
    usage = Usage(input_tokens=1000, cache_read_tokens=10, cache_write_tokens=10, output_tokens=100)

    for provider in test_providers:
        for model in provider.models:
            candidate_refs = dict.fromkeys([model.id, *_example_model_refs(model.match)])
            errors: list[str] = []

            for model_ref in candidate_refs:
                try:
                    calc_price(usage, model_ref=model_ref, provider_id=provider.id)
                except Exception as exc:
                    errors.append(f'{model_ref}: {type(exc).__name__}: {exc}')
                else:
                    break
            else:
                failures.append(f'{provider.id}/{model.id}: {"; ".join(errors)}')

    return failures


def _example_model_refs(match: MatchLogic) -> list[str]:
    if isinstance(match, ClauseEquals):
        return [match.equals]
    elif isinstance(match, ClauseStartsWith):
        return [match.starts_with]
    elif isinstance(match, ClauseEndsWith):
        return [match.ends_with]
    elif isinstance(match, ClauseContains):
        return [match.contains]
    elif isinstance(match, ClauseRegex):
        return []
    elif isinstance(match, ClauseOr):
        refs: list[str] = []
        for clause in match.or_:
            refs.extend(_example_model_refs(clause))
        return refs
    ref = ''
    for clause in match.and_:
        clause_refs = _example_model_refs(clause)
        if not clause_refs:
            return []
        ref += clause_refs[0]
    return [ref]


def test_example_model_refs_handles_regex_and_and_clauses():
    assert _example_model_refs(ClauseRegex('^test$')) == []
    assert _example_model_refs(ClauseAnd([ClauseStartsWith('test-'), ClauseEndsWith('model')])) == ['test-model']
    assert _example_model_refs(ClauseAnd([ClauseStartsWith('test-'), ClauseRegex('model')])) == []


def test_complex_usage():
    # Based on https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash
    # Input price
    #   $0.30 (text / image / video)
    #   $1.00 (audio)
    # Output price (including thinking tokens)
    #   $2.50
    # Context caching price
    #   $0.03 (text / image / video)
    #   $0.10 (audio)

    mil = 1_000_000
    assert calc_price(
        Usage(input_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('0.3'))

    # input_audio_tokens == input_tokens means all tokens are audio tokens
    assert calc_price(
        Usage(input_tokens=mil, input_audio_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('1.0'))

    assert calc_price(
        Usage(output_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('2.5'))

    # All cached text tokens
    assert calc_price(
        Usage(input_tokens=mil, cache_read_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('0.03'))

    # All cached audio tokens
    assert calc_price(
        Usage(input_tokens=mil, input_audio_tokens=mil, cache_read_tokens=mil, cache_audio_read_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('0.10'))

    cached_text_tokens = 1
    uncached_text_tokens = 1_000
    cached_audio_tokens = 1_000_000
    uncached_audio_tokens = 1_000_000_000
    cached_tokens = cached_text_tokens + cached_audio_tokens
    audio_tokens = uncached_audio_tokens + cached_audio_tokens
    total_input_tokens = cached_text_tokens + uncached_text_tokens + cached_audio_tokens + uncached_audio_tokens
    assert total_input_tokens == 1_001_001_001

    assert (
        calc_price(
            Usage(
                input_tokens=total_input_tokens,
                input_audio_tokens=audio_tokens,
                cache_read_tokens=cached_tokens,
                cache_audio_read_tokens=cached_audio_tokens,
            ),
            'gemini-2.5-flash',
        ).total_price
        == snapshot(Decimal('1000.100_300_03'))
        == Decimal('0.03') * cached_text_tokens / mil
        + Decimal('0.3') * uncached_text_tokens / mil
        + Decimal('0.1') * cached_audio_tokens / mil
        + Decimal('1.0') * uncached_audio_tokens / mil
    )


@pytest.mark.parametrize(
    ('model_ref', 'input_mtok', 'output_mtok'),
    [
        ('gemini-2.5-flash-lite-preview-tts', Decimal('0.5'), Decimal('10')),
        ('gemini-2.5-flash-tts', Decimal('0.5'), Decimal('10')),
        ('gemini-2.5-flash-preview-tts', Decimal('0.5'), Decimal('10')),
        ('gemini-2.5-pro-tts', Decimal('1'), Decimal('20')),
        ('gemini-2.5-pro-preview-tts', Decimal('1'), Decimal('20')),
    ],
)
def test_gemini_tts_prices(model_ref: str, input_mtok: Decimal, output_mtok: Decimal) -> None:
    price = calc_price(
        Usage(input_tokens=1_000_000, output_tokens=1_000_000, output_audio_tokens=1_000_000),
        model_ref,
        provider_id='google',
    )

    assert price.input_price == input_mtok
    assert price.output_price == output_mtok


@pytest.mark.parametrize(
    ('model_ref', 'expected_model_id'),
    [
        ('GEMINI-2.5-FLASH-LITE-PREVIEW-06-17', 'gemini-2.5-flash-lite'),
        ('GEMINI-2.5-PRO', 'gemini-2.5-pro'),
    ],
)
def test_gemini_tts_matching_preserves_case_insensitive_generic_models(model_ref: str, expected_model_id: str) -> None:
    price = calc_price(Usage(input_tokens=1), model_ref, provider_id='google')

    assert price.model.id == expected_model_id


def test_output_audio_usage():
    mil = 1_000_000

    assert calc_price(
        Usage(output_tokens=mil),
        'gpt-4o-realtime-preview',
    ).total_price == snapshot(Decimal('20.0'))

    # All audio tokens
    assert calc_price(
        Usage(output_tokens=mil, output_audio_tokens=mil),
        'gpt-4o-realtime-preview',
    ).total_price == snapshot(Decimal('80.0'))

    output_text_tokens = mil
    output_audio_tokens = mil * 1000
    total_output_tokens = output_text_tokens + output_audio_tokens
    assert (
        calc_price(
            Usage(output_tokens=total_output_tokens, output_audio_tokens=output_audio_tokens),
            'gpt-4o-realtime-preview',
        ).total_price
        == snapshot(Decimal('80020.0'))
        == Decimal('20') * output_text_tokens / mil + Decimal('80') * output_audio_tokens / mil
    )


def test_grok_4_6_long_context_cliff():
    """Grok 4.6 bills the whole request at the long-context rate, not just the tokens past 200k.

    Ref: https://docs.x.ai/docs/models/grok-4.6 - "billed at the higher rate for all tokens in
    the request". Pinning both sides of the threshold: reading it as a marginal tier would put
    a 500k-token prompt at $1.40 instead of $2.00.
    """
    # The boundary is inclusive on xAI's side (">= 200k prompt tokens") but a tier here
    # fires on `tokens > start`, so the threshold is pinned from both directions: one
    # token below stays on the base rate, exactly 200k is already on the higher one.
    under = calc_price(Usage(input_tokens=199_999), 'grok-4.6', provider_id='x-ai')
    assert under.input_price == snapshot(Decimal('0.399998'))

    at = calc_price(Usage(input_tokens=200_000), 'grok-4.6', provider_id='x-ai')
    assert at.input_price == snapshot(Decimal('0.8'))

    # One more token roughly doubles the bill; under marginal pricing it would barely move.
    assert at.input_price > under.input_price * 2 - Decimal('0.0001')

    full = calc_price(Usage(input_tokens=500_000), 'grok-4.6', provider_id='x-ai')
    assert full.input_price == snapshot(Decimal('2.0'))
    assert full.input_price != Decimal('200000') * 2 / 1_000_000 + Decimal('300000') * 4 / 1_000_000

    mixed = calc_price(
        Usage(input_tokens=300_000, cache_read_tokens=10_000, output_tokens=1_000),
        'grok-4.6',
        provider_id='x-ai',
    )
    assert mixed.total_price == snapshot(Decimal('1.182'))
