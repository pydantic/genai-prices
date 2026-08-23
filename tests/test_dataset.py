"""Collect the cross-language golden dataset into the pytest run.

`tests/dataset/extract_usages.py` generates `tests/dataset/usages.json`, which the JS suite asserts
against in `packages/js/src/__tests__/dataset.test.ts`. It is the only same-usage-same-price check
across the two implementations, and it was reachable *only* via the second line of the Makefile `test`
target - so `uv run pytest`, IDE runners and CI's own lowest-dependency-version step all skipped the
largest regression corpus in the repo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

DATASET_DIR = Path(__file__).parent / 'dataset'


@pytest.fixture(scope='module')
def extract_usages_module():
    # The dataset scripts import their sibling `utils` by bare name, so the directory has to be on the
    # path before importing.
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
