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
from typing import Any, cast

import pytest

from genai_prices.types import Provider, UsageExtractor, UsageExtractorMapping

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


def test_rebuild_usages_falls_back_to_current_dataset(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extract_usages = cast(Any, extract_usages_module)
    (tmp_path / 'usages.json').write_text('[]')
    monkeypatch.setattr(extract_usages, 'this_dir', tmp_path)
    monkeypatch.setattr(extract_usages, 'raw_bodies_path', tmp_path / 'missing-raw-bodies.json')

    assert extract_usages.rebuild_usages() == ([], [])


def test_usage_consistency_accepts_contained_and_overlapping_details(extract_usages_module: object) -> None:
    extract_usages = cast(Any, extract_usages_module)

    extract_usages.check_usage_consistency(
        {
            'input_tokens': 10,
            'input_text_tokens': 6,
            'input_audio_tokens': 4,
            'cache_read_tokens': 7,
            'cache_audio_read_tokens': 4,
        }
    )


def test_usage_consistency_rejects_missing_aggregate(extract_usages_module: object) -> None:
    extract_usages = cast(Any, extract_usages_module)

    with pytest.raises(AssertionError, match=r'output_reasoning_tokens \(6\) is missing aggregate output_tokens'):
        extract_usages.check_usage_consistency({'output_reasoning_tokens': 6})


def test_usage_consistency_rejects_descendant_greater_than_aggregate(extract_usages_module: object) -> None:
    extract_usages = cast(Any, extract_usages_module)

    with pytest.raises(
        AssertionError,
        match=r'output_reasoning_tokens \(6\) cannot exceed output_tokens \(5\)',
    ):
        extract_usages.check_usage_consistency({'output_tokens': 5, 'output_reasoning_tokens': 6})


def test_usage_consistency_rejects_mutually_exclusive_details_over_aggregate(
    extract_usages_module: object,
) -> None:
    extract_usages = cast(Any, extract_usages_module)

    with pytest.raises(
        AssertionError,
        match=r'mutually exclusive token_type usage .* totals 11, which exceeds output_tokens \(10\)',
    ):
        extract_usages.check_usage_consistency(
            {'output_tokens': 10, 'output_reasoning_tokens': 6, 'output_citation_tokens': 5}
        )


def test_extract_and_check_reports_inconsistent_usage_context(extract_usages_module: object) -> None:
    extract_usages = cast(Any, extract_usages_module)
    extractor = UsageExtractor(
        root='usage',
        mappings=[
            UsageExtractorMapping(path='output_tokens', dest='output_tokens'),
            UsageExtractorMapping(path='reasoning_tokens', dest='output_reasoning_tokens'),
        ],
    )
    provider = Provider(name='Test', id='test', api_pattern='test', extractors=[extractor])
    body = {'file': 'recorded-response.yaml', 'usage': {'output_tokens': 5, 'reasoning_tokens': 6}}

    with pytest.raises(
        AssertionError,
        match=(
            r'Inconsistent extracted usage for test/default in recorded-response.yaml: '
            r'output_reasoning_tokens \(6\) cannot exceed output_tokens \(5\)'
        ),
    ):
        extract_usages.extract_and_check(body, extractor, provider)


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
