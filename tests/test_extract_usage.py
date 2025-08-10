from typing import Any

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage
from genai_prices.data import providers


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
            snapshot(Usage(input_tokens=504, cache_write_tokens=123, cache_read_tokens=0, output_tokens=97)),
        ),
        (
            {'usage': {'input_tokens': 504, 'output_tokens': 97, 'service_tier': 'standard'}},
            snapshot(Usage(input_tokens=504, output_tokens=97)),
        ),
    ],
)
def test_extract_usage_ok(response_data: Any, expected: Usage):
    provider = providers[0]
    assert provider.name == 'Anthropic'
    assert provider.extract is not None
    usage = provider.extract_usage(response_data)
    assert usage == expected


@pytest.mark.parametrize(
    'response_data,error',
    [
        ({}, snapshot('Missing value at `usage`')),
        ({'usage': {}}, snapshot('Missing value at `usage.input_tokens`')),
        ({'usage': 123}, snapshot('Expected `usage` value to be a dict, got int')),
        ({'usage': {'input_tokens': []}}, snapshot('Expected `usage.input_tokens` value to be a int, got list')),
    ],
)
def test_extract_usage_error(response_data: Any, error: str):
    provider = providers[0]
    assert provider.name == 'Anthropic'
    assert provider.extract is not None

    with pytest.raises(ValueError) as exc_info:
        provider.extract_usage(response_data)

    assert str(exc_info.value) == error
