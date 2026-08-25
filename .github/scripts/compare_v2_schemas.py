"""Compare published v2 schemas while ignoring documentation-only descriptions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def strip_descriptions(node: Any, *, property_map: bool = False) -> Any:
    """Remove schema description annotations without removing properties named `description`."""
    if isinstance(node, dict):
        return {
            key: strip_descriptions(value, property_map=key == 'properties')
            for key, value in node.items()
            if property_map or key != 'description'
        }
    if isinstance(node, list):
        return [strip_descriptions(item) for item in node]
    return node


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
