"""Collect the cross-language golden dataset into the pytest run.

`tests/dataset/extract_usages.py` generates `tests/dataset/usages.json`, which the JS suite asserts
against in `packages/js/src/__tests__/dataset.test.ts`. It is the only same-usage-same-price check
across the two implementations, and it was reachable *only* via the second line of the Makefile `test`
target - so `uv run pytest`, IDE runners and CI's own lowest-dependency-version step all skipped the
largest regression corpus in the repo.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import NoReturn

import pytest

from genai_prices.types import Provider, UsageExtractor, UsageExtractorMapping

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


def test_get_body_keys_handles_string_list_and_empty_paths(extract_usages_module: object) -> None:
    string_paths = UsageExtractor(
        root='usage', model_path='model', mappings=[UsageExtractorMapping(path='input_tokens', dest='input_tokens')]
    )
    list_paths = UsageExtractor(
        root=['usage', 'details'],
        model_path=['model', 'id'],
        mappings=[UsageExtractorMapping(path='input_tokens', dest='input_tokens')],
    )
    empty_paths = UsageExtractor(
        root='', model_path='', mappings=[UsageExtractorMapping(path='input_tokens', dest='input_tokens')]
    )

    assert extract_usages_module.get_body_keys(string_paths) == {'usage', 'model'}  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert extract_usages_module.get_body_keys(list_paths) == {'usage', 'model'}  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert extract_usages_module.get_body_keys(empty_paths) == set()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


@pytest.mark.parametrize('has_raw_bodies', [False, True])
def test_rebuild_usages_uses_available_recordings(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, has_raw_bodies: bool
) -> None:
    current = [{'body': {'file': 'current.json'}}]
    recordings = [{'file': 'recorded.json'}]
    (tmp_path / 'usages.json').write_text(json.dumps(current))
    raw_bodies = tmp_path / 'raw_bodies.json'
    if has_raw_bodies:
        raw_bodies.write_text(json.dumps(recordings))

    calls: list[list[dict[str, object]]] = []

    def fake_get_usages(bodies: list[dict[str, object]]) -> list[dict[str, object]]:
        calls.append(bodies)
        return [{'body': body} for body in bodies]

    monkeypatch.setattr(extract_usages_module, 'this_dir', tmp_path)
    monkeypatch.setattr(extract_usages_module, 'raw_bodies_path', raw_bodies)
    monkeypatch.setattr(extract_usages_module, 'get_usages', fake_get_usages)

    rebuilt_current, rebuilt = extract_usages_module.rebuild_usages()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]

    assert rebuilt_current == current
    expected_bodies = recordings if has_raw_bodies else [{'file': 'current.json'}]
    assert calls == [expected_bodies, expected_bodies] if has_raw_bodies else [expected_bodies]
    assert rebuilt == [{'body': body} for body in expected_bodies]


def test_main_reports_current_dataset(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    current: list[dict[str, object]] = [{'body': {'file': 'recorded.json'}}]

    def current_result() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return current, current

    monkeypatch.setattr(extract_usages_module, 'rebuild_usages', current_result)

    assert extract_usages_module.main() is None  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert capsys.readouterr().out == 'usages.json is up to date.\n'


def test_main_rejects_stale_dataset_without_writing(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    current: list[dict[str, object]] = []
    rebuilt: list[dict[str, object]] = [{'body': {'file': 'recorded.json'}}]

    def stale_result() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return current, rebuilt

    monkeypatch.setattr(extract_usages_module, 'rebuild_usages', stale_result)

    with pytest.raises(AssertionError, match='usages.json is out of date'):
        extract_usages_module.main(write=False)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def test_main_writes_and_reports_a_stale_dataset(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current: list[dict[str, object]] = []
    rebuilt: list[dict[str, object]] = [{'body': {'file': 'recorded.json'}}]

    def stale_result() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return current, rebuilt

    monkeypatch.setattr(extract_usages_module, 'this_dir', tmp_path)
    monkeypatch.setattr(extract_usages_module, 'rebuild_usages', stale_result)

    with pytest.raises(AssertionError, match='usages.json updated'):
        extract_usages_module.main()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

    assert json.loads((tmp_path / 'usages.json').read_text()) == rebuilt


@dataclasses.dataclass
class UsageCase:
    provider_id: str
    api_flavor: str
    model_ref: str | None
    usage_dict: dict[str, int]


@dataclasses.dataclass
class Calculation:
    input_price: Decimal
    output_price: Decimal
    total_price: Decimal


def test_case_to_result_records_prices_and_merges_matching_usage(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_calc_price(*_args: object, **_kwargs: object) -> Calculation:
        return Calculation(Decimal('1'), Decimal('2'), Decimal('4'))

    monkeypatch.setattr(extract_usages_module, 'calc_price', fake_calc_price)
    this_result: dict[str, object] = {'body': {'file': 'recorded.json'}, 'extracted': []}
    case = UsageCase('openai', 'chat', 'gpt-test', {'input_tokens': 1})

    first = extract_usages_module.case_to_result(case, this_result)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
    second = extract_usages_module.case_to_result(case, this_result)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]

    assert first == {
        'provider_id': 'openai',
        'api_flavor': 'chat',
        'input_price': '1',
        'output_price': '2',
        'total_price': '4',
    }
    assert second == first
    assert this_result['extracted'] == [
        {
            'usage': {'input_tokens': 1},
            'extractors': [first, second],
        }
    ]


def test_case_to_result_omits_unavailable_prices(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_lookup_error(*_args: object, **_kwargs: object) -> NoReturn:
        raise LookupError

    monkeypatch.setattr(extract_usages_module, 'calc_price', raise_lookup_error)
    this_result: dict[str, object] = {'body': {'file': 'recorded.json'}, 'extracted': []}

    result = extract_usages_module.case_to_result(  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        UsageCase('openai', 'chat', 'unpriced', {'input_tokens': 1}), this_result
    )

    assert result == {'provider_id': 'openai', 'api_flavor': 'chat'}
    assert this_result['extracted'] == [{'usage': {'input_tokens': 1}, 'extractors': [result]}]


def test_case_to_result_reports_calculation_errors(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_calculation_error(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError('bad price')

    monkeypatch.setattr(extract_usages_module, 'calc_price', raise_calculation_error)
    this_result: dict[str, object] = {'body': {'file': 'recorded.json'}, 'extracted': []}

    with pytest.raises(AssertionError, match='Error calculating price for openai:gpt-test') as exc_info:
        extract_usages_module.case_to_result(  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            UsageCase('openai', 'chat', 'gpt-test', {'input_tokens': 1}), this_result
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_check_cases_usages_match_accepts_shared_usage(extract_usages_module: object) -> None:
    extract_usages_module.check_cases_usages_match(  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        [
            UsageCase('openai', 'chat', 'gpt-test', {'input_tokens': 1, 'output_tokens': 2}),
            UsageCase('openai', 'responses', 'gpt-test', {'input_tokens': 1}),
        ]
    )


def test_get_usages_ignores_bodies_without_extractable_usage(
    extract_usages_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extract_usages_module, 'extractors', [])

    assert extract_usages_module.get_usages([{'file': 'recorded.json', 'ignored': 'value'}]) == []  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


@dataclasses.dataclass
class LookupFailingExtractor:
    api_flavor: str = 'default'

    def extract(self, _body: object) -> NoReturn:
        raise LookupError


def test_extract_and_check_ignores_invalid_recorded_bodies(extract_usages_module: object) -> None:
    extractor = UsageExtractor(
        root='usage',
        mappings=[UsageExtractorMapping(path='input_tokens', dest='input_tokens')],
    )
    provider = Provider(id='openai', name='OpenAI', api_pattern='https://example.com', extractors=[extractor])

    assert extract_usages_module.extract_and_check({}, extractor, provider) is None  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert extract_usages_module.extract_and_check({}, LookupFailingExtractor(), provider) is None  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
