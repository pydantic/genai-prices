from typing import Any

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage
from genai_prices.data import providers
from genai_prices.types import Provider


@pytest.mark.parametrize(
    'response_data,expected',
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
            snapshot(
                (
                    'claude-sonnet-4-20250514',
                    Usage(input_tokens=504, cache_write_tokens=123, cache_read_tokens=0, output_tokens=97),
                )
            ),
        ),
        (
            {'model': 'x', 'usage': {'input_tokens': 504, 'output_tokens': 97, 'service_tier': 'standard'}},
            snapshot(('x', Usage(input_tokens=504, output_tokens=97))),
        ),
    ],
)
def test_extract_usage_ok(response_data: Any, expected: Usage):
    provider = providers[0]
    assert provider.name == 'Anthropic'
    assert provider.extractors is not None
    usage = provider.extract_usage(response_data)
    assert usage == expected


def test_openai():
    provider = next(provider for provider in providers if provider.id == 'openai')
    assert provider.name == 'OpenAI'
    assert provider.extractors is not None
    response_data = {
        'model': 'gpt-4.1',
        'usage': {'prompt_tokens': 100, 'completion_tokens': 100},
    }
    usage = provider.extract_usage(response_data, api_flavor='chat')
    assert usage == snapshot(('gpt-4.1', Usage(input_tokens=100, output_tokens=100)))

    response_data = {
        'model': 'gpt-5',
        'usage': {'input_tokens': 100, 'output_tokens': 100},
    }
    usage = provider.extract_usage(response_data, api_flavor='responses')
    assert usage == snapshot(('gpt-5', Usage(input_tokens=100, output_tokens=100)))


@pytest.mark.parametrize(
    'response_data,error',
    [
        ({}, snapshot('Missing value at `model`')),
        ({'model': None}, snapshot('Expected `model` value to be a str, got None')),
        ({'model': 'x'}, snapshot('Missing value at `usage`')),
        ({'model': 'x', 'usage': {}}, snapshot('Missing value at `usage.input_tokens`')),
        ({'model': 'x', 'usage': 123}, snapshot('Expected `usage` value to be a dict, got int')),
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


def test_unknown_flavor():
    provider = providers[0]
    assert provider.name == 'Anthropic'
    assert provider.extractors is not None

    with pytest.raises(ValueError, match="Unknown api_flavor 'wrong', allowed values: default"):
        provider.extract_usage({}, api_flavor='wrong')


def test_no_flavors():
    provider = Provider(id='test', name='Test', api_pattern='x')

    with pytest.raises(ValueError, match='No extraction logic defined for this provider'):
        provider.extract_usage({})
