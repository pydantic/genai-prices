import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price, extract_usage
from genai_prices.data import providers
from genai_prices.types import Provider


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
    provider = providers[0]
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
    provider = providers[0]
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


def test_google():
    usage = google_provider.extract_usage(gemini_response_data)
    assert usage == snapshot(('gemini-2.5-flash', Usage(input_tokens=75, output_tokens=162)))


gemini_response_data_caching = {
    'usageMetadata': {
        'promptTokenCount': 14152,
        'candidatesTokenCount': 50,
        'totalTokenCount': 14271,
        'cachedContentTokenCount': 12239,
        'trafficType': 'ON_DEMAND',
        'promptTokensDetails': [{'modality': 'TEXT', 'tokenCount': 14002}, {'modality': 'AUDIO', 'tokenCount': 150}],
        'cacheTokensDetails': [{'modality': 'AUDIO', 'tokenCount': 129}, {'modality': 'TEXT', 'tokenCount': 12110}],
        'candidatesTokensDetails': [{'modality': 'TEXT', 'tokenCount': 50}],
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
            cache_read_tokens=12110,
            output_tokens=119,
            input_audio_tokens=150,
            cache_audio_read_tokens=129,
        ),
    )
    assert model is not None
    assert calc_price(usage, model).total_price == snapshot(Decimal('0.001855625'))


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
    assert usage == snapshot(('gemini-2.5-flash', Usage(input_tokens=75, output_tokens=18)))


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
