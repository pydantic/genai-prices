from __future__ import annotations

from decimal import Decimal

import pytest
from inline_snapshot import snapshot
from pydantic import TypeAdapter, ValidationError

from prices.source_litellm import LiteLLMModel, get_litellm_prices, lite_llm_response_schema

from .fixtures import capture_source_prices, load_mapping, load_payload, mock_httpx_get

LITELLM_URL = 'https://raw.githubusercontent.com/BerriAI/litellm/refs/heads/main/model_prices_and_context_window.json'

# LiteLLM's payload is keyed by model name but carries two entries that are not models: a documentation
# template whose values are prose placeholders, and a block of routing rules. `OnErrorOmit` exists to
# skip exactly these — any *other* key it starts skipping is silent data loss.
NON_MODEL_ENTRIES = {'sample_spec', 'fallback_generalizations'}

_strict_model_schema = TypeAdapter(LiteLLMModel)


@pytest.mark.parametrize(
    ('reasoning_per_token', 'expected_reasoning_mtok'),
    [
        (Decimal('0.000003'), Decimal('3')),
        (Decimal('0.000002'), None),
        (None, None),
    ],
)
def test_litellm_model_price_preserves_only_distinct_reasoning_rate(
    reasoning_per_token: Decimal | None,
    expected_reasoning_mtok: Decimal | None,
):
    model = LiteLLMModel(
        input_cost_per_token=Decimal('0.000001'),
        output_cost_per_token=Decimal('0.000002'),
        output_cost_per_reasoning_token=reasoning_per_token,
        litellm_provider='test',
    )

    expected = {'input_mtok': Decimal('1'), 'output_mtok': Decimal('2')}
    if expected_reasoning_mtok is not None:
        expected['output_reasoning_mtok'] = expected_reasoning_mtok
    assert model.model_price().model_dump(exclude_none=True) == expected


def test_litellm_payload_drops_no_models():
    """`lite_llm_response_schema` uses `OnErrorOmit`, so schema drift costs us models with no error at all.

    Counting raw entries against decoded ones is the assertion that turns that silence into a failure.
    """
    raw = load_mapping('litellm_models.json')
    decoded = lite_llm_response_schema.validate_json(load_payload('litellm_models.json'))

    expected_models = set(raw) - NON_MODEL_ENTRIES
    assert set(decoded) == expected_models
    assert len(decoded) == len(raw) - len(NON_MODEL_ENTRIES)


def test_litellm_payload_models_also_decode_strictly():
    """Every real model must satisfy the schema *without* `OnErrorOmit` covering for it."""
    raw = load_mapping('litellm_models.json')

    for name, entry in raw.items():
        if name in NON_MODEL_ENTRIES:
            continue
        _strict_model_schema.validate_python(entry)


@pytest.mark.parametrize('name', sorted(NON_MODEL_ENTRIES))
def test_litellm_non_model_entries_are_the_only_expected_drops(name: str):
    """Pins *why* `OnErrorOmit` is tolerable here: these two entries are not models and cannot validate."""
    entry = load_mapping('litellm_models.json')[name]

    with pytest.raises(ValidationError):
        _strict_model_schema.validate_python(entry)


def test_litellm_prices_map_providers_and_skip_unpriced(monkeypatch: pytest.MonkeyPatch):
    """Runs the importer end-to-end on the recorded payload, capturing the write instead of performing it."""
    mock_httpx_get(monkeypatch, expected_url=LITELLM_URL, content=load_payload('litellm_models.json'))
    written = capture_source_prices(monkeypatch)

    get_litellm_prices()

    assert {
        provider: {name: price.model_dump(exclude_none=True) for name, price in models.items()}
        for provider, models in written['litellm'].items()
    } == snapshot(
        {
            'google': {
                'gemini/gemini-robotics-er-1.5-preview': {
                    'input_mtok': Decimal('0.30'),
                    'output_mtok': Decimal('2.50'),
                },
                'vertex_ai/claude-3-5-haiku': {'input_mtok': Decimal('1'), 'output_mtok': Decimal('5')},
            },
            'aws': {'us.writer.palmyra-x4-v1:0': {'input_mtok': Decimal('2.50'), 'output_mtok': Decimal('10')}},
            'x-ai': {'xai/grok-2': {'input_mtok': Decimal('2'), 'output_mtok': Decimal('10')}},
            'azure': {'azure/eu/gpt-4o-2024-08-06': {'input_mtok': Decimal('2.75'), 'output_mtok': Decimal('11')}},
        }
    )


def test_litellm_prices_skip_entries_the_importer_cannot_use(monkeypatch: pytest.MonkeyPatch):
    """The recorded payload deliberately includes entries the importer must drop, so the mapping above is
    an assertion about filtering rather than a coincidence of the sample."""
    mock_httpx_get(monkeypatch, expected_url=LITELLM_URL, content=load_payload('litellm_models.json'))
    written = capture_source_prices(monkeypatch)

    get_litellm_prices()

    imported = {name for models in written['litellm'].values() for name in models}
    # no per-token cost at all, so there is no price to record
    assert '1024-x-1024/50-steps/stability.stable-diffusion-xl-v1' not in imported
    # `litellm_provider` values with no provider YAML of their own
    assert 'ollama/codegeex4' not in imported
    assert 'dashscope/qwen-plus-2025-04-28' not in imported
