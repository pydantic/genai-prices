from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from inline_snapshot import snapshot

from prices import source_openrouter, source_prices, update
from prices.prices_types import ClauseEquals, ClauseOr, ModelInfo, ModelPrice
from prices.source_openrouter import (
    OpenRouterModel,
    OpenRouterPricing,
    OpenRouterResponse,
    report_unknown_pricing_fields,
)

from .fixtures import load_entries, load_payload

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
        created=datetime(2026, 1, 1, tzinfo=timezone.utc),
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

    openrouter_record = model.model_info(inc_description=False, strip_provider=False, inc_context_window=True)
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
