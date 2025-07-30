from genai_prices.sources import find_provider_by_id
from genai_prices import data

# Use actual provider data for testing
actual_providers = data.providers


class TestProviderMatching:
    def test_find_providers_by_exact_id_match(self):
        """Test finding providers by exact ID match."""
        result = find_provider_by_id(actual_providers, 'google')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_id(actual_providers, 'anthropic')
        assert result is not None
        assert result.id == 'anthropic'

        result = find_provider_by_id(actual_providers, 'openai')
        assert result is not None
        assert result.id == 'openai'

    def test_find_providers_by_provider_match_logic(self):
        """Test finding providers by provider_match logic."""
        result = find_provider_by_id(actual_providers, 'google-gla')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_id(actual_providers, 'google-vertex')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_id(actual_providers, 'gemini')
        assert result is not None
        assert result.id == 'google'

    def test_case_insensitive_matching(self):
        """Test case insensitive matching."""
        result = find_provider_by_id(actual_providers, 'GOOGLE-GLA')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_id(actual_providers, 'ANTHROPIC')
        assert result is not None
        assert result.id == 'anthropic'

    def test_whitespace_handling(self):
        """Test whitespace handling in provider names."""
        result = find_provider_by_id(actual_providers, '  google-gla  ')
        assert result is not None
        assert result.id == 'google'

        result = find_provider_by_id(actual_providers, 'openai ')
        assert result is not None
        assert result.id == 'openai'

    def test_unknown_providers(self):
        """Test handling of unknown providers."""
        result = find_provider_by_id(actual_providers, 'unknown-provider')
        assert result is None

        result = find_provider_by_id(actual_providers, 'custom-ai')
        assert result is None

        # Model names should not match providers anymore
        result = find_provider_by_id(actual_providers, 'claude')
        assert result is None

        result = find_provider_by_id(actual_providers, 'gpt')
        assert result is None
