import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from scripts.price_check_sources import (
    _SUPPLEMENTAL_HOST_EVIDENCE,
    load_provider_sources,
    official_source_hosts,
)

ROOT = Path(__file__).resolve().parents[1]


def _fixture_root(tmp_path: Path, provider_yaml: str, weekly_yaml: str) -> Path:
    providers = tmp_path / 'prices/providers'
    providers.mkdir(parents=True)
    (providers / 'sample.yml').write_text(provider_yaml)
    github = tmp_path / '.github'
    github.mkdir()
    (github / 'agentic-price-check-providers.yml').write_text(weekly_yaml)
    return tmp_path


def test_existing_provider_files_are_all_accounted_for() -> None:
    records = load_provider_sources(ROOT)
    provider_files = {path.relative_to(ROOT).as_posix() for path in (ROOT / 'prices/providers').glob('*.yml')}

    assert {record.file for record in records} == provider_files
    assert all(record.id and record.name and record.sources for record in records)


def test_weekly_sources_are_unioned_by_provider_file(tmp_path: Path) -> None:
    root = _fixture_root(
        tmp_path,
        'id: sample\nname: Sample\npricing_urls:\n  - https://pricing.example/current\nmodels:\n  - id: model\n    pricing_url: https://model-only.example/prices\n',
        'providers:\n  - name: Sample\n    file: prices/providers/sample.yml\n    sources:\n      - https://weekly.example/prices\n',
    )

    records = load_provider_sources(root)

    assert records[0].sources == ('https://pricing.example/current', 'https://weekly.example/prices')
    assert 'model-only.example' not in official_source_hosts(root)


def test_allowed_hosts_are_exact_source_hosts_and_explicit_supplements(tmp_path: Path) -> None:
    root = _fixture_root(
        tmp_path,
        'id: sample\nname: Sample\npricing_urls:\n  - https://source.example/prices\n  - https://source.example.evil.test/path\n',
        'providers: []\n',
    )

    assert official_source_hosts(root) == (
        'docs.aws.amazon.com',
        'docs.fireworks.ai',
        'docs.together.ai',
        'learn.microsoft.com',
        'source.example',
        'source.example.evil.test',
    )


@pytest.mark.parametrize(
    'source',
    [
        'http://source.example/prices',
        'https://user:secret@source.example/prices',
        'https://source.example:8443/prices',
    ],
)
@pytest.mark.parametrize('source_location', ['pricing_urls', 'weekly sources'])
def test_invalid_source_authorities_are_rejected(
    tmp_path: Path, source: str, source_location: str
) -> None:
    if source_location == 'pricing_urls':
        provider_yaml = f'id: sample\nname: Sample\npricing_urls:\n  - {source}\n'
        weekly_yaml = 'providers: []\n'
    else:
        provider_yaml = 'id: sample\nname: Sample\npricing_urls: []\n'
        weekly_yaml = (
            'providers:\n  - name: Sample\n    file: prices/providers/sample.yml\n'
            f'    sources:\n      - {source}\n'
        )
    root = _fixture_root(tmp_path, provider_yaml, weekly_yaml)

    with pytest.raises(ValueError, match='source URL'):
        load_provider_sources(root)


def test_loaded_snapshot_is_unchanged_after_source_file_edit(tmp_path: Path) -> None:
    root = _fixture_root(
        tmp_path,
        'id: sample\nname: Sample\npricing_urls:\n  - https://before.example/prices\n',
        'providers: []\n',
    )
    snapshot = load_provider_sources(root)
    provider_file = root / snapshot[0].file
    provider_file.write_text('id: sample\nname: Sample\npricing_urls:\n  - https://after.example/prices\n')

    assert snapshot[0].sources == ('https://before.example/prices',)
    assert load_provider_sources(root)[0].sources == ('https://after.example/prices',)


def test_weekly_snapshot_retains_mistral_redirect_host() -> None:
    hosts = official_source_hosts(ROOT)

    assert 'docs.mistral.ai' in hosts
    assert 'mistral.ai' in hosts


def test_supplemental_hosts_have_repository_evidence() -> None:
    for host, provider_file in _SUPPLEMENTAL_HOST_EVIDENCE.items():
        content = (ROOT / provider_file).read_text()
        urls = re.findall(r'https?://[A-Za-z0-9.-]+', content)
        content_hosts = {urlparse(url).hostname for url in urls}

        assert host in content_hosts, f'{provider_file} has no URL hosted at {host}'
