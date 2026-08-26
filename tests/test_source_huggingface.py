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
            self.data: dict[str, object] = {'id': path.stem, 'models': []}
            self.saved = False
            self.instances.append(self)

        def save(self) -> None:
            self.saved = True

    source_file = tmp_path / 'src' / 'prices' / 'source_huggingface.py'
    source_file.parent.mkdir(parents=True)
    providers_dir = tmp_path / 'providers'
    providers_dir.mkdir()
    (providers_dir / 'huggingface_inactive.yml').write_text('stale generated provider')

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
        'huggingface_inactive.yml',
        'huggingface_together.yml',
    }
    together_yaml = (providers_dir / 'huggingface_together.yml').read_text()
    assert 'moonshotai/Kimi-K3' in together_yaml
    assert together_yaml.count('root: usage') == 2
    assert together_yaml.count('api_flavor: chat') == 1
    assert 'api_flavor: default' not in together_yaml
    assert [provider_yaml.path.name for provider_yaml in FakeProviderYaml.instances if provider_yaml.saved] == [
        'huggingface_inactive.yml',
        'huggingface_together.yml',
    ]

    [inactive_provider] = [
        provider_yaml
        for provider_yaml in FakeProviderYaml.instances
        if provider_yaml.path.name == 'huggingface_inactive.yml'
    ]
    extractors = inactive_provider.data['extractors']
    assert extractors == [
        {'root': 'usage', 'mappings': [], 'model_path': 'model'},
        {'api_flavor': 'chat', 'root': 'usage', 'mappings': [], 'model_path': 'model'},
    ]
