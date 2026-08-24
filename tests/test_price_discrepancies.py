from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest

from prices import price_discrepancies
from prices.price_discrepancies import (
    can_ignore_missing_model,
    check_for_price_discrepancies,
    handle_missing_model,
    prices_conflict,
)
from prices.prices_types import ClauseEquals, ConditionalPrice, ModelInfo, ModelPrice, Provider, Tier, TieredPrices
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

    def add_id_to_model(self, lookup_id: str, new_model_id: str) -> None:
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


def test_prices_conflict_accepts_a_subset_of_current_dynamic_prices() -> None:
    current = ModelPrice.model_validate({'input_mtok': Decimal('1'), 'output_reasoning_mtok': Decimal('5')})
    source = ModelPrice(input_mtok=Decimal('1'))
    assert prices_conflict(current, source) is False


def test_prices_conflict_rejects_free_and_priced_models() -> None:
    assert prices_conflict(ModelPrice(), ModelPrice(input_mtok=Decimal('1'))) is True


def test_prices_conflict_accepts_the_base_rate_of_a_tiered_price() -> None:
    tiered = TieredPrices(base=Decimal('1'), tiers=[Tier(start=1_000_000, price=Decimal('2'))])
    assert prices_conflict(ModelPrice(input_mtok=tiered), ModelPrice(input_mtok=Decimal('1'))) is False


def test_prices_conflict_rejects_a_different_tiered_price() -> None:
    tiered = TieredPrices(base=Decimal('2'), tiers=[Tier(start=1_000_000, price=Decimal('3'))])
    assert prices_conflict(ModelPrice(input_mtok=tiered), ModelPrice(input_mtok=Decimal('1'))) is True


@pytest.mark.parametrize(
    ('provider_id', 'model_id'),
    [
        ('openai', 'batch-model'),
        ('openai', 'gpt-oss-120b'),
        ('openai', 'openai/gpt-4o'),
        ('google', 'gecko-embedding'),
        ('google', 'bison-chat'),
        ('google', 'multimodalembedding-model'),
        ('google', 'gemini-flash-experimental'),
        ('google', 'gemini-pro-experimental'),
        ('google', 'gemini-pro-vision'),
        ('google', 'gemma-2-27b'),
        ('google', 'gemini/model'),
        ('google', 'vertex_ai/model'),
        ('google', 'gemini-1.0-pro'),
        ('google', 'gemini-2.0-pro-exp'),
        ('google', 'text-embedding-004'),
        ('google', 'text-multilingual-embedding-002'),
        ('google', 'text-unicorn-embedding'),
    ],
)
def test_can_ignore_known_missing_models(provider_id: str, model_id: str) -> None:
    assert can_ignore_missing_model(provider_id, model_id) is True


@pytest.mark.parametrize(
    ('provider_id', 'model_id'), [('openai', 'gpt-4o'), ('google', 'gemini-2.5-pro'), ('other', 'batch-model')]
)
def test_can_not_ignore_unknown_missing_models(provider_id: str, model_id: str) -> None:
    assert can_ignore_missing_model(provider_id, model_id) is False


@pytest.mark.parametrize(
    ('action', 'expected_prices', 'expected_ids', 'expected_result'),
    [
        ('n', [('new-model', ModelPrice(input_mtok=Decimal('1')))], [], True),
        ('0', [], [('matching-model', 'new-model')], True),
        ('skip', [], [], False),
    ],
)
def test_handle_missing_model_records_the_selected_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    action: str,
    expected_prices: list[tuple[str, ModelPrice]],
    expected_ids: list[tuple[str, str]],
    expected_result: bool,
) -> None:
    price = ModelPrice(input_mtok=Decimal('1'))
    # This candidate is compatible but not equal, so the interactive report includes its differences.
    candidate = model('matching-model', ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')))
    provider_yml = FakeProviderYaml(provider('test', [candidate]))
    monkeypatch.setattr('builtins.input', input_action(action))

    assert handle_missing_model(price, 'new-model', provider_yml) is expected_result
    assert provider_yml.added_prices == expected_prices
    assert provider_yml.added_ids == expected_ids
    assert 'Possible match: 0 matching-model' in capsys.readouterr().out


def test_handle_missing_model_reports_an_exact_match(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    price = ModelPrice(input_mtok=Decimal('1'))
    provider_yml = FakeProviderYaml(provider('test', [model('matching-model', price)]))
    monkeypatch.setattr('builtins.input', input_action('skip'))

    assert handle_missing_model(price, 'new-model', provider_yml) is False
    assert 'Exact price match' in capsys.readouterr().out


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
    second_affected = model('also-affected', ModelPrice(input_mtok=Decimal('1')))
    second_affected.price_discrepancies = {'source': {}}
    provider_ymls = {
        'first': FakeProviderYaml(provider('first', [affected, model('clear', ModelPrice(input_mtok=Decimal('1')))])),
        'second': FakeProviderYaml(provider('second', [second_affected])),
        'third': FakeProviderYaml(provider('third', [model('clear', ModelPrice(input_mtok=Decimal('1')))])),
    }
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers(provider_ymls))

    assert check_for_price_discrepancies() == 2
    assert capsys.readouterr().out == 'price discrepancies:\n               First: 1\n              Second: 1\n'


def test_check_for_price_discrepancies_reports_when_there_are_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(price_discrepancies, 'get_providers_yaml', loaded_providers({}))

    assert check_for_price_discrepancies() == 0
    assert capsys.readouterr().out == 'no price discrepancies found\n'
