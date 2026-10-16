from pathlib import Path

import pytest

from scripts.price_check_scope_policy import allowed_price_check_files
from scripts.price_check_sources import load_provider_sources

ROOT = Path(__file__).resolve().parents[1]


def _all_provider_files() -> list[str]:
    return sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'prices/providers').glob('*.yml'))


def _pending(provider_id: str) -> list[dict[str, str]]:
    return [
        {
            'request_id': 'a-request-id',
            'target_model': 'vendor/model',
            'provider_id': provider_id,
            'source': 'ignored source text',
        }
    ]


def test_weekly_scope_keeps_25_manifest_files_and_non_provider_paths() -> None:
    all_provider_files = _all_provider_files()
    allowed_files = ['README.md', *all_provider_files, 'tests/test_price_calc.py']

    filtered = allowed_price_check_files(ROOT, allowed_files, 'agentic-price-check.md', [])

    provider_files = [path for path in filtered if path.startswith('prices/providers/')]
    assert len(provider_files) == 25
    assert provider_files == [path for path in all_provider_files if path in set(provider_files)]
    assert 'prices/providers/quicksilverpro.yml' not in filtered
    assert 'prices/providers/aws.yml' not in filtered
    assert 'README.md' in filtered
    assert 'tests/test_price_calc.py' in filtered


def test_pending_provider_adds_only_that_provider_to_weekly_scope() -> None:
    filtered = allowed_price_check_files(ROOT, _all_provider_files(), 'agentic-price-check.md', _pending('aws'))

    assert 'prices/providers/aws.yml' in filtered
    assert 'prices/providers/azure.yml' not in filtered
    assert 'prices/providers/quicksilverpro.yml' not in filtered


def test_discovery_sentinel_allows_every_existing_provider_file() -> None:
    all_provider_files = _all_provider_files()

    filtered = allowed_price_check_files(ROOT, all_provider_files, 'agentic-price-check.md', _pending('_discovery'))

    assert filtered == all_provider_files
    assert set(filtered) == {provider.file for provider in load_provider_sources(ROOT)}


def test_targeted_workflow_keeps_its_supplied_allowlist_unchanged() -> None:
    allowed_files = ['prices/providers/aws.yml', 'tests/test_price_calc.py', 'prices/providers/openai.yml']

    assert allowed_price_check_files(ROOT, allowed_files, 'agentic-model-price-check.md', []) == allowed_files


@pytest.mark.parametrize(
    'pending_backfill',
    [
        None,
        [{'request_id': 'request', 'provider_id': 'aws'}],
        _pending('provider-that-does-not-exist'),
    ],
)
def test_weekly_scope_rejects_invalid_or_unknown_pending_rows(pending_backfill: object) -> None:
    with pytest.raises(ValueError, match='Pending price-check backfill'):
        allowed_price_check_files(ROOT, _all_provider_files(), 'agentic-price-check.md', pending_backfill)


def test_scope_rejects_unknown_workflow_source() -> None:
    with pytest.raises(ValueError, match='Unknown price-check workflow source'):
        allowed_price_check_files(ROOT, [], 'some-other-workflow.md', [])
