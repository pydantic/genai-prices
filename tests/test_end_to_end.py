from decimal import Decimal

from inline_snapshot import snapshot

from genai_prices import extract_usage
from genai_prices.types import Usage


def test_anthropic_without_caching():
    response = dict(
        model='claude-3-7-sonnet-20250219',
        usage=dict(
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            input_tokens=144222,
            output_tokens=197,
            server_tool_use=None,
            service_tier='standard',
        ),
    )

    extracted_usage = extract_usage(response, provider_id='anthropic')
    assert extracted_usage.usage == snapshot(
        Usage(input_tokens=144222, cache_write_tokens=0, cache_read_tokens=0, output_tokens=197)
    )
    price = extracted_usage.calc_price()
    assert price.input_price == snapshot(Decimal('0.432666'))
    assert price.output_price == snapshot(Decimal('0.002955'))
    assert price.total_price == snapshot(Decimal('0.435621'))


def test_anthropic_caching_write():
    response = dict(
        model='claude-3-7-sonnet-20250219',
        usage=dict(
            cache_creation_input_tokens=144211,
            cache_read_input_tokens=0,
            input_tokens=11,
            output_tokens=197,
            server_tool_use=None,
            service_tier='standard',
        ),
    )

    extracted_usage = extract_usage(response, provider_id='anthropic')
    assert extracted_usage.usage == snapshot(
        Usage(input_tokens=11 + 144211, cache_write_tokens=144211, cache_read_tokens=0, output_tokens=197)
    )
    price = extracted_usage.calc_price()
    assert price.input_price == snapshot(Decimal('0.54082425'))
    assert price.output_price == snapshot(Decimal('0.002955'))
    assert price.total_price == snapshot(Decimal('0.54377925'))


def test_anthropic_caching_read():
    response = dict(
        model='claude-3-7-sonnet-20250219',
        usage=dict(
            cache_creation_input_tokens=0,
            cache_read_input_tokens=144211,
            input_tokens=11,
            output_tokens=197,
            server_tool_use=None,
            service_tier='standard',
        ),
    )

    extracted_usage = extract_usage(response, provider_id='anthropic')
    assert extracted_usage.usage == snapshot(
        Usage(input_tokens=11 + 144211, cache_write_tokens=0, cache_read_tokens=144211, output_tokens=197)
    )
    price = extracted_usage.calc_price()
    assert price.input_price == snapshot(Decimal('0.0432963'))
    assert price.output_price == snapshot(Decimal('0.002955'))
    assert price.total_price == snapshot(Decimal('0.0462513'))


def test_anthropic_with_web_search():
    response = dict(
        model='claude-3-7-sonnet-20250219',
        usage=dict(
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            input_tokens=10809,
            output_tokens=644,
            server_tool_use=dict(web_search_requests=1),
            service_tier='standard',
        ),
    )

    extracted_usage = extract_usage(response, provider_id='anthropic')
    assert extracted_usage.usage == snapshot(
        Usage(
            input_tokens=10809, cache_write_tokens=0, cache_read_tokens=0, output_tokens=644, tool_use={'web_search': 1}
        )
    )
    price = extracted_usage.calc_price()
    # input: 3 * 10809 / 1e6 = 0.032427
    # output: 15 * 644 / 1e6 = 0.00966
    # web_search: 10 * 1 / 1000 = 0.01
    assert price.input_price == snapshot(Decimal('0.032427'))
    assert price.output_price == snapshot(Decimal('0.00966'))
    assert price.total_price == snapshot(Decimal('0.052087'))


def test_openai_without_caching():
    response = dict(
        model='gpt-4.1-2025-04-14',
        usage=dict(
            completion_tokens=610,
            prompt_tokens=131609,
            total_tokens=132219,
            completion_tokens_details=dict(
                accepted_prediction_tokens=0,
                audio_tokens=0,
                reasoning_tokens=0,
                rejected_prediction_tokens=0,
            ),
            prompt_tokens_details=dict(audio_tokens=0, cached_tokens=0),
        ),
    )

    extracted_usage = extract_usage(response, provider_id='openai', api_flavor='chat')
    assert extracted_usage.usage == snapshot(
        Usage(input_tokens=131609, cache_read_tokens=0, output_tokens=610, input_audio_tokens=0, output_audio_tokens=0)
    )
    price = extracted_usage.calc_price()
    assert price.input_price == snapshot(Decimal('0.263218'))
    assert price.output_price == snapshot(Decimal('0.00488'))
    assert price.total_price == snapshot(Decimal('0.268098'))


def test_openai_caching():
    response = dict(
        model='gpt-4.1-2025-04-14',
        usage=dict(
            completion_tokens=610,
            prompt_tokens=131609,
            total_tokens=132219,
            completion_tokens_details=dict(
                accepted_prediction_tokens=0,
                audio_tokens=0,
                reasoning_tokens=0,
                rejected_prediction_tokens=0,
            ),
            prompt_tokens_details=dict(audio_tokens=0, cached_tokens=131584),
        ),
    )

    extracted_usage = extract_usage(response, provider_id='openai', api_flavor='chat')
    assert extracted_usage.usage == snapshot(
        Usage(
            input_tokens=131609,
            cache_read_tokens=131584,
            output_tokens=610,
            input_audio_tokens=0,
            output_audio_tokens=0,
        )
    )
    price = extracted_usage.calc_price()
    assert price.input_price == snapshot(Decimal('0.065842'))
    assert price.output_price == snapshot(Decimal('0.00488'))
    assert price.total_price == snapshot(Decimal('0.070722'))
