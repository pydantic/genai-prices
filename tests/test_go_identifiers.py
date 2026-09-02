from pathlib import Path

import pytest

from prices import go_identifiers, package_data
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


def test_go_package_pattern_accepts_import_comments() -> None:
    match = go_identifiers._GO_PACKAGE_PATTERN.search(
        'package genai_prices // import "github.com/pydantic/genai-prices/packages/go"\n'
    )

    assert match is not None
    assert match.group(1) == 'genai_prices'


def test_go_file_package_level_identifiers_parse_identifier_lists() -> None:
    identifiers = go_identifiers._go_file_package_level_identifiers(
        """
package genai_prices

const Existing, UsageFoo = 0, 1
var Other, UsageBar int
const (
    BlockExisting, UsageBaz = 2, 3
)
""",
        exclude_generated=False,
    )

    assert {'Existing', 'UsageFoo', 'Other', 'UsageBar', 'BlockExisting', 'UsageBaz'} <= identifiers


def test_go_file_package_level_identifiers_track_scope_instead_of_indentation() -> None:
    identifiers = go_identifiers._go_file_package_level_identifiers(
        """
package genai_prices

    var UsagePackage = 1
func example() {
var UsageLocal = 2
}
""",
        exclude_generated=False,
    )

    assert identifiers == {'UsagePackage', 'example'}


def test_go_file_package_level_identifiers_ignore_type_block_fields() -> None:
    identifiers = go_identifiers._go_file_package_level_identifiers(
        """
package genai_prices

type (
    UsageStruct struct {
        UsageField, Other int
    }
    UsageInterface interface {
        UsageMethod()
    }
)
""",
        exclude_generated=False,
    )

    assert {'UsageStruct', 'UsageInterface'} <= identifiers
    assert not {'UsageField', 'Other', 'UsageMethod'} & identifiers


def test_go_file_package_level_identifiers_ignore_multiline_function_parameters() -> None:
    identifiers = go_identifiers._go_file_package_level_identifiers(
        """
package genai_prices

type (
    UsageHandler func(
        UsageTypeParameter int,
    ) error
)
var (
    UsageCallback = func(
        UsageVarParameter int,
    ) {}
)
""",
        exclude_generated=False,
    )

    assert {'UsageHandler', 'UsageCallback'} <= identifiers
    assert not {'UsageTypeParameter', 'UsageVarParameter'} & identifiers


def test_go_file_package_level_identifiers_accept_function_comments_and_ignore_literal_braces() -> None:
    identifiers = go_identifiers._go_file_package_level_identifiers(
        """
package genai_prices

var interpreted = "}"
var raw = `}`
/* multiline comment
} */
func UsageFuture /* comment with } */ () {}
""",
        exclude_generated=False,
    )

    assert {'UsageFuture', 'interpreted', 'raw'} <= identifiers


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


def test_package_data_validates_identifiers_before_generating(monkeypatch: pytest.MonkeyPatch) -> None:
    def empty_provider_data(_path: Path) -> list[package_data.JsonData]:
        return []

    monkeypatch.setattr(package_data, '_load_provider_data', empty_provider_data)
    monkeypatch.setattr(
        package_data,
        'load_units',
        lambda: {'bad-name': {'dimensions': {'family': 'events'}, 'per': 1}},
    )

    def unexpected_generation(_provider_data: object, _units: object) -> None:
        raise AssertionError('generation started before Go identifiers were validated')

    monkeypatch.setattr(package_data, 'package_python_data', unexpected_generation)

    with pytest.raises(ValueError, match="Invalid generated Go identifier 'UsageBad-name'"):
        package_data.package_data()
