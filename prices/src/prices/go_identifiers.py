from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict, cast

from .utils import root_dir

_GO_IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_GO_AST_HELPER = Path(__file__).with_name('go_identifiers_ast.go')
_GO_KEYWORDS = frozenset(
    {
        'break',
        'case',
        'chan',
        'const',
        'continue',
        'default',
        'defer',
        'else',
        'fallthrough',
        'for',
        'func',
        'go',
        'goto',
        'if',
        'import',
        'interface',
        'map',
        'package',
        'range',
        'return',
        'select',
        'struct',
        'switch',
        'type',
        'var',
    }
)


class _GoDeclaration(TypedDict):
    path: str
    kind: str
    name: str


def go_usage_key_identifier(usage_key: str) -> str:
    """Return the generated Go constant name for a usage key."""
    parts: list[str] = []
    for part in usage_key.split('_'):
        if not part:
            parts.append('_')
        elif part[0].isdigit():
            parts.append(part.upper())
        else:
            parts.append(part[0].upper() + part[1:])
    return 'Usage' + ''.join(parts)


def validate_go_usage_key_identifiers(usage_keys: Iterable[str]) -> None:
    """Reject generated Go names that are invalid, ambiguous, or already declared."""
    package_identifiers = go_package_level_identifiers()
    generated_identifiers: dict[str, str] = {}
    for usage_key in usage_keys:
        identifier = go_usage_key_identifier(usage_key)
        if not _GO_IDENTIFIER_PATTERN.fullmatch(identifier):
            raise ValueError(f'Invalid generated Go identifier {identifier!r} for usage key {usage_key!r}')
        if identifier in _GO_KEYWORDS:
            raise ValueError(f'Generated Go identifier {identifier!r} for usage key {usage_key!r} is a keyword')

        if previous_usage_key := generated_identifiers.get(identifier):
            raise ValueError(
                f'Generated Go identifier collision: {previous_usage_key!r} and {usage_key!r} both map to {identifier}'
            )
        generated_identifiers[identifier] = usage_key

        if identifier in package_identifiers:
            raise ValueError(
                f'Generated Go identifier {identifier!r} for usage key {usage_key!r} '
                'collides with an existing package-level declaration'
            )


def go_package_level_identifiers() -> frozenset[str]:
    """Read non-generated package-level identifiers from the Go package using Go's parser."""
    go_paths = sorted((root_dir / 'packages' / 'go').glob('*.go'))
    result = subprocess.run(
        ['go', 'run', str(_GO_AST_HELPER), '--', *(str(path) for path in go_paths)],
        cwd=root_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    declarations = cast(list[_GoDeclaration], json.loads(result.stdout))
    return frozenset(
        declaration['name']
        for declaration in declarations
        if not (Path(declaration['path']).name == 'data_units.go' and declaration['kind'] == 'const')
    )
