from pydantic import TypeAdapter

from .prices_types import ModelPrice
from .source_guard import check_non_empty
from .utils import package_dir

ProvidePrices = dict[str, ModelPrice]
SourcePricesType = dict[str, ProvidePrices]
source_prices_schema = TypeAdapter(SourcePricesType)
source_prices_dir = package_dir / 'source_prices'


def write_source_prices(source: str, source_prices: SourcePricesType) -> None:
    # Chokepoint for every importer that writes a JSON source file, so one check covers them all.
    check_non_empty(source, sum(len(models) for models in source_prices.values()))
    source_prices_dir.mkdir(exist_ok=True)
    source_prices_file = source_prices_dir / f'{source}.json'
    source_prices_file.write_bytes(source_prices_schema.dump_json(source_prices, indent=2, exclude_none=True))
    print(f'prices written to {source_prices_file}')


def load_source_prices() -> dict[str, SourcePricesType]:
    prices: dict[str, SourcePricesType] = {}
    for path in source_prices_dir.iterdir():
        try:
            prices[path.stem] = source_prices_schema.validate_json(path.read_bytes())
        except ValueError as e:
            raise ValueError(f'Error loading source prices from {path}: {e}')
    return prices
