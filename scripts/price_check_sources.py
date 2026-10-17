"""Load the fixed set of official sources available to a price check."""

import argparse
import json
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, HttpUrl, StrictStr, StringConstraints, TypeAdapter

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
_http_url_adapter = TypeAdapter(HttpUrl)


class _ProviderFile(BaseModel):
    model_config = ConfigDict(extra='ignore')

    id: StrictStr
    name: StrictStr
    pricing_urls: list[StrictStr]


class _WeeklyProvider(BaseModel):
    model_config = ConfigDict(extra='ignore')

    file: StrictStr
    sources: list[StrictStr]


class _WeeklyManifest(BaseModel):
    model_config = ConfigDict(extra='ignore')

    providers: list[_WeeklyProvider]


class ProviderSource(BaseModel):
    """A provider's checked source links."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    file: str
    sources: tuple[str, ...]


class PendingBackfill(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)

    request_id: Annotated[StrictStr, StringConstraints(min_length=1)]
    target_model: Annotated[StrictStr, StringConstraints(min_length=1)]
    provider_id: Annotated[StrictStr, StringConstraints(min_length=1)]


def pending_backfill_rows(pending: object, known_ids: set[str]) -> list[PendingBackfill]:
    """Validate the receiver's selected backlog without interpreting its extra fields."""
    try:
        rows = TypeAdapter(list[PendingBackfill]).validate_python(pending, strict=True)
    except ValueError as exc:
        raise ValueError('Pending price-check backfill rows are invalid') from exc
    unknown_ids = {row.provider_id for row in rows} - known_ids - {'_discovery'}
    if unknown_ids:
        raise ValueError(f'Pending price-check backfill has unknown provider IDs: {sorted(unknown_ids)}')
    return rows


def weekly_provider_sources(root: Path = DEFAULT_ROOT) -> tuple[ProviderSource, ...]:
    """Select the weekly manifest's exact required URLs, rather than every allowed URL."""
    records = {record.file: record for record in load_provider_sources(root)}
    manifest = _WeeklyManifest.model_validate(_load_document(root / '.github/agentic-price-check-providers.yml'))
    unknown_files = {provider.file for provider in manifest.providers} - records.keys()
    if unknown_files:
        raise ValueError(f'Weekly manifest references unknown provider files: {sorted(unknown_files)}')
    return tuple(
        records[provider.file].model_copy(update={'sources': tuple(sorted(set(provider.sources)))})
        for provider in manifest.providers
    )


# These exact hosts have official links in their provider YAML files. They are
# listed explicitly so model-level links are never discovered or trusted by parsing.
_SUPPLEMENTAL_HOST_EVIDENCE = {
    'docs.aws.amazon.com': 'prices/providers/aws.yml',
    'learn.microsoft.com': 'prices/providers/azure.yml',
    'docs.together.ai': 'prices/providers/together.yml',
    'docs.fireworks.ai': 'prices/providers/fireworks.yml',
}


def _validated_source(source: str, file: str) -> HttpUrl:
    try:
        url = _http_url_adapter.validate_python(source)
    except ValueError as exc:
        raise ValueError(f'{file}: invalid source URL {source!r}') from exc
    if url.scheme != 'https' or url.username is not None or url.password is not None:
        raise ValueError(f'{file}: source URL must use HTTPS without credentials: {source!r}')
    if url.port not in (None, 443):
        raise ValueError(f'{file}: source URL must use port 443: {source!r}')
    if url.host is None:
        raise ValueError(f'{file}: source URL must have a host: {source!r}')
    return url


def _load_document(path: Path) -> object:
    return yaml.safe_load(path.read_text())


def load_provider_sources(root: Path = DEFAULT_ROOT) -> tuple[ProviderSource, ...]:
    """Load and validate provider sources, including weekly sources matching each file."""
    providers_dir = root / 'prices/providers'
    manifest_path = root / '.github/agentic-price-check-providers.yml'
    manifest = _WeeklyManifest.model_validate(_load_document(manifest_path))

    weekly_sources: dict[str, set[str]] = {}
    for provider in manifest.providers:
        weekly_sources.setdefault(provider.file, set()).update(provider.sources)

    records: list[ProviderSource] = []
    for path in sorted(providers_dir.glob('*.yml')):
        relative_path = path.relative_to(root).as_posix()
        provider = _ProviderFile.model_validate(_load_document(path))
        sources = set(provider.pricing_urls) | weekly_sources.get(relative_path, set())
        for source in sorted(sources):
            _validated_source(source, relative_path)
        records.append(
            ProviderSource(
                id=provider.id,
                name=provider.name,
                file=relative_path,
                sources=tuple(sorted(sources)),
            )
        )
    return tuple(records)


def _hosts_for(records: tuple[ProviderSource, ...]) -> tuple[str, ...]:
    hosts = {
        url.host
        for provider in records
        for source in provider.sources
        if (url := _validated_source(source, provider.file)).host is not None
    }
    hosts.update(_SUPPLEMENTAL_HOST_EVIDENCE)
    return tuple(sorted(hosts))


def official_source_hosts(root: Path = DEFAULT_ROOT) -> tuple[str, ...]:
    """Return the exact HTTPS hosts allowed for official source fetches."""
    return _hosts_for(load_provider_sources(root))


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    records = load_provider_sources(args.root)
    print(
        json.dumps(
            {
                'providers': [record.model_dump(mode='json') for record in records],
                'hosts': list(_hosts_for(records)),
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    _main()
