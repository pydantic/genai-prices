from prices.prices_types import UsageExtractorMapping


def test_source_usage_extractor_dest_accepts_current_destination() -> None:
    mapping = UsageExtractorMapping(path='prompt_tokens', dest='input_tokens')

    assert mapping.dest == 'input_tokens'


def test_source_usage_extractor_dest_accepts_registry_defined_string() -> None:
    mapping = UsageExtractorMapping(path='future_tokens', dest='future_tokens')

    assert mapping.dest == 'future_tokens'
