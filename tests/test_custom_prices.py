from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price, data, types
from genai_prices.calc import DataSnapshot, set_custom_snapshot
from genai_prices.update_prices import UpdatePrices


@dataclass
class CustomModelPrice(types.ModelPrice):
    sausage_price: Decimal | None = None

    def calc_price(self, usage: types.AbstractUsage) -> types.CalcPrice:
        price = super().calc_price(usage)
        if isinstance(usage, CustomUsage) and self.sausage_price is not None:
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
    with AltUpdatePrices() as update_pries:
        update_pries.wait()
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
    with ExtraUpdatePrices() as update_pries:
        update_pries.wait()
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
    with ExtraUpdatePrices() as update_pries:
        update_pries.wait()
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
