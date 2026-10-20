from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from inline_snapshot import snapshot
from pydantic import TypeAdapter

from prices import source_openrouter, source_prices, update
from prices.prices_types import (
    ClauseEquals,
    ClauseOr,
    ConditionalPrice,
    ModelInfo,
    ModelPrice,
    Provider,
    StartDateConstraint,
    Tier,
    TieredPrices,
)
from prices.source_openrouter import (
    OpenRouterEndpoint,
    OpenRouterEndpointsResponse,
    OpenRouterModel,
    OpenRouterPricing,
    OpenRouterResponse,
    report_unknown_pricing_fields,
)

from .fixtures import load_entries, load_mapping, load_payload

# The exact pricing keys OpenRouter added without notice, which `extra='forbid'` turned into 115
# `extra_forbidden` errors and a fully aborted pull (#532).
UNDECLARED_PRICING_FIELDS = {
    'overrides': None,
    'input_cache_write_1h': '0.000006',
    'input_audio_cache': '0.0000005',
    'image_output': '0.03',
    'audio_output': '0.00008',
}


def openrouter_model(
    model_id: str,
    *,
    canonical_slug: str | None = None,
    pricing: OpenRouterPricing | None = None,
) -> OpenRouterModel:
    return OpenRouterModel(
        id=model_id,
        canonical_slug=canonical_slug or model_id,
        name=f'Test: {model_id}',
        created=datetime(2026, 1, 1, tzinfo=UTC),
        description='Test description\n\nMore details',
        context_length=1_000_000,
        pricing=pricing or OpenRouterPricing(prompt=Decimal('0.000001'), completion=Decimal('0.000002')),
        supported_parameters=[],
    )


def pricing_with_extras(extras: dict[str, object]) -> OpenRouterPricing:
    return OpenRouterPricing.model_validate({'prompt': '0.000001', 'completion': '0.000002', **extras})


@pytest.mark.parametrize('model_id', ['google/gemini-3.5-flash', '~anthropic/claude-fable-latest'])
def test_openrouter_provider_model_info_preserves_api_model_id(model_id: str):
    model_info = openrouter_model(model_id).model_info(inc_description=False, strip_provider=False)

    assert model_info.id == model_id
    assert model_info.match == ClauseEquals(equals=model_id)
    assert model_info.description is None


def test_openrouter_provider_model_info_matches_canonical_slug_alias():
    model_info = openrouter_model(
        'moonshotai/kimi-k2.7-code',
        canonical_slug='moonshotai/kimi-k2.7-code-20260612',
    ).model_info(inc_description=False, strip_provider=False)

    assert model_info.id == 'moonshotai/kimi-k2.7-code'
    assert model_info.match == ClauseOr(
        or_=[  # pyright: ignore[reportCallIssue]
            ClauseEquals(equals='moonshotai/kimi-k2.7-code'),
            ClauseEquals(equals='moonshotai/kimi-k2.7-code-20260612'),
        ]
    )
    assert model_info.description is None


@pytest.mark.parametrize(
    ('model_id', 'native_model_id'),
    [
        ('google/gemini-3.5-flash', 'gemini-3.5-flash'),
        ('~anthropic/claude-fable-latest', 'claude-fable-latest'),
    ],
)
def test_native_provider_model_info_uses_native_model_id(model_id: str, native_model_id: str):
    model_info = openrouter_model(model_id).model_info()

    assert model_info.id == native_model_id
    assert model_info.match == ClauseEquals(equals=native_model_id)
    assert model_info.description == 'Test description'


def test_model_info_carries_context_window_only_when_requested():
    """OpenRouter's `context_length` describes their own offering, so it only goes on `openrouter` records."""
    model = openrouter_model('anthropic/claude-opus-5')

    openrouter_record = model.model_info(inc_description=False, strip_provider=False, include_context_window=True)
    native_record = model.model_info()

    assert openrouter_record.context_window == 1_000_000
    assert native_record.context_window is None


@pytest.mark.parametrize(
    ('reasoning_per_token', 'expected_reasoning_mtok'),
    [
        (Decimal('0.000003'), Decimal('3')),
        (Decimal('0.000002'), None),
        (None, None),
    ],
)
def test_openrouter_model_price_preserves_only_distinct_reasoning_rate(
    reasoning_per_token: Decimal | None,
    expected_reasoning_mtok: Decimal | None,
):
    price = OpenRouterPricing(
        prompt=Decimal('0.000001'),
        completion=Decimal('0.000002'),
        internal_reasoning=reasoning_per_token,
    ).model_price()

    expected = {'input_mtok': Decimal('1'), 'output_mtok': Decimal('2')}
    if expected_reasoning_mtok is not None:
        expected['output_reasoning_mtok'] = expected_reasoning_mtok
    assert price.model_dump(exclude_none=True) == expected


@pytest.mark.parametrize(
    ('canonical_slug', 'expected_provider_id'),
    [
        ('mistralai/mistral-large', 'mistral'),
        ('microsoft/phi-4', 'azure'),
        ('amazon/nova-pro', 'aws'),
        ('anthropic/claude-opus-5', 'anthropic'),
    ],
)
def test_openrouter_provider_id_applies_vendor_aliases(canonical_slug: str, expected_provider_id: str):
    model = openrouter_model(canonical_slug, canonical_slug=canonical_slug)

    assert model.provider_id() == expected_provider_id


def test_openrouter_provider_name_is_the_segment_before_the_colon():
    assert openrouter_model('anthropic/claude-opus-5').provider_name() == 'Test'


def test_openrouter_pricing_tolerates_unknown_fields():
    """A new OpenRouter pricing dimension must not abort the pull, and must not shift known prices (#532)."""
    baseline = OpenRouterPricing(
        prompt=Decimal('0.000001'),
        completion=Decimal('0.000002'),
        input_cache_read=Decimal('0.0000001'),
    )
    with_extras = OpenRouterPricing.model_validate(
        {
            'prompt': '0.000001',
            'completion': '0.000002',
            'input_cache_read': '0.0000001',
            **UNDECLARED_PRICING_FIELDS,
        }
    )

    assert set(with_extras.model_extra or {}) == set(UNDECLARED_PRICING_FIELDS)
    assert with_extras.model_price() == baseline.model_price()
    assert with_extras.has_negative_price() is False


def test_report_unknown_pricing_fields(capsys: pytest.CaptureFixture[str]):
    models = [
        openrouter_model('a/one', pricing=pricing_with_extras({'image_output': '0.03', 'input_audio_cache': '0.5'})),
        openrouter_model('a/two', pricing=pricing_with_extras({'input_audio_cache': '0.5'})),
        openrouter_model('a/three', pricing=pricing_with_extras({})),
    ]

    assert report_unknown_pricing_fields(models) == snapshot({'image_output': 1, 'input_audio_cache': 2})
    assert capsys.readouterr().out == snapshot("""\
OpenRouter sent pricing fields we ignore:
  input_audio_cache: 2 models
  image_output: 1 models

""")


def test_report_unknown_pricing_fields_silent_when_nothing_unknown(capsys: pytest.CaptureFixture[str]):
    assert report_unknown_pricing_fields([openrouter_model('a/one')]) == {}
    assert capsys.readouterr().out == ''


def test_openrouter_payload_decodes_strictly():
    """The recorded response must decode with nothing dropped — `OpenRouterResponse.data` is not lenient,
    so a shape change upstream surfaces here as a hard failure rather than as missing models."""
    raw_entries = load_entries('openrouter_models.json', 'data')
    response = OpenRouterResponse.model_validate_json(load_payload('openrouter_models.json'))

    assert len(response.data) == len(raw_entries)
    assert [model.id for model in response.data] == snapshot(
        [
            'anthropic/claude-opus-5',
            'google/gemini-3-pro-image',
            '~google/gemini-pro-latest',
            'openai/gpt-audio',
            'perplexity/sonar-deep-research',
            'openrouter/auto-beta',
        ]
    )


def test_openrouter_payload_carries_undeclared_pricing_fields(capsys: pytest.CaptureFixture[str]):
    """Guards the fixture itself: if it stopped containing real undeclared fields,
    `test_openrouter_payload_decodes_strictly` would pass for the wrong reason."""
    response = OpenRouterResponse.model_validate_json(load_payload('openrouter_models.json'))

    counts = report_unknown_pricing_fields(response.data)

    assert counts == snapshot(
        {
            'input_cache_write_1h': 1,
            'image_output': 1,
            'input_audio_cache': 2,
            'overrides': 1,
            'audio_output': 1,
        }
    )
    assert set(counts) == set(UNDECLARED_PRICING_FIELDS)
    assert 'input_audio_cache: 2 models' in capsys.readouterr().out


def test_openrouter_payload_builds_model_info_for_every_priced_model():
    response = OpenRouterResponse.model_validate_json(load_payload('openrouter_models.json'))

    negative = [model.id for model in response.data if model.pricing.has_negative_price()]
    assert negative == snapshot(['openrouter/auto-beta'])

    priced = [model.model_info() for model in response.data if not model.pricing.has_negative_price()]
    assert {info.id: info.prices.input_mtok for info in priced if isinstance(info.prices, ModelPrice)} == snapshot(
        {
            'claude-opus-5': Decimal('5'),
            'gemini-3-pro-image': Decimal('2'),
            'gemini-pro-latest': Decimal('2'),
            'gpt-audio': Decimal('2.5'),
            'sonar-deep-research': Decimal('2'),
        }
    )


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass


class FakeProvider:
    def __init__(self, id: str, matching_models: dict[str, ModelInfo]) -> None:
        self.id = id
        self.matching_models = matching_models

    def find_model(self, model_id: str) -> ModelInfo | None:
        return self.matching_models.get(model_id)


class FakeProviderYaml:
    def __init__(self, provider: FakeProvider, *, existing_model_ids: set[str] | None = None) -> None:
        self.provider = provider
        self.existing_model_ids = existing_model_ids or set()
        self.added: list[ModelInfo] = []
        self.updated: list[tuple[str, ModelInfo]] = []
        self.saved = False

    def update_model(self, model_id: str, model: ModelInfo) -> None:
        if model_id not in self.existing_model_ids:
            raise LookupError(model_id)
        self.updated.append((model_id, model))

    def add_model(self, model: ModelInfo) -> int:
        self.added.append(model)
        return 1

    def save(self) -> None:
        self.saved = True


def orchestration_response() -> OpenRouterResponse:
    response = OpenRouterResponse.model_validate_json(load_payload('openrouter_models.json'))
    claude = next(model for model in response.data if model.id == 'anthropic/claude-opus-5')
    response.data.extend(
        [
            openrouter_model('anthropic/identical', pricing=claude.pricing),
            openrouter_model('anthropic/free', pricing=OpenRouterPricing()),
            openrouter_model(
                'anthropic/different',
                pricing=OpenRouterPricing(prompt=Decimal('0.000004'), completion=Decimal('0.000008')),
            ),
            openrouter_model('anthropic/free-source', pricing=OpenRouterPricing()),
            openrouter_model(
                'anthropic/replaces-free',
                pricing=OpenRouterPricing(prompt=Decimal('0.000004'), completion=Decimal('0.000008')),
            ),
            openrouter_model(
                'microsoft/dynamic',
                pricing=OpenRouterPricing(prompt=Decimal('-1')),
            ),
        ]
    )
    return response


def matched_model(id: str) -> ModelInfo:
    return ModelInfo(
        id=id,
        match=ClauseEquals(equals=id),
        prices=ModelPrice(input_mtok=Decimal('1')),
    )


def fake_providers() -> tuple[dict[str, FakeProviderYaml], FakeProviderYaml, FakeProviderYaml]:
    openrouter_yaml = FakeProviderYaml(
        FakeProvider('openrouter', {}),
        existing_model_ids={'anthropic/claude-opus-5'},
    )
    anthropic_yaml = FakeProviderYaml(
        FakeProvider(
            'anthropic',
            {
                'claude-opus-5': matched_model('shared'),
                'identical': matched_model('shared'),
                'free': matched_model('shared'),
                'different': matched_model('shared'),
                'free-source': matched_model('was-free'),
                'replaces-free': matched_model('was-free'),
            },
        ),
        existing_model_ids={'shared', 'was-free'},
    )
    perplexity_yaml = FakeProviderYaml(FakeProvider('perplexity', {}))
    return (
        {
            'openrouter': openrouter_yaml,
            'anthropic': anthropic_yaml,
            'perplexity': perplexity_yaml,
        },
        openrouter_yaml,
        anthropic_yaml,
    )


def test_openrouter_main_exits_nonzero_on_empty_payload(monkeypatch: pytest.MonkeyPatch):
    def fake_get(_url: str) -> FakeResponse:
        return FakeResponse(b'{"data": []}')

    monkeypatch.setattr(httpx2, 'get', fake_get)
    monkeypatch.setattr(source_openrouter, 'get_providers_yaml', lambda: pytest.fail('nothing should be loaded'))

    with pytest.raises(SystemExit, match='OpenRouter returned no models'):
        source_openrouter.main('metadata')


def test_openrouter_main_updates_metadata_and_reports_unknown_pricing_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    providers, openrouter_yaml, anthropic_yaml = fake_providers()
    response = orchestration_response()

    def fake_get(url: str) -> FakeResponse:
        assert url == 'https://openrouter.ai/api/v1/models'
        return FakeResponse(response.model_dump_json().encode())

    monkeypatch.setattr(httpx2, 'get', fake_get)
    monkeypatch.setattr(source_openrouter, 'get_providers_yaml', lambda: providers)

    source_openrouter.main('metadata')

    output = capsys.readouterr().out
    assert 'OpenRouter sent pricing fields we ignore:' in output
    assert 'input_audio_cache: 2 models' in output
    assert 'Provider openrouter:' in output
    assert 'Provider anthropic:' in output
    assert 'Provider perplexity:' in output
    assert openrouter_yaml.saved
    assert anthropic_yaml.saved
    assert len(anthropic_yaml.updated) == 6
    assert [model.id for model in providers['perplexity'].added] == ['sonar-deep-research']

    # `context_window` flows onto `openrouter` records only, never onto native provider records
    assert all(model.context_window is not None for _, model in openrouter_yaml.updated)
    assert all(model.context_window is None for _, model in anthropic_yaml.updated)
    assert all(model.context_window is None for model in providers['perplexity'].added)


def test_openrouter_main_writes_prices(monkeypatch: pytest.MonkeyPatch):
    providers, _, _ = fake_providers()
    response = orchestration_response()
    written: dict[str, source_prices.SourcePricesType] = {}

    def fake_write(source: str, prices: source_prices.SourcePricesType) -> None:
        written[source] = prices

    def fake_get(url: str) -> FakeResponse:
        assert url == 'https://openrouter.ai/api/v1/models'
        return FakeResponse(response.model_dump_json().encode())

    monkeypatch.setattr(
        httpx2,
        'get',
        fake_get,
    )
    monkeypatch.setattr(source_openrouter, 'get_providers_yaml', lambda: providers)
    monkeypatch.setattr(
        source_openrouter.source_prices,
        'write_source_prices',
        fake_write,
    )

    source_openrouter.main('prices')

    assert set(written) == {'openrouter'}
    prices = written['openrouter']
    assert set(prices) == {'anthropic', 'perplexity'}
    assert prices['anthropic']['shared'].input_mtok == Decimal('5')
    assert prices['anthropic']['was-free'].input_mtok == Decimal('4')
    assert prices['perplexity']['sonar-deep-research'].input_mtok == Decimal('2')


def test_openrouter_main_adds_native_models_to_provider_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'anthropic.yml'
    provider_path.write_text(
        """\
id: anthropic
name: Anthropic
api_pattern: anthropic
models:
  - id: new-model
    match:
      or:
        - equals: new-model
    prices: {input_mtok: 1}
"""
    )
    anthropic_yaml = update.ProviderYaml(provider_path)
    openrouter_path = tmp_path / 'openrouter.yml'
    openrouter_path.write_text(
        """\
id: openrouter
name: OpenRouter
api_pattern: openrouter
models:
  - id: anthropic/new-model
    match:
      or:
        - equals: anthropic/new-model
    prices: {input_mtok: 1}
"""
    )
    openrouter_yaml = update.ProviderYaml(openrouter_path)
    response = OpenRouterResponse(
        data=[openrouter_model('anthropic/new-model', canonical_slug='anthropic/new-model-20260825')]
    )

    def fake_get(_url: str) -> FakeResponse:
        return FakeResponse(response.model_dump_json().encode())

    monkeypatch.setattr(httpx2, 'get', fake_get)
    monkeypatch.setattr(
        source_openrouter,
        'get_providers_yaml',
        lambda: {'openrouter': openrouter_yaml, 'anthropic': anthropic_yaml},
    )

    source_openrouter.main('metadata')

    [model] = update.ProviderYaml(provider_path).provider.models
    assert model.id == 'new-model'
    assert model.description == 'Test description'
    [openrouter_model_info] = update.ProviderYaml(openrouter_path).provider.models
    assert openrouter_model_info.is_match('anthropic/new-model-20260825')


def test_openrouter_main_deduplicates_native_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider_path = tmp_path / 'anthropic.yml'
    provider_path.write_text('id: anthropic\nname: Anthropic\napi_pattern: anthropic\nmodels: []\n')
    anthropic_yaml = update.ProviderYaml(provider_path)
    openrouter_yaml = FakeProviderYaml(FakeProvider('openrouter', {}))
    model = openrouter_model('anthropic/new-model')
    response = OpenRouterResponse(data=[model, model])

    def fake_get(_url: str) -> FakeResponse:
        return FakeResponse(response.model_dump_json().encode())

    monkeypatch.setattr(httpx2, 'get', fake_get)
    monkeypatch.setattr(
        source_openrouter,
        'get_providers_yaml',
        lambda: {'openrouter': openrouter_yaml, 'anthropic': anthropic_yaml},
    )

    source_openrouter.main('metadata')

    assert [model.id for model in update.ProviderYaml(provider_path).provider.models] == ['new-model']


@pytest.mark.parametrize(
    'existing_model_ids',
    [
        {'anthropic/one'},
        set[str](),
    ],
)
def test_openrouter_main_metadata_reports_only_the_changed_kind(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], existing_model_ids: set[str]
):
    response = OpenRouterResponse(data=[openrouter_model('anthropic/one')])
    openrouter_yaml = FakeProviderYaml(FakeProvider('openrouter', {}), existing_model_ids=existing_model_ids)

    def fake_get(url: str) -> FakeResponse:
        assert url == 'https://openrouter.ai/api/v1/models'
        return FakeResponse(response.model_dump_json().encode())

    monkeypatch.setattr(
        httpx2,
        'get',
        fake_get,
    )
    monkeypatch.setattr(source_openrouter, 'get_providers_yaml', lambda: {'openrouter': openrouter_yaml})

    source_openrouter.main('metadata')

    output = capsys.readouterr().out
    if existing_model_ids:
        assert '1 models updated' in output
        assert 'models added' not in output
    else:
        assert '1 models added' in output
        assert 'models updated' not in output


def test_openrouter_provider_models_tier_prompt_length_overrides_and_skip_unrepresentable_ones() -> None:
    long_context = pricing_with_extras(
        {
            'input_cache_read': '0.0000001',
            'overrides': [
                {'min_prompt_tokens': 400_000, 'prompt': '0.000004'},
                {'min_prompt_tokens': 200_000, 'prompt': '0.000002', 'completion': '0.000003'},
            ],
        }
    )
    time_of_day = pricing_with_extras({'overrides': [{'utc_days': ['monday'], 'prompt': '0.000002'}]})

    models = source_openrouter.parse_provider_models(
        [
            openrouter_model('google/long', pricing=long_context),
            openrouter_model('deepseek/off-peak', pricing=time_of_day),
            openrouter_model('openrouter/auto'),
            openrouter_model('~deepseek/deepseek-flash-latest'),
            openrouter_model('vendor/dynamic', pricing=OpenRouterPricing(prompt=Decimal('-1'))),
            openrouter_model('openai/gpt:batch', canonical_slug='openai/gpt-20260101'),
        ]
    )

    assert [model.id for model in models] == ['google/long', 'openai/gpt:batch']
    assert models[0].prices == ModelPrice(
        input_mtok=TieredPrices(
            base=Decimal('1'), tiers=[Tier(start=200_000, price=Decimal('2')), Tier(start=400_000, price=Decimal('4'))]
        ),
        cache_read_mtok=Decimal('0.1'),
        output_mtok=TieredPrices(base=Decimal('2'), tiers=[Tier(start=200_000, price=Decimal('3'))]),
    )
    assert models[0].context_window == 1_000_000
    assert models[1].match == ClauseEquals(equals='openai/gpt:batch')
    assert models[1].prices == ModelPrice(input_mtok=Decimal('1'), output_mtok=Decimal('2'))


def test_openrouter_batch_routes_take_cache_writes_at_their_input_discount() -> None:
    base = pricing_with_extras(
        {
            'prompt': '0.000002',
            'input_cache_write': '0.0000025',
            'overrides': [{'min_prompt_tokens': 272_000, 'prompt': '0.000004', 'input_cache_write': '0.000005'}],
        }
    )
    batch = pricing_with_extras({'overrides': [{'min_prompt_tokens': 272_000, 'prompt': '0.000002'}]})
    unaligned = pricing_with_extras({'overrides': [{'min_prompt_tokens': 128_000, 'prompt': '0.000002'}]})

    models = source_openrouter.parse_provider_models(
        [
            openrouter_model('openai/terra', pricing=base),
            openrouter_model('openai/terra:batch', pricing=batch),
            openrouter_model('openai/luna', pricing=base),
            openrouter_model('openai/luna:batch', pricing=unaligned),
            openrouter_model('openai/sol', pricing=OpenRouterPricing(input_cache_write=Decimal('0.000001'))),
            openrouter_model('openai/sol:batch'),
        ]
    )
    prices = {model.id: model.prices for model in models}

    assert isinstance(terra := prices['openai/terra:batch'], ModelPrice)
    assert terra.cache_write_mtok == TieredPrices(
        base=Decimal('1.25'), tiers=[Tier(start=272_000, price=Decimal('2.5'))]
    )
    assert isinstance(luna := prices['openai/luna:batch'], ModelPrice)
    assert luna.cache_write_mtok is None
    assert isinstance(sol := prices['openai/sol:batch'], ModelPrice)
    assert sol.cache_write_mtok is None


@pytest.mark.parametrize(
    ('overrides', 'error'),
    [
        ([{'min_prompt_tokens': 1, 'internal_reasoning': '0.1'}], 'Unexpected OpenRouter price override'),
        ([{'region': 'eu', 'prompt': '0.1'}], 'Unexpected OpenRouter price override'),
        ([{'min_prompt_tokens': 1, 'input_cache_write': '0.1'}], 'overrides input_cache_write for vendor/m without'),
    ],
)
def test_openrouter_provider_models_reject_overrides_they_cannot_tier(overrides: object, error: str) -> None:
    model = openrouter_model('vendor/m', pricing=pricing_with_extras({'overrides': overrides}))

    with pytest.raises(RuntimeError, match=error):
        source_openrouter.parse_provider_models([model])


def test_upsert_keeps_a_curated_tier_when_the_source_reports_only_its_base(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider_path = tmp_path / 'openrouter.yml'
    provider_path.write_text(
        """\
id: openrouter
name: OpenRouter
api_pattern: openrouter
models:
  - id: vendor/new-base
    match: {equals: vendor/new-base}
    prices: {input_mtok: {base: 1, tiers: [{start: 200000, price: 2}]}, output_mtok: 2}
  - id: vendor/same-base
    match: {equals: vendor/same-base}
    prices: {input_mtok: {base: 1, tiers: [{start: 200000, price: 2}]}, output_mtok: 2}
"""
    )
    models = source_openrouter.parse_provider_models(
        [
            openrouter_model('vendor/same-base', pricing=OpenRouterPricing(prompt=Decimal('0.000001'))),
            openrouter_model('vendor/new-base', pricing=OpenRouterPricing(prompt=Decimal('0.0000015'))),
        ]
    )

    assert update.ProviderYaml(provider_path).upsert_models(models, source='OpenRouter', min_count=1) == (0, 1)

    provider = update.ProviderYaml(provider_path).provider
    tiered = ModelPrice(
        input_mtok=TieredPrices(base=Decimal('1'), tiers=[Tier(start=200_000, price=Decimal('2'))]),
        output_mtok=Decimal('2'),
    )
    assert [model.prices for model in provider.models] == [tiered, tiered]
    assert capsys.readouterr().out == (
        'OpenRouter: kept vendor/new-base unchanged, vendor/new-base reports a flat rate where it is tiered\n'
    )


def test_openrouter_keeps_rates_that_only_drifted_within_tolerance(tmp_path: Path) -> None:
    provider_path = tmp_path / 'openrouter.yml'
    provider_path.write_text(
        """\
id: openrouter
name: OpenRouter
api_pattern: openrouter
models:
  - id: vendor/drift
    match: {equals: vendor/drift}
    context_window: 1000
    prices: {input_mtok: 0.446, output_mtok: 0.892}
  - id: vendor/jump
    match: {equals: vendor/jump}
    prices: {input_mtok: 0.0376, output_mtok: 0.08}
  - id: vendor/new-key
    match: {equals: vendor/new-key}
    prices: {input_mtok: 1, output_mtok: 2}
  - id: vendor/tiered
    match: {equals: vendor/tiered}
    prices: {input_mtok: {base: 1, tiers: [{start: 200000, price: 2}]}, output_mtok: 2}
"""
    )
    provider_yaml = update.ProviderYaml(provider_path)
    tiered = pricing_with_extras(
        {'prompt': '0.00000101', 'overrides': [{'min_prompt_tokens': 200_000, 'prompt': '0.00000199'}]}
    )
    models = source_openrouter.parse_provider_models(
        [
            openrouter_model(
                'vendor/drift',
                pricing=OpenRouterPricing.model_validate({'prompt': '0.000000443', 'completion': '0.000000885'}),
            ),
            openrouter_model(
                'vendor/jump',
                pricing=OpenRouterPricing.model_validate({'prompt': '0.0000000344', 'completion': '0.00000008'}),
            ),
            openrouter_model('vendor/new-key', pricing=pricing_with_extras({'input_cache_read': '0.0000001'})),
            openrouter_model('vendor/tiered', pricing=tiered),
            openrouter_model('vendor/brand-new'),
        ]
    )

    settled = [source_openrouter.settled(model, provider_yaml) for model in models]
    assert provider_yaml.upsert_models(settled, source='OpenRouter', min_count=1) == (1, 4)

    provider = update.ProviderYaml(provider_path).provider
    prices = {model.id: model.prices for model in provider.models}
    assert prices['vendor/drift'] == ModelPrice(input_mtok=Decimal('0.446'), output_mtok=Decimal('0.892'))
    assert prices['vendor/tiered'] == ModelPrice(
        input_mtok=TieredPrices(base=Decimal('1'), tiers=[Tier(start=200_000, price=Decimal('2'))]),
        output_mtok=Decimal('2'),
    )
    assert isinstance(jump := prices['vendor/jump'], list)
    assert jump[-1].prices == ModelPrice(input_mtok=Decimal('0.0344'), output_mtok=Decimal('0.08'))
    assert isinstance(new_key := prices['vendor/new-key'], list)
    assert new_key[-1].prices.cache_read_mtok == Decimal('0.1')
    drift = provider.find_model('vendor/drift')
    assert drift is not None and drift.context_window == 1000


def test_upsert_preserves_todays_price_and_drops_redundant_cache_on_new_models(tmp_path: Path) -> None:
    provider_path = tmp_path / 'openrouter.yml'
    provider_path.write_text(
        """\
id: openrouter
name: OpenRouter
api_pattern: openrouter
models:
  - id: vendor/m
    match: {equals: vendor/m}
    prices: {input_mtok: 1, cache_read_mtok: 0.5, output_mtok: 2}
"""
    )

    def report(model_id: str, input_mtok: str, cache_read_mtok: str) -> ModelInfo:
        return ModelInfo(
            id=model_id,
            match=ClauseEquals(equals=model_id),
            prices=ModelPrice(
                input_mtok=Decimal(input_mtok), cache_read_mtok=Decimal(cache_read_mtok), output_mtok=Decimal(2)
            ),
            prices_checked=date.today(),
        )

    update.ProviderYaml(provider_path).upsert_models(
        [report('vendor/m', '0.8', '0.4')], source='OpenRouter', min_count=1
    )
    update.ProviderYaml(provider_path).upsert_models(
        [report('vendor/m', '0.6', '0.6'), report('vendor/new', '0.6', '0.6')], source='OpenRouter', min_count=1
    )

    provider = update.ProviderYaml(provider_path).provider
    without_cache = ModelPrice(input_mtok=Decimal('0.6'), output_mtok=Decimal(2))
    assert [model.prices for model in provider.models] == [
        [
            ConditionalPrice(
                prices=ModelPrice(input_mtok=Decimal(1), cache_read_mtok=Decimal('0.5'), output_mtok=Decimal(2))
            ),
            ConditionalPrice(
                constraint=StartDateConstraint(start_date=date.today()),
                prices=ModelPrice(input_mtok=Decimal('0.8'), cache_read_mtok=Decimal('0.4'), output_mtok=Decimal(2)),
            ),
        ],
        without_cache,
    ]


# Official records for the models in `openrouter_provider_models.json`, matched the way the real provider files do.
ORIGINAL_PROVIDER_MODELS = {
    'deepseek': """\
  - id: deepseek-reasoner
    match: {or: [{equals: deepseek-reasoner}, {equals: deepseek-r1-0528}]}
    prices: {input_mtok: 0.135, cache_read_mtok: 0.035, output_mtok: 0.55}
""",
    'minimax': """\
  - id: MiniMax-M2
    match: {equals: minimax-m2}
    prices: {input_mtok: 0.3, cache_write_mtok: 0.375, cache_read_mtok: 0.03, output_mtok: 1.2}
""",
    'mistral': """\
  - id: mistral-medium-3-5
    match: {starts_with: mistral-medium-3}
    prices: {input_mtok: 1.5, output_mtok: 7.5}
""",
    'zai': """\
  - id: GLM-5
    match: {equals: glm-5}
    prices: {input_mtok: 1, cache_read_mtok: 0.2, output_mtok: 3.2}
  - id: GLM-5.3-Flash
    match: {equals: glm-5.3-flash}
    prices: {input_mtok: 0.15, cache_read_mtok: 0.03, output_mtok: 0.5}
""",
}

# The `openrouter` records as the cheapest-endpoint importer left them on 2026-10-20.
OPENROUTER_RECORDS = """\
id: openrouter
name: OpenRouter
api_pattern: openrouter
models:
  - id: deepseek/deepseek-r1-0528
    match: {equals: deepseek/deepseek-r1-0528}
    prices: {input_mtok: 0.5, cache_read_mtok: 0.35, output_mtok: 2.15}
  - id: minimax/minimax-m2
    match: {equals: minimax/minimax-m2}
    prices: {input_mtok: 0.255, cache_read_mtok: 0.03, output_mtok: 1.02}
  - id: mistralai/mistral-medium-3
    match: {equals: mistralai/mistral-medium-3}
    prices: {input_mtok: 0.4, cache_read_mtok: 0.04, output_mtok: 2}
  - id: qwen/qwen3.6-35b-a3b
    match: {equals: qwen/qwen3.6-35b-a3b}
    prices: {input_mtok: 0.1, cache_read_mtok: 0.05, output_mtok: 0.95}
  - id: z-ai/glm-5
    match: {equals: z-ai/glm-5}
    prices: {input_mtok: 0.6, cache_read_mtok: 0.12, output_mtok: 1.92}
  - id: z-ai/glm-5.3-flash
    match: {equals: z-ai/glm-5.3-flash}
    prices:
      - prices: {input_mtok: 0.075, cache_read_mtok: 0.015, output_mtok: 0.25}
      - constraint: {start_date: 2026-09-10}
        prices: {input_mtok: 0.15, cache_read_mtok: 0.03, output_mtok: 0.5}
  - id: z-ai/glm-5.3-flash:batch
    match: {equals: z-ai/glm-5.3-flash:batch}
    prices: {input_mtok: 0.05, cache_read_mtok: 0.01, output_mtok: 0.18}
"""

endpoints_schema = TypeAdapter(dict[str, OpenRouterEndpointsResponse])


def write_provider(tmp_path: Path, provider_id: str, models: str) -> update.ProviderYaml:
    path = tmp_path / f'{provider_id}.yml'
    path.write_text(f'id: {provider_id}\nname: {provider_id}\napi_pattern: {provider_id}\nmodels:\n{models}')
    return update.ProviderYaml(path)


def openrouter_api(endpoints: dict[str, bytes]) -> httpx2.MockTransport:
    models = load_payload('openrouter_provider_models.json')

    def handle(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == source_openrouter.MODELS_URL:
            return httpx2.Response(200, content=models)
        model_id = request.url.path.removeprefix('/api/v1/models/').removesuffix('/endpoints')
        assert str(request.url) == source_openrouter.ENDPOINTS_URL.format(model_id=model_id)
        return httpx2.Response(200, content=endpoints[model_id])

    return httpx2.MockTransport(handle)


def latest_prices(provider_path: Path) -> dict[str, ModelPrice]:
    return {
        model.id: source_openrouter.latest_price(model) for model in update.ProviderYaml(provider_path).provider.models
    }


def test_update_openrouter_provider_prices_models_at_official_or_most_common_rates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Recorded 2026-10-20, when the cheapest-endpoint rates of glm-5.3-flash and glm-5 flipped (#848)."""
    providers = {
        provider_id: write_provider(tmp_path, provider_id, models)
        for provider_id, models in ORIGINAL_PROVIDER_MODELS.items()
    }
    monkeypatch.setattr(source_openrouter, 'get_providers_yaml', lambda: providers)
    monkeypatch.setattr(source_openrouter, 'MIN_MODEL_COUNT', 1)
    provider_path = tmp_path / 'openrouter.yml'
    provider_path.write_text(OPENROUTER_RECORDS)
    before = latest_prices(provider_path)
    recorded = {
        model_id: json.dumps(payload).encode()
        for model_id, payload in load_mapping('openrouter_endpoints.json').items()
    }

    source_openrouter.update_openrouter_provider(provider_path, transport=openrouter_api(recorded))

    assert capsys.readouterr().out == 'OpenRouter prices updated: 0 added, 7 updated\n'
    after = latest_prices(provider_path)
    changed = {model_id: after[model_id] for model_id in after if after[model_id] != before[model_id]}
    assert changed == {
        # Z.AI's own endpoint charges the official rate; the model list reported a 40%-off reseller's.
        'z-ai/glm-5': ModelPrice(input_mtok=Decimal(1), cache_read_mtok=Decimal('0.2'), output_mtok=Decimal('3.2')),
        # Minimax's own endpoint is 15% off; before the discount it charges the official rate.
        'minimax/minimax-m2': ModelPrice(
            input_mtok=Decimal('0.3'),
            cache_write_mtok=Decimal('0.375'),
            cache_read_mtok=Decimal('0.03'),
            output_mtok=Decimal('1.2'),
        ),
    }
    # The model list reported $0.048 from one host; Z.AI and most other hosts charge the official $0.15.
    assert after['z-ai/glm-5.3-flash'].input_mtok == Decimal('0.15')
    # DeepSeek doesn't serve R1-0528, and Mistral's own endpoint doesn't charge the record `mistral-medium-3` matches.
    assert after['deepseek/deepseek-r1-0528'].input_mtok == Decimal('0.5')
    assert after['mistralai/mistral-medium-3'].input_mtok == Decimal('0.4')

    # The cheap and discounted hosts leave, as they did within hours on 2026-10-19 and 2026-10-20.
    responses = endpoints_schema.validate_json(load_payload('openrouter_endpoints.json'))
    for response in responses.values():
        response.data.endpoints = [
            endpoint
            for endpoint in response.data.endpoints
            if not endpoint.pricing.discount and endpoint.host() != 'open-inference'
        ]
    remaining = {model_id: response.model_dump_json().encode() for model_id, response in responses.items()}

    source_openrouter.update_openrouter_provider(provider_path, transport=openrouter_api(remaining))

    assert capsys.readouterr().out == 'OpenRouter prices updated: 0 added, 7 updated\n'
    assert latest_prices(provider_path) == after


def endpoint(
    tag: str,
    prompt: str,
    completion: str | None,
    *,
    cache_read: str | None = None,
    service_tier: str | None = None,
    discount: str = '0',
) -> OpenRouterEndpoint:
    pricing = OpenRouterPricing(
        prompt=Decimal(prompt) / 1_000_000,
        completion=None if completion is None else Decimal(completion) / 1_000_000,
        input_cache_read=None if cache_read is None else Decimal(cache_read) / 1_000_000,
        discount=Decimal(discount),
    )
    return OpenRouterEndpoint(tag=tag, service_tier=service_tier, pricing=pricing)


@pytest.mark.parametrize(
    ('endpoints', 'recorded', 'rates'),
    [
        pytest.param(
            [
                endpoint('a/us', '1', '2'),
                endpoint('a/eu', '1', '2'),
                endpoint('b', '2', '4'),
                endpoint('c/fp8', '2', '4'),
            ],
            None,
            ('2', '4'),
            id='each host counts once',
        ),
        pytest.param(
            [
                endpoint('a', '1', '2', cache_read='0.1'),
                endpoint('b', '1', '2', cache_read='0.2'),
                endpoint('c', '1', '2'),
                endpoint('d', '3', '4'),
                endpoint('e', '3', '4'),
            ],
            None,
            ('1', '2'),
            id='input and output rates outvote whole rate cards',
        ),
        pytest.param(
            [endpoint('a/flex', '3', '6', service_tier='flex'), endpoint('b', '9', '9'), endpoint('c', '9', '9')],
            None,
            ('9', '9'),
            id='standard tier only',
        ),
        pytest.param([endpoint('a/flex', '3', '6', service_tier='flex')], None, ('3', '6'), id='flex when alone'),
        pytest.param(
            [
                endpoint('a', '0.5', '1', discount='0.5'),
                endpoint('b', '0.5', '1', discount='0.5'),
                endpoint('c', '1', '2'),
            ],
            None,
            ('1', '2'),
            id='full price only',
        ),
        pytest.param([endpoint('a', '0.5', '1', discount='0.5')], None, ('0.5', '1'), id='discounted when alone'),
        pytest.param([endpoint('a', '2', '4'), endpoint('b', '1', '2')], None, ('1', '2'), id='tie takes cheapest'),
        pytest.param(
            [endpoint('a', '2', '4'), endpoint('b', '1', '2')],
            '{input_mtok: 2.05, output_mtok: 4}',
            ('2', '4'),
            id='tie keeps recorded rate',
        ),
        pytest.param([], None, ('1', '2'), id='no endpoints keeps listed rate'),
    ],
)
def test_endpoint_pricing_takes_the_rate_most_hosts_charge(
    tmp_path: Path, endpoints: list[OpenRouterEndpoint], recorded: str | None, rates: tuple[str, str]
) -> None:
    records = (
        '  []\n' if recorded is None else f'  - id: vendor/m\n    match: {{equals: vendor/m}}\n    prices: {recorded}\n'
    )
    provider_yaml = write_provider(tmp_path, 'openrouter', records)

    pricing = source_openrouter.with_endpoint_pricing(openrouter_model('vendor/m'), endpoints, provider_yaml).pricing

    assert (pricing.prompt, pricing.completion) == tuple(Decimal(rate) / 1_000_000 for rate in rates)


REPORTED = ModelPrice(input_mtok=Decimal(9), output_mtok=Decimal(9))
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.mark.parametrize(
    ('model_id', 'prices', 'endpoints', 'expected'),
    [
        pytest.param(
            'z-ai/glm',
            {'input_mtok': 1, 'cache_read_mtok': 0.2, 'output_mtok': 2, 'web_searches_kcount': 10},
            [endpoint('z-ai/fp8', '1.02', '2')],
            ModelPrice(input_mtok=Decimal(1), cache_read_mtok=Decimal('0.2'), output_mtok=Decimal(2)),
            id='own endpoint confirms the token rates',
        ),
        pytest.param(
            'z-ai/glm',
            {'input_mtok': {'base': 1, 'tiers': [{'start': 200_000, 'price': 2}]}, 'output_mtok': 2},
            [endpoint('z-ai', '1', '2')],
            ModelPrice(
                input_mtok=TieredPrices(base=Decimal(1), tiers=[Tier(start=200_000, price=Decimal(2))]),
                output_mtok=Decimal(2),
            ),
            id='tiered record compares its base',
        ),
        pytest.param(
            'z-ai/glm',
            [
                {'prices': {'input_mtok': 1, 'output_mtok': 2}},
                {'constraint': {'start_date': TOMORROW}, 'prices': {'input_mtok': 5, 'output_mtok': 10}},
            ],
            [endpoint('z-ai', '1', '2')],
            ModelPrice(input_mtok=Decimal(1), output_mtok=Decimal(2)),
            id='future price ignored',
        ),
        pytest.param(
            'z-ai/glm',
            {'input_mtok': 1, 'output_mtok': 2},
            [endpoint('z-ai', '0.5', '1', discount='0.5')],
            ModelPrice(input_mtok=Decimal(1), output_mtok=Decimal(2)),
            id='own endpoint before its discount',
        ),
        pytest.param(
            'z-ai/glm', {'input_mtok': 1, 'output_mtok': 2}, [endpoint('z-ai', '1.2', '2')], REPORTED, id='disagrees'
        ),
        pytest.param(
            'z-ai/glm',
            {'input_mtok': 1, 'output_mtok': 2},
            [endpoint('novita', '1', '2')],
            REPORTED,
            id='reseller only',
        ),
        pytest.param(
            'z-ai/glm',
            {'input_mtok': 1, 'output_mtok': 2},
            [endpoint('z-ai/priority', '1', '2', service_tier='priority')],
            REPORTED,
            id='own priority tier only',
        ),
        pytest.param(
            'z-ai/glm',
            {'input_mtok': 1, 'output_mtok': 2},
            [endpoint('z-ai', '1', None)],
            REPORTED,
            id='no output rate',
        ),
        pytest.param(
            'z-ai/glm',
            [
                {'prices': {'input_mtok': 1, 'output_mtok': 2}},
                {
                    'constraint': {'start_time': '01:00:00Z', 'end_time': '04:00:00Z'},
                    'prices': {'input_mtok': 2, 'output_mtok': 4},
                },
            ],
            [endpoint('z-ai', '1', '2')],
            REPORTED,
            id='time of day record',
        ),
        pytest.param('z-ai/glm', {}, [endpoint('z-ai', '1', '2')], REPORTED, id='free record'),
        pytest.param('z-ai/other', {'input_mtok': 1}, [endpoint('z-ai', '1', '2')], REPORTED, id='no record'),
        pytest.param('z-ai/glm:batch', {'input_mtok': 1}, [endpoint('z-ai', '1', '2')], REPORTED, id='route'),
        pytest.param('qwen/glm', {'input_mtok': 1}, [endpoint('qwen', '1', '2')], REPORTED, id='unmapped author'),
    ],
)
def test_official_price_applies_only_where_the_original_provider_charges_it(
    model_id: str, prices: object, endpoints: list[OpenRouterEndpoint], expected: ModelPrice
) -> None:
    zai = Provider.model_validate(
        {
            'id': 'zai',
            'name': 'Z.AI',
            'api_pattern': 'z',
            'models': [{'id': 'glm', 'match': {'equals': 'glm'}, 'prices': prices}],
        }
    )
    model = ModelInfo(id=model_id, match=ClauseEquals(equals=model_id), prices=REPORTED)

    assert source_openrouter.with_official_price(model, endpoints, {'zai': zai}).prices == expected
