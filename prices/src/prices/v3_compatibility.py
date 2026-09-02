from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping, Sequence
from typing import TypeAlias, cast

import jsonschema
import ruamel.yaml
from jsonschema.validators import validator_for
from typing_extensions import Never

from .export_validation import (
    NormalizedImplications,
    RuntimeUnitProjection,
    normalize_conditional_implications,
    runtime_unit_projection,
    validate_runtime_unit_projection,
    validate_unit_evolution,
    validate_units,
)
from .utils import root_dir

JsonData: TypeAlias = 'None | bool | int | float | str | list[JsonData] | dict[str, JsonData]'

_ANNOTATION_KEYS = frozenset({'description', 'title'})
_LOWER_BOUNDS = frozenset({'exclusiveMinimum', 'minItems', 'minLength', 'minProperties', 'minimum'})
_UPPER_BOUNDS = frozenset({'exclusiveMaximum', 'maxItems', 'maxLength', 'maxProperties', 'maximum'})
_EXACT_CONSTRAINTS = frozenset({'format', 'multipleOf', 'pattern'})
_STRUCTURAL_KEYS = (
    frozenset(
        {
            '$defs',
            '$ref',
            'additionalProperties',
            'anyOf',
            'const',
            'default',
            'enum',
            'items',
            'oneOf',
            'properties',
            'propertyNames',
            'required',
            'type',
            'uniqueItems',
        }
    )
    | _LOWER_BOUNDS
    | _UPPER_BOUNDS
    | _EXACT_CONSTRAINTS
)

_V3_DATA_PATH = 'prices/new_data/v3/data.json'
_V3_SCHEMA_PATH = 'prices/new_data/v3/data.schema.json'
_SOURCE_UNITS_PATH = 'prices/units.yml'


def validate_v3_compatibility(
    target_oid: str,
    *,
    candidate_runtime_units: RuntimeUnitProjection,
    candidate_implications: NormalizedImplications,
    candidate_schema: JsonData,
    candidate_payload: JsonData,
) -> None:
    """Compare an in-memory v3 candidate with one exact target Git object."""
    resolved_target_oid = resolve_compatibility_target(target_oid)
    print(f'Validating v3 compatibility against target {resolved_target_oid}')
    _validate_target_is_ancestor(resolved_target_oid)

    target_source_units = _load_target_source_units(resolved_target_oid)
    validate_units(target_source_units)
    target_source_projection = runtime_unit_projection(target_source_units)
    target_implications = normalize_conditional_implications(target_source_units)
    has_v3_data = _target_path_exists(resolved_target_oid, _V3_DATA_PATH)
    has_v3_schema = _target_path_exists(resolved_target_oid, _V3_SCHEMA_PATH)
    if has_v3_data != has_v3_schema:
        raise ValueError(f'Invalid v3 compatibility baseline at {resolved_target_oid}: mixed v3 artifacts')

    previous_schema: JsonData | None = None
    if has_v3_data:
        previous_payload = _load_target_json(resolved_target_oid, _V3_DATA_PATH)
        previous_schema = _load_target_json(resolved_target_oid, _V3_SCHEMA_PATH)
        previous_runtime_units = _payload_runtime_units(previous_payload, 'target v3 payload')
        _validate_payload(previous_schema, previous_payload, 'target v3 payload')
        if previous_runtime_units != target_source_projection:
            raise ValueError(
                f'Invalid v3 compatibility baseline at {resolved_target_oid}: '
                'published units do not match target source units'
            )
    else:
        previous_runtime_units = target_source_projection

    validate_runtime_unit_projection(candidate_runtime_units)
    candidate_payload_units = _payload_runtime_units(candidate_payload, 'candidate v3 payload')
    if candidate_payload_units != runtime_unit_projection(candidate_runtime_units):
        raise ValueError('Invalid candidate v3 payload: units do not match the supplied in-memory candidate')
    _validate_payload(candidate_schema, candidate_payload, 'candidate v3 payload')

    if previous_schema is not None:
        validate_v3_schema_evolution(previous_schema, candidate_schema)

    candidate_source_units = _source_units_from_projections(candidate_runtime_units, candidate_implications)
    validate_unit_evolution(previous_runtime_units, target_implications, candidate_source_units)


def main() -> None:
    """Run the target-bound compatibility check without writing build artifacts."""
    parser = argparse.ArgumentParser(description='Validate an in-memory v3 candidate against an exact Git target')
    parser.add_argument('target_oid', help='Git commit or ref to use as the compatibility target')
    args = parser.parse_args()

    from .build import load_providers, load_units, prepare_providers_for_export, prepare_v3_data

    raw_units = load_units()
    providers = load_providers()
    prepare_providers_for_export(providers)
    candidate_schema, candidate_payload = prepare_v3_data(providers, raw_units)
    validate_v3_compatibility(
        args.target_oid,
        candidate_runtime_units=runtime_unit_projection(raw_units),
        candidate_implications=normalize_conditional_implications(raw_units),
        candidate_schema=candidate_schema,
        candidate_payload=candidate_payload,
    )


def resolve_compatibility_target(target_oid: str | None = None) -> str:
    """Resolve a requested compatibility target, defaulting to the current HEAD."""
    requested_target = target_oid or 'HEAD'
    result = subprocess.run(
        ['git', 'rev-parse', '--verify', f'{requested_target}^{{commit}}'],
        cwd=root_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    resolved = result.stdout.strip()
    if result.returncode != 0 or not resolved:
        raise ValueError(f'Invalid v3 compatibility target {requested_target!r}: expected a Git commit')
    return resolved


def _validate_target_is_ancestor(target_oid: str) -> None:
    result = subprocess.run(
        ['git', 'merge-base', '--is-ancestor', target_oid, 'HEAD'],
        cwd=root_dir,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError(f'Stale v3 compatibility target {target_oid}: target is not an ancestor of HEAD')


def _target_path_exists(target_oid: str, relative_path: str) -> bool:
    result = subprocess.run(
        ['git', 'cat-file', '-e', f'{target_oid}:{relative_path}'],
        cwd=root_dir,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _git_show(target_oid: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ['git', 'show', f'{target_oid}:{relative_path}'],
        cwd=root_dir,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError(f'Invalid v3 compatibility baseline at {target_oid}: missing {relative_path}')
    return result.stdout


def _load_target_json(target_oid: str, relative_path: str) -> JsonData:
    try:
        return cast(JsonData, json.loads(_git_show(target_oid, relative_path)))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'Invalid v3 compatibility baseline at {target_oid}: malformed {relative_path}') from exc


def _load_target_source_units(target_oid: str) -> dict[str, dict[str, object]]:
    raw_source = _git_show(target_oid, _SOURCE_UNITS_PATH)
    yaml = ruamel.yaml.YAML(typ='safe')
    try:
        loaded = cast(object, yaml.load(raw_source))  # pyright: ignore[reportUnknownMemberType]
    except ruamel.yaml.YAMLError as exc:
        raise ValueError(f'Invalid v3 compatibility baseline at {target_oid}: malformed {_SOURCE_UNITS_PATH}') from exc
    mapping = _schema_mapping(loaded, f'target {_SOURCE_UNITS_PATH}')
    return {
        usage_key: dict(_schema_mapping(raw_unit, f'target unit {usage_key}'))
        for usage_key, raw_unit in mapping.items()
    }


def _payload_runtime_units(payload: JsonData, label: str) -> RuntimeUnitProjection:
    payload_mapping = _schema_mapping(payload, label)
    raw_units = payload_mapping.get('units')
    if not isinstance(raw_units, Mapping):
        raise ValueError(f'Invalid {label}: expected an object units member')
    units = {
        usage_key: dict(_schema_mapping(raw_unit, f'{label} unit {usage_key}'))
        for usage_key, raw_unit in _schema_mapping(raw_units, f'{label} units').items()
    }
    registry = validate_runtime_unit_projection(units)
    return runtime_unit_projection(
        {
            usage_key: {
                'per': unit.per,
                **({'price_key': unit.price_key} if unit.price_key != usage_key else {}),
                'dimensions': dict(unit.dimensions),
            }
            for usage_key, unit in registry.units.items()
        }
    )


def _validate_payload(schema: JsonData, payload: JsonData, label: str) -> None:
    schema_mapping = _schema_mapping(schema, f'{label} schema')
    schema_dict = dict(schema_mapping)
    try:
        validator_cls = validator_for(schema_dict, default=jsonschema.Draft202012Validator)
        validator_cls.check_schema(schema_dict)
        validator_cls(schema_dict).validate(payload)
    except jsonschema.SchemaError as exc:
        raise ValueError(f'Invalid {label} schema: {exc.message}') from exc
    except jsonschema.ValidationError as exc:
        raise ValueError(f'Invalid {label}: {exc.message}') from exc


def _source_units_from_projections(
    runtime_units: RuntimeUnitProjection,
    normalized_implications: NormalizedImplications,
) -> dict[str, dict[str, object]]:
    if set(normalized_implications) != set(runtime_units):
        raise ValueError('Invalid candidate unit implications: keys do not match candidate runtime units')
    source_units: dict[str, dict[str, object]] = {}
    for usage_key, runtime_unit in runtime_units.items():
        source_unit = dict(runtime_unit)
        requirements: dict[str, dict[str, str]] = {}
        for trigger, required_key, required_value in normalized_implications[usage_key]:
            existing_value = requirements.setdefault(trigger, {}).get(required_key)
            if existing_value is not None and existing_value != required_value:
                raise ValueError(f'Invalid candidate unit implications for {usage_key}: conflicting {required_key}')
            requirements[trigger][required_key] = required_value
        if requirements:
            source_unit['dimension_requirements'] = requirements
        source_units[usage_key] = source_unit
    return source_units


def validate_v3_schema_evolution(previous_schema: JsonData, candidate_schema: JsonData) -> None:
    """Validate additive evolution within this repository's v3 schema normal form."""
    previous = _schema_mapping(previous_schema, 'previous schema')
    candidate = _schema_mapping(candidate_schema, 'candidate schema')
    _compare_schema(previous, candidate, previous, candidate, '$', set())


def _compare_schema(
    previous: Mapping[str, JsonData],
    candidate: Mapping[str, JsonData],
    previous_root: Mapping[str, JsonData],
    candidate_root: Mapping[str, JsonData],
    path: str,
    seen_refs: set[tuple[str, str]],
) -> None:
    previous_ref = previous.get('$ref')
    if previous_ref is not None:
        candidate_ref = candidate.get('$ref')
        if not isinstance(previous_ref, str) or not isinstance(candidate_ref, str) or candidate_ref != previous_ref:
            _incompatible(path, f'changed reference from {previous_ref!r} to {candidate_ref!r}')
        ref_pair = (previous_ref, candidate_ref)
        if ref_pair not in seen_refs:
            seen_refs.add(ref_pair)
            _compare_schema(
                _resolve_ref(previous_ref, previous_root, f'{path} previous reference'),
                _resolve_ref(candidate_ref, candidate_root, f'{path} candidate reference'),
                previous_root,
                candidate_root,
                previous_ref,
                seen_refs,
            )
    elif '$ref' in candidate:
        _incompatible(path, 'replaced an inline schema with a reference')

    _compare_types(previous, candidate, path)
    _compare_default(previous, candidate, path)
    _compare_enum(previous, candidate, path)
    _compare_const(previous, candidate, path)
    _compare_bounds(previous, candidate, path)
    _compare_exact_constraints(previous, candidate, path)

    previous_required = _string_set(previous.get('required', []), f'{path}.required')
    candidate_required = _string_set(candidate.get('required', []), f'{path}.required')
    if added_required := candidate_required - previous_required:
        _incompatible(path, f'newly requires {sorted(added_required)!r}')
    if removed_required := previous_required - candidate_required:
        _incompatible(path, f'no longer requires {sorted(removed_required)!r}')

    previous_properties = _optional_schema_map(previous.get('properties'), f'{path}.properties')
    candidate_properties = _optional_schema_map(candidate.get('properties'), f'{path}.properties')
    for property_name, previous_property in previous_properties.items():
        candidate_property = candidate_properties.get(property_name)
        if candidate_property is None:
            _incompatible(path, f'removed property {property_name!r}')
        _compare_schema(
            previous_property,
            candidate_property,
            previous_root,
            candidate_root,
            f'{path}.properties.{property_name}',
            seen_refs,
        )

    _compare_additional_properties(previous, candidate, previous_root, candidate_root, path, seen_refs)
    _compare_optional_subschema(previous, candidate, 'items', previous_root, candidate_root, path, seen_refs)
    _compare_optional_subschema(previous, candidate, 'propertyNames', previous_root, candidate_root, path, seen_refs)
    _compare_variants(previous, candidate, 'anyOf', previous_root, candidate_root, path, seen_refs)
    _compare_variants(previous, candidate, 'oneOf', previous_root, candidate_root, path, seen_refs)
    _compare_unknown_keywords(previous, candidate, path)


def _compare_types(previous: Mapping[str, JsonData], candidate: Mapping[str, JsonData], path: str) -> None:
    previous_types = _schema_types(previous.get('type'), f'{path}.type')
    candidate_types = _schema_types(candidate.get('type'), f'{path}.type')
    if previous_types is None:
        if candidate_types is not None:
            _incompatible(path, f'narrowed unconstrained type to {sorted(candidate_types)!r}')
        return
    if candidate_types is None:
        return
    if not all(
        any(_type_accepts(candidate_type, old_type) for candidate_type in candidate_types)
        for old_type in previous_types
    ):
        _incompatible(path, f'narrowed type from {sorted(previous_types)!r} to {sorted(candidate_types)!r}')


def _compare_default(previous: Mapping[str, JsonData], candidate: Mapping[str, JsonData], path: str) -> None:
    if ('default' in previous or 'default' in candidate) and previous.get('default') != candidate.get('default'):
        _incompatible(path, f'changed default from {previous.get("default")!r} to {candidate.get("default")!r}')


def _compare_enum(previous: Mapping[str, JsonData], candidate: Mapping[str, JsonData], path: str) -> None:
    previous_enum = previous.get('enum')
    candidate_enum = candidate.get('enum')
    if previous_enum is None:
        if candidate_enum is not None:
            _incompatible(path, 'added an enum restriction')
        return
    if candidate_enum is None:
        return
    previous_values = _json_value_set(previous_enum, f'{path}.enum')
    candidate_values = _json_value_set(candidate_enum, f'{path}.enum')
    if not previous_values <= candidate_values:
        _incompatible(path, f'removed enum values {sorted(previous_values - candidate_values, key=repr)!r}')


def _compare_const(previous: Mapping[str, JsonData], candidate: Mapping[str, JsonData], path: str) -> None:
    if 'const' not in previous:
        if 'const' in candidate:
            _incompatible(path, 'added a const restriction')
        return
    if 'const' in candidate and candidate['const'] != previous['const']:
        _incompatible(path, f'changed const from {previous["const"]!r} to {candidate["const"]!r}')


def _compare_bounds(previous: Mapping[str, JsonData], candidate: Mapping[str, JsonData], path: str) -> None:
    for key in _LOWER_BOUNDS:
        old_bound = previous.get(key)
        new_bound = candidate.get(key)
        if old_bound is None:
            if new_bound is not None:
                _incompatible(path, f'added lower bound {key}={new_bound!r}')
        elif new_bound is not None and _number(new_bound, f'{path}.{key}') > _number(old_bound, f'{path}.{key}'):
            _incompatible(path, f'narrowed lower bound {key} from {old_bound!r} to {new_bound!r}')

    for key in _UPPER_BOUNDS:
        old_bound = previous.get(key)
        new_bound = candidate.get(key)
        if old_bound is None:
            if new_bound is not None:
                _incompatible(path, f'added upper bound {key}={new_bound!r}')
        elif new_bound is not None and _number(new_bound, f'{path}.{key}') < _number(old_bound, f'{path}.{key}'):
            _incompatible(path, f'narrowed upper bound {key} from {old_bound!r} to {new_bound!r}')


def _compare_exact_constraints(previous: Mapping[str, JsonData], candidate: Mapping[str, JsonData], path: str) -> None:
    for key in _EXACT_CONSTRAINTS:
        if key not in previous:
            if key in candidate:
                _incompatible(path, f'added {key} restriction')
        elif key in candidate and candidate[key] != previous[key]:
            _incompatible(path, f'changed {key} restriction')

    old_unique = previous.get('uniqueItems', False)
    new_unique = candidate.get('uniqueItems', False)
    if old_unique is not True and new_unique is True:
        _incompatible(path, 'newly requires unique array items')


def _compare_additional_properties(
    previous: Mapping[str, JsonData],
    candidate: Mapping[str, JsonData],
    previous_root: Mapping[str, JsonData],
    candidate_root: Mapping[str, JsonData],
    path: str,
    seen_refs: set[tuple[str, str]],
) -> None:
    old_value = previous.get('additionalProperties', True)
    new_value = candidate.get('additionalProperties', True)
    if old_value is False:
        return
    if new_value is False:
        _incompatible(path, 'narrowed additional properties')
    if old_value is True:
        if new_value is not True:
            _incompatible(path, 'added a schema restriction for additional properties')
        return
    if new_value is True:
        return
    old_schema = _schema_mapping(old_value, f'{path}.additionalProperties')
    new_schema = _schema_mapping(new_value, f'{path}.additionalProperties')
    _compare_schema(old_schema, new_schema, previous_root, candidate_root, f'{path}.additionalProperties', seen_refs)


def _compare_optional_subschema(
    previous: Mapping[str, JsonData],
    candidate: Mapping[str, JsonData],
    key: str,
    previous_root: Mapping[str, JsonData],
    candidate_root: Mapping[str, JsonData],
    path: str,
    seen_refs: set[tuple[str, str]],
) -> None:
    old_value = previous.get(key)
    new_value = candidate.get(key)
    if old_value is None:
        if new_value is not None:
            _incompatible(path, f'added {key} restriction')
        return
    if new_value is None:
        return
    _compare_schema(
        _schema_mapping(old_value, f'{path}.{key}'),
        _schema_mapping(new_value, f'{path}.{key}'),
        previous_root,
        candidate_root,
        f'{path}.{key}',
        seen_refs,
    )


def _compare_variants(
    previous: Mapping[str, JsonData],
    candidate: Mapping[str, JsonData],
    key: str,
    previous_root: Mapping[str, JsonData],
    candidate_root: Mapping[str, JsonData],
    path: str,
    seen_refs: set[tuple[str, str]],
) -> None:
    old_value = previous.get(key)
    new_value = candidate.get(key)
    if old_value is None:
        if new_value is not None:
            _incompatible(path, f'added {key} restriction')
        return
    if new_value is None:
        _incompatible(path, f'removed {key} variants')

    old_variants = _schema_sequence(old_value, f'{path}.{key}')
    new_variants = _schema_sequence(new_value, f'{path}.{key}')
    used_candidate_indexes: set[int] = set()
    for old_index, old_variant in enumerate(old_variants):
        for new_index, new_variant in enumerate(new_variants):
            if new_index in used_candidate_indexes:
                continue
            try:
                _compare_schema(
                    old_variant,
                    new_variant,
                    previous_root,
                    candidate_root,
                    f'{path}.{key}[{old_index}]',
                    set(seen_refs),
                )
            except ValueError:
                continue
            used_candidate_indexes.add(new_index)
            break
        else:
            _incompatible(path, f'removed or narrowed {key} variant {old_index}')

    for new_index, new_variant in enumerate(new_variants):
        if new_index in used_candidate_indexes:
            continue
        if not _variant_is_distinguishable(new_variant, old_variants, previous_root, candidate_root):
            _incompatible(path, f'added ambiguous behavior-changing {key} variant {new_index}')


def _variant_is_distinguishable(
    candidate_variant: Mapping[str, JsonData],
    previous_variants: Sequence[Mapping[str, JsonData]],
    previous_root: Mapping[str, JsonData],
    candidate_root: Mapping[str, JsonData],
) -> bool:
    candidate_resolved = _resolve_schema(candidate_variant, candidate_root)
    previous_resolved = [_resolve_schema(variant, previous_root) for variant in previous_variants]
    previous_property_names = {
        property_name
        for variant in previous_resolved
        for property_name in _optional_schema_map(variant.get('properties'), 'variant properties')
    }

    for previous_variant in previous_resolved:
        old_types = _schema_types(previous_variant.get('type'), 'variant type')
        new_types = _schema_types(candidate_resolved.get('type'), 'variant type')
        if (
            old_types is not None
            and new_types is not None
            and not any(_types_overlap(old_type, new_type) for old_type in old_types for new_type in new_types)
        ):
            continue

        old_required = _string_set(previous_variant.get('required', []), 'variant required')
        new_required = _string_set(candidate_resolved.get('required', []), 'variant required')
        projected_required = new_required & previous_property_names
        if not old_required <= projected_required:
            continue
        if _has_disjoint_discriminator(previous_variant, candidate_resolved, old_required & new_required):
            continue
        return False
    return True


def _has_disjoint_discriminator(
    previous: Mapping[str, JsonData], candidate: Mapping[str, JsonData], shared_required: set[str]
) -> bool:
    previous_properties = _optional_schema_map(previous.get('properties'), 'variant properties')
    candidate_properties = _optional_schema_map(candidate.get('properties'), 'variant properties')
    for property_name in shared_required:
        old_values = _literal_values(previous_properties[property_name])
        new_values = _literal_values(candidate_properties[property_name])
        if old_values is not None and new_values is not None and old_values.isdisjoint(new_values):
            return True
    return False


def _literal_values(schema: Mapping[str, JsonData]) -> set[object] | None:
    if 'const' in schema:
        return {_hashable_json_value(schema['const'])}
    if 'enum' in schema:
        return _json_value_set(schema['enum'], 'variant enum')
    return None


def _compare_unknown_keywords(previous: Mapping[str, JsonData], candidate: Mapping[str, JsonData], path: str) -> None:
    previous_unknown = set(previous) - _STRUCTURAL_KEYS - _ANNOTATION_KEYS
    candidate_unknown = set(candidate) - _STRUCTURAL_KEYS - _ANNOTATION_KEYS
    if previous_unknown != candidate_unknown:
        _incompatible(
            path,
            f'changed unsupported schema keywords from {sorted(previous_unknown)!r} to {sorted(candidate_unknown)!r}',
        )
    for key in previous_unknown:
        if previous[key] != candidate[key]:
            _incompatible(path, f'changed unsupported schema keyword {key!r}')


def _schema_mapping(value: object, label: str) -> Mapping[str, JsonData]:
    if not isinstance(value, Mapping):
        raise ValueError(f'Invalid {label}: expected an object schema')
    object_mapping = cast(Mapping[object, object], value)
    if not all(isinstance(key, str) for key in object_mapping):
        raise ValueError(f'Invalid {label}: expected an object schema')
    return cast(Mapping[str, JsonData], value)


def _optional_schema_map(value: JsonData, label: str) -> dict[str, Mapping[str, JsonData]]:
    if value is None:
        return {}
    mapping = _schema_mapping(value, label)
    return {key: _schema_mapping(item, f'{label}.{key}') for key, item in mapping.items()}


def _schema_sequence(value: JsonData, label: str) -> list[Mapping[str, JsonData]]:
    if not isinstance(value, list):
        raise ValueError(f'Invalid {label}: expected a schema array')
    return [_schema_mapping(item, f'{label}[{index}]') for index, item in enumerate(value)]


def _schema_types(value: JsonData, label: str) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(cast(list[str], value))
    raise ValueError(f'Invalid {label}: expected a type string or string array')


def _string_set(value: JsonData, label: str) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f'Invalid {label}: expected a string array')
    return set(cast(list[str], value))


def _json_value_set(value: JsonData, label: str) -> set[object]:
    if not isinstance(value, list):
        raise ValueError(f'Invalid {label}: expected an array')
    return {_hashable_json_value(item) for item in value}


def _hashable_json_value(value: JsonData) -> object:
    if isinstance(value, list):
        return tuple(_hashable_json_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _hashable_json_value(item)) for key, item in value.items()))
    return value


def _number(value: JsonData, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f'Invalid {label}: expected a number')
    return float(value)


def _resolve_ref(reference: str, root: Mapping[str, JsonData], label: str) -> Mapping[str, JsonData]:
    prefix = '#/$defs/'
    if not reference.startswith(prefix):
        raise ValueError(f'Invalid {label}: only local $defs references are supported')
    definitions = _schema_mapping(root.get('$defs'), f'{label} $defs')
    name = reference.removeprefix(prefix)
    if name not in definitions:
        raise ValueError(f'Invalid {label}: missing definition {name!r}')
    return _schema_mapping(definitions[name], f'{label} definition {name!r}')


def _resolve_schema(schema: Mapping[str, JsonData], root: Mapping[str, JsonData]) -> Mapping[str, JsonData]:
    reference = schema.get('$ref')
    if isinstance(reference, str):
        return _resolve_ref(reference, root, 'variant reference')
    return schema


def _type_accepts(candidate_type: str, previous_type: str) -> bool:
    return candidate_type == previous_type or (candidate_type == 'number' and previous_type == 'integer')


def _types_overlap(left: str, right: str) -> bool:
    return _type_accepts(left, right) or _type_accepts(right, left)


def _incompatible(path: str, reason: str) -> Never:
    raise ValueError(f'Incompatible v3 schema at {path}: {reason}')


if __name__ == '__main__':  # pragma: no cover - exercised through the installed module command
    main()
