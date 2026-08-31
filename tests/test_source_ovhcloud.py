"""Tests for `prices.source_ovhcloud` against a recorded API response."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from inline_snapshot import snapshot

from prices import source_ovhcloud
from prices.prices_types import ClauseEquals, ClauseOr, ModelPrice, UsageExtractor
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


def test_ovhcloud_main_writes_and_collapses_generated_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, list[dict[str, object]]]:
            return {'data': ovhcloud_models()}

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

    source_file = tmp_path / 'src' / 'prices' / 'source_ovhcloud.py'
    source_file.parent.mkdir(parents=True)
    providers_dir = tmp_path / 'providers'
    providers_dir.mkdir()

    def fake_path(_: str) -> Path:
        return source_file

    def fake_get(url: str, *, timeout: float) -> FakeResponse:
        assert url == 'https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/models'
        assert timeout == 30.0
        return FakeResponse()

    monkeypatch.setattr(source_ovhcloud, 'Path', fake_path)
    monkeypatch.setattr(source_ovhcloud, 'ProviderYaml', FakeProviderYaml)
    monkeypatch.setattr(httpx2, 'get', fake_get)
    collapse_results = iter([True, False])

    def fake_collapse(_: FakeProviderYaml) -> bool:
        return next(collapse_results)

    monkeypatch.setattr(source_ovhcloud, 'collapse_provider', fake_collapse)

    source_ovhcloud.main()
    source_ovhcloud.main()

    output_path = providers_dir / 'ovhcloud.yml'
    assert output_path.is_file()
    assert 'gpt-oss-120b' in output_path.read_text()
    assert output_path.read_text().count('api_flavor: default') == 1
    assert output_path.read_text().count('api_flavor: chat') == 1
    output = capsys.readouterr().out
    assert output.count('Created ') == 2
    assert output.count('Collapsed and saved ') == 1
    assert len([provider_yaml for provider_yaml in FakeProviderYaml.instances if provider_yaml.saved]) == 1


def test_ovhcloud_main_exits_nonzero_on_request_errors(monkeypatch: pytest.MonkeyPatch):
    def fake_get(_: str, *, timeout: float) -> None:
        assert timeout == 30.0
        raise RuntimeError('not available')

    monkeypatch.setattr(httpx2, 'get', fake_get)

    with pytest.raises(SystemExit, match='Error fetching OVHcloud AI Endpoints models: not available'):
        source_ovhcloud.main()


def test_ovhcloud_main_exits_nonzero_when_no_models_have_prices(monkeypatch: pytest.MonkeyPatch):
    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, list[dict[str, object]]]:
            return {
                'data': [
                    {'id': 'without-pricing'},
                    {'id': 'free', 'pricing': {'prompt': '0', 'completion': '0'}},
                ]
            }

    def fake_get(_: str, *, timeout: float) -> FakeResponse:
        assert timeout == 30.0
        return FakeResponse()

    monkeypatch.setattr(httpx2, 'get', fake_get)

    with pytest.raises(SystemExit, match='No valid models found with pricing information'):
        source_ovhcloud.main()
