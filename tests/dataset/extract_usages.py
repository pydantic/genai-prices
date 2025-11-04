from __future__ import annotations

import dataclasses
import json
from itertools import combinations
from typing import Any

from utils import raw_bodies_path, this_dir

from genai_prices import extract_usage
from genai_prices.data_snapshot import get_snapshot
from genai_prices.types import Provider, UsageExtractor


@dataclasses.dataclass
class Case:
    provider_id: str
    api_flavor: str
    model_ref: str | None
    usage_dict: dict[str, Any]


def main():
    bodies = json.loads(raw_bodies_path.read_text())
    snapshot = get_snapshot()

    extractors = [(provider, e) for provider in snapshot.providers if provider.extractors for e in provider.extractors]
    result: list[Any] = []

    for body in bodies:
        body_keys = set[str]().union(*[get_body_keys(extractor) for _, extractor in extractors])
        body = {k: body[k] for k in body_keys if k in body}

        extracted = [e for provider, extractor in extractors if (e := extract_and_check(body, extractor, provider))]
        if extracted:
            this_result: dict[str, Any] = {'body': body, 'extracted': []}
            result.append(this_result)
            models: set[str] = {case.model_ref for case in extracted if case.model_ref}
            assert len(models) in (0, 1), models
            if models:
                this_result['model'] = models.pop()

            for case1, case2 in combinations(extracted, 2):
                for k, v in case1.usage_dict.items():
                    if k in case2.usage_dict:
                        assert v == case2.usage_dict[k]

            for case in extracted:
                extractor_dict = {'provider_id': case.provider_id, 'api_flavor': case.api_flavor}
                for other in this_result['extracted']:
                    if case.usage_dict == other['usage']:
                        other['extractors'].append(extractor_dict)
                        break
                else:
                    this_result['extracted'].append({'usage': case.usage_dict, 'extractors': [extractor_dict]})

    (this_dir / 'usages.json').write_text(json.dumps(result, indent=2, sort_keys=True))


def get_body_keys(extractor: UsageExtractor):
    keys = set[str]()
    for path in [extractor.model_path, extractor.root]:
        if path:
            if isinstance(path, list):
                path = path[0]
            assert isinstance(path, str)
            keys.add(path)
    return keys


def extract_and_check(body: dict[str, Any], extractor: UsageExtractor, provider: Provider):
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
