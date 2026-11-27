from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

import httpx2

from .prices_types import ClauseEquals, ClauseOr, MatchLogic, ModelInfo, ModelPrice, Tier, TieredPrices
from .update import ProviderYaml, UnreadableRowError, skipping_unreadable_row
from .utils import package_dir

MODELS_URL = 'https://api.trustedrouter.com/v1/models'
MIN_MODEL_COUNT = 200
HIDDEN_METADATA_FLAGS = ('internal_only', 'configuration_hidden', 'synthetic_monitor')
TOKEN_PRICE_FIELDS = {
    'input_mtok': 'prompt',
    'cache_write_mtok': 'input_cache_write',
    'cache_read_mtok': 'input_cache_read',
    'output_mtok': 'completion',
}
SCALAR_PRICE_KEYS = (
    'prompt',
    'completion',
    'input_cache_read',
    'input_cache_write',
    'input_character',
    'input_audio_minute',
    'request',
    'minimum',
)


def parse_models(models: list[Any]) -> list[ModelInfo]:
    """Parse public priced models from TrustedRouter's `/v1/models` payload."""
    all_ids = {
        raw_id.lower()
        for model in models
        if isinstance(model, dict) and isinstance(raw_id := cast(dict[str, Any], model).get('id'), str) and raw_id
    }
    claimed_aliases: set[str] = set()
    model_infos: list[ModelInfo] = []

    for model in models:
        with skipping_unreadable_row('TrustedRouter') as row:
            if not isinstance(model, dict):
                raise UnreadableRowError(f'Unexpected TrustedRouter model entry: {model!r}')
            entry = cast(dict[str, Any], model)
            model_id = entry.get('id')
            if not isinstance(model_id, str) or not model_id.strip():
                raise UnreadableRowError(f'Missing TrustedRouter model id: {entry!r}')
            row.model_ids.add(model_id)

            raw_metadata = entry.get('trustedrouter')
            if raw_metadata is not None and not isinstance(raw_metadata, dict):
                raise UnreadableRowError(f'Unexpected TrustedRouter metadata for {model_id}: {raw_metadata!r}')
            metadata: dict[str, Any] = cast(dict[str, Any], raw_metadata) if raw_metadata is not None else {}
            if any(metadata.get(flag) for flag in HIDDEN_METADATA_FLAGS):
                continue

            pricing = entry.get('pricing')
            if not isinstance(pricing, dict):
                continue

            prices = _model_price(model_id, cast(dict[str, Any], pricing))
            if prices is None:
                continue

            model_infos.append(
                ModelInfo(
                    id=model_id,
                    name=_model_name(entry.get('name')),
                    match=_model_match(model_id, metadata.get('aliases'), all_ids, claimed_aliases),
                    context_window=_context_window(entry.get('context_length')),
                    prices=prices,
                    prices_checked=date.today(),
                )
            )

    return model_infos


def main(provider_path: Path | None = None) -> None:
    response = httpx2.get(MODELS_URL, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    payload: Any = response.json()
    data: Any = cast(dict[str, Any], payload).get('data') if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RuntimeError('TrustedRouter /v1/models response did not contain a data list')
    models = parse_models(cast(list[Any], data))
    provider_yaml = ProviderYaml(provider_path or package_dir / 'providers/trustedrouter.yml')
    added, updated = provider_yaml.upsert_models(models, source='TrustedRouter', min_count=MIN_MODEL_COUNT)
    print(f'TrustedRouter prices updated: {added} added, {updated} updated')


def get_trustedrouter_prices() -> None:  # pragma: no cover - thin CLI alias for main
    """Download and update TrustedRouter prices."""
    main()


def _model_price(model_id: str, pricing: dict[str, Any]) -> ModelPrice | None:
    parsed = {key: _parse_decimal(pricing.get(key), field=key, model_id=model_id) for key in SCALAR_PRICE_KEYS}
    if any(value is not None and value < 0 for value in parsed.values()):
        return None
    if (minimum := parsed['minimum']) is not None and minimum > 0:
        # Per-request minimum-charge floors cannot be expressed in the v2 price schema.
        return None

    fields: dict[str, Decimal | TieredPrices] = {
        price_key: value * 1_000_000
        for price_key, api_key in TOKEN_PRICE_FIELDS.items()
        if (value := parsed[api_key]) is not None and value > 0
    }

    if (raw_tiers := pricing.get('tiers')) is not None:
        if not _apply_tiers(model_id, raw_tiers, fields):
            return None

    if (char_rate := parsed['input_character']) is not None and char_rate > 0:
        fields['input_mchars'] = char_rate * 1_000_000
    if (audio_min_rate := parsed['input_audio_minute']) is not None and audio_min_rate > 0:
        hourly = audio_min_rate * 60
        fields['audio_hours'] = hourly
        fields['input_audio_hours'] = hourly
    if (request_rate := parsed['request']) is not None and request_rate > 0:
        fields['requests_kcount'] = request_rate * 1_000

    if not fields:
        return None
    return ModelPrice.model_validate(fields)


def _apply_tiers(model_id: str, raw_tiers: Any, fields: dict[str, Decimal | TieredPrices]) -> bool:
    tiers = _validated_tiers(model_id, raw_tiers)
    for price_key, api_key in TOKEN_PRICE_FIELDS.items():
        tier0_val = _parse_decimal(tiers[0].get(api_key), field=f'tiers[0].{api_key}', model_id=model_id)
        if tier0_val is not None and tier0_val < 0:
            return False
        base_rate = tier0_val * 1_000_000 if tier0_val else cast(Decimal | None, fields.get(price_key))

        step_tiers: list[Tier] = []
        for prev_tier, tier in zip(tiers, tiers[1:]):
            tier_val = _parse_decimal(tier.get(api_key), field=f'tiers.{api_key}', model_id=model_id)
            if tier_val is not None and tier_val < 0:
                return False
            if tier_val is not None and tier_val > 0:
                step_tiers.append(Tier(start=cast(int, prev_tier['max_prompt_tokens']), price=tier_val * 1_000_000))

        if not step_tiers:
            continue
        if base_rate is None:
            raise UnreadableRowError(f'TrustedRouter tiers {api_key} for {model_id} without a base rate')
        if any(step.price != base_rate for step in step_tiers):
            fields[price_key] = TieredPrices(base=base_rate, tiers=step_tiers)
        else:
            fields[price_key] = base_rate
    return True


def _validated_tiers(model_id: str, raw_tiers: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tiers, list):
        raise UnreadableRowError(f'Unexpected TrustedRouter tiers for {model_id}: {raw_tiers!r}')
    raw_list = cast(list[Any], raw_tiers)
    if len(raw_list) < 2:
        raise UnreadableRowError(f'Unexpected TrustedRouter tiers for {model_id}: {raw_tiers!r}')
    tiers: list[dict[str, Any]] = []
    previous_max = 0
    for index, entry in enumerate(raw_list):
        if not isinstance(entry, dict):
            raise UnreadableRowError(f'Unexpected TrustedRouter tier entry for {model_id}: {entry!r}')
        tier_dict = cast(dict[str, Any], entry)
        max_tokens = tier_dict.get('max_prompt_tokens')
        is_last = index == len(raw_list) - 1
        if is_last:
            if max_tokens is not None:
                raise UnreadableRowError(f'Unexpected TrustedRouter final tier for {model_id}: {tier_dict!r}')
        else:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= previous_max:
                raise UnreadableRowError(f'Unexpected TrustedRouter tier boundary for {model_id}: {tier_dict!r}')
            previous_max = max_tokens
        tiers.append(tier_dict)
    return tiers


def _parse_decimal(raw: Any, *, field: str, model_id: str) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise UnreadableRowError(f'Non-numeric {field} price for {model_id}: {raw!r}')
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise UnreadableRowError(f'Non-numeric {field} price for {model_id}: {raw!r}') from exc
    if not value.is_finite():
        raise UnreadableRowError(f'Non-finite {field} price for {model_id}: {raw!r}')
    return value


def _model_name(raw_name: Any) -> str | None:
    if not isinstance(raw_name, str):
        return None
    return raw_name.split(':', 1)[-1].strip() or None


def _context_window(raw_context: Any) -> int | None:
    if isinstance(raw_context, int) and not isinstance(raw_context, bool) and raw_context > 0:
        return raw_context
    return None


def _model_match(
    model_id: str,
    raw_aliases: Any,
    all_ids: set[str],
    claimed_aliases: set[str],
) -> MatchLogic:
    clauses: list[MatchLogic] = [ClauseEquals(equals=model_id)]
    if isinstance(raw_aliases, list):
        for alias in cast(list[Any], raw_aliases):
            if not isinstance(alias, str) or not alias:
                continue
            alias_lower = alias.lower()
            if alias_lower in all_ids or alias_lower in claimed_aliases:
                continue
            claimed_aliases.add(alias_lower)
            clauses.append(ClauseEquals(equals=alias))
    return ClauseOr(or_=clauses) if len(clauses) > 1 else clauses[0]  # pyright: ignore[reportCallIssue]
