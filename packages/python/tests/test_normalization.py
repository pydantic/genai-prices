import sys
import os

# Add the parent directory to the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from genai_prices.types import find_provider_by_match, Provider, ClauseOr, ClauseEquals

# Mock providers for testing
mock_providers = [
    Provider(
        id='google',
        name='Google',
        api_pattern='',
        models=[],
        provider_match=ClauseOr(or_=[
            ClauseEquals(equals='google'),
            ClauseEquals(equals='gemini'),
            ClauseEquals(equals='google-gla'),
            ClauseEquals(equals='google-vertex'),
            ClauseEquals(equals='google-ai')
        ])
    ),
    Provider(
        id='meta',
        name='Meta',
        api_pattern='',
        models=[],
        provider_match=ClauseOr(or_=[
            ClauseEquals(equals='meta'),
            ClauseEquals(equals='meta-llama'),
            ClauseEquals(equals='llama')
        ])
    ),
    Provider(
        id='mistral',
        name='Mistral',
        api_pattern='',
        models=[],
        provider_match=ClauseOr(or_=[
            ClauseEquals(equals='mistral'),
            ClauseEquals(equals='mistralai')
        ])
    ),
    Provider(
        id='anthropic',
        name='Anthropic',
        api_pattern='',
        models=[],
        provider_match=ClauseOr(or_=[
            ClauseEquals(equals='anthropic'),
            ClauseEquals(equals='claude')
        ])
    ),
    Provider(
        id='openai',
        name='OpenAI',
        api_pattern='',
        models=[],
        provider_match=ClauseOr(or_=[
            ClauseEquals(equals='openai'),
            ClauseEquals(equals='gpt')
        ])
    )
]


class TestProviderMatching:
    def test_find_providers_by_exact_id_match(self):
        """Test finding providers by exact ID match."""
        result = find_provider_by_match(mock_providers, 'google')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_match(mock_providers, 'meta')
        assert result is not None
        assert result.id == 'meta'

        result = find_provider_by_match(mock_providers, 'mistral')
        assert result is not None
        assert result.id == 'mistral'

    def test_find_providers_by_provider_match_logic(self):
        """Test finding providers by provider_match logic."""
        result = find_provider_by_match(mock_providers, 'gemini')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_match(mock_providers, 'google-gla')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_match(mock_providers, 'google-vertex')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_match(mock_providers, 'meta-llama')
        assert result is not None
        assert result.id == 'meta'

        result = find_provider_by_match(mock_providers, 'llama')
        assert result is not None
        assert result.id == 'meta'

        result = find_provider_by_match(mock_providers, 'mistralai')
        assert result is not None
        assert result.id == 'mistral'

        result = find_provider_by_match(mock_providers, 'claude')
        assert result is not None
        assert result.id == 'anthropic'

        result = find_provider_by_match(mock_providers, 'gpt')
        assert result is not None
        assert result.id == 'openai'

    def test_case_insensitive_matching(self):
        """Test case insensitive matching."""
        result = find_provider_by_match(mock_providers, 'GEMINI')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_match(mock_providers, 'GOOGLE-GLA')
        assert result is not None
        assert result.id == 'google'

    def test_whitespace_handling(self):
        """Test whitespace handling in provider names."""
        result = find_provider_by_match(mock_providers, '  gemini  ')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_match(mock_providers, 'google-gla ')
        assert result is not None
        assert result.id == 'google'

    def test_unknown_providers(self):
        """Test handling of unknown providers."""
        result = find_provider_by_match(mock_providers, 'unknown-provider')
        assert result is None

        result = find_provider_by_match(mock_providers, 'custom-ai')
        assert result is None
