from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from prices import price_discrepancies, source_prices, update
from prices.price_discrepancies import check_for_price_discrepancies, prices_conflict
from prices.prices_types import ClauseEquals, ConditionalPrice, ModelInfo, ModelPrice, Provider
from prices.source_prices import SourcePricesType


def model(
    model_id: str, prices: ModelPrice | list[ConditionalPrice], *, prices_checked: date | None = None
) -> ModelInfo:
    return ModelInfo(id=model_id, match=ClauseEquals(equals=model_id), prices=prices, prices_checked=prices_checked)


def provider(provider_id: str, models: list[ModelInfo]) -> Provider:
    return Provider(id=provider_id, name=provider_id.title(), api_pattern='https://example.com', models=models)


@dataclass
class FakeProviderYaml:
    provider: Provider
    added_prices: list[tuple[str, ModelPrice]] = field(default_factory=list)
    added_ids: list[tuple[str, str]] = field(default_factory=list)
    saved: int = 0

    def add_price(self, model_id: str, price: ModelPrice) -> None:
        self.added_prices.append((model_id, price))

    def add_id_to_model(self, lookup_id: str, new_model_id: str) -> None:  # pragma: no cover
        self.added_ids.append((lookup_id, new_model_id))

    def save(self) -> None:
        self.saved += 1


def input_action(action: str) -> Callable[[str], str]:
    def choose_action(_prompt: str) -> str:
        return action

    return choose_action


def loaded_source_prices(prices: dict[str, SourcePricesType]) -> Callable[[], dict[str, SourcePricesType]]:
    def load_prices() -> dict[str, SourcePricesType]:
        return prices

    return load_prices


def loaded_providers(
    providers: dict[str, FakeProviderYaml],
) -> Callable[[], dict[str, FakeProviderYaml]]:
    def get_providers() -> dict[str, FakeProviderYaml]:
        return providers

    return get_providers


def test_prices_conflict_false_when_identical() -> None:
    price = ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))
    assert prices_conflict(price, price) is False


def test_prices_conflict_true_when_values_differ() -> None:
    current = ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))
    source = ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('3'))
    assert prices_conflict(current, source) is True


def test_prices_conflict_does_not_raise_on_extra_source_key() -> None:
    """`ModelPrice` is extra='allow'; a key our YAML doesn't carry is absent, not None."""
    current = ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))
    source = ModelPrice.model_validate(
        {'input_mtok': Decimal('1'), 'output_mtok': Decimal('2'), 'output_reasoning_mtok': Decimal('5')}
    )
    assert prices_conflict(current, source) is True


def test_update_price_discrepancies_groups_missing_models_and_saves(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    price = ModelPrice(input_mtok=Decimal('1'))
    provider_yml = FakeProviderYaml(provider('test', []))
    monkeypatch.setattr(
        price_discrepancies,
        'load_source_prices',
        loaded_source_prices(
            {
                'unrelated': {'other': {}},
                'first': {'test': {'new-model': price}},
                'second': {'test': {'new-model': price}},
            }
        ),
    )
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers({'test': provider_yml}))
    monkeypatch.setattr('builtins.input', input_action('n'))

    price_discrepancies.update_price_discrepancies(date(2026, 1, 1))

    assert provider_yml.added_prices == [('new-model', price)]
    assert provider_yml.saved == 1
    assert capsys.readouterr().out == (
        'Checking price discrepancies since 2026-01-01\n'
        "Unrecognized model: new-model\nSources: first, second\nPrice: {'input_mtok': 1}\n\n"
        'price discrepancies:\n                Test: 1\n'
    )


def test_update_price_discrepancies_updates_provider_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    providers_dir = tmp_path / 'providers'
    providers_dir.mkdir()
    provider_path = providers_dir / 'testing.yml'
    provider_path.write_text(
        """\
id: testing
name: Testing
api_pattern: testing
models:
  - id: existing
    match:
      equals: existing
    prices:
      input_mtok: 1
      output_mtok: 2
  - id: free-model
    match:
      equals: free-model
    prices: {}
  - id: tiered
    match:
      equals: tiered
    prices:
      input_mtok:
        base: 4
        tiers:
          - {start: 1000, price: 2}
"""
    )
    source_prices_dir = tmp_path / 'source_prices'
    monkeypatch.setattr(update, 'package_dir', tmp_path)
    monkeypatch.setattr(source_prices, 'source_prices_dir', source_prices_dir)
    source_prices.write_source_prices(
        'testing',
        {
            'testing': {
                'new-model': ModelPrice(input_mtok=Decimal('1')),
                'existing-alias': ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')),
                'skipped-model': ModelPrice(input_mtok=Decimal('3')),
                'free-model': ModelPrice(input_mtok=Decimal('1')),
                'tiered': ModelPrice(input_mtok=Decimal('4')),
            }
        },
    )
    actions = iter(['n', '0', 'skip'])

    def choose_action(_prompt: str) -> str:
        return next(actions)

    monkeypatch.setattr('builtins.input', choose_action)

    price_discrepancies.update_price_discrepancies(date(2026, 1, 1))

    saved = update.ProviderYaml(provider_path)
    assert saved.provider.find_model('existing-alias') is not None
    assert saved.provider.find_model('new-model') is not None


def test_update_price_discrepancies_reports_invalid_source_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_prices_dir = tmp_path / 'source_prices'
    source_prices_dir.mkdir()
    invalid_path = source_prices_dir / 'invalid.json'
    invalid_path.write_text('{"testing": {"model": {"input_mtok": 0}}}')
    monkeypatch.setattr(source_prices, 'source_prices_dir', source_prices_dir)

    with pytest.raises(ValueError, match=f'Error loading source prices from {invalid_path}'):
        price_discrepancies.update_price_discrepancies()


def test_update_price_discrepancies_reports_invalid_provider_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    providers_dir = tmp_path / 'providers'
    providers_dir.mkdir()
    (providers_dir / 'invalid.yml').write_text('id: invalid\n')
    source_prices_dir = tmp_path / 'source_prices'
    source_prices_dir.mkdir()
    monkeypatch.setattr(update, 'package_dir', tmp_path)
    monkeypatch.setattr(source_prices, 'source_prices_dir', source_prices_dir)

    with pytest.raises(ValueError, match='Invalid provider data for invalid.yml'):
        price_discrepancies.update_price_discrepancies()


def test_update_price_discrepancies_skips_checked_conditional_and_conflicting_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    price = ModelPrice(input_mtok=Decimal('1'))
    conditional = [ConditionalPrice(prices=price)]
    provider_yml = FakeProviderYaml(
        provider(
            'groq',
            [
                model('conditional', conditional),
                model('current', price, prices_checked=date(2027, 1, 1)),
                model('old', price, prices_checked=date(2025, 1, 1)),
                model('stale-conflict', ModelPrice(input_mtok=Decimal('2')), prices_checked=date(2025, 1, 1)),
            ],
        )
    )
    monkeypatch.setattr(
        price_discrepancies,
        'load_source_prices',
        loaded_source_prices(
            {
                'source': {
                    'groq': {
                        'groq/conditional': price,
                        'groq/current': price,
                        'groq/old': price,
                        'groq/stale-conflict': price,
                    }
                }
            }
        ),
    )
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers({'groq': provider_yml}))

    price_discrepancies.update_price_discrepancies(date(2026, 1, 1))

    assert provider_yml.saved == 0
    assert capsys.readouterr().out == 'Checking price discrepancies since 2026-01-01\nno price discrepancies found\n'


def test_update_price_discrepancies_uses_a_default_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(price_discrepancies, 'load_source_prices', loaded_source_prices({}))
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers({}))

    price_discrepancies.update_price_discrepancies()

    assert capsys.readouterr().out.startswith('Checking price discrepancies since ')


def test_update_price_discrepancies_ignores_known_models_after_comparing_multiple_prices(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_yml = FakeProviderYaml(provider('openai', []))
    monkeypatch.setattr(
        price_discrepancies,
        'load_source_prices',
        loaded_source_prices(
            {
                'first': {'openai': {'batch-model': ModelPrice(input_mtok=Decimal('1'))}},
                'second': {'openai': {'batch-model': ModelPrice(input_mtok=Decimal('2'))}},
                'third': {'openai': {'batch-model': ModelPrice(input_mtok=Decimal('2'))}},
            }
        ),
    )
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers({'openai': provider_yml}))

    price_discrepancies.update_price_discrepancies(date(2026, 1, 1))

    assert provider_yml.saved == 0
    assert capsys.readouterr().out == 'Checking price discrepancies since 2026-01-01\nno price discrepancies found\n'


def test_update_price_discrepancies_ignores_known_google_models(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_yml = FakeProviderYaml(provider('google', []))
    monkeypatch.setattr(
        price_discrepancies,
        'load_source_prices',
        loaded_source_prices(
            {'source': {'google': {'gemini-flash-experimental': ModelPrice(input_mtok=Decimal('1'))}}}
        ),
    )
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers({'google': provider_yml}))

    price_discrepancies.update_price_discrepancies(date(2026, 1, 1))

    assert capsys.readouterr().out == 'Checking price discrepancies since 2026-01-01\nno price discrepancies found\n'


def test_update_price_discrepancies_reports_every_provider_with_an_added_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    price = ModelPrice(input_mtok=Decimal('1'))
    first = FakeProviderYaml(provider('first', []))
    second = FakeProviderYaml(provider('second', []))
    monkeypatch.setattr(
        price_discrepancies,
        'load_source_prices',
        loaded_source_prices({'source': {'first': {'first-new': price}, 'second': {'second-new': price}}}),
    )
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers({'first': first, 'second': second}))
    monkeypatch.setattr('builtins.input', input_action('n'))

    price_discrepancies.update_price_discrepancies(date(2026, 1, 1))

    assert first.saved == second.saved == 1
    output = capsys.readouterr().out
    assert 'price discrepancies:\n               First: 1\n' in output
    assert output.endswith('              Second: 1\n')


def test_check_for_price_discrepancies_reports_each_affected_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    affected = model('affected', ModelPrice(input_mtok=Decimal('1')))
    affected.price_discrepancies = {'source': {}}
    another_affected = model('another-affected', ModelPrice(input_mtok=Decimal('1')))
    another_affected.price_discrepancies = {'source': {}}
    second_affected = model('also-affected', ModelPrice(input_mtok=Decimal('1')))
    second_affected.price_discrepancies = {'source': {}}
    provider_ymls = {
        'first': FakeProviderYaml(
            provider('first', [affected, another_affected, model('clear', ModelPrice(input_mtok=Decimal('1')))])
        ),
        'second': FakeProviderYaml(provider('second', [second_affected])),
        'third': FakeProviderYaml(provider('third', [model('clear', ModelPrice(input_mtok=Decimal('1')))])),
    }
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers(provider_ymls))

    assert check_for_price_discrepancies() == 3
    assert capsys.readouterr().out == 'price discrepancies:\n               First: 2\n              Second: 1\n'


def test_check_for_price_discrepancies_reports_when_there_are_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers({}))

    assert check_for_price_discrepancies() == 0
    assert capsys.readouterr().out == 'no price discrepancies found\n'
