from __future__ import annotations as _annotations

import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import cache

import httpx
from pydantic import ValidationError

from . import data, types

DEFAULT_AUTO_UPDATE_TTL = timedelta(hours=1)
DEFAULT_AUTO_UPDATE_URL = 'https://raw.githubusercontent.com/pydantic/genai-prices/refs/heads/main/prices/data.json'


class AsyncSource(ABC):
    @abstractmethod
    async def fetch(self, current_snapshot: DataSnapshot | None) -> DataSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def source_id(self) -> str:
        raise NotImplementedError


class AutoUpdateAsyncSource(AsyncSource):
    client: httpx.AsyncClient | None = None
    url: str = DEFAULT_AUTO_UPDATE_URL
    data_ttl: timedelta = DEFAULT_AUTO_UPDATE_TTL
    request_timeout: httpx.Timeout = field(default_factory=lambda: httpx.Timeout(timeout=30, connect=5))

    async def fetch(self, current_snapshot: DataSnapshot | None) -> DataSnapshot | None:
        if current_snapshot is None or not current_snapshot.active(self.data_ttl):
            try:
                client = self.client if self.client else _cached_async_http_client()
                r = await client.get(self.url, timeout=self.request_timeout)
                r.raise_for_status()
                providers = data.providers_schema.validate_json(r.content)
            except (httpx.HTTPError, ValidationError) as e:
                warnings.warn(f'Failed to auto update from {self.url}: {e}')
            else:
                return DataSnapshot(providers=providers, from_auto_update=True)

    def source_id(self) -> str:
        return self.url


class SyncSource(ABC):
    @abstractmethod
    def fetch(self, current_snapshot: DataSnapshot | None) -> DataSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def source_id(self) -> str:
        raise NotImplementedError


class AutoUpdateSyncSource(SyncSource):
    client: httpx.Client | None = None
    url: str = DEFAULT_AUTO_UPDATE_URL
    data_ttl: timedelta = DEFAULT_AUTO_UPDATE_TTL
    request_timeout: httpx.Timeout = field(default_factory=lambda: httpx.Timeout(timeout=30, connect=5))

    def fetch(self, current_snapshot: DataSnapshot | None) -> DataSnapshot | None:
        if current_snapshot is None or not current_snapshot.active(self.data_ttl):
            try:
                if self.client:
                    r = self.client.get(self.url, timeout=self.request_timeout)
                else:
                    r = httpx.get(self.url, timeout=self.request_timeout)

                r.raise_for_status()
                providers = data.providers_schema.validate_json(r.content)
            except (httpx.HTTPError, ValidationError) as e:
                warnings.warn(f'Failed to auto update from {self.url}: {e}')
            else:
                return DataSnapshot(providers=providers, from_auto_update=True)

    def source_id(self) -> str:
        return self.url


@dataclass
class PriceCalculation:
    price: Decimal
    provider: types.Provider
    model: types.ModelInfo
    auto_update_timestamp: datetime | None

    def __repr__(self) -> str:
        return (
            f'PriceCalculation(price={self.price!r}, '
            f'provider=Provider(id={self.provider.id!r}, name={self.provider.name!r}, ...), '
            f'model=Model(id={self.model.id!r}, name={self.model.name!r}, ...), '
            f'auto_update_timestamp={self.auto_update_timestamp!r})'
        )


@dataclass
class DataSnapshot:
    providers: list[types.Provider]
    from_auto_update: bool
    _lookup_cache: dict[tuple[str | None, str], tuple[types.Provider, types.ModelInfo]] = field(
        default_factory=lambda: {}
    )
    timestamp: datetime = field(default_factory=datetime.now)

    def active(self, ttl: timedelta) -> bool:
        return self.timestamp + ttl > datetime.now()

    def calc(
        self,
        usage: types.Usage,
        model_ref: str,
        provider_id: types.ProviderID | None,
        provider_api_url: str | None,
        genai_request_timestamp: datetime | None,
    ) -> PriceCalculation:
        genai_request_timestamp = genai_request_timestamp or datetime.now(tz=timezone.utc)

        provider, model = self.find_provider_model(model_ref, provider_id, provider_api_url)
        return PriceCalculation(
            price=model.get_prices(genai_request_timestamp).calc_price(usage),
            provider=provider,
            model=model,
            auto_update_timestamp=self.timestamp if self.from_auto_update else None,
        )

    def find_provider_model(
        self,
        model_ref: str,
        provider_id: types.ProviderID | None,
        provider_api_url: str | None,
    ) -> tuple[types.Provider, types.ModelInfo]:
        if provider_model := self._lookup_cache.get((provider_id or provider_api_url, model_ref)):
            return provider_model

        try:
            provider = next(provider for provider in self.providers if provider.is_match(provider_id, provider_api_url))
        except StopIteration as e:
            if provider_id:
                raise LookupError(f'Unable to find provider {provider_id=!r}') from e
            else:
                raise LookupError(f'Unable to find provider {provider_api_url=!r}') from e

        if model := provider.find_model(model_ref):
            self._lookup_cache[(provider_id or provider_api_url, model_ref)] = ret = provider, model
            return ret
        else:
            raise LookupError(f'Unable to find model with {model_ref=!r} in {provider.id}')


@cache
def _cached_async_http_client(timeout: int, connect: int) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout=timeout, connect=connect))
