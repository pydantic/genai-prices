from __future__ import annotations

import re
from typing import Annotated, Literal, TypeAlias, TypedDict, cast

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class _RawClauseStartsWith(_StrictModel):
    starts_with: StrictStr


class _RawClauseEndsWith(_StrictModel):
    ends_with: StrictStr


class _RawClauseContains(_StrictModel):
    contains: StrictStr


class _RawClauseRegex(_StrictModel):
    regex: StrictStr

    @field_validator('regex')
    @classmethod
    def valid_regex(cls, value: str) -> str:
        re.compile(value)
        return value


class _RawClauseEquals(_StrictModel):
    equals: StrictStr


class _RawClauseOr(_StrictModel):
    or_: list[_RawMatchLogic] = Field(alias='or')


class _RawClauseAnd(_StrictModel):
    and_: list[_RawMatchLogic] = Field(alias='and')


_RawMatchLogic: TypeAlias = (
    _RawClauseStartsWith
    | _RawClauseEndsWith
    | _RawClauseContains
    | _RawClauseRegex
    | _RawClauseEquals
    | _RawClauseOr
    | _RawClauseAnd
)


class _RawArrayMatch(_StrictModel):
    type: Literal['array-match']
    field: StrictStr
    match: _RawMatchLogic


_RawExtractPath: TypeAlias = StrictStr | list[StrictStr | _RawArrayMatch]


class _RawUsageExtractorMapping(_StrictModel):
    path: _RawExtractPath
    dest: StrictStr
    required: StrictBool = True


class _RawUsageExtractor(_StrictModel):
    root: _RawExtractPath
    mappings: list[_RawUsageExtractorMapping]
    api_flavor: StrictStr = 'default'
    model_path: _RawExtractPath = 'model'


class _RawTier(_StrictModel):
    start: StrictInt
    price: StrictInt | StrictFloat


class _RawTieredPrices(_StrictModel):
    base: StrictInt | StrictFloat
    tiers: list[_RawTier]


_RawPriceValue: TypeAlias = StrictInt | StrictFloat | _RawTieredPrices


class _RawModelPrice(RootModel[dict[StrictStr, _RawPriceValue]]):
    model_config = ConfigDict(strict=True)


class _RawStartDateConstraint(_StrictModel):
    start_date: Annotated[StrictStr, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]


class _RawTimeOfDateConstraint(_StrictModel):
    start_time: StrictStr
    end_time: StrictStr


class _RawConditionalPrice(_StrictModel):
    prices: _RawModelPrice
    constraint: _RawStartDateConstraint | _RawTimeOfDateConstraint | None = None


_Id = Annotated[StrictStr, Field(max_length=100, pattern=r'^\S+$')]
_Name = Annotated[StrictStr, Field(max_length=100)]
_Description = Annotated[StrictStr, Field(max_length=1000)]


class _RawModelInfo(_StrictModel):
    id: _Id
    match: _RawMatchLogic
    prices: _RawModelPrice | list[_RawConditionalPrice]
    name: _Name | None = None
    description: _Description | None = None
    context_window: StrictInt | None = None
    price_comments: _Description | None = None
    deprecated: StrictBool | None = None


class _RawProvider(_StrictModel):
    id: _Id
    name: _Name
    api_pattern: StrictStr
    models: list[_RawModelInfo]
    pricing_urls: list[AnyUrl] | None = None
    description: _Description | None = None
    price_comments: _Description | None = None
    model_match: _RawMatchLogic | None = None
    provider_match: _RawMatchLogic | None = None
    extractors: list[_RawUsageExtractor] | None = None
    fallback_model_providers: list[StrictStr] | None = None


class _RawUnitDefinition(_StrictModel):
    per: Annotated[StrictInt, Field(gt=0)]
    dimensions: dict[StrictStr, StrictStr]
    price_key: StrictStr | None = None


class _RawWrappedV2(_StrictModel):
    units: dict[StrictStr, _RawUnitDefinition]
    providers: list[_RawProvider]


class RawV2Payload(TypedDict):
    units: dict[str, dict[str, object]]
    providers: list[dict[str, object]]


def decode_v2_payload(raw: object) -> RawV2Payload:
    """Strictly decode the complete wrapped v2 wire payload."""
    decoded = _RawWrappedV2.model_validate(raw)
    payload = decoded.model_dump(mode='json', by_alias=True, exclude_none=True, exclude_unset=True)
    return cast(RawV2Payload, payload)
