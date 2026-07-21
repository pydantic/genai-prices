from decimal import Decimal

import pytest

from prices.source_litellm import LiteLLMModel


@pytest.mark.parametrize(
    ('reasoning_per_token', 'expected_reasoning_mtok'),
    [
        (Decimal('0.000003'), Decimal('3')),
        (Decimal('0.000002'), None),
        (None, None),
    ],
)
def test_litellm_model_price_preserves_only_distinct_reasoning_rate(
    reasoning_per_token: Decimal | None,
    expected_reasoning_mtok: Decimal | None,
):
    model = LiteLLMModel(
        input_cost_per_token=Decimal('0.000001'),
        output_cost_per_token=Decimal('0.000002'),
        output_cost_per_reasoning_token=reasoning_per_token,
        litellm_provider='test',
    )

    expected = {'input_mtok': Decimal('1'), 'output_mtok': Decimal('2')}
    if expected_reasoning_mtok is not None:
        expected['output_reasoning_mtok'] = expected_reasoning_mtok
    assert model.model_price().model_dump(exclude_none=True) == expected
