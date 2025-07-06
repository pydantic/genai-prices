from __future__ import annotations as _annotations

import warnings
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, overload

import httpx
from pydantic import ValidationError

from . import data, types

__all__ = ('sync_calc_price',)
DEFAULT_PHONE_HOME_TTL = timedelta(hours=1)
DEFAULT_PHONE_HOME_REQUEST_TIMEOUT = 30
DEFAULT_PHONE_HOME_URL = 'https://raw.githubusercontent.com/pydantic/llm-pricing/refs/heads/main/prices/data.json'


@dataclass
class PriceCalculation:
    price: Decimal
    provider: types.Provider
    model: types.ModelInfo
    phone_home_timestamp: datetime | None

    def __repr__(self) -> str:
        return (
            f'PriceCalculation(price={self.price!r}, '
            f'provider=Provider(id={self.provider.id!r}, name={self.provider.name!r}, ...), '
            f'model=Model(id={self.model.id!r}, name={self.model.name!r}, ...), '
            f'phone_home_timestamp={self.phone_home_timestamp!r})'
        )


@overload
def sync_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_id: types.ProviderID,
    request_timestamp: datetime | None = None,
    phone_home: bool = False,
    phone_home_client: httpx.Client | None = None,
    phone_home_url: str = DEFAULT_PHONE_HOME_URL,
    phone_home_data_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
    phone_home_request_timeout: int = DEFAULT_PHONE_HOME_REQUEST_TIMEOUT,
) -> PriceCalculation: ...


@overload
def sync_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_api_url: str,
    request_timestamp: datetime | None = None,
    phone_home: bool = False,
    phone_home_client: httpx.Client | None = None,
    phone_home_url: str = DEFAULT_PHONE_HOME_URL,
    phone_home_data_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
    phone_home_request_timeout: int = DEFAULT_PHONE_HOME_REQUEST_TIMEOUT,
) -> PriceCalculation: ...


def sync_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_id: types.ProviderID | None = None,
    provider_api_url: str | None = None,
    request_timestamp: datetime | None = None,
    phone_home: bool = False,
    phone_home_client: httpx.Client | None = None,
    phone_home_url: str = DEFAULT_PHONE_HOME_URL,
    phone_home_data_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
    phone_home_request_timeout: int = DEFAULT_PHONE_HOME_REQUEST_TIMEOUT,
) -> PriceCalculation:
    global _phone_home_snapshot

    if phone_home:
        if _phone_home_snapshot is None or not _phone_home_snapshot.active(phone_home_data_ttl):
            try:
                if phone_home_client:
                    r = phone_home_client.get(phone_home_url, timeout=phone_home_request_timeout)
                else:
                    r = httpx.get(phone_home_url, timeout=phone_home_request_timeout)
                r.raise_for_status()
                providers = data.providers_schema.validate_json(r.content)
            except (httpx.HTTPError, ValidationError) as e:
                warnings.warn(f'Failed to phone home to {phone_home_url}: {e}')
                snapshot = _phone_home_snapshot or _local_snapshot
            else:
                snapshot = _phone_home_snapshot = DataSnapshot(providers=providers, source='phone_number')
        else:
            snapshot = _phone_home_snapshot
    else:
        snapshot = _local_snapshot

    return snapshot.calc(usage, model_ref, provider_id, provider_api_url, request_timestamp)


@overload
async def async_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_id: types.ProviderID,
    request_timestamp: datetime | None = None,
    phone_home: bool = False,
    phone_home_client: httpx.AsyncClient | None = None,
    phone_home_url: str = DEFAULT_PHONE_HOME_URL,
    phone_home_data_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
    phone_home_request_timeout: int = DEFAULT_PHONE_HOME_REQUEST_TIMEOUT,
) -> PriceCalculation: ...


@overload
async def async_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_api_url: str,
    request_timestamp: datetime | None = None,
    phone_home: bool = False,
    phone_home_client: httpx.AsyncClient | None = None,
    phone_home_url: str = DEFAULT_PHONE_HOME_URL,
    phone_home_data_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
    phone_home_request_timeout: int = DEFAULT_PHONE_HOME_REQUEST_TIMEOUT,
) -> PriceCalculation: ...


async def async_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_id: types.ProviderID | None = None,
    provider_api_url: str | None = None,
    request_timestamp: datetime | None = None,
    phone_home: bool = False,
    phone_home_client: httpx.AsyncClient | None = None,
    phone_home_url: str = DEFAULT_PHONE_HOME_URL,
    phone_home_data_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
    phone_home_request_timeout: int = DEFAULT_PHONE_HOME_REQUEST_TIMEOUT,
) -> PriceCalculation:
    global _phone_home_snapshot

    snapshot = _local_snapshot
    if phone_home:
        if _phone_home_snapshot is None or not _phone_home_snapshot.active(phone_home_data_ttl):
            async with AsyncExitStack() as exit_stack:
                try:
                    if not phone_home_client:
                        phone_home_client = httpx.AsyncClient()
                        await exit_stack.enter_async_context(phone_home_client)

                    r = await phone_home_client.get(phone_home_url, timeout=phone_home_request_timeout)
                    r.raise_for_status()
                    providers = data.providers_schema.validate_json(r.content)
                except (httpx.HTTPError, ValidationError) as e:
                    warnings.warn(f'Failed to phone home to {phone_home_url}: {e}')
                    snapshot = _phone_home_snapshot or _local_snapshot
                else:
                    snapshot = _phone_home_snapshot = DataSnapshot(providers=providers, source='phone_number')
        else:
            snapshot = _phone_home_snapshot

    return snapshot.calc(usage, model_ref, provider_id, provider_api_url, request_timestamp)


@dataclass
class DataSnapshot:
    providers: list[types.Provider]
    source: Literal['phone_number', 'local']
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
        request_timestamp: datetime | None,
    ) -> PriceCalculation:
        request_timestamp = request_timestamp or datetime.now(tz=timezone.utc)

        provider, model = self.find_provider_model(model_ref, provider_id, provider_api_url)
        return PriceCalculation(
            price=model.get_prices(request_timestamp).calc_price(usage),
            provider=provider,
            model=model,
            phone_home_timestamp=self.timestamp if self.source == 'phone_number' else None,
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


_local_snapshot = DataSnapshot(providers=data.providers, source='local')
_phone_home_snapshot: DataSnapshot | None = None
