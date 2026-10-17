import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from scripts import price_check_coverage as coverage
from scripts.price_check_sources import load_provider_sources, weekly_provider_sources
from scripts.price_check_web_fetch import web_fetch

ROOT = Path(__file__).resolve().parents[1]


def test_plan_uses_exact_weekly_sources_and_selected_backlog() -> None:
    pending = [
        {'request_id': 'request', 'target_model': 'vendor/model', 'provider_id': provider_id}
        for provider_id in ('aws', '_discovery', 'openai')
    ]
    plan = coverage.coverage_plan(ROOT, pending)
    providers = {provider['provider_id']: provider for provider in plan['providers']}
    weekly = {provider.id: provider for provider in weekly_provider_sources(ROOT)}
    all_sources = {provider.id: provider for provider in load_provider_sources(ROOT)}
    assert set(providers) == set(weekly) | {'aws', '_discovery'}
    assert providers['openai']['sources'] == list(weekly['openai'].sources)
    assert providers['aws']['sources'] == list(all_sources['aws'].sources)
    assert providers['_discovery']['sources'] == []
    assert providers['openai']['backfill'] == [pending[2]]


@pytest.mark.parametrize(
    'outcome', ['success', 'transport', 'policy', 'invalid', 'invalid_range', 'execution', 'cancelled']
)
def test_fetch_records_actual_attempt_without_contents_or_errors(tmp_path: Path, outcome: str) -> None:
    directory = tmp_path / 'gh-aw/price-check-coverage'
    directory.mkdir(parents=True)
    url = 'https://pricing.example/required'
    (directory / 'plan.json').write_text(json.dumps({'providers': [{'sources': [url]}]}))
    ledger = tmp_path / 'attempts.jsonl'
    response = {
        'url': 'https://redirect.example/private',
        'status': 200,
        'content_type': 'text/plain',
        'start_index': 0,
        'end_index': 4,
        'total_length': 8,
        'truncated': True,
        'content': 'private page',
    }
    process = AsyncMock()
    if outcome == 'invalid_range':
        response['end_index'] = 99
    process.returncode = 1 if outcome in {'transport', 'policy'} else 0
    process.communicate.return_value = (
        b'invalid' if outcome == 'invalid' else json.dumps(response).encode(),
        b'private policy error'
        if outcome == 'policy'
        else b'web_fetch received HTTP 503 from pricing.example private error',
    )
    subprocess = AsyncMock(return_value=process)
    if outcome == 'execution':
        subprocess.side_effect = OSError('private execution error')
    elif outcome == 'cancelled':
        subprocess.side_effect = asyncio.CancelledError()
    with (
        patch.dict('os.environ', {'RUNNER_TEMP': str(tmp_path)}),
        patch.object(coverage, 'FETCH_LEDGER', ledger),
        patch('scripts.price_check_web_fetch.asyncio.create_subprocess_exec', subprocess),
    ):
        if outcome == 'success':
            assert asyncio.run(web_fetch(url)) == response
        else:
            with pytest.raises(asyncio.CancelledError if outcome == 'cancelled' else Exception):
                asyncio.run(web_fetch(url))
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(events) == 2
    assert events[0]['source'] == url
    assert events[0]['attempt_id'] == events[1]['attempt_id']
    assert events[1]['outcome'] == ('response' if outcome == 'success' else 'error')
    assert 'private' not in ledger.read_text()
    if outcome == 'success':
        assert events[1]['truncated'] is True
    elif outcome == 'transport':
        assert events[1]['http_status'] == 503
    elif outcome in {'policy', 'invalid', 'invalid_range', 'execution'}:
        assert events[1]['error_kind'] == 'invalid_response_or_execution'


@pytest.mark.parametrize('start,max_length', [(-1, 20000), (2**53, 20000), (0, 20001), (0, 0), (1.5, 100)])
def test_invalid_arguments_do_not_pollute_ledger(tmp_path: Path, start: int, max_length: int) -> None:
    with (
        patch.dict('os.environ', {'RUNNER_TEMP': str(tmp_path)}),
        patch('scripts.price_check_web_fetch.asyncio.create_subprocess_exec', new_callable=AsyncMock) as subprocess,
    ):
        with pytest.raises(Exception, match='safe integer'):
            asyncio.run(web_fetch('https://pricing.example/', start_index=start, max_length=max_length))
        subprocess.assert_not_called()


def test_cancelled_communication_kills_and_reaps_fetcher() -> None:
    process = AsyncMock()
    process.kill = Mock()
    process.returncode = None
    process.communicate.side_effect = asyncio.CancelledError()
    with patch('scripts.price_check_web_fetch.asyncio.create_subprocess_exec', AsyncMock(return_value=process)):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(web_fetch('https://pricing.example/'))
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


def test_ledger_io_cannot_fail_a_successful_fetch(tmp_path: Path) -> None:
    directory = tmp_path / 'gh-aw/price-check-coverage'
    directory.mkdir(parents=True)
    (directory / 'plan.json').write_text('{"providers": []}')
    response = {
        'url': 'https://pricing.example/',
        'status': 200,
        'content_type': 'text/plain',
        'start_index': 0,
        'end_index': 1,
        'total_length': 1,
        'truncated': False,
        'content': 'x',
    }
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (json.dumps(response).encode(), b'')
    with (
        patch.dict('os.environ', {'RUNNER_TEMP': str(tmp_path)}),
        patch.object(coverage, 'FETCH_LEDGER', tmp_path),
        patch('scripts.price_check_web_fetch.asyncio.create_subprocess_exec', AsyncMock(return_value=process)),
    ):
        assert asyncio.run(web_fetch(response['url'])) == response
        for malformed in ('invalid', '{}', '{"providers": [{"sources": null}]}'):
            (directory / 'plan.json').write_text(malformed)
            assert asyncio.run(web_fetch(response['url'])) == response


def test_follow_up_url_is_not_persisted_and_targeted_fetches_are_unchanged(tmp_path: Path) -> None:
    ledger = tmp_path / 'attempts.jsonl'
    with patch.dict('os.environ', {'RUNNER_TEMP': str(tmp_path)}), patch.object(coverage, 'FETCH_LEDGER', ledger):
        coverage.start_fetch('https://user:secret@pricing.example/private?token=secret', 0, 20000)
        assert not ledger.exists()
        directory = tmp_path / 'gh-aw/price-check-coverage'
        directory.mkdir(parents=True)
        (directory / 'plan.json').write_text('{"providers": []}')
        coverage.start_fetch('https://user:secret@pricing.example/private?token=secret', 0, 20000)
        assert json.loads(ledger.read_text())['source'] is None
        assert 'secret' not in ledger.read_text()
