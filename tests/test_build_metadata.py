from decimal import Decimal

import pytest

from prices.build import inherit_context_windows
from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Provider


def make_model(model_id: str, *, context_window: int | None = None, canonical_model: str | None = None) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        match=ClauseEquals(equals=model_id),
        canonical_model=canonical_model,
        context_window=context_window,
        prices=ModelPrice(input_mtok=Decimal('1')),
    )


def test_inherit_context_window_from_canonical_model():
    canonical = make_model('canonical', context_window=200_000)
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_context_windows(providers)

    assert offering.context_window == 200_000


def test_provider_context_window_overrides_canonical_model():
    canonical = make_model('canonical', context_window=200_000)
    offering = make_model('offering', context_window=100_000, canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_context_windows(providers)

    assert offering.context_window == 100_000


def test_unknown_canonical_model_is_rejected():
    offering = make_model('offering', canonical_model='native/missing')
    providers = [Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering])]

    with pytest.raises(ValueError, match='unknown canonical model `native/missing`'):
        inherit_context_windows(providers)


def test_canonical_model_without_context_window_is_rejected():
    canonical = make_model('canonical')
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    with pytest.raises(ValueError, match='Canonical model `native/canonical` has no context window'):
        inherit_context_windows(providers)


def test_chained_canonical_models_are_rejected():
    original = make_model('original', context_window=200_000)
    canonical = make_model('canonical', context_window=200_000, canonical_model='source/original')
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='source', name='Source', api_pattern='source', models=[original]),
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    with pytest.raises(
        ValueError, match='Canonical model `native/canonical` must not reference another canonical model'
    ):
        inherit_context_windows(providers)
