from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from prices import __main__ as commands, collapse, detect_deprecated, inject_providers
from prices.prices_types import ModelPrice
from prices.source_prices import SourcePricesType
from prices.update import ProviderYaml as ProviderYamlFile


@dataclass
class Model:
    id: str
    prices: object
    collapse: bool = True
    deprecated: bool = False
    removed: bool = False
    prices_checked: date | None = None
    matches_source: bool = False

    def is_match(self, model_id: str) -> bool:
        return self.matches_source and model_id == self.id


@dataclass
class Provider:
    id: str
    name: str
    models: list[Model]


@dataclass
class ProviderYaml:
    provider: Provider
    path: Path = Path('provider.yml')


def test_collapse_provider_and_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    shared_prices = object()
    provider = Provider(
        id='example',
        name='Example',
        models=[
            Model('parent', shared_prices, collapse=False),
            Model('not-collapsible', shared_prices, collapse=False),
            Model('unrelated', shared_prices),
            Model('parent:different', object()),
            Model('parent:matching', shared_prices),
        ],
    )
    provider_yaml = Mock(spec=ProviderYamlFile)
    provider_yaml.provider = provider

    assert collapse.collapse_provider(provider_yaml) == 1
    provider_yaml.update_model.assert_called_once_with('parent', provider.models[4])
    provider_yaml.remove_model.assert_called_once_with('parent:matching')

    monkeypatch.setattr(collapse, 'get_providers_yaml', lambda: {'example': provider_yaml})
    collapse.collapse()
    provider_yaml.save.assert_called_once()
    assert capsys.readouterr().out == 'Provider example:\n  1 models combined\n\nTotal models combined: 1\n'

    empty_provider = ProviderYaml(Provider(id='empty', name='Empty', models=[]))
    monkeypatch.setattr(collapse, 'get_providers_yaml', lambda: {'empty': empty_provider})
    collapse.collapse()
    assert capsys.readouterr().out == 'No models combined\n'


def test_detect_deprecated_reports_candidates_and_uncovered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Today:
        @classmethod
        def today(cls) -> date:
            return date(2026, 8, 24)

    checked = date(2026, 1, 1)
    covered = ProviderYaml(
        Provider(
            id='covered',
            name='Covered',
            models=[
                Model('deprecated', object(), deprecated=True, prices_checked=checked),
                Model('removed', object(), removed=True, prices_checked=checked),
                Model('unchecked', object()),
                Model('recent', object(), prices_checked=date(2026, 8, 1)),
                Model('present', object(), prices_checked=checked, matches_source=True),
                Model('missing', object(), prices_checked=checked),
            ],
        )
    )
    no_source = ProviderYaml(Provider(id='no-source', name='No source', models=[]))
    source_prices: dict[str, SourcePricesType] = {'source': {'covered': {'present': ModelPrice(input_mtok=Decimal(1))}}}

    def load_source_prices() -> dict[str, SourcePricesType]:
        return source_prices

    monkeypatch.setattr(detect_deprecated, 'date', Today)
    monkeypatch.setattr(detect_deprecated, 'load_source_prices', load_source_prices)
    monkeypatch.setattr(detect_deprecated, 'get_providers_yaml', lambda: {'covered': covered, 'no-source': no_source})

    detect_deprecated.detect_deprecated()

    assert capsys.readouterr().out == (
        'Found 1 candidate(s) for deprecation/removal:\n\n'
        '  covered: missing (last checked: 2026-01-01)\n'
        '\nNote: 1 provider(s) have no external source coverage and were skipped:\n'
        '  no-source\n'
    )


def test_detect_deprecated_reports_no_candidates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_prices: dict[str, SourcePricesType] = {}
    providers: dict[str, ProviderYaml] = {}

    def load_source_prices() -> dict[str, SourcePricesType]:
        return source_prices

    def get_providers_yaml() -> dict[str, ProviderYaml]:
        return providers

    monkeypatch.setattr(detect_deprecated, 'load_source_prices', load_source_prices)
    monkeypatch.setattr(detect_deprecated, 'get_providers_yaml', get_providers_yaml)

    detect_deprecated.detect_deprecated()

    assert capsys.readouterr().out == 'No deprecation/removal candidates found.\n'


def test_inject_providers_updates_readme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    readme = tmp_path / 'README.md'
    readme.write_text('before\n[comment]: <> (providers-start)\nold\n[comment]: <> (providers-end)\nafter\n')
    monkeypatch.setattr(inject_providers, 'root_dir', tmp_path)
    monkeypatch.setattr(
        inject_providers,
        'get_providers_yaml',
        lambda: {
            'zeta': ProviderYaml(Provider('zeta', 'Zeta', [Model('one', object())]), Path('zeta.yml')),
            'alpha': ProviderYaml(
                Provider('alpha', 'Alpha', [Model('one', object()), Model('two', object())]), Path('alpha.yml')
            ),
        },
    )

    inject_providers.inject_providers()

    assert readme.read_text() == (
        'before\n[comment]: <> (providers-start)\n\n'
        '- [Alpha](prices/providers/alpha.yml) - 2 models\n'
        '- [Zeta](prices/providers/zeta.yml) - 1 models\n\n'
        '[comment]: <> (providers-end)\nafter\n'
    )
    assert capsys.readouterr().out == 'README.md updated with providers list\n'


def test_inject_providers_is_idempotent_and_requires_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    readme = tmp_path / 'README.md'
    readme.write_text('[comment]: <> (providers-start)\n\n\n\n[comment]: <> (providers-end)')
    monkeypatch.setattr(inject_providers, 'root_dir', tmp_path)
    providers: dict[str, ProviderYaml] = {}

    def get_providers_yaml() -> dict[str, ProviderYaml]:
        return providers

    monkeypatch.setattr(inject_providers, 'get_providers_yaml', get_providers_yaml)

    inject_providers.inject_providers()
    assert capsys.readouterr().out == 'README.md already up to date\n'

    readme.write_text('no provider section')
    with pytest.raises(AssertionError, match='contains 0 providers sections'):
        inject_providers.inject_providers()


def test_command_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def build() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(commands, 'build', build)
    monkeypatch.setattr(sys, 'argv', ['prices', 'build'])

    assert commands.main() is None
    assert called is True


def test_command_dispatch_exits_with_integer_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def build() -> int:
        return 3

    monkeypatch.setattr(commands, 'build', build)
    monkeypatch.setattr(sys, 'argv', ['prices', 'build'])

    with pytest.raises(SystemExit, match='3'):
        commands.main()


@pytest.mark.parametrize('argv', (['prices'], ['prices', 'unknown']))
def test_command_dispatch_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    monkeypatch.setattr(sys, 'argv', argv)

    with pytest.raises(SystemExit, match='1'):
        commands.main()

    output = capsys.readouterr().out
    if len(argv) == 2:
        assert output.startswith('Invalid command\nUsage:')
    else:
        assert output.startswith('Usage:')
    assert '  build:' in output
