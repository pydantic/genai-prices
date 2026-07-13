from datetime import datetime, timezone
from decimal import Decimal

import pytest
from inline_snapshot import snapshot

from genai_prices import Usage, calc_price
from genai_prices.data import providers
from genai_prices.data_snapshot import DataSnapshot, get_snapshot, set_custom_snapshot
from genai_prices.types import (
    ClauseAnd,
    ClauseContains,
    ClauseEndsWith,
    ClauseEquals,
    ClauseOr,
    ClauseRegex,
    ClauseStartsWith,
    MatchLogic,
    ModelInfo,
    ModelPrice,
    Provider,
    Tier,
    TieredPrices,
    calc_mtok_price,
    calc_unit_price,
)

pytestmark = pytest.mark.anyio


def test_sync_success_with_provider():
    price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o', provider_id='openai')

    assert price.input_price == snapshot(Decimal('0.0025'))
    assert price.output_price == snapshot(Decimal('0.001'))
    assert price.total_price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


@pytest.mark.parametrize(
    ('model_ref', 'expected_input_price'),
    [
        ('gpt-5.6-sol', Decimal('0.00625')),
        ('gpt-5.6-terra', Decimal('0.003125')),
        ('gpt-5.6-luna', Decimal('0.00125')),
    ],
)
def test_gpt_5_6_cache_write_price(model_ref: str, expected_input_price: Decimal):
    price = calc_price(
        Usage(input_tokens=1_000, cache_write_tokens=1_000),
        model_ref=model_ref,
        provider_id='openai',
    )

    assert price.input_price == expected_input_price
    assert price.output_price == Decimal(0)
    assert price.total_price == expected_input_price


@pytest.mark.parametrize(
    ('model_ref', 'short_write_rate', 'long_write_rate'),
    [
        ('gpt-5.6-sol', Decimal('6.25'), Decimal('12.5')),
        ('gpt-5.6-terra', Decimal('3.125'), Decimal('6.25')),
        ('gpt-5.6-luna', Decimal('1.25'), Decimal('2.5')),
    ],
)
def test_gpt_5_6_cache_write_price_context_boundary(
    model_ref: str,
    short_write_rate: Decimal,
    long_write_rate: Decimal,
):
    for tokens, rate in ((272_000, short_write_rate), (272_001, long_write_rate)):
        price = calc_price(
            Usage(input_tokens=tokens, cache_write_tokens=tokens),
            model_ref=model_ref,
            provider_id='openai',
        )

        expected_input_price = rate * tokens / 1_000_000
        assert price.input_price == expected_input_price
        assert price.output_price == Decimal(0)
        assert price.total_price == expected_input_price


@pytest.mark.parametrize(
    ('model_ref', 'input_rate', 'cache_write_rate', 'cache_read_rate', 'output_rate'),
    [
        ('gpt-5.6-sol', Decimal('10'), Decimal('12.5'), Decimal('1'), Decimal('45')),
        ('gpt-5.6-terra', Decimal('5'), Decimal('6.25'), Decimal('0.5'), Decimal('22.5')),
        ('gpt-5.6-luna', Decimal('2'), Decimal('2.5'), Decimal('0.2'), Decimal('9')),
    ],
)
def test_gpt_5_6_long_context_mixed_price(
    model_ref: str,
    input_rate: Decimal,
    cache_write_rate: Decimal,
    cache_read_rate: Decimal,
    output_rate: Decimal,
):
    price = calc_price(
        Usage(
            input_tokens=300_000,
            cache_write_tokens=100_000,
            cache_read_tokens=50_000,
            output_tokens=10_000,
        ),
        model_ref=model_ref,
        provider_id='openai',
    )

    expected_input_price = (input_rate * 150_000 + cache_write_rate * 100_000 + cache_read_rate * 50_000) / 1_000_000
    expected_output_price = output_rate * 10_000 / 1_000_000
    assert price.input_price == expected_input_price
    assert price.output_price == expected_output_price
    assert price.total_price == expected_input_price + expected_output_price


def test_sync_success_with_url():
    price = calc_price(
        Usage(input_tokens=1000, output_tokens=100, cache_write_tokens=20, cache_read_tokens=30),
        model_ref='claude-3.5-sonnet@abc',
        provider_api_url='https://api.anthropic.com/foo/bar',
    )
    assert price.input_price == snapshot(Decimal('0.002934'))
    assert price.output_price == snapshot(Decimal('0.0015'))
    assert price.total_price == snapshot(Decimal('0.004434'))
    assert price.model.name == snapshot('Claude Sonnet 3.5')
    assert price.provider.name == snapshot('Anthropic')
    assert price.auto_update_timestamp is None


def test_sync_success_with_model():
    price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='gpt-4o')

    assert price.input_price == snapshot(Decimal('0.0025'))
    assert price.output_price == snapshot(Decimal('0.001'))
    assert price.total_price == snapshot(Decimal('0.0035'))
    assert price.model.name == snapshot('gpt 4o')
    assert price.provider.id == snapshot('openai')
    assert price.auto_update_timestamp is None


def test_sync_success_with_model_regex():
    price = calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref='o3')

    assert price.input_price == snapshot(Decimal('0.002'))
    assert price.output_price == snapshot(Decimal('0.0008'))
    assert price.total_price == snapshot(Decimal('0.0028'))
    assert price.model.name == snapshot('o3')
    assert price.provider.id == snapshot('openai')


def test_openrouter_deepseek_v32_price():
    price = calc_price(
        Usage(input_tokens=2_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000),
        model_ref='deepseek/deepseek-v3.2',
        provider_id='openrouter',
    )

    assert price.input_price == snapshot(Decimal('0.4576'))
    assert price.output_price == snapshot(Decimal('0.3432'))
    assert price.total_price == snapshot(Decimal('0.8008'))
    assert price.model.name == snapshot('DeepSeek V3.2')
    assert price.provider.id == snapshot('openrouter')


def test_moonshotai_kimi_k27_code_price():
    price = calc_price(
        Usage(input_tokens=1_000, cache_read_tokens=100, output_tokens=100),
        model_ref='kimi-k2.7-code',
        provider_id='moonshotai',
    )

    assert price.model.id == 'kimi-k2.7-code'
    assert price.input_price == Decimal('0.000874')
    assert price.output_price == Decimal('0.0004')
    assert price.total_price == Decimal('0.001274')


def test_openrouter_kimi_k27_code_price():
    price = calc_price(
        Usage(input_tokens=1_000, cache_read_tokens=100, output_tokens=100),
        model_ref='moonshotai/kimi-k2.7-code',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'moonshotai/kimi-k2.7-code'
    assert price.input_price == Decimal('0.000691')
    assert price.output_price == Decimal('0.00035')
    assert price.total_price == Decimal('0.001041')


def test_openrouter_kimi_k27_code_dated_price():
    price = calc_price(
        Usage(input_tokens=2_038_030, output_tokens=13_034),
        model_ref='moonshotai/kimi-k2.7-code-20260612',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'moonshotai/kimi-k2.7-code'
    assert price.input_price == Decimal('1.5285225')
    assert price.output_price == Decimal('0.0456190')
    assert price.total_price == Decimal('1.5741415')


def test_openrouter_glm_51_dated_price():
    price = calc_price(
        Usage(input_tokens=27_447, output_tokens=83),
        model_ref='z-ai/glm-5.1-20260406',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'z-ai/glm-5.1'
    assert price.input_price == Decimal('0.02689806')
    assert price.output_price == Decimal('0.00025564')
    assert price.total_price == Decimal('0.02715370')


def test_openrouter_glm_52_dated_price():
    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref='z-ai/glm-5.2-20260616',
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == 'z-ai/glm-5.2'
    assert price.input_price == Decimal('0.0014')
    assert price.output_price == Decimal('0.00044')
    assert price.total_price == Decimal('0.00184')


def test_zhipuai_glm_52_price():
    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref='glm-5.2',
        provider_id='zhipuai',
    )

    assert price.model.id == 'GLM-5.2'
    assert price.input_price == Decimal('0.001103')
    assert price.output_price == Decimal('0.0003862')
    assert price.total_price == Decimal('0.0014892')


def test_openrouter_modern_dated_aliases_price():
    for model_ref, model_id, input_price, output_price, total_price in [
        (
            'minimax/minimax-m3-20260531',
            'minimax/minimax-m3',
            Decimal('0.0003'),
            Decimal('0.00012'),
            Decimal('0.00042'),
        ),
        (
            'qwen/qwen3.7-plus-20260602',
            'qwen/qwen3.7-plus',
            Decimal('0.0004'),
            Decimal('0.00016'),
            Decimal('0.00056'),
        ),
    ]:
        price = calc_price(
            Usage(input_tokens=1_000, output_tokens=100),
            model_ref=model_ref,
            provider_api_url='https://openrouter.ai/api/v1',
        )

        assert price.model.id == model_id
        assert price.input_price == input_price
        assert price.output_price == output_price
        assert price.total_price == total_price


@pytest.mark.parametrize('model_ref', ['deepseek/deepseek-v3.2', 'google/gemini-2.5-flash-lite'])
def test_openrouter_api_model_refs_priceable_by_api_url(model_ref: str):
    price = calc_price(
        Usage(input_tokens=1_000, output_tokens=100),
        model_ref=model_ref,
        provider_api_url='https://openrouter.ai/api/v1',
    )

    assert price.model.id == model_ref
    assert price.provider.id == 'openrouter'


def test_tiered_prices():
    price = calc_price(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='google')
    # Google uses threshold-based pricing: if context > 128K, ALL tokens charged at tier price
    # (0.15 * 500000) / 1_000_000 = 0.075

    assert price.input_price == snapshot(Decimal('0.075'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.075'))
    assert price.model.name == snapshot('gemini 1.5 flash')
    assert price.provider.id == snapshot('google')


def test_model_price_str_tiered_prices_include_dollar_prefix():
    model_price = ModelPrice(input_mtok=TieredPrices(base=Decimal('2.5'), tiers=[]))
    assert str(model_price) == '$2.5/input MTok (+tiers)'


def test_model_price_str_requests_and_private_state() -> None:
    model_price = ModelPrice(requests_kcount=Decimal('2'))
    object.__setattr__(model_price, '_private_state', Decimal('3'))

    assert str(model_price) == '$2 / K requests'


def test_calc_price_rejects_unregistered_dynamic_extra() -> None:
    price = ModelPrice(hovercraft_mtok=Decimal('1'))

    with pytest.raises(ValueError, match='Unknown price key: hovercraft_mtok'):
        price.calc_price(Usage(input_tokens=1))


def test_calc_price_rejects_dynamic_descendant_without_ancestors() -> None:
    price = ModelPrice(cache_image_read_mtok=Decimal('1'))

    with pytest.raises(ValueError, match='Missing ancestor price for cache_image_read_tokens'):
        price.calc_price(Usage(cache_image_read_tokens=1))


def test_set_custom_snapshot_does_not_validate_dynamic_model_prices() -> None:
    snapshot = DataSnapshot(
        providers=[
            Provider(
                id='testing',
                name='Testing',
                api_pattern='testing',
                models=[
                    ModelInfo(
                        id='bad-extra',
                        match=ClauseEquals('bad-extra'),
                        prices=ModelPrice(hovercraft_mtok=Decimal('1')),
                    )
                ],
            )
        ],
        from_auto_update=False,
    )

    try:
        set_custom_snapshot(snapshot)
        assert get_snapshot() is snapshot
    finally:
        set_custom_snapshot(None)


def test_requests_kcount_prices():
    # request count defaults to 1
    price = calc_price(Usage(), model_ref='sonar', provider_id='perplexity')
    assert price.input_price == snapshot(Decimal('0'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.012'))
    assert price.model.name == snapshot('Sonar')
    assert price.provider.name == snapshot('Perplexity')


def test_calc_unit_price_matches_mtok_wrapper() -> None:
    assert calc_unit_price(Decimal('2.5'), 500_000, total_input_tokens=0, per=1_000_000) == calc_mtok_price(
        Decimal('2.5'), 500_000, total_input_tokens=0
    )


def test_calc_unit_price_handles_absent_price_or_count() -> None:
    assert calc_unit_price(None, 500, total_input_tokens=0, per=1_000) == Decimal(0)
    assert calc_unit_price(Decimal('2.5'), None, total_input_tokens=0, per=1_000) == Decimal(0)


def test_calc_unit_price_handles_tiered_prices() -> None:
    price = TieredPrices(base=Decimal('1'), tiers=[Tier(start=100, price=Decimal('2'))])

    assert calc_unit_price(price, 10, total_input_tokens=100, per=1_000) == Decimal('0.01')
    assert calc_unit_price(price, 10, total_input_tokens=101, per=1_000) == Decimal('0.02')


def test_calc_unit_price_uses_non_million_normalization_factor() -> None:
    assert calc_unit_price(Decimal('12'), 2, total_input_tokens=0, per=1_000) == Decimal('0.024')


def test_price_constraint_before():
    price = calc_price(Usage(input_tokens=1000), model_ref='o3', genai_request_timestamp=datetime(2025, 6, 1))
    assert price.input_price == snapshot(Decimal('0.01'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.01'))
    assert price.model.name == snapshot('o3')
    assert price.provider.name == snapshot('OpenAI')


def test_price_constraint_after():
    price = calc_price(Usage(input_tokens=1000), model_ref='o3')
    assert price.input_price == snapshot(Decimal('0.002'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('0.002'))
    assert price.model.name == snapshot('o3')
    assert price.provider.name == snapshot('OpenAI')


def test_price_constraint_time_of_date():
    price = calc_price(
        Usage(input_tokens=100_000_000),
        model_ref='deepseek-chat',
        genai_request_timestamp=datetime(2025, 6, 1, 16, tzinfo=timezone.utc),
    )
    assert price.input_price == snapshot(Decimal('27.00'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('27'))
    assert price.model.name == snapshot('DeepSeek Chat')
    assert price.provider.name == snapshot('Deepseek')
    price = calc_price(
        Usage(input_tokens=100_000_000),
        model_ref='deepseek-chat',
        genai_request_timestamp=datetime(2025, 6, 1, 17, tzinfo=timezone.utc),
    )
    assert price.input_price == snapshot(Decimal('13.500'))
    assert price.output_price == snapshot(Decimal('0'))
    assert price.total_price == snapshot(Decimal('13.5'))
    assert price.model.name == snapshot('DeepSeek Chat')
    assert price.provider.name == snapshot('Deepseek')


def test_provider_not_found_id():
    with pytest.raises(LookupError, match="Unable to find provider provider_id='foobar'"):
        calc_price(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_id='foobar')


def test_provider_not_found_url():
    with pytest.raises(LookupError, match="Unable to find provider provider_api_url='foobar'"):
        calc_price(Usage(input_tokens=500_000), model_ref='gemini-1.5-flash', provider_api_url='foobar')


def test_provider_not_found_model_ref():
    with pytest.raises(LookupError, match="Unable to find provider with model matching 'llama2-70b-4096'"):
        calc_price(Usage(input_tokens=500_000), model_ref='llama2-70b-4096')


def test_model_not_found():
    with pytest.raises(LookupError, match="Unable to find model with model_ref='wrong' in google"):
        calc_price(Usage(input_tokens=500_000), model_ref='wrong', provider_id='google')


EXAMPLES: list[tuple[str, str]] = [
    # ('openrouter', 'amazon/us.amazon.nova-micro-v1:0'),
    # ('openrouter', 'amazon/us.amazon.nova-pro-v1:0'),
    ('anthropic', 'anthropic.claude-v2'),
    ('anthropic', 'claude-3-5-haiku-123'),
    ('anthropic', 'claude-3-5-haiku-20241022'),
    ('anthropic', 'claude-3-5-haiku-latest'),
    ('anthropic', 'claude-3-5-sonnet-20241022'),
    ('anthropic', 'claude-3-5-sonnet-latest'),
    ('anthropic', 'claude-3-7-sonnet-20250219'),
    ('anthropic', 'claude-3-7-sonnet-latest'),
    ('anthropic', 'claude-3-opus-20240229'),
    ('anthropic', 'claude-opus-4-20250514'),
    ('anthropic', 'claude-opus-4-20250514'),
    ('anthropic', 'claude-opus-4-0'),
    ('cohere', 'command-r7b-12-2024'),
    ('deepseek', 'deepseek-r1-distill-llama-70b'),
    ('google', 'gemini-1.5-flash-002'),
    ('google', 'gemini-1.5-flash-123'),
    ('google', 'gemini-1.5-flash'),
    ('google', 'gemini-1.5-pro-002'),
    ('google', 'gemini-2.0-flash-exp'),
    ('google', 'gemini-2.0-flash-thinking-exp-01-21'),
    ('google', 'gemini-2.0-flash'),
    ('google', 'gemini-2.5-pro-preview-03-25'),
    # ('openrouter', 'meta-llama/llama-3.3-70b-versatile'),
    # ('openrouter', 'meta-llama/llama-4-scout-17b-16e-instruct'),
    ('mistral', 'mistral-small-latest'),
    ('mistral', 'pixtral-12b-latest'),
    ('openai', 'gpt-3.5-turbo-0125'),
    ('openai', 'gpt-3.5-turbo-instruct:20230824-v2'),
    ('openai', 'gpt-4-0613'),
    ('openai', 'gpt-4.1-2025-04-14'),
    ('openai', 'gpt-4.1-mini-2025-04-14'),
    ('openai', 'gpt-4.1-mini'),
    ('openai', 'gpt-4.1-nano-2025-04-14'),
    ('openai', 'gpt-4.5-preview-2025-02-27'),
    ('openai', 'gpt-4o-2024-08-06'),
    ('openai', 'gpt-4o-2024-11-20'),
    ('openai', 'gpt-4o-audio-preview-2024-10-01'),
    ('openai', 'gpt-4o-audio-preview-2024-12-17'),
    ('openai', 'gpt-4o-mini-2024-07-18'),
    ('openai', 'gpt-4o-mini'),
    ('openai', 'gpt-4o'),
    ('openai', 'o3-mini-2025-01-31'),
    ('openai', 'gpt-5.4'),
    ('openai', 'gpt-5.4-pro'),
    ('openai', 'gpt-5.6-sol'),
    ('openai', 'gpt-5.6-terra'),
    ('openai', 'gpt-5.6-luna'),
    ('openai', 'text-embedding-3-small'),
]


@pytest.mark.parametrize('provider,model', EXAMPLES)
def test_models_found(provider: str, model: str):
    calc_price(Usage(input_tokens=1000, output_tokens=100), model_ref=model, provider_id=provider)


def test_all_bundled_models_have_a_priceable_public_ref():
    assert not _unpriceable_model_refs(providers)


def test_unpriceable_model_refs_reports_public_ref_errors():
    test_providers = [
        Provider(
            id='test-provider',
            name='Test Provider',
            api_pattern='https://example.com',
            models=[
                ModelInfo(
                    id='test-model',
                    match=ClauseRegex('^test-model$'),
                    prices=ModelPrice(input_mtok=Decimal('1')),
                )
            ],
        )
    ]

    assert _unpriceable_model_refs(test_providers) == [
        "test-provider/test-model: test-model: LookupError: Unable to find provider provider_id='test-provider'"
    ]


def _unpriceable_model_refs(test_providers: list[Provider]) -> list[str]:
    failures: list[str] = []
    usage = Usage(input_tokens=1000, cache_read_tokens=10, cache_write_tokens=10, output_tokens=100)

    for provider in test_providers:
        for model in provider.models:
            candidate_refs = dict.fromkeys([model.id, *_example_model_refs(model.match)])
            errors: list[str] = []

            for model_ref in candidate_refs:
                try:
                    calc_price(usage, model_ref=model_ref, provider_id=provider.id)
                except Exception as exc:
                    errors.append(f'{model_ref}: {type(exc).__name__}: {exc}')
                else:
                    break
            else:
                failures.append(f'{provider.id}/{model.id}: {"; ".join(errors)}')

    return failures


def _example_model_refs(match: MatchLogic) -> list[str]:
    if isinstance(match, ClauseEquals):
        return [match.equals]
    elif isinstance(match, ClauseStartsWith):
        return [match.starts_with]
    elif isinstance(match, ClauseEndsWith):
        return [match.ends_with]
    elif isinstance(match, ClauseContains):
        return [match.contains]
    elif isinstance(match, ClauseRegex):
        return []
    elif isinstance(match, ClauseOr):
        refs: list[str] = []
        for clause in match.or_:
            refs.extend(_example_model_refs(clause))
        return refs
    ref = ''
    for clause in match.and_:
        clause_refs = _example_model_refs(clause)
        if not clause_refs:
            return []
        ref += clause_refs[0]
    return [ref]


def test_example_model_refs_handles_regex_and_and_clauses():
    assert _example_model_refs(ClauseRegex('^test$')) == []
    assert _example_model_refs(ClauseAnd([ClauseStartsWith('test-'), ClauseEndsWith('model')])) == ['test-model']
    assert _example_model_refs(ClauseAnd([ClauseStartsWith('test-'), ClauseRegex('model')])) == []


def test_complex_usage():
    # Based on https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash
    # Input price
    #   $0.30 (text / image / video)
    #   $1.00 (audio)
    # Output price (including thinking tokens)
    #   $2.50
    # Context caching price
    #   $0.03 (text / image / video)
    #   $0.10 (audio)

    mil = 1_000_000
    assert calc_price(
        Usage(input_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('0.3'))

    # input_audio_tokens == input_tokens means all tokens are audio tokens
    assert calc_price(
        Usage(input_tokens=mil, input_audio_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('1.0'))

    assert calc_price(
        Usage(output_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('2.5'))

    # All cached text tokens
    assert calc_price(
        Usage(input_tokens=mil, cache_read_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('0.03'))

    # All cached audio tokens
    assert calc_price(
        Usage(input_tokens=mil, input_audio_tokens=mil, cache_read_tokens=mil, cache_audio_read_tokens=mil),
        'gemini-2.5-flash',
    ).total_price == snapshot(Decimal('0.10'))

    cached_text_tokens = 1
    uncached_text_tokens = 1_000
    cached_audio_tokens = 1_000_000
    uncached_audio_tokens = 1_000_000_000
    cached_tokens = cached_text_tokens + cached_audio_tokens
    audio_tokens = uncached_audio_tokens + cached_audio_tokens
    total_input_tokens = cached_text_tokens + uncached_text_tokens + cached_audio_tokens + uncached_audio_tokens
    assert total_input_tokens == 1_001_001_001

    assert (
        calc_price(
            Usage(
                input_tokens=total_input_tokens,
                input_audio_tokens=audio_tokens,
                cache_read_tokens=cached_tokens,
                cache_audio_read_tokens=cached_audio_tokens,
            ),
            'gemini-2.5-flash',
        ).total_price
        == snapshot(Decimal('1000.100_300_03'))
        == Decimal('0.03') * cached_text_tokens / mil
        + Decimal('0.3') * uncached_text_tokens / mil
        + Decimal('0.1') * cached_audio_tokens / mil
        + Decimal('1.0') * uncached_audio_tokens / mil
    )


def test_output_audio_usage():
    mil = 1_000_000

    assert calc_price(
        Usage(output_tokens=mil),
        'gpt-4o-realtime-preview',
    ).total_price == snapshot(Decimal('20.0'))

    # All audio tokens
    assert calc_price(
        Usage(output_tokens=mil, output_audio_tokens=mil),
        'gpt-4o-realtime-preview',
    ).total_price == snapshot(Decimal('80.0'))

    output_text_tokens = mil
    output_audio_tokens = mil * 1000
    total_output_tokens = output_text_tokens + output_audio_tokens
    assert (
        calc_price(
            Usage(output_tokens=total_output_tokens, output_audio_tokens=output_audio_tokens),
            'gpt-4o-realtime-preview',
        ).total_price
        == snapshot(Decimal('80020.0'))
        == Decimal('20') * output_text_tokens / mil + Decimal('80') * output_audio_tokens / mil
    )
