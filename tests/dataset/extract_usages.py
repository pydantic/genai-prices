import dataclasses
import json
from itertools import combinations
from typing import Any

from utils import raw_bodies_path, this_dir

from genai_prices import extract_usage
from genai_prices.data_snapshot import get_snapshot
from genai_prices.types import Provider, UsageExtractor


def main():
    bodies = json.loads(raw_bodies_path.read_text())
    snapshot = get_snapshot()

    extractors = [(provider, e) for provider in snapshot.providers if provider.extractors for e in provider.extractors]
    usages: list[Any] = []
    for body in bodies:
        body_keys = set[str]().union(*[get_body_keys(extractor) for _, extractor in extractors])
        body = {k: body[k] for k in body_keys if k in body}

        extracteds: list[Any] = []
        for provider, extractor in extractors:
            extracted = extract_and_check(body, extractor, provider)
            if extracted:
                extracteds.append(extracted)
        if extracteds:
            usages.append((body, extracteds))

    result: list[Any] = []
    for body, extracted in usages:
        this_result: dict[str, Any] = {'body': body, 'extracted': []}
        result.append(this_result)
        models = {e1[2] for e1 in extracted if e1[2]}
        assert len(models) in (0, 1), models
        if models:
            this_result['model'] = models.pop()

        for e1, e2 in combinations(extracted, 2):
            u1 = e1[3]
            u2 = e2[3]
            for k, v in u1.items():
                if k in u2:
                    assert v == u2[k]

        for provider_id, flavor, _model_ref, usage_dict in extracted:
            for other in this_result['extracted']:
                if usage_dict == other['usage']:
                    other['extractors'].append({'provider_id': provider_id, 'api_flavor': flavor})
                    break
            else:
                this_result['extracted'].append(
                    {'usage': usage_dict, 'extractors': [{'provider_id': provider_id, 'api_flavor': flavor}]}
                )

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
    return provider.id, flavor, model_ref, usage_dict


main()
