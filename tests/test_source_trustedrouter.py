from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
from cassetter.cassette import RawResponse

from prices import source_trustedrouter
from prices.prices_types import ClauseEquals, ClauseOr, ModelPrice, StartDateConstraint, Tier, TieredPrices
from prices.update import ProviderYaml

from .fixtures import ProviderSnapshot

KEEP_MODEL_KEYS = ('id', 'name', 'context_length', 'pricing')
KEEP_METADATA_KEYS = ('internal_only', 'configuration_hidden', 'synthetic_monitor', 'aliases')


def slim_models_response(response: RawResponse) -> RawResponse:  # pragma: no cover - runs only when recording
    payload = json.loads(response.body or b'')
    slim_models: list[dict[str, Any]] = []
    for model in payload.get('data', []):
        entry = {key: model[key] for key in KEEP_MODEL_KEYS if key in model}
        if isinstance(tr := model.get('trustedrouter'), dict):
            entry['trustedrouter'] = {key: tr[key] for key in KEEP_METADATA_KEYS if key in tr}
        slim_models.append(entry)
    response.body = json.dumps({'data': slim_models}).encode()
    response.headers = {'content-type': ['application/json']}
    return response


@pytest.fixture(scope='module')
def vcr_config() -> dict[str, Any]:
    return {'before_record_response': slim_models_response}


SAMPLE_MODEL = {
    'id': 'anthropic/claude-sonnet-5',
    'name': 'Anthropic: Claude Sonnet 5',
    'context_length': 1_000_000,
    'pricing': {
        'prompt': '0.00000211',
        'completion': '0.00001055',
        'input_cache_read': '0.000000211',
        'input_cache_write': '0.0000026375',
    },
    'trustedrouter': {
        'internal_only': False,
        'configuration_hidden': False,
        'synthetic_monitor': False,
        'aliases': ['anthropic/claude-sonnet-5-alias', '', 123, 'trustedrouter/auto'],
    },
}


def test_trustedrouter_parses_token_non_token_aliases_and_filters_hidden_and_unpriced() -> None:
    models = source_trustedrouter.parse_models(
        [
            SAMPLE_MODEL,
            {
                'id': 'trustedrouter/auto',
                'name': 'TrustedRouter Auto',
                'context_length': 1_048_576,
                'pricing': {'prompt': '0.000000026375', 'completion': '0.00000007385'},
                'trustedrouter': {'aliases': ['anthropic/claude-sonnet-5-alias', 'trustedrouter/auto-routing']},
            },
            {
                'id': 'elevenlabs/eleven-v3',
                'name': 'Vendor:   ',
                'context_length': 0,
                'pricing': {'input_character': '0.0000844'},
            },
            {
                'id': 'openai/whisper-1',
                'name': None,
                'context_length': True,
                'pricing': {'input_audio_minute': '0.00633'},
            },
            {
                'id': 'deepseek/fetch',
                'pricing': {'request': '0.000792'},
            },
            {'id': 'hidden/internal', 'pricing': {'prompt': '0.000001'}, 'trustedrouter': {'internal_only': True}},
            {'id': 'hidden/config', 'pricing': {'prompt': '0.000001'}, 'trustedrouter': {'configuration_hidden': True}},
            {'id': 'hidden/synth', 'pricing': {'prompt': '0.000001'}, 'trustedrouter': {'synthetic_monitor': True}},
            {'id': 'trustedrouter/synth', 'pricing': {'prompt': '-1', 'completion': '-1'}},
            {'id': 'trustedrouter/free', 'pricing': {'prompt': '0', 'completion': '0'}},
            {'id': 'image/only', 'pricing': {'prompt': '0', 'completion': '0', 'image': '0.03'}},
            {'id': 'missing/pricing', 'pricing': None},
        ]
    )

    assert [(m.id, m.name, m.context_window) for m in models] == [
        ('anthropic/claude-sonnet-5', 'Claude Sonnet 5', 1_000_000),
        ('trustedrouter/auto', 'TrustedRouter Auto', 1_048_576),
        ('elevenlabs/eleven-v3', None, None),
        ('openai/whisper-1', None, None),
        ('deepseek/fetch', None, None),
    ]
    assert models[0].match == ClauseOr(
        or_=[  # pyright: ignore[reportCallIssue]
            ClauseEquals(equals='anthropic/claude-sonnet-5'),
            ClauseEquals(equals='anthropic/claude-sonnet-5-alias'),
        ]
    )
    assert models[0].prices == ModelPrice(
        input_mtok=Decimal('2.11'),
        cache_write_mtok=Decimal('2.6375'),
        cache_read_mtok=Decimal('0.211'),
        output_mtok=Decimal('10.55'),
    )
    assert models[1].match == ClauseOr(
        or_=[  # pyright: ignore[reportCallIssue]
            ClauseEquals(equals='trustedrouter/auto'),
            ClauseEquals(equals='trustedrouter/auto-routing'),
        ]
    )
    assert models[2].prices == ModelPrice.model_validate({'input_mchars': Decimal('84.4')})
    assert models[3].prices == ModelPrice.model_validate(
        {'audio_hours': Decimal('0.3798'), 'input_audio_hours': Decimal('0.3798')}
    )
    assert models[4].prices == ModelPrice(requests_kcount=Decimal('0.792'))
    assert all(m.prices_checked == date.today() for m in models)


def test_trustedrouter_parses_prompt_length_tiers_and_handles_constant_and_negative_tiers() -> None:
    models = source_trustedrouter.parse_models(
        [
            {
                'id': 'qwen/qwen3-coder-flash',
                'name': 'Qwen: Qwen3 Coder Flash',
                'context_length': 1_048_576,
                'pricing': {
                    'prompt': '0.0000003165',
                    'completion': '0.0000015825',
                    'input_cache_read': '0.00000003165',
                    'tiers': [
                        {
                            'max_prompt_tokens': 32_000,
                            'prompt': '0.0000003165',
                            'completion': '0.0000015825',
                        },
                        {
                            'max_prompt_tokens': 128_000,
                            'prompt': '0.0000005275',
                            'completion': '0.0000015825',
                            'input_cache_read': '0.00000005275',
                        },
                        {
                            'max_prompt_tokens': None,
                            'prompt': '0.000000844',
                            'completion': '0.0000015825',
                            'input_cache_read': '0.0000000844',
                        },
                    ],
                },
            },
            {
                'id': 'vendor/tier0-negative',
                'pricing': {
                    'prompt': '0.000001',
                    'tiers': [
                        {'max_prompt_tokens': 100_000, 'prompt': '-1'},
                        {'max_prompt_tokens': None, 'prompt': '0.000002'},
                    ],
                },
            },
            {
                'id': 'vendor/tier1-negative',
                'pricing': {
                    'prompt': '0.000001',
                    'tiers': [
                        {'max_prompt_tokens': 100_000, 'prompt': '0.000001'},
                        {'max_prompt_tokens': None, 'prompt': '-1'},
                    ],
                },
            },
            {
                'id': 'vendor/zero-higher-tier',
                'pricing': {
                    'prompt': '0.000001',
                    'completion': '0.000002',
                    'tiers': [
                        {'max_prompt_tokens': 100_000, 'prompt': '0.000001', 'completion': '0.000002'},
                        {'max_prompt_tokens': None, 'prompt': '0.000002', 'completion': '0'},
                    ],
                },
            },
        ]
    )

    assert [m.id for m in models] == ['qwen/qwen3-coder-flash', 'vendor/zero-higher-tier']
    assert models[0].prices == ModelPrice(
        input_mtok=TieredPrices(
            base=Decimal('0.3165'),
            tiers=[Tier(start=32_000, price=Decimal('0.5275')), Tier(start=128_000, price=Decimal('0.844'))],
        ),
        cache_read_mtok=TieredPrices(
            base=Decimal('0.03165'),
            tiers=[Tier(start=32_000, price=Decimal('0.05275')), Tier(start=128_000, price=Decimal('0.0844'))],
        ),
        output_mtok=Decimal('1.5825'),
    )
    assert models[1].prices == ModelPrice(
        input_mtok=TieredPrices(base=Decimal('1'), tiers=[Tier(start=100_000, price=Decimal('2'))]),
        output_mtok=Decimal('2'),
    )


@pytest.mark.parametrize(
    ('bad_row', 'error'),
    [
        ({'id': '', 'pricing': {'prompt': '0.000001'}}, 'Missing TrustedRouter model id'),
        ({'id': 'v/bool', 'pricing': {'prompt': True}}, 'Non-numeric prompt price for v/bool'),
        ({'id': 'v/str', 'pricing': {'prompt': 'varies'}}, 'Non-numeric prompt price for v/str'),
        ({'id': 'v/nan', 'pricing': {'prompt': 'NaN'}}, 'Non-finite prompt price for v/nan'),
        ({'id': 'v/tiers-type', 'pricing': {'prompt': '0.000001', 'tiers': 'bad'}}, 'Unexpected TrustedRouter tiers'),
        (
            {'id': 'v/tiers-short', 'pricing': {'prompt': '0.000001', 'tiers': [{'max_prompt_tokens': None}]}},
            'Unexpected TrustedRouter tiers',
        ),
        (
            {'id': 'v/tiers-entry', 'pricing': {'prompt': '0.000001', 'tiers': ['bad', {'max_prompt_tokens': None}]}},
            'Unexpected TrustedRouter tier entry',
        ),
        (
            {
                'id': 'v/tiers-final',
                'pricing': {
                    'prompt': '0.000001',
                    'tiers': [
                        {'max_prompt_tokens': 100_000, 'prompt': '0.000001'},
                        {'max_prompt_tokens': 200_000, 'prompt': '0.000002'},
                    ],
                },
            },
            'Unexpected TrustedRouter final tier',
        ),
        (
            {
                'id': 'v/tiers-order',
                'pricing': {
                    'prompt': '0.000001',
                    'tiers': [
                        {'max_prompt_tokens': 200_000, 'prompt': '0.000001'},
                        {'max_prompt_tokens': 100_000, 'prompt': '0.000002'},
                        {'max_prompt_tokens': None, 'prompt': '0.000003'},
                    ],
                },
            },
            'Unexpected TrustedRouter tier boundary',
        ),
        (
            {
                'id': 'v/tiers-nobase',
                'pricing': {
                    'prompt': '0.000001',
                    'tiers': [
                        {'max_prompt_tokens': 100_000, 'prompt': '0.000001'},
                        {'max_prompt_tokens': None, 'prompt': '0.000002', 'completion': '0.000004'},
                    ],
                },
            },
            'TrustedRouter tiers completion for v/tiers-nobase without a base rate',
        ),
    ],
)
def test_trustedrouter_skips_unreadable_rows_and_reads_the_others(
    bad_row: dict[str, Any], error: str, capsys: pytest.CaptureFixture[str]
) -> None:
    models = source_trustedrouter.parse_models([bad_row, SAMPLE_MODEL])

    assert [m.id for m in models] == ['anthropic/claude-sonnet-5']
    output = capsys.readouterr().out
    assert 'TrustedRouter: skipped a row it cannot read' in output
    assert error in output


def test_trustedrouter_upserts_dates_rate_changes_and_drops_redundant_cache(tmp_path: Path) -> None:
    provider_path = tmp_path / 'trustedrouter.yml'
    provider_path.write_text(
        """\
id: trustedrouter
name: TrustedRouter
api_pattern: 'https://api\\.trustedrouter\\.com(?:/|$)'
models:
  - id: anthropic/claude-sonnet-5
    match: {equals: anthropic/claude-sonnet-5}
    prices: {input_mtok: 3, output_mtok: 15}
"""
    )

    redundant_cache = {
        'id': 'vendor/same-cache',
        'pricing': {'prompt': '0.000001', 'completion': '0.000002', 'input_cache_read': '0.000001'},
    }
    models = source_trustedrouter.parse_models([SAMPLE_MODEL, redundant_cache])
    assert ProviderYaml(provider_path).upsert_models(models, source='TrustedRouter', min_count=1) == (1, 1)

    provider = ProviderYaml(provider_path).provider
    updated = provider.find_model('anthropic/claude-sonnet-5')
    assert updated is not None and isinstance(updated.prices, list)
    assert updated.prices[0].constraint is None
    assert updated.prices[1].constraint == StartDateConstraint(start_date=date.today())
    assert updated.prices[1].prices.input_mtok == Decimal('2.11')
    new_model = provider.find_model('vendor/same-cache')
    assert new_model is not None
    assert new_model.prices == ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))


def test_trustedrouter_main_rejects_malformed_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_get(_url: str, **_kwargs: Any) -> httpx2.Response:
        return httpx2.Response(200, json={'unexpected': True}, request=httpx2.Request('GET', _url))

    monkeypatch.setattr(httpx2, 'get', fake_get)
    provider_path = tmp_path / 'trustedrouter.yml'
    provider_path.write_text('id: trustedrouter\nname: TrustedRouter\napi_pattern: tr\nmodels: []\n')

    with pytest.raises(RuntimeError, match='did not contain a data list'):
        source_trustedrouter.main(provider_path)


@pytest.mark.vcr()
def test_trustedrouter_main_fetches_recorded_models(
    provider_snapshot: ProviderSnapshot, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = provider_snapshot('trustedrouter.yml')

    source_trustedrouter.main(provider_path)

    assert capsys.readouterr().out == 'TrustedRouter prices updated: 0 added, 548 updated\n'
