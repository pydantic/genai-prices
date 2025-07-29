from __future__ import annotations as _annotations

import asyncio
import re
import warnings
from abc import ABC, abstractmethod
from concurrent import futures
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cache
from typing import TYPE_CHECKING

import httpx
from pydantic import ValidationError

from . import types
from .types import normalize_provider, normalize_model

if TYPE_CHECKING:
    from .sources import DataSnapshot

__all__ = (
    'DEFAULT_AUTO_UPDATE_MAX_AGE',
    'DEFAULT_AUTO_UPDATE_URL',
    'AsyncSource',
    'AutoUpdateAsyncSource',
    'auto_update_async_source',
    'SyncSource',
    'AutoUpdateSyncSource',
    'DataSnapshot',
)

DEFAULT_AUTO_UPDATE_MAX_AGE = timedelta(hours=1)
DEFAULT_AUTO_UPDATE_FETCH_AGE = timedelta(minutes=30)
DEFAULT_AUTO_UPDATE_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json'


class AsyncSource(ABC):
    @abstractmethod
    async def fetch(self) -> 'DataSnapshot | None':
        """Try to fetch a new snapshot if required.

        This method should check if any relevant cached has expired, if not it should return `None`.

        If fetching new data fails, this method should emit a warning and return `None`.
        """
        raise NotImplementedError


@dataclass
class AutoUpdateAsyncSource(AsyncSource):
    client: httpx.AsyncClient | None = None
    url: str = DEFAULT_AUTO_UPDATE_URL
    max_age: timedelta = DEFAULT_AUTO_UPDATE_MAX_AGE
    fetch_age: timedelta = DEFAULT_AUTO_UPDATE_FETCH_AGE
    request_timeout: httpx.Timeout = field(default_factory=lambda: httpx.Timeout(timeout=10, connect=5))
    _pre_fetch_task: asyncio.Task[None] | None = field(default=None, init=False)

    def pre_fetch(self) -> None:
        if self._pre_fetch_task is None:
            self._pre_fetch_task = asyncio.create_task(self._fetch())

    async def fetch(self) -> 'DataSnapshot | None':
        if self._pre_fetch_task is not None:
            await self._pre_fetch_task
            self._pre_fetch_task = None

        if _cached_auto_update_snapshot is None or not _cached_auto_update_snapshot.active(self.max_age):
            await self._fetch()
        elif not _cached_auto_update_snapshot.active(self.fetch_age):
            self.pre_fetch()
        return _cached_auto_update_snapshot

    async def _fetch(self):
        from . import data

        global _cached_auto_update_snapshot

        try:
            client = self.client or _cached_async_http_client()
            r = await client.get(self.url, timeout=self.request_timeout)
            r.raise_for_status()
            providers = data.providers_schema.validate_json(r.content)
        except (httpx.HTTPError, ValidationError) as e:
            warnings.warn(f'Failed to auto update from {self.url}: {e}')
        else:
            _cached_auto_update_snapshot = DataSnapshot(providers=providers, from_auto_update=True)


class SyncSource(ABC):
    @abstractmethod
    def fetch(self) -> 'DataSnapshot | None':
        """Try to fetch a new snapshot if required.

        This method should check if any relevant cached has expired, if not it should return `None`.

        If fetching new data fails, this method should emit a warning and return `None`.
        """
        raise NotImplementedError


@dataclass
class AutoUpdateSyncSource(SyncSource):
    client: httpx.Client | None = None
    url: str = DEFAULT_AUTO_UPDATE_URL
    max_age: timedelta = DEFAULT_AUTO_UPDATE_MAX_AGE
    fetch_age: timedelta = DEFAULT_AUTO_UPDATE_FETCH_AGE
    request_timeout: httpx.Timeout = field(default_factory=lambda: httpx.Timeout(timeout=10, connect=5))
    _pre_fetch_task: futures.Future[None] | None = field(default=None, init=False)

    def pre_fetch(self) -> None:
        if self._pre_fetch_task is None:
            self._pre_fetch_task = futures.ThreadPoolExecutor(max_workers=1).submit(self._fetch)

    def fetch(self) -> 'DataSnapshot | None':
        if self._pre_fetch_task is not None:
            self._pre_fetch_task.result()
            self._pre_fetch_task = None

        if _cached_auto_update_snapshot is None or not _cached_auto_update_snapshot.active(self.max_age):
            self._fetch()
        elif not _cached_auto_update_snapshot.active(self.fetch_age):
            self.pre_fetch()
        return _cached_auto_update_snapshot

    def _fetch(self):
        from . import data

        global _cached_auto_update_snapshot

        try:
            client = self.client or httpx
            r = client.get(self.url, timeout=self.request_timeout)
            r.raise_for_status()
            providers = data.providers_schema.validate_json(r.content)
        except (httpx.HTTPError, ValidationError) as e:
            warnings.warn(f'Failed to auto update from {self.url}: {e}')
        else:
            _cached_auto_update_snapshot = DataSnapshot(providers=providers, from_auto_update=True)


_cached_auto_update_snapshot: DataSnapshot | None = None
auto_update_async_source = AutoUpdateAsyncSource()
auto_update_sync_source = AutoUpdateSyncSource()


@dataclass
class DataSnapshot:
    providers: list[types.Provider]
    from_auto_update: bool
    _lookup_cache: dict[tuple[str | None, str | None, str], tuple[types.Provider, types.ModelInfo]] = field(
        default_factory=lambda: {}
    )
    timestamp: datetime = field(default_factory=datetime.now)

    def active(self, ttl: timedelta) -> bool:
        """Check if the snapshot is "active" (e.g. hasn't expired) based on a time to live."""
        return self.timestamp + ttl > datetime.now()

    def calc(
        self,
        usage: types.AbstractUsage,
        model_ref: str,
        provider_id: str | None,
        provider_api_url: str | None,
        genai_request_timestamp: datetime | None,
    ) -> types.PriceCalculation:
        """Calculate the price for the given usage."""
        genai_request_timestamp = genai_request_timestamp or datetime.now(tz=timezone.utc)

        provider, model = self.find_provider_model(model_ref, provider_id, provider_api_url)
        model_price = model.get_prices(genai_request_timestamp)
        return types.PriceCalculation(
            price=model_price.calc_price(usage),
            provider=provider,
            model=model,
            model_price=model_price,
            auto_update_timestamp=self.timestamp if self.from_auto_update else None,
        )

    def find_provider_model(
        self,
        model_ref: str,
        provider_id: str | None,
        provider_api_url: str | None,
    ) -> tuple[types.Provider, types.ModelInfo]:
        """Find the provider and model for the given model reference and optional provider identifier."""
        if provider_model := self._lookup_cache.get((provider_id, provider_api_url, model_ref)):
            return provider_model

        provider = self.find_provider(model_ref, provider_id, provider_api_url)

        # Normalize the model reference if provider_id is provided
        normalized_model_ref = model_ref
        if provider_id is not None:
            normalized_provider_id = normalize_provider(provider_id)
            normalized_model_ref = normalize_model(normalized_provider_id, model_ref)

        if model := provider.find_model(normalized_model_ref):
            self._lookup_cache[(provider_id, provider_api_url, model_ref)] = ret = provider, model
            return ret
        else:
            raise LookupError(f'Unable to find model with {normalized_model_ref=!r} in {provider.id}')

    def find_provider(
        self,
        model_ref: str,
        provider_id: str | None,
        provider_api_url: str | None,
    ) -> types.Provider:
        if provider_id is not None:
            normalized_provider_id = normalize_provider(provider_id)
            for provider in self.providers:
                if provider.id == normalized_provider_id:
                    return provider
            raise LookupError(f'Unable to find provider {normalized_provider_id=!r}')

        if provider_api_url is not None:
            for provider in self.providers:
                if re.match(provider.api_pattern, provider_api_url):
                    return provider
            raise LookupError(f'Unable to find provider {provider_api_url=!r}')

        for provider in self.providers:
            if provider.model_match is not None and provider.model_match.is_match(model_ref):
                return provider

        raise LookupError(f'Unable to find provider with model matching {model_ref!r}')


@cache
def _cached_async_http_client() -> httpx.AsyncClient:
    """Naughty trick (also used by pydantic-ai and openai) to avoid creating a new async client for each request."""
    return httpx.AsyncClient()
