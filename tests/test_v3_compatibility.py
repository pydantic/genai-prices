import copy
from typing import Any, cast

import pytest

from prices.build import v3_data_schema
from prices.v3_compatibility import JsonData, validate_v3_schema_evolution


def _definition(schema: dict[str, Any], name: str) -> dict[str, Any]:
    return cast(dict[str, Any], schema['$defs'][name])


def test_validate_v3_schema_evolution_accepts_identical_and_additive_schema_changes() -> None:
    previous = v3_data_schema()
    candidate = copy.deepcopy(previous)
    runtime_unit = _definition(candidate, 'RuntimeUnitData')
    runtime_unit['properties']['future_annotation'] = {'type': 'string'}
    runtime_unit['properties']['per']['minimum'] = 0
    runtime_unit['properties']['per']['maximum'] = 9_007_199_254_740_992

    validate_v3_schema_evolution(previous, previous)
    validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_allows_added_enum_values_and_distinguishable_variants() -> None:
    previous: dict[str, Any] = {
        'additionalProperties': False,
        'properties': {
            'kind': {'enum': ['known'], 'type': 'string'},
            'capability': {
                'oneOf': [
                    {
                        'additionalProperties': False,
                        'properties': {'equals': {'type': 'string'}},
                        'required': ['equals'],
                        'type': 'object',
                    }
                ]
            },
        },
        'required': ['kind', 'capability'],
        'type': 'object',
    }
    candidate = copy.deepcopy(previous)
    candidate['properties']['kind']['enum'].append('future')
    candidate['properties']['capability']['oneOf'].append(
        {
            'additionalProperties': False,
            'properties': {'glob': {'type': 'string'}},
            'required': ['glob'],
            'type': 'object',
        }
    )

    validate_v3_schema_evolution(previous, candidate)


@pytest.mark.parametrize(
    ('mutation', 'message'),
    [
        ('remove property', 'removed property'),
        ('new required', 'newly requires'),
        ('remove required', 'no longer requires'),
        ('narrow type', 'narrowed type'),
        ('narrow lower bound', 'narrowed lower bound'),
        ('narrow upper bound', 'narrowed upper bound'),
        ('change default', 'changed default'),
        ('remove variant', 'removed or narrowed oneOf variant'),
        ('change reference', 'changed reference'),
    ],
)
def test_validate_v3_schema_evolution_rejects_stable_core_changes(mutation: str, message: str) -> None:
    previous = v3_data_schema()
    candidate = copy.deepcopy(previous)
    runtime_unit = _definition(candidate, 'RuntimeUnitData')
    if mutation == 'remove property':
        candidate['properties'].pop('units')
    elif mutation == 'new required':
        runtime_unit['properties']['future'] = {'type': 'string'}
        runtime_unit['required'].append('future')
    elif mutation == 'remove required':
        runtime_unit['required'].remove('dimensions')
    elif mutation == 'narrow type':
        runtime_unit['properties']['per']['type'] = 'string'
    elif mutation == 'narrow lower bound':
        runtime_unit['properties']['per']['minimum'] = 2
    elif mutation == 'narrow upper bound':
        runtime_unit['properties']['per']['maximum'] = 100
    elif mutation == 'change default':
        _definition(candidate, 'UsageExtractor')['properties']['api_flavor']['default'] = 'future'
    elif mutation == 'remove variant':
        _definition(candidate, 'ModelInfo')['properties']['match']['oneOf'].pop()
    else:
        _definition(candidate, 'Provider')['properties']['models']['items']['$ref'] = '#/$defs/Provider'

    with pytest.raises(ValueError, match=message):
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_rejects_removed_enum_values() -> None:
    previous: dict[str, JsonData] = {'enum': ['one', 'two'], 'type': 'string'}
    candidate: dict[str, JsonData] = {'enum': ['one'], 'type': 'string'}

    with pytest.raises(ValueError, match='removed enum values'):
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_rejects_ambiguous_behavior_changing_variant() -> None:
    previous = v3_data_schema()
    candidate = copy.deepcopy(previous)
    candidate['$defs']['ClauseCaseSensitiveEquals'] = {
        'additionalProperties': False,
        'properties': {
            'equals': {'type': 'string'},
            'case_sensitive': {'type': 'boolean'},
        },
        'required': ['equals', 'case_sensitive'],
        'type': 'object',
    }
    _definition(candidate, 'ModelInfo')['properties']['match']['oneOf'].append(
        {'$ref': '#/$defs/ClauseCaseSensitiveEquals'}
    )

    with pytest.raises(ValueError, match='ambiguous behavior-changing oneOf variant'):
        validate_v3_schema_evolution(previous, candidate)


@pytest.mark.parametrize(
    ('previous', 'candidate', 'message'),
    [
        ({}, {'type': 'string'}, 'narrowed unconstrained type'),
        ({}, {'enum': ['one']}, 'added an enum restriction'),
        ({}, {'const': 'one'}, 'added a const restriction'),
        ({'const': 'one'}, {'const': 'two'}, 'changed const'),
        ({}, {'minimum': 0}, 'added lower bound'),
        ({}, {'maximum': 1}, 'added upper bound'),
        ({}, {'pattern': 'x'}, 'added pattern restriction'),
        ({'pattern': 'x'}, {'pattern': 'y'}, 'changed pattern restriction'),
        ({}, {'uniqueItems': True}, 'newly requires unique array items'),
        ({'additionalProperties': True}, {'additionalProperties': False}, 'narrowed additional properties'),
        (
            {'additionalProperties': True},
            {'additionalProperties': {'type': 'string'}},
            'schema restriction for additional properties',
        ),
        ({}, {'items': {'type': 'string'}}, 'added items restriction'),
        ({}, {'anyOf': [{'type': 'string'}]}, 'added anyOf restriction'),
        ({'anyOf': [{'type': 'string'}]}, {}, 'removed anyOf variants'),
        ({}, {'$defs': {'Value': {}}, '$ref': '#/$defs/Value'}, 'replaced an inline schema with a reference'),
        ({'x-unsupported': 1}, {}, 'changed unsupported schema keywords'),
        ({'x-unsupported': 1}, {'x-unsupported': 2}, 'changed unsupported schema keyword'),
    ],
)
def test_validate_v3_schema_evolution_rejects_restricted_schema_narrowing(
    previous: dict[str, Any], candidate: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_accepts_supported_schema_widening() -> None:
    accepted_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = [
        ({'type': ['integer', 'string']}, {}),
        ({'enum': ['one']}, {}),
        ({'const': 'one'}, {}),
        ({'minimum': 1, 'maximum': 2}, {}),
        ({'pattern': 'x'}, {}),
        ({'additionalProperties': {'type': 'string'}}, {'additionalProperties': True}),
        ({'items': {'type': 'string'}}, {}),
        ({'enum': [['nested'], {'key': 'value'}]}, {'enum': [['nested'], {'key': 'value'}, 'future']}),
        ({'x-first': 1, 'x-second': 2}, {'x-first': 1, 'x-second': 2}),
    ]

    for previous, candidate in accepted_pairs:
        validate_v3_schema_evolution(previous, candidate)


def test_validate_v3_schema_evolution_accepts_reordered_and_disjoint_variants() -> None:
    string_variant = {'type': 'string'}
    integer_variant = {'type': 'integer'}
    previous: dict[str, Any] = {'oneOf': [string_variant, integer_variant]}
    reordered_candidate: dict[str, Any] = {'oneOf': [integer_variant, string_variant, {'type': 'object'}]}
    validate_v3_schema_evolution(previous, reordered_candidate)

    old_tagged: dict[str, Any] = {
        'properties': {'type': {'enum': ['old'], 'type': 'string'}},
        'required': ['type'],
        'type': 'object',
    }
    new_tagged: dict[str, Any] = {
        'properties': {'type': {'const': 'new', 'type': 'string'}},
        'required': ['type'],
        'type': 'object',
    }
    validate_v3_schema_evolution({'oneOf': [old_tagged]}, {'oneOf': [old_tagged, new_tagged]})


@pytest.mark.parametrize(
    ('previous', 'candidate', 'message'),
    [
        ([], {}, 'previous schema.*object schema'),
        ({1: {}}, {}, 'previous schema.*object schema'),
        ({'properties': {'value': []}}, {'properties': {'value': []}}, 'object schema'),
        ({'oneOf': {}}, {'oneOf': {}}, 'schema array'),
        ({'type': 1}, {'type': 1}, 'type string or string array'),
        ({'type': ['string', 1]}, {'type': ['string', 1]}, 'type string or string array'),
        ({'required': 'value'}, {'required': 'value'}, 'string array'),
        ({'enum': 'value'}, {'enum': 'value'}, 'expected an array'),
        ({'minimum': True}, {'minimum': True}, 'expected a number'),
        (
            {'$defs': {}, '$ref': 'https://example.com/schema'},
            {'$defs': {}, '$ref': 'https://example.com/schema'},
            'only local.*references',
        ),
        (
            {'$defs': {}, '$ref': '#/$defs/Missing'},
            {'$defs': {}, '$ref': '#/$defs/Missing'},
            'missing definition',
        ),
    ],
)
def test_validate_v3_schema_evolution_rejects_malformed_normal_form(
    previous: Any, candidate: Any, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_v3_schema_evolution(previous, candidate)
