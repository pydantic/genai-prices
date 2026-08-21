import json
from typing import Any

import yaml
from utils import raw_bodies_path, this_dir

bodies: list[Any] = []
pydantic_ai_tests = this_dir / '../../../pydantic-ai/tests'
for f in pydantic_ai_tests.rglob('*.yaml'):
    text = f.read_text()
    if len(text) > 3_000_000:
        continue
    parsed = yaml.safe_load(text)
    interactions = parsed.get('interactions', [])
    for interaction in interactions:
        parsed_body = interaction.get('response', {}).get('parsed_body', {})
        if parsed_body and isinstance(parsed_body, dict):
            assert 'file' not in parsed_body
            filename = str(f.relative_to(pydantic_ai_tests))
            if (
                filename
                == 'models/openrouter/cassettes/test_cache/test_openrouter_cache_instructions_gemini_real_api.yaml'
            ):
                # This contains inconsistent usage in the sense that some tokens are counted as both cache read
                # and cache write, which adds up to more than the input tokens.
                # This is specific to how OpenRouter+Gemini work.
                # Probably the best solution is https://github.com/pydantic/genai-prices/issues/239.
                continue
            parsed_body['file'] = filename
            bodies.append(parsed_body)

raw_bodies_path.write_text(json.dumps(bodies))
