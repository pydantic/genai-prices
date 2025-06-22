import sys

from .build import build_prices


def main():
    if len(sys.argv) < 2:
        print('Usage: uv run -m src [build-prices]')

    command = sys.argv[1]
    if command == 'build-prices':
        build_prices()
    else:
        print('Invalid command')
        print('Usage: uv run -m src [build-prices]')
        sys.exit(1)


if __name__ == '__main__':
    main()
