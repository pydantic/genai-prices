"""Filter a price-check workflow's safe file list to its current providers."""

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints, TypeAdapter
from pydantic_core import ValidationError

from scripts.price_check_sources import load_provider_sources

_TARGETED_SOURCE = 'agentic-model-price-check.md'
_WEEKLY_SOURCE = 'agentic-price-check.md'
_DISCOVERY_PROVIDER_ID = '_discovery'
_PROVIDER_FILE_PREFIX = 'prices/providers/'


class _ManifestProvider(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    file: Annotated[StrictStr, StringConstraints(min_length=1)]


class _WeeklyManifest(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    providers: list[_ManifestProvider]


class _PendingBackfillRow(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    request_id: Annotated[StrictStr, StringConstraints(min_length=1)]
    target_model: Annotated[StrictStr, StringConstraints(min_length=1)]
    provider_id: Annotated[StrictStr, StringConstraints(min_length=1)]


_PENDING_ROWS = TypeAdapter(list[_PendingBackfillRow])


def _is_provider_yaml(path: str) -> bool:
    return path.startswith(_PROVIDER_FILE_PREFIX) and path.endswith(('.yml', '.yaml'))


def _provider_files_from_weekly_manifest(root: Path, known_files: set[str]) -> set[str]:
    manifest_path = root / '.github/agentic-price-check-providers.yml'
    raw: object = yaml.safe_load(manifest_path.read_text())
    manifest = _WeeklyManifest.model_validate(raw)
    files = {provider.file for provider in manifest.providers}
    unknown_files = files - known_files
    if unknown_files:
        raise ValueError(f'Weekly manifest references unknown provider files: {sorted(unknown_files)}')
    return files


def _pending_provider_ids(pending_backfill: object, known_ids: set[str]) -> set[str]:
    try:
        rows = _PENDING_ROWS.validate_python(pending_backfill, strict=True)
    except ValidationError as exc:
        raise ValueError('Pending price-check backfill rows are invalid') from exc

    provider_ids = {row.provider_id for row in rows}
    unknown_ids = provider_ids - known_ids - {_DISCOVERY_PROVIDER_ID}
    if unknown_ids:
        raise ValueError(f'Pending price-check backfill has unknown provider IDs: {sorted(unknown_ids)}')
    return provider_ids


def allowed_price_check_files(
    root: Path,
    allowed_files: list[str],
    workflow_source: str,
    pending_backfill: object,
) -> list[str]:
    """Narrow weekly provider writes while preserving the workflow's safe allowlist."""
    if workflow_source not in {_TARGETED_SOURCE, _WEEKLY_SOURCE}:
        raise ValueError(f'Unknown price-check workflow source: {workflow_source!r}')
    if any(not path for path in allowed_files):
        raise ValueError('Price-check allowed files must be non-empty paths')
    if workflow_source == _TARGETED_SOURCE:
        return allowed_files.copy()

    provider_sources = load_provider_sources(root)
    files_by_id: dict[str, str] = {}
    files_by_path: dict[str, str] = {}
    for provider in provider_sources:
        if provider.id in files_by_id or provider.file in files_by_path:
            raise ValueError('Provider source IDs and file paths must be unique')
        files_by_id[provider.id] = provider.file
        files_by_path[provider.file] = provider.id

    ordinary_files = _provider_files_from_weekly_manifest(root, set(files_by_path))
    pending_ids = _pending_provider_ids(pending_backfill, set(files_by_id))
    if _DISCOVERY_PROVIDER_ID in pending_ids:
        allowed_provider_files = set(files_by_path)
    else:
        allowed_provider_files = ordinary_files | {files_by_id[provider_id] for provider_id in pending_ids}

    return [path for path in allowed_files if not _is_provider_yaml(path) or path in allowed_provider_files]
