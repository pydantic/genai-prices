from __future__ import annotations

import sys
from collections.abc import Sequence
from functools import lru_cache
from importlib import import_module
from types import ModuleType
from typing import Any

PROGRAM_NAME = 'genai-prices'
_OPTIONAL_CLI_PACKAGES = {'pydantic_settings', 'rich', 'rich_argparse'}


def _missing_cli_dependency_message(package: str) -> str:
    return (
        f'Optional CLI dependency {package!r} is not installed. '
        'Install CLI extras with: pip install "genai-prices[cli]"'
    )


@lru_cache
def _load_impl() -> ModuleType:
    try:
        return import_module('genai_prices._cli_impl')
    except ModuleNotFoundError as exc:
        package = (exc.name or '').split('.')[0]
        if package in _OPTIONAL_CLI_PACKAGES:
            raise RuntimeError(_missing_cli_dependency_message(package)) from exc
        raise


def cli() -> int:  # pragma: no cover
    """Run the CLI."""
    try:
        return _load_impl().cli()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


def cli_logic(args_list: Sequence[str] | None = None) -> int:
    try:
        return _load_impl().cli_logic(args_list)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1


def __getattr__(name: str) -> Any:
    if name.startswith('__'):
        raise AttributeError(name)
    return getattr(_load_impl(), name)
