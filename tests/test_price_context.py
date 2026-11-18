from __future__ import annotations

import json
import warnings
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest

from genai_prices import UpdatePrices, Usage, calc_price, extract_usage
from genai_prices.data_snapshot import set_custom_snapshot
from genai_prices.types import AbstractUsage, CalcPrice, ModelPrice, PriceVariant
from prices import prices_types
from prices.build import load_units
from prices.export_validation import validate_export_payload

FIXTURE: dict[str, Any] = json.loads((Path(__file__).parent / 'fixtures/price_context.json').read_text())


@pytest.fixture
def context_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    def get(url: str, timeout: httpx2.Timeout) -> httpx2.Response:
        assert timeout is not None
        return httpx2.Response(200, json=FIXTURE['providers'], request=httpx2.Request('GET', url))

    monkeypatch.setattr(httpx2, 'get', get)
    set_custom_snapshot(UpdatePrices().fetch())


@pytest.mark.usefixtures('context_prices')
@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['name'])
def test_price_context_contract(case: dict[str, Any]) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        result = calc_price(
            Usage(**FIXTURE['usage']),
            'context-model',
            provider_id='testing',
            genai_request_timestamp=datetime.fromisoformat(case['timestamp'].replace('Z', '+00:00')),
            price_context=case.get('context'),
        )
    assert result.input_price == Decimal(str(case['input']))
    assert result.output_price == Decimal(str(case['output']))
    assert result.total_price == Decimal(str(case['total']))
    assert caught == []


@pytest.mark.parametrize(
    'model,tier,total',
    [
        ('o3', 'flex', '4.8125'),
        ('o3', 'priority', '16.84375'),
        ('o4-mini', 'flex', '2.647'),
        ('o4-mini', 'priority', '9.625'),
        ('gpt-5-mini', 'flex', '1.096875'),
        ('gpt-6.1-sol', 'fast', '36.1'),
        ('gpt-6.1-sol', 'priority', '36.1'),
        ('gpt-6.1-terra', 'flex', '4.5125'),
        ('gpt-6.1-terra', 'fast', '18.05'),
        ('gpt-6.1-terra', 'priority', '18.05'),
    ],
)
def test_openai_service_tiers(model: str, tier: str, total: str) -> None:
    result = calc_price(
        Usage(input_tokens=1_000_000, cache_read_tokens=250_000, output_tokens=1_000_000),
        model,
        provider_id='openai',
        genai_request_timestamp=datetime(2026, 10, 26),
        price_context={'service_tier': tier},
    )
    assert result.total_price == Decimal(total)


@pytest.mark.parametrize(
    'provider,model,timestamp,total',
    [
        ('openai', 'o3', datetime(2026, 10, 14), '4.875'),
        ('anthropic', 'claude-sonnet-5', datetime(2026, 10, 14), '5.775'),
        ('google', 'gemini-4-argon', datetime(2026, 10, 14), '5.7625'),
        ('google', 'gemini-4-argon', datetime(2026, 12, 1), '11.525'),
        ('google', 'gemini-4-carbon', datetime(2026, 11, 16), '5.7625'),
        ('google', 'gemini-4-carbon', datetime(2026, 12, 1), '11.525'),
        ('google', 'gemini-4-hydrogen', datetime(2026, 11, 15), '8.64375'),
        ('google', 'gemini-4-hydrogen', datetime(2026, 11, 16), '4.321875'),
        ('groq', 'openai/gpt-oss-120b', datetime(2026, 10, 14), '0.375'),
        ('mistral', 'mistral-small-2603', datetime(2026, 10, 14), '0.358125'),
        ('x-ai', 'grok-4.3', datetime(2026, 10, 14), '5.58'),
    ],
)
def test_batch_processing(provider: str, model: str, timestamp: datetime, total: str) -> None:
    result = calc_price(
        Usage(input_tokens=1_000_000, cache_read_tokens=250_000, output_tokens=1_000_000),
        model,
        provider_id=provider,
        genai_request_timestamp=timestamp,
        price_context={'processing': 'batch'},
    )
    assert result.total_price == Decimal(total)


@pytest.mark.parametrize(
    'model,context,input_tokens,total',
    [
        ('gpt-6.2-astra', {'service_tier': 'default'}, 200_000, '5.24'),
        ('gpt-6.2-astra', {'service_tier': 'default'}, 1_000_000, '21.28'),
        ('gpt-6.2-astra', {'service_tier': 'fast'}, 200_000, '10.48'),
        ('gpt-6.2-astra', {'service_tier': 'fast'}, 1_000_000, '42.56'),
        ('gpt-6.2-astra', {'service_tier': 'priority'}, 200_000, '10.48'),
        ('gpt-6.2-astra', {'service_tier': 'priority'}, 1_000_000, '42.56'),
        ('gpt-6.2-astra', {'processing': 'batch'}, 200_000, '2.62'),
        ('gpt-6.2-astra', {'processing': 'batch'}, 1_000_000, '10.64'),
        ('gpt-6.2-sol', {'service_tier': 'default'}, 200_000, '1.31'),
        ('gpt-6.2-sol', {'service_tier': 'default'}, 1_000_000, '5.32'),
        ('gpt-6.2-sol', {'service_tier': 'fast'}, 200_000, '2.62'),
        ('gpt-6.2-sol', {'service_tier': 'fast'}, 1_000_000, '10.64'),
        ('gpt-6.2-sol', {'service_tier': 'priority'}, 200_000, '2.62'),
        ('gpt-6.2-sol', {'service_tier': 'priority'}, 1_000_000, '10.64'),
        ('gpt-6.2-sol', {'processing': 'batch'}, 200_000, '0.655'),
        ('gpt-6.2-sol', {'processing': 'batch'}, 1_000_000, '2.66'),
    ],
)
def test_openai_gpt_6_2_price_variants(model: str, context: dict[str, str], input_tokens: int, total: str) -> None:
    """Base and long-context (>272K input) rates for every GPT-6.2 variant, on the release date."""
    result = calc_price(
        Usage(input_tokens=input_tokens, cache_read_tokens=50_000, cache_write_tokens=10_000, output_tokens=100_000),
        model,
        provider_id='openai',
        genai_request_timestamp=datetime(2026, 11, 17),
        price_context=context,
    )
    assert result.total_price == Decimal(total)


@pytest.mark.parametrize(
    'model,timestamp,input_tokens,total',
    [
        ('gpt-6.2-astra', datetime(2026, 11, 17), 200_000, '15.72'),
        ('gpt-6.2-astra', datetime(2026, 11, 17), 1_000_000, '63.84'),
        ('gpt-6.2-astra', datetime(2027, 2, 28), 200_000, '15.72'),
        ('gpt-6.2-astra', datetime(2027, 3, 1), 200_000, '31.44'),
        ('gpt-6.2-astra', datetime(2027, 3, 1), 1_000_000, '127.68'),
        ('gpt-6.2-sol', datetime(2026, 11, 17), 200_000, '3.93'),
        ('gpt-6.2-sol', datetime(2026, 11, 17), 1_000_000, '15.96'),
        ('gpt-6.2-sol', datetime(2027, 2, 28), 200_000, '3.93'),
        ('gpt-6.2-sol', datetime(2027, 3, 1), 200_000, '7.86'),
        ('gpt-6.2-sol', datetime(2027, 3, 1), 1_000_000, '31.92'),
    ],
)
def test_openai_gpt_6_2_ultrafast(model: str, timestamp: datetime, input_tokens: int, total: str) -> None:
    """Ultrafast is 3x Standard through 2027-02-28 and 6x from 2027-03-01, for the same context length."""
    result = calc_price(
        Usage(input_tokens=input_tokens, cache_read_tokens=50_000, cache_write_tokens=10_000, output_tokens=100_000),
        model,
        provider_id='openai',
        genai_request_timestamp=timestamp,
        price_context={'service_tier': 'ultrafast'},
    )
    assert result.total_price == Decimal(total)


@pytest.mark.parametrize(
    'model,tier,timestamp,total',
    [
        ('gemini-4-hydrogen', 'flex', datetime(2026, 11, 15), '8.64375'),
        ('gemini-4-hydrogen', 'flex', datetime(2026, 11, 16), '4.321875'),
        ('gemini-4-hydrogen', 'priority', datetime(2026, 11, 15), '8.64375'),
        ('gemini-4-hydrogen', 'priority', datetime(2026, 11, 16), '15.55875'),
        ('gemini-4-carbon', 'flex', datetime(2026, 11, 16), '5.7625'),
        ('gemini-4-carbon', 'flex', datetime(2026, 12, 1), '11.525'),
        ('gemini-4-carbon', 'priority', datetime(2026, 11, 16), '20.745'),
        ('gemini-4-carbon', 'priority', datetime(2026, 12, 1), '41.49'),
        ('gemini-4-argon', 'flex', datetime(2026, 10, 13), '11.525'),
        ('gemini-4-argon', 'flex', datetime(2026, 10, 14), '5.7625'),
        ('gemini-4-argon', 'flex', datetime(2026, 12, 1), '11.525'),
        ('gemini-4-argon', 'priority', datetime(2026, 10, 13), '11.525'),
        ('gemini-4-argon', 'priority', datetime(2026, 10, 14), '20.745'),
        ('gemini-4-argon', 'priority', datetime(2026, 12, 1), '41.49'),
    ],
)
def test_google_gemini_4_service_tiers(model: str, tier: str, timestamp: datetime, total: str) -> None:
    result = calc_price(
        Usage(input_tokens=1_000_000, cache_read_tokens=250_000, output_tokens=1_000_000),
        model,
        provider_id='google',
        genai_request_timestamp=timestamp,
        price_context={'service_tier': tier},
    )
    assert result.total_price == Decimal(total)


@pytest.mark.parametrize(
    'model,tier,timestamp,total',
    [
        ('gemini-2.5-flash', 'flex', datetime(2026, 11, 16), '2.7325'),
        ('gemini-2.5-flash', 'flex', datetime(2026, 11, 17), '1.37'),
        ('gemini-2.5-flash', 'priority', datetime(2026, 11, 17), '4.9185'),
        ('gemini-2.5-pro', 'flex', datetime(2026, 11, 17), '8.5'),
        ('gemini-2.5-pro', 'priority', datetime(2026, 11, 17), '30.4875'),
        ('gemini-3.1-pro-preview', 'priority', datetime(2026, 11, 17), '37.98'),
        ('gemini-3.5-flash-lite', 'priority', datetime(2026, 11, 17), '4.9175'),
        ('gemini-3.8-flash', 'flex', datetime(2026, 11, 17), '2.165625'),
        ('gemini-3.8-flash', 'flex', datetime(2027, 1, 1), '4.33125'),
        ('gemini-3.8-flash', 'priority', datetime(2026, 11, 17), '7.79625'),
        ('gemini-3.8-flash', 'priority', datetime(2027, 1, 1), '15.5925'),
    ],
)
def test_google_gemini_flex_and_priority_tiers(model: str, tier: str, timestamp: datetime, total: str) -> None:
    """Flex and Priority rates verified on 2026-11-17; earlier requests keep standard rates."""
    result = calc_price(
        Usage(input_tokens=1_000_000, cache_read_tokens=250_000, output_tokens=1_000_000),
        model,
        provider_id='google',
        genai_request_timestamp=timestamp,
        price_context={'service_tier': tier},
    )
    assert result.total_price == Decimal(total)


@pytest.mark.parametrize(
    'model,input_tokens,cache_read_tokens,input_price,output_price',
    [
        ('o4-mini', 100_000, 100_000, '0.0138', '2.2'),
        ('gpt-5.4', 272_000, 272_000, '0.03536', '7.5'),
        ('gpt-5.4', 272_001, 272_001, '0.06800025', '11.25'),
        ('gpt-5.5-pro', 272_000, 0, '4.08', '90'),
        ('gpt-5.5-pro', 272_001, 0, '4.080015', '90'),
    ],
)
def test_openai_published_flex_rates(
    model: str, input_tokens: int, cache_read_tokens: int, input_price: str, output_price: str
) -> None:
    result = calc_price(
        Usage(input_tokens=input_tokens, cache_read_tokens=cache_read_tokens, output_tokens=1_000_000),
        model,
        provider_id='openai',
        genai_request_timestamp=datetime(2026, 10, 12),
        price_context={'service_tier': 'flex'},
    )
    assert result.input_price == Decimal(input_price)
    assert result.output_price == Decimal(output_price)


def test_extracted_context_and_no_mutation() -> None:
    response = {
        'model': 'o3',
        'service_tier': 'flex',
        'usage': {'prompt_tokens': 1_000_000, 'completion_tokens': 1_000_000},
    }
    extracted = extract_usage(response, provider_id='openai', api_flavor='chat')
    for tier, total in [('flex', '5'), ('default', '10'), ('priority', '17.5'), ('flex', '5')]:
        assert extracted.calc_price(
            price_context={'service_tier': tier}, genai_request_timestamp=datetime(2026, 10, 12)
        ).total_price == Decimal(total)


def test_unresearched_tier_history_and_unsupported_model() -> None:
    for model, timestamp in [('o3', datetime(2026, 10, 11)), ('text-embedding-3-small', datetime(2026, 10, 12))]:
        standard = calc_price(
            Usage(input_tokens=1_000_000), model, provider_id='openai', genai_request_timestamp=timestamp
        )
        result = calc_price(
            Usage(input_tokens=1_000_000),
            model,
            provider_id='openai',
            genai_request_timestamp=timestamp,
            price_context={'service_tier': 'flex'},
        )
        assert result.total_price == standard.total_price


def test_fallback_provider_does_not_inherit_tier_rates() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    timestamp = datetime(2026, 10, 12)
    standard = calc_price(usage, 'gpt-5', provider_id='azure', genai_request_timestamp=timestamp)
    assert standard.total_price == Decimal('11.25')
    for context in [None, {}, {'service_tier': 'priority'}]:
        result = calc_price(
            usage, 'gpt-5', provider_id='azure', genai_request_timestamp=timestamp, price_context=context
        )
        assert result.provider.id == 'azure'
        assert result.total_price == standard.total_price


@pytest.mark.parametrize('when', [{}, {'service_tier': None}, {'service_tier': True}, {1: 'flex'}])
def test_invalid_variant_condition(when: Any) -> None:
    with pytest.raises(ValueError, match='Price variant when'):
        PriceVariant(when=when, prices=ModelPrice(input_mtok=Decimal('1')))


def test_variant_export_validation() -> None:
    provider = prices_types.Provider.model_validate(FIXTURE['providers'][0])
    validate_export_payload([provider], load_units())
    assert provider.models[0].price_variants is not None
    provider.models[0].price_variants[0].prices = prices_types.ModelPrice.model_validate({'cache_image_read_mtok': 1})
    with pytest.raises(ValueError, match='Invalid price variant'):
        validate_export_payload([provider], load_units())


@pytest.mark.parametrize(
    'second_when,first_constraint,second_constraint,valid',
    [
        ({'inference_geo': 'us'}, None, None, False),
        ({'service_tier': 'priority'}, None, None, True),
        (
            {'inference_geo': 'us'},
            {'start_time': '00:00:00Z', 'end_time': '06:00:00Z'},
            {'start_time': '06:00:00Z', 'end_time': '12:00:00Z'},
            True,
        ),
        (
            {'inference_geo': 'us'},
            {'start_time': '22:00:00Z', 'end_time': '06:00:00Z'},
            {'start_time': '08:00:00+02:00', 'end_time': '14:00:00+02:00'},
            True,
        ),
        (
            {'inference_geo': 'us'},
            {'start_time': '22:00:00Z', 'end_time': '06:00:00Z'},
            {'start_time': '23:00:00Z', 'end_time': '07:00:00Z'},
            False,
        ),
        (
            {'inference_geo': 'us'},
            None,
            {'start_time': '00:00:00Z', 'end_time': '00:00:00Z'},
            True,
        ),
    ],
)
def test_variant_export_validation_covers_combined_overrides(
    second_when: dict[str, str],
    first_constraint: dict[str, str] | None,
    second_constraint: dict[str, str] | None,
    valid: bool,
) -> None:
    provider = prices_types.Provider.model_validate(
        {
            'id': 'example',
            'name': 'Example',
            'api_pattern': 'example',
            'models': [
                {
                    'id': 'm',
                    'match': {'equals': 'm'},
                    'prices': {'input_mtok': 1},
                    'price_variants': [
                        {
                            'when': {'service_tier': 'flex'},
                            'constraint': first_constraint,
                            'prices': {'cache_read_mtok': 1},
                        },
                        {'when': second_when, 'constraint': second_constraint, 'prices': {'input_image_mtok': 1}},
                    ],
                }
            ],
        }
    )
    if valid:
        validate_export_payload([provider], load_units())
    else:
        with pytest.raises(ValueError, match='Missing join price'):
            validate_export_payload([provider], load_units())


def test_variant_export_validation_covers_later_variant_alone() -> None:
    provider = prices_types.Provider.model_validate(
        {
            'id': 'example',
            'name': 'Example',
            'api_pattern': 'example',
            'models': [
                {
                    'id': 'm',
                    'match': {'equals': 'm'},
                    'prices': {'input_mtok': 1},
                    'price_variants': [
                        {'when': {'service_tier': 'flex'}, 'prices': {'input_audio_mtok': 1}},
                        {'when': {'inference_geo': 'us'}, 'prices': {'cache_read_mtok': 1, 'cache_audio_read_mtok': 1}},
                    ],
                }
            ],
        }
    )
    with pytest.raises(ValueError, match='Invalid price variant.*Missing ancestor price'):
        validate_export_payload([provider], load_units())


def test_variant_preserves_model_price_subclass() -> None:
    from genai_prices.types import ClauseEquals, ModelInfo, Provider

    class CustomPrice(ModelPrice):
        def calc_price(self, usage: AbstractUsage) -> CalcPrice:
            result = super().calc_price(usage)
            result['total_price'] += Decimal('1')
            return result

    model = ModelInfo(
        id='custom',
        match=ClauseEquals('custom'),
        prices=CustomPrice(input_mtok=Decimal('4')),
        price_variants=[PriceVariant({'service_tier': 'flex'}, ModelPrice(input_mtok=Decimal('2')))],
    )
    provider = Provider(id='custom', name='Custom', api_pattern='custom', models=[model])
    assert (
        model.calc_price(Usage(input_tokens=1_000_000), provider, price_context={'service_tier': 'flex'}).total_price
        == 3
    )
    assert model.calc_price(Usage(input_tokens=1_000_000), provider).total_price == 5
