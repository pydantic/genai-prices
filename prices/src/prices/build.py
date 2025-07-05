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
from pydantic.main import IncEx

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
    write_prices(providers, root_dir, 'data.json')
    for provider in providers:
        provider.exclude_free()
    write_prices(providers, root_dir, 'data_slim.json', slim=True)


def write_prices(providers: list[Provider], root_dir: Path, prices_file: str, *, slim: bool = False):
    print('')
    prices_json_path = package_dir / prices_file

    data_json_schema = providers_schema.json_schema(mode='serialization')
    data_json_schema = simplify_json_schema(data_json_schema)
    if slim:
        # delete Provider fields
        data_json_schema['$defs']['Provider']['properties'].pop('pricing_urls')
        data_json_schema['$defs']['Provider']['properties'].pop('description')
        data_json_schema['$defs']['Provider']['properties'].pop('price_comments')
        # delete ModelInfo fields
        data_json_schema['$defs']['ModelInfo']['properties'].pop('name')
        data_json_schema['$defs']['ModelInfo']['properties'].pop('description')
        data_json_schema['$defs']['ModelInfo']['properties'].pop('price_comments')

    prices_json_schema_path = prices_json_path.with_suffix('.schema.json')
    prices_json_schema_path.write_bytes(pydantic_core.to_json(data_json_schema, indent=2) + b'\n')
    print(f'Prices data JSON schema written to {prices_json_schema_path.relative_to(root_dir)}')

    exclude: IncEx | None = None
    if slim:
        exclude = {
            '__all__': {
                'pricing_url': True,
                'description': True,
                'price_comments': True,
                'models': {'__all__': {'name', 'description', 'price_comments'}},
            }
        }

    json_data = providers_schema.dump_json(providers, by_alias=True, exclude_none=True, exclude=exclude) + b'\n'
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
