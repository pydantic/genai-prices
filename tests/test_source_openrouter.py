from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from prices.prices_types import ClauseEquals, ClauseOr, ModelPrice
from prices.source_openrouter import (
    OpenRouterModel,
    OpenRouterPricing,
    OpenRouterResponse,
    report_unknown_pricing_fields,
)

from .fixtures import load_entries, load_payload

# The exact pricing keys OpenRouter added without notice, which `extra='forbid'` turned into 115
# `extra_forbidden` errors and a fully aborted pull (#532).
UNDECLARED_PRICING_FIELDS = {
    'overrides': None,
    'input_cache_write_1h': '0.000006',
    'input_audio_cache': '0.0000005',
    'image_output': '0.03',
    'audio_output': '0.00008',
}


def openrouter_model(
    model_id: str,
    *,
    canonical_slug: str | None = None,
    pricing: OpenRouterPricing | None = None,
) -> OpenRouterModel:
    return OpenRouterModel(
        id=model_id,
        canonical_slug=canonical_slug or model_id,
        name=f'Test: {model_id}',
        created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        description='Test description\n\nMore details',
        context_length=1_000_000,
        pricing=pricing or OpenRouterPricing(prompt=Decimal('0.000001'), completion=Decimal('0.000002')),
        supported_parameters=[],
    )


def pricing_with_extras(extras: dict[str, object]) -> OpenRouterPricing:
    return OpenRouterPricing.model_validate({'prompt': '0.000001', 'completion': '0.000002', **extras})


@pytest.mark.parametrize('model_id', ['google/gemini-3.5-flash', '~anthropic/claude-fable-latest'])
def test_openrouter_provider_model_info_preserves_api_model_id(model_id: str):
    model_info = openrouter_model(model_id).model_info(inc_description=False, strip_provider=False)

    assert model_info.id == model_id
    assert model_info.match == ClauseEquals(equals=model_id)
    assert model_info.description is None


def test_openrouter_provider_model_info_matches_canonical_slug_alias():
    model_info = openrouter_model(
        'moonshotai/kimi-k2.7-code',
        canonical_slug='moonshotai/kimi-k2.7-code-20260612',
    ).model_info(inc_description=False, strip_provider=False)

    assert model_info.id == 'moonshotai/kimi-k2.7-code'
    assert model_info.match == ClauseOr(
        or_=[  # pyright: ignore[reportCallIssue]
            ClauseEquals(equals='moonshotai/kimi-k2.7-code'),
            ClauseEquals(equals='moonshotai/kimi-k2.7-code-20260612'),
        ]
    )
    assert model_info.description is None


@pytest.mark.parametrize(
    ('model_id', 'native_model_id'),
    [
        ('google/gemini-3.5-flash', 'gemini-3.5-flash'),
        ('~anthropic/claude-fable-latest', 'claude-fable-latest'),
    ],
)
def test_native_provider_model_info_uses_native_model_id(model_id: str, native_model_id: str):
    model_info = openrouter_model(model_id).model_info()

    assert model_info.id == native_model_id
    assert model_info.match == ClauseEquals(equals=native_model_id)
    assert model_info.description == 'Test description'


@pytest.mark.parametrize(
    ('reasoning_per_token', 'expected_reasoning_mtok'),
    [
        (Decimal('0.000003'), Decimal('3')),
        (Decimal('0.000002'), None),
        (None, None),
    ],
)
def test_openrouter_model_price_preserves_only_distinct_reasoning_rate(
    reasoning_per_token: Decimal | None,
    expected_reasoning_mtok: Decimal | None,
):
    price = OpenRouterPricing(
        prompt=Decimal('0.000001'),
        completion=Decimal('0.000002'),
        internal_reasoning=reasoning_per_token,
    ).model_price()

    expected = {'input_mtok': Decimal('1'), 'output_mtok': Decimal('2')}
    if expected_reasoning_mtok is not None:
        expected['output_reasoning_mtok'] = expected_reasoning_mtok
    assert price.model_dump(exclude_none=True) == expected


@pytest.mark.parametrize(
    ('canonical_slug', 'expected_provider_id'),
    [
        ('mistralai/mistral-large', 'mistral'),
        ('microsoft/phi-4', 'azure'),
        ('amazon/nova-pro', 'aws'),
        ('anthropic/claude-opus-5', 'anthropic'),
    ],
)
def test_openrouter_provider_id_applies_vendor_aliases(canonical_slug: str, expected_provider_id: str):
    model = openrouter_model(canonical_slug, canonical_slug=canonical_slug)

    assert model.provider_id() == expected_provider_id


def test_openrouter_provider_name_is_the_segment_before_the_colon():
    assert openrouter_model('anthropic/claude-opus-5').provider_name() == 'Test'


def test_openrouter_pricing_tolerates_unknown_fields():
    """A new OpenRouter pricing dimension must not abort the pull, and must not shift known prices (#532)."""
    baseline = OpenRouterPricing(
        prompt=Decimal('0.000001'),
        completion=Decimal('0.000002'),
        input_cache_read=Decimal('0.0000001'),
    )
    with_extras = OpenRouterPricing.model_validate(
        {
            'prompt': '0.000001',
            'completion': '0.000002',
            'input_cache_read': '0.0000001',
            **UNDECLARED_PRICING_FIELDS,
        }
    )

    assert set(with_extras.model_extra or {}) == set(UNDECLARED_PRICING_FIELDS)
    assert with_extras.model_price() == baseline.model_price()
    assert with_extras.has_negative_price() is False


def test_report_unknown_pricing_fields(capsys: pytest.CaptureFixture[str]):
    models = [
        openrouter_model('a/one', pricing=pricing_with_extras({'image_output': '0.03', 'input_audio_cache': '0.5'})),
        openrouter_model('a/two', pricing=pricing_with_extras({'input_audio_cache': '0.5'})),
        openrouter_model('a/three', pricing=pricing_with_extras({})),
    ]

    assert report_unknown_pricing_fields(models) == snapshot({'image_output': 1, 'input_audio_cache': 2})
    assert capsys.readouterr().out == snapshot("""\
OpenRouter sent pricing fields we ignore:
  input_audio_cache: 2 models
  image_output: 1 models

""")


def test_report_unknown_pricing_fields_silent_when_nothing_unknown(capsys: pytest.CaptureFixture[str]):
    assert report_unknown_pricing_fields([openrouter_model('a/one')]) == {}
    assert capsys.readouterr().out == ''


def test_openrouter_payload_decodes_strictly():
    """The recorded response must decode with nothing dropped — `OpenRouterResponse.data` is not lenient,
    so a shape change upstream surfaces here as a hard failure rather than as missing models."""
    raw_entries = load_entries('openrouter_models.json', 'data')
    response = OpenRouterResponse.model_validate_json(load_payload('openrouter_models.json'))

    assert len(response.data) == len(raw_entries)
    assert [model.id for model in response.data] == snapshot(
        [
            'anthropic/claude-opus-5',
            'google/gemini-3-pro-image',
            '~google/gemini-pro-latest',
            'openai/gpt-audio',
            'perplexity/sonar-deep-research',
            'openrouter/auto-beta',
        ]
    )


def test_openrouter_payload_carries_undeclared_pricing_fields(capsys: pytest.CaptureFixture[str]):
    """Guards the fixture itself: if it stopped containing real undeclared fields,
    `test_openrouter_payload_decodes_strictly` would pass for the wrong reason."""
    response = OpenRouterResponse.model_validate_json(load_payload('openrouter_models.json'))

    counts = report_unknown_pricing_fields(response.data)

    assert counts == snapshot(
        {
            'input_cache_write_1h': 1,
            'image_output': 1,
            'input_audio_cache': 2,
            'overrides': 1,
            'audio_output': 1,
        }
    )
    assert set(counts) == set(UNDECLARED_PRICING_FIELDS)
    assert 'input_audio_cache: 2 models' in capsys.readouterr().out


def test_openrouter_payload_builds_model_info_for_every_priced_model():
    response = OpenRouterResponse.model_validate_json(load_payload('openrouter_models.json'))

    negative = [model.id for model in response.data if model.pricing.has_negative_price()]
    assert negative == snapshot(['openrouter/auto-beta'])

    priced = [model.model_info() for model in response.data if not model.pricing.has_negative_price()]
    assert {info.id: info.prices.input_mtok for info in priced if isinstance(info.prices, ModelPrice)} == snapshot(
        {
            'claude-opus-5': Decimal('5'),
            'gemini-3-pro-image': Decimal('2'),
            'gemini-pro-latest': Decimal('2'),
            'gpt-audio': Decimal('2.5'),
            'sonar-deep-research': Decimal('2'),
        }
    )
