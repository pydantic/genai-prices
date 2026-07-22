from __future__ import annotations

import io
import subprocess
import sys
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from dirty_equals import IsStr
from inline_snapshot import snapshot
from rich.console import Console

import genai_prices._cli as cli_module
from genai_prices import update_prices
from genai_prices._cli import (
    _collect_model_price_fields,
    _format_model_price_value,
    _format_model_prices,
    _parse_cli,
    _price_field_label,
    _render_calc_error,
    _should_split_model_price_columns,
    _suggest_models,
    _unit_display_name,
    _unit_for_price_key,
    _unit_per_label,
    cli_logic,
)
from genai_prices.data import providers
from genai_prices.data_snapshot import DataSnapshot, set_custom_snapshot
from genai_prices.data_units import unit_data
from genai_prices.types import ClauseEquals, ModelInfo, ModelPrice, PriceCalculation, Provider, TieredPrices
from genai_prices.units import UnitDef, UnitRegistry


@contextmanager
def _use_registry(registry: UnitRegistry) -> Iterator[None]:
    with patch('genai_prices.units._get_registry', return_value=registry):
        yield


def _find_model_ref(predicate: Callable[[ModelPrice], bool], *, exclude: Collection[str] = frozenset()) -> str:
    now = datetime.now(timezone.utc)
    return next(
        f'{provider.id}:{model.id}'
        for provider in providers
        for model in provider.models
        if predicate(model.get_prices(now)) and f'{provider.id}:{model.id}' not in exclude
    )


def _has_tiered_prices(model_price: ModelPrice) -> bool:
    fields = _collect_model_price_fields([_price_calculation(model_price)])
    return any(isinstance(getattr(model_price, field_name), TieredPrices) for field_name in fields)


def _price_calculation(model_price: ModelPrice) -> PriceCalculation:
    provider = Provider(id='testing', name='Testing', api_pattern='testing', models=[])
    model = ModelInfo(id='model', match=ClauseEquals('model'), prices=model_price)
    return PriceCalculation(
        input_price=Decimal('0'),
        output_price=Decimal('0'),
        total_price=Decimal('0'),
        model=model,
        provider=provider,
        model_price=model_price,
        auto_update_timestamp=None,
    )


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
    assert 'calc' in out
    assert 'list' in out
    assert err == ''


def test_parse_cli_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cli_module.sys, 'argv', [cli_module.PROGRAM_NAME, '--version'])
    cli = _parse_cli(None)
    assert cli.version is True


def test_cli_import_exits_for_missing_optional_dependency():
    package_path = Path(__file__).parents[1] / 'packages' / 'python'
    script_path = Path(__file__).with_name('cli_missing_dependency_import.py')

    result = subprocess.run(
        [sys.executable, str(script_path), str(package_path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert result.stdout == ''
    assert result.stderr == (
        'Optional CLI dependency \'rich\' is not installed. Install CLI extras with: pip install "genai-prices[cli]"\n'
    )


def test_render_calc_error_escapes_rich_markup_in_message():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    _render_calc_error(
        console,
        message='bad [red]oops[/] message',
        model_ref='gpt-4o',
        provider_id=None,
        providers=[],
        plain=False,
        use_color=True,
    )

    assert '[red]oops[/]' in stream.getvalue()


def test_calc(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'calc', '--input-tokens', '1000', '--output-tokens', '100', 'gpt-4o']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: OpenAI
         Model: gpt 4o
  Model Prices: $2.5/input MTok, $10/output MTok, $1.25/input cache read MTok
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


def test_calc_plain_model_prices_use_cli_formatter(capsys: pytest.CaptureFixture[str]):
    custom_units = dict(unit_data)
    custom_units['sausage_tokens'] = {
        'per': 1_000_000,
        'price_key': 'sausage_mtok',
        'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
    }
    registry = UnitRegistry(custom_units)
    set_custom_snapshot(
        DataSnapshot(
            providers=[
                Provider(
                    id='testing',
                    name='Testing',
                    api_pattern='testing',
                    models=[
                        ModelInfo(
                            id='sausage',
                            match=ClauseEquals('sausage'),
                            prices=ModelPrice(input_mtok=Decimal('1'), sausage_mtok=Decimal('2')),
                        )
                    ],
                )
            ],
            from_auto_update=False,
        )
    )
    try:
        with _use_registry(registry):
            assert cli_logic(['--plain', 'calc', '--input-tokens', '1000', 'testing:sausage']) == 0
            out, err = capsys.readouterr()
    finally:
        set_custom_snapshot(None)

    assert '  Model Prices: $1/input MTok, $2/input sausage MTok\n' in out
    assert err == ''


def test_calc_timestamp(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'calc', '--input-tokens', '10000', 'o3']) == 0
    out, err = capsys.readouterr()
    assert out == snapshot("""\
      Provider: OpenAI
         Model: o3
  Model Prices: $2/input MTok, $8/output MTok, $0.5/input cache read MTok
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
  Model Prices: $10/input MTok, $40/output MTok, $0.5/input cache read MTok
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
Deepseek: (7 models)
  deepseek:deepseek-chat: DeepSeek Chat
  deepseek:deepseek-reasoner: Deepseek R1
  deepseek:deepseek-v3.1-terminus: DeepSeek V3.1 Terminus
  deepseek:deepseek-v3.2: DeepSeek V3.2
  deepseek:deepseek-v3.2-exp: DeepSeek V3.2 Exp
  deepseek:deepseek-v4-flash: DeepSeek V4 Flash
  deepseek:deepseek-v4-pro: DeepSeek V4 Pro
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


def test_calc_unknown_provider_without_suggestions(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['--plain', 'calc', '--input-tokens', '1000', 'zzzzzz:gpt-4o']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Error:' in err
    assert 'Did you mean provider:' not in err


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


def test_calc_provider_suggestions_rich_color_multiple(capsys: pytest.CaptureFixture[str]):
    assert cli_logic(['calc', '--input-tokens', '1000', 'coher:gpt-4o']) == 1
    out, err = capsys.readouterr()
    assert out == ''
    assert 'Did you mean provider:' in err
    assert 'cohere' in err
    assert 'together' in err


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


def test_calc_requests_kcount_no_color(capsys: pytest.CaptureFixture[str]):
    model_ref = _find_model_ref(lambda price: price.requests_kcount is not None)
    assert cli_logic(['calc', '--no-color', '--input-tokens', '1000', model_ref]) == 0
    out, err = capsys.readouterr()
    assert 'K requests' in out
    assert err == ''


def test_calc_tiered_prices_no_color(capsys: pytest.CaptureFixture[str]):
    model_ref = _find_model_ref(_has_tiered_prices)
    assert cli_logic(['calc', '--no-color', '--input-tokens', '1000', model_ref]) == 0
    out, err = capsys.readouterr()
    assert '(+tiers)' in out
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
    assert 'requests' in out.lower()
    assert err == ''


def test_price_field_label_uses_bundled_registry_metadata() -> None:
    assert _price_field_label('input_mtok') == 'Input/MTok'
    assert _price_field_label('cache_read_mtok') == 'Input Cache Read/MTok'
    assert _price_field_label('cache_audio_read_mtok') == 'Input Audio Cache Read/MTok'
    assert _price_field_label('web_searches_kcount') == 'Web Searches/K'
    assert _price_field_label('requests_kcount') == 'Requests/K'


def test_price_field_label_uses_custom_registry_metadata() -> None:
    registry = UnitRegistry(
        {
            'sausage_tokens': {
                'per': 1_000_000,
                'price_key': 'sausage_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
            }
        }
    )
    with _use_registry(registry):
        assert _price_field_label('sausage_mtok') == 'Input Sausage/MTok'


def test_format_model_prices_uses_bundled_registry_metadata() -> None:
    price = ModelPrice(
        input_mtok=Decimal('1'),
        cache_read_mtok=Decimal('0.5'),
        requests_kcount=Decimal('12'),
    )

    assert _format_model_prices(price, split_lines=False, use_color=False).plain == (
        '$1/input MTok, $0.5/input cache read MTok, $12 / K requests'
    )


def test_format_model_prices_preserves_tier_text() -> None:
    price = ModelPrice(input_mtok=TieredPrices(base=Decimal('1'), tiers=[]))

    assert _format_model_prices(price, split_lines=False, use_color=False).plain == '$1/input MTok (+tiers)'


def test_format_model_prices_uses_custom_registry_metadata() -> None:
    registry = UnitRegistry(
        {
            'input_tokens': {
                'per': 1_000_000,
                'price_key': 'input_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
            'sausage_tokens': {
                'per': 1_000_000,
                'price_key': 'sausage_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
            },
        }
    )
    with _use_registry(registry):
        price = ModelPrice(input_mtok=Decimal('1'), sausage_mtok=Decimal('2'))
        formatted = _format_model_prices(price, split_lines=True, use_color=False)

    assert formatted.plain == '$1/input MTok\n$2/input sausage MTok'


def test_format_model_price_value_uses_registry_backed_fields() -> None:
    price = ModelPrice(input_mtok=Decimal('1'), requests_kcount=Decimal('12'))

    assert _format_model_price_value(price, 'input_mtok', use_color=False).plain == '$1'
    assert _format_model_price_value(price, 'requests_kcount', use_color=False).plain == '$12'


def test_format_model_price_value_preserves_tier_text() -> None:
    price = ModelPrice(input_mtok=TieredPrices(base=Decimal('1'), tiers=[]))

    assert _format_model_price_value(price, 'input_mtok', use_color=False).plain == '$1 (+tiers)'


def test_format_model_price_value_uses_custom_registry_metadata() -> None:
    registry = UnitRegistry(
        {
            'sausage_tokens': {
                'per': 1_000_000,
                'price_key': 'sausage_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
            }
        }
    )
    with _use_registry(registry):
        price = ModelPrice(sausage_mtok=Decimal('2'))
        formatted = _format_model_price_value(price, 'sausage_mtok', use_color=False)

    assert formatted.plain == '$2'


def test_collect_model_price_fields_uses_effective_registry_order() -> None:
    registry = UnitRegistry(
        {
            'sausage_tokens': {
                'per': 1_000_000,
                'price_key': 'sausage_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
            },
            'input_tokens': {
                'per': 1_000_000,
                'price_key': 'input_mtok',
                'dimensions': {'family': 'tokens', 'direction': 'input'},
            },
        }
    )
    with _use_registry(registry):
        price = ModelPrice(input_mtok=Decimal('1'), sausage_mtok=Decimal('2'))
        fields = _collect_model_price_fields([_price_calculation(price)])

    assert fields == ['sausage_mtok', 'input_mtok']


def test_collect_model_price_fields_appends_unregistered_price_keys() -> None:
    price = ModelPrice(input_mtok=Decimal('1'), hovercraft_mtok=Decimal('2'))

    assert _collect_model_price_fields([_price_calculation(price)]) == ['input_mtok', 'hovercraft_mtok']


def test_unknown_price_field_fallbacks() -> None:
    assert _price_field_label('hovercraft_mtok') == 'Hovercraft'
    assert _unit_for_price_key('hovercraft_mtok') is None


@pytest.mark.parametrize(
    ('unit', 'display_name', 'per_label'),
    [
        (UnitDef('audio_seconds', 'audio_second', 1, {'family': 'time', 'modality': 'audio'}), 'Audio', '1'),
        (UnitDef('characters', 'characters_million', 1_000_000, {'family': 'characters'}), 'Characters', 'M'),
        (UnitDef('images', 'images_kcount', 1_000, {'family': 'images'}), 'Images', 'K'),
    ],
)
def test_unit_label_fallbacks(unit: UnitDef, display_name: str, per_label: str) -> None:
    assert _unit_display_name(unit) == display_name
    assert _unit_per_label(unit) == per_label


def test_calc_table_split_columns_includes_dynamic_price_column(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    custom_units = dict(unit_data)
    custom_units['sausage_tokens'] = {
        'per': 1_000_000,
        'price_key': 'sausage_mtok',
        'dimensions': {'family': 'tokens', 'direction': 'input', 'ingredient': 'sausage'},
    }
    registry = UnitRegistry(custom_units)
    set_custom_snapshot(
        DataSnapshot(
            providers=[
                Provider(
                    id='testing',
                    name='Testing',
                    api_pattern='testing',
                    models=[
                        ModelInfo(
                            id='sausage',
                            match=ClauseEquals('sausage'),
                            prices=ModelPrice(input_mtok=Decimal('1'), sausage_mtok=Decimal('2')),
                        )
                    ],
                )
            ],
            from_auto_update=False,
        )
    )
    monkeypatch.setenv('COLUMNS', '240')
    try:
        with _use_registry(registry):
            assert cli_logic(['calc', '--no-color', '--table', '--input-tokens', '1000', 'testing:sausage']) == 0
            out, err = capsys.readouterr()
    finally:
        set_custom_snapshot(None)

    assert 'Input Sausage/MTok' in out
    assert '$2' in out
    assert err == ''


def test_split_model_price_columns_no_fields():
    console = Console(width=60)
    assert _should_split_model_price_columns(console, []) is False


def test_suggest_models_missing_provider():
    assert _suggest_models('gpt-4o', 'missing', providers) == []


def test_suggest_models_case_insensitive_provider_path():
    model_id = 'AaAaAaAaAaAaAaAaAaAa'
    fake_providers = [
        Provider(
            id='provider',
            name='Provider',
            api_pattern='https://example.com',
            models=[ModelInfo(id=model_id, match=ClauseEquals(model_id))],
        )
    ]
    assert _suggest_models(model_id.lower(), 'provider', fake_providers) == [f'provider:{model_id}']


def test_suggest_models_case_insensitive_global_path():
    model_id = 'AaAaAaAaAaAaAaAaAaAa'
    fake_providers = [
        Provider(
            id='provider',
            name='Provider',
            api_pattern='https://example.com',
            models=[ModelInfo(id=model_id, match=ClauseEquals(model_id))],
        )
    ]
    assert _suggest_models(f'provider:{model_id.lower()}', None, fake_providers) == [f'provider:{model_id}']


def test_calc_update_prices(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, int | bool] = {'instances': 0, 'starts': 0}

    class DummyUpdatePrices:
        def __init__(self) -> None:
            calls['instances'] += 1

        def start(self, *, wait: bool = False) -> None:
            calls['starts'] += 1
            calls['wait'] = wait

    monkeypatch.setattr(update_prices, 'UpdatePrices', DummyUpdatePrices)
    assert cli_logic(['--plain', 'calc', '--update-prices', '--input-tokens', '1000', 'gpt-4o', 'gpt-4o']) == 0
    assert calls == {'instances': 1, 'starts': 1, 'wait': True}
