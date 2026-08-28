from decimal import Decimal

import pytest

from prices.build import inherit_context_windows, prepare_providers_for_export
from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Provider, providers_schema


def make_model(
    model_id: str,
    *,
    context_window: int | None = None,
    canonical_model: str | None = None,
    removed: bool = False,
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        match=ClauseEquals(equals=model_id),
        canonical_model=canonical_model,
        context_window=context_window,
        removed=removed,
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


def test_serialized_offering_is_flattened():
    canonical = make_model('canonical', context_window=200_000)
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_context_windows(providers)
    serialized = providers_schema.dump_python(providers, mode='json', exclude_none=True)[1]['models'][0]

    assert serialized['context_window'] == 200_000
    assert 'canonical_model' not in serialized


def test_provider_context_window_overrides_canonical_model():
    canonical = make_model('canonical', context_window=200_000)
    offering = make_model('offering', context_window=100_000, canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_context_windows(providers)

    assert offering.context_window == 100_000


def test_canonical_reference_accepts_maximum_length_ids():
    provider_id = 'p' * 100
    model_id = 'm' * 100
    canonical = make_model(model_id, context_window=200_000)
    offering = make_model('offering', canonical_model=f'{provider_id}/{model_id}')
    providers = [
        Provider(id=provider_id, name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_context_windows(providers)

    assert offering.context_window == 200_000


def test_canonical_reference_requires_provider_qualification():
    with pytest.raises(ValueError, match='canonical_model'):
        make_model('offering', canonical_model='canonical')


def test_unknown_canonical_model_is_rejected():
    offering = make_model('offering', canonical_model='native/missing')
    providers = [Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering])]

    with pytest.raises(ValueError, match='unknown canonical model `native/missing`'):
        inherit_context_windows(providers)


def test_canonical_model_without_context_window_is_allowed():
    canonical = make_model('canonical')
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_context_windows(providers)

    assert offering.context_window is None


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


def test_removed_canonical_model_can_supply_active_offering():
    canonical = make_model('canonical', context_window=200_000, removed=True)
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='host', name='Host', api_pattern='host', models=[offering]),
    ]

    prepare_providers_for_export(providers)

    assert providers[0].models == []
    assert offering.context_window == 200_000


def test_authoring_schema_accepts_explicit_null_context_window():
    """`context_window: null` is a deliberate no-single-window decision (see openrouter.yml), so the
    authoring schema must not make editors flag it even though nullable unions are simplified away."""
    from prices.build import _provider_yaml_schema, load_units

    schema = _provider_yaml_schema(load_units())

    assert schema['$defs']['ModelInfo']['properties']['context_window']['type'] == ['integer', 'null']
