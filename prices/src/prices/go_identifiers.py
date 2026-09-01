from __future__ import annotations

import re
from collections.abc import Iterable

from .utils import root_dir

_GO_IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_GO_PACKAGE_PATTERN = re.compile(r'^package\s+([A-Za-z_][A-Za-z0-9_]*)\s*$', re.MULTILINE)
_GO_DECLARATION_PATTERN = re.compile(r'^(?:const|type|var)\s+([A-Za-z_][A-Za-z0-9_]*)\b')
_GO_FUNCTION_PATTERN = re.compile(r'^func\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^]]+\]\s*)?\(')
_GO_BLOCK_PATTERN = re.compile(r'^(?:const|type|var)\s*\($')
_GO_BLOCK_MEMBER_PATTERN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\b')
_GENERATED_UNIT_CONSTANT_PATTERN = re.compile(r'^(Usage[A-Za-z0-9_]*)\s+UsageKey\s*=\s*"[A-Za-z][A-Za-z0-9_]*"$')
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
    """Read non-generated package-level identifiers from the Go package."""
    identifiers: set[str] = set()
    go_package_dir = root_dir / 'packages' / 'go'
    for path in sorted(go_package_dir.glob('*.go')):
        source = path.read_text()
        package_match = _GO_PACKAGE_PATTERN.search(source)
        if package_match is None or package_match.group(1) != 'genai_prices':
            continue
        identifiers.update(_go_file_package_level_identifiers(source, exclude_generated=path.name == 'data_units.go'))
    return frozenset(identifiers)


def _go_file_package_level_identifiers(source: str, *, exclude_generated: bool) -> set[str]:
    identifiers: set[str] = set()
    in_declaration_block = False
    for line in source.splitlines():
        stripped = line.strip()
        if in_declaration_block:
            if stripped == ')':
                in_declaration_block = False
                continue
            if match := _GO_BLOCK_MEMBER_PATTERN.match(stripped):
                if exclude_generated and _GENERATED_UNIT_CONSTANT_PATTERN.fullmatch(stripped):
                    continue
                identifiers.add(match.group(1))
            continue

        if _GO_BLOCK_PATTERN.fullmatch(stripped):
            in_declaration_block = True
        elif match := _GO_DECLARATION_PATTERN.match(stripped):
            identifiers.add(match.group(1))
        elif match := _GO_FUNCTION_PATTERN.match(stripped):
            identifiers.add(match.group(1))
    return identifiers
