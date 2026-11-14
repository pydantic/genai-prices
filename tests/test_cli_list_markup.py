from __future__ import annotations

import pytest

from genai_prices._cli import cli_logic


@pytest.mark.parametrize('plain', [False, True])
@pytest.mark.parametrize('provider_id', ['[/red]', '[bold]missing[/bold]', r'unknown\[red]'])
def test_unknown_provider_is_rendered_literally(
    plain: bool,
    provider_id: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr('genai_prices.data.providers', [])
    leading_args = ['--plain'] if plain else []

    assert cli_logic([*leading_args, 'list', provider_id]) == 1

    output, error = capsys.readouterr()
    assert output == ''
    assert error == f'Error: provider {provider_id!r} not found in []\n'
