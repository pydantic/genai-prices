from collections.abc import Sequence
from typing import NamedTuple

from genai_prices.data import providers
from genai_prices.types import ArrayMatch, ClauseEquals, UsageExtractorMapping

GoogleExtractorMappingSignature = tuple[tuple[str, ...], str, bool]


class GoogleUsageMetadataSource(NamedTuple):
    count_stem: str
    count_destinations: tuple[str, ...]
    detail_direction: str | None = None
    detail_stem: str | None = None

    @property
    def count_path(self) -> str:
        return f'{self.count_stem}TokenCount'

    @property
    def detail_path(self) -> str | None:
        if self.detail_direction is None:
            return None
        detail_stem = self.detail_stem or self.count_stem
        return f'{detail_stem}TokensDetails'


def test_google_default_extractor_mappings_are_complete():
    google_provider = next(provider for provider in providers if provider.id == 'google')
    assert google_provider.name == 'Google'
    assert google_provider.extractors is not None
    google_extractor = next(extractor for extractor in google_provider.extractors if extractor.api_flavor == 'default')

    actual = {_google_extractor_mapping_signature(mapping) for mapping in google_extractor.mappings}

    assert actual == _google_default_extractor_expected_signatures()


def _google_default_extractor_expected_signatures() -> set[GoogleExtractorMappingSignature]:
    # Google names aggregate counts as <stem>TokenCount and modality arrays as <stem>TokensDetails.
    # Cache is the naming exception: cachedContentTokenCount has cacheTokensDetails.
    sources = (
        GoogleUsageMetadataSource('prompt', ('input_tokens',), 'input'),
        GoogleUsageMetadataSource('cachedContent', ('cache_read_tokens',), 'cache_read', detail_stem='cache'),
        GoogleUsageMetadataSource('candidates', ('output_tokens',), 'output'),
        # Thinking tokens have no detail array, but Google prices them as text output.
        GoogleUsageMetadataSource(
            'thoughts',
            ('output_tokens', 'output_text_tokens', 'output_reasoning_tokens', 'output_text_reasoning_tokens'),
        ),
        # Tool-use prompt tokens are additional prompt/input context, including their modality breakdown.
        GoogleUsageMetadataSource('toolUsePrompt', ('input_tokens',), 'input'),
    )

    signatures: set[GoogleExtractorMappingSignature] = set()
    for source in sources:
        signatures.update(_google_count_signatures(source))
        signatures.update(_google_detail_signatures(source))
    return signatures


def _google_count_signatures(source: GoogleUsageMetadataSource) -> set[GoogleExtractorMappingSignature]:
    return {
        _google_optional_extractor_mapping(source.count_path, destination) for destination in source.count_destinations
    }


def _google_detail_signatures(source: GoogleUsageMetadataSource) -> set[GoogleExtractorMappingSignature]:
    if source.detail_path is None:
        return set()

    assert source.detail_direction is not None
    modalities = ('TEXT', 'AUDIO', 'IMAGE', 'DOCUMENT', 'VIDEO')
    return {
        _google_optional_extractor_mapping(
            (source.detail_path, modality, 'tokenCount'),
            _google_modality_detail_dest(source.detail_direction, modality),
        )
        for modality in modalities
    }


def _google_optional_extractor_mapping(path: str | tuple[str, ...], dest: str) -> GoogleExtractorMappingSignature:
    path_tuple = (path,) if isinstance(path, str) else path
    return path_tuple, dest, False


def _google_extractor_mapping_signature(mapping: UsageExtractorMapping) -> GoogleExtractorMappingSignature:
    return _google_extractor_path_signature(mapping.path), mapping.dest, mapping.required


def _google_extractor_path_signature(path: str | Sequence[str | ArrayMatch]) -> tuple[str, ...]:
    if isinstance(path, str):
        return (path,)
    assert len(path) == 3
    array_name, array_match, leaf = path
    assert isinstance(array_name, str)
    assert isinstance(array_match, ArrayMatch)
    assert isinstance(array_match.match, ClauseEquals)
    assert isinstance(leaf, str)
    return array_name, array_match.match.equals, leaf


def _google_modality_detail_dest(direction: str, modality: str) -> str:
    # Google can report DOCUMENT in ModalityTokenCount, but PDF/page tokens are image-priced.
    usage_modality = 'image' if modality == 'DOCUMENT' else modality.lower()
    if direction == 'cache_read':
        return f'cache_{usage_modality}_read_tokens'
    return f'{direction}_{usage_modality}_tokens'
