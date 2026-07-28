from __future__ import annotations

import copy
from decimal import Decimal
from operator import attrgetter
from typing import Any, cast

import pydantic_core
import ruamel.yaml
from pydantic import ValidationError

from prices.export_validation import validate_export_payload, validate_units
from prices.prices_types import Provider
from prices.utils import package_dir, root_dir, simplify_json_schema


def decimal_constructor(loader: ruamel.yaml.SafeLoader, node: ruamel.yaml.ScalarNode) -> Decimal:
    s = cast(str, loader.construct_scalar(node))  # pyright: ignore[reportUnknownMemberType]
    return Decimal(s)


yaml = ruamel.yaml.YAML(typ='safe')
yaml.constructor.add_constructor('tag:yaml.org,2002:float', decimal_constructor)  # pyright: ignore[reportUnknownMemberType]


def load_units() -> dict[str, Any]:
    with (package_dir / 'units.yml').open() as f:
        units = cast(dict[str, Any], yaml.load(f))  # pyright: ignore[reportUnknownMemberType]

    return units


def build():
    """Validate the publication inputs and build the provider authoring schema."""
    units = load_units()
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
    for provider in providers:
        provider.exclude_removed()
    validate_export_payload(providers, units)

    # Write only the authoring schema. The legacy v1 publication artifacts are
    # pinned and remain byte-for-byte unchanged.
    schema_json_path = package_dir / 'providers' / '.schema.json'
    schema_json_path.write_bytes(pydantic_core.to_json(_provider_yaml_schema(units), indent=2) + b'\n')
    print('Providers JSON schema written to', schema_json_path.relative_to(root_dir))


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
        model_price_properties.setdefault(unit.price_key, copy.deepcopy(additional_price_schema))

    extractor_mapping_schema = cast(dict[str, Any], json_schema['$defs']['UsageExtractorMapping'])
    extractor_mapping_properties = cast(dict[str, Any], extractor_mapping_schema['properties'])
    dest_schema = cast(dict[str, Any], extractor_mapping_properties['dest'])
    dest_schema['enum'] = sorted(registry._reported_usage_keys)  # pyright: ignore[reportPrivateUsage]

    return json_schema


if __name__ == '__main__':
    build()
