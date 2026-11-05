"""Pin which providers may have a `default` api_flavor extractor.

A provider's `default` extractor is what answers requests that do not name a
flavor, so it should read the API of the provider that declares it. See the
`api_flavor` rule in `AGENTS.md`. `openrouter` is the documented temporary
exception: its `default` extractor still holds a copy of System One until the
gateway sends `systemone`.
"""

from genai_prices.data import providers

EXPECTED_DEFAULT_FLAVOR_PROVIDERS = frozenset(
    {
        'anthropic',
        'arcee',
        'aws',
        'cloudflare',
        'cohere',
        'databricks',
        'google',
        'groq',
        'huggingface_cerebras',
        'huggingface_fireworks-ai',
        'huggingface_groq',
        'huggingface_hyperbolic',
        'huggingface_nebius',
        'huggingface_novita',
        'huggingface_nscale',
        'huggingface_ovhcloud',
        'huggingface_publicai',
        'huggingface_sambanova',
        'huggingface_together',
        'minimax',
        'mistral',
        'openai-decisions',
        'openrouter',
        'ovhcloud',
        'perplexity',
        'typesafe',
        'x-ai',
    }
)


def test_default_flavor_is_the_providers_own_api() -> None:
    actual_default_flavor_providers = {
        provider.id
        for provider in providers
        if any(extractor.api_flavor == 'default' for extractor in provider.extractors or ())
    }
    assert actual_default_flavor_providers == EXPECTED_DEFAULT_FLAVOR_PROVIDERS, (
        'The set of providers with a `default` api_flavor extractor changed. A `default` extractor must '
        'read the API of the provider that declares it; see the api_flavor rule in AGENTS.md before '
        'adding or removing a provider here. `openrouter` remains until its transitional `default` '
        'extractor is replaced by `systemone`.'
    )
