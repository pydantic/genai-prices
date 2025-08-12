import pytest
from inline_snapshot import snapshot

from genai_prices.calc import find_provider_by_id
from genai_prices.data import providers


def test_find_providers_by_exact_id_match():
    """Test finding providers by exact ID match."""
    result = find_provider_by_id(providers, 'google')
    assert result is not None
    assert result.id == 'google'

    result = find_provider_by_id(providers, 'anthropic')
    assert result is not None
    assert result.id == 'anthropic'

    result = find_provider_by_id(providers, 'openai')
    assert result is not None
    assert result.id == 'openai'


def test_find_providers_by_provider_match_logic():
    """Test finding providers by provider_match logic."""
    result = find_provider_by_id(providers, 'google-gla')
    assert result is not None
    assert result.id == 'google'

    result = find_provider_by_id(providers, 'google-vertex')
    assert result is not None
    assert result.id == 'google'

    result = find_provider_by_id(providers, 'gemini')
    assert result is not None
    assert result.id == 'google'


def test_case_insensitive_matching():
    """Test case insensitive matching."""
    result = find_provider_by_id(providers, 'GOOGLE-GLA')
    assert result is not None
    assert result.id == 'google'

    result = find_provider_by_id(providers, 'ANTHROPIC')
    assert result is not None
    assert result.id == 'anthropic'


def test_whitespace_handling():
    """Test whitespace handling in provider names."""
    result = find_provider_by_id(providers, '  google-gla  ')
    assert result is not None
    assert result.id == 'google'

    result = find_provider_by_id(providers, 'openai ')
    assert result is not None
    assert result.id == 'openai'


def test_unknown_providers():
    """Test handling of unknown providers."""
    result = find_provider_by_id(providers, 'unknown-provider')
    assert result is None

    result = find_provider_by_id(providers, 'custom-ai')
    assert result is None

    result = find_provider_by_id(providers, 'claude')
    assert result is None

    result = find_provider_by_id(providers, 'gpt')
    assert result is None


@pytest.mark.parametrize(
    'provider_ref,provider_id',
    [
        ('openai', snapshot('openai')),
        ('anthropic', snapshot('anthropic')),
        ('google-gla', snapshot('google')),
        ('bedrock', snapshot('aws')),
        ('google-vertex', snapshot('google')),
        ('groq', snapshot('groq')),
        ('gemini', snapshot('google')),
        ('mistral_ai', snapshot('mistral')),
        ('openrouter', snapshot('openrouter')),
        ('azure', snapshot('azure')),
        ('gcp.vertex.agent', snapshot('google')),
        ('perplexity', snapshot('perplexity')),
        ('Google', snapshot('google')),
        ('vertex_ai', snapshot('google')),
        ('google', snapshot('google')),
        ('xai', snapshot('x-ai')),
        ('anthropic.messages', snapshot('anthropic')),
        ('deepseek', snapshot('deepseek')),
        ('openai.chat', snapshot('openai')),
        ('aws.bedrock', snapshot('aws')),
        ('together_ai', snapshot('together')),
        ('cohere_chat', snapshot('cohere')),
    ],
)
def test_provider_matching(provider_ref: str, provider_id: str):
    result = find_provider_by_id(providers, provider_ref)
    assert result is not None
    assert result.id == provider_id
