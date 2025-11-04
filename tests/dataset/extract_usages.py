from __future__ import annotations

import dataclasses
import json
from itertools import combinations
from typing import Any

from utils import raw_bodies_path, this_dir

from genai_prices import Usage, calc_price, extract_usage
from genai_prices.data_snapshot import get_snapshot
from genai_prices.types import Provider, UsageExtractor


@dataclasses.dataclass
class Case:
    provider_id: str
    api_flavor: str
    model_ref: str | None
    usage_dict: dict[str, Any]


extractors = [
    (provider, e) for provider in get_snapshot().providers if provider.extractors for e in provider.extractors
]


def main():
    usages_file = this_dir / 'usages.json'
    current_result = json.loads(usages_file.read_text())
    if raw_bodies_path.exists():
        bodies = json.loads(raw_bodies_path.read_text())
        result = get_usages(bodies)
    else:
        result = current_result
    simplified_bodies = [r['body'] for r in result]
    assert get_usages(simplified_bodies) == result
    dumped = json.dumps(result, indent=2, sort_keys=True)
    usages_file.write_text(dumped + '\n')
    if result != current_result:
        raise AssertionError('usages.json updated!!!')
    print('usages.json is up to date.')


def get_usages(bodies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for body in bodies:
        body_keys = set[str]().union(*[get_body_keys(extractor) for _, extractor in extractors])
        body = {k: body[k] for k in body_keys if k in body}

        cases: list[Case] = [
            e for provider, extractor in extractors if (e := extract_and_check(body, extractor, provider))
        ]
        if cases:
            this_result: dict[str, Any] = {'body': body, 'extracted': []}
            result.append(this_result)
            models: set[str] = {case.model_ref for case in cases if case.model_ref}
            assert len(models) in (0, 1), models
            if models:
                this_result['model'] = models.pop()

            check_cases_usages_match(cases)

            for case in cases:
                case_to_result(case, this_result)

    return result


def case_to_result(case: Case, this_result: dict[str, Any]):
    extractor_dict: dict[str, Any] = {'provider_id': case.provider_id, 'api_flavor': case.api_flavor}
    if case.model_ref:
        try:
            price = calc_price(Usage(**case.usage_dict), provider_id=case.provider_id, model_ref=case.model_ref)
        except LookupError:
            pass
        else:
            assert price.input_price + price.output_price == price.total_price
            extractor_dict['input_price'] = str(price.input_price)
            extractor_dict['output_price'] = str(price.output_price)
    for other in this_result['extracted']:
        if case.usage_dict == other['usage']:
            other['extractors'].append(extractor_dict)
            break
    else:
        this_result['extracted'].append({'usage': case.usage_dict, 'extractors': [extractor_dict]})


def check_cases_usages_match(cases: list[Case]):
    for case1, case2 in combinations(cases, 2):
        for k, v in case1.usage_dict.items():
            if k in case2.usage_dict:
                assert v == case2.usage_dict[k]


def get_body_keys(extractor: UsageExtractor) -> set[str]:
    keys = set[str]()
    for path in [extractor.model_path, extractor.root]:
        if path:
            if isinstance(path, list):
                path = path[0]
            assert isinstance(path, str)
            keys.add(path)
    return keys


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
    usage_dict = {k: v for k, v in dataclasses.asdict(usage).items() if v}
    return Case(provider.id, flavor, model_ref, usage_dict)


main()
