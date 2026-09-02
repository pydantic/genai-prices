from __future__ import annotations

import copy
from decimal import Decimal
from operator import attrgetter
from pathlib import Path
from typing import Any, cast

import pydantic_core
import ruamel.yaml
from pydantic import ValidationError

from genai_prices.units import UnitDef
from prices.export_validation import (
    normalize_conditional_implications,
    public_unit_key_schema,
    runtime_unit_projection,
    validate_export_payload,
    validate_units,
)
from prices.frozen_v2 import validate_frozen_v2_artifacts
from prices.prices_types import Provider, providers_schema
from prices.utils import package_dir, root_dir, simplify_json_schema
from prices.v3_compatibility import resolve_compatibility_target, validate_v3_compatibility


def decimal_constructor(loader: ruamel.yaml.SafeLoader, node: ruamel.yaml.ScalarNode) -> Decimal:
    s = cast(str, loader.construct_scalar(node))  # pyright: ignore[reportUnknownMemberType]
    return Decimal(s)


yaml = ruamel.yaml.YAML(typ='safe')
yaml.constructor.add_constructor('tag:yaml.org,2002:float', decimal_constructor)  # pyright: ignore[reportUnknownMemberType]


def load_units() -> dict[str, Any]:
    with (package_dir / 'units.yml').open() as f:
        units = cast(dict[str, Any], yaml.load(f))  # pyright: ignore[reportUnknownMemberType]

    return units


def v3_data_schema() -> dict[str, Any]:
    """Build the wrapped v3 schema with dynamic price and extractor destination keys."""
    provider_array_schema = simplify_json_schema(providers_schema.json_schema(mode='serialization'))
    definitions = cast(dict[str, Any], provider_array_schema.pop('$defs'))
    provider_items = cast(dict[str, Any], provider_array_schema['items'])
    definitions['RuntimeUnitData'] = {
        'additionalProperties': False,
        'properties': {
            'per': {
                'maximum': 9_007_199_254_740_991,
                'minimum': 1,
                'type': 'integer',
            },
            'price_key': {
                **public_unit_key_schema(),
            },
            'dimensions': {
                'additionalProperties': {'minLength': 1, 'type': 'string'},
                'minProperties': 1,
                'properties': {'family': {'minLength': 1, 'type': 'string'}},
                'propertyNames': {'minLength': 1, 'type': 'string'},
                'required': ['family'],
                'type': 'object',
            },
        },
        'required': ['per', 'dimensions'],
        'type': 'object',
    }
    return {
        '$defs': definitions,
        'additionalProperties': False,
        'properties': {
            'units': {
                'additionalProperties': {'$ref': '#/$defs/RuntimeUnitData'},
                'propertyNames': public_unit_key_schema(),
                'type': 'object',
            },
            'providers': {'items': provider_items, 'type': 'array'},
        },
        'required': ['units', 'providers'],
        'type': 'object',
    }


def prepare_v3_data(providers: list[Provider], raw_units: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prepare a validated v3 schema and wrapped payload without writing artifacts."""
    validate_export_payload(providers, raw_units)
    schema = v3_data_schema()
    provider_data = providers_schema.dump_python(providers, mode='json', by_alias=True, exclude_none=True)
    payload = {
        'units': runtime_unit_projection(raw_units),
        'providers': provider_data,
    }
    return schema, payload


def build(compatibility_target_oid: str | None = None) -> None:
    """Validate the complete candidate before publishing the provider schema and v3 data."""
    target_oid = resolve_compatibility_target(compatibility_target_oid)
    units = load_units()
    providers = load_providers()
    prepare_providers_for_export(providers)
    candidate_schema, candidate_payload = prepare_v3_data(providers, units)
    provider_schema = _provider_yaml_schema(units)
    validate_frozen_v2_artifacts()
    validate_v3_compatibility(
        target_oid,
        candidate_runtime_units=runtime_unit_projection(units),
        candidate_implications=normalize_conditional_implications(units),
        candidate_schema=candidate_schema,
        candidate_payload=candidate_payload,
    )

    schema_json_path = package_dir / 'providers' / '.schema.json'
    schema_json_path.write_bytes(pydantic_core.to_json(provider_schema, indent=2) + b'\n')
    print('Providers JSON schema written to', schema_json_path.relative_to(root_dir))
    write_v3_data(providers, units, prepared=(candidate_schema, candidate_payload))


def load_providers() -> list[Provider]:
    """Load and validate provider YAML without applying export-time mutations."""
    providers: list[Provider] = []

    providers_dir = package_dir / 'providers'
    for file in providers_dir.iterdir():
        if file.suffix not in ('.yml', '.yaml'):
            continue

        with file.open('rb') as f:
            data = cast(Any, yaml.load(f))  # pyright: ignore[reportUnknownMemberType]

        try:
            provider = Provider.model_validate_json(pydantic_core.to_json(data), strict=True)
        except ValidationError as e:
            raise ValueError(f'Error validating provider {file.name}:\n{e}') from e
        else:
            providers.append(provider)

    providers.sort(key=attrgetter('id'))
    return providers


def prepare_providers_for_export(providers: list[Provider]) -> None:
    """Resolve canonical links before dropping removed models, so a removed record can still pass on its metadata."""
    inherit_context_windows(providers)
    for provider in providers:
        provider.exclude_removed()


def inherit_context_windows(providers: list[Provider]) -> None:
    """Fill each model's missing context window from its canonical record."""
    models = {f'{provider.id}/{model.id}': model for provider in providers for model in provider.models}

    for provider in providers:
        for model in provider.models:
            if canonical_ref := model.canonical_model:
                canonical = models.get(canonical_ref)
                if canonical is None:
                    raise ValueError(
                        f'Model `{provider.id}/{model.id}` references unknown canonical model `{canonical_ref}`'
                    )
                if canonical.canonical_model is not None:
                    raise ValueError(f'Canonical model `{canonical_ref}` must not reference another canonical model')
                if model.context_window is None and canonical.context_window is not None:
                    model.context_window = canonical.context_window


def _provider_yaml_schema(raw_units: dict[str, Any]) -> dict[str, Any]:
    """Build the provider YAML authoring schema from validated unit registry data."""
    json_schema = simplify_json_schema(Provider.model_json_schema())
    return _add_unit_vocabulary_to_schema(json_schema, raw_units)


def _add_unit_vocabulary_to_schema(json_schema: dict[str, Any], raw_units: dict[str, Any]) -> dict[str, Any]:
    registry = validate_units(raw_units)

    model_price_schema = cast(dict[str, Any], json_schema['$defs']['ModelPrice'])
    model_price_properties = cast(dict[str, Any], model_price_schema['properties'])
    additional_price_schema = cast(dict[str, Any], model_price_schema['additionalProperties'])
    for unit in registry.units.values():
        model_price_properties.setdefault(unit.price_key, _unit_price_schema(unit, additional_price_schema))

    extractor_mapping_schema = cast(dict[str, Any], json_schema['$defs']['UsageExtractorMapping'])
    extractor_mapping_properties = cast(dict[str, Any], extractor_mapping_schema['properties'])
    dest_schema = cast(dict[str, Any], extractor_mapping_properties['dest'])
    dest_schema['enum'] = sorted(registry._reported_usage_keys)  # pyright: ignore[reportPrivateUsage]

    return json_schema


def _unit_price_schema(unit: UnitDef, additional_price_schema: dict[str, Any]) -> dict[str, Any]:
    schema = copy.deepcopy(additional_price_schema)
    schema['title'] = unit.price_key.replace('_', ' ').title()
    normalization = {1_000: 'thousand', 1_000_000: 'million'}.get(unit.per, f'{unit.per:,}')
    cache_ttl = unit.dimensions.get('cache_ttl')
    duration_price_unit = {60: ('minutes', 'minute'), 3_600: ('hours', 'hour')}.get(unit.per)
    if (
        duration_price_unit is not None
        and unit.usage_key.endswith('_seconds')
        and unit.price_key.endswith(f'_{duration_price_unit[0]}')
    ):
        normalization = ''
        usage_name = f'{unit.usage_key.removesuffix("_seconds").replace("_", " ")} {duration_price_unit[1]}'
    elif (
        unit.dimensions.get('token_type') == 'cache_write'
        and unit.dimensions.get('modality') is None
        and cache_ttl is not None
    ):
        ttl_description = {'5m': '5-minute', '1h': '1-hour'}.get(cache_ttl, cache_ttl)
        usage_name = f'tokens written to the cache with a {ttl_description} TTL'
    else:
        usage_name = unit.usage_key.replace('_', ' ')
    schema['description'] = f'price in USD per {" ".join(filter(None, (normalization, usage_name)))}'
    return schema


def write_v3_data(
    providers: list[Provider],
    raw_units: dict[str, Any],
    *,
    prepared: tuple[dict[str, Any], dict[str, Any]] | None = None,
) -> None:
    """Write the validated wrapped v3 schema and payload."""
    schema, payload = prepared if prepared is not None else prepare_v3_data(providers, raw_units)
    output_dir = package_dir / 'new_data' / 'v3'
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_generated_json(output_dir / 'data.schema.json', schema, indent=2)
    _write_generated_json(output_dir / 'data.json', payload)


def _write_generated_json(path: Path, value: object, *, indent: int | None = None) -> None:
    encoded = pydantic_core.to_json(value, indent=indent) + b'\n'
    current = path.read_bytes() if path.exists() else None
    action = 'unchanged' if current == encoded else 'updated'
    if current != encoded:
        path.write_bytes(encoded)
    print(f'Generated {path.relative_to(root_dir)} {action}')


if __name__ == '__main__':
    build()
