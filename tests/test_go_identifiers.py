import pytest

from prices import go_identifiers
from prices.build import load_units


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


def test_go_package_level_identifiers_find_real_declarations_and_exclude_generated_constants() -> None:
    identifiers = go_identifiers.go_package_level_identifiers()

    assert {
        'UsageKey',
        'RemoteDataURL',
        'ErrProviderNotFound',
        'bundledCalculator',
        'NewCalculator',
        'unitDef',
    } <= identifiers
    assert 'bundledUnits' in identifiers
    assert 'UsageInputTokens' not in identifiers
    assert 'UnmarshalJSON' not in identifiers


def test_go_file_package_level_identifiers_ignore_function_local_declarations() -> None:
    identifiers = go_identifiers._go_file_package_level_identifiers(
        """
package genai_prices

var PackageValue = 1

func example() {
    var UsageFoo = 1
    const (
        UsageBar = 2
    )
}
""",
        exclude_generated=False,
    )

    assert identifiers == {'PackageValue', 'example'}


def test_go_file_package_level_identifiers_parse_commented_declaration_blocks() -> None:
    identifiers = go_identifiers._go_file_package_level_identifiers(
        """
package genai_prices

const ( // package constants
    Existing = 1
    UsageFoo = 2
)
""",
        exclude_generated=False,
    )

    assert {'Existing', 'UsageFoo'} <= identifiers


def test_validate_go_usage_key_identifiers_accepts_current_vocabulary() -> None:
    go_identifiers.validate_go_usage_key_identifiers(load_units())


def test_validate_go_usage_key_identifiers_rejects_invalid_names_and_collisions() -> None:
    with pytest.raises(ValueError, match="Invalid generated Go identifier 'UsageBad-name'"):
        go_identifiers.validate_go_usage_key_identifiers(['bad-name'])

    with pytest.raises(ValueError, match='identifier collision.*foo_bar.*fooBar.*UsageFooBar'):
        go_identifiers.validate_go_usage_key_identifiers(['foo_bar', 'fooBar'])

    with pytest.raises(ValueError, match="'UsageKey'.*'key'.*existing package-level declaration"):
        go_identifiers.validate_go_usage_key_identifiers(['key'])


def test_validate_go_usage_key_identifiers_rejects_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    def keyword_transform(_usage_key: str) -> str:
        return 'var'

    monkeypatch.setattr(go_identifiers, 'go_usage_key_identifier', keyword_transform)

    with pytest.raises(ValueError, match="identifier 'var'.*is a keyword"):
        go_identifiers.validate_go_usage_key_identifiers(['events'])
