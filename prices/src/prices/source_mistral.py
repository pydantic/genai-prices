from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2
from pydantic import BaseModel, Field

from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice
from prices.update import ProviderYaml
from prices.utils import package_dir

PRICING_URL = 'https://docs.mistral.ai/inference/pricing'
MIN_MODEL_COUNT = 8
# The page embeds its model catalog as Next.js flight data: JSON string chunks pushed onto `self.__next_f`.
FLIGHT_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
FLIGHT_JSON_ROW = re.compile(r'^[0-9a-f]+:([\[{].*)$', re.M)
PRICE_KEYS: dict[tuple[str, str | None], tuple[str, ...]] = {
    ('Input', '/M Tokens'): ('input_mtok',),
    ('Cached input', '/M Tokens'): ('cache_read_mtok',),
    ('Output', '/M Tokens'): ('output_mtok',),
    ('Input', '/1000 Pages'): ('input_document_kpages',),
    ('Input', '/1000 Annotated Pages'): ('input_annotated_document_kpages',),
    ('Input', '/Min'): ('audio_hours', 'input_audio_hours'),
}


class MistralRate(BaseModel):
    label: str
    unit: str | None
    price_usd: Decimal = Field(alias='priceUsd')


class MistralModel(BaseModel):
    name: str
    api_ids: list[str] = Field(alias='modelIds')
    is_free: bool = Field(alias='isFree')
    pricing: list[MistralRate]


def parse_pricing_page(page: str) -> list[ModelInfo]:
    records: list[MistralModel] = []

    def collect(obj: dict[str, object]) -> dict[str, object]:
        if 'modelIds' in obj and 'pricing' in obj:
            records.append(MistralModel.model_validate(obj))
        return obj

    payload = ''.join(json.loads(f'"{chunk}"') for chunk in FLIGHT_CHUNK.findall(page))
    for row in FLIGHT_JSON_ROW.findall(payload):
        json.loads(row, object_hook=collect, parse_float=Decimal)

    models: dict[str, ModelInfo] = {}
    conflicting: set[str] = set()
    for record in records:
        # A catalog entry without an API name is a legacy or self-hosted model nobody can call.
        if not record.api_ids or record.is_free:
            continue
        prices: dict[str, Decimal] = {}
        for rate in record.pricing:
            keys = PRICE_KEYS.get((rate.label, rate.unit))
            if keys is None:
                # e.g. TTS output per million characters, which the unit registry has no key for.
                prices = {}
                break
            if value := rate.price_usd * (60 if rate.unit == '/Min' else 1):
                prices |= dict.fromkeys(keys, value.normalize())
        if not prices:
            continue
        model = ModelInfo(
            id=record.api_ids[0],
            name=record.name,
            match=ClauseEquals(equals=record.api_ids[0]),
            prices=ModelPrice(**prices),
            prices_checked=date.today(),
        )
        # The page repeats a model under other models' related models, normally at the same rates.
        if models.setdefault(model.id, model).prices != model.prices:
            conflicting.add(model.id)
    for model_id in sorted(conflicting):
        print(f'Mistral: kept {model_id} unchanged, the pricing page lists it at conflicting rates; update it by hand')
    return [model for model_id, model in models.items() if model_id not in conflicting]


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(PRICING_URL, timeout=30.0)
    response.raise_for_status()
    models = parse_pricing_page(response.text)
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/mistral.yml')
    added, updated = provider_yaml.upsert_models(models, source='Mistral', min_count=MIN_MODEL_COUNT)
    print(f'Mistral prices updated: {added} added, {updated} updated')


def get_mistral_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update Mistral prices."""
    main()
