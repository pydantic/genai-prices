from __future__ import annotations

import copy
import difflib
import gzip
import io
from decimal import Decimal
from operator import attrgetter
from typing import Any, cast

import pydantic_core
import ruamel.yaml
from pydantic import ValidationError

from prices.export_validation import validate_export_payload, validate_units
from prices.prices_types import Provider, providers_schema
from prices.utils import package_dir, pretty_size, root_dir, simplify_json_schema


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
    """Build the provider authoring schema and v2 price data with its JSON Schema."""
    units = load_units()

    # write the schema JSON file used by the yaml language server
    schema_json_path = package_dir / 'providers' / '.schema.json'
    schema_json_path.write_bytes(pydantic_core.to_json(_provider_yaml_schema(units), indent=2) + b'\n')
    print('Providers JSON schema written to', schema_json_path.relative_to(root_dir))

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
    write_prices(providers, units, 'data_v2.json')


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
    dest_schema['enum'] = sorted(registry.reported_usage_keys)

    return json_schema


def write_prices(
    providers: list[Provider],
    units: dict[str, Any],
    prices_file: str,
):
    print('')
    prices_json_path = package_dir / prices_file

    providers_json_schema = providers_schema.json_schema(mode='serialization')
    providers_json_schema = simplify_json_schema(providers_json_schema)

    data_json_schema = _add_unit_vocabulary_to_schema(providers_json_schema, units)

    prices_json_schema_path = prices_json_path.with_suffix('.schema.json')
    prices_json_schema_path.write_bytes(pydantic_core.to_json(data_json_schema, indent=2) + b'\n')
    print(f'Prices data JSON schema written to {prices_json_schema_path.relative_to(root_dir)}')

    provider_data = providers_schema.dump_python(
        providers,
        mode='json',
        by_alias=True,
        exclude_none=True,
        warnings=False,
    )
    json_data = pydantic_core.to_json(provider_data) + b'\n'
    current_data = prices_json_path.read_bytes() if prices_json_path.exists() else None
    if json_data != current_data:
        if current_data is not None:
            diff = difflib.unified_diff(
                pretty_providers_json(current_data),
                pretty_providers_json(json_data),
                fromfile='current_prices',
                tofile='new_prices',
            )
            diff_str = ''.join(diff)
            if diff_str:
                print('Prices have the following changes:')
                print('=' * 80)
                print(diff_str)
                print('=' * 80)
            else:
                print('Prices have whitespace/dict ordering changes')

        prices_json_path.write_bytes(json_data)
        action = 'updated'
    else:
        action = 'unchanged'

    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb') as f:
        f.write(json_data)
    gz_len = len(buffer.getvalue())
    print(
        f'Prices data file {prices_json_path.relative_to(root_dir)} {action} '
        f'({pretty_size(len(json_data))}, {pretty_size(gz_len)} gzipped)'
    )


def pretty_providers_json(compact_json: bytes) -> list[str]:
    return pydantic_core.to_json(pydantic_core.from_json(compact_json), indent=2).decode().splitlines(keepends=True)


if __name__ == '__main__':
    build()
