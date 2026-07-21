from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypedDict

import httpx2
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .utils import pretty_size, root_dir

MODELS_DEV_MODELS_URL = 'https://models.dev/models.json'
_MAX_MODELS_SIZE = 5 * 1024 * 1024
_MODEL_METADATA_PATH = root_dir / 'packages' / 'python' / 'genai_prices' / '_model_metadata.json'
_MIN_MODEL_COUNT = 100
_MIN_CONTEXT_COUNT = 100
_MAX_REMOVAL_FRACTION = 0.2
_MAX_CHANGED_LIMIT_FRACTION = 0.5


class ModelMetadataSource(Protocol):
    """Build-time source for provider-independent model metadata."""

    def fetch(self) -> bytes: ...


@dataclass(frozen=True)
class ModelsDevModelSource:
    """Stream the public models.dev model catalog with a bounded response size."""

    url: str = MODELS_DEV_MODELS_URL
    max_size: int = _MAX_MODELS_SIZE

    def fetch(self) -> bytes:
        chunks: list[bytes] = []
        size = 0
        with httpx2.stream(
            'GET',
            self.url,
            follow_redirects=True,
            timeout=httpx2.Timeout(timeout=30, connect=10),
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.max_size:
                    raise ValueError(f'models.dev model catalog is larger than the {pretty_size(self.max_size)} limit')
                chunks.append(chunk)
        return b''.join(chunks)


class _ModelsDevLimit(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    context: int | None = Field(default=None, ge=0)
    input: int | None = Field(default=None, ge=0)
    output: int | None = Field(default=None, ge=0)


class _ModelsDevModel(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    id: str
    limit: _ModelsDevLimit | None = None


_models_dev_models_schema = TypeAdapter(dict[str, _ModelsDevModel])

ModelLimitsData = list[int | None]


class ModelMetadataData(TypedDict):
    version: Literal[1]
    source: str
    source_sha256: str
    models: dict[str, ModelLimitsData]


def normalize_model_metadata(data: bytes) -> ModelMetadataData:
    """Normalize the provider-independent models.dev catalog."""
    catalog = _models_dev_models_schema.validate_json(data)

    models: dict[str, ModelLimitsData] = {}
    model_ids: set[str] = set()
    for key, model in catalog.items():
        _check_embedded_id(key, model.id)
        normalized_id = _normalize_id(key)
        _check_collision(model_ids, normalized_id)
        if limits := _normalize_limits(model.limit):
            models[normalized_id] = limits

    models = dict(sorted(models.items()))
    source_sha256 = hashlib.sha256(json.dumps(models, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {
        'version': 1,
        'source': MODELS_DEV_MODELS_URL,
        'source_sha256': source_sha256,
        'models': models,
    }


def update_model_metadata(
    source: ModelMetadataSource | None = None,
    *,
    output_path: Path = _MODEL_METADATA_PATH,
    enforce_safety: bool = True,
) -> None:
    """Fetch models.dev and update the committed model metadata snapshot."""
    source = source or ModelsDevModelSource()
    normalized = normalize_model_metadata(source.fetch())

    previous = json.loads(output_path.read_bytes()) if output_path.exists() else None
    if enforce_safety:
        _validate_metadata_update(previous, normalized)
    summary = _change_summary(previous, normalized)
    output_path.write_text(_render_metadata(normalized))

    counts = _metadata_counts(normalized)
    print(summary)
    print(
        f'Model metadata successfully written to {output_path} '
        f'({counts.models} models, {counts.contexts} context limits)'
    )


def _normalize_limits(limits: _ModelsDevLimit | None) -> ModelLimitsData | None:
    if limits is None:
        return None
    values = [_positive_or_none(limits.context), _positive_or_none(limits.input), _positive_or_none(limits.output)]
    return values if any(value is not None for value in values) else None


def _render_metadata(data: ModelMetadataData) -> str:
    lines = [
        '{',
        f'  "version": {data["version"]},',
        f'  "source": {json.dumps(data["source"], ensure_ascii=False)},',
        f'  "source_sha256": {json.dumps(data["source_sha256"])},',
        '  "models": {',
    ]
    models = data['models']
    for index, (model_id, limits) in enumerate(models.items()):
        comma = ',' if index < len(models) - 1 else ''
        lines.append(f'    {json.dumps(model_id, ensure_ascii=False)}: {json.dumps(limits, ensure_ascii=False)}{comma}')
    lines.extend(('  }', '}'))
    return '\n'.join(lines) + '\n'


def _positive_or_none(value: int | None) -> int | None:
    return value if value is not None and value > 0 else None


def _normalize_id(value: str) -> str:
    return value.strip().lower()


def _check_embedded_id(key: str, embedded_id: str) -> None:
    if key != embedded_id:
        raise ValueError(f'model ID {embedded_id!r} does not match its key {key!r}')


def _check_collision(items: set[str], normalized_id: str) -> None:
    if normalized_id in items:
        raise ValueError(f'case-insensitive model ID collision for {normalized_id!r}')
    items.add(normalized_id)


@dataclass(frozen=True)
class _MetadataCounts:
    models: int
    contexts: int


def _metadata_counts(data: ModelMetadataData) -> _MetadataCounts:
    models = data['models']
    return _MetadataCounts(
        models=len(models),
        contexts=sum(limits[0] is not None for limits in models.values()),
    )


def _validate_metadata_update(previous: ModelMetadataData | None, current: ModelMetadataData) -> None:
    current_counts = _metadata_counts(current)
    if current_counts.models < _MIN_MODEL_COUNT:
        raise ValueError(
            f'models.dev update has only {current_counts.models} models, expected at least {_MIN_MODEL_COUNT}'
        )
    if current_counts.contexts < _MIN_CONTEXT_COUNT:
        raise ValueError(
            f'models.dev update has only {current_counts.contexts} context limits, '
            f'expected at least {_MIN_CONTEXT_COUNT}'
        )
    if previous is None:
        return

    previous_counts = _metadata_counts(previous)
    if current_counts.models < previous_counts.models * (1 - _MAX_REMOVAL_FRACTION):
        raise ValueError(
            f'models.dev update removes too many models: {previous_counts.models} -> {current_counts.models}'
        )
    if current_counts.contexts < previous_counts.contexts * (1 - _MAX_REMOVAL_FRACTION):
        raise ValueError(
            f'models.dev update removes too many context limits: '
            f'{previous_counts.contexts} -> {current_counts.contexts}'
        )

    previous_models = previous['models']
    current_models = current['models']
    removed = previous_models.keys() - current_models.keys()
    if len(removed) > len(previous_models) * _MAX_REMOVAL_FRACTION:
        raise ValueError(f'models.dev update removes too many model IDs: {len(removed)} of {len(previous_models)}')
    shared = previous_models.keys() & current_models.keys()
    changed = sum(previous_models[key] != current_models[key] for key in shared)
    if shared and changed > len(shared) * _MAX_CHANGED_LIMIT_FRACTION:
        raise ValueError(f'models.dev update changes too many model limits: {changed} of {len(shared)}')


def _change_summary(previous: ModelMetadataData | None, current: ModelMetadataData) -> str:
    if previous is None:
        return 'Model metadata changes: initial snapshot'
    previous_models = previous['models']
    current_models = current['models']
    added = current_models.keys() - previous_models.keys()
    removed = previous_models.keys() - current_models.keys()
    shared = previous_models.keys() & current_models.keys()
    changed = sum(previous_models[key] != current_models[key] for key in shared)
    return f'Model metadata changes: {len(added)} added, {len(removed)} removed, {changed} limits changed'
