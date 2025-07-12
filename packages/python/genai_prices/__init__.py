from __future__ import annotations as _annotations

import typing
from datetime import datetime

from . import data, sources, types
from .types import Usage

__all__ = 'Usage', 'calc_price_async', 'prefetch_async', 'calc_price_sync', 'prefetch_sync'


@typing.overload
async def calc_price_async(
    usage: types.AbstractUsage,
    model_ref: str,
    *,
    provider_id: types.ProviderID,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.AsyncSource = False,
) -> sources.PriceCalculation: ...


@typing.overload
async def calc_price_async(
    usage: types.AbstractUsage,
    model_ref: str,
    *,
    provider_api_url: str,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.AsyncSource = False,
) -> sources.PriceCalculation: ...


async def calc_price_async(
    usage: types.AbstractUsage,
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


def prefetch_async():
    """Prefetches the latest snapshot for use with `calc_price_async`.

    NOTE: this method is NOT async itself, it starts a task to fetch the latest snapshot which will be joined when
    calling `calc_price_async`.
    """
    sources.auto_update_async_source.pre_fetch()


@typing.overload
def calc_price_sync(
    usage: types.AbstractUsage,
    model_ref: str,
    *,
    provider_id: types.ProviderID,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.SyncSource = False,
) -> sources.PriceCalculation: ...


@typing.overload
def calc_price_sync(
    usage: types.AbstractUsage,
    model_ref: str,
    *,
    provider_api_url: str,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.SyncSource = False,
) -> sources.PriceCalculation: ...


def calc_price_sync(
    usage: types.AbstractUsage,
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


def prefetch_sync():
    """Prefetches the latest snapshot for use with `calc_price_sync`.

    This method creates a concurrent future (aka thread) to fetch the latest snapshot which will be joined when
    calling `calc_price_sync`.
    """
    sources.auto_update_sync_source.pre_fetch()


_local_snapshot = sources.DataSnapshot(providers=data.providers, from_auto_update=False)
