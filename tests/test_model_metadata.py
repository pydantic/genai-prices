from __future__ import annotations

from genai_prices import ModelMetadata, get_model_metadata


def test_get_canonical_model_metadata():
    assert get_model_metadata('anthropic/claude-sonnet-4-5') == ModelMetadata(
        context_window=200_000,
        max_output_tokens=64_000,
    )
    assert get_model_metadata('openai/gpt-5') == ModelMetadata(
        context_window=400_000,
        max_input_tokens=272_000,
        max_output_tokens=128_000,
    )


def test_model_ids_are_normalized():
    expected = get_model_metadata('anthropic/claude-sonnet-4-5')

    assert get_model_metadata('  ANTHROPIC/CLAUDE-SONNET-4-5  ') == expected


def test_unknown_models_return_none():
    assert get_model_metadata('') is None
    assert get_model_metadata('gpt-5') is None
    assert get_model_metadata('unknown/model') is None


def test_model_metadata_does_not_load_price_data():
    from genai_prices.data_snapshot import _bundled_snapshot
    from genai_prices.model_metadata import _get_bundled_model_metadata

    _get_bundled_model_metadata.cache_clear()
    _bundled_snapshot.cache_clear()

    assert get_model_metadata('anthropic/claude-sonnet-4-5') is not None
    assert _bundled_snapshot.cache_info().currsize == 0
