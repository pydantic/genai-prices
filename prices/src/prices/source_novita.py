from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice, Tier, TieredPrices
from prices.update import ProviderYaml
from prices.utils import package_dir

MODELS_URL = 'https://api.novita.ai/v3/openai/models'
MIN_MODEL_COUNT = 40
PRICE_KEYS = {'prompt': 'input_mtok', 'input_cache_read': 'cache_read_mtok', 'completion': 'output_mtok'}


def parse_models(models: list[dict[str, Any]]) -> list[ModelInfo]:
    model_infos: list[ModelInfo] = []
    for model in models:
        prices = _model_price(model)
        if prices.input_mtok is None and prices.output_mtok is None:
            continue
        model_infos.append(
            ModelInfo(
                id=model['id'],
                name=(model.get('display_name') or '').strip() or None,
                match=ClauseEquals(equals=model['id']),
                context_window=model.get('context_size') or None,
                prices=prices,
                prices_checked=date.today(),
            )
        )
    return model_infos


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(MODELS_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_models(response.json()['data'])
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/novita.yml')
    added, updated = provider_yaml.upsert_models(models, source='Novita', min_count=MIN_MODEL_COUNT)
    print(f'Novita prices updated: {added} added, {updated} updated')


def get_novita_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Novita prices."""
    main()


def _model_price(model: dict[str, Any]) -> ModelPrice:
    base = _rates(model.get('pricing') or {})
    bands = model.get('tiered_billing_configs') if model.get('is_tiered_billing') else None
    if not bands:
        return ModelPrice(**base)
    prices: dict[str, Decimal | TieredPrices | None] = {}
    for key, base_rate in base.items():
        # The engines apply a tier above its start, which is where Novita's next band begins.
        tiers = [
            Tier(start=band['min_tokens'], price=rate)
            for band in bands[1:]
            if (rate := _rates(band['pricing'])[key]) is not None
        ]
        prices[key] = TieredPrices(base=base_rate, tiers=tiers) if base_rate is not None and tiers else base_rate
    return ModelPrice(**prices)  # pyright: ignore[reportArgumentType]


def _rates(pricing: dict[str, Any]) -> dict[str, Decimal | None]:
    rates: dict[str, Decimal | None] = {}
    for novita_key, price_key in PRICE_KEYS.items():
        value: str | None = pricing.get(novita_key, {}).get('price_per_m_decimal')
        rates[price_key] = Decimal(value) if value and Decimal(value) != 0 else None
    return rates
