"""Non-interactive auto-update of price aliases.

Detects missing model IDs from external price sources, classifies them as
either auto-resolvable aliases (Tier 1) or models needing human review (Tier 2),
and applies Tier 1 changes to the provider YAML files.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from .price_discrepancies import can_ignore_missing_model, prices_conflict
from .prices_types import ModelInfo, ModelPrice, TieredPrices
from .source_prices import load_source_prices
from .update import ProviderYaml, get_providers_yaml


def is_name_prefix_match(existing_id: str, new_id: str) -> bool:
    """Check if new_id is a variant of existing_id at a natural name boundary.

    Two strategies:
    1. Direct prefix: ``existing_id`` is a prefix of ``new_id`` and the remainder
       starts with ``-``, ``.``, or ``:``.
    2. Dot-dash equivalence: normalise ``\\d.\\d`` → ``\\d-\\d`` in both IDs, then
       apply the same prefix-at-boundary check.

    This intentionally prevents ``gpt-4`` from matching ``gpt-4o`` (remainder
    must start with a separator, not an alphanumeric character).
    """
    if existing_id == new_id:
        return False

    def _is_prefix_at_boundary(prefix: str, full: str) -> bool:
        if not full.startswith(prefix):
            return False
        remainder = full[len(prefix) :]
        return bool(remainder) and remainder[0] in ('-', '.', ':')

    # Strategy 1: direct prefix
    if _is_prefix_at_boundary(existing_id, new_id):
        return True

    # Strategy 2: dot-dash equivalence (version numbers only)
    def _normalize(s: str) -> str:
        return re.sub(r'(\d)\.(\d)', r'\1-\2', s)

    norm_existing = _normalize(existing_id)
    norm_new = _normalize(new_id)
    if norm_existing == existing_id and norm_new == new_id:
        # No version-number dots to normalize — no match via this strategy
        return False

    return _is_prefix_at_boundary(norm_existing, norm_new)


def get_dot_dash_variants(model_id: str) -> list[str]:
    """Generate dot/dash variant for version-number segments.

    For IDs containing ``\\d.\\d`` segments, returns the dash variant and vice-versa.
    Only operates on version-like patterns (single digit around the separator).

    Returns an empty list if no variant applies.
    """
    variants: list[str] = []

    # dot → dash
    dot_to_dash = re.sub(r'(\d)\.(\d)', r'\1-\2', model_id)
    if dot_to_dash != model_id:
        variants.append(dot_to_dash)

    # dash → dot (only for version-like segments: single-digit around dash)
    dash_to_dot = re.sub(r'(\d)-(\d)', r'\1.\2', model_id)
    if dash_to_dot != model_id and dash_to_dot not in variants:
        variants.append(dash_to_dot)

    return variants


@dataclass
class AliasResolution:
    """A model alias that can be automatically applied."""

    provider_id: str
    existing_model_id: str
    new_alias: str
    source_names: list[str]
    price: dict[str, Any]
    match_type: str = 'exact'  # 'exact' or 'subset'


@dataclass
class UnresolvedModel:
    """A missing model that needs human review."""

    provider_id: str
    model_id: str
    source_names: list[str]
    price: dict[str, Any]
    reason: str
    candidate_model_ids: list[str]


@dataclass
class AutoUpdateReport:
    """Result of an auto-update run."""

    applied: list[AliasResolution] = field(default_factory=list)
    unresolved: list[UnresolvedModel] = field(default_factory=list)
    providers_saved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_subset_price_match(existing: ModelPrice, source: ModelPrice) -> bool:
    """Check if source price is a subset of existing price.

    Returns True when every non-None field in ``source`` matches the
    corresponding field in ``existing``. ``existing`` is allowed to have
    extra fields that ``source`` doesn't report (e.g. ``cache_read_mtok``).

    At least ``input_mtok`` or ``output_mtok`` must be present in source
    to avoid matching on trivially sparse prices.
    """
    if source.input_mtok is None and source.output_mtok is None:
        return False

    for field_name in source.__pydantic_fields__:
        source_val = getattr(source, field_name)
        if source_val is None:
            continue
        existing_val = getattr(existing, field_name)
        if existing_val is None:
            return False
        # Handle TieredPrices: compare base price
        if isinstance(existing_val, TieredPrices):
            if existing_val.base != source_val:
                return False
        elif existing_val != source_val:
            return False
    return True


def classify_missing_model(
    model_id: str,
    price: ModelPrice,
    provider_yml: ProviderYaml,
    source_names: list[str],
) -> AliasResolution | UnresolvedModel:
    """Classify a missing model as auto-alias or needing human review."""
    provider_id = provider_yml.provider.id
    price_dict = price.model_dump(exclude_none=True, mode='json')

    # Find all existing models with an exact price match
    exact_matches: list[ModelInfo] = [
        m for m in provider_yml.provider.models if isinstance(m.prices, ModelPrice) and m.prices == price
    ]
    match_type = 'exact'

    # Fall back to subset match: source price has fewer fields but all present fields match
    if not exact_matches:
        exact_matches = [
            m
            for m in provider_yml.provider.models
            if isinstance(m.prices, ModelPrice) and _is_subset_price_match(m.prices, price)
        ]
        match_type = 'subset'

    if not exact_matches:
        # Check for non-conflicting matches (for reason detail)
        non_conflict = [
            m
            for m in provider_yml.provider.models
            if isinstance(m.prices, ModelPrice)
            and (not prices_conflict(m.prices, price) or not prices_conflict(price, m.prices))
        ]
        return UnresolvedModel(
            provider_id=provider_id,
            model_id=model_id,
            source_names=source_names,
            price=price_dict,
            reason='no_exact_price_match',
            candidate_model_ids=[m.id for m in non_conflict],
        )

    # Narrow by name prefix
    name_matches = [m for m in exact_matches if is_name_prefix_match(m.id, model_id)]

    if len(name_matches) == 1:
        return AliasResolution(
            provider_id=provider_id,
            existing_model_id=name_matches[0].id,
            new_alias=model_id,
            source_names=source_names,
            price=price_dict,
            match_type=match_type,
        )

    if len(name_matches) > 1:
        # Multiple name matches — pick the most specific (longest prefix).
        # e.g. gpt-5 and gpt-5.1 both match gpt-5.1-chat, but gpt-5.1 is more specific.
        name_matches.sort(key=lambda m: len(m.id), reverse=True)
        if len(name_matches[0].id) > len(name_matches[1].id):
            # Clear winner by length
            return AliasResolution(
                provider_id=provider_id,
                existing_model_id=name_matches[0].id,
                new_alias=model_id,
                source_names=source_names,
                price=price_dict,
                match_type=match_type,
            )
        return UnresolvedModel(
            provider_id=provider_id,
            model_id=model_id,
            source_names=source_names,
            price=price_dict,
            reason='multiple_exact_price_matches',
            candidate_model_ids=[m.id for m in name_matches],
        )

    # Exact price match(es) but no name similarity — don't list all price-coincidence
    # matches as candidates since they're misleading (many models share the same price).
    return UnresolvedModel(
        provider_id=provider_id,
        model_id=model_id,
        source_names=source_names,
        price=price_dict,
        reason='exact_price_match_but_no_name_similarity',
        candidate_model_ids=[],
    )


_BEDROCK_VENDOR_PREFIXES = (
    'anthropic.',
    'amazon.',
    'meta.',
    'cohere.',
    'ai21.',
    'mistral.',
    'writer.',
    'deepseek.',
    'openai.',
    'google.',
    'qwen.',
    'minimax.',
    'moonshot.',
    'nvidia.',
    'twelvelabs.',
)

_BEDROCK_REGION_PREFIXES = ('us.', 'eu.', 'apac.', 'global.')


def _is_routing_path(model_id: str) -> bool:
    """Check if a model ID is a routing path rather than a real model name.

    Filters out:
    - Slash-separated routing keys from LiteLLM (e.g. ``openrouter/meta-llama/llama-3-70b``,
      ``anthropic/fast/claude-opus-4-6``)
    - AWS Bedrock ARN-style IDs (e.g. ``anthropic.claude-3-5-haiku-20241022-v1:0``,
      ``us.anthropic.claude-opus-4-6-v1``)
    """
    if '/' in model_id:
        return True

    # Strip regional prefix first (e.g. "us.anthropic.claude-..." → "anthropic.claude-...")
    stripped = model_id
    for rp in _BEDROCK_REGION_PREFIXES:
        if stripped.startswith(rp):
            stripped = stripped[len(rp) :]
            break

    # Check for Bedrock vendor-prefixed model IDs
    if stripped.startswith(_BEDROCK_VENDOR_PREFIXES):
        return True

    return False


def _collect_missing_models(
    providers_yml: dict[str, ProviderYaml],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Collect missing models across all sources and providers.

    Returns ``{provider_id: {model_id: [{'price': ModelPrice, 'sources': [str]}]}}``
    """
    source_prices = load_source_prices()
    all_missing: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for provider_yml in providers_yml.values():
        missing: dict[str, list[dict[str, Any]]] = {}
        provider_id = provider_yml.provider.id

        for source, sp in source_prices.items():
            if provider_prices := sp.get(provider_id):
                for model_id, price in provider_prices.items():
                    if provider_id == 'groq':
                        model_id = model_id.removeprefix('groq/')

                    # Skip routing paths (e.g. "openrouter/meta-llama/...", "anthropic/fast/...")
                    if _is_routing_path(model_id):
                        continue

                    if provider_yml.provider.find_model(model_id):
                        continue

                    entries = missing.setdefault(model_id, [])
                    for other in entries:
                        if not prices_conflict(price, other['price']) or not prices_conflict(other['price'], price):
                            other['sources'].append(source)
                            break
                    else:
                        entries.append(dict(price=price, sources=[source]))

        if missing:
            all_missing[provider_id] = missing

    return all_missing


def detect_auto_updates() -> AutoUpdateReport:
    """Detect missing models and classify them. Does not modify any files."""
    providers_yml = get_providers_yaml()
    all_missing = _collect_missing_models(providers_yml)
    report = AutoUpdateReport()

    for provider_id, missing in all_missing.items():
        provider_yml = providers_yml[provider_id]

        for model_id, entries in missing.items():
            if can_ignore_missing_model(provider_id, model_id):
                continue

            if len(entries) != 1:
                price_dict = entries[0]['price'].model_dump(exclude_none=True, mode='json')
                all_sources = [s for e in entries for s in e['sources']]
                report.unresolved.append(
                    UnresolvedModel(
                        provider_id=provider_id,
                        model_id=model_id,
                        source_names=all_sources,
                        price=price_dict,
                        reason='conflicting_prices_across_sources',
                        candidate_model_ids=[],
                    ),
                )
                continue

            entry = entries[0]
            price: ModelPrice = entry['price']
            source_names: list[str] = entry['sources']

            result = classify_missing_model(model_id, price, provider_yml, source_names)

            if isinstance(result, UnresolvedModel):
                report.unresolved.append(result)
            else:
                report.applied.append(result)

    return report


def apply_auto_updates(report: AutoUpdateReport) -> list[str]:
    """Apply aliases from a report to provider YAMLs. Returns list of saved provider IDs."""
    providers_yml = get_providers_yaml()
    modified_providers: set[str] = set()

    for r in report.applied:
        provider_yml = providers_yml[r.provider_id]
        if not provider_yml.provider.find_model(r.new_alias):
            provider_yml.add_id_to_model(r.existing_model_id, r.new_alias)
            modified_providers.add(r.provider_id)

        for variant in get_dot_dash_variants(r.new_alias):
            if not provider_yml.provider.find_model(variant):
                provider_yml.add_id_to_model(r.existing_model_id, variant)

    saved: list[str] = []
    for pid in modified_providers:
        providers_yml[pid].save()
        saved.append(pid)

    return saved


def auto_update() -> None:
    """Detect new price aliases. Outputs JSON report to stdout."""
    report = detect_auto_updates()
    json.dump(report.to_dict(), sys.stdout, indent=2)
    print(file=sys.stderr)
    print(f'found {len(report.applied)} alias(es), {len(report.unresolved)} unresolved.', file=sys.stderr)
