from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price, types
from genai_prices.data_snapshot import DataSnapshot
from genai_prices.update_prices import UpdatePrices

pytestmark = pytest.mark.anyio


class MultiTierUpdatePrices(UpdatePrices):
    """Custom UpdatePrices that injects a multi-tier pricing model for testing."""

    def fetch(self) -> DataSnapshot | None:
        """Create a mock provider with a multi-tier pricing model.

        Pricing structure (threshold-based with different tiers for input vs output):

        Input tokens:
        - Base: $1/MTok for requests with <= 100K tokens
        - Tier 1: $2/MTok for requests with > 100K tokens (applies to ALL tokens)
        - Tier 2: $3/MTok for requests with > 500K tokens (applies to ALL tokens)
        - Tier 3: $5/MTok for requests with > 1M tokens (applies to ALL tokens)

        Output tokens (different thresholds and prices to test independent tier calculation):
        - Base: $3/MTok for requests with <= 200K tokens
        - Tier 1: $5/MTok for requests with > 200K tokens (applies to ALL tokens)
        - Tier 2: $8/MTok for requests with > 1M tokens (applies to ALL tokens)
        """
        custom_providers = [
            types.Provider(
                id='mock-provider',
                name='Mock Provider',
                api_pattern=r'mock\.example\.com',
                models=[
                    types.ModelInfo(
                        id='mock-multi-tier',
                        match=types.ClauseEquals('mock-multi-tier'),
                        name='Mock Multi-Tier Model',
                        prices=types.ModelPrice(
                            input_mtok=types.TieredPrices(
                                base=Decimal('1'),
                                tiers=[
                                    types.Tier(start=100_000, price=Decimal('2')),
                                    types.Tier(start=500_000, price=Decimal('3')),
                                    types.Tier(start=1_000_000, price=Decimal('5')),
                                ],
                            ),
                            output_mtok=types.TieredPrices(
                                base=Decimal('3'),
                                tiers=[
                                    types.Tier(start=200_000, price=Decimal('5')),
                                    types.Tier(start=1_000_000, price=Decimal('8')),
                                ],
                            ),
                        ),
                    )
                ],
            )
        ]
        return DataSnapshot(providers=custom_providers, from_auto_update=False)


def test_claude_sonnet_4_5_tiered_pricing_below_threshold():
    """Test Claude Sonnet 4.5 with 100,000 input tokens (below 200K threshold).

    Pricing structure (threshold-based):
    - Base: $3/MTok for requests with < 200K tokens
    - Tier: $6/MTok for requests with >= 200K tokens (applies to ALL tokens)

    Calculation for 100,000 tokens:
    - All tokens at base price: (3 * 100,000) / 1,000,000 = $0.30
    """
    price = calc_price(Usage(input_tokens=100_000), model_ref='claude-sonnet-4.5', provider_id='anthropic')

    assert price.input_price == snapshot(Decimal('0.3'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.3'))
    assert price.model.name == snapshot('Claude Sonnet 4.5')
    assert price.provider.id == snapshot('anthropic')


def test_claude_sonnet_4_5_tiered_pricing_above_threshold():
    """Test Claude Sonnet 4.5 with 1,000,000 input tokens (above 200K threshold).

    Pricing structure (threshold-based):
    - Base: $3/MTok for requests with < 200K tokens
    - Tier: $6/MTok for requests with >= 200K tokens (applies to ALL tokens)

    Calculation for 1,000,000 tokens:
    - ALL tokens at tier price: (6 * 1,000,000) / 1,000,000 = $6.00
    """
    price = calc_price(Usage(input_tokens=1_000_000), model_ref='claude-sonnet-4.5', provider_id='anthropic')

    assert price.input_price == snapshot(Decimal('6'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('6'))
    assert price.model.name == snapshot('Claude Sonnet 4.5')
    assert price.provider.id == snapshot('anthropic')


def test_claude_sonnet_4_5_tiered_pricing_at_threshold():
    """Test Claude Sonnet 4.5 exactly at the 200,000 token threshold.

    Calculation for 200,000 tokens:
    - Threshold is '> 200000', so exactly 200K still uses base price
    - All tokens at base price: (3 * 200,000) / 1,000,000 = $0.60
    """
    price = calc_price(Usage(input_tokens=200_000), model_ref='claude-sonnet-4.5', provider_id='anthropic')

    assert price.input_price == snapshot(Decimal('0.6'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.6'))
    assert price.model.name == snapshot('Claude Sonnet 4.5')
    assert price.provider.id == snapshot('anthropic')


def test_claude_sonnet_4_5_tiered_pricing_just_above_threshold():
    """Test Claude Sonnet 4.5 with 200,001 tokens (just above threshold).

    Calculation for 200,001 tokens:
    - Threshold crossed, so ALL tokens pay tier price
    - ALL tokens at tier price: (6 * 200,001) / 1,000,000 = $1.200006
    """
    price = calc_price(Usage(input_tokens=200_001), model_ref='claude-sonnet-4.5', provider_id='anthropic')

    assert price.input_price == snapshot(Decimal('1.200006'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('1.200006'))
    assert price.model.name == snapshot('Claude Sonnet 4.5')
    assert price.provider.id == snapshot('anthropic')


def test_claude_sonnet_4_5_with_output_below_threshold():
    """Test Claude Sonnet 4.5 with input below threshold but with output tokens.

    Input: 100,000 tokens (below 200K threshold)
    Output: 100,000 tokens

    Pricing structure:
    - Input base: $3/MTok, tier: $6/MTok (threshold at 200K)
    - Output base: $15/MTok, tier: $22.5/MTok (threshold at 200K)

    Calculation:
    - Input: 100K < 200K, so base rate applies: (3 * 100,000) / 1,000,000 = $0.30
    - Output: tier determined by input (100K < 200K), so base rate: (15 * 100,000) / 1,000,000 = $1.50
    - Total: $0.30 + $1.50 = $1.80
    """
    price = calc_price(
        Usage(input_tokens=100_000, output_tokens=100_000),
        model_ref='claude-sonnet-4.5',
        provider_id='anthropic',
    )

    assert price.input_price == snapshot(Decimal('0.3'))
    assert price.output_price == snapshot(Decimal('1.5'))
    assert price.total_price == snapshot(Decimal('1.8'))
    assert price.model.name == snapshot('Claude Sonnet 4.5')
    assert price.provider.id == snapshot('anthropic')


def test_claude_sonnet_4_5_with_output_above_threshold():
    """Test Claude Sonnet 4.5 with input above threshold and output tokens.

    Input: 300,000 tokens (above 200K threshold)
    Output: 100,000 tokens

    Pricing structure:
    - Input base: $3/MTok, tier: $6/MTok (threshold at 200K)
    - Output base: $15/MTok, tier: $22.5/MTok (threshold at 200K)

    Calculation:
    - Input: 300K > 200K, so tier rate applies to ALL: (6 * 300,000) / 1,000,000 = $1.80
    - Output: tier determined by input (300K > 200K), so tier rate: (22.5 * 100,000) / 1,000,000 = $2.25
    - Total: $1.80 + $2.25 = $4.05
    """
    price = calc_price(
        Usage(input_tokens=300_000, output_tokens=100_000),
        model_ref='claude-sonnet-4.5',
        provider_id='anthropic',
    )

    assert price.input_price == snapshot(Decimal('1.8'))
    assert price.output_price == snapshot(Decimal('2.25'))
    assert price.total_price == snapshot(Decimal('4.05'))
    assert price.model.name == snapshot('Claude Sonnet 4.5')
    assert price.provider.id == snapshot('anthropic')


def test_google_gemini_tiered_pricing_below_threshold():
    """Test Google Gemini 1.5 Flash with 100,000 input tokens (below 128K threshold).

    Pricing structure (threshold-based):
    - Base: $0.075/MTok for requests with < 128K tokens
    - Tier: $0.15/MTok for requests with >= 128K tokens (applies to ALL tokens)

    Calculation for 100,000 tokens:
    - All tokens at base price: (0.075 * 100,000) / 1,000,000 = $0.0075
    """
    price = calc_price(Usage(input_tokens=100_000), model_ref='gemini-1.5-flash', provider_id='google')

    assert price.input_price == snapshot(Decimal('0.0075'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.0075'))
    assert price.model.name == snapshot('gemini 1.5 flash')
    assert price.provider.id == snapshot('google')


def test_google_gemini_tiered_pricing_above_threshold():
    """Test Google Gemini 1.5 Flash with 500,000 input tokens (above 128K threshold).

    Pricing structure (threshold-based):
    - Base: $0.075/MTok for requests with < 128K tokens
    - Tier: $0.15/MTok for requests with >= 128K tokens (applies to ALL tokens)

    Calculation for 500,000 tokens:
    - Threshold crossed, ALL tokens at tier price: (0.15 * 500,000) / 1,000,000 = $0.075
    """
    price = calc_price(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='google')

    assert price.input_price == snapshot(Decimal('0.075'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.075'))
    assert price.model.name == snapshot('gemini 1.5 flash')
    assert price.provider.id == snapshot('google')


def test_multi_tier_base_pricing():
    """Test multi-tier model at base pricing (50K tokens, below first tier).

    Pricing: Base $1/MTok (<=100K)
    Calculation: (1 * 50,000) / 1,000,000 = $0.05
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=50_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('0.05'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.05'))


def test_multi_tier_at_base_threshold():
    """Test multi-tier model exactly at first threshold (100K tokens).

    Pricing: Threshold is '> 100000', so exactly 100K uses base
    Calculation: (1 * 100,000) / 1,000,000 = $0.10
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=100_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('0.1'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.1'))


def test_multi_tier_first_tier():
    """Test multi-tier model in first tier (200K tokens, between 100K and 500K).

    Pricing: Tier 1 $2/MTok (>100K, <=500K)
    Calculation: ALL tokens at tier 1: (2 * 200,000) / 1,000,000 = $0.40
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=200_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('0.4'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.4'))


def test_multi_tier_at_second_threshold():
    """Test multi-tier model exactly at second threshold (500K tokens).

    Pricing: Threshold is '> 500000', so exactly 500K uses tier 1
    Calculation: (2 * 500,000) / 1,000,000 = $1.00
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=500_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('1'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('1'))


def test_multi_tier_second_tier():
    """Test multi-tier model in second tier (750K tokens, between 500K and 1M).

    Pricing: Tier 2 $3/MTok (>500K, <=1M)
    Calculation: ALL tokens at tier 2: (3 * 750,000) / 1,000,000 = $2.25
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=750_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('2.25'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('2.25'))


def test_multi_tier_at_third_threshold():
    """Test multi-tier model exactly at third threshold (1M tokens).

    Pricing: Threshold is '> 1000000', so exactly 1M uses tier 2
    Calculation: (3 * 1,000,000) / 1,000,000 = $3.00
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=1_000_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('3'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('3'))


def test_multi_tier_third_tier():
    """Test multi-tier model in third tier (2M tokens, above 1M).

    Pricing: Tier 3 $5/MTok (>1M)
    Calculation: ALL tokens at tier 3: (5 * 2,000,000) / 1,000,000 = $10.00
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=2_000_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('10'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('10'))


def test_multi_tier_with_output_base_tier():
    """Test multi-tier model with output tokens in base tier.

    Input: 50K tokens (base tier for input)
    Output: 10K tokens (base tier for output)

    Pricing:
    - Input base: $1/MTok (tier determined by 50K <= 100K)
    - Output base: $3/MTok (tier determined by 50K <= 200K)

    Calculation:
    - Input: (1 * 50,000) / 1,000,000 = $0.05
    - Output: (3 * 10,000) / 1,000,000 = $0.03
    - Total: $0.05 + $0.03 = $0.08
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=50_000, output_tokens=10_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('0.05'))
    assert price.output_price == snapshot(Decimal('0.03'))
    assert price.total_price == snapshot(Decimal('0.08'))


def test_multi_tier_with_output_second_tier():
    """Test multi-tier model with output tokens crossing different tier than input.

    Input: 600K tokens (input tier 2: >500K, <=1M)
    Output: 250K tokens (output tier 1: >200K, <=1M)

    Pricing:
    - Input tier 2: $3/MTok (determined by 600K > 500K)
    - Output tier 1: $5/MTok (determined by 600K > 200K but <= 1M)

    Calculation:
    - Input: (3 * 600,000) / 1,000,000 = $1.80
    - Output: (5 * 250,000) / 1,000,000 = $1.25
    - Total: $1.80 + $1.25 = $3.05
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=600_000, output_tokens=250_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('1.8'))
    assert price.output_price == snapshot(Decimal('1.25'))
    assert price.total_price == snapshot(Decimal('3.05'))


def test_multi_tier_with_output_highest_tier():
    """Test multi-tier model with output tokens in highest tier.

    Input: 1.5M tokens (input tier 3: >1M)
    Output: 500K tokens (output tier 2: >1M)

    Pricing:
    - Input tier 3: $5/MTok (determined by 1.5M > 1M)
    - Output tier 2: $8/MTok (determined by 1.5M > 1M, output has only 2 tiers)

    Calculation:
    - Input: (5 * 1,500,000) / 1,000,000 = $7.50
    - Output: (8 * 500,000) / 1,000,000 = $4.00
    - Total: $7.50 + $4.00 = $11.50
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=1_500_000, output_tokens=500_000),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('7.5'))
    assert price.output_price == snapshot(Decimal('4'))
    assert price.total_price == snapshot(Decimal('11.5'))


def test_multi_tier_boundary_transitions():
    """Test transitions across all tier boundaries.

    Test with 100,001 tokens (just above first threshold).
    Should use tier 1 pricing for ALL tokens.

    Calculation: (2 * 100,001) / 1,000,000 = $0.200002
    """
    with MultiTierUpdatePrices() as update_prices:
        update_prices.wait()
        price = calc_price(
            Usage(input_tokens=100_001),
            model_ref='mock-multi-tier',
            provider_id='mock-provider',
        )

    assert price.input_price == snapshot(Decimal('0.200002'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.200002'))
