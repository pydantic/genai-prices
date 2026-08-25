from __future__ import annotations

from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import cast

import pytest

SCRIPTS_DIR = Path(__file__).parents[1] / '.github' / 'scripts'
SPEC = spec_from_file_location('compare_v2_schemas', SCRIPTS_DIR / 'compare_v2_schemas.py')
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
schemas_match = cast(Callable[[object, object], bool], getattr(MODULE, 'schemas_match'))


def test_description_annotations_do_not_change_the_contract() -> None:
    base = {'description': 'old docs', 'properties': {'name': {'type': 'string', 'description': 'old field docs'}}}
    head = {'description': 'new docs', 'properties': {'name': {'type': 'string', 'description': 'new field docs'}}}

    assert schemas_match(head, base)


@pytest.mark.parametrize(
    'head',
    [
        {'properties': {'name': {'type': 'integer'}}},
        {'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        {'properties': {'name': {'type': 'string'}, 'added': {'type': 'string'}}},
        {'properties': {'enabled': {'const': 1}}},
    ],
)
def test_contract_changes_are_rejected(head: dict[str, object]) -> None:
    base = {'properties': {'name': {'type': 'string'}, 'enabled': {'const': True}}}

    assert not schemas_match(head, base)


def test_property_named_description_keeps_its_contract() -> None:
    base = {'properties': {'description': {'type': 'string', 'description': 'old field docs'}}}
    docs_only = {'properties': {'description': {'type': 'string', 'description': 'new field docs'}}}
    contract_change = {'properties': {'description': {'type': 'string', 'maxLength': 100}}}

    assert schemas_match(docs_only, base)
    assert not schemas_match(contract_change, base)


@pytest.mark.parametrize('keyword', ['const', 'default', 'enum', 'examples'])
def test_description_keys_in_instance_values_are_contract_data(keyword: str) -> None:
    base = {'properties': {'value': {keyword: {'description': 'old'}}}}
    head = {'properties': {'value': {keyword: {'description': 'new'}}}}

    assert not schemas_match(head, base)
