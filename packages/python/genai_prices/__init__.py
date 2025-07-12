from __future__ import annotations as _annotations

from datetime import datetime
from functools import cache

from . import sources, types
from .types import Usage

__all__ = 'Usage', 'calc_price_async', 'prefetch_async', 'calc_price_sync', 'prefetch_sync'


async def calc_price_async(
    usage: types.AbstractUsage,
    model_ref: str,
    *,
    provider_id: types.ProviderID | str | None = None,
    provider_api_url: str | None = None,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.AsyncSource = False,
) -> types.PriceCalculation:
    """Async method to calculate the price of an LLM API call.

    If `auto_update` is `True` and the cached is empty or expired, this method will make an async HTTP request to
    GitHub to get the most recent LLM prices available.

    Either `provider_id` or `provider_api_url` should be provided, but not both. If neither are provided,
    we try to find the most suitable provider based on the model reference.

    Args:
        usage: The usage to calculate the price for.
        model_ref: A reference to the model used, this method will try to match this to a specific model.
        provider_id: The ID of the provider to calculate the price for.
        provider_api_url: The API URL of the provider to calculate the price for.
        genai_request_timestamp: The timestamp of the request to the GenAI service, use `None` to use the current time.
        auto_update: Whether to automatically update pricing data, or a custom source to use for fetching pricing data.

    Returns:
        The price calculation details.
    """
    snapshot = _local_snapshot()
    if auto_update is not False:
        if auto_update is True:
            auto_update = sources.auto_update_async_source

        new_snapshot = await auto_update.fetch()
        if new_snapshot is not None:
            snapshot = new_snapshot

    return snapshot.calc(usage, model_ref, provider_id, provider_api_url, genai_request_timestamp)


def prefetch_async():
    """Prefetches the latest snapshot for use with `calc_price_async`.

    NOTE: this method is NOT async itself, it starts a task to fetch the latest snapshot which will be awaited when
    calling `calc_price_async`.
    """
    sources.auto_update_async_source.pre_fetch()


def calc_price_sync(
    usage: types.AbstractUsage,
    model_ref: str,
    *,
    provider_id: types.ProviderID | str | None = None,
    provider_api_url: str | None = None,
    genai_request_timestamp: datetime | None = None,
    auto_update: bool | sources.SyncSource = False,
) -> types.PriceCalculation:
    """Sync method to calculate the price of an LLM API call.

    If `auto_update` is `True` and the cached is empty or expired, this method will make an synchronous HTTP request to
    GitHub to get the most recent LLM prices available.

    Either `provider_id` or `provider_api_url` should be provided, but not both. If neither are provided,
    we try to find the most suitable provider based on the model reference.

    Args:
        usage: The usage to calculate the price for.
        model_ref: A reference to the model used, this method will try to match this to a specific model.
        provider_id: The ID of the provider to calculate the price for.
        provider_api_url: The API URL of the provider to calculate the price for.
        genai_request_timestamp: The timestamp of the request to the GenAI service, use `None` to use the current time.
        auto_update: Whether to automatically update pricing data, or a custom source to use for fetching pricing data.

    Returns:
        The price calculation details.
    """
    snapshot = _local_snapshot()
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


@cache
def _local_snapshot():
    from .data import providers

    return sources.DataSnapshot(providers=providers, from_auto_update=False)
