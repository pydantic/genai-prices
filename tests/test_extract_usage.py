import re
from decimal import Decimal
from typing import Any

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price, extract_usage
from genai_prices.data import providers
from genai_prices.types import (
    ArrayMatch,
    ClauseEquals,
    ExtractedUsage,
    ModelPrice,
    Provider,
    UsageExtractor,
    UsageExtractorMapping,
)
from genai_prices.units import UnitRegistry


class MyMapping(dict[str, Any]):
    pass


@pytest.mark.parametrize(
    'response_data,expected_model,expected_usage,expected_price',
    [
        (
            {
                'id': 'msg_0152tnC3YpjyASTB9qxqDJXu',
                'type': 'message',
                'role': 'assistant',
                'model': 'claude-sonnet-4-20250514',
                'stop_reason': 'tool_use',
                'stop_sequence': None,
                'usage': {
                    'input_tokens': 504,
                    'cache_creation': {
                        'ephemeral_5m_input_tokens': 100,
                        'ephemeral_1h_input_tokens': 23,
                    },
                    'cache_creation_input_tokens': 123,
                    'cache_read_input_tokens': 0,
                    'output_tokens': 97,
                    'service_tier': 'standard',
                },
            },
            snapshot('claude-sonnet-4-20250514'),
            snapshot(
                Usage(
                    input_tokens=627,
                    cache_write_tokens=123,
                    cache_write_5m_tokens=100,
                    cache_write_1h_tokens=23,
                    cache_read_tokens=0,
                    output_tokens=97,
                )
            ),
            snapshot(Decimal('0.00348')),
        ),
        (
            {
                'model': 'claude-3-5-haiku',
                'usage': {'input_tokens': 504, 'output_tokens': 97, 'service_tier': 'standard'},
            },
            snapshot('claude-3-5-haiku'),
            snapshot(Usage(input_tokens=504, output_tokens=97)),
            snapshot(Decimal('0.0007912')),
        ),
        (
            MyMapping(
                model='claude-3.5-haiku', usage=MyMapping(input_tokens=504, output_tokens=97, service_tier='standard')
            ),
            snapshot('claude-3.5-haiku'),
            snapshot(Usage(input_tokens=504, output_tokens=97)),
            snapshot(Decimal('0.0007912')),
        ),
    ],
)
def test_extract_usage_ok(response_data: Any, expected_model: str, expected_usage: Usage, expected_price: Decimal):
    provider = next(provider for provider in providers if provider.id == 'anthropic')
    assert provider.name == 'Anthropic'
    assert provider.extractors is not None
    model, usage = provider.extract_usage(response_data)
    assert model == expected_model
    assert usage == expected_usage

    # also test the public simple API
    extracted_usage = extract_usage(response_data, provider_id='anthropic')
    assert extracted_usage.usage == expected_usage
    assert extracted_usage.provider.name == 'Anthropic'

    assert extracted_usage.calc_price().total_price == expected_price


def test_anthropic_native_thinking_tokens():
    provider = next(provider for provider in providers if provider.id == 'anthropic')
    response_data = {
        'model': 'claude-sonnet-4-20250514',
        'usage': {
            'input_tokens': 10,
            'output_tokens': 8,
            'output_tokens_details': {'thinking_tokens': 6},
        },
    }

    assert provider.extract_usage(response_data) == (
        'claude-sonnet-4-20250514',
        Usage(input_tokens=10, output_tokens=8, output_reasoning_tokens=6),
    )


def test_openai():
    provider = next(provider for provider in providers if provider.id == 'openai')
    assert provider.name == 'OpenAI'
    assert provider.extractors is not None
    response_data = {
        'model': 'gpt-4.1',
        'usage': {
            'prompt_tokens': 100,
            'completion_tokens': 200,
            'prompt_tokens_details': {'cached_tokens': None},
            'completion_tokens_details': {'reasoning_tokens': 120},
        },
    }
    usage = provider.extract_usage(response_data, api_flavor='chat')
    assert usage == snapshot(('gpt-4.1', Usage(input_tokens=100, output_tokens=200, output_reasoning_tokens=120)))

    extracted_usage = extract_usage(response_data, provider_id='openai', api_flavor='chat')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=100, output_tokens=200, output_reasoning_tokens=120))
    assert extracted_usage.provider.name == snapshot('OpenAI')
    assert extracted_usage.model is not None
    assert extracted_usage.model.name == snapshot('gpt 4.1')

    assert extracted_usage.calc_price().total_price == snapshot(Decimal('0.0018'))

    response_data = {
        'model': 'gpt-5',
        'usage': {'input_tokens': 100, 'output_tokens': 200, 'output_tokens_details': {'reasoning_tokens': 120}},
    }
    usage = provider.extract_usage(response_data, api_flavor='responses')
    assert usage == snapshot(('gpt-5', Usage(input_tokens=100, output_tokens=200, output_reasoning_tokens=120)))

    extracted_usage = extract_usage(response_data, provider_id='openai', api_flavor='responses')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=100, output_tokens=200, output_reasoning_tokens=120))
    assert extracted_usage.provider.name == snapshot('OpenAI')
    assert extracted_usage.model is not None
    assert extracted_usage.model.name == snapshot('GPT-5')

    assert extracted_usage.calc_price().total_price == snapshot(Decimal('0.002125'))

    with pytest.raises(ValueError, match=re.escape("Unknown api_flavor 'default', allowed values: chat, responses")):
        provider.extract_usage(response_data)


@pytest.mark.parametrize(
    ('model_id', 'expected_price'),
    [
        ('moonshotai/Kimi-K3', Decimal('21.3')),
        ('thinkingmachines/Inkling-NVFP4', Decimal('7.67')),
    ],
)
def test_modal_chat_usage(model_id: str, expected_price: Decimal) -> None:
    response_data = {
        'model': model_id,
        'usage': {
            'prompt_tokens': 3_000_000,
            'prompt_tokens_details': {'cached_tokens': 1_000_000, 'cache_write_tokens': 1_000_000},
            'completion_tokens': 1_000_000,
            'reasoning_tokens': 500_000,
        },
    }

    extracted_usage = extract_usage(
        response_data,
        provider_api_url='https://example--kimi-k3.modal.run/v1',
        api_flavor='chat',
    )

    assert extracted_usage.provider.id == 'modal'
    assert extracted_usage.model is not None
    assert extracted_usage.model.id == model_id
    assert extracted_usage.usage == Usage(
        input_tokens=3_000_000,
        cache_read_tokens=1_000_000,
        cache_write_tokens=1_000_000,
        output_tokens=1_000_000,
        output_reasoning_tokens=500_000,
    )
    assert extracted_usage.calc_price().total_price == expected_price


def test_modal_responses_usage() -> None:
    response_data = {
        'model': 'moonshotai/Kimi-K3',
        'usage': {
            'input_tokens': 90,
            'input_tokens_details': {'cached_tokens': 64, 'cache_write_tokens': 0},
            'output_tokens': 188,
            'output_tokens_details': {'reasoning_tokens': 169},
            'total_tokens': 278,
        },
    }

    extracted_usage = extract_usage(
        response_data,
        provider_api_url='https://example--kimi-k3.modal.run/v1',
        api_flavor='responses',
    )

    assert extracted_usage.provider.id == 'modal'
    assert extracted_usage.model is not None
    assert extracted_usage.model.id == 'moonshotai/Kimi-K3'
    assert extracted_usage.usage == Usage(
        input_tokens=90,
        cache_read_tokens=64,
        cache_write_tokens=0,
        output_tokens=188,
        output_reasoning_tokens=169,
    )
    assert extracted_usage.calc_price().input_price == Decimal('0.0000972')
    assert extracted_usage.calc_price().output_price == Decimal('0.00282')
    assert extracted_usage.calc_price().total_price == Decimal('0.0029172')


@pytest.mark.parametrize(
    ('api_flavor', 'usage_data'),
    [
        (
            'chat',
            {
                'prompt_tokens': 2_006,
                'prompt_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 1_920},
                'completion_tokens': 300,
            },
        ),
        (
            'responses',
            {
                'input_tokens': 2_006,
                'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 1_920},
                'output_tokens': 300,
            },
        ),
    ],
)
def test_openai_cache_write_tokens(api_flavor: str, usage_data: dict[str, Any]):
    response_data = {'model': 'gpt-5.6-sol', 'usage': usage_data}
    extracted_usage = extract_usage(response_data, provider_id='openai', api_flavor=api_flavor)

    assert extracted_usage.usage == Usage(
        input_tokens=2_006,
        cache_write_tokens=1_920,
        cache_read_tokens=0,
        output_tokens=300,
    )
    assert extracted_usage.calc_price().total_price == Decimal('0.015944')


@pytest.mark.parametrize('provider_id', ['openai', 'azure'])
def test_openai_realtime_usage_modalities(provider_id: str):
    response_data = {
        'type': 'response.done',
        'response': {
            'usage': {
                'input_tokens': 1_000,
                'input_token_details': {
                    'text_tokens': 600,
                    'audio_tokens': 250,
                    'image_tokens': 150,
                    'cached_tokens': 400,
                    'cached_tokens_details': {
                        'text_tokens': 250,
                        'audio_tokens': 100,
                        'image_tokens': 50,
                    },
                },
                'output_tokens': 500,
                'output_token_details': {'text_tokens': 200, 'audio_tokens': 300},
            }
        },
    }

    extracted_usage = extract_usage(response_data, provider_id=provider_id, api_flavor='realtime')

    assert extracted_usage.provider.id == provider_id
    assert extracted_usage.usage == Usage(
        input_tokens=1_000,
        output_tokens=500,
        cache_read_tokens=400,
        input_text_tokens=600,
        output_text_tokens=200,
        input_audio_tokens=250,
        output_audio_tokens=300,
        input_image_tokens=150,
        cache_text_read_tokens=250,
        cache_audio_read_tokens=100,
        cache_image_read_tokens=50,
    )


def test_openai_transcription_duration_usage_and_price() -> None:
    provider = next(provider for provider in providers if provider.id == 'openai')

    model, usage = provider.extract_usage(
        {'usage': {'type': 'duration', 'seconds': 30}},
        api_flavor='transcription',
    )
    price = calc_price(usage, model_ref='gpt-realtime-whisper', provider_id='openai')

    assert model is None
    assert usage == Usage(audio_seconds=30, input_audio_seconds=30)
    assert price.input_price == Decimal('0.0085')
    assert price.output_price == 0
    assert price.total_price == Decimal('0.0085')

    assert provider.extract_usage(
        {
            'usage': {
                'type': 'tokens',
                'input_tokens': 5,
                'input_token_details': {'text_tokens': 0, 'audio_tokens': 5},
                'output_tokens': 2,
            }
        },
        api_flavor='transcription',
    ) == (None, Usage(input_tokens=5, input_text_tokens=0, input_audio_tokens=5, output_tokens=2))


def test_openai_image_usage_modalities():
    provider = next(provider for provider in providers if provider.id == 'openai')
    usage_data = {
        'input_tokens': 100,
        'input_tokens_details': {'text_tokens': 70, 'image_tokens': 30},
        'output_tokens': 600,
        'output_tokens_details': {'text_tokens': 100, 'image_tokens': 500},
    }
    expected_usage = Usage(
        input_tokens=100,
        output_tokens=600,
        input_text_tokens=70,
        output_text_tokens=100,
        input_image_tokens=30,
        output_image_tokens=500,
    )

    assert provider.extract_usage({'usage': usage_data}, api_flavor='images') == (None, expected_usage)

    with pytest.raises(ValueError, match='input_tokens_details'):
        provider.extract_usage(
            {'usage': {'input_tokens': 100, 'output_tokens': 600}},
            api_flavor='images',
        )


def test_mistral():
    provider = next(provider for provider in providers if provider.id == 'mistral')
    assert provider.name == 'Mistral'
    assert provider.extractors is not None
    # Mistral nests prompt-cache hits under `prompt_tokens_details.cached_tokens`.
    # https://docs.mistral.ai/studio-api/conversations/advanced/prompt-caching
    response_data = {
        'model': 'mistral-large-2512',
        'usage': {
            'prompt_tokens': 1013,
            'completion_tokens': 30,
            'total_tokens': 1043,
            'prompt_tokens_details': {'cached_tokens': 1008},
        },
    }
    usage = provider.extract_usage(response_data)
    assert usage == snapshot(('mistral-large-2512', Usage(input_tokens=1013, cache_read_tokens=1008, output_tokens=30)))

    extracted_usage = extract_usage(response_data, provider_id='mistral')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=1013, cache_read_tokens=1008, output_tokens=30))
    assert extracted_usage.provider.name == snapshot('Mistral')
    # The 1008 cached tokens are billed at `cache_read_mtok` (10% of the input rate), not the full
    # input rate: (1013 - 1008) * 0.5 + 1008 * 0.05 + 30 * 1.5, all per Mtok.
    assert extracted_usage.calc_price().total_price == snapshot(Decimal('0.0000979'))

    # The nested mapping is optional: responses without prompt caching still extract cleanly.
    response_data_no_cache = {
        'model': 'mistral-large-2512',
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
    }
    assert provider.extract_usage(response_data_no_cache) == snapshot(
        ('mistral-large-2512', Usage(input_tokens=10, output_tokens=5))
    )


def test_groq_cached_tokens():
    provider = next(provider for provider in providers if provider.id == 'groq')
    response_data = {
        'model': 'llama-3.3-70b-versatile',
        'usage': {
            'prompt_tokens': 19038,
            'completion_tokens': 135,
            'prompt_tokens_details': {'cached_tokens': 18944},
            'completion_tokens_details': {'reasoning_tokens': 94},
        },
    }
    model, usage = provider.extract_usage(response_data)
    assert model == 'llama-3.3-70b-versatile'
    assert usage == Usage(
        input_tokens=19038,
        output_tokens=135,
        cache_read_tokens=18944,
        output_reasoning_tokens=94,
    )

    extracted_usage = extract_usage(response_data, provider_id='groq')
    assert extracted_usage.usage == usage


def test_openrouter_chat_cache_write_tokens():
    provider = next(provider for provider in providers if provider.id == 'openrouter')
    assert provider.name == 'OpenRouter'
    assert provider.extractors is not None
    response_data = {
        'model': 'anthropic/claude-4.6-sonnet-20260217',
        'usage': {
            'prompt_tokens': 4819,
            'completion_tokens': 1906,
            'total_tokens': 6725,
            'prompt_tokens_details': {
                'cached_tokens': 0,
                'cache_write_tokens': 4800,
                'audio_tokens': 17,
            },
            'completion_tokens_details': {
                'audio_tokens': 23,
                'reasoning_tokens': 1200,
            },
        },
    }
    usage = provider.extract_usage(response_data, api_flavor='chat')
    assert usage == snapshot(
        (
            'anthropic/claude-4.6-sonnet-20260217',
            Usage(
                input_tokens=4819,
                cache_write_tokens=4800,
                cache_read_tokens=0,
                output_tokens=1906,
                input_audio_tokens=17,
                output_audio_tokens=23,
                output_reasoning_tokens=1200,
            ),
        )
    )

    extracted_usage = extract_usage(response_data, provider_id='openrouter', api_flavor='chat')
    assert extracted_usage.usage == snapshot(
        Usage(
            input_tokens=4819,
            cache_write_tokens=4800,
            cache_read_tokens=0,
            output_tokens=1906,
            input_audio_tokens=17,
            output_audio_tokens=23,
            output_reasoning_tokens=1200,
        )
    )
    assert extracted_usage.provider.name == snapshot('OpenRouter')
    assert extracted_usage.model is not None
    assert extracted_usage.model.id == snapshot('anthropic/claude-sonnet-4.6')

    extracted_usage_by_url = extract_usage(
        response_data, provider_api_url='https://openrouter.ai/api/v1', api_flavor='chat'
    )
    assert extracted_usage_by_url.usage == extracted_usage.usage


cohere_chat_response_data = {
    'id': 'chatcmpl-00000000-0000-0000-0000-000000000000',
    'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Done.'}]},
    'usage': {
        'billed_units': {'input_tokens': 13, 'output_tokens': 8},
        'tokens': {'input_tokens': 542, 'output_tokens': 8},
        'cached_tokens': 0,
    },
    'model': 'command-r-plus',
}


def test_cohere_default_flavor_uses_billed_units_and_prices():
    provider = next(provider for provider in providers if provider.id == 'cohere')
    assert provider.name == 'Cohere'
    assert provider.extractors is not None

    usage = provider.extract_usage(cohere_chat_response_data)
    assert usage == snapshot(('command-r-plus', Usage(input_tokens=13, output_tokens=8)))

    extracted_usage = extract_usage(cohere_chat_response_data, provider_id='cohere')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=13, output_tokens=8))
    assert extracted_usage.provider.name == snapshot('Cohere')
    assert extracted_usage.model is not None
    assert extracted_usage.model.id == snapshot('command-r-plus')
    assert extracted_usage.calc_price().total_price == snapshot(Decimal('0.0001125'))


def test_cohere_tokens_flavor_extracts_raw_tokens_and_cache():
    provider = next(provider for provider in providers if provider.id == 'cohere')
    assert provider.name == 'Cohere'
    assert provider.extractors is not None

    # Recorded Cohere JSON fixtures in tests/dataset/usages.json serialize these token fields as integers.
    usage = provider.extract_usage(cohere_chat_response_data, api_flavor='tokens')
    assert usage == snapshot(('command-r-plus', Usage(input_tokens=542, cache_read_tokens=0, output_tokens=8)))

    extracted_usage = extract_usage(cohere_chat_response_data, provider_id='cohere', api_flavor='tokens')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=542, cache_read_tokens=0, output_tokens=8))
    assert extracted_usage.provider.name == snapshot('Cohere')
    assert extracted_usage.model is not None
    assert extracted_usage.model.id == snapshot('command-r-plus')

    # the v2 SDK talks to api.cohere.com, the old pattern only matched api.cohere.ai
    extracted_usage_by_url = extract_usage(
        cohere_chat_response_data, provider_api_url='https://api.cohere.com', api_flavor='tokens'
    )
    assert extracted_usage_by_url.provider.name == snapshot('Cohere')
    assert extracted_usage_by_url.usage == snapshot(Usage(input_tokens=542, cache_read_tokens=0, output_tokens=8))


def test_cohere_tokens_flavor_extracts_cached_tokens_without_tokens_object():
    provider = next(provider for provider in providers if provider.id == 'cohere')
    assert provider.name == 'Cohere'
    assert provider.extractors is not None

    response_data = {
        'model': 'command-r-plus',
        'usage': {
            'billed_units': {'input_tokens': 13, 'output_tokens': 8},
            'cached_tokens': 37,
        },
    }

    usage = provider.extract_usage(response_data, api_flavor='tokens')
    assert usage == snapshot(('command-r-plus', Usage(cache_read_tokens=37)))


def test_cohere_tokens_flavor_errors_without_tokens_or_cached_tokens():
    provider = next(provider for provider in providers if provider.id == 'cohere')
    assert provider.name == 'Cohere'
    assert provider.extractors is not None

    response_data = {
        'model': 'command-r-plus',
        'usage': {
            'billed_units': {'input_tokens': 13, 'output_tokens': 8},
        },
    }

    with pytest.raises(ValueError, match='No usage information found at usage'):
        provider.extract_usage(response_data, api_flavor='tokens')


def test_extracted_usage_calc_price_requires_model():
    extracted_usage = ExtractedUsage(
        usage=Usage(input_tokens=1),
        model=None,
        provider=Provider(id='test', name='Test', api_pattern='test'),
        auto_update_timestamp=None,
    )

    with pytest.raises(ValueError, match='No model reference found in response data and model not provided'):
        extracted_usage.calc_price()


@pytest.mark.parametrize(
    'response_data,error',
    [
        ({}, snapshot('Missing value at `usage`')),
        ({'model': None}, snapshot('Missing value at `usage`')),
        ({'model': 'x'}, snapshot('Missing value at `usage`')),
        ({'model': 'x', 'usage': {}}, snapshot('Missing value at `usage.input_tokens`')),
        ({'model': 'x', 'usage': 123}, snapshot('Expected `usage` value to be a Mapping, got int')),
        (
            {'model': 'x', 'usage': {'input_tokens': []}},
            snapshot('Expected `usage.input_tokens` value to be a int or float or Decimal, got list'),
        ),
    ],
)
def test_extract_usage_error(response_data: Any, error: str):
    provider = next(provider for provider in providers if provider.id == 'anthropic')
    assert provider.name == 'Anthropic'
    assert provider.extractors is not None

    with pytest.raises(ValueError) as exc_info:
        provider.extract_usage(response_data)

    assert str(exc_info.value) == error


def test_usage_extractor_errors_when_optional_mappings_find_no_usage_values():
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(
                path=[ArrayMatch(type='array-match', field='modality', match=ClauseEquals('AUDIO')), 'tokenCount'],
                dest='input_audio_tokens',
                required=False,
            )
        ],
    )

    with pytest.raises(ValueError, match='No usage information found at usage'):
        extractor.extract({'model': 'test-model', 'usage': {}})


def test_usage_extractor_errors_when_required_nested_path_has_wrong_type():
    extractor = UsageExtractor(
        root='usage',
        mappings=[UsageExtractorMapping(path=['totals', 'input_tokens'], dest='input_tokens')],
    )

    with pytest.raises(ValueError, match='Expected `usage.totals` value to be a dict, got int'):
        extractor.extract({'model': 'test-model', 'usage': {'totals': 1}})


def test_usage_extractor_errors_when_required_array_match_path_has_wrong_type():
    extractor = UsageExtractor(
        root=['usage', ArrayMatch(type='array-match', field='modality', match=ClauseEquals('AUDIO')), 'data'],
        mappings=[UsageExtractorMapping(path='tokenCount', dest='input_audio_tokens')],
    )

    with pytest.raises(ValueError, match='Expected .* value to be a sequence, got dict'):
        extractor.extract({'model': 'test-model', 'usage': {'modality': 'AUDIO', 'tokenCount': 1}})


def test_usage_extractor_errors_when_required_array_match_finds_no_item():
    extractor = UsageExtractor(
        root=['usage', ArrayMatch(type='array-match', field='modality', match=ClauseEquals('AUDIO')), 'data'],
        mappings=[UsageExtractorMapping(path='tokenCount', dest='input_audio_tokens')],
    )

    with pytest.raises(ValueError, match='Unable to find item at .*'):
        extractor.extract({'model': 'test-model', 'usage': [{'modality': 'TEXT', 'data': {'tokenCount': 1}}]})


def test_usage_extractor_errors_when_required_nested_key_is_missing():
    extractor = UsageExtractor(
        root='usage',
        mappings=[UsageExtractorMapping(path=['totals', 'input_tokens'], dest='input_tokens')],
    )

    with pytest.raises(ValueError, match='Missing value at `usage.totals`'):
        extractor.extract({'model': 'test-model', 'usage': {}})


def test_usage_extractor_skips_optional_nested_path_with_wrong_type():
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path=['totals', 'input_tokens'], dest='input_tokens', required=False),
            UsageExtractorMapping(path='output_tokens', dest='output_tokens'),
        ],
    )

    assert extractor.extract({'model': 'test-model', 'usage': {'totals': 1, 'output_tokens': 2}}) == (
        'test-model',
        Usage(output_tokens=2),
    )


def test_usage_extractor_skips_optional_nested_path_with_missing_parent():
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path=['totals', 'input_tokens'], dest='input_tokens', required=False),
            UsageExtractorMapping(path='output_tokens', dest='output_tokens'),
        ],
    )

    assert extractor.extract({'model': 'test-model', 'usage': {'output_tokens': 2}}) == (
        'test-model',
        Usage(output_tokens=2),
    )


def test_usage_extractor_skips_optional_nested_path_with_null_parent():
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path=['details', 'reasoning_tokens'], dest='output_reasoning_tokens', required=False),
            UsageExtractorMapping(path='output_tokens', dest='output_tokens'),
        ],
    )

    assert extractor.extract({'model': 'test-model', 'usage': {'details': None, 'output_tokens': 2}}) == (
        'test-model',
        Usage(output_tokens=2),
    )


def test_usage_extractor_accepts_optional_integral_float_value():
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path='prompt_tokens', dest='input_tokens', required=False),
            UsageExtractorMapping(path='output_tokens', dest='output_tokens'),
        ],
    )

    model, usage = extractor.extract({'model': 'test-model', 'usage': {'prompt_tokens': 3.0, 'output_tokens': 2}})

    assert (model, usage) == (
        'test-model',
        Usage(input_tokens=3.0, output_tokens=2),
    )
    assert type(usage.input_tokens) is float


def test_usage_extractor_preserves_decimal_value() -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[UsageExtractorMapping(path='duration', dest='audio_seconds')],
    )
    value = Decimal('3.00')

    model, usage = extractor.extract({'model': 'test-model', 'usage': {'duration': value}})

    assert model == 'test-model'
    assert usage.audio_seconds is value


def test_usage_extractor_accumulates_fractional_values_by_destination() -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path='first_seconds', dest='audio_seconds'),
            UsageExtractorMapping(path='second_seconds', dest='audio_seconds'),
        ],
    )

    model, usage = extractor.extract({'model': 'test-model', 'usage': {'first_seconds': 0.1, 'second_seconds': 0.2}})

    assert model == 'test-model'
    assert usage.audio_seconds == 0.3
    assert type(usage.audio_seconds) is float


def test_usage_extractor_accumulates_mixed_values_as_decimal() -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path='first_seconds', dest='audio_seconds'),
            UsageExtractorMapping(path='second_seconds', dest='audio_seconds'),
            UsageExtractorMapping(path='whole_seconds', dest='audio_seconds'),
        ],
    )

    model, usage = extractor.extract(
        {
            'model': 'test-model',
            'usage': {
                'first_seconds': Decimal('0.1'),
                'second_seconds': 0.2,
                'whole_seconds': 1,
            },
        }
    )

    assert model == 'test-model'
    assert usage.audio_seconds == Decimal('1.3')
    assert isinstance(usage.audio_seconds, Decimal)


@pytest.mark.parametrize(
    'invalid_value',
    [
        -1,
        -0.1,
        float('nan'),
        float('inf'),
        Decimal('-0.1'),
        Decimal('NaN'),
        Decimal('Infinity'),
        True,
    ],
)
def test_usage_extractor_rejects_invalid_component_before_accumulation(invalid_value: Any) -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path='invalid', dest='audio_seconds', required=False),
            UsageExtractorMapping(path='offset', dest='audio_seconds'),
        ],
    )

    with pytest.raises(
        ValueError, match='Invalid usage value for audio_seconds: expected a finite non-negative int, float, or Decimal'
    ):
        extractor.extract({'model': 'test-model', 'usage': {'invalid': invalid_value, 'offset': 2}})


def test_public_extract_usage_preserves_fractional_values() -> None:
    response_data = {
        'model': 'gpt-4.1',
        'usage': {
            'prompt_tokens': 13.0,
            'completion_tokens': 0.25,
            'prompt_tokens_details': {'cached_tokens': None},
            'completion_tokens_details': {'reasoning_tokens': None},
        },
    }

    extracted = extract_usage(response_data, provider_id='openai', api_flavor='chat')

    assert extracted.usage == Usage(input_tokens=13.0, output_tokens=0.25)
    assert type(extracted.usage.input_tokens) is float
    assert type(extracted.usage.output_tokens) is float


def test_usage_extractor_skips_optional_nested_path_after_wrong_type_parent():
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path=['totals', 'nested', 'input_tokens'], dest='input_tokens', required=False),
            UsageExtractorMapping(path='output_tokens', dest='output_tokens'),
        ],
    )

    assert extractor.extract({'model': 'test-model', 'usage': {'totals': 1, 'output_tokens': 2}}) == (
        'test-model',
        Usage(output_tokens=2),
    )


def test_usage_extractor_accepts_sequence_root_path():
    extractor = UsageExtractor(
        root=['outer', 'usage'],
        mappings=[UsageExtractorMapping(path='input_tokens', dest='input_tokens')],
    )

    assert extractor.extract({'model': 'test-model', 'outer': {'usage': {'input_tokens': 3}}}) == (
        'test-model',
        Usage(input_tokens=3),
    )


def test_no_flavors():
    provider = Provider(id='test', name='Test', api_pattern='x')

    with pytest.raises(ValueError, match='No extraction logic defined for this provider'):
        provider.extract_usage({})


gemini_response_data = {
    'usageMetadata': {
        'promptTokenCount': 75,
        'candidatesTokenCount': 18,
        'totalTokenCount': 262,
        'trafficType': 'ON_DEMAND',
        'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 75}],
        'candidatesTokensDetails': [{'modality': 'TEXT', 'tokenCount': 18}],
        'toolUsePromptTokenCount': 25,
        'thoughtsTokenCount': 144,
    },
    'modelVersion': 'gemini-2.5-flash',
    'createTime': '2025-08-25T14:26:17.534704Z',
    'responseId': 'iXKsaLDRIPqsgLUPotqEyA0',
}
google_provider = next(provider for provider in providers if provider.id == 'google')
assert google_provider.name == 'Google'
assert google_provider.extractors is not None


def test_google():
    usage = google_provider.extract_usage(gemini_response_data)
    assert usage == snapshot(
        (
            'gemini-2.5-flash',
            Usage(
                input_tokens=100,
                output_tokens=162,
                input_text_tokens=75,
                output_text_tokens=18,
                input_tool_tokens=25,
                output_reasoning_tokens=144,
            ),
        )
    )


gemini_response_data_caching = {
    'usageMetadata': {
        'promptTokenCount': 14152,
        'candidatesTokenCount': 60,
        'totalTokenCount': 14271,
        'cachedContentTokenCount': 12239,
        'trafficType': 'ON_DEMAND',
        'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 14002}, {'modality': 'AUDIO', 'tokenCount': 150}],
        'cacheTokensDetails': [{'modality': 'AUDIO', 'tokenCount': 129}, {'modality': 'TEXT', 'tokenCount': 12110}],
        'candidatesTokensDetails': [{'modality': 'TEXT', 'tokenCount': 50}, {'modality': 'AUDIO', 'tokenCount': 10}],
        'thoughtsTokenCount': 69,
    },
    'modelVersion': 'gemini-2.5-flash',
}


def test_google_caching():
    model, usage = google_provider.extract_usage(gemini_response_data_caching)
    assert model == snapshot('gemini-2.5-flash')
    assert usage == snapshot(
        Usage(
            input_tokens=14152,
            output_tokens=129,
            cache_read_tokens=12239,
            input_text_tokens=14002,
            output_text_tokens=50,
            cache_text_read_tokens=12110,
            input_audio_tokens=150,
            output_audio_tokens=10,
            cache_audio_read_tokens=129,
            output_reasoning_tokens=69,
        ),
    )
    assert model is not None
    assert calc_price(usage, model).total_price == snapshot(Decimal('0.0012873'))


def test_google_caching_public_extraction_parity():
    extracted_usage = extract_usage(gemini_response_data_caching, provider_id='google')

    assert extracted_usage.usage == snapshot(
        Usage(
            input_tokens=14152,
            output_tokens=129,
            cache_read_tokens=12239,
            input_text_tokens=14002,
            output_text_tokens=50,
            cache_text_read_tokens=12110,
            input_audio_tokens=150,
            output_audio_tokens=10,
            cache_audio_read_tokens=129,
            output_reasoning_tokens=69,
        )
    )
    assert extracted_usage.model is not None
    assert (
        extracted_usage.calc_price().total_price
        == calc_price(
            extracted_usage.usage,
            extracted_usage.model.id,
            provider_id='google',
        ).total_price
    )


def test_google_extracts_text_image_and_video_token_details():
    response_data = {
        'usageMetadata': {
            'promptTokenCount': 1_000,
            'candidatesTokenCount': 500,
            'cachedContentTokenCount': 300,
            'promptTokensDetails': [
                {'modality': 'TEXT', 'tokenCount': 600},
                {'modality': 'IMAGE', 'tokenCount': 250},
                {'modality': 'DOCUMENT', 'tokenCount': 50},
                {'modality': 'VIDEO', 'tokenCount': 150},
            ],
            'cacheTokensDetails': [
                {'modality': 'TEXT', 'tokenCount': 100},
                {'modality': 'IMAGE', 'tokenCount': 125},
                {'modality': 'DOCUMENT', 'tokenCount': 25},
                {'modality': 'VIDEO', 'tokenCount': 75},
            ],
            'candidatesTokensDetails': [
                {'modality': 'TEXT', 'tokenCount': 300},
                {'modality': 'IMAGE', 'tokenCount': 125},
                {'modality': 'DOCUMENT', 'tokenCount': 25},
                {'modality': 'VIDEO', 'tokenCount': 75},
            ],
        },
        'modelVersion': 'gemini-2.5-flash',
    }

    assert google_provider.extract_usage(response_data) == (
        'gemini-2.5-flash',
        Usage(
            input_tokens=1_000,
            cache_read_tokens=300,
            output_tokens=500,
            input_text_tokens=600,
            cache_text_read_tokens=100,
            output_text_tokens=300,
            input_image_tokens=300,
            input_video_tokens=150,
            cache_image_read_tokens=150,
            cache_video_read_tokens=75,
            output_image_tokens=150,
            output_video_tokens=75,
        ),
    )


def test_google_extracts_tool_use_modalities_from_details():
    response_data = {
        'usageMetadata': {
            'promptTokenCount': 10,
            'candidatesTokenCount': 3,
            'thoughtsTokenCount': 4,
            'toolUsePromptTokenCount': 25,
            'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 10}],
            'candidatesTokensDetails': [{'modality': 'TEXT', 'tokenCount': 3}],
            'toolUsePromptTokensDetails': [
                {'modality': 'TEXT', 'tokenCount': 10},
                {'modality': 'AUDIO', 'tokenCount': 5},
                {'modality': 'IMAGE', 'tokenCount': 5},
                {'modality': 'DOCUMENT', 'tokenCount': 2},
                {'modality': 'VIDEO', 'tokenCount': 3},
            ],
        },
        'modelVersion': 'gemini-2.5-flash',
    }

    assert google_provider.extract_usage(response_data) == (
        'gemini-2.5-flash',
        Usage(
            input_tokens=35,
            output_tokens=7,
            input_text_tokens=20,
            output_text_tokens=3,
            input_audio_tokens=5,
            input_audio_tool_tokens=5,
            input_image_tokens=7,
            input_image_tool_tokens=7,
            input_video_tokens=3,
            input_video_tool_tokens=3,
            input_tool_tokens=25,
            input_text_tool_tokens=10,
            output_reasoning_tokens=4,
        ),
    )


gemini_response_data_thoughtless = {
    'usageMetadata': {
        'promptTokenCount': 75,
        'candidatesTokenCount': 18,
        'totalTokenCount': 237,
        'trafficType': 'ON_DEMAND',
        'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 75}],
        'candidatesTokensDetails': [{'modality': 'TEXT', 'tokenCount': 18}],
    },
    'modelVersion': 'gemini-2.5-flash',
    'createTime': '2025-08-25T14:26:17.534704Z',
    'responseId': 'iXKsaLDRIPqsgLUPotqEyA0',
}


def test_gemini_response_thoughtless():
    usage = google_provider.extract_usage(gemini_response_data_thoughtless)
    assert usage == snapshot(
        ('gemini-2.5-flash', Usage(input_tokens=75, output_tokens=18, input_text_tokens=75, output_text_tokens=18))
    )


def test_bedrock():
    provider = next(provider for provider in providers if provider.id == 'aws')
    assert provider.name == 'AWS Bedrock'
    assert provider.extractors is not None

    response_data_cache_write = {
        'usage': {'cacheReadInputTokens': 0, 'cacheWriteInputTokens': 11207, 'inputTokens': 9, 'outputTokens': 5}
    }
    usage = provider.extract_usage(response_data_cache_write)
    assert usage == snapshot(
        (None, Usage(input_tokens=11216, cache_write_tokens=11207, cache_read_tokens=0, output_tokens=5))
    )

    extracted_usage = extract_usage(response_data_cache_write, provider_id='aws')
    assert extracted_usage.usage == snapshot(
        Usage(input_tokens=11216, cache_write_tokens=11207, cache_read_tokens=0, output_tokens=5)
    )
    assert extracted_usage.provider.name == snapshot('AWS Bedrock')
    assert extracted_usage.model == snapshot(None)

    response_data_cache_read = {
        'usage': {'cacheReadInputTokens': 11207, 'cacheWriteInputTokens': 0, 'inputTokens': 9, 'outputTokens': 5}
    }
    usage = provider.extract_usage(response_data_cache_read)
    assert usage == snapshot(
        (None, Usage(input_tokens=11216, cache_write_tokens=0, cache_read_tokens=11207, output_tokens=5))
    )

    extracted_usage = extract_usage(response_data_cache_read, provider_id='aws')
    assert extracted_usage.usage == snapshot(
        Usage(input_tokens=11216, cache_write_tokens=0, cache_read_tokens=11207, output_tokens=5)
    )
    assert extracted_usage.provider.name == snapshot('AWS Bedrock')
    assert extracted_usage.model == snapshot(None)

    response_data_no_cache = {'usage': {'inputTokens': 406, 'outputTokens': 53}}
    usage = provider.extract_usage(response_data_no_cache)
    assert usage == snapshot((None, Usage(input_tokens=406, output_tokens=53)))

    extracted_usage = extract_usage(response_data_no_cache, provider_id='aws')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=406, output_tokens=53))
    assert extracted_usage.provider.name == snapshot('AWS Bedrock')
    assert extracted_usage.model == snapshot(None)

    # boto3 endpoint URLs have no trailing slash
    extracted_usage_by_url = extract_usage(
        response_data_no_cache, provider_api_url='https://bedrock-runtime.us-east-1.amazonaws.com'
    )
    assert extracted_usage_by_url.provider.name == snapshot('AWS Bedrock')
    assert extracted_usage_by_url.usage == snapshot(Usage(input_tokens=406, output_tokens=53))

    response_data_pricing = {
        'model': 'amazon.nova-lite-v1:0',
        'usage': {'cacheReadInputTokens': 1504, 'cacheWriteInputTokens': 0, 'inputTokens': 13, 'outputTokens': 5},
    }
    extracted_usage = extract_usage(response_data_pricing, provider_id='aws')
    assert extracted_usage.usage == snapshot(
        Usage(input_tokens=1517, cache_write_tokens=0, cache_read_tokens=1504, output_tokens=5)
    )
    assert extracted_usage.provider.name == snapshot('AWS Bedrock')
    assert extracted_usage.model is not None
    assert extracted_usage.model.id == snapshot('amazon.nova-lite-v1:0')
    assert extracted_usage.calc_price().total_price == snapshot(Decimal('0.00002454'))


anthropic_response_data = {
    'model': 'claude-sonnet-4-20250514',
    'usage': {
        'input_tokens': 483,
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 0,
        'output_tokens': 78,
    },
}


def test_google_anthropic():
    usage = google_provider.extract_usage(anthropic_response_data, api_flavor='anthropic')
    assert usage == snapshot(
        (
            'claude-sonnet-4-20250514',
            Usage(input_tokens=483, cache_write_tokens=0, cache_read_tokens=0, output_tokens=78),
        )
    )


@pytest.mark.parametrize('dest', ['imaginary_tokens', 'input_mtok', 'requests'])
def test_extractor_warns_and_skips_invalid_destination_string(dest: str) -> None:
    with pytest.warns(UserWarning, match=f'Unsupported extractor destination for standard extraction: {dest}'):
        extractor = UsageExtractor(
            root='usage',
            mappings=[UsageExtractorMapping(path='missing_tokens', dest=dest)],
        )

    assert extractor.extract({'model': 'test-model', 'usage': {}}) == ('test-model', Usage())


def test_extractor_accumulates_by_destination_string() -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path='prompt_tokens', dest='input_tokens'),
            UsageExtractorMapping(path='cached_tokens', dest='input_tokens', required=False),
            UsageExtractorMapping(path='missing_tokens', dest='output_tokens', required=False),
        ],
    )

    assert extractor.extract({'model': 'test-model', 'usage': {'prompt_tokens': 100, 'cached_tokens': 25}}) == (
        'test-model',
        Usage(input_tokens=125),
    )


def test_runtime_extractor_uses_active_global_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = UnitRegistry(
        {
            'input_tokens': {
                'per': 1_000_000,
                'price_key': 'input_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
            'sausage_tokens': {
                'per': 1_000_000,
                'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
            },
        }
    )
    monkeypatch.setattr('genai_prices.units._get_registry', lambda: registry)

    extractor = UsageExtractor(
        root='usage',
        mappings=[UsageExtractorMapping(path='sausage_tokens', dest='sausage_tokens')],
    )

    assert extractor.extract({'model': 'test-model', 'usage': {'sausage_tokens': 7}}) == (
        'test-model',
        Usage(sausage_tokens=7),
    )


def test_extractor_accumulates_repeated_destination_string_with_zero_values() -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path='prompt_tokens', dest='input_tokens'),
            UsageExtractorMapping(path='cached_tokens', dest='input_tokens'),
        ],
    )

    assert extractor.extract({'model': 'test-model', 'usage': {'prompt_tokens': 0, 'cached_tokens': 25}}) == (
        'test-model',
        Usage(input_tokens=25),
    )


def test_array_match_skips_non_mapping_items_before_match() -> None:
    extractor = UsageExtractor(
        root=['usage', ArrayMatch(type='array-match', field='modality', match=ClauseEquals('AUDIO')), 'data'],
        mappings=[UsageExtractorMapping(path='tokenCount', dest='input_audio_tokens')],
    )

    assert extractor.extract(
        {
            'model': 'test-model',
            'usage': [None, {'modality': None}, {'modality': 'AUDIO', 'data': {'tokenCount': 9}}],
        }
    ) == (
        'test-model',
        Usage(input_audio_tokens=9),
    )


def test_extractor_ignores_unknown_response_extras() -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[UsageExtractorMapping(path='prompt_tokens', dest='input_tokens')],
    )

    assert extractor.extract(
        {'model': 'test-model', 'usage': {'prompt_tokens': 100, 'provider_specific_tokens': 999}}
    ) == (
        'test-model',
        Usage(input_tokens=100),
    )


def test_pricing_rejects_registered_contradictions_with_registry_message() -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path='prompt_tokens', dest='input_tokens'),
            UsageExtractorMapping(path='audio_tokens', dest='input_audio_tokens'),
        ],
    )

    _, usage = extractor.extract({'model': 'test-model', 'usage': {'prompt_tokens': 50, 'audio_tokens': 100}})

    assert usage == Usage(input_tokens=50, input_audio_tokens=100)
    assert usage.input_tokens == 50
    with pytest.raises(ValueError, match='input_audio_tokens .* cannot exceed input_tokens'):
        ModelPrice(input_mtok=Decimal('1'), input_audio_mtok=Decimal('2')).calc_price(usage)


def test_accumulate_extracted_usage():
    extracted = extract_usage(gemini_response_data, provider_id='google')
    assert extracted.usage == Usage(
        input_tokens=100,
        output_tokens=162,
        input_text_tokens=75,
        output_text_tokens=18,
        input_tool_tokens=25,
        output_reasoning_tokens=144,
    )
    with pytest.raises(TypeError):
        _ = extracted + 1
    with pytest.raises(TypeError):
        _ = None + extracted
    with pytest.raises(TypeError):
        _ = extracted + None
    with pytest.raises(ValueError):
        _ = extracted + extract_usage(anthropic_response_data, provider_id='anthropic')
    with pytest.raises(ValueError, match='providers do not match'):
        _ = extracted + ExtractedUsage(
            usage=Usage(input_tokens=1),
            model=extracted.model,
            provider=Provider(id='other', name='Other', api_pattern='https://other.example'),
            auto_update_timestamp=None,
        )
    double_extracted = extracted + extracted
    assert double_extracted.usage == Usage(
        input_tokens=100 * 2,
        output_tokens=162 * 2,
        input_text_tokens=75 * 2,
        output_text_tokens=18 * 2,
        input_tool_tokens=25 * 2,
        output_reasoning_tokens=144 * 2,
    )
    assert repr(double_extracted) == snapshot(
        "ExtractedUsage(usage=Usage(input_tokens=200, output_tokens=324, input_text_tokens=150, output_text_tokens=36, input_tool_tokens=50, output_reasoning_tokens=288), model=Model(id='gemini-2.5-flash', name='Gemini 2.5 Flash', ...), provider=Provider(id='google', name='Google', ...), auto_update_timestamp=None)"
    )
    assert repr(double_extracted.calc_price()) == snapshot(
        "PriceCalculation(input_price=Decimal('0.00006'), output_price=Decimal('0.00081'), total_price=Decimal('0.00087'), model=Model(id='gemini-2.5-flash', name='Gemini 2.5 Flash', ...), provider=Provider(id='google', name='Google', ...), model_price=ModelPrice($0.3/input MTok, $2.5/output MTok, $0.03/input cache read MTok, $1/input audio MTok, $0.1/input audio cache read MTok), auto_update_timestamp=None)"
    )
    assert Usage(input_tokens=10, output_tokens=10) + Usage(output_tokens=10) == Usage(
        input_tokens=10, output_tokens=20
    )
    assert Usage(input_audio_tokens=10) + Usage(input_tokens=10) == Usage(input_audio_tokens=10, input_tokens=10)
    assert Usage(input_tokens=1).__radd__(Usage(output_tokens=2)) == Usage(input_tokens=1, output_tokens=2)
    with pytest.raises(TypeError):
        _ = Usage() + 1


def test_xai_native():
    provider = next(provider for provider in providers if provider.id == 'x-ai')
    response_data = {
        'model': 'grok-4-fast-reasoning',
        'usage': {
            'prompt_tokens': 181,
            'cached_prompt_text_tokens': 162,
            'completion_tokens': 27,
            'reasoning_tokens': 19,
            'prompt_text_tokens': 181,
            'total_tokens': 227,
        },
    }
    model, usage = provider.extract_usage(response_data)
    assert model == 'grok-4-fast-reasoning'
    assert usage == Usage(input_tokens=181, cache_read_tokens=162, output_tokens=46, output_reasoning_tokens=19)

    extracted_usage = extract_usage(response_data, provider_id='x-ai')
    assert extracted_usage.usage == usage
    assert extracted_usage.calc_price().total_price == Decimal('0.0000349')


def test_xai_realtime_duration_and_message_usage_and_price() -> None:
    provider = next(provider for provider in providers if provider.id == 'x-ai')
    response_data: dict[str, Any] = {
        'type': 'response.done',
        'response': {
            'usage': {
                'input_tokens': 5,
                'input_token_details': {'text_tokens': 5, 'audio_tokens': 0},
                'output_tokens': 42,
                'output_token_details': {'text_tokens': 3, 'audio_tokens': 39},
                'billable_audio_seconds': 60,
                'input_text_messages': 2,
            }
        },
    }

    model, usage = provider.extract_usage(response_data, api_flavor='realtime')
    price = calc_price(usage, model_ref='grok-voice-think-fast-1.0', provider_id='x-ai')

    assert model is None
    assert usage == Usage(
        input_tokens=5,
        output_tokens=42,
        input_text_tokens=5,
        output_text_tokens=3,
        input_audio_tokens=0,
        output_audio_tokens=39,
        input_text_messages=2,
        audio_seconds=60,
    )
    assert price.input_price == Decimal('0.008')
    assert price.output_price == 0
    assert price.total_price == Decimal('0.058')


def test_xai_transcription_duration_usage_and_price() -> None:
    provider = next(provider for provider in providers if provider.id == 'x-ai')

    model, usage = provider.extract_usage(
        {'text': 'Hello.', 'language': 'en', 'duration': 90, 'words': []},
        api_flavor='transcription',
    )
    price = calc_price(usage, model_ref='grok-transcribe', provider_id='x-ai')

    assert model is None
    assert usage == Usage(audio_seconds=90, input_audio_seconds=90)
    assert price.input_price == Decimal('0.005')
    assert price.output_price == 0
    assert price.total_price == Decimal('0.005')


@pytest.mark.parametrize(
    ('provider_id', 'expected_output_tokens'),
    [('azure', 8), ('google', 8), ('x-ai', 14)],
)
def test_openai_compatible_reasoning_tokens(provider_id: str, expected_output_tokens: int):
    provider = next(provider for provider in providers if provider.id == provider_id)
    response_data = {
        'model': 'reasoning-model',
        'usage': {
            'prompt_tokens': 10,
            'completion_tokens': 8,
            'completion_tokens_details': {'reasoning_tokens': 6},
        },
    }

    assert provider.extract_usage(response_data, api_flavor='chat') == (
        'reasoning-model',
        Usage(input_tokens=10, output_tokens=expected_output_tokens, output_reasoning_tokens=6),
    )


def test_perplexity_deep_research_additive_output_categories():
    response_data = {
        'model': 'sonar-deep-research',
        'usage': {
            'prompt_tokens': 33,
            'completion_tokens': 11_395,
            'total_tokens': 11_428,
            'citation_tokens': 19_028,
            'num_search_queries': 21,
            'reasoning_tokens': 193_947,
        },
    }

    extracted = extract_usage(response_data, provider_id='perplexity')

    assert extracted.usage == Usage(
        input_tokens=33,
        output_tokens=224_370,
        output_reasoning_tokens=193_947,
        output_citation_tokens=19_028,
        web_searches=21,
    )
    price = extracted.calc_price()
    assert price.input_price == Decimal('0.000066')
    assert price.output_price == Decimal('0.711057')
    assert price.total_price == Decimal('0.816123')


def test_perplexity_reasoning_pro_reports_reasoning_in_completion_tokens():
    response_data = {
        'model': 'sonar-reasoning-pro',
        'usage': {
            'prompt_tokens': 17,
            'completion_tokens': 1_152,
            'total_tokens': 1_169,
        },
    }

    extracted = extract_usage(response_data, provider_id='perplexity')

    assert extracted.usage == Usage(input_tokens=17, output_tokens=1_152)
