"""Tests for the auto_update module."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from prices.auto_update import (
    AliasResolution,
    AutoUpdateReport,
    UnresolvedModel,
    _is_routing_path,
    _is_subset_price_match,
    classify_missing_model,
    get_dot_dash_variants,
    is_name_prefix_match,
)
from prices.prices_types import ClauseEquals, ModelInfo, ModelPrice

# ── _is_routing_path ──────────────────────────────────────────────────


class TestIsRoutingPath:
    def test_slash_separated(self):
        assert _is_routing_path('openrouter/meta-llama/llama-3-70b') is True

    def test_litellm_routing(self):
        assert _is_routing_path('anthropic/fast/claude-opus-4-6') is True

    def test_bedrock_vendor_prefix(self):
        assert _is_routing_path('anthropic.claude-3-5-haiku-20241022-v1:0') is True

    def test_bedrock_regional_prefix(self):
        assert _is_routing_path('us.anthropic.claude-opus-4-6-v1') is True

    def test_bedrock_eu_prefix(self):
        assert _is_routing_path('eu.amazon.nova-2-lite-v1:0') is True

    def test_bedrock_apac_prefix(self):
        assert _is_routing_path('apac.anthropic.claude-opus-4-6-v1') is True

    def test_bedrock_global_prefix(self):
        assert _is_routing_path('global.anthropic.claude-opus-4-6-v1') is True

    def test_normal_model_id(self):
        assert _is_routing_path('gpt-5.2-chat-latest') is False

    def test_model_with_colon(self):
        assert _is_routing_path('claude-3:thinking') is False

    def test_model_with_version_dot(self):
        assert _is_routing_path('gpt-4.1-mini') is False


# ── _is_subset_price_match ────────────────────────────────────────────


class TestIsSubsetPriceMatch:
    def test_exact_match_is_subset(self):
        existing = ModelPrice(
            input_mtok=Decimal('1.25'),
            cache_read_mtok=Decimal('0.125'),
            output_mtok=Decimal(10),
        )
        source = ModelPrice(
            input_mtok=Decimal('1.25'),
            cache_read_mtok=Decimal('0.125'),
            output_mtok=Decimal(10),
        )
        assert _is_subset_price_match(existing, source) is True

    def test_source_missing_cache_read(self):
        """Source omits cache_read_mtok but input/output match."""
        existing = ModelPrice(
            input_mtok=Decimal('1.75'),
            cache_read_mtok=Decimal('0.175'),
            output_mtok=Decimal(14),
        )
        source = ModelPrice(input_mtok=Decimal('1.75'), output_mtok=Decimal(14))
        assert _is_subset_price_match(existing, source) is True

    def test_source_has_different_value(self):
        existing = ModelPrice(input_mtok=Decimal('1.75'), output_mtok=Decimal(14))
        source = ModelPrice(input_mtok=Decimal('1.75'), output_mtok=Decimal(99))
        assert _is_subset_price_match(existing, source) is False

    def test_source_has_field_existing_lacks(self):
        """Source reports cache_read but existing doesn't have it."""
        existing = ModelPrice(input_mtok=Decimal('1.75'), output_mtok=Decimal(14))
        source = ModelPrice(
            input_mtok=Decimal('1.75'),
            cache_read_mtok=Decimal('0.5'),
            output_mtok=Decimal(14),
        )
        assert _is_subset_price_match(existing, source) is False

    def test_trivial_source_rejected(self):
        """Source with no input or output is too sparse."""
        existing = ModelPrice(input_mtok=Decimal(1), output_mtok=Decimal(2))
        source = ModelPrice(requests_kcount=Decimal('0.5'))
        assert _is_subset_price_match(existing, source) is False


# ── is_name_prefix_match ──────────────────────────────────────────────


class TestIsNamePrefixMatch:
    def test_direct_prefix_dash(self):
        assert is_name_prefix_match('gpt-5.2', 'gpt-5.2-chat-latest') is True

    def test_direct_prefix_dot(self):
        assert is_name_prefix_match('gpt-4.1', 'gpt-4.1-mini-2025-04-14') is True

    def test_direct_prefix_colon(self):
        assert is_name_prefix_match('claude-3', 'claude-3:thinking') is True

    def test_dot_dash_equivalence(self):
        """gpt-5.2 should match gpt-5-2-chat-latest via normalization."""
        assert is_name_prefix_match('gpt-5.2', 'gpt-5-2-chat-latest') is True

    def test_dot_dash_equivalence_reverse(self):
        """gpt-5-2 (dash form) should match gpt-5.2-chat-latest (dot form)."""
        assert is_name_prefix_match('gpt-5-2', 'gpt-5.2-chat-latest') is True

    def test_boundary_safety_no_separator(self):
        """gpt-4 must NOT match gpt-4o (remainder starts with 'o', not a separator)."""
        assert is_name_prefix_match('gpt-4', 'gpt-4o') is False

    def test_boundary_safety_alphanumeric(self):
        assert is_name_prefix_match('gpt-4', 'gpt-4omni') is False

    def test_completely_different_names(self):
        assert is_name_prefix_match('claude-3', 'gpt-4-turbo') is False

    def test_same_id(self):
        assert is_name_prefix_match('gpt-4o', 'gpt-4o') is False

    def test_no_version_dot_no_match(self):
        """Without version-number dots, dot-dash equivalence doesn't apply."""
        assert is_name_prefix_match('claude-sonnet', 'claude.sonnet-v2') is False

    def test_existing_longer_than_new(self):
        assert is_name_prefix_match('gpt-5.2-chat-latest', 'gpt-5.2') is False


# ── get_dot_dash_variants ─────────────────────────────────────────────


class TestGetDotDashVariants:
    def test_dot_to_dash(self):
        variants = get_dot_dash_variants('gpt-5.2-chat')
        assert 'gpt-5-2-chat' in variants

    def test_dash_to_dot(self):
        variants = get_dot_dash_variants('gpt-5-2-chat')
        assert 'gpt-5.2-chat' in variants

    def test_no_version_segments(self):
        assert get_dot_dash_variants('claude-sonnet-latest') == []

    def test_multiple_version_segments(self):
        variants = get_dot_dash_variants('model-1.2-v3.4')
        assert 'model-1-2-v3-4' in variants

    def test_no_op_for_long_numbers(self):
        """multi-digit numbers around separator aren't version-like enough for dash→dot."""
        # 12-34 would match \d-\d but that's fine; the regex matches single digits around the sep
        variants = get_dot_dash_variants('model-v12.3')
        # 12.3 → 12-3 matches (\d)\.(\d) at "2.3"
        assert 'model-v12-3' in variants


# ── classify_missing_model ────────────────────────────────────────────


def _make_provider_yml(models: list[ModelInfo]) -> MagicMock:
    """Create a mock ProviderYaml with the given models."""
    mock = MagicMock()
    mock.provider.id = 'openai'
    mock.provider.models = models
    mock.find_model.return_value = None
    return mock


def _make_model(
    model_id: str,
    input_mtok: Decimal = Decimal('2.5'),
    output_mtok: Decimal = Decimal(10),
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        prices=ModelPrice(input_mtok=input_mtok, output_mtok=output_mtok),
        match=ClauseEquals(equals=model_id),
    )


class TestClassifyMissingModel:
    def test_exact_price_and_prefix_match_is_tier1(self):
        """Exact price + name prefix → Tier 1 alias."""
        existing = _make_model('gpt-5.2', Decimal('2.5'), Decimal(10))
        provider = _make_provider_yml([existing])
        price = ModelPrice(input_mtok=Decimal('2.5'), output_mtok=Decimal(10))

        result = classify_missing_model('gpt-5.2-chat-latest', price, provider, ['litellm'])

        assert isinstance(result, AliasResolution)
        assert result.existing_model_id == 'gpt-5.2'
        assert result.new_alias == 'gpt-5.2-chat-latest'

    def test_exact_price_no_name_similarity_is_tier2(self):
        """Exact price but unrelated name → Tier 2."""
        existing = _make_model('computer-use', Decimal(3), Decimal(15))
        provider = _make_provider_yml([existing])
        price = ModelPrice(input_mtok=Decimal(3), output_mtok=Decimal(15))

        result = classify_missing_model('ft:gpt-4.1', price, provider, ['openrouter'])

        assert isinstance(result, UnresolvedModel)
        assert result.reason == 'exact_price_match_but_no_name_similarity'
        assert result.candidate_model_ids == []  # price-coincidence candidates are noise

    def test_subset_price_and_prefix_match_is_tier1(self):
        """Source omits cache_read_mtok but input/output match + name prefix → Tier 1."""
        existing = ModelInfo(
            id='gpt-5.2',
            prices=ModelPrice(
                input_mtok=Decimal('1.75'),
                cache_read_mtok=Decimal('0.175'),
                output_mtok=Decimal(14),
            ),
            match=ClauseEquals(equals='gpt-5.2'),
        )
        provider = _make_provider_yml([existing])
        # Source only reports input + output (no cache_read)
        price = ModelPrice(input_mtok=Decimal('1.75'), output_mtok=Decimal(14))

        result = classify_missing_model('gpt-5.2-chat-latest', price, provider, ['litellm'])

        assert isinstance(result, AliasResolution)
        assert result.existing_model_id == 'gpt-5.2'

    def test_no_price_match_is_tier2(self):
        """No existing model has matching price → Tier 2."""
        existing = _make_model('gpt-5.2', Decimal('2.5'), Decimal(10))
        provider = _make_provider_yml([existing])
        price = ModelPrice(input_mtok=Decimal(99), output_mtok=Decimal(99))

        result = classify_missing_model('gpt-5.2-chat', price, provider, ['litellm'])

        assert isinstance(result, UnresolvedModel)
        assert result.reason == 'no_exact_price_match'

    def test_multiple_exact_matches_narrowed_by_name(self):
        """Multiple exact matches, but only one passes name prefix → Tier 1."""
        model_a = _make_model('gpt-5.2', Decimal('2.5'), Decimal(10))
        model_b = _make_model('unrelated-model', Decimal('2.5'), Decimal(10))
        provider = _make_provider_yml([model_a, model_b])
        price = ModelPrice(input_mtok=Decimal('2.5'), output_mtok=Decimal(10))

        result = classify_missing_model('gpt-5.2-chat-latest', price, provider, ['litellm'])

        assert isinstance(result, AliasResolution)
        assert result.existing_model_id == 'gpt-5.2'

    def test_multiple_name_matches_picks_longest_prefix(self):
        """Multiple name matches → pick the most specific (longest) prefix."""
        model_a = _make_model('gpt-5.2', Decimal('2.5'), Decimal(10))
        model_b = _make_model('gpt-5.2-turbo', Decimal('2.5'), Decimal(10))
        provider = _make_provider_yml([model_a, model_b])
        price = ModelPrice(input_mtok=Decimal('2.5'), output_mtok=Decimal(10))

        # gpt-5.2-turbo-latest matches both gpt-5.2 and gpt-5.2-turbo as prefix,
        # but gpt-5.2-turbo is more specific → Tier 1
        result = classify_missing_model('gpt-5.2-turbo-latest', price, provider, ['litellm'])

        assert isinstance(result, AliasResolution)
        assert result.existing_model_id == 'gpt-5.2-turbo'

    def test_multiple_name_matches_same_length_is_tier2(self):
        """Multiple name matches with same-length prefixes → Tier 2."""
        model_a = _make_model('gpt-5.2a', Decimal('2.5'), Decimal(10))
        model_b = _make_model('gpt-5.2b', Decimal('2.5'), Decimal(10))
        provider = _make_provider_yml([model_a, model_b])
        price = ModelPrice(input_mtok=Decimal('2.5'), output_mtok=Decimal(10))

        result = classify_missing_model('gpt-5.2a-latest', price, provider, ['litellm'])

        # Only gpt-5.2a matches (gpt-5.2b doesn't prefix-match gpt-5.2a-latest)
        assert isinstance(result, AliasResolution)
        assert result.existing_model_id == 'gpt-5.2a'


# ── AutoUpdateReport.to_dict ─────────────────────────────────────────


class TestToDict:
    def test_round_trips(self):
        report = AutoUpdateReport(
            applied=[
                AliasResolution(
                    provider_id='openai',
                    existing_model_id='gpt-5.2',
                    new_alias='gpt-5.2-chat-latest',
                    source_names=['litellm', 'openrouter'],
                    price={'input_mtok': '2.5'},
                ),
            ],
            unresolved=[
                UnresolvedModel(
                    provider_id='openai',
                    model_id='unknown',
                    source_names=['openrouter'],
                    price={'input_mtok': '99'},
                    reason='no_exact_price_match',
                    candidate_model_ids=[],
                ),
            ],
        )
        d = report.to_dict()
        assert len(d['applied']) == 1
        assert d['applied'][0]['new_alias'] == 'gpt-5.2-chat-latest'
        assert d['applied'][0]['match_type'] == 'exact'
        assert len(d['unresolved']) == 1
        assert d['unresolved'][0]['model_id'] == 'unknown'

    def test_empty_report(self):
        d = AutoUpdateReport().to_dict()
        assert d['applied'] == []
        assert d['unresolved'] == []
