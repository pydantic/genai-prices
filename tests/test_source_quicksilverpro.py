"""Tests for `prices.source_quicksilverpro` against a recorded `pricing.json`."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from inline_snapshot import snapshot

from prices import source_quicksilverpro
from prices.prices_types import ClauseEquals, ModelPrice
from prices.source_quicksilverpro import get_model_infos

from .fixtures import load_entries


def quicksilverpro_models() -> list[dict[str, object]]:
    return load_entries('quicksilverpro_pricing.json', 'models')


def test_quicksilverpro_catalog_rates_are_already_per_mtok():
    infos = list(get_model_infos(quicksilverpro_models()))

    assert {
        info.id: (
            info.prices.input_mtok,
            info.prices.cache_read_mtok,
            info.prices.cache_write_mtok,
            info.prices.output_mtok,
            info.context_window,
        )
        for info in infos
        if isinstance(info.prices, ModelPrice)
    } == snapshot(
        {
            'gpt-5.6-sol': (Decimal('4'), Decimal('0.4'), Decimal('5'), Decimal('24'), 1048576),
            'deepseek-v4-flash': (Decimal('0.112'), Decimal('0.0144'), None, Decimal('0.224'), 1048576),
            'gemini-3-pro-image': (Decimal('1.7'), None, None, Decimal('10.2'), 1048576),
            'gemini-3-flash-preview': (Decimal('0.425'), None, None, Decimal('2.55'), 1048576),
            'muse-spark-1.2': (Decimal('1'), Decimal('0.12'), None, Decimal('3.4'), 1048576),
        }
    )


def test_quicksilverpro_image_output_rate_is_recorded():
    infos = {info.id: info for info in get_model_infos(quicksilverpro_models())}
    prices = infos['gemini-3-pro-image'].prices
    assert isinstance(prices, ModelPrice)

    assert prices.model_dump(exclude_none=True)['output_image_mtok'] == Decimal('102')


def test_quicksilverpro_skips_per_image_models():
    """FLUX is billed per image, which has no unit in the registry."""
    ids = [info.id for info in get_model_infos(quicksilverpro_models())]

    assert 'flux.2-pro' not in ids


def test_quicksilverpro_flags_deprecated_models():
    infos = {info.id: info for info in get_model_infos(quicksilverpro_models())}

    assert infos['gemini-3-flash-preview'].deprecated is True
    assert infos['gpt-5.6-sol'].deprecated is None
    assert infos['gpt-5.6-sol'].match == ClauseEquals(equals='gpt-5.6-sol')
    assert infos['gpt-5.6-sol'].name == 'GPT-5.6 Sol'


@pytest.mark.vcr()
def test_quicksilverpro_main_fetches_recorded_catalog(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    provider_path = tmp_path / 'quicksilverpro.yml'
    provider_path.write_text('id: quicksilverpro\nname: QuickSilver Pro\napi_pattern: quicksilverpro\nmodels: []\n')

    source_quicksilverpro.main(provider_path)

    assert capsys.readouterr().out == snapshot('QuickSilver Pro prices updated: 68 added, 0 updated\n')


def test_quicksilverpro_skips_token_models_without_rates():
    assert list(get_model_infos([{'id': 'free', 'pricing_unit': 'tokens', 'input_per_1m': 0}])) == []
