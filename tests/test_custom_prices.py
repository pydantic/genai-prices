from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price, data, types
from genai_prices.data_snapshot import DataSnapshot, set_custom_snapshot
from genai_prices.update_prices import UpdatePrices


@dataclass
class CustomModelPrice(types.ModelPrice):
    sausage_price: Decimal | None = None

    def calc_price(self, usage: types.AbstractUsage) -> types.CalcPrice:
        price = super().calc_price(usage)
        assert isinstance(usage, CustomUsage)
        assert self.sausage_price is not None
        price['total_price'] += self.sausage_price * usage.sausages
        return price


class AltUpdatePrices(UpdatePrices):
    def fetch(self) -> DataSnapshot | None:
        custom_providers = [
            types.Provider(
                id='testing',
                name='Testing',
                api_pattern=r'.*testing\.example\.com',
                models=[
                    types.ModelInfo(
                        id='foobar',
                        match=types.ClauseEquals('foobar'),
                        name='Foobar',
                        prices=types.ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2')),
                    ),
                    types.ModelInfo(
                        id='sausage',
                        match=types.ClauseStartsWith('sausage'),
                        name='Sausage',
                        prices=CustomModelPrice(
                            input_mtok=Decimal('1'),
                            output_mtok=Decimal('2'),
                            sausage_price=Decimal('3'),
                        ),
                    ),
                ],
            )
        ]
        return DataSnapshot(providers=custom_providers, from_auto_update=False)


class ExtraUpdatePrices(UpdatePrices):
    def fetch(self) -> DataSnapshot | None:
        providers = deepcopy(data.providers)
        openai = next(provider for provider in providers if provider.id == 'openai')
        openai.models.insert(
            0,
            types.ModelInfo(
                id='gpt-4o',
                match=types.ClauseStartsWith('gpt-4o'),
                name='gpt-4o Custom',
                prices=CustomModelPrice(
                    input_mtok=Decimal('1'),
                    output_mtok=Decimal('2'),
                    sausage_price=Decimal('3'),
                ),
            ),
        )
        return DataSnapshot(providers=providers, from_auto_update=False)


@dataclass
class CustomUsage:
    sausages: int

    requests: int | None = None

    input_tokens: int | None = None

    cache_write_tokens: int | None = None
    cache_read_tokens: int | None = None

    output_tokens: int | None = None

    input_audio_tokens: int | None = None
    cache_audio_read_tokens: int | None = None
    output_audio_tokens: int | None = None


def test_alt_source():
    with AltUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=1_000_000, output_tokens=1_000_000),
            model_ref='foobar',
            provider_id='testing',
        )
        assert price.input_price == snapshot(Decimal('1'))
        assert price.output_price == snapshot(Decimal('2'))
        assert price.total_price == snapshot(Decimal('3'))
        assert price.model.name == snapshot('Foobar')
        assert price.provider.id == snapshot('testing')
        assert price.auto_update_timestamp is None

    with pytest.raises(LookupError, match="Unable to find provider provider_id='testing'"):
        calc_price(
            Usage(input_tokens=1_000_000, output_tokens=1_000_000),
            model_ref='foobar',
            provider_id='testing',
        )


def test_alt_source_sausage():
    set_custom_snapshot(AltUpdatePrices().fetch())
    try:
        price = calc_price(
            CustomUsage(sausages=3, input_tokens=1_000_000, output_tokens=1_000_000),
            model_ref='sausage',
            provider_id='testing',
        )
        assert price.input_price == snapshot(Decimal('1'))
        assert price.output_price == snapshot(Decimal('2'))
        assert price.total_price == snapshot(Decimal('12'))
        assert price.model.name == snapshot('Sausage')
        assert price.provider.id == snapshot('testing')
        assert price.auto_update_timestamp is None
    finally:
        set_custom_snapshot(None)


def test_extra_source_normal():
    with ExtraUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            CustomUsage(sausages=3, input_tokens=1_000_000, output_tokens=1_000_000),
            model_ref='gpt-4',
            provider_id='openai',
        )
        assert price.input_price == snapshot(Decimal('30'))
        assert price.output_price == snapshot(Decimal('60'))
        assert price.total_price == snapshot(Decimal('90'))
        assert price.model.name == snapshot('gpt 4')
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is None


def test_extra_source_sausage():
    with ExtraUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            CustomUsage(sausages=3, input_tokens=1_000_000, output_tokens=1_000_000),
            model_ref='gpt-4o',
            provider_id='openai',
        )
        assert price.input_price == snapshot(Decimal('1'))
        assert price.output_price == snapshot(Decimal('2'))
        assert price.total_price == snapshot(Decimal('12'))
        assert price.model.name == snapshot('gpt-4o Custom')
        assert price.provider.id == snapshot('openai')
        assert price.auto_update_timestamp is None


def test_custom_price_override_gets_original_usage_and_super_prices_registered_fields() -> None:
    @dataclass
    class BonusUsage:
        input_tokens: int
        bonus_units: int

    @dataclass
    class BonusModelPrice(types.ModelPrice):
        bonus_price: Decimal | None = None

        def calc_price(self, usage: types.AbstractUsage) -> types.CalcPrice:
            price = super().calc_price(usage)
            if isinstance(usage, BonusUsage) and self.bonus_price is not None:
                price['total_price'] += self.bonus_price * usage.bonus_units
            return price

    provider = types.Provider(id='testing', name='Testing', api_pattern='testing', models=[])
    model = types.ModelInfo(
        id='bonus',
        match=types.ClauseEquals('bonus'),
        prices=BonusModelPrice(input_mtok=Decimal('1'), bonus_price=Decimal('2')),
    )

    price = model.calc_price(BonusUsage(input_tokens=1_000_000, bonus_units=3), provider)

    assert price.input_price == Decimal('1')
    assert price.output_price == Decimal('0')
    assert price.total_price == Decimal('7')

    # A non-BonusUsage skips the bonus branch, returning only the super() prices.
    plain_price = model.calc_price(types.Usage(input_tokens=1_000_000), provider)
    assert plain_price.total_price == Decimal('1')


def test_base_model_price_stores_dynamic_price_kwargs() -> None:
    price = types.ModelPrice(
        input_mtok=Decimal('1'),
        cache_image_read_mtok=Decimal('0.5'),
    )

    assert price.input_mtok == Decimal('1')
    assert price._extra_prices == {'cache_image_read_mtok': Decimal('0.5')}
    assert price.cache_image_read_mtok == Decimal('0.5')


def test_provider_parsing_preserves_dynamic_model_price_keys() -> None:
    providers = types.providers_schema.validate_json(
        json.dumps(
            [
                {
                    'id': 'testing',
                    'name': 'Testing',
                    'api_pattern': 'testing',
                    'models': [
                        {
                            'id': 'model',
                            'match': {'equals': 'model'},
                            'prices': {
                                'input_mtok': 1,
                                'cache_image_read_mtok': 0.5,
                            },
                        }
                    ],
                }
            ]
        )
    )

    price = providers[0].models[0].prices
    assert isinstance(price, types.ModelPrice)
    assert price._extra_prices == {'cache_image_read_mtok': Decimal('0.5')}
    assert price.cache_image_read_mtok == Decimal('0.5')


def test_dynamic_model_price_assignment_and_deletion() -> None:
    price = types.ModelPrice()

    price.cache_image_read_mtok = Decimal('0.5')
    assert price._extra_prices == {'cache_image_read_mtok': Decimal('0.5')}
    assert price.cache_image_read_mtok == Decimal('0.5')

    del price.cache_image_read_mtok
    assert price._extra_prices == {}
    assert price.cache_image_read_mtok is None


def test_custom_model_price_constructor_still_accepts_declared_custom_fields() -> None:
    price = CustomModelPrice(
        input_mtok=Decimal('1'),
        output_mtok=Decimal('2'),
        sausage_price=Decimal('3'),
    )

    assert price.input_mtok == Decimal('1')
    assert price.output_mtok == Decimal('2')
    assert price.sausage_price == Decimal('3')


def test_custom_model_price_constructor_defers_undeclared_dynamic_keys_to_phase_4() -> None:
    with pytest.raises(TypeError, match='cache_image_read_mtok'):
        CustomModelPrice(
            input_mtok=Decimal('1'),
            cache_image_read_mtok=Decimal('0.5'),  # pyright: ignore[reportCallIssue]
            sausage_price=Decimal('3'),
        )


def test_model_price_constructor_restores_stored_extra_prices() -> None:
    price = types.ModelPrice(
        input_mtok=Decimal('1'),
        _extra_prices={'cache_image_read_mtok': Decimal('0.5')},  # pyright: ignore[reportArgumentType]
    )

    assert price._extra_prices == {'cache_image_read_mtok': Decimal('0.5')}
    assert price.cache_image_read_mtok == Decimal('0.5')


def test_model_price_constructor_rejects_non_mapping_stored_extra_prices() -> None:
    with pytest.raises(TypeError, match='_extra_prices must be a mapping'):
        types.ModelPrice(_extra_prices=[('cache_image_read_mtok', Decimal('0.5'))])  # pyright: ignore[reportArgumentType]


def test_store_unknown_price_keys_passes_through_non_dict_input() -> None:
    sentinel = object()

    assert types.ModelPrice._store_unknown_price_keys(sentinel) is sentinel  # pyright: ignore[reportCallIssue]


def test_model_price_delattr_declared_field_and_unset_registered_key() -> None:
    price = types.ModelPrice(input_mtok=Decimal('1'))

    del price.input_mtok
    assert price.input_mtok is None

    with pytest.raises(AttributeError, match='cache_image_read_mtok'):
        del price.cache_image_read_mtok


def test_model_price_is_free_handles_non_decimal_extra_price() -> None:
    price = types.ModelPrice()
    price.cache_image_read_mtok = 0

    assert price.is_free() is True
