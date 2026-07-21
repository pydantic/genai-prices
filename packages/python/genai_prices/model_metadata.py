from __future__ import annotations as _annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Literal

from pydantic import PositiveInt, TypeAdapter
from typing_extensions import TypedDict

__all__ = 'ModelMetadata', 'get_model_metadata'


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Provider-independent token limits for a model."""

    context_window: int | None = None
    """Maximum number of tokens in the model's context window."""
    max_input_tokens: int | None = None
    """Maximum number of input tokens."""
    max_output_tokens: int | None = None
    """Maximum number of output tokens."""


_LimitsData = tuple[PositiveInt | None, PositiveInt | None, PositiveInt | None]


class _ModelMetadataData(TypedDict):
    version: Literal[1]
    source: str
    source_sha256: str
    models: dict[str, _LimitsData]


def get_model_metadata(model_ref: str) -> ModelMetadata | None:
    """Get provider-independent token limits for a canonical model.

    Args:
        model_ref: A canonical models.dev model identifier.

    Returns:
        Model token limits, or `None` when metadata is unavailable for the model.
    """
    model_ref = model_ref.strip().lower()
    if not model_ref:
        return None
    return _get_bundled_model_metadata().get(model_ref)


@cache
def _get_bundled_model_metadata() -> dict[str, ModelMetadata]:
    data = files(__package__).joinpath('_model_metadata.json').read_bytes()
    parsed = TypeAdapter(_ModelMetadataData).validate_json(data)
    return {
        model_id: ModelMetadata(
            context_window=limits[0],
            max_input_tokens=limits[1],
            max_output_tokens=limits[2],
        )
        for model_id, limits in parsed['models'].items()
    }
