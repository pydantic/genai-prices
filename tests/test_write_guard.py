"""Tests for `prices.write_guard`, which stops importers from overwriting tracked provider YAML with a truncated catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from prices.write_guard import ALLOW_MODEL_COUNT_DROP_ENV, check_model_count


def write_provider(path: Path, model_count: int) -> None:
    models = ''.join(
        f'  - id: model-{i}\n    match:\n      equals: model-{i}\n    prices:\n      input_mtok: 1\n'
        for i in range(model_count)
    )
    path.write_text(f'id: guarded\nname: Guarded\napi_pattern: https://guarded\nmodels:\n{models}')


def test_missing_file_is_not_checked(tmp_path: Path):
    check_model_count(tmp_path / 'new.yml', 0, source='test')


def test_zero_models_refuses_to_overwrite(tmp_path: Path):
    path = tmp_path / 'guarded.yml'
    write_provider(path, 4)

    with pytest.raises(SystemExit, match='test returned no priced models but guarded.yml has 4; refusing to write'):
        check_model_count(path, 0, source='test')


@pytest.mark.parametrize('override', [None, '0', 'false'])
def test_sharp_drop_refuses_to_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: str | None):
    if override is None:
        monkeypatch.delenv(ALLOW_MODEL_COUNT_DROP_ENV, raising=False)
    else:
        monkeypatch.setenv(ALLOW_MODEL_COUNT_DROP_ENV, override)
    path = tmp_path / 'guarded.yml'
    write_provider(path, 10)

    with pytest.raises(SystemExit, match=r'test returned 4 priced models but guarded.yml has 10; refusing to write'):
        check_model_count(path, 4, source='test')


@pytest.mark.parametrize('new_count', [5, 10, 12])
def test_modest_changes_are_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_count: int):
    monkeypatch.delenv(ALLOW_MODEL_COUNT_DROP_ENV, raising=False)
    path = tmp_path / 'guarded.yml'
    write_provider(path, 10)

    check_model_count(path, new_count, source='test')


def test_sharp_drop_can_be_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(ALLOW_MODEL_COUNT_DROP_ENV, '1')
    path = tmp_path / 'guarded.yml'
    write_provider(path, 10)

    check_model_count(path, 1, source='test')
