"""Token unit registry — defines unit families, dimensions, and unit definitions."""

from __future__ import annotations as _annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnitDef:
    """Definition of a single pricing unit."""

    id: str
    family_id: str
    usage_key: str
    dimensions: dict[str, str]


@dataclass(frozen=True)
class UnitFamily:
    """A family of pricing units that share a normalization factor."""

    id: str
    per: int
    description: str
    dimensions: dict[str, list[str]]
    units: dict[str, UnitDef]


def _tok(unit_id: str, usage_key: str, dimensions: dict[str, str]) -> UnitDef:
    return UnitDef(id=unit_id, family_id='tokens', usage_key=usage_key, dimensions=dimensions)


TOKENS_FAMILY = UnitFamily(
    id='tokens',
    per=1_000_000,
    description='Token counts',
    dimensions={
        'direction': ['input', 'output'],
        'modality': ['text', 'audio', 'image', 'video'],
        'cache': ['read', 'write'],
    },
    units={
        # Catch-all input/output (no modality, no cache)
        'input_mtok': _tok('input_mtok', 'input_tokens', {'direction': 'input'}),
        'output_mtok': _tok('output_mtok', 'output_tokens', {'direction': 'output'}),
        # Cache (no modality)
        'cache_read_mtok': _tok('cache_read_mtok', 'cache_read_tokens', {'direction': 'input', 'cache': 'read'}),
        'cache_write_mtok': _tok('cache_write_mtok', 'cache_write_tokens', {'direction': 'input', 'cache': 'write'}),
        # Text modality
        'input_text_mtok': _tok('input_text_mtok', 'input_text_tokens', {'direction': 'input', 'modality': 'text'}),
        'output_text_mtok': _tok('output_text_mtok', 'output_text_tokens', {'direction': 'output', 'modality': 'text'}),
        'cache_read_text_mtok': _tok(
            'cache_read_text_mtok',
            'cache_read_text_tokens',
            {'direction': 'input', 'modality': 'text', 'cache': 'read'},
        ),
        'cache_write_text_mtok': _tok(
            'cache_write_text_mtok',
            'cache_write_text_tokens',
            {'direction': 'input', 'modality': 'text', 'cache': 'write'},
        ),
        # Audio modality
        'input_audio_mtok': _tok('input_audio_mtok', 'input_audio_tokens', {'direction': 'input', 'modality': 'audio'}),
        'output_audio_mtok': _tok(
            'output_audio_mtok', 'output_audio_tokens', {'direction': 'output', 'modality': 'audio'}
        ),
        # NOTE: usage_key uses current field name 'cache_audio_read_tokens', not spec's 'cache_read_audio_tokens'
        'cache_read_audio_mtok': _tok(
            'cache_read_audio_mtok',
            'cache_audio_read_tokens',
            {'direction': 'input', 'modality': 'audio', 'cache': 'read'},
        ),
        'cache_write_audio_mtok': _tok(
            'cache_write_audio_mtok',
            'cache_write_audio_tokens',
            {'direction': 'input', 'modality': 'audio', 'cache': 'write'},
        ),
        # Image modality
        'input_image_mtok': _tok('input_image_mtok', 'input_image_tokens', {'direction': 'input', 'modality': 'image'}),
        'output_image_mtok': _tok(
            'output_image_mtok', 'output_image_tokens', {'direction': 'output', 'modality': 'image'}
        ),
        'cache_read_image_mtok': _tok(
            'cache_read_image_mtok',
            'cache_read_image_tokens',
            {'direction': 'input', 'modality': 'image', 'cache': 'read'},
        ),
        'cache_write_image_mtok': _tok(
            'cache_write_image_mtok',
            'cache_write_image_tokens',
            {'direction': 'input', 'modality': 'image', 'cache': 'write'},
        ),
        # Video modality
        'input_video_mtok': _tok('input_video_mtok', 'input_video_tokens', {'direction': 'input', 'modality': 'video'}),
        'output_video_mtok': _tok(
            'output_video_mtok', 'output_video_tokens', {'direction': 'output', 'modality': 'video'}
        ),
        'cache_read_video_mtok': _tok(
            'cache_read_video_mtok',
            'cache_read_video_tokens',
            {'direction': 'input', 'modality': 'video', 'cache': 'read'},
        ),
        'cache_write_video_mtok': _tok(
            'cache_write_video_mtok',
            'cache_write_video_tokens',
            {'direction': 'input', 'modality': 'video', 'cache': 'write'},
        ),
    },
)

# Mapping from current ModelPrice field names to registry unit IDs.
# Only needed during Phase 1 while ModelPrice uses fixed fields.
FIELD_TO_UNIT: dict[str, str] = {
    'input_mtok': 'input_mtok',
    'output_mtok': 'output_mtok',
    'cache_read_mtok': 'cache_read_mtok',
    'cache_write_mtok': 'cache_write_mtok',
    'input_audio_mtok': 'input_audio_mtok',
    'cache_audio_read_mtok': 'cache_read_audio_mtok',  # field name differs from unit ID
    'output_audio_mtok': 'output_audio_mtok',
}

_FAMILIES: dict[str, UnitFamily] = {'tokens': TOKENS_FAMILY}
_ALL_UNITS: dict[str, UnitDef] = {uid: unit for fam in _FAMILIES.values() for uid, unit in fam.units.items()}


def get_family(family_id: str) -> UnitFamily:
    """Look up a unit family by ID. Raises KeyError if not found."""
    return _FAMILIES[family_id]


def get_unit(unit_id: str) -> UnitDef:
    """Look up a unit definition by ID. Raises KeyError if not found."""
    return _ALL_UNITS[unit_id]
