import pytest

from prices import go_identifiers


@pytest.mark.parametrize(
    ('usage_key', 'identifier'),
    [
        ('input_tokens', 'UsageInputTokens'),
        ('input_5m_tokens', 'UsageInput5MTokens'),
        ('request__count', 'UsageRequest_Count'),
    ],
)
def test_go_usage_key_identifier_preserves_existing_spelling(usage_key: str, identifier: str) -> None:
    assert go_identifiers.go_usage_key_identifier(usage_key) == identifier
