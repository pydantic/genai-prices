"""Decide whether a pull request should receive the TypeScript review workflow.

The command reads one JSON object from standard input. Its fields are deliberately
normalised by the workflow before reaching this module:

```
{
  "ci_conclusion": "success",
  "event_name": "pull_request",
  "target_repo": "owner/repository",
  "trigger": {"head_repo": "owner/repository", "head_branch": "feature", "head_sha": "abc"},
  "matching_prs": [{"number": 1, "state": "open", "draft": false,
                    "head": {"repo": {"full_name": "owner/repository"}, "ref": "feature", "sha": "abc"},
                    "base": {"ref": "main"}}],
  "resolved_pr": {"number": 1, "state": "open", "draft": false,
                  "head": {"repo": {"full_name": "owner/repository"}, "ref": "feature", "sha": "abc"},
                  "base": {"ref": "main"}},
  "changed_files": [{"filename": "packages/js/src/index.ts",
                     "previous_filename": null}],
  "reviews": [{"state": "APPROVED", "body": "...", "commit_id": "abc"}]
}
```
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TextIO

REVIEW_MARKER_SUFFIX = '/typescript-review -->'
RELEVANT_EXACT_FILENAMES = frozenset(
    {
        'package.json',
        'package-lock.json',
        '.npmrc',
        'prices/units.yml',
        'prices/new_data/v2/data.json',
        'tests/dataset/extract_usages.py',
        'tests/dataset/usages.json',
    }
)
RELEVANT_PREFIXES = ('packages/js/', 'benchmarks/javascript/', 'prices/providers/', 'prices/src/prices/')


@dataclass(frozen=True)
class PullRequest:
    number: int
    state: str
    draft: bool
    head_repo: str | None
    head_ref: str
    head_sha: str
    base_ref: str


@dataclass(frozen=True)
class Trigger:
    head_repo: str | None
    head_ref: str
    head_sha: str


@dataclass(frozen=True)
class ChangedFile:
    filename: str
    previous_filename: str | None


@dataclass(frozen=True)
class Review:
    state: str
    body: str
    commit_id: str


@dataclass(frozen=True)
class EligibilityInput:
    ci_conclusion: str
    event_name: str
    target_repo: str
    trigger: Trigger
    matching_prs: tuple[PullRequest, ...]
    resolved_pr: PullRequest | None
    changed_files: tuple[ChangedFile, ...]
    reviews: tuple[Review, ...]


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str
    pr_number: int | None = None
    head_sha: str | None = None
    head_ref: str | None = None
    base_ref: str | None = None


def _object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f'{name} must be an object')
    for key in value:
        if not isinstance(key, str):
            raise ValueError(f'{name} must use string keys')
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{name} must be a string')
    return value


def _nonempty_string(value: object, name: str) -> str:
    result = _string(value, name)
    if not result:
        raise ValueError(f'{name} must not be empty')
    return result


def _optional_nonempty_string(value: object, name: str) -> str | None:
    if value is None or value == '':
        return None
    return _nonempty_string(value, name)


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f'{name} must be a boolean')
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f'{name} must be an integer')
    return value


def _field(data: Mapping[str, object], key: str, parent: str) -> object:
    try:
        return data[key]
    except KeyError as exc:
        raise ValueError(f'{parent}.{key} is required') from exc


def _array(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ValueError(f'{name} must be an array')
    return value


def _parse_pull_request(value: object, name: str) -> PullRequest:
    data = _object(value, name)
    head = _object(_field(data, 'head', name), name + '.head')
    base = _object(_field(data, 'base', name), name + '.base')
    head_repository_value = _field(head, 'repo', name + '.head')
    head_repository = _object(head_repository_value, name + '.head.repo') if head_repository_value is not None else None
    number = _integer(_field(data, 'number', name), name + '.number')
    if number < 1:
        raise ValueError(f'{name}.number must be positive')
    return PullRequest(
        number=number,
        state=_nonempty_string(_field(data, 'state', name), name + '.state'),
        draft=_boolean(_field(data, 'draft', name), name + '.draft'),
        head_repo=(
            _optional_nonempty_string(
                _field(head_repository, 'full_name', name + '.head.repo'), name + '.head.repo.full_name'
            )
            if head_repository is not None
            else None
        ),
        head_ref=_nonempty_string(_field(head, 'ref', name + '.head'), name + '.head.ref'),
        head_sha=_nonempty_string(_field(head, 'sha', name + '.head'), name + '.head.sha'),
        base_ref=_nonempty_string(_field(base, 'ref', name + '.base'), name + '.base.ref'),
    )


def _parse_trigger(value: object, name: str) -> Trigger:
    data = _object(value, name)
    return Trigger(
        head_repo=_optional_nonempty_string(_field(data, 'head_repo', name), name + '.head_repo'),
        head_ref=_nonempty_string(_field(data, 'head_branch', name), name + '.head_branch'),
        head_sha=_nonempty_string(_field(data, 'head_sha', name), name + '.head_sha'),
    )


def _parse_changed_file(value: object, name: str) -> ChangedFile:
    data = _object(value, name)
    previous_filename = data.get('previous_filename')
    if previous_filename is not None:
        previous_filename = _nonempty_string(previous_filename, name + '.previous_filename')
    return ChangedFile(
        filename=_nonempty_string(_field(data, 'filename', name), name + '.filename'),
        previous_filename=previous_filename,
    )


def _parse_review(value: object, name: str) -> Review:
    data = _object(value, name)
    return Review(
        state=_nonempty_string(_field(data, 'state', name), name + '.state'),
        body=_string(_field(data, 'body', name), name + '.body') if _field(data, 'body', name) is not None else '',
        commit_id=(
            _nonempty_string(_field(data, 'commit_id', name), name + '.commit_id')
            if _field(data, 'commit_id', name) is not None
            else ''
        ),
    )


def parse_input(value: object) -> EligibilityInput:
    """Validate and convert the workflow's normalised JSON input."""
    data = _object(value, 'input')
    matching_values = _array(_field(data, 'matching_prs', 'input'), 'input.matching_prs')
    changed_file_values = _array(_field(data, 'changed_files', 'input'), 'input.changed_files')
    review_values = _array(_field(data, 'reviews', 'input'), 'input.reviews')
    trigger = _parse_trigger(_field(data, 'trigger', 'input'), 'input.trigger')
    matching_prs = tuple(
        _parse_pull_request(item, f'input.matching_prs[{index}]') for index, item in enumerate(matching_values)
    )
    candidates = tuple(
        pull_request
        for pull_request in matching_prs
        if pull_request.state == 'open'
        and pull_request.head_ref == trigger.head_ref
        and pull_request.head_sha == trigger.head_sha
    )
    resolved_value = data.get('resolved_pr')
    if len(candidates) == 1:
        if resolved_value is None:
            raise ValueError('input.resolved_pr must be an object when exactly one pull request matches')
        resolved_pr = _parse_pull_request(resolved_value, 'input.resolved_pr')
    else:
        resolved_pr = None
    return EligibilityInput(
        ci_conclusion=_nonempty_string(_field(data, 'ci_conclusion', 'input'), 'input.ci_conclusion'),
        event_name=_nonempty_string(_field(data, 'event_name', 'input'), 'input.event_name'),
        target_repo=_nonempty_string(_field(data, 'target_repo', 'input'), 'input.target_repo'),
        trigger=trigger,
        matching_prs=matching_prs,
        resolved_pr=resolved_pr,
        changed_files=tuple(
            _parse_changed_file(item, f'input.changed_files[{index}]') for index, item in enumerate(changed_file_values)
        ),
        reviews=tuple(_parse_review(item, f'input.reviews[{index}]') for index, item in enumerate(review_values)),
    )


def _result(eligible: bool, reason: str, pull_request: PullRequest | None = None) -> EligibilityResult:
    if pull_request is None:
        return EligibilityResult(eligible=eligible, reason=reason)
    return EligibilityResult(
        eligible=eligible,
        reason=reason,
        pr_number=pull_request.number,
        head_sha=pull_request.head_sha,
        head_ref=pull_request.head_ref,
        base_ref=pull_request.base_ref,
    )


def _is_relevant_path(path: str) -> bool:
    return path in RELEVANT_EXACT_FILENAMES or path.startswith(RELEVANT_PREFIXES)


def _has_relevant_file(changed_files: Sequence[ChangedFile]) -> bool:
    return any(
        _is_relevant_path(changed_file.filename)
        or changed_file.previous_filename is not None
        and _is_relevant_path(changed_file.previous_filename)
        for changed_file in changed_files
    )


def _marker(target_repo: str) -> str:
    return f'<!-- gh-aw-workflow-call-id: {target_repo}{REVIEW_MARKER_SUFFIX}'


def _has_current_formal_review(reviews: Sequence[Review], head_sha: str, target_repo: str) -> bool:
    marker = _marker(target_repo)
    return any(
        review.state in {'APPROVED', 'CHANGES_REQUESTED'} and review.commit_id == head_sha and marker in review.body
        for review in reviews
    )


def classify(data: EligibilityInput) -> EligibilityResult:
    """Apply the workflow eligibility policy to validated data."""
    if data.ci_conclusion != 'success':
        return _result(False, 'CI did not succeed')
    if data.event_name != 'pull_request':
        return _result(False, 'event is not pull_request')
    if data.trigger.head_repo != data.target_repo:
        return _result(False, 'triggering head repository differs from target repository')

    matching_prs = tuple(
        pull_request
        for pull_request in data.matching_prs
        if pull_request.state == 'open'
        and pull_request.head_ref == data.trigger.head_ref
        and pull_request.head_sha == data.trigger.head_sha
    )
    if len(matching_prs) != 1:
        return _result(False, 'trigger does not resolve to exactly one open pull request')

    pull_request = data.resolved_pr
    if pull_request is None:
        return _result(False, 'resolved pull request is unavailable')
    if pull_request.state != 'open':
        return _result(False, 'resolved pull request is not open', pull_request)
    if pull_request.draft:
        return _result(False, 'resolved pull request is a draft', pull_request)
    if pull_request.head_repo != data.target_repo:
        return _result(False, 'resolved pull request head repository differs from target repository', pull_request)
    if pull_request.number != matching_prs[0].number:
        return _result(False, 'resolved pull request does not match trigger lookup', pull_request)
    if pull_request.head_ref != data.trigger.head_ref or pull_request.head_sha != data.trigger.head_sha:
        return _result(False, 'resolved pull request head differs from trigger', pull_request)
    if not _has_relevant_file(data.changed_files):
        return _result(False, 'no TypeScript-review-relevant files changed', pull_request)
    if _has_current_formal_review(data.reviews, pull_request.head_sha, data.target_repo):
        return _result(False, 'current commit already has a formal TypeScript review', pull_request)
    return _result(True, 'eligible', pull_request)


def _output_value(value: bool | int | str | None) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def write_output(result: EligibilityResult, stream: TextIO) -> None:
    """Write the result using GitHub Actions' simple output-file syntax."""
    for key, value in (
        ('eligible', result.eligible),
        ('reason', result.reason),
        ('pr_number', result.pr_number),
        ('head_sha', result.head_sha),
        ('head_ref', result.head_ref),
        ('base_ref', result.base_ref),
    ):
        print(f'{key}={_output_value(value)}', file=stream)


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    """Run the JSON-to-output CLI."""
    try:
        value: object = json.load(stdin)
        result = classify(parse_input(value))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'::error::{exc}', file=stderr)
        return 1
    write_output(result, stdout)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
