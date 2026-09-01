from __future__ import annotations

import dataclasses
import datetime
import json
from collections import defaultdict
from collections.abc import Mapping
from itertools import combinations
from typing import Any

from utils import raw_bodies_path, this_dir

from genai_prices import Usage, calc_price, extract_usage
from genai_prices._usage import UsageValue, sum_usage_values
from genai_prices.data_snapshot import get_snapshot
from genai_prices.types import Provider, UsageExtractor
from genai_prices.units import _get_registry


@dataclasses.dataclass
class Case:
    provider_id: str
    api_flavor: str
    model_ref: str | None
    usage_dict: dict[str, UsageValue]


extractors = [
    (provider, e) for provider in get_snapshot().providers if provider.extractors for e in provider.extractors
]


def get_body_keys(extractor: UsageExtractor) -> set[str]:
    keys = set[str]()
    for path in [extractor.model_path, extractor.root]:
        if path:  # pragma: no branch - published extractors always use nonempty paths
            if isinstance(path, list):
                path = path[0]
            assert isinstance(path, str)
            keys.add(path)
    return keys


body_keys = set[str]().union(*[get_body_keys(extractor) for _, extractor in extractors])
assert 'file' not in body_keys
body_keys.add('file')


registry = _get_registry()


def get_direct_refinement_groups() -> dict[str, dict[str, tuple[str, ...]]]:
    """Group mutually exclusive direct refinements by ancestor and added dimension."""
    result: dict[str, dict[str, tuple[str, ...]]] = {}
    for ancestor_key, ancestor in registry.units.items():
        groups: defaultdict[str, list[str]] = defaultdict(list)
        for descendant_key, descendant in registry.units.items():
            added_dimensions = descendant.dimensions.items() - ancestor.dimensions.items()
            if ancestor.dimensions.items() < descendant.dimensions.items() and len(added_dimensions) == 1:
                dimension, _ = next(iter(added_dimensions))
                groups[dimension].append(descendant_key)

        multi_value_groups = {dimension: tuple(keys) for dimension, keys in groups.items() if len(keys) > 1}
        if multi_value_groups:
            result[ancestor_key] = multi_value_groups
    return result


direct_refinement_groups = get_direct_refinement_groups()


def check_usage_consistency(usage_values: Mapping[str, UsageValue]) -> None:
    """Check necessary containment constraints for positive extracted usage values."""
    for usage_key, value in usage_values.items():
        for ancestor_key in registry.ancestor_usage_keys(usage_key):
            ancestor_value = usage_values.get(ancestor_key)
            if ancestor_value is None:
                raise AssertionError(f'{usage_key} ({value}) is missing aggregate {ancestor_key}')
            if value > ancestor_value:
                raise AssertionError(f'{usage_key} ({value}) cannot exceed {ancestor_key} ({ancestor_value})')

    for aggregate_key, groups in direct_refinement_groups.items():
        aggregate_value = usage_values.get(aggregate_key)
        if aggregate_value is None:
            continue
        for dimension, refinement_keys in groups.items():
            refinements = [(key, usage_values[key]) for key in refinement_keys if key in usage_values]
            if len(refinements) < 2:
                continue
            refinement_total = sum_usage_values(value for _, value in refinements)
            if refinement_total > aggregate_value:
                details = ', '.join(f'{key} ({value})' for key, value in refinements)
                raise AssertionError(
                    f'mutually exclusive {dimension} usage {details} totals {refinement_total}, '
                    f'which exceeds {aggregate_key} ({aggregate_value})'
                )


def rebuild_usages() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recompute the dataset from the recorded bodies. Returns `(current, rebuilt)`; writes nothing."""
    usages_file = this_dir / 'usages.json'
    current_result: list[dict[str, Any]] = json.loads(usages_file.read_text())
    if raw_bodies_path.exists():  # pragma: no cover - raw recordings are not committed with the golden dataset
        bodies = json.loads(raw_bodies_path.read_text())
        result = get_usages(bodies)
    else:
        result = current_result
    return current_result, get_usages([r['body'] for r in result])


def main(*, write: bool = True):
    # Compare before writing. This used to write first and compare after, so a failing run left the
    # file rewritten and the *second* run always passed - which reads as "I fixed it" when nothing was.
    current_result, result = rebuild_usages()
    if result == current_result:
        print('usages.json is up to date.')
        return
    if not write:
        raise AssertionError('usages.json is out of date - run `python tests/dataset/extract_usages.py` and commit it.')
    (this_dir / 'usages.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    raise AssertionError('usages.json updated!!!')


def get_usages(bodies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for body in bodies:
        body = {k: body[k] for k in body_keys if k in body}

        cases: list[Case] = [
            e for provider, extractor in extractors if (e := extract_and_check(body, extractor, provider))
        ]
        if cases:  # pragma: no branch - the golden dataset retains only extractable response bodies
            this_result: dict[str, Any] = {'body': body, 'extracted': []}
            result.append(this_result)
            models: set[str] = {case.model_ref for case in cases if case.model_ref}
            assert len(models) in (0, 1), models
            if models:
                this_result['model'] = models.pop()
            else:
                assert 'model' not in body

            # TODO
            # check_cases_usages_match(cases)

            has_price = False
            for case in cases:
                extractor_result = case_to_result(case, this_result)
                if 'input_price' in extractor_result or 'output_price' in extractor_result:
                    has_price = True
            if not has_price and 'model' in this_result:
                model = this_result['model']
                assert (
                    # TODO fix/investigate
                    model
                    in [
                        # https://github.com/pydantic/genai-prices/issues/232
                        'groq/compound',
                        # new models with no prices yet
                        'glm-4.6v',
                        'gpt-oss:20b',
                        'models/gemini-2.5-pro',
                        'openai.gpt-5.6-luna',
                        'openai.gpt-oss-120b',
                        'openai.gpt-oss-safeguard-20b',
                        'openai/gpt-5-mini-2025-08-07',
                        'openai/gpt-5.6-sol',
                        'qwen3:0.6b',
                        'x-ai/grok-4',
                        'zai-glm-4.7',
                    ]
                    # google-gla sometimes adding 'models/' prefix
                    or model.startswith('models/')
                    # prices missing
                    or 'openrouter' in body['file']
                ), (body['file'], model)

    return result


def case_to_result(case: Case, this_result: dict[str, Any]):
    extractor_dict: dict[str, Any] = {'provider_id': case.provider_id, 'api_flavor': case.api_flavor}
    if case.model_ref:
        try:
            price = calc_price(
                Usage(**case.usage_dict),
                provider_id=case.provider_id,
                model_ref=case.model_ref,
                genai_request_timestamp=datetime.datetime(2025, 11, 6, 12, 0, 0, tzinfo=datetime.timezone.utc),
            )
        except LookupError:
            pass
        except Exception as e:  # pragma: no cover - the checked-in golden corpus has no calculation errors
            message = f'Error calculating price for {case.provider_id}:{case.model_ref} with usage {case.usage_dict} and file {this_result["body"]["file"]}'
            raise AssertionError(message) from e
        else:
            extractor_dict['input_price'] = str(price.input_price)
            extractor_dict['output_price'] = str(price.output_price)
            if price.total_price != price.input_price + price.output_price:
                extractor_dict['total_price'] = str(price.total_price)
    for other in this_result['extracted']:
        if case.usage_dict == other['usage']:
            other['extractors'].append(extractor_dict)
            break
    else:
        this_result['extracted'].append({'usage': case.usage_dict, 'extractors': [extractor_dict]})
    return extractor_dict


def check_cases_usages_match(cases: list[Case]):  # pragma: no cover - its call site is intentionally disabled above
    for case1, case2 in combinations(cases, 2):
        for k, v in case1.usage_dict.items():
            if k in case2.usage_dict:
                assert v == case2.usage_dict[k]


def extract_and_check(body: dict[str, Any], extractor: UsageExtractor, provider: Provider) -> Case | None:
    try:
        model_ref, usage = extractor.extract(body)
    except (LookupError, ValueError):
        return None
    flavor = extractor.api_flavor
    assert (model_ref, usage) == provider.extract_usage(body, api_flavor=flavor)
    if model_ref and provider.find_model(model_ref):
        extracted = extract_usage(body, provider_id=provider.id, api_flavor=flavor)
        assert extracted.model and extracted.model.is_match(model_ref)
        assert usage == extracted.usage
    usage_dict: dict[str, UsageValue] = {k: v for k, v in usage.__dict__.items() if v}
    try:
        check_usage_consistency(usage_dict)
    except AssertionError as exc:
        source = body.get('file', '<unknown response>')
        raise AssertionError(f'Inconsistent extracted usage for {provider.id}/{flavor} in {source}: {exc}') from exc
    return Case(provider.id, flavor, model_ref, usage_dict)


if __name__ == '__main__':
    main()
