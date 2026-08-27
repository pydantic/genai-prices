from copy import copy
from datetime import date, datetime
from decimal import Decimal

import pytest

from genai_prices import Usage, calc_price
from genai_prices.types import (
    ClauseEquals,
    ConditionalPrice,
    ModelInfo,
    ModelPrice,
    StartDateConstraint,
    Tier,
    TieredPrices,
)

MILLION = Decimal(1_000_000)
THOUSAND = Decimal(1_000)


def mtok(rate: str, tokens: int) -> Decimal:
    return Decimal(rate) * tokens / MILLION


@pytest.mark.parametrize('model_ref', ['command-a', 'command-a-03-2025'])
def test_cohere_command_a_known_ids(model_ref: str) -> None:
    price = calc_price(Usage(input_tokens=1), model_ref=model_ref, provider_id='cohere')

    assert price.model.id == 'command-a'


def test_cohere_command_a_variants_do_not_use_command_a_prices() -> None:
    with pytest.raises(LookupError, match="Unable to find model with model_ref='command-a-plus-05-2026' in cohere"):
        calc_price(Usage(input_tokens=1), model_ref='command-a-plus-05-2026', provider_id='cohere')


def test_gemini_25_flash_context_window() -> None:
    price = calc_price(Usage(), model_ref='gemini-2.5-flash', provider_id='google')

    assert price.model.context_window == 1_048_576


@pytest.mark.parametrize(
    ('model_ref', 'hourly_rate', 'usage', 'billed_seconds'),
    [
        ('whisper-large-v3', Decimal('0.111'), Usage(), Decimal(0)),
        ('whisper-large-v3', Decimal('0.111'), Usage(audio_seconds=Decimal(1)), Decimal(10)),
        (
            'whisper-large-v3',
            Decimal('0.111'),
            Usage(audio_seconds=Decimal(0), input_audio_seconds=Decimal(5)),
            Decimal(10),
        ),
        ('whisper-large-v3-turbo', Decimal('0.04'), Usage(input_audio_seconds=Decimal(1)), Decimal(10)),
        (
            'whisper-large-v3',
            Decimal('0.111'),
            Usage(audio_seconds=Decimal(10), input_audio_seconds=Decimal(10)),
            Decimal(10),
        ),
        (
            'whisper-large-v3-turbo',
            Decimal('0.04'),
            Usage(audio_seconds=Decimal(11), input_audio_seconds=Decimal(11)),
            Decimal(11),
        ),
    ],
)
def test_groq_transcription_duration_prices(
    model_ref: str,
    hourly_rate: Decimal,
    usage: Usage,
    billed_seconds: Decimal,
) -> None:
    original_usage = copy(usage)
    price = calc_price(usage, model_ref=model_ref, provider_id='groq')
    expected_price = hourly_rate * billed_seconds / Decimal(3_600)

    assert price.input_price == expected_price
    assert price.output_price == 0
    assert price.total_price == expected_price
    assert usage == original_usage


@pytest.mark.parametrize(
    ('provider_id', 'model_ref', 'seconds', 'expected_price'),
    [
        ('openai', 'gpt-transcribe', Decimal('0.5'), Decimal('0.0000375')),
        ('openai', 'whisper-1', Decimal(30), Decimal('0.003')),
        ('mistral', 'voxtral-mini-2602', Decimal(60), Decimal('0.003')),
    ],
)
def test_transcription_duration_prices(
    provider_id: str,
    model_ref: str,
    seconds: Decimal,
    expected_price: Decimal,
) -> None:
    price = calc_price(
        Usage(audio_seconds=seconds, input_audio_seconds=seconds),
        model_ref=model_ref,
        provider_id=provider_id,
    )

    assert price.input_price == expected_price
    assert price.output_price == 0
    assert price.total_price == expected_price


def test_openai_transcription_model_ids_fail_closed() -> None:
    price = calc_price(
        Usage(input_tokens=1, input_audio_tokens=1),
        model_ref='gpt-4o-transcribe-diarize',
        provider_id='openai',
    )

    assert price.model.id == 'gpt-4o-transcribe'
    with pytest.raises(LookupError, match="model_ref='gpt-transcribe-diarize'"):
        calc_price(Usage(), model_ref='gpt-transcribe-diarize', provider_id='openai')


@pytest.mark.parametrize(
    ('model_ref', 'text_rate', 'image_rate'),
    [
        ('gemini-2.5-flash-image', '2.5', '30'),
        ('gemini-3-pro-image', '12', '120'),
        ('gemini-3-pro-image-preview', '12', '120'),
        ('gemini-3.1-flash-image', '3', '60'),
        ('gemini-3.1-flash-image-preview', '3', '60'),
    ],
)
def test_google_image_models_price_unclassified_output_as_text(
    model_ref: str,
    text_rate: str,
    image_rate: str,
) -> None:
    usage = Usage(
        output_tokens=2_309,
        output_image_tokens=1_120,
        output_reasoning_tokens=529,
    )

    price = calc_price(usage, model_ref=model_ref, provider_id='google')

    expected_output = mtok(text_rate, 1_189) + mtok(image_rate, 1_120)
    assert price.output_price == expected_output
    assert price.total_price == expected_output


def test_openai_image_model_prices_overlapping_input_modalities_and_cache() -> None:
    usage = Usage(
        input_tokens=1_000,
        output_tokens=600,
        cache_read_tokens=200,
        input_image_tokens=300,
        output_image_tokens=500,
        cache_image_read_tokens=50,
    )

    price = calc_price(usage, model_ref='gpt-image-1.5', provider_id='openai')

    expected_input = mtok('5', 550) + mtok('8', 250) + mtok('1.25', 150) + mtok('2', 50)
    expected_output = mtok('10', 100) + mtok('32', 500)
    assert price.input_price == expected_input
    assert price.output_price == expected_output
    assert price.total_price == expected_input + expected_output


def test_openai_realtime_prices_image_and_cached_image_input() -> None:
    usage = Usage(
        input_tokens=1_000,
        output_tokens=500,
        cache_read_tokens=400,
        input_audio_tokens=250,
        output_audio_tokens=300,
        input_image_tokens=150,
        cache_audio_read_tokens=100,
        cache_image_read_tokens=50,
    )

    price = calc_price(usage, model_ref='gpt-realtime-2.1', provider_id='openai')

    expected_input = (
        mtok('4', 350) + mtok('32', 150) + mtok('5', 100) + mtok('0.4', 250) + mtok('0.4', 100) + mtok('0.5', 50)
    )
    expected_output = mtok('24', 200) + mtok('64', 300)
    assert price.input_price == expected_input
    assert price.output_price == expected_output
    assert price.total_price == expected_input + expected_output


@pytest.mark.parametrize(
    ('model_ref', 'usage', 'expected_input', 'expected_output'),
    [
        (
            'gemini-3.1-flash-lite-image',
            Usage(input_tokens=1_000, output_tokens=2_000, output_image_tokens=1_000),
            mtok('0.25', 1_000),
            mtok('1.5', 1_000) + mtok('30', 1_000),
        ),
        (
            'gemini-3.1-flash-live-preview',
            Usage(
                input_tokens=1_000,
                output_tokens=500,
                input_audio_tokens=200,
                output_audio_tokens=300,
                input_image_tokens=100,
                input_video_tokens=100,
            ),
            mtok('0.75', 600) + mtok('3', 200) + mtok('1', 100) + mtok('1', 100),
            mtok('4.5', 200) + mtok('12', 300),
        ),
        (
            'gemini-embedding-2',
            Usage(
                input_tokens=1_000,
                input_audio_tokens=200,
                input_image_tokens=100,
                input_video_tokens=100,
            ),
            mtok('0.2', 600) + mtok('6.5', 200) + mtok('0.45', 100) + mtok('12', 100),
            Decimal('0'),
        ),
        (
            'gemini-omni-flash-preview',
            Usage(input_tokens=1_000, output_tokens=500, output_video_tokens=300),
            mtok('1.5', 1_000),
            mtok('9', 200) + mtok('17.5', 300),
        ),
    ],
)
def test_new_google_multimodal_model_prices(
    model_ref: str,
    usage: Usage,
    expected_input: Decimal,
    expected_output: Decimal,
) -> None:
    price = calc_price(usage, model_ref=model_ref, provider_id='google')

    assert price.input_price == expected_input
    assert price.output_price == expected_output
    assert price.total_price == expected_input + expected_output


def test_model_price_decomposition_matches_current_text_cache_pricing() -> None:
    price = ModelPrice(
        input_mtok=Decimal('2'),
        cache_write_mtok=Decimal('0.5'),
        cache_read_mtok=Decimal('0.25'),
        output_mtok=Decimal('10'),
    ).calc_price(Usage(input_tokens=1_000, cache_write_tokens=20, cache_read_tokens=30, output_tokens=100))

    expected_input = mtok('2', 950) + mtok('0.5', 20) + mtok('0.25', 30)
    expected_output = mtok('10', 100)
    assert price == {
        'input_price': expected_input,
        'output_price': expected_output,
        'total_price': expected_input + expected_output,
    }


def test_anthropic_prices_one_hour_cache_writes_at_the_ttl_rate() -> None:
    price = calc_price(
        Usage(
            input_tokens=300_000,
            cache_write_tokens=200_000,
            cache_write_5m_tokens=100_000,
            cache_write_1h_tokens=100_000,
        ),
        model_ref='claude-sonnet-4-5',
        provider_id='anthropic',
    )

    expected_input = mtok('6', 100_000) + mtok('7.5', 100_000) + mtok('12', 100_000)
    assert price.input_price == expected_input
    assert price.output_price == Decimal(0)
    assert price.total_price == expected_input


def test_model_info_uses_first_conditional_price_when_none_are_active() -> None:
    model = ModelInfo(
        id='future-model',
        match=ClauseEquals('future-model'),
        prices=[
            ConditionalPrice(
                constraint=StartDateConstraint(start_date=date(2030, 1, 1)),
                prices=ModelPrice(input_mtok=Decimal('1')),
            ),
            ConditionalPrice(
                constraint=StartDateConstraint(start_date=date(2031, 1, 1)),
                prices=ModelPrice(input_mtok=Decimal('2')),
            ),
        ],
    )

    assert model.get_prices(datetime(2029, 1, 1)).input_mtok == Decimal('1')


@pytest.mark.parametrize(
    'model_price,usage,message',
    [
        # Impossible usage is rejected by the registry's leaf decomposition (a descendant usage key
        # exceeding its ancestor yields a negative leaf value). Prices carry full ancestor coverage so
        # validation reaches the usage check rather than failing earlier on missing ancestor prices.
        (
            ModelPrice(
                input_mtok=Decimal('1'),
                cache_read_mtok=Decimal('2'),
                input_audio_mtok=Decimal('3'),
                cache_audio_read_mtok=Decimal('4'),
            ),
            Usage(input_tokens=10, cache_read_tokens=5, input_audio_tokens=1, cache_audio_read_tokens=2),
            r'cache_audio_read_tokens \(2\) cannot exceed input_audio_tokens \(1\)',
        ),
        (
            ModelPrice(
                input_mtok=Decimal('1'),
                cache_read_mtok=Decimal('2'),
                input_audio_mtok=Decimal('3'),
                cache_audio_read_mtok=Decimal('4'),
            ),
            Usage(input_tokens=10, cache_read_tokens=1, input_audio_tokens=5, cache_audio_read_tokens=2),
            r'cache_audio_read_tokens \(2\) cannot exceed cache_read_tokens \(1\)',
        ),
        (
            ModelPrice(input_mtok=Decimal('1'), cache_write_mtok=Decimal('1')),
            Usage(input_tokens=1, cache_write_tokens=2),
            r'cache_write_tokens \(2\) cannot exceed input_tokens \(1\)',
        ),
        (
            ModelPrice(output_mtok=Decimal('1'), output_audio_mtok=Decimal('1')),
            Usage(output_tokens=1, output_audio_tokens=2),
            r'output_audio_tokens \(2\) cannot exceed output_tokens \(1\)',
        ),
    ],
)
def test_model_price_rejects_impossible_overlapping_usage(model_price: ModelPrice, usage: Usage, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        model_price.calc_price(usage)


def test_standard_price_parity_handles_simple_input_output_tokens() -> None:
    price = ModelPrice(input_mtok=Decimal('1.25'), output_mtok=Decimal('3')).calc_price(
        Usage(input_tokens=2_000, output_tokens=500)
    )

    expected_input = mtok('1.25', 2_000)
    expected_output = mtok('3', 500)
    assert price == {
        'input_price': expected_input,
        'output_price': expected_output,
        'total_price': expected_input + expected_output,
    }


def test_standard_price_parity_handles_cache_read_write_tokens() -> None:
    price = ModelPrice(
        input_mtok=Decimal('2'),
        cache_write_mtok=Decimal('0.5'),
        cache_read_mtok=Decimal('0.25'),
    ).calc_price(Usage(input_tokens=1_000, cache_write_tokens=200, cache_read_tokens=300))

    expected_input = mtok('2', 500) + mtok('0.5', 200) + mtok('0.25', 300)
    assert price == {
        'input_price': expected_input,
        'output_price': Decimal('0'),
        'total_price': expected_input,
    }


def test_model_price_decomposition_handles_audio_cache_overlap() -> None:
    price = ModelPrice(
        input_mtok=Decimal('1'),
        cache_read_mtok=Decimal('2'),
        input_audio_mtok=Decimal('3'),
        cache_audio_read_mtok=Decimal('4'),
    ).calc_price(
        Usage(
            input_tokens=1_000,
            cache_read_tokens=400,
            input_audio_tokens=300,
            cache_audio_read_tokens=100,
        )
    )

    expected_input = mtok('1', 400) + mtok('2', 300) + mtok('3', 200) + mtok('4', 100)
    assert price == {
        'input_price': expected_input,
        'output_price': Decimal('0'),
        'total_price': expected_input,
    }


def test_model_price_decomposition_handles_fractional_usage() -> None:
    price = ModelPrice(input_mtok=Decimal('1'), cache_read_mtok=Decimal('2')).calc_price(
        Usage(input_tokens=0.3, cache_read_tokens=0.1)
    )

    assert price == {
        'input_price': Decimal('0.0000004'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.0000004'),
    }


def test_overlap_price_parity_handles_cached_audio_overlap() -> None:
    price = ModelPrice(
        input_mtok=Decimal('1'),
        cache_read_mtok=Decimal('0.25'),
        input_audio_mtok=Decimal('2'),
        cache_audio_read_mtok=Decimal('0.5'),
    ).calc_price(
        Usage(
            input_tokens=1_000,
            cache_read_tokens=400,
            input_audio_tokens=300,
            cache_audio_read_tokens=100,
        )
    )

    expected_input = mtok('1', 400) + mtok('0.25', 300) + mtok('2', 200) + mtok('0.5', 100)
    assert price == {
        'input_price': expected_input,
        'output_price': Decimal('0'),
        'total_price': expected_input,
    }


def test_model_price_decomposition_handles_output_audio() -> None:
    price = ModelPrice(output_mtok=Decimal('5'), output_audio_mtok=Decimal('10')).calc_price(
        Usage(output_tokens=700, output_audio_tokens=200)
    )

    expected_output = mtok('5', 500) + mtok('10', 200)
    assert price == {
        'input_price': Decimal('0'),
        'output_price': expected_output,
        'total_price': expected_output,
    }


def test_overlap_price_parity_handles_output_audio() -> None:
    price = ModelPrice(output_mtok=Decimal('5'), output_audio_mtok=Decimal('9')).calc_price(
        Usage(output_tokens=800, output_audio_tokens=300)
    )

    expected_output = mtok('5', 500) + mtok('9', 300)
    assert price == {
        'input_price': Decimal('0'),
        'output_price': expected_output,
        'total_price': expected_output,
    }


def test_model_price_prices_requests_only_in_total() -> None:
    price = ModelPrice(requests_kcount=Decimal('12')).calc_price(Usage(input_tokens=1_000))

    expected_total = Decimal('12') / THOUSAND
    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0'),
        'total_price': expected_total,
    }


def test_model_price_prices_reported_web_searches_only_in_total() -> None:
    price = ModelPrice(web_searches_kcount=Decimal('10')).calc_price(Usage(web_searches=2))

    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0'),
        'total_price': Decimal('0.02'),
    }


def test_request_price_regression_counts_one_request_per_price_calculation() -> None:
    price = ModelPrice(requests_kcount=Decimal('12')).calc_price(Usage(input_tokens=1_000, output_tokens=500))

    expected_total = Decimal('12') / THOUSAND
    assert price == {
        'input_price': Decimal('0'),
        'output_price': Decimal('0'),
        'total_price': expected_total,
    }


def test_request_price_regression_contributes_only_to_total_price() -> None:
    price = ModelPrice(input_mtok=Decimal('1'), requests_kcount=Decimal('12')).calc_price(Usage(input_tokens=1_000))

    expected_input = mtok('1', 1_000)
    expected_request = Decimal('12') / THOUSAND
    assert price == {
        'input_price': expected_input,
        'output_price': Decimal('0'),
        'total_price': expected_input + expected_request,
    }


def test_model_price_charges_unpriced_descendants_through_parent() -> None:
    price = ModelPrice(input_mtok=Decimal('5'), output_mtok=Decimal('10')).calc_price(
        Usage(input_tokens=700, input_audio_tokens=200, output_tokens=70, output_audio_tokens=20)
    )

    expected_input = mtok('5', 700)
    expected_output = mtok('10', 70)
    assert price == {
        'input_price': expected_input,
        'output_price': expected_output,
        'total_price': expected_input + expected_output,
    }


def test_cache_audio_read_without_specific_price_requires_join_price() -> None:
    with pytest.raises(
        ValueError,
        match='Missing join price for cache_read_tokens and input_audio_tokens: cache_audio_read_tokens',
    ):
        ModelPrice(
            input_mtok=Decimal('1'),
            cache_read_mtok=Decimal('2'),
            input_audio_mtok=Decimal('3'),
        ).calc_price(
            Usage(
                input_tokens=1_000,
                cache_read_tokens=400,
                input_audio_tokens=300,
                cache_audio_read_tokens=100,
            )
        )


def test_pricing_rejects_missing_join_usage_when_join_is_priced() -> None:
    price = ModelPrice(
        input_mtok=Decimal('1'),
        cache_read_mtok=Decimal('2'),
        input_audio_mtok=Decimal('3'),
        cache_audio_read_mtok=Decimal('4'),
    )

    with pytest.raises(ValueError, match='Missing usage for cache_audio_read_tokens'):
        price.calc_price(Usage(input_tokens=1_000, cache_read_tokens=400, input_audio_tokens=300))


def test_tiered_price_regression_uses_provided_input_token_threshold() -> None:
    price = ModelPrice(
        output_mtok=TieredPrices(base=Decimal('1'), tiers=[Tier(start=100_000, price=Decimal('2'))])
    ).calc_price(Usage(input_tokens=100_000, input_audio_tokens=200_000, output_tokens=10_000))

    expected_output = mtok('1', 10_000)
    assert price == {
        'input_price': Decimal('0'),
        'output_price': expected_output,
        'total_price': expected_output,
    }
