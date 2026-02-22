from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from dirty_equals import IsStr
from inline_snapshot import snapshot
from rich.console import Console

import genai_prices._cli as cli_module
from genai_prices._cli import cli_logic
from genai_prices.data import providers
from genai_prices.types import ModelPrice, TieredPrices


def _find_model_ref(predicate: Callable[[ModelPrice], bool], *, exclude: set[str] | None = None) -> str:
    exclude = exclude or set()
    now = datetime.now(timezone.utc)
    for provider in providers:
        for model in provider.models:
            prices = model.get_prices(now)
            if predicate(prices):
                model_ref = f'{provider.id}:{model.id}'
                if model_ref in exclude:
                    continue
                return model_ref
    raise AssertionError('No matching model found')


def _has_tiered_prices(model_price: ModelPrice) -> bool:
    return any(isinstance(getattr(model_price, field.name), TieredPrices) for field in dataclasses.fields(model_price))


def test_version(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--version']) == 0
    out, err = capsys.readouterr()
    assert out == IsStr(regex=r'genai-prices .*\n')
    assert err == ''


def test_version_plain(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', '--version']) == 0
    out, err = capsys.readouterr()
    assert out == IsStr(regex=r'genai-prices .*\n')
    assert err == ''


def test_cli_unknown_flag(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--unknown-flag']) == 2
    out, err = capsys.readouterr()
    assert out == ''
    assert 'unrecognized arguments: --unknown-flag' in err


def test_cli_no_subcommand_help(capsys: pytest.CaptureFixture[str]):
    assert cli_logic([]) == 1
    out, err = capsys.readouterr()
    assert 'usage:' in out.lower()
    assert err == ''


def test_parse_cli_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cli_module.sys, 'argv', [cli_module.PROGRAM_NAME, '--version'])
    cli = cli_module._parse_cli(None)
    assert cli.version is True


def test_cli_logic_missing_optional_cli_deps(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    def missing_impl() -> None:
        raise RuntimeError(
            'Optional CLI dependency \'rich\' is not installed. Install CLI extras with: pip install "genai-prices[cli]"'
        )

    monkeypatch.setattr(cli_module, '_load_impl', missing_impl)

    assert cli_module.cli_logic(['--version']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Install CLI extras with: pip install "genai-prices[cli]"' in err


def test_cli_entrypoint_missing_optional_cli_deps(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    def missing_impl() -> None:
        raise RuntimeError(
            'Optional CLI dependency \'rich\' is not installed. Install CLI extras with: pip install "genai-prices[cli]"'
        )

    monkeypatch.setattr(cli_module, '_load_impl', missing_impl)

    with pytest.raises(SystemExit, match='1'):
        cli_module.cli()

    out, err = capsys.readouterr()
    assert out == ''
    assert 'Install CLI extras with: pip install "genai-prices[cli]"' in err


def test_calc(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'calc', '--input-tokens', '1000', '--output-tokens', '100', 'gpt-4o']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: OpenAI
         Model: gpt 4o
  Model Prices: $2.5/input MTok, $1.25/cache read MTok, $10/output MTok
Context Window: 128,000
   Input Price: $0.0025
  Output Price: $0.001
   Total Price: $0.0035

""")
    assert err == ''


def test_calc_with_provider(capsys: pytest.CaptureFixture[str]):
    assert (
        cli_logic(
            [
                '--plain',
                'calc',
                '--input-tokens',
                '1000',
                '--output-tokens',
                '100',
                'azure:gpt-3.5-turbo-16k-0613',
            ]
        )
        == 0
    )
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: Microsoft Azure
         Model: GPT-3.5 Turbo 16k
  Model Prices: $3/input MTok, $4/output MTok
Context Window: 16,385
   Input Price: $0.003
  Output Price: $0.0004
   Total Price: $0.0034

""")
    assert err == ''


def test_calc_timestamp(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'calc', '--input-tokens', '10000', 'o3']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: OpenAI
         Model: o3
  Model Prices: $2/input MTok, $0.5/cache read MTok, $8/output MTok
   Input Price: $0.02
  Output Price: $0
   Total Price: $0.02

""")
    assert err == ''

    assert cli_logic(['--plain', 'calc', '--input-tokens', '10000', '--timestamp', '2025-06-01', 'o3']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: OpenAI
         Model: o3
  Model Prices: $10/input MTok, $0.5/cache read MTok, $40/output MTok
   Input Price: $0.1
  Output Price: $0
   Total Price: $0.1

""")
    assert err == ''


def test_list(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'list']) == 0
    out, err = capsys.readouterr()
    assert out.count('\n') > 100
    assert err == ''


def test_list_provider(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'list', 'deepseek']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
Deepseek: (2 models)
  deepseek:deepseek-chat: DeepSeek Chat
  deepseek:deepseek-reasoner: Deepseek R1
""")
    assert err == ''


def test_list_provider_wrong(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'list', 'foobar']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert err == IsStr(regex="^Error: provider 'foobar' not found in .*\n")


def test_list_rich(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['list']) == 0
    out, err = capsys.readouterr()
    assert 'models' in out
    assert err == ''


def test_list_provider_rich(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['list', 'deepseek']) == 0
    out, err = capsys.readouterr()
    assert 'deepseek' in out
    assert err == ''


def test_list_provider_wrong_rich(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['list', 'foobar']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Error:' in err


def test_calc_table_compact(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setenv('COLUMNS', '80')
    assert (
        cli_logic(['calc', '--no-color', '--table', '--input-tokens', '1000', '--output-tokens', '100', 'gpt-4o']) == 0
    )
    out, err = capsys.readouterr()
    assert 'Prices' in out
    assert 'Input/MTok' not in out
    assert err == ''


def test_calc_table_split_columns(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setenv('COLUMNS', '200')
    assert (
        cli_logic(
            [
                'calc',
                '--no-color',
                '--table',
                '--input-tokens',
                '1000',
                '--output-tokens',
                '100',
                'gpt-4o',
                'azure:gpt-3.5-turbo-16k-0613',
            ]
        )
        == 0
    )
    out, err = capsys.readouterr()
    assert 'Model Prices' not in out
    assert 'Input/MTok' in out
    assert 'Cache Read/MTok' in out
    assert 'Cache Write/MTok' not in out
    assert 'Input Audio/MTok' not in out
    assert err == ''


def test_calc_rich_columns(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--input-tokens', '1000', '--output-tokens', '100', 'gpt-4o', 'o3']) == 0
    out, err = capsys.readouterr()
    assert out.count('Provider') >= 2
    assert err == ''


def test_calc_no_color_vertical_table(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--no-color', '--input-tokens', '1000', '--output-tokens', '100', 'gpt-4o']) == 0
    out, err = capsys.readouterr()
    assert 'Provider' in out
    assert 'Model Prices' in out
    assert err == ''


def test_calc_keep_going(capsys: pytest.CaptureFixture[str]):
    assert (
        cli_logic(
            [
                'calc',
                '--keep-going',
                '--no-color',
                '--input-tokens',
                '1000',
                '--output-tokens',
                '100',
                'gpt-4o',
                'does-not-exist',
            ]
        )
        == 1
    )
    out, err = capsys.readouterr()
    assert 'gpt 4o' in out
    assert 'Error:' in err


def test_calc_keep_going_all_invalid(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--keep-going', '--input-tokens', '1000', 'does-not-exist']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Error:' in err


def test_calc_table_error_renders_summary(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setenv('COLUMNS', '200')
    assert cli_logic(['calc', '--table', '--input-tokens', '1000', 'gpt-4o', 'does-not-exist']) == 1
    out, err = capsys.readouterr()
    assert 'Provider' in out
    assert 'Error:' in err


def test_calc_table_empty_results(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setenv('COLUMNS', '200')
    assert cli_logic(['calc', '--table', '--keep-going', '--input-tokens', '1000', 'does-not-exist']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Error:' in err


def test_calc_provider_suggestions(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'calc', '--input-tokens', '1000', 'opnai:gpt-4o']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Did you mean provider: openai' in err


def test_calc_model_suggestions(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'calc', '--input-tokens', '1000', 'openai:gpt-4o0']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Did you mean: openai:gpt-4o' in err


def test_calc_provider_suggestions_rich_color(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--input-tokens', '1000', 'opnai:gpt-4o']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Did you mean provider:' in err


def test_calc_provider_suggestions_rich_no_color(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--no-color', '--input-tokens', '1000', 'opnai:gpt-4o']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Did you mean provider: openai' in err


def test_calc_model_suggestions_rich_color(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--input-tokens', '1000', 'openai:gpt-4o0']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Did you mean:' in err


def test_calc_model_suggestions_rich_no_color(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--no-color', '--input-tokens', '1000', 'openai:gpt-4o0']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Did you mean: openai:gpt-4o' in err


def test_calc_requests_kcount_rich(capsys: pytest.CaptureFixture[str]):
    model_ref = _find_model_ref(lambda price: price.requests_kcount is not None)
    assert cli_logic(['calc', '--input-tokens', '1000', model_ref]) == 0
    out, err = capsys.readouterr()
    assert 'K requests' in out
    assert err == ''


def test_calc_table_split_columns_rich_prices(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    tiered_ref = _find_model_ref(_has_tiered_prices)
    requests_ref = _find_model_ref(
        lambda price: price.requests_kcount is not None,
        exclude={tiered_ref},
    )
    monkeypatch.setenv('COLUMNS', '200')
    assert cli_logic(['calc', '--table', '--input-tokens', '1000', tiered_ref, requests_ref]) == 0
    out, err = capsys.readouterr()
    assert '(+tiers)' in out
    assert 'Requests/K' in out
    assert err == ''


def test_split_model_price_columns_no_fields():
    console = Console(width=60)
    assert cli_module._should_split_model_price_columns(console, []) is False


def test_suggest_models_missing_provider():
    assert cli_module._suggest_models('gpt-4o', 'missing', providers) == []


def test_calc_update_prices(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, int | bool] = {'instances': 0, 'starts': 0}

    class DummyUpdatePrices:
        def __init__(self) -> None:
            calls['instances'] += 1

        def start(self, *, wait: bool = False) -> None:
            calls['starts'] += 1
            calls['wait'] = wait

    monkeypatch.setattr(cli_module.update_prices, 'UpdatePrices', DummyUpdatePrices)
    assert cli_logic(['--plain', 'calc', '--update-prices', '--input-tokens', '1000', 'gpt-4o', 'gpt-4o']) == 0
    assert calls == {'instances': 1, 'starts': 1, 'wait': True}
