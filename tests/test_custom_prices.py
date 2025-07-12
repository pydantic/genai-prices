from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal

from inline_snapshot import snapshot

from genai_prices import Usage, calc_price_sync, data, types
from genai_prices.sources import DataSnapshot, SyncSource


@dataclass
class CustomModelPrice(types.ModelPrice):
    sausage_price: Decimal | None = None

    def calc_price(self, usage: types.AbstractUsage) -> Decimal:
        price = super().calc_price(usage)
        if isinstance(usage, CustomUsage) and self.sausage_price is not None:
            price += self.sausage_price * usage.sausages
        return price


class AltPricesSource(SyncSource):
    def fetch(self) -> DataSnapshot | None:
        custom_providers = [
            types.Provider(
                id='testing',
                name='Testing',
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


class ExtraPricesSource(SyncSource):
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
    price = calc_price_sync(
        Usage(input_tokens=1_000_000, output_tokens=1_000_000),
        model_ref='foobar',
        provider_id='testing',
        auto_update=AltPricesSource(),
    )
    assert price.price == snapshot(Decimal('3'))
    assert price.model.name == snapshot('Foobar')
    assert price.provider.id == snapshot('testing')
    assert price.auto_update_timestamp is None


def test_alt_source_sausage():
    price = calc_price_sync(
        CustomUsage(sausages=3, input_tokens=1_000_000, output_tokens=1_000_000),
        model_ref='sausage',
        provider_id='testing',
        auto_update=AltPricesSource(),
    )
    assert price.price == snapshot(Decimal('12'))
    assert price.model.name == snapshot('Sausage')
    assert price.provider.id == snapshot('testing')
    assert price.auto_update_timestamp is None


def test_extra_source_normal():
    price = calc_price_sync(
        CustomUsage(sausages=3, input_tokens=1_000_000, output_tokens=1_000_000),
        model_ref='gpt-4',
        provider_id='openai',
        auto_update=ExtraPricesSource(),
    )
    assert price.price == snapshot(Decimal('90'))
    assert price.model.name == snapshot('gpt 4')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


def test_extra_source_sausage():
    price = calc_price_sync(
        CustomUsage(sausages=3, input_tokens=1_000_000, output_tokens=1_000_000),
        model_ref='gpt-4o',
        provider_id='openai',
        auto_update=ExtraPricesSource(),
    )
    assert price.price == snapshot(Decimal('12'))
    assert price.model.name == snapshot('gpt-4o Custom')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None
