from __future__ import annotations as _annotations

from datetime import datetime
from typing import overload

from . import data, sources, types

__all__ = 'calc_price', 'sync_calc_price'


@overload
async def calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_id: types.ProviderID,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.AsyncSource = False,
) -> sources.PriceCalculation: ...


@overload
async def calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_api_url: str,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.AsyncSource = False,
) -> sources.PriceCalculation: ...


async def calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_id: types.ProviderID | None = None,
    provider_api_url: str | None = None,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.AsyncSource = False,
) -> sources.PriceCalculation:
    snapshot = _local_snapshot
    if auto_update is not False:
        if auto_update is True:
            auto_update = sources.auto_update_async_source

        new_snapshot = await auto_update.fetch()
        if new_snapshot is not None:
            snapshot = new_snapshot

    return snapshot.calc(usage, model_ref, provider_id, provider_api_url, genai_request_timestamp)


@overload
def sync_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_id: types.ProviderID,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.SyncSource = False,
) -> sources.PriceCalculation: ...


@overload
def sync_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_api_url: str,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.SyncSource = False,
) -> sources.PriceCalculation: ...


def sync_calc_price(
    usage: types.Usage,
    model_ref: str,
    *,
    provider_id: types.ProviderID | None = None,
    provider_api_url: str | None = None,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.SyncSource = False,
) -> sources.PriceCalculation:
    snapshot = _local_snapshot
    if auto_update is not False:
        if auto_update is True:
            auto_update = sources.auto_update_sync_source

        new_snapshot = auto_update.fetch()
        if new_snapshot is not None:
            snapshot = new_snapshot

    return snapshot.calc(usage, model_ref, provider_id, provider_api_url, genai_request_timestamp)


_local_snapshot = sources.DataSnapshot(providers=data.providers, from_auto_update=False)
