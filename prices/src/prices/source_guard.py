"""Refuse to persist implausible imports.

Every price importer reads a third-party API and writes the result somewhere. Two of them
(`source_huggingface`, `source_ovhcloud`) overwrite *tracked* provider YAML, which is what the
published pricing artifacts are built from, and the only gate on that is a human reading the diff.
That gate degrades exactly when it matters most - a large regenerated diff where one bad entry hides
among hundreds of legitimate ones.

These guards move the failure earlier: refuse to write at all when the response does not look like a
real one, rather than writing it and hoping the diff gets read. They are not a defence against a
carefully-crafted malicious response - nothing here is - but they turn the two loudest upstream
failure modes (an empty response, and a response that lost most of its models) into hard errors.

Set `GENAI_PRICES_ALLOW_IMPLAUSIBLE_IMPORT=1` to override when a drop is genuinely expected, e.g. a
provider really did retire most of its catalogue.
"""

from __future__ import annotations

import os

OVERRIDE_ENV_VAR = 'GENAI_PRICES_ALLOW_IMPLAUSIBLE_IMPORT'
"""Set to `1` to downgrade these errors to warnings."""

MIN_RETAINED_FRACTION = 0.5
"""Refuse a rewrite that keeps less than this fraction of the models already recorded."""


class ImplausibleImportError(RuntimeError):
    """An upstream response was too degraded to persist."""


def _override_enabled() -> bool:
    return os.environ.get(OVERRIDE_ENV_VAR) == '1'


def _fail(message: str) -> None:
    if _override_enabled():
        print(f'WARNING: {message} (allowed by {OVERRIDE_ENV_VAR})')
        return
    raise ImplausibleImportError(f'{message}\nSet {OVERRIDE_ENV_VAR}=1 if this is genuinely expected.')


def check_non_empty(source: str, model_count: int) -> None:
    """Reject an import that produced no models at all.

    This is the failure mode that went unnoticed for months: an upstream changed shape, the parser
    quietly dropped every entry, and the importer wrote an empty file and exited 0.
    """
    if model_count == 0:
        _fail(f'{source}: upstream returned no usable models, refusing to write')


def check_no_sharp_drop(source: str, provider_id: str, new_count: int, existing_count: int) -> None:
    """Reject a rewrite that would delete most of a provider's recorded models."""
    check_non_empty(f'{source} ({provider_id})', new_count)
    if existing_count and new_count < existing_count * MIN_RETAINED_FRACTION:
        _fail(
            f'{source} ({provider_id}): upstream returned {new_count} models but '
            f'{existing_count} are already recorded, refusing to overwrite'
        )
