from genai_prices import normalize_provider, normalize_model


class TestProviderNormalization:
    def test_google_provider_aliases(self):
        """Test Google provider aliases normalization."""
        assert normalize_provider('gemini') == 'google'
        assert normalize_provider('google-gla') == 'google'
        assert normalize_provider('google-vertex') == 'google'
        assert normalize_provider('google-ai') == 'google'
        assert normalize_provider('GOOGLE-GLA') == 'google'

    def test_meta_provider_aliases(self):
        """Test Meta provider aliases normalization."""
        assert normalize_provider('meta-llama') == 'meta'
        assert normalize_provider('llama') == 'meta'

    def test_mistral_provider_aliases(self):
        """Test Mistral provider aliases normalization."""
        assert normalize_provider('mistralai') == 'mistral'

    def test_anthropic_provider_aliases(self):
        """Test Anthropic provider aliases normalization."""
        assert normalize_provider('anthropic') == 'anthropic'
        assert normalize_provider('claude') == 'anthropic'

    def test_openai_provider_aliases(self):
        """Test OpenAI provider aliases normalization."""
        assert normalize_provider('openai') == 'openai'
        assert normalize_provider('gpt') == 'openai'

    def test_unknown_providers(self):
        """Test handling of unknown providers."""
        assert normalize_provider('unknown-provider') == 'unknown-provider'
        assert normalize_provider('custom-ai') == 'custom-ai'

    def test_whitespace_handling(self):
        """Test whitespace handling in provider names."""
        assert normalize_provider('  gemini  ') == 'google'
        assert normalize_provider('google-gla ') == 'google'


class TestModelNormalization:
    def test_anthropic_claude_opus_4_models(self):
        """Test Anthropic Claude Opus 4 model normalization."""
        assert normalize_model('anthropic', 'claude-opus-4-20250514') == 'claude-opus-4-20250514'
        assert normalize_model('anthropic', 'claude-opus-4-something') == 'claude-opus-4-20250514'
        assert normalize_model('anthropic', 'claude-opus-4') == 'claude-opus-4-20250514'

    def test_openai_gpt_35_models(self):
        """Test OpenAI GPT-3.5 model normalization."""
        assert normalize_model('openai', 'gpt-3.5-turbo') == 'gpt-3.5-turbo'
        assert normalize_model('openai', 'gpt-3.5-turbo-16k') == 'gpt-3.5-turbo'
        assert normalize_model('openai', 'gpt-3.5-turbo-instruct') == 'gpt-3.5-turbo'

    def test_other_provider_models(self):
        """Test that models for other providers are not normalized."""
        assert normalize_model('google', 'gemini-2.5-pro') == 'gemini-2.5-pro'
        assert normalize_model('mistral', 'mistral-large') == 'mistral-large'
        assert normalize_model('anthropic', 'claude-3-sonnet') == 'claude-3-sonnet'

    def test_whitespace_handling(self):
        """Test whitespace handling in model names."""
        assert normalize_model('anthropic', '  claude-opus-4  ') == 'claude-opus-4-20250514'
        assert normalize_model('openai', ' gpt-3.5-turbo ') == 'gpt-3.5-turbo'
