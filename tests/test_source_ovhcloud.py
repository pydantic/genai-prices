"""Tests for `prices.source_ovhcloud`.

Covers the payload-shaped half of the importer. `main()` itself writes a provider YAML file, so only the
pure `get_model_infos` extraction is exercised here, against a recorded slice of the real response.
"""

from __future__ import annotations

from decimal import Decimal

from inline_snapshot import snapshot

from prices.prices_types import ClauseEquals, ClauseOr, ModelPrice
from prices.source_ovhcloud import get_model_infos

from .fixtures import load_entries


def ovhcloud_models() -> list[dict[str, object]]:
    return load_entries('ovhcloud_models.json', 'data')


def test_ovhcloud_payload_converts_per_token_prices_to_mtok():
    infos = list(get_model_infos(ovhcloud_models()))

    assert {
        info.id: (info.prices.input_mtok, info.prices.output_mtok, info.context_window)
        for info in infos
        if isinstance(info.prices, ModelPrice)
    } == snapshot(
        {
            'bge-m3': (Decimal('0.01'), None, 8192),
            'gpt-oss-120b': (Decimal('0.09'), Decimal('0.47'), 131072),
            'Qwen3-32B': (Decimal('0.09'), Decimal('0.25'), 32768),
        }
    )


def test_ovhcloud_skips_models_priced_at_zero():
    """OVHcloud reports `0` for models it does not bill per token; those carry no price to record."""
    ids = [info.id for info in get_model_infos(ovhcloud_models())]

    assert 'whisper-large-v3-turbo' not in ids
    assert 'Qwen3Guard-Gen-8B' not in ids


def test_ovhcloud_mixed_case_id_also_matches_lowercase():
    infos = {info.id: info.match for info in get_model_infos(ovhcloud_models())}

    assert infos['Qwen3-32B'] == ClauseOr(
        or_=[  # pyright: ignore[reportCallIssue]
            ClauseEquals(equals='Qwen3-32B'),
            ClauseEquals(equals='qwen3-32b'),
        ]
    )
    assert infos['gpt-oss-120b'] == ClauseEquals(equals='gpt-oss-120b')
