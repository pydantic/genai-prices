from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
from jsonschema.validators import validator_for
from pydantic import TypeAdapter
from typing_extensions import NotRequired, TypedDict

from genai_prices import data as genai_data, data_units as genai_data_units
from genai_prices.data import providers
from prices.prices_types import providers_schema
from prices.utils import package_dir

_V2_DIR = package_dir / 'new_data' / 'v2'


class _RawConditionalPrice(TypedDict):
    prices: dict[str, object]


class _RawModel(TypedDict):
    """A published model entry, narrowed to the keys these lifecycle tests inspect.

    Pydantic drops the undeclared keys, so `deprecated`/`removed` presence stays observable while everything
    else is discarded — which is how these tests read raw JSON without `Any` or `cast`.
    """

    id: str
    prices: dict[str, object] | list[_RawConditionalPrice]
    deprecated: NotRequired[bool]
    removed: NotRequired[bool]


class _RawProvider(TypedDict):
    id: str
    models: list[_RawModel]


_raw_providers_schema = TypeAdapter(list[_RawProvider])


def _load_raw_providers(data_path: Path) -> list[_RawProvider]:
    return _raw_providers_schema.validate_json(data_path.read_bytes())


def _price_keys(payload: list[_RawProvider]) -> set[str]:
    keys: set[str] = set()
    for provider in payload:
        for model in provider['models']:
            prices = model['prices']
            if isinstance(prices, dict):
                keys |= prices.keys()
            else:
                for conditional_price in prices:
                    keys |= conditional_price['prices'].keys()
    return keys


def test_deprecated_models_present_with_flag():
    """Deprecated models should be present in built data with the deprecated flag set to True."""
    deprecated_models = [(p.id, m.id, m.deprecated) for p in providers for m in p.models if m.deprecated]
    assert len(deprecated_models) > 0, 'Expected at least one deprecated model in built data'
    for _, _, deprecated in deprecated_models:
        assert deprecated is True


def test_removed_models_absent():
    """Removed models (claude-instant-1, claude-instant-1.2) should not appear in the built provider data."""
    anthropic = next(p for p in providers if p.id == 'anthropic')
    model_ids = {m.id for m in anthropic.models}
    assert 'claude-instant-1' not in model_ids
    assert 'claude-instant-1.2' not in model_ids


def test_deprecated_flag_in_v2_data() -> None:
    """The deprecated flag should appear in the v2 payloads for deprecated models and be absent for normal models.

    Targets v2 because v1 is frozen: reading it here would assert about a file no build can change.
    """
    for data_path in (_V2_DIR / 'data.json', _V2_DIR / 'data_slim.json'):
        deprecated_found = False

        for provider in _load_raw_providers(data_path):
            for model in provider['models']:
                if model.get('deprecated') is True:
                    deprecated_found = True
                else:
                    assert 'deprecated' not in model, (
                        f'Non-deprecated model has deprecated key in {data_path.name}: {provider["id"]}:{model["id"]}'
                    )

        assert deprecated_found, f'Expected at least one model with deprecated=true in {data_path.name}'


def test_removed_field_not_in_v2_data() -> None:
    """`removed` is a build-time filter and must never reach a published payload."""
    for data_path in (_V2_DIR / 'data.json', _V2_DIR / 'data_slim.json'):
        for provider in _load_raw_providers(data_path):
            for model in provider['models']:
                assert 'removed' not in model, (
                    f'removed field found in {data_path.name} for model {provider["id"]}:{model["id"]}'
                )


# Every price key present across both frozen v1 payloads. Byte identity is pinned in
# `tests/test_frozen_v1_data.py`; this is the semantic companion a hash bump would not catch.
_V1_PRICE_KEYS = frozenset(
    {
        'cache_audio_read_mtok',
        'cache_read_mtok',
        'cache_write_mtok',
        'input_audio_mtok',
        'input_mtok',
        'output_audio_mtok',
        'output_mtok',
        'requests_kcount',
    }
)


def test_v1_payloads_use_only_v1_price_keys() -> None:
    """Semantic companion to the byte freeze: v1 must keep speaking the v1 billing-unit vocabulary."""
    for filename in ('data.json', 'data_slim.json'):
        keys = _price_keys(_load_raw_providers(package_dir / filename))

        assert keys, f'no price keys found in {filename}'
        assert keys <= _V1_PRICE_KEYS, (
            f'{filename} contains post-v1 price keys {sorted(keys - _V1_PRICE_KEYS)}; v1 is frozen and must not be '
            'regenerated from the current (v2) unit registry'
        )


_PUBLISHED_ARTIFACTS = [
    pytest.param(
        package_dir / 'data.json',
        id='v1-full',
    ),
    pytest.param(
        package_dir / 'data_slim.json',
        id='v1-slim',
        marks=pytest.mark.xfail(
            reason=(
                'frozen v1 slim data carries `pricing_urls` on every provider while its published schema sets '
                '`additionalProperties: false` and omits it — see issue #533. Predates the v2 split (reproducible '
                'at e15b266^) and v1 is frozen, so the mismatch is recorded here rather than repaired.'
            ),
            # xfail_strict is true repo-wide; non-strict so a future corrected republish of v1 does not fail CI
            strict=False,
        ),
    ),
    pytest.param(
        _V2_DIR / 'data.json',
        id='v2-full',
    ),
    pytest.param(
        _V2_DIR / 'data_slim.json',
        id='v2-slim',
    ),
]


@pytest.mark.parametrize('data_path', _PUBLISHED_ARTIFACTS)
def test_built_payloads_validate_against_their_own_schemas(data_path: Path) -> None:
    """Every published payload must satisfy the schema published beside it."""
    data = json.loads(data_path.read_bytes())
    schema = json.loads(data_path.with_suffix('.schema.json').read_bytes())

    # The generated schemas declare no `$schema`; `validator_for` falls back to the dialect pydantic emits, and
    # picks up the declared one automatically if a future build starts writing it.
    validator_cls = validator_for(schema, default=jsonschema.Draft202012Validator)
    errors = [
        f'{"/".join(str(part) for part in error.absolute_path)}: {error.message}'
        for error in validator_cls(schema).iter_errors(data)
    ]

    assert errors == []


def test_v1_remote_payloads_are_provider_arrays():
    """Pinned v1 JSON payloads retain their original provider-array contract."""
    from prices.utils import package_dir

    for filename in ('data.json', 'data_slim.json'):
        payload = cast(list[object], json.loads((package_dir / filename).read_bytes()))

        assert isinstance(payload, list)
        assert payload
        assert all(isinstance(provider, dict) for provider in payload)


def test_v2_remote_payloads_are_provider_arrays_with_static_unit_vocabulary():
    """V2 publishes current providers without embedding mutable unit registry state."""
    from prices.utils import package_dir

    v2_dir = package_dir / 'new_data' / 'v2'
    for stem in ('data', 'data_slim'):
        payload = cast(list[dict[str, Any]], json.loads((v2_dir / f'{stem}.json').read_bytes()))
        schema = cast(dict[str, Any], json.loads((v2_dir / f'{stem}.schema.json').read_bytes()))

        assert isinstance(payload, list)
        assert payload
        assert all(isinstance(provider, dict) for provider in payload)
        assert schema['type'] == 'array'

        model_price_schema = schema['$defs']['ModelPrice']
        assert 'cache_image_write_mtok' in model_price_schema['properties']
        extractor_destinations = schema['$defs']['UsageExtractorMapping']['properties']['dest']['enum']
        assert 'input_image_tokens' in extractor_destinations

        google = next(provider for provider in payload if provider['id'] == 'google')
        destinations = {mapping['dest'] for extractor in google['extractors'] for mapping in extractor['mappings']}
        assert 'input_image_tokens' in destinations


def test_v2_slim_payload_is_exact_projection_of_full_payload() -> None:
    from prices.utils import package_dir

    v2_dir = package_dir / 'new_data' / 'v2'
    full_payload = json.loads((v2_dir / 'data.json').read_bytes())
    slim_payload = json.loads((v2_dir / 'data_slim.json').read_bytes())
    build_providers = providers_schema.validate_python(full_payload)
    for provider in build_providers:
        provider.exclude_free()

    expected_slim_payload = json.loads(
        providers_schema.dump_json(
            build_providers,
            by_alias=True,
            exclude_none=True,
            exclude={
                '__all__': {
                    'pricing_urls': True,
                    'description': True,
                    'price_comments': True,
                    'models': {'__all__': {'name', 'description', 'price_comments'}},
                }
            },
        )
    )

    assert slim_payload == expected_slim_payload
    assert all('pricing_urls' not in provider for provider in slim_payload)


def test_python_unit_data_is_separate_from_provider_data():
    """Unit registry data is bundled separately from provider-heavy Python data."""
    assert genai_data.__all__ == ('providers',)
    assert genai_data_units.__all__ == ('unit_data',)
    assert not hasattr(genai_data, 'unit_data')
    assert not hasattr(genai_data_units, 'providers')
    assert isinstance(genai_data_units.unit_data, dict)


def test_python_unit_data_import_does_not_import_provider_data():
    """Importing bundled unit registry data does not import the generated provider list."""
    subprocess.run(
        [
            sys.executable,
            '-c',
            "import sys; import genai_prices.data_units; assert 'genai_prices.data' not in sys.modules",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_get_registry_does_not_import_provider_data():
    """Building the active unit registry does not import the generated provider list."""
    subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import sys; '
                'from genai_prices.units import _get_registry; '
                '_get_registry(); '
                "assert 'genai_prices.data' not in sys.modules"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_generated_provider_data_import_succeeds_with_extractor_validation():
    """Generated provider data can construct extractors while destination validation is enabled."""
    subprocess.run(
        [
            sys.executable,
            '-c',
            'import genai_prices.data; assert genai_prices.data.providers',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
