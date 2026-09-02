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


def test_go_package_level_identifiers_use_go_syntax(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    go_package_dir = tmp_path / 'packages' / 'go'
    go_package_dir.mkdir(parents=True)
    (go_package_dir / 'declarations.go').write_text(
        """
package /* import comment */ genai_prices

var PackageValue = 1

func example() {
    var UsageLocal = 1
    _ = UsageLocal
}

func UsageGeneric[
    T any,
](
    UsageParameter T,
) {}

type Receiver struct{}

func (Receiver) UsageMethod() {}

const /* declaration comment */ (
    UsageExisting = 1
)

type (
    UsageHandler func(
        UsageTypeParameter int,
    ) error
)

var (
    UsageExpression = other +
        UsageContinuation
    UsageCallback = func(
        UsageVarParameter int,
    ) {}
)
"""
    )
    (go_package_dir / 'data_units.go').write_text(
        """
package genai_prices

const UsageGenerated UsageKey = "generated"

var bundledUnits = map[UsageKey]int{}
"""
    )
    (go_package_dir / 'other.go').write_text('package other\n\nvar UsageOther = 1\n')
    monkeypatch.setattr(go_identifiers, 'root_dir', tmp_path)

    identifiers = go_identifiers.go_package_level_identifiers()

    assert {
        'PackageValue',
        'example',
        'UsageGeneric',
        'Receiver',
        'UsageExisting',
        'UsageHandler',
        'UsageExpression',
        'UsageCallback',
        'bundledUnits',
    } <= identifiers
    assert (
        not {
            'UsageLocal',
            'UsageParameter',
            'UsageMethod',
            'UsageTypeParameter',
            'UsageContinuation',
            'UsageVarParameter',
            'UsageGenerated',
            'UsageOther',
        }
        & identifiers
    )


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
