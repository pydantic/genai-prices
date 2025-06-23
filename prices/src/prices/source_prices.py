from pydantic import TypeAdapter

from .types import ModelPrice
from .utils import package_dir

ProvidePrices = dict[str, ModelPrice]
SourcePricesType = dict[str, ProvidePrices]
source_prices_schema = TypeAdapter(SourcePricesType)
source_prices_dir = package_dir / 'source_prices'


def write_source_prices(source: str, source_prices: SourcePricesType) -> None:
    source_prices_dir.mkdir(exist_ok=True)
    source_prices_file = source_prices_dir / f'{source}.json'
    source_prices_file.write_bytes(source_prices_schema.dump_json(source_prices, indent=2, exclude_none=True))


def load_source_prices() -> dict[str, SourcePricesType]:
    prices: dict[str, SourcePricesType] = {}
    for path in source_prices_dir.iterdir():
        try:
            prices[path.stem] = source_prices_schema.validate_json(path.read_bytes())
        except ValueError as e:
            raise ValueError(f'Error loading source prices from {path}: {e}')
    return prices
