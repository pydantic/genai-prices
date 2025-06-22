from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, TypeVar

package_dir = Path(__file__).parent.parent.parent


def pretty_size(size: int) -> str:
    if size < 1024:
        return f'{size} bytes'
    elif size < 1024 * 1024:
        return f'{size / 1024:.2f} KB'
    else:
        return f'{size / (1024 * 1024):.2f} MB'


def mtok(v: Decimal | None) -> Decimal | None:
    """Convert a token price to mtok."""
    if v is None:
        return None
    else:
        return v * 1_000_000


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

    if (add_props := schema.get('additionalProperties')) is not None:
        schema['additionalProperties'] = add_props if isinstance(add_props, bool) else simplify_json_schema(add_props)

    if (pat_props := schema.get('patternProperties')) is not None:
        handled_pat_props = {}
        for key, value in pat_props.items():
            handled_pat_props[key] = simplify_json_schema(value)
        schema['patternProperties'] = handled_pat_props

    return schema


def _simplify_json_schema_array(schema: JsonSchema) -> JsonSchema:
    if prefix_items := schema.get('prefixItems'):
        schema['prefixItems'] = [simplify_json_schema(item) for item in prefix_items]

    if items := schema.get('items'):
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
        if schema.get('default', 42) is None:
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
