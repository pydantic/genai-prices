from pydantic_core import from_json

from genai_prices.types import _providers_from_raw
from prices.utils import package_dir as prices_package_dir


def test_legacy_provider_payload_remains_runtime_compatible() -> None:
    raw_providers = from_json((prices_package_dir / 'data.json').read_bytes())
    providers = _providers_from_raw(raw_providers)

    assert providers
    assert all(provider.id for provider in providers)
