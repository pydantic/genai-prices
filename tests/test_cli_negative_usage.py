from __future__ import annotations

import pytest

from genai_prices._cli import cli_logic


@pytest.mark.parametrize('leading_args,calc_args', [([], []), (['--plain'], []), ([], ['--no-color'])])
@pytest.mark.parametrize(
    'flag,usage_key',
    [
        ('--input-tokens', 'input_tokens'),
        ('--cache-write-tokens', 'cache_write_tokens'),
        ('--cache-read-tokens', 'cache_read_tokens'),
        ('--output-tokens', 'output_tokens'),
        ('--input-audio-tokens', 'input_audio_tokens'),
        ('--cache-audio-read-tokens', 'cache_audio_read_tokens'),
        ('--output-audio-tokens', 'output_audio_tokens'),
    ],
)
def test_negative_usage_returns_cli_error(
    leading_args: list[str],
    calc_args: list[str],
    flag: str,
    usage_key: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli_logic([*leading_args, 'calc', *calc_args, flag, '-1', 'gpt-4o']) == 1

    output, error = capsys.readouterr()
    assert output == ''
    assert error == (
        f'Error: Invalid usage value for {usage_key}: expected a finite non-negative int, float, or Decimal\n'
    )
