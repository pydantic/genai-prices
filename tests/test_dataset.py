"""Collect the cross-language golden dataset into the pytest run.

`tests/dataset/extract_usages.py` generates `tests/dataset/usages.json`, which the JS suite asserts
against in `packages/js/src/__tests__/dataset.test.ts`. It is the only same-usage-same-price check
across the two implementations, and it was reachable *only* via the second line of the Makefile `test`
target - so `uv run pytest`, IDE runners and CI's own lowest-dependency-version step all skipped the
largest regression corpus in the repo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DATASET_DIR = Path(__file__).parent / 'dataset'


@pytest.fixture(scope='module')
def extract_usages_module():
    sys.path.insert(0, str(DATASET_DIR))
    try:
        import extract_usages

        yield extract_usages
    finally:
        sys.path.remove(str(DATASET_DIR))


def test_usages_dataset_is_up_to_date(extract_usages_module: object) -> None:
    current, rebuilt = extract_usages_module.rebuild_usages()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
    assert rebuilt == current, (
        'usages.json is stale. Run `python tests/dataset/extract_usages.py` to regenerate it, check the '
        'diff, and commit it - the JS suite asserts against this file.'
    )


def test_main_reports_current_dataset(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    current: list[dict[str, object]] = [{'body': {'file': 'recorded.json'}}]
    monkeypatch.setattr(extract_usages_module, 'rebuild_usages', lambda: (current, current))

    assert extract_usages_module.main() is None  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert capsys.readouterr().out == 'usages.json is up to date.\n'


def test_main_rejects_stale_dataset_without_writing(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current: list[dict[str, object]] = []
    rebuilt: list[dict[str, object]] = [{'body': {'file': 'recorded.json'}}]
    usages_file = tmp_path / 'usages.json'
    usages_file.write_text('unchanged')
    monkeypatch.setattr(extract_usages_module, 'this_dir', tmp_path)
    monkeypatch.setattr(extract_usages_module, 'rebuild_usages', lambda: (current, rebuilt))

    with pytest.raises(AssertionError, match='usages.json is out of date'):
        extract_usages_module.main(write=False)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

    assert usages_file.read_text() == 'unchanged'


def test_main_writes_a_stale_dataset(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current: list[dict[str, object]] = []
    rebuilt: list[dict[str, object]] = [{'body': {'file': 'recorded.json'}}]
    monkeypatch.setattr(extract_usages_module, 'this_dir', tmp_path)
    monkeypatch.setattr(extract_usages_module, 'rebuild_usages', lambda: (current, rebuilt))

    with pytest.raises(AssertionError, match='usages.json updated'):
        extract_usages_module.main()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

    assert json.loads((tmp_path / 'usages.json').read_text()) == rebuilt
