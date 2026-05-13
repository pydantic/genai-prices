import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price, extract_usage
from genai_prices.data import providers
from genai_prices.types import ArrayMatch, ClauseEquals, ModelPrice, Provider, UsageExtractor, UsageExtractorMapping
from genai_prices.units import UnitRegistry


class MyMapping(Mapping[str, Any]):
    def __init__(self, **data: Any):
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Any:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


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
                    'cache_creation_input_tokens': 123,
                    'cache_read_input_tokens': 0,
                    'output_tokens': 97,
                    'service_tier': 'standard',
                },
            },
            snapshot('claude-sonnet-4-20250514'),
            snapshot(Usage(input_tokens=627, cache_write_tokens=123, cache_read_tokens=0, output_tokens=97)),
            snapshot(Decimal('0.00342825')),
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
            'completion_tokens_details': None,
        },
    }
    usage = provider.extract_usage(response_data, api_flavor='chat')
    assert usage == snapshot(('gpt-4.1', Usage(input_tokens=100, output_tokens=200)))

    extracted_usage = extract_usage(response_data, provider_id='openai', api_flavor='chat')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=100, output_tokens=200))
    assert extracted_usage.provider.name == snapshot('OpenAI')
    assert extracted_usage.model is not None
    assert extracted_usage.model.name == snapshot('gpt 4.1')

    assert extracted_usage.calc_price().total_price == snapshot(Decimal('0.0018'))

    response_data = {
        'model': 'gpt-5',
        'usage': {'input_tokens': 100, 'output_tokens': 200},
    }
    usage = provider.extract_usage(response_data, api_flavor='responses')
    assert usage == snapshot(('gpt-5', Usage(input_tokens=100, output_tokens=200)))

    extracted_usage = extract_usage(response_data, provider_id='openai', api_flavor='responses')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=100, output_tokens=200))
    assert extracted_usage.provider.name == snapshot('OpenAI')
    assert extracted_usage.model is not None
    assert extracted_usage.model.name == snapshot('GPT-5')

    assert extracted_usage.calc_price().total_price == snapshot(Decimal('0.002125'))

    with pytest.raises(ValueError, match=re.escape("Unknown api_flavor 'default', allowed values: chat, responses")):
        provider.extract_usage(response_data)


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
        )
    )
    assert extracted_usage.provider.name == snapshot('OpenRouter')
    assert extracted_usage.model is not None
    assert extracted_usage.model.id == snapshot('anthropic/claude-sonnet-4.6')

    extracted_usage_by_url = extract_usage(
        response_data, provider_api_url='https://openrouter.ai/api/v1', api_flavor='chat'
    )
    assert extracted_usage_by_url.usage == extracted_usage.usage


@pytest.mark.parametrize(
    'response_data,error',
    [
        ({}, snapshot('Missing value at `usage`')),
        ({'model': None}, snapshot('Missing value at `usage`')),
        ({'model': 'x'}, snapshot('Missing value at `usage`')),
        ({'model': 'x', 'usage': {}}, snapshot('Missing value at `usage.input_tokens`')),
        ({'model': 'x', 'usage': 123}, snapshot('Expected `usage` value to be a Mapping, got int')),
        (
            {'model': 'x', 'usage': {'input_tokens': 123.0}},
            snapshot('Expected `usage.input_tokens` value to be a int, got float'),
        ),
        (
            {'model': 'x', 'usage': {'input_tokens': []}},
            snapshot('Expected `usage.input_tokens` value to be a int, got list'),
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


def test_no_flavors():
    provider = Provider(id='test', name='Test', api_pattern='x')

    with pytest.raises(ValueError, match='No extraction logic defined for this provider'):
        provider.extract_usage({})


gemini_response_data = {
    'usageMetadata': {
        'promptTokenCount': 75,
        'candidatesTokenCount': 18,
        'totalTokenCount': 237,
        'trafficType': 'ON_DEMAND',
        'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 75}],
        'candidatesTokensDetails': [{'modality': 'TEXT', 'tokenCount': 18}],
        'thoughtsTokenCount': 144,
    },
    'modelVersion': 'gemini-2.5-flash',
    'createTime': '2025-08-25T14:26:17.534704Z',
    'responseId': 'iXKsaLDRIPqsgLUPotqEyA0',
}
google_provider = next(provider for provider in providers if provider.id == 'google')
assert google_provider.name == 'Google'
assert google_provider.extractors is not None


def test_google_default_extractor_mappings_are_complete():
    google_extractors = google_provider.extractors
    assert google_extractors is not None
    google_extractor = next(extractor for extractor in google_extractors if extractor.api_flavor == 'default')
    detail_arrays = {
        'promptTokensDetails': 'input',
        'cacheTokensDetails': 'cache_read',
        'candidatesTokensDetails': 'output',
        'toolUsePromptTokensDetails': 'output',
    }
    modalities = ('TEXT', 'AUDIO', 'IMAGE', 'DOCUMENT', 'VIDEO')
    scalar_mappings = (
        (('promptTokenCount',), 'input_tokens'),
        (('cachedContentTokenCount',), 'cache_read_tokens'),
        (('candidatesTokenCount',), 'output_tokens'),
        (('thoughtsTokenCount',), 'output_tokens'),
        (('thoughtsTokenCount',), 'output_text_tokens'),
        (('toolUsePromptTokenCount',), 'output_tokens'),
    )
    expected = {(path, dest, False) for path, dest in scalar_mappings} | {
        ((array_name, modality, 'tokenCount'), _google_modality_detail_dest(direction, modality), False)
        for array_name, direction in detail_arrays.items()
        for modality in modalities
    }
    actual = {_google_extractor_mapping_signature(mapping) for mapping in google_extractor.mappings}

    assert actual == expected


def _google_extractor_mapping_signature(mapping: UsageExtractorMapping) -> tuple[tuple[str, ...], str, bool]:
    return _google_extractor_path_signature(mapping.path), mapping.dest, mapping.required


def _google_extractor_path_signature(path: str | Sequence[str | ArrayMatch]) -> tuple[str, ...]:
    if isinstance(path, str):
        return (path,)
    assert len(path) == 3
    array_name, array_match, leaf = path
    assert isinstance(array_name, str)
    assert isinstance(array_match, ArrayMatch)
    assert isinstance(array_match.match, ClauseEquals)
    assert isinstance(leaf, str)
    return array_name, array_match.match.equals, leaf


def _google_modality_detail_dest(direction: str, modality: str) -> str:
    usage_modality = 'image' if modality == 'DOCUMENT' else modality.lower()
    if direction == 'cache_read':
        return f'cache_{usage_modality}_read_tokens'
    return f'{direction}_{usage_modality}_tokens'


def test_google():
    usage = google_provider.extract_usage(gemini_response_data)
    assert usage == snapshot(
        ('gemini-2.5-flash', Usage(input_tokens=75, output_tokens=162, input_text_tokens=75, output_text_tokens=162))
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
            output_text_tokens=119,
            cache_text_read_tokens=12110,
            input_audio_tokens=150,
            output_audio_tokens=10,
            cache_audio_read_tokens=129,
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
            output_text_tokens=119,
            cache_text_read_tokens=12110,
            input_audio_tokens=150,
            output_audio_tokens=10,
            cache_audio_read_tokens=129,
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
                {'modality': 'IMAGE', 'tokenCount': 7},
                {'modality': 'DOCUMENT', 'tokenCount': 2},
                {'modality': 'VIDEO', 'tokenCount': 3},
            ],
        },
        'modelVersion': 'gemini-2.5-flash',
    }

    assert google_provider.extract_usage(response_data) == (
        'gemini-2.5-flash',
        Usage(
            input_tokens=10,
            output_tokens=32,
            input_text_tokens=10,
            output_text_tokens=17,
            output_audio_tokens=5,
            output_image_tokens=9,
            output_video_tokens=3,
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
    response_data = {'usage': {'inputTokens': 406, 'outputTokens': 53}}
    usage = provider.extract_usage(response_data)
    assert usage == snapshot((None, Usage(input_tokens=406, output_tokens=53)))

    extracted_usage = extract_usage(response_data, provider_id='aws')
    assert extracted_usage.usage == snapshot(Usage(input_tokens=406, output_tokens=53))
    assert extracted_usage.provider.name == snapshot('AWS Bedrock')
    assert extracted_usage.model == snapshot(None)


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
def test_extractor_rejects_invalid_destination_string_at_construction(dest: str) -> None:
    with pytest.raises(ValueError, match=f'Invalid extractor destination: {dest}'):
        UsageExtractor(
            root='usage',
            mappings=[UsageExtractorMapping(path='prompt_tokens', dest=dest)],
        )


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
            'tokens': {
                'per': 1_000_000,
                'units': {
                    'input_tokens': {
                        'price_key': 'input_mtok',
                        'dimensions': {'direction': 'input'},
                    },
                    'sausage_tokens': {
                        'dimensions': {'direction': 'input', 'ingredient': 'sausage'},
                    },
                },
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
    assert extracted.usage == Usage(input_tokens=75, output_tokens=162, input_text_tokens=75, output_text_tokens=162)
    with pytest.raises(TypeError):
        _ = extracted + 1
    with pytest.raises(TypeError):
        _ = None + extracted
    with pytest.raises(TypeError):
        _ = extracted + None
    with pytest.raises(ValueError):
        _ = extracted + extract_usage(anthropic_response_data, provider_id='anthropic')
    double_extracted = extracted + extracted
    assert double_extracted.usage == Usage(
        input_tokens=75 * 2,
        output_tokens=162 * 2,
        input_text_tokens=75 * 2,
        output_text_tokens=162 * 2,
    )
    assert Usage(input_tokens=10, output_tokens=10) + Usage(output_tokens=10) == Usage(
        input_tokens=10, output_tokens=20
    )
    assert Usage(input_audio_tokens=10) + Usage(input_tokens=10) == Usage(input_audio_tokens=10, input_tokens=10)


def test_xai_native():
    provider = next(provider for provider in providers if provider.id == 'x-ai')
    response_data = {
        'model': 'grok-4-fast-non-reasoning',
        'usage': {
            'prompt_tokens': 181,
            'cached_prompt_text_tokens': 162,
            'completion_tokens': 27,
            'prompt_text_tokens': 181,
            'total_tokens': 208,
        },
    }
    model, usage = provider.extract_usage(response_data)
    assert model == 'grok-4-fast-non-reasoning'
    assert usage == Usage(input_tokens=181, cache_read_tokens=162, output_tokens=27)
