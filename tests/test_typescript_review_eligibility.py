from __future__ import annotations

import io
import json
import re
from collections.abc import Callable
from dataclasses import replace

import pytest
import typescript_review_eligibility as eligibility


def _pull_request(
    *,
    number: int = 7,
    state: str = 'open',
    draft: bool = False,
    head_repo: str | None = 'pydantic/genai-prices',
    head_ref: str = 'typescript-work',
    head_sha: str = 'current-sha',
    base_ref: str = 'main',
) -> dict[str, object]:
    return {
        'number': number,
        'state': state,
        'draft': draft,
        'head': {'repo': {'full_name': head_repo}, 'ref': head_ref, 'sha': head_sha},
        'base': {'ref': base_ref},
    }


def _trigger(
    *,
    head_repo: str | None = 'pydantic/genai-prices',
    head_branch: str = 'typescript-work',
    head_sha: str = 'current-sha',
) -> dict[str, object]:
    return {'head_repo': head_repo, 'head_branch': head_branch, 'head_sha': head_sha}


def _input() -> dict[str, object]:
    pull_request = _pull_request()
    return {
        'ci_conclusion': 'success',
        'event_name': 'pull_request',
        'target_repo': 'pydantic/genai-prices',
        'trigger': _trigger(),
        'matching_prs': [pull_request.copy()],
        'resolved_pr': pull_request.copy(),
        'changed_files': [{'filename': 'packages/js/src/index.ts', 'previous_filename': None}],
        'reviews': [],
    }


def _result(value: dict[str, object]) -> eligibility.EligibilityResult:
    return eligibility.classify(eligibility.parse_input(value))


def _set_null_target_repo(data: dict[str, object]) -> None:
    data['target_repo'] = None


def _set_mapping_matching_prs(data: dict[str, object]) -> None:
    data['matching_prs'] = {}


def _set_null_changed_file(data: dict[str, object]) -> None:
    data['changed_files'] = [None]


def _set_null_review(data: dict[str, object]) -> None:
    data['reviews'] = [None]


def _set_invalid_previous_filename(data: dict[str, object]) -> None:
    data['changed_files'] = [{'filename': 'file.py', 'previous_filename': 1}]


SHAPE_CASES: list[tuple[Callable[[dict[str, object]], None], str]] = [
    (_set_null_target_repo, 'input.target_repo must be a string'),
    (_set_mapping_matching_prs, 'input.matching_prs must be an array'),
    (_set_null_changed_file, 'input.changed_files[0] must be an object'),
    (_set_null_review, 'input.reviews[0] must be an object'),
    (_set_invalid_previous_filename, 'input.changed_files[0].previous_filename must be a string'),
]


def test_baseline_is_eligible_and_writes_github_output() -> None:
    result = _result(_input())

    assert result == eligibility.EligibilityResult(
        eligible=True,
        reason='eligible',
        pr_number=7,
        head_sha='current-sha',
        head_ref='typescript-work',
        base_ref='main',
    )
    stream = io.StringIO()
    eligibility.write_output(result, stream)
    assert stream.getvalue().splitlines() == [
        'eligible=true',
        'reason=eligible',
        'pr_number=7',
        'head_sha=current-sha',
        'head_ref=typescript-work',
        'base_ref=main',
    ]


@pytest.mark.parametrize(
    ('field', 'value', 'reason'),
    [
        ('ci_conclusion', 'failure', 'CI did not succeed'),
        ('event_name', 'push', 'event is not pull_request'),
    ],
)
def test_non_eligible_run_contexts(field: str, value: str, reason: str) -> None:
    data = _input()
    data[field] = value

    assert _result(data) == eligibility.EligibilityResult(eligible=False, reason=reason)


@pytest.mark.parametrize('matching_prs', [[], [_pull_request(number=7), _pull_request(number=8)]])
def test_zero_or_ambiguous_matching_pull_requests(matching_prs: list[dict[str, object]]) -> None:
    data = _input()
    data['matching_prs'] = matching_prs

    assert _result(data) == eligibility.EligibilityResult(
        eligible=False, reason='trigger does not resolve to exactly one open pull request'
    )


def test_no_matching_pull_request_accepts_null_resolved_pull_request() -> None:
    data = _input()
    data['matching_prs'] = []
    data['resolved_pr'] = None

    assert _result(data).reason == 'trigger does not resolve to exactly one open pull request'


def test_no_matching_pull_request_does_not_require_resolved_pull_request() -> None:
    data = _input()
    data['matching_prs'] = []
    del data['resolved_pr']

    assert _result(data).reason == 'trigger does not resolve to exactly one open pull request'


def test_one_matching_pull_request_requires_resolved_pull_request() -> None:
    data = _input()
    data['resolved_pr'] = None

    with pytest.raises(ValueError, match='input.resolved_pr must be an object'):
        eligibility.parse_input(data)


def test_unavailable_resolved_pull_request_is_not_eligible() -> None:
    parsed = eligibility.parse_input(_input())

    assert eligibility.classify(replace(parsed, resolved_pr=None)).reason == 'resolved pull request is unavailable'


def test_trigger_from_fork_is_not_eligible() -> None:
    data = _input()
    data['trigger'] = _trigger(head_repo='contributor/genai-prices')

    assert _result(data) == eligibility.EligibilityResult(
        eligible=False, reason='triggering head repository differs from target repository'
    )


def test_trigger_with_null_repository_is_not_eligible() -> None:
    data = _input()
    data['trigger'] = _trigger(head_repo=None)

    assert _result(data).reason == 'triggering head repository differs from target repository'


def test_trigger_with_empty_repository_is_not_eligible() -> None:
    data = _input()
    data['trigger'] = _trigger(head_repo='')

    assert _result(data).reason == 'triggering head repository differs from target repository'


def test_resolved_pull_request_must_be_open() -> None:
    data = _input()
    data['resolved_pr'] = _pull_request(state='closed')

    assert _result(data).reason == 'resolved pull request is not open'


def test_resolved_pull_request_must_not_be_draft() -> None:
    data = _input()
    data['resolved_pr'] = _pull_request(draft=True)

    assert _result(data).reason == 'resolved pull request is a draft'


def test_resolved_pull_request_must_not_be_from_a_fork() -> None:
    data = _input()
    data['resolved_pr'] = _pull_request(head_repo='contributor/genai-prices')

    assert _result(data).reason == 'resolved pull request head repository differs from target repository'


def test_resolved_pull_request_with_null_repository_is_not_eligible() -> None:
    data = _input()
    data['resolved_pr'] = _pull_request(head_repo=None)

    assert _result(data).reason == 'resolved pull request head repository differs from target repository'


def test_resolved_pull_request_must_match_lookup_number() -> None:
    data = _input()
    data['resolved_pr'] = _pull_request(number=8)

    assert _result(data).reason == 'resolved pull request does not match trigger lookup'


@pytest.mark.parametrize('resolved_pr', [_pull_request(head_ref='stale-branch'), _pull_request(head_sha='stale-sha')])
def test_resolved_pull_request_head_must_match_trigger(resolved_pr: dict[str, object]) -> None:
    data = _input()
    data['resolved_pr'] = resolved_pr

    assert _result(data).reason == 'resolved pull request head differs from trigger'


def test_unrelated_changes_are_not_eligible() -> None:
    data = _input()
    data['changed_files'] = [{'filename': 'README.md', 'previous_filename': None}]

    assert _result(data).reason == 'no TypeScript-review-relevant files changed'


@pytest.mark.parametrize(
    'filename',
    [
        'packages/js/package.json',
        'benchmarks/javascript/bench.ts',
        'package.json',
        'package-lock.json',
        '.npmrc',
        'prices/providers/openai.yml',
        'prices/units.yml',
        'prices/new_data/v2/data.json',
        'prices/src/prices/build.py',
        'prices/src/prices/package_data.py',
        'prices/src/prices/prices_types.py',
        'prices/src/prices/export_validation.py',
        'prices/src/prices/utils.py',
        'tests/dataset/extract_usages.py',
        'tests/dataset/usages.json',
    ],
)
def test_each_relevant_filename_is_eligible(filename: str) -> None:
    data = _input()
    data['changed_files'] = [{'filename': filename, 'previous_filename': None}]

    assert _result(data).eligible is True


def test_renamed_relevant_file_is_eligible() -> None:
    data = _input()
    data['changed_files'] = [{'filename': 'docs/release.md', 'previous_filename': 'packages/js/src/index.ts'}]

    assert _result(data).eligible is True


def test_missing_previous_filename_is_accepted() -> None:
    data = _input()
    data['changed_files'] = [{'filename': 'packages/js/src/index.ts'}]

    assert _result(data).eligible is True


def test_same_commit_formal_review_with_marker_skips_rerun() -> None:
    data = _input()
    data['reviews'] = [
        {
            'state': 'APPROVED',
            'body': '<!-- gh-aw-workflow-call-id: pydantic/genai-prices/typescript-review -->',
            'commit_id': 'current-sha',
        }
    ]

    assert _result(data).reason == 'current commit already has a formal TypeScript review'


@pytest.mark.parametrize(
    'review',
    [
        {
            'state': 'COMMENTED',
            'body': '<!-- gh-aw-workflow-call-id: pydantic/genai-prices/typescript-review -->',
            'commit_id': 'current-sha',
        },
        {
            'state': 'CHANGES_REQUESTED',
            'body': '<!-- gh-aw-workflow-call-id: pydantic/genai-prices/typescript-review -->',
            'commit_id': 'old-sha',
        },
        {'state': 'APPROVED', 'body': 'Looks good', 'commit_id': 'current-sha'},
    ],
)
def test_nonmatching_review_does_not_skip_rerun(review: dict[str, str]) -> None:
    data = _input()
    data['reviews'] = [review]

    assert _result(data).eligible is True


def test_null_review_body_and_commit_id_do_not_skip_rerun() -> None:
    data = _input()
    data['reviews'] = [{'state': 'APPROVED', 'body': None, 'commit_id': None}]

    assert _result(data).eligible is True


@pytest.mark.parametrize(
    ('mutate', 'message'),
    SHAPE_CASES,
)
def test_input_shape_errors_fail_validation(mutate: Callable[[dict[str, object]], None], message: str) -> None:
    data = _input()
    mutate(data)

    with pytest.raises(ValueError, match=re.escape(message)):
        eligibility.parse_input(data)


@pytest.mark.parametrize(
    ('value', 'message'),
    [
        ({1: 'not-a-string-key'}, 'input must use string keys'),
        ({}, 'input.matching_prs is required'),
    ],
)
def test_invalid_root_shape_fails_validation(value: object, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        eligibility.parse_input(value)


@pytest.mark.parametrize(
    ('pull_request', 'message'),
    [
        (_pull_request(head_ref=''), 'input.resolved_pr.head.ref must not be empty'),
        ({**_pull_request(), 'draft': 'false'}, 'input.resolved_pr.draft must be a boolean'),
        (_pull_request(number=True), 'input.resolved_pr.number must be an integer'),
        (_pull_request(number=0), 'input.resolved_pr.number must be positive'),
    ],
)
def test_invalid_pull_request_fields_fail_validation(pull_request: dict[str, object], message: str) -> None:
    data = _input()
    data['resolved_pr'] = pull_request

    with pytest.raises(ValueError, match=re.escape(message)):
        eligibility.parse_input(data)


def test_cli_rejects_invalid_json() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert eligibility.main(io.StringIO('{'), stdout, stderr) == 1
    assert stdout.getvalue() == ''
    assert stderr.getvalue().startswith('::error::')


def test_cli_reads_json_object_and_writes_result() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert eligibility.main(io.StringIO(json.dumps(_input())), stdout, stderr) == 0
    assert stderr.getvalue() == ''
    assert stdout.getvalue().startswith('eligible=true\n')


def test_output_blanks_unresolvable_pull_request_fields() -> None:
    stream = io.StringIO()

    eligibility.write_output(eligibility.EligibilityResult(eligible=False, reason='not eligible'), stream)

    assert stream.getvalue().endswith('pr_number=\nhead_sha=\nhead_ref=\nbase_ref=\n')
