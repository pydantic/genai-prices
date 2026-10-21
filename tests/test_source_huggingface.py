"""Tests for `prices.source_huggingface` against a recorded API response."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from shutil import copyfile

import pytest
from inline_snapshot import snapshot

from prices import source_huggingface
from prices.prices_types import ModelPrice
from prices.source_huggingface import get_model_infos
from prices.utils import package_dir

from .fixtures import load_entries


def huggingface_models() -> list[dict[str, object]]:
    return load_entries('huggingface_models.json', 'data')


def test_huggingface_payload_extracts_models_for_provider():
    infos = list(get_model_infos(huggingface_models(), 'together'))

    assert {
        info.id: (info.prices.input_mtok, info.prices.output_mtok, info.context_window)
        for info in infos
        if isinstance(info.prices, ModelPrice)
    } == snapshot(
        {
            'moonshotai/Kimi-K3': (Decimal('3'), Decimal('15'), 1000000),
            'zai-org/GLM-5.2': (Decimal('1.4'), Decimal('4.4'), 512000),
            'thinkingmachines/Inkling': (Decimal('1'), Decimal('4.05'), 524288),
            'prism-ml/Ternary-Bonsai-27B-gguf': (None, None, 262144),
        }
    )


def test_huggingface_model_name_strips_owner_prefix():
    infos = {info.id: info.name for info in get_model_infos(huggingface_models(), 'together')}

    assert infos['moonshotai/Kimi-K3'] == 'Kimi-K3'
    assert infos['zai-org/GLM-5.2'] == 'GLM-5.2'


def test_huggingface_skips_providers_without_pricing():
    """`thinkingmachines/Inkling` is listed on fireworks-ai with no `pricing` block, so it must not appear."""
    ids = [info.id for info in get_model_infos(huggingface_models(), 'fireworks-ai')]

    assert ids == snapshot(['moonshotai/Kimi-K3', 'zai-org/GLM-5.2'])


def test_huggingface_returns_nothing_for_absent_provider():
    assert list(get_model_infos(huggingface_models(), 'not-a-provider')) == []


@pytest.mark.vcr()
def test_huggingface_main_updates_existing_providers_and_skips_new_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copyfile(package_dir / 'providers/huggingface_groq.yml', tmp_path / 'huggingface_groq.yml')

    source_huggingface.main(tmp_path)

    assert capsys.readouterr().out == snapshot("""\
HuggingFace (baseten) skipped: huggingface_baseten.yml does not exist, add it with the add-provider skill
HuggingFace (cerebras) skipped: huggingface_cerebras.yml does not exist, add it with the add-provider skill
HuggingFace (deepinfra) skipped: huggingface_deepinfra.yml does not exist, add it with the add-provider skill
HuggingFace (fireworks-ai) skipped: huggingface_fireworks-ai.yml does not exist, add it with the add-provider skill
HuggingFace (groq) prices updated: 0 added, 2 updated
HuggingFace (novita) skipped: huggingface_novita.yml does not exist, add it with the add-provider skill
HuggingFace (nscale) skipped: huggingface_nscale.yml does not exist, add it with the add-provider skill
HuggingFace (ovhcloud) skipped: huggingface_ovhcloud.yml does not exist, add it with the add-provider skill
HuggingFace (publicai) skipped: huggingface_publicai.yml does not exist, add it with the add-provider skill
HuggingFace (scaleway) skipped: huggingface_scaleway.yml does not exist, add it with the add-provider skill
HuggingFace (together) skipped: huggingface_together.yml does not exist, add it with the add-provider skill
""")
    assert [path.name for path in tmp_path.iterdir()] == ['huggingface_groq.yml']


@pytest.mark.vcr()
def test_huggingface_main_rejects_a_truncated_router(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(source_huggingface, 'MIN_MODEL_COUNT', 100_000)

    with pytest.raises(RuntimeError, match='expected at least 100000'):
        source_huggingface.main(tmp_path)

    assert list(tmp_path.iterdir()) == []
