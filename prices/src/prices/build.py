from __future__ import annotations

import difflib
import gzip
import io
from decimal import Decimal
from operator import attrgetter
from pathlib import Path
from typing import Any, cast

import pydantic_core
import ruamel.yaml
from pydantic import ValidationError

from .types import Provider, providers_schema
from .utils import package_dir, pretty_size, simplify_json_schema


def decimal_constructor(loader: ruamel.yaml.SafeLoader, node: ruamel.yaml.ScalarNode) -> Decimal:
    s = cast(str, loader.construct_scalar(node))  # pyright: ignore[reportUnknownMemberType]
    return Decimal(s)


yaml = ruamel.yaml.YAML(typ='safe')
yaml.constructor.add_constructor('tag:yaml.org,2002:float', decimal_constructor)  # pyright: ignore[reportUnknownMemberType]


def build():
    """Build providers/.schema.json and data.json and data_schema.json."""
    root_dir = package_dir.parent
    # write the schema JSON file used by the yaml language server
    schema_json_path = package_dir / 'providers' / '.schema.json'
    json_schema = Provider.model_json_schema()
    json_schema = simplify_json_schema(json_schema)
    schema_json_path.write_bytes(pydantic_core.to_json(json_schema, indent=2) + b'\n')
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
    write_prices(
        providers,
        root_dir,
        'data.json',
    )


def write_prices(providers: list[Provider], root_dir: Path, prices_file: str):
    prices_json_path = package_dir / prices_file

    data_json_schema = providers_schema.json_schema(mode='serialization')
    data_json_schema = simplify_json_schema(data_json_schema)
    prices_json_schema_path = prices_json_path.with_suffix('.schema.json')
    prices_json_schema_path.write_bytes(pydantic_core.to_json(data_json_schema, indent=2) + b'\n')
    print(f'Prices data JSON schema written to {prices_json_schema_path.relative_to(root_dir)}')

    if prices_json_path.exists():
        try:
            current_prices = providers_schema.validate_json(prices_json_path.read_bytes())
        except ValidationError as e:
            print(f'warning, error loading current prices:\n{e}')
            current_prices = None
    else:
        current_prices = None

    json_data = providers_schema.dump_json(providers, by_alias=True, exclude_none=True) + b'\n'
    if json_data != prices_json_path.read_bytes():
        if current_prices is not None:
            diff = difflib.unified_diff(
                pretty_providers_json(current_prices),
                pretty_providers_json(providers),
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

        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode='wb') as f:
            f.write(json_data)
        gz_len = len(buffer.getvalue())

        print(
            f'Prices data written to {prices_json_path.relative_to(root_dir)}'
            f' ({pretty_size(prices_json_path.stat().st_size)}, {pretty_size(gz_len)} gzipped)'
        )
    else:
        print('Prices data unchanged')


def pretty_providers_json(providers: list[Provider]) -> list[str]:
    return (
        providers_schema.dump_json(providers, by_alias=True, exclude_none=True, indent=2)
        .decode()
        .splitlines(keepends=True)
    )
