import sys

from .build import build_prices
from .update_openrouter import update_from_openrouter


def main():
    if len(sys.argv) < 2:
        print('Usage: uv run -m src [build-prices|update-openrouter]')
        sys.exit(1)

    command = sys.argv[1]
    if command == 'build-prices':
        build_prices()
    elif command == 'update-openrouter':
        update_from_openrouter()
    else:
        print('Invalid command')
        print('Usage: uv run -m src [build-prices]')
        sys.exit(1)


if __name__ == '__main__':
    main()
