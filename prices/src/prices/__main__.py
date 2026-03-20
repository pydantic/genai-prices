import sys
from inspect import getdoc

from .build import build
from .collapse import collapse
from .detect_deprecated import detect_deprecated
from .inject_providers import inject_providers
from .package_data import package_data
from .price_discrepancies import check_for_price_discrepancies, update_price_discrepancies
from .source_huggingface import get_huggingface_prices
from .source_litellm import get_litellm_prices
from .source_openrouter import get_openrouter_prices, update_from_openrouter
from .source_ovhcloud import get_ovhcloud_prices
from .source_simonw_prices import get_simonw_prices


def main():
    actions = (
        build,
        update_from_openrouter,
        collapse,
        detect_deprecated,
        get_huggingface_prices,
        get_litellm_prices,
        get_openrouter_prices,
        get_ovhcloud_prices,
        get_simonw_prices,
        update_price_discrepancies,
        check_for_price_discrepancies,
        package_data,
        inject_providers,
    )
    if len(sys.argv) == 2:
        command = sys.argv[1]
        action = next((f for f in actions if f.__name__ == command), None)
        if action:
            return_value = action()
            if isinstance(return_value, int):
                sys.exit(return_value)
            return
        else:
            print('Invalid command')

    print('Usage: uv run -m src [action]')
    print('actions:')
    for f in actions:
        doc = (getdoc(f) or '').split('\n', 1)[0]
        print(f'  {f.__name__}: {doc}')
    sys.exit(1)


if __name__ == '__main__':
    main()
