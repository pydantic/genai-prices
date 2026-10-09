from datetime import datetime, timezone
from decimal import Decimal

import pytest

from genai_prices import Usage, calc_price


@pytest.mark.parametrize('request_date', ['2026-09-30', '2026-10-09'])
@pytest.mark.parametrize(
    ('provider_id', 'model_ref', 'input_rate', 'cache_rate', 'output_rate'),
    [
        ('avian', 'deepseek/deepseek-v4-flash', '0.0805', '0.0165', '0.161'),
        ('avian', 'deepseek/deepseek-v4-pro-0813', '0.594', '0.0198', '1.782'),
        ('avian', 'xiaomi/mimo-v2.5-pro', '0.435', '0.0036', '0.87'),
        ('avian', 'xiaomi/mimo-v2.6-flash', '0.2', '0.05', '0.4'),
        ('avian', 'xiaomi/mimo-v2.6-pro', '0.435', '0.0036', '0.87'),
        ('github-copilot', 'claude-sonnet-5.5', '2', '0.20', '10'),
    ],
)
def test_price_check_preserves_rates_without_an_effective_date(
    request_date: str, provider_id: str, model_ref: str, input_rate: str, cache_rate: str, output_rate: str
) -> None:
    result = calc_price(
        Usage(input_tokens=2_000_000, cache_read_tokens=1_000_000, output_tokens=1_000_000),
        model_ref=model_ref,
        provider_id=provider_id,
        genai_request_timestamp=datetime.fromisoformat(request_date).replace(tzinfo=timezone.utc),
    )

    assert result.input_price == Decimal(input_rate) + Decimal(cache_rate)
    assert result.output_price == Decimal(output_rate)
