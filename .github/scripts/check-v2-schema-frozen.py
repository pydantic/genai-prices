"""Fail when a PR changes the published v2 schemas in a way that is not purely additive.

The unit-derived definitions (price keys and extractor destinations, both generated from
`prices/units.yml`) are byte-frozen: widening them silently under-prices usage for clients that
haven't upgraded, so a new unit requires v3 instead - see specs/data-driven-unit-registry/.

Everything else may only grow: new definitions and new optional properties are allowed, but an
existing definition, property, `required` list or `additionalProperties` setting must not change.

Usage: check-v2-schema-frozen.py <base-sha>
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCHEMAS = ('prices/new_data/v2/data.schema.json', 'prices/new_data/v2/data_slim.schema.json')
# `$defs` generated from prices/units.yml. Any change here is a unit change and needs v3.
UNIT_DEFS = ('ModelPrice', 'UsageExtractorMapping')
# Per-definition keys that must not change. `description`/`title` are docs and may be reworded.
FROZEN_DEF_KEYS = ('type', 'required', 'additionalProperties', 'enum', 'anyOf', 'oneOf', 'allOf', '$ref', 'items')

JsonObject = dict[str, object]


def load_base(base_sha: str, path: str) -> JsonObject:
    raw = subprocess.check_output(['git', 'show', f'{base_sha}:{path}'])
    return json.loads(raw)


def as_object(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def compare(base: JsonObject, head: JsonObject) -> list[str]:
    errors: list[str] = []
    for key in base.keys() | head.keys():
        if key != '$defs' and base.get(key) != head.get(key):
            errors.append(f'top-level `{key}` changed')

    base_defs, head_defs = as_object(base.get('$defs')), as_object(head.get('$defs'))
    for name, base_def_value in base_defs.items():
        if name not in head_defs:
            errors.append(f'`$defs.{name}` was removed')
            continue
        base_def, head_def = as_object(base_def_value), as_object(head_defs[name])
        if name in UNIT_DEFS:
            if base_def != head_def:
                errors.append(f'`$defs.{name}` is generated from prices/units.yml and changed: a unit change needs v3')
            continue
        for key in FROZEN_DEF_KEYS:
            if base_def.get(key) != head_def.get(key):
                errors.append(f'`$defs.{name}.{key}` changed')
        base_props, head_props = as_object(base_def.get('properties')), as_object(head_def.get('properties'))
        for prop, prop_schema in base_props.items():
            if head_props.get(prop) != prop_schema:
                errors.append(f'existing property `$defs.{name}.properties.{prop}` was removed or changed')
    return errors


def main(base_sha: str) -> int:
    failed = False
    for path in SCHEMAS:
        head = json.loads(Path(path).read_text())
        for error in compare(load_base(base_sha, path), head):
            print(
                f'::error file={path}::{error}. The v2 schema may only grow additively - see specs/data-driven-unit-registry/.'
            )
            failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
