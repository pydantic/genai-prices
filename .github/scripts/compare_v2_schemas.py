"""Compare published v2 schemas while ignoring documentation-only descriptions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_MAP_KEYS = {'$defs', 'definitions', 'dependentSchemas', 'patternProperties', 'properties'}
SCHEMA_LIST_KEYS = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}
SCHEMA_VALUE_KEYS = {
    'additionalProperties',
    'contains',
    'contentSchema',
    'else',
    'if',
    'items',
    'not',
    'propertyNames',
    'then',
    'unevaluatedItems',
    'unevaluatedProperties',
}


def strip_descriptions(node: Any) -> Any:
    """Remove schema description annotations without removing properties named `description`."""
    if not isinstance(node, dict):
        return node

    stripped: dict[str, Any] = {}
    for key, value in node.items():
        if key == 'description':
            continue
        if key in SCHEMA_MAP_KEYS and isinstance(value, dict):
            stripped[key] = {name: strip_descriptions(schema) for name, schema in value.items()}
        elif key in SCHEMA_LIST_KEYS and isinstance(value, list):
            stripped[key] = [strip_descriptions(schema) for schema in value]
        elif key in SCHEMA_VALUE_KEYS:
            stripped[key] = strip_descriptions(value)
        else:
            # Instance-valued keywords such as const, enum, default, and examples are contract data.
            stripped[key] = value
    return stripped


def schemas_match(head: Any, base: Any) -> bool:
    """Compare schemas with JSON-type-aware canonical serialization."""

    def canonical(value: Any) -> str:
        return json.dumps(strip_descriptions(value), sort_keys=True, separators=(',', ':'))

    return canonical(head) == canonical(base)


def main(head_path: Path, base_path: Path) -> None:
    with head_path.open() as f:
        head = json.load(f)
    with base_path.open() as f:
        base = json.load(f)
    if not schemas_match(head, base):
        raise SystemExit(1)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: compare_v2_schemas.py <head-schema> <base-schema>')
    main(Path(sys.argv[1]), Path(sys.argv[2]))
