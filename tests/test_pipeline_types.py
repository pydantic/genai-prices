import re
from datetime import date, time, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from prices.prices_types import (
    ArrayMatch,
    ClauseAnd,
    ClauseContains,
    ClauseEndsWith,
    ClauseEquals,
    ClauseOr,
    ClauseRegex,
    ClauseStartsWith,
    ConditionalPrice,
    MatchLogic,
    ModelInfo,
    ModelPrice,
    Provider,
    StartDateConstraint,
    Tier,
    TieredPrices,
    TimeOfDateConstraint,
    UsageExtractor,
    UsageExtractorMapping,
    clause_discriminator,
    doesnt_end_with_find_item,
    get_model_ids,
    match_logic_schema,
    providers_schema,
    serialize_decimal,
)


def _model(
    model_id: str, *, match: MatchLogic | None = None, prices: ModelPrice | list[ConditionalPrice] | None = None
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        match=match or ClauseEquals(equals=model_id),
        prices=prices if prices is not None else ModelPrice(),
    )


def _provider(models: list[ModelInfo], *, extractors: list[UsageExtractor] | None = None) -> Provider:
    return Provider(
        id='provider', name='Provider', api_pattern='https://api.example.test/*', models=models, extractors=extractors
    )


def test_provider_finds_models_and_excludes_removed_and_free() -> None:
    provider = _provider(
        [
            _model('free'),
            _model('paid', prices=ModelPrice(input_mtok=Decimal(1))),
            _model('removed', prices=ModelPrice(input_mtok=Decimal(1))),
        ],
        extractors=[
            UsageExtractor(root='usage', mappings=[UsageExtractorMapping(path='input_tokens', dest='input_tokens')])
        ],
    )
    provider.models[2].removed = True

    assert provider.find_model('PAID') is provider.models[1]
    assert provider.find_model('unknown') is None

    provider.exclude_removed()
    provider.exclude_free()

    assert [model.id for model in provider.models] == ['paid']

    assert _provider([_model('without-extractor')], extractors=None).extractors is None


def test_provider_rejects_duplicate_extractor_flavors() -> None:
    extractors = [
        UsageExtractor(root='usage', mappings=[UsageExtractorMapping(path='input_tokens', dest='input_tokens')]),
        UsageExtractor(root='result', mappings=[UsageExtractorMapping(path='output_tokens', dest='output_tokens')]),
    ]

    with pytest.raises(ValidationError, match=r"Duplicate extraction api_flavor: \['default'\]"):
        _provider([_model('model')], extractors=extractors)


def test_provider_rejects_duplicate_model_ids() -> None:
    models = [
        _model('duplicate', match=ClauseEquals(equals='first')),
        _model('duplicate', match=ClauseEquals(equals='second')),
    ]

    with pytest.raises(ValidationError, match=r"Duplicate model ids: \['duplicate'\]"):
        _provider(models)


def test_provider_rejects_model_match_collisions() -> None:
    models = [
        _model('first', match=ClauseEquals(equals='shared')),
        _model('second', match=ClauseEquals(equals='shared')),
    ]

    with pytest.raises(ValidationError, match=r"Model `first` matches other model ids: \['second'\]"):
        _provider(models)


def test_provider_requires_models_to_be_sorted_by_id() -> None:
    with pytest.raises(ValidationError, match='Models are not sorted by ID: move `zebra` 0 -> 1 after `ant`'):
        _provider([_model('zebra'), _model('ant')])


def test_model_price_and_model_info_validation_and_serialization() -> None:
    with pytest.raises(ValidationError, match='model prices may not be empty'):
        _model('empty', prices=[])

    with pytest.raises(ValidationError, match='exactly one price must not have a constraint'):
        _model(
            'all-constrained',
            prices=[
                ConditionalPrice(
                    constraint=StartDateConstraint(start_date=date(2026, 1, 1)),
                    prices=ModelPrice(input_mtok=Decimal(1)),
                ),
                ConditionalPrice(
                    constraint=StartDateConstraint(start_date=date(2026, 2, 1)),
                    prices=ModelPrice(input_mtok=Decimal(2)),
                ),
            ],
        )

    conditional_prices = [
        ConditionalPrice(prices=ModelPrice(input_mtok=Decimal(1))),
        ConditionalPrice(
            constraint=StartDateConstraint(start_date=date(2026, 1, 1)), prices=ModelPrice(input_mtok=Decimal('1.5'))
        ),
    ]
    conditional_model = _model('conditional', prices=conditional_prices)
    direct_model = _model('direct', prices=ModelPrice(input_mtok=Decimal(1), output_mtok=Decimal('1.5')))

    assert conditional_model.model_dump(mode='json', exclude_none=True)['prices'] == [
        {'prices': {'input_mtok': 1}},
        {'constraint': {'start_date': '2026-01-01'}, 'prices': {'input_mtok': 1.5}},
    ]
    assert direct_model.model_dump(mode='json', exclude_none=True)['prices'] == {'input_mtok': 1, 'output_mtok': 1.5}
    assert serialize_decimal(Decimal('2')) == 2
    assert serialize_decimal(Decimal('2.25')) == 2.25


def test_model_info_rejects_checked_price_discrepancy_and_identifies_free_prices() -> None:
    with pytest.raises(ValidationError, match='`price_discrepancies` should be removed when `prices_checked` is set'):
        ModelInfo(
            id='checked',
            match=ClauseEquals(equals='checked'),
            prices=ModelPrice(),
            price_discrepancies={'source': 'different'},
            prices_checked=date(2026, 1, 1),
        )

    checked_without_discrepancy = ModelInfo(
        id='checked-without-discrepancy',
        match=ClauseEquals(equals='checked-without-discrepancy'),
        prices=ModelPrice(),
        prices_checked=date(2026, 1, 1),
    )
    assert checked_without_discrepancy.prices_checked == date(2026, 1, 1)

    assert _model('free').is_free()
    assert not _model('paid', prices=ModelPrice(input_mtok=Decimal(1))).is_free()
    assert _model('conditional-free', prices=[ConditionalPrice(prices=ModelPrice())]).is_free()
    assert not _model('conditional-paid', prices=[ConditionalPrice(prices=ModelPrice(input_mtok=Decimal(1)))]).is_free()
    assert ModelPrice.model_construct(extra_price=None).is_free()
    assert not ModelPrice.model_validate({'extra_price': Decimal(1)}).is_free()


def test_tiered_and_time_constraints_validate() -> None:
    assert (
        TieredPrices(base=Decimal(1), tiers=[Tier(start=1, price=Decimal(2)), Tier(start=2, price=Decimal(3))])
        .tiers[0]
        .start
        == 1
    )
    with pytest.raises(ValidationError, match='Tiers must be in ascending order by start'):
        TieredPrices(base=Decimal(1), tiers=[Tier(start=2, price=Decimal(2)), Tier(start=1, price=Decimal(3))])

    constraint = TimeOfDateConstraint(start_time=time(9, tzinfo=timezone.utc), end_time=time(17, tzinfo=timezone.utc))
    assert constraint.start_time.tzinfo is timezone.utc
    with pytest.raises(ValidationError, match='Times must be timezone aware'):
        TimeOfDateConstraint(start_time=time(9), end_time=time(17))


def test_match_logic_clauses_discriminators_and_model_ids() -> None:
    starts_with = ClauseStartsWith(starts_with='model-')
    ends_with = ClauseEndsWith(ends_with='-latest')
    contains = ClauseContains(contains='pro')
    regex = ClauseRegex(regex=re.compile(r'^gpt-\d+$'))
    equals = ClauseEquals(equals='exact')
    or_clause = ClauseOr.model_validate({'or': [starts_with, equals]})
    and_clause = ClauseAnd.model_validate({'and': [contains, ends_with]})

    assert starts_with.is_match('MODEL-name')
    assert not starts_with.is_match('name')
    assert ends_with.is_match('model-LATEST')
    assert not ends_with.is_match('model')
    assert contains.is_match('Pro-model')
    assert not contains.is_match('model')
    assert regex.is_match('gpt-4')
    assert not regex.is_match('gpt-four')
    assert equals.is_match('EXACT')
    assert not equals.is_match('different')
    assert or_clause.is_match('model-name')
    assert not or_clause.is_match('different')
    assert and_clause.is_match('pro-latest')
    assert not and_clause.is_match('pro-old')

    assert clause_discriminator({'equals': 'model'}) == 'equals'
    assert clause_discriminator(equals) == 'equals'
    assert clause_discriminator(or_clause) == 'or'
    assert clause_discriminator('not-a-clause') is None
    assert match_logic_schema.validate_python({'contains': 'pro'}) == contains
    assert get_model_ids(equals) == ['exact']
    assert get_model_ids(starts_with) == ['model-']
    assert get_model_ids(ends_with) == ['-latest']
    assert get_model_ids(contains) == ['pro']
    assert get_model_ids(regex) == [r'^gpt-\d+$']
    assert get_model_ids(ClauseOr.model_validate({'or': [equals, starts_with]})) == ['exact', 'model-']
    assert get_model_ids(ClauseAnd.model_validate({'and': [contains, ends_with]})) == ['pro', '-latest']


def test_match_logic_rejects_duplicate_clauses() -> None:
    with pytest.raises(ValidationError, match='Duplicates found'):
        ClauseOr.model_validate({'or': [ClauseEquals(equals='same'), ClauseEquals(equals='same')]})
    with pytest.raises(ValidationError, match='Duplicates found'):
        ClauseAnd.model_validate({'and': [ClauseEquals(equals='same'), ClauseEquals(equals='same')]})


def test_extract_paths_validate_and_provider_schema_uses_aliases() -> None:
    array_match = ArrayMatch(type='array-match', field='choices', match=ClauseEquals(equals='choice'))
    assert doesnt_end_with_find_item('usage') == 'usage'
    assert doesnt_end_with_find_item(['choices', 'usage']) == ['choices', 'usage']
    with pytest.raises(ValueError, match='ExtractPath should not be empty'):
        doesnt_end_with_find_item([])
    with pytest.raises(ValueError, match='ExtractPath should not end with a `ArrayMatch` object'):
        doesnt_end_with_find_item(['choices', array_match])

    provider = providers_schema.validate_python(
        [
            {
                'id': 'provider',
                'name': 'Provider',
                'api_pattern': 'https://api.example.test/*',
                'models': [{'id': 'model', 'match': {'equals': 'model'}, 'prices': {}}],
            }
        ]
    )[0]
    assert providers_schema.dump_python([provider], by_alias=True)[0]['models'][0]['match'] == {'equals': 'model'}
