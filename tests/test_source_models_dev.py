from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import httpx2
import pytest
from inline_snapshot import snapshot
from pydantic import ValidationError

from prices.source_models_dev import (
    MODELS_DEV_MODELS_URL,
    ModelMetadataData,
    ModelsDevModelSource,
    _change_summary,
    _validate_metadata_update,
    normalize_model_metadata,
    update_model_metadata,
)


def models_dev_catalog() -> bytes:
    return json.dumps(
        {
            'origin/test-model': {
                'id': 'origin/test-model',
                'limit': {'context': 100, 'input': 80, 'output': 20},
                'ignored': 'additive fields are allowed',
            },
            'origin/non-token-model': {
                'id': 'origin/non-token-model',
                'limit': {'context': 0, 'output': 0},
            },
            'origin/no-limit-model': {'id': 'origin/no-limit-model'},
        }
    ).encode()


def test_normalize_model_metadata():
    assert normalize_model_metadata(models_dev_catalog()) == snapshot(
        {
            'version': 1,
            'source': 'https://models.dev/models.json',
            'source_sha256': '17b9a1b0cd4bb8e6565354c03f53ef1a562b5b6485c4aafb0814509d00997f81',
            'models': {'origin/test-model': [100, 80, 20]},
        }
    )


def test_normalize_model_metadata_rejects_embedded_id_mismatch():
    data = json.loads(models_dev_catalog())
    data['origin/test-model']['id'] = 'origin/other-model'

    with pytest.raises(ValueError, match='does not match its key'):
        normalize_model_metadata(json.dumps(data).encode())


def test_normalize_model_metadata_rejects_negative_limits():
    data = json.loads(models_dev_catalog())
    data['origin/test-model']['limit']['context'] = -1

    with pytest.raises(ValidationError):
        normalize_model_metadata(json.dumps(data).encode())


def test_normalize_model_metadata_rejects_case_insensitive_collisions():
    data = json.loads(models_dev_catalog())
    data['ORIGIN/TEST-MODEL'] = {
        'id': 'ORIGIN/TEST-MODEL',
        'limit': {'context': 100},
    }

    with pytest.raises(ValueError, match='case-insensitive model ID collision'):
        normalize_model_metadata(json.dumps(data).encode())


def large_metadata() -> ModelMetadataData:
    return {
        'version': 1,
        'source': 'test',
        'source_sha256': '0' * 64,
        'models': {f'origin/model-{index}': [100, None, 20] for index in range(150)},
    }


def test_update_safety_accepts_expected_catalog():
    metadata = large_metadata()

    _validate_metadata_update(None, metadata)
    _validate_metadata_update(metadata, metadata)


def test_update_safety_rejects_small_catalogs_and_context_removal():
    previous = large_metadata()
    too_few_models = copy.deepcopy(previous)
    too_few_models['models'] = dict(list(too_few_models['models'].items())[:99])
    with pytest.raises(ValueError, match='only 99 models'):
        _validate_metadata_update(None, too_few_models)

    too_few_contexts = copy.deepcopy(previous)
    for limits in list(too_few_contexts['models'].values())[:51]:
        limits[0] = None
    with pytest.raises(ValueError, match='only 99 context limits'):
        _validate_metadata_update(previous, too_few_contexts)

    removed_models = copy.deepcopy(previous)
    for model_id in list(removed_models['models'])[:31]:
        del removed_models['models'][model_id]
    with pytest.raises(ValueError, match='removes too many models'):
        _validate_metadata_update(previous, removed_models)


def test_update_safety_rejects_replaced_ids_and_mass_limit_changes():
    previous = large_metadata()
    replaced_ids = copy.deepcopy(previous)
    for model_id in list(replaced_ids['models'])[:31]:
        limits = replaced_ids['models'].pop(model_id)
        replaced_ids['models'][f'replacement-{model_id}'] = limits
    with pytest.raises(ValueError, match='removes too many model IDs'):
        _validate_metadata_update(previous, replaced_ids)

    changed_limits = copy.deepcopy(previous)
    for limits in list(changed_limits['models'].values())[:76]:
        assert limits[0] is not None
        limits[0] += 1
    with pytest.raises(ValueError, match='changes too many model limits'):
        _validate_metadata_update(previous, changed_limits)


@dataclass(frozen=True)
class StaticModelSource:
    data: bytes

    def fetch(self) -> bytes:
        return self.data


def test_update_model_metadata_writes_one_artifact(tmp_path: Path):
    output_path = tmp_path / '_model_metadata.json'

    update_model_metadata(
        StaticModelSource(models_dev_catalog()),
        output_path=output_path,
        enforce_safety=False,
    )

    metadata = json.loads(output_path.read_bytes())
    assert metadata['source'] == MODELS_DEV_MODELS_URL
    assert metadata['source_sha256']
    rendered = output_path.read_bytes()
    assert b'"origin/test-model": [100, 80, 20]' in rendered

    update_model_metadata(
        StaticModelSource(models_dev_catalog()),
        output_path=output_path,
        enforce_safety=False,
    )
    assert output_path.read_bytes() == rendered


def test_streaming_source_enforces_response_limit(monkeypatch: pytest.MonkeyPatch):
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        def iter_bytes(self) -> list[bytes]:
            return [b'12', b'34']

    def stream(*_args: object, **_kwargs: object) -> Response:
        return Response()

    monkeypatch.setattr(httpx2, 'stream', stream)

    with pytest.raises(ValueError, match='larger than the 3 bytes limit'):
        ModelsDevModelSource(max_size=3).fetch()


def test_change_summary():
    previous = large_metadata()
    current = copy.deepcopy(previous)
    current['models']['origin/new'] = [100, None, 20]
    del current['models']['origin/model-0']
    current['models']['origin/model-1'] = [101, None, 20]

    assert _change_summary(None, current) == 'Model metadata changes: initial snapshot'
    assert _change_summary(previous, current) == snapshot(
        'Model metadata changes: 1 added, 1 removed, 1 limits changed'
    )
