from __future__ import annotations


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
