from decimal import Decimal

import pytest

from genai_prices._cli import cli_logic
from genai_prices.data_snapshot import DataSnapshot, set_custom_snapshot
from genai_prices.types import ClauseEquals, ModelInfo, ModelPrice, Provider


def _install_usage_models() -> None:
    set_custom_snapshot(
        DataSnapshot(
            providers=[
                Provider(
                    id='testing',
                    name='Testing',
                    api_pattern='testing',
                    models=[
                        ModelInfo(id='basic', match=ClauseEquals('basic'), prices=ModelPrice(input_mtok=Decimal('1'))),
                        ModelInfo(
                            id='detailed',
                            match=ClauseEquals('detailed'),
                            prices=ModelPrice(
                                input_mtok=Decimal('1'),
                                cache_write_mtok=Decimal('2'),
                                cache_read_mtok=Decimal('3'),
                                input_audio_mtok=Decimal('4'),
                                cache_audio_read_mtok=Decimal('5'),
                                cache_audio_write_mtok=Decimal('5'),
                                output_mtok=Decimal('6'),
                                output_audio_mtok=Decimal('7'),
                            ),
                        ),
                    ],
                )
            ],
            from_auto_update=False,
        )
    )


@pytest.mark.parametrize('leading_args, calc_args', [([], []), (['--plain'], []), ([], ['--no-color'])])
@pytest.mark.parametrize(
    'usage_args, message',
    [
        (['--input-tokens', '1', '--cache-write-tokens', '2'], 'cache_write_tokens (2) cannot exceed input_tokens (1)'),
        (['--input-tokens', '1', '--cache-read-tokens', '2'], 'cache_read_tokens (2) cannot exceed input_tokens (1)'),
        (['--input-tokens', '1', '--input-audio-tokens', '2'], 'input_audio_tokens (2) cannot exceed input_tokens (1)'),
        (
            [
                '--input-tokens',
                '3',
                '--cache-read-tokens',
                '3',
                '--input-audio-tokens',
                '1',
                '--cache-audio-read-tokens',
                '2',
            ],
            'cache_audio_read_tokens (2) cannot exceed input_audio_tokens (1)',
        ),
        (
            ['--output-tokens', '1', '--output-audio-tokens', '2'],
            'output_audio_tokens (2) cannot exceed output_tokens (1)',
        ),
        (
            ['--input-tokens', '1', '--cache-write-tokens', '1', '--cache-read-tokens', '1'],
            'more-specific usage for cache_read_tokens, cache_write_tokens totals 2, which exceeds input_tokens (1)',
        ),
    ],
)
def test_invalid_usage_relationship_returns_cli_error(
    leading_args: list[str],
    calc_args: list[str],
    usage_args: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_usage_models()

    assert cli_logic([*leading_args, 'calc', *calc_args, *usage_args, 'testing:detailed']) == 1

    output, error = capsys.readouterr()
    assert output == ''
    assert error == f'Error: Invalid usage data: {message}\n'


@pytest.mark.parametrize(
    'leading_args, calc_args', [([], []), (['--plain'], []), ([], ['--no-color']), ([], ['--table', '--no-color'])]
)
@pytest.mark.parametrize('keep_going', [False, True])
@pytest.mark.parametrize('invalid_first', [False, True])
def test_usage_relationship_errors_preserve_model_iteration(
    leading_args: list[str],
    calc_args: list[str],
    keep_going: bool,
    invalid_first: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_usage_models()
    models = ['testing:detailed', 'testing:basic'] if invalid_first else ['testing:basic', 'testing:detailed']
    flags = ['--keep-going'] if keep_going else []

    assert (
        cli_logic(
            [*leading_args, 'calc', *calc_args, *flags, '--input-tokens', '1', '--cache-read-tokens', '2', *models]
        )
        == 1
    )

    output, error = capsys.readouterr()
    assert ('basic' in output) is (keep_going or not invalid_first)
    assert error == 'Error: Invalid usage data: cache_read_tokens (2) cannot exceed input_tokens (1)\n'
