"""Tests for `prices.source_huggingface` against a recorded API response."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from inline_snapshot import snapshot

from prices import source_huggingface
from prices.prices_types import ModelPrice, UsageExtractor
from prices.source_huggingface import get_model_infos
from prices.write_guard import ALLOW_MODEL_COUNT_DROP_ENV

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


def test_huggingface_main_writes_and_collapses_generated_providers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Exercise the file-writing importer while keeping its generated YAML in a temporary directory."""

    class FakeResponse:
        def json(self) -> dict[str, list[dict[str, object]]]:
            models = huggingface_models()
            unpriced_model: dict[str, object] = {
                'id': 'unpriced/model',
                'owned_by': 'unpriced',
                'providers': [{'provider': 'unpriced'}],
            }
            models.append(unpriced_model)
            return {'data': models}

    class FakeProviderYaml:
        instances: list[FakeProviderYaml] = []

        def __init__(self, path: Path) -> None:
            self.path = path
            self.provider = SimpleNamespace(
                extractors=[UsageExtractor(api_flavor='chat', root='usage', mappings=[])],
            )
            self.saved = False
            self.instances.append(self)

        def save(self) -> None:
            self.saved = True

    source_file = tmp_path / 'src' / 'prices' / 'source_huggingface.py'
    source_file.parent.mkdir(parents=True)
    providers_dir = tmp_path / 'providers'
    providers_dir.mkdir()

    def fake_path(_: str) -> Path:
        return source_file

    def fake_get(url: str) -> FakeResponse:
        assert url == 'https://router.huggingface.co/v1/models'
        return FakeResponse()

    def fake_collapse(provider_yaml: FakeProviderYaml) -> bool:
        return provider_yaml.path.stem == 'huggingface_together'

    monkeypatch.setattr(source_huggingface, 'Path', fake_path)
    monkeypatch.setattr(source_huggingface, 'ProviderYaml', FakeProviderYaml)
    monkeypatch.setattr(httpx2, 'get', fake_get)
    monkeypatch.setattr(source_huggingface, 'collapse_provider', fake_collapse)

    source_huggingface.main()

    assert {path.name for path in providers_dir.iterdir()} == {
        'huggingface_fireworks-ai.yml',
        'huggingface_together.yml',
    }
    assert 'moonshotai/Kimi-K3' in (providers_dir / 'huggingface_together.yml').read_text()
    together_yaml = (providers_dir / 'huggingface_together.yml').read_text()
    assert together_yaml.count('api_flavor: default') == 1
    assert together_yaml.count('api_flavor: chat') == 1
    assert [provider_yaml.path.name for provider_yaml in FakeProviderYaml.instances if provider_yaml.saved] == [
        'huggingface_together.yml'
    ]


def test_huggingface_main_exits_nonzero_on_empty_payload(monkeypatch: pytest.MonkeyPatch):
    class FakeResponse:
        def json(self) -> dict[str, list[dict[str, object]]]:
            return {'data': []}

    def fake_get(_url: str) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(httpx2, 'get', fake_get)

    with pytest.raises(SystemExit, match='HuggingFace router returned no models'):
        source_huggingface.main()


def test_huggingface_main_checks_all_providers_before_writing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv(ALLOW_MODEL_COUNT_DROP_ENV, raising=False)

    class FakeResponse:
        def json(self) -> dict[str, list[dict[str, object]]]:
            return {'data': huggingface_models()}

    class FakeProviderYaml:
        def __init__(self, path: Path) -> None:
            assert path.name == 'openai.yml'
            self.provider = SimpleNamespace(
                extractors=[UsageExtractor(api_flavor='chat', root='usage', mappings=[])],
            )

    source_file = tmp_path / 'src' / 'prices' / 'source_huggingface.py'
    source_file.parent.mkdir(parents=True)
    providers_dir = tmp_path / 'providers'
    providers_dir.mkdir()
    existing_path = providers_dir / 'huggingface_together.yml'
    models = ''.join(
        f'  - id: model-{i}\n    match:\n      equals: model-{i}\n    prices:\n      input_mtok: 1\n' for i in range(10)
    )
    existing = (
        f'id: huggingface_together\nname: HuggingFace Together\napi_pattern: https://example.com\nmodels:\n{models}'
    )
    existing_path.write_text(existing)

    def fake_path(_: str) -> Path:
        return source_file

    def fake_get(_: str) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(source_huggingface, 'Path', fake_path)
    monkeypatch.setattr(source_huggingface, 'ProviderYaml', FakeProviderYaml)
    monkeypatch.setattr(httpx2, 'get', fake_get)

    with pytest.raises(
        SystemExit,
        match=r'HuggingFace router \(together\) returned 4 priced models but huggingface_together.yml has 10',
    ):
        source_huggingface.main()

    assert list(providers_dir.iterdir()) == [existing_path]
    assert existing_path.read_text() == existing
