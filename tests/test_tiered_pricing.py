from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price

pytestmark = pytest.mark.anyio


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
