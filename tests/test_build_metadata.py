from decimal import Decimal

import pytest

from genai_prices import types as runtime_types
from prices.build import inherit_canonical_metadata, prepare_providers_for_export
from prices.prices_types import (
    ClauseEquals,
    ModelCapabilities,
    ModelInfo,
    ModelPrice,
    Provider,
    ReasoningCapabilities,
    SamplingCapabilities,
    providers_schema,
)


def make_model(
    model_id: str,
    *,
    context_window: int | None = None,
    capabilities: ModelCapabilities | None = None,
    canonical_model: str | None = None,
    removed: bool = False,
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        match=ClauseEquals(equals=model_id),
        canonical_model=canonical_model,
        context_window=context_window,
        capabilities=capabilities,
        removed=removed,
        prices=ModelPrice(input_mtok=Decimal('1')),
    )


REASONER = ModelCapabilities(
    reasoning=ReasoningCapabilities(supported=True, always_on=True, effort_levels=['low', 'medium', 'high']),
    sampling=SamplingCapabilities(temperature=False, top_p=False),
    service_tiers=['auto', 'default'],
)


def test_inherit_capabilities_from_canonical_model():
    canonical = make_model('canonical', capabilities=REASONER)
    offering = make_model('offering', canonical_model='native/canonical')
    explicit = make_model(
        'explicit', capabilities=ModelCapabilities(max_output_tokens=4096), canonical_model='native/canonical'
    )
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[explicit, offering]),
    ]

    inherit_canonical_metadata(providers)

    assert offering.capabilities == REASONER
    assert explicit.capabilities == ModelCapabilities(max_output_tokens=4096)


def test_capabilities_round_trip_to_runtime_types():
    model = make_model('reasoner', capabilities=REASONER)
    providers = [Provider(id='native', name='Native', api_pattern='native', models=[model])]
    serialized = providers_schema.dump_python(providers, mode='json', exclude_none=True)
    assert serialized[0]['models'][0]['capabilities'] == {
        'reasoning': {'supported': True, 'always_on': True, 'effort_levels': ['low', 'medium', 'high']},
        'sampling': {'temperature': False, 'top_p': False},
        'service_tiers': ['auto', 'default'],
    }

    runtime = runtime_types._providers_from_raw(serialized)[0].models[0]
    assert runtime.capabilities == runtime_types.ModelCapabilities(
        reasoning=runtime_types.ReasoningCapabilities(
            supported=True, always_on=True, effort_levels=['low', 'medium', 'high']
        ),
        sampling=runtime_types.SamplingCapabilities(temperature=False, top_p=False),
        service_tiers=['auto', 'default'],
    )


def test_omitted_capability_fields_stay_unknown():
    reasoning = ReasoningCapabilities.model_validate({'effort_levels': ['low']})
    assert reasoning.supported is None and reasoning.always_on is None
    assert SamplingCapabilities.model_validate({}).temperature is None


def test_capabilities_reject_unknown_fields():
    with pytest.raises(ValueError, match='extra_forbidden'):
        ReasoningCapabilities.model_validate({'supports_reasoning': True})


def test_inherit_context_window_from_canonical_model():
    canonical = make_model('canonical', context_window=200_000)
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_canonical_metadata(providers)

    assert offering.context_window == 200_000


def test_serialized_offering_is_flattened():
    canonical = make_model('canonical', context_window=200_000)
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_canonical_metadata(providers)
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

    inherit_canonical_metadata(providers)

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

    inherit_canonical_metadata(providers)

    assert offering.context_window == 200_000


def test_canonical_reference_requires_provider_qualification():
    with pytest.raises(ValueError, match='canonical_model'):
        make_model('offering', canonical_model='canonical')


def test_unknown_canonical_model_is_rejected():
    offering = make_model('offering', canonical_model='native/missing')
    providers = [Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering])]

    with pytest.raises(ValueError, match='unknown canonical model `native/missing`'):
        inherit_canonical_metadata(providers)


def test_canonical_model_without_context_window_is_allowed():
    canonical = make_model('canonical')
    offering = make_model('offering', canonical_model='native/canonical')
    providers = [
        Provider(id='native', name='Native', api_pattern='native', models=[canonical]),
        Provider(id='proxy', name='Proxy', api_pattern='proxy', models=[offering]),
    ]

    inherit_canonical_metadata(providers)

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
        inherit_canonical_metadata(providers)


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
