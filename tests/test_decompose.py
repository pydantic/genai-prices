from decimal import Decimal

import pytest

from genai_prices import Usage
from genai_prices.decompose import (
    compute_leaf_values,
    get_priced_descendants,
    is_descendant_or_self,
    validate_ancestor_coverage,
)
from genai_prices.types import ModelPrice, Tier, TieredPrices
from genai_prices.units import TOKENS_FAMILY, get_unit


class TestContainment:
    def test_self_is_descendant_or_self(self):
        unit = get_unit('input_mtok')
        assert is_descendant_or_self(unit, unit)

    def test_child_is_descendant(self):
        assert is_descendant_or_self(get_unit('input_mtok'), get_unit('cache_read_mtok'))

    def test_parent_is_not_descendant_of_child(self):
        assert not is_descendant_or_self(get_unit('cache_read_mtok'), get_unit('input_mtok'))

    def test_grandchild_is_descendant(self):
        assert is_descendant_or_self(get_unit('input_mtok'), get_unit('cache_read_audio_mtok'))

    def test_lattice_both_parents(self):
        """cache_read_audio is a descendant of both cache_read and input_audio."""
        cra = get_unit('cache_read_audio_mtok')
        assert is_descendant_or_self(get_unit('cache_read_mtok'), cra)
        assert is_descendant_or_self(get_unit('input_audio_mtok'), cra)

    def test_sibling_not_descendant(self):
        assert not is_descendant_or_self(get_unit('cache_read_mtok'), get_unit('cache_write_mtok'))

    def test_different_direction_not_descendant(self):
        assert not is_descendant_or_self(get_unit('input_mtok'), get_unit('output_mtok'))

    def test_wrong_modality_not_descendant(self):
        assert not is_descendant_or_self(get_unit('input_audio_mtok'), get_unit('cache_read_image_mtok'))

    def test_cache_write_not_descendant_of_cache_read(self):
        assert not is_descendant_or_self(get_unit('cache_read_mtok'), get_unit('cache_write_audio_mtok'))


class TestPricedDescendants:
    def test_all_priced(self):
        priced = {'input_mtok', 'cache_read_mtok', 'input_audio_mtok', 'cache_read_audio_mtok'}
        descs = get_priced_descendants('input_mtok', priced, TOKENS_FAMILY)
        assert descs == {'cache_read_mtok', 'input_audio_mtok', 'cache_read_audio_mtok'}

    def test_excludes_unpriced(self):
        priced = {'input_mtok', 'cache_read_mtok'}
        descs = get_priced_descendants('input_mtok', priced, TOKENS_FAMILY)
        assert descs == {'cache_read_mtok'}

    def test_leaf_has_no_descendants(self):
        priced = {'input_mtok', 'cache_read_audio_mtok'}
        descs = get_priced_descendants('cache_read_audio_mtok', priced, TOKENS_FAMILY)
        assert descs == set()

    def test_excludes_self(self):
        priced = {'input_mtok', 'cache_read_mtok'}
        descs = get_priced_descendants('input_mtok', priced, TOKENS_FAMILY)
        assert 'input_mtok' not in descs


class TestLeafValues:
    def test_simple_text_model(self):
        """Text-only: no carve-outs."""
        priced = {'input_mtok', 'output_mtok'}
        usage = {'input_tokens': 1000, 'output_tokens': 500}
        assert compute_leaf_values(priced, usage, TOKENS_FAMILY) == {'input_mtok': 1000, 'output_mtok': 500}

    def test_with_cache(self):
        """Cache tokens carved out of input catch-all."""
        priced = {'input_mtok', 'output_mtok', 'cache_read_mtok', 'cache_write_mtok'}
        usage = {'input_tokens': 1000, 'cache_read_tokens': 200, 'cache_write_tokens': 100, 'output_tokens': 500}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {
            'input_mtok': 700,
            'cache_read_mtok': 200,
            'cache_write_mtok': 100,
            'output_mtok': 500,
        }

    def test_with_audio(self):
        """Audio tokens carved out of input catch-all."""
        priced = {'input_mtok', 'output_mtok', 'input_audio_mtok'}
        usage = {'input_tokens': 1000, 'input_audio_tokens': 300, 'output_tokens': 500}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 700, 'input_audio_mtok': 300, 'output_mtok': 500}

    def test_spec_example(self):
        """Example from Section 4 of the unit registry spec."""
        priced = {'input_mtok', 'cache_read_mtok', 'input_audio_mtok'}
        usage = {'input_tokens': 1000, 'cache_read_tokens': 200, 'input_audio_tokens': 300}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 500, 'cache_read_mtok': 200, 'input_audio_mtok': 300}

    def test_lattice_cache_read_audio(self):
        """cache_read_audio carved from both cache_read and input_audio (lattice structure)."""
        priced = {'input_mtok', 'cache_read_mtok', 'input_audio_mtok', 'cache_read_audio_mtok'}
        usage = {
            'input_tokens': 1000,
            'cache_read_tokens': 200,
            'input_audio_tokens': 300,
            'cache_audio_read_tokens': 50,  # current field name
        }
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {
            'input_mtok': 550,  # 1000 - 200 - 300 + 50
            'cache_read_mtok': 150,  # 200 - 50
            'input_audio_mtok': 250,  # 300 - 50
            'cache_read_audio_mtok': 50,  # leaf
        }

    def test_unpriced_audio_stays_in_catchall(self):
        """If input_audio is NOT priced, audio tokens remain in the catch-all."""
        priced = {'input_mtok', 'output_mtok', 'cache_read_mtok'}
        usage = {
            'input_tokens': 1000,
            'cache_read_tokens': 200,
            'input_audio_tokens': 300,  # not priced — stays in catch-all
            'output_tokens': 500,
        }
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 800, 'cache_read_mtok': 200, 'output_mtok': 500}

    def test_missing_usage_is_zero(self):
        """Missing usage values default to zero."""
        priced = {'input_mtok', 'output_mtok', 'cache_read_mtok'}
        usage = {'input_tokens': 1000, 'output_tokens': 500}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 1000, 'cache_read_mtok': 0, 'output_mtok': 500}

    def test_negative_leaf_raises_error(self):
        """Inconsistent usage (cache > input) raises ValueError with helpful message."""
        priced = {'input_mtok', 'cache_read_mtok'}
        usage = {'input_tokens': 100, 'cache_read_tokens': 200}
        with pytest.raises(ValueError, match=r'Negative leaf value.*input_mtok'):
            compute_leaf_values(priced, usage, TOKENS_FAMILY)

    def test_usage_as_object(self):
        """Usage can be an object with attributes (like the Usage dataclass)."""
        priced = {'input_mtok', 'output_mtok', 'cache_read_mtok'}
        usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=200)
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'input_mtok': 800, 'cache_read_mtok': 200, 'output_mtok': 500}

    def test_full_current_model(self):
        """All 7 current units priced — matches what the hardcoded chain does."""
        priced = {
            'input_mtok',
            'output_mtok',
            'cache_read_mtok',
            'cache_write_mtok',
            'input_audio_mtok',
            'cache_read_audio_mtok',
            'output_audio_mtok',
        }
        usage = {
            'input_tokens': 1000,
            'cache_read_tokens': 200,
            'cache_write_tokens': 100,
            'input_audio_tokens': 300,
            'cache_audio_read_tokens': 50,
            'output_tokens': 800,
            'output_audio_tokens': 150,
        }
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {
            # input_mtok: 1000 - 200 - 100 - 300 + 50 = 450
            'input_mtok': 450,
            'cache_read_mtok': 150,  # 200 - 50
            'cache_write_mtok': 100,  # leaf
            'input_audio_mtok': 250,  # 300 - 50
            'cache_read_audio_mtok': 50,  # leaf
            'output_mtok': 650,  # 800 - 150
            'output_audio_mtok': 150,  # leaf
        }

    def test_output_audio_carved_from_output(self):
        """output_audio carved from output catch-all."""
        priced = {'output_mtok', 'output_audio_mtok'}
        usage = {'output_tokens': 800, 'output_audio_tokens': 200}
        leaves = compute_leaf_values(priced, usage, TOKENS_FAMILY)
        assert leaves == {'output_mtok': 600, 'output_audio_mtok': 200}


class TestCalcPriceEquivalence:
    """Verify the rewired calc_price produces the same results as the hardcoded chain."""

    def test_simple_text(self):
        mp = ModelPrice(input_mtok=Decimal('3'), output_mtok=Decimal('15'))
        result = mp.calc_price(Usage(input_tokens=1_000_000, output_tokens=500_000))
        assert result['input_price'] == Decimal('3')
        assert result['output_price'] == Decimal('7.5')
        assert result['total_price'] == Decimal('10.5')

    def test_with_cache(self):
        mp = ModelPrice(
            input_mtok=Decimal('3'),
            output_mtok=Decimal('15'),
            cache_read_mtok=Decimal('0.3'),
            cache_write_mtok=Decimal('3.75'),
        )
        usage = Usage(input_tokens=1000, cache_read_tokens=200, cache_write_tokens=100, output_tokens=500)
        result = mp.calc_price(usage)
        # input leaf: 1000 - 200 - 100 = 700
        expected_input = (Decimal('3') * 700 + Decimal('0.3') * 200 + Decimal('3.75') * 100) / 1_000_000
        assert result['input_price'] == expected_input

    def test_with_audio_and_cache(self):
        """All 7 current units priced, with audio and cache."""
        mp = ModelPrice(
            input_mtok=Decimal('5'),
            output_mtok=Decimal('20'),
            cache_read_mtok=Decimal('0.5'),
            cache_write_mtok=Decimal('6.25'),
            input_audio_mtok=Decimal('100'),
            output_audio_mtok=Decimal('200'),
            cache_audio_read_mtok=Decimal('2.5'),
        )
        usage = Usage(
            input_tokens=1000,
            cache_read_tokens=200,
            cache_write_tokens=100,
            input_audio_tokens=300,
            cache_audio_read_tokens=50,
            output_tokens=800,
            output_audio_tokens=150,
        )
        result = mp.calc_price(usage)
        # Leaf values (see test_full_current_model in TestLeafValues):
        # input_mtok: 450, cache_read: 150, cache_write: 100
        # input_audio: 250, cache_read_audio: 50
        # output: 650, output_audio: 150
        expected_input = (
            Decimal('5') * 450
            + Decimal('0.5') * 150
            + Decimal('6.25') * 100
            + Decimal('100') * 250
            + Decimal('2.5') * 50
        ) / 1_000_000
        expected_output = (Decimal('20') * 650 + Decimal('200') * 150) / 1_000_000
        assert result['input_price'] == expected_input
        assert result['output_price'] == expected_output

    def test_with_tiered_prices(self):
        """TieredPrices still works through the decomposition path."""
        mp = ModelPrice(
            input_mtok=TieredPrices(base=Decimal('3'), tiers=[Tier(start=200_000, price=Decimal('6'))]),
            output_mtok=TieredPrices(base=Decimal('15'), tiers=[Tier(start=200_000, price=Decimal('30'))]),
            cache_read_mtok=Decimal('0.3'),
        )
        # Below threshold
        usage_low = Usage(input_tokens=100_000, cache_read_tokens=20_000, output_tokens=50_000)
        result_low = mp.calc_price(usage_low)
        expected_input_low = (Decimal('3') * 80_000 + Decimal('0.3') * 20_000) / 1_000_000
        expected_output_low = Decimal('15') * 50_000 / 1_000_000
        assert result_low['input_price'] == expected_input_low
        assert result_low['output_price'] == expected_output_low

        # Above threshold — tier applies to ALL tokens of that type
        usage_high = Usage(input_tokens=300_000, cache_read_tokens=50_000, output_tokens=100_000)
        result_high = mp.calc_price(usage_high)
        expected_input_high = (Decimal('6') * 250_000 + Decimal('0.3') * 50_000) / 1_000_000
        expected_output_high = Decimal('30') * 100_000 / 1_000_000
        assert result_high['input_price'] == expected_input_high
        assert result_high['output_price'] == expected_output_high

    def test_with_requests(self):
        mp = ModelPrice(input_mtok=Decimal('3'), output_mtok=Decimal('15'), requests_kcount=Decimal('1'))
        result = mp.calc_price(Usage(input_tokens=1000, output_tokens=500))
        expected = Decimal('3') * 1000 / 1_000_000 + Decimal('15') * 500 / 1_000_000 + Decimal('1') / 1000
        assert result['total_price'] == expected

    def test_none_usage(self):
        mp = ModelPrice(input_mtok=Decimal('3'), output_mtok=Decimal('15'))
        result = mp.calc_price(Usage())
        assert result['total_price'] == Decimal('0')


class TestAncestorCoverage:
    def test_valid_simple(self):
        validate_ancestor_coverage({'input_mtok', 'output_mtok'}, TOKENS_FAMILY)

    def test_valid_with_cache(self):
        validate_ancestor_coverage({'input_mtok', 'output_mtok', 'cache_read_mtok'}, TOKENS_FAMILY)

    def test_missing_ancestor(self):
        with pytest.raises(ValueError, match=r"ancestor 'input_mtok'.*not"):
            validate_ancestor_coverage({'cache_read_mtok', 'output_mtok'}, TOKENS_FAMILY)

    def test_missing_intermediate_ancestor(self):
        with pytest.raises(ValueError, match=r'ancestor'):
            validate_ancestor_coverage(
                {'input_mtok', 'cache_read_audio_mtok', 'output_mtok'},
                TOKENS_FAMILY,
            )

    def test_model_price_validates(self):
        with pytest.raises(ValueError, match=r'ancestor'):
            ModelPrice(cache_read_mtok=Decimal('0.3'))
