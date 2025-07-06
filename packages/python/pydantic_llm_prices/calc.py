from __future__ import annotations as _annotations

import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, overload

import httpx
from pydantic import ValidationError

from . import data, types

__all__ = ('sync_calc_price',)
DEFAULT_PHONE_HOME_TTL = timedelta(hours=1)
DEFAULT_PHONE_HOME_URL = '...'


@dataclass
class PriceCalculation:
    price: Decimal
    provider: types.Provider
    model: types.ModelInfo
    phone_home_timestamp: datetime | None


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
    phone_home_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
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
    phone_home_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
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
    phone_home_ttl: timedelta = DEFAULT_PHONE_HOME_TTL,
) -> PriceCalculation:
    global _phone_home_snapshot

    if phone_home:
        if _phone_home_snapshot is None or not _phone_home_snapshot.active(phone_home_ttl):
            try:
                if phone_home_client:
                    r = phone_home_client.get(phone_home_url)
                else:
                    r = httpx.get(phone_home_url)
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

    request_timestamp = request_timestamp or datetime.now(tz=timezone.utc)

    provider, model = snapshot.find_provider_model(model_ref, provider_id, provider_api_url)
    return PriceCalculation(
        price=model.get_prices(request_timestamp).calc_price(usage),
        provider=provider,
        model=model,
        phone_home_timestamp=snapshot.timestamp if snapshot.source == 'phone_number' else None,
    )


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

    def find_provider_model(
        self,
        model_ref: str,
        provider_id: types.ProviderID | None,
        provider_api_url: str | None,
    ) -> tuple[types.Provider, types.ModelInfo]:
        if provider_and_model := self._lookup_cache.get((provider_id or provider_api_url, model_ref)):
            return provider_and_model

        try:
            provider = next(provider for provider in self.providers if provider.is_match(provider_id, provider_api_url))
        except StopIteration as e:
            if provider_id:
                raise LookupError(f'Unable to find provider {provider_id=!r}') from e
            else:
                raise LookupError(f'Unable to find provider {provider_api_url=!r}') from e
        else:
            if model := provider.find_model(model_ref):
                self._lookup_cache[(provider_id or provider_api_url, model_ref)] = ret = provider, model
                return ret
            else:
                raise LookupError(f'Unable to find model with {model_ref=!r} in {provider.id}')

        raise LookupError(f'Unable to find any model with {model_ref=!r}')


_local_snapshot = DataSnapshot(providers=data.providers, source='local')
_phone_home_snapshot: DataSnapshot | None = None
