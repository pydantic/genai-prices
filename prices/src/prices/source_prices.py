from pydantic import TypeAdapter

from .types import ModelPrice
from .utils import package_dir

ProvidePrices = dict[str, ModelPrice]
SourcePricesType = dict[str, ProvidePrices]
source_prices_schema = TypeAdapter(SourcePricesType)


def write_source_prices(source: str, source_prices: SourcePricesType) -> None:
    source_prices_dir = package_dir / 'source_prices'
    source_prices_dir.mkdir(exist_ok=True)
    source_prices_file = source_prices_dir / f'{source}.json'
    source_prices_file.write_bytes(source_prices_schema.dump_json(source_prices, indent=2, exclude_none=True))
