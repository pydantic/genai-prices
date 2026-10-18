from __future__ import annotations

import re
from decimal import Decimal
from itertools import takewhile
from pathlib import Path
from typing import Any, Literal, TypeVar

import httpx2

package_dir = Path(__file__).parent.parent.parent
root_dir = package_dir.parent


def pretty_size(size: int) -> str:
    if size < 1024:
        return f'{size} bytes'
    elif size < 1024 * 1024:  # pragma: no cover - reaching this branch requires an inflated generated-data fixture
        return f'{size / 1024:.2f} KB'
    else:  # pragma: no cover - reaching this branch requires a generated-data fixture larger than 1 MiB
        return f'{size / (1024 * 1024):.2f} MB'


def mtok(v: Decimal | None) -> Decimal | None:
    """Convert a token price to mtok."""
    if v is None or v == 0:
        return None
    else:
        return v * 1_000_000


def distinct_mtok(v: Decimal | None, aggregate_v: Decimal | None) -> Decimal | None:
    """Convert a token price to mtok when it is distinct from its aggregate price."""
    if v == aggregate_v:
        return None
    return mtok(v)


def fetch_markdown(url: str) -> str:
    response = httpx2.get(url, timeout=30.0)
    response.raise_for_status()
    if not response.headers.get('content-type', '').startswith('text/markdown'):
        raise RuntimeError(f'{url} returned {response.headers.get("content-type")}, not markdown')
    return response.text


def markdown_tables(markdown: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return every GFM table in `markdown` as its header cells and non-empty body rows."""
    lines = [line.strip() for line in markdown.splitlines()] + ['']
    tables: list[tuple[list[str], list[list[str]]]] = []
    for index, line in enumerate(lines[:-1]):
        if not line.startswith('|') or not re.fullmatch(r'\|(?: *:?-+:? *\|)+', lines[index + 1]):
            continue
        header = _table_cells(line)
        rows = [
            _table_cells(row_line)
            for row_line in takewhile(lambda row_line: row_line.startswith('|'), lines[index + 2 :])
        ]
        if bad := next((row for row in rows if len(row) != len(header)), None):
            raise ValueError(f'Table row has {len(bad)} cells, header has {len(header)}: {bad}')
        tables.append((header, [row for row in rows if any(row)]))
    return tables


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.removeprefix('|').removesuffix('|').split('|')]


T = TypeVar('T')


def check_unique(items: list[T]) -> list[T]:
    unique: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        s = str(item)
        if s in unique:
            duplicates.append(s)
        unique.add(s)

    if duplicates:
        raise ValueError(f'Duplicates found: {", ".join(duplicates)}')
    return items


JsonSchema = dict[str, Any]


def simplify_json_schema(schema: JsonSchema) -> JsonSchema:
    """Simplify nullable unions in JSON schema by walking the schema recursively.

    Copied partially from
    https://github.com/pydantic/pydantic-ai/blob/v0.3.2/pydantic_ai_slim/pydantic_ai/profiles/_json_schema.py
    """
    # Handle the schema based on its type / structure
    if defs := schema.get('$defs'):
        schema['$defs'] = {key: simplify_json_schema(value) for key, value in defs.items()}

    type_ = schema.get('type')
    if type_ == 'object':
        return _simplify_json_schema_object(schema)
    elif type_ == 'array':
        return _simplify_json_schema_array(schema)
    elif type_ is None:
        schema = _simplify_json_schema_union(schema, 'anyOf')
        return _simplify_json_schema_union(schema, 'oneOf')
    else:
        return schema


def _simplify_json_schema_object(schema: JsonSchema) -> JsonSchema:
    if properties := schema.get('properties'):
        handled_properties = {}
        for key, value in properties.items():
            handled_properties[key] = simplify_json_schema(value)
        schema['properties'] = handled_properties

    if (add_props := schema.get('additionalProperties')) is not None:  # pragma: no branch
        schema['additionalProperties'] = add_props if isinstance(add_props, bool) else simplify_json_schema(add_props)

    if (pat_props := schema.get('patternProperties')) is not None:  # pragma: no cover
        handled_pat_props = {}
        for key, value in pat_props.items():
            handled_pat_props[key] = simplify_json_schema(value)
        schema['patternProperties'] = handled_pat_props

    return schema


def _simplify_json_schema_array(schema: JsonSchema) -> JsonSchema:
    if prefix_items := schema.get('prefixItems'):  # pragma: no cover - provider schemas use homogeneous arrays
        schema['prefixItems'] = [simplify_json_schema(item) for item in prefix_items]

    if items := schema.get('items'):  # pragma: no branch - generated array schemas always declare items
        schema['items'] = simplify_json_schema(items)

    return schema


def _simplify_json_schema_union(schema: JsonSchema, union_kind: Literal['anyOf', 'oneOf']) -> JsonSchema:
    members = schema.get(union_kind)
    if not members:
        return schema

    handled = [simplify_json_schema(member) for member in members]

    # always remove null option from schemas
    if {'type': 'null'} in members:
        handled = [item for item in handled if item != {'type': 'null'}]
        if schema.get('default', 42) is None:  # pragma: no branch - nullable Pydantic fields have a null default
            schema.pop('default')

    if len(handled) == 1:
        # In this case, no need to retain the union
        new_schema = handled[0]
        # keys to the new schema
        for key, value in schema.items():
            if key not in new_schema and key not in {'type', 'anyOf', 'oneOf', 'default'}:
                new_schema[key] = value
        return new_schema
    else:
        schema[union_kind] = handled
        return schema
