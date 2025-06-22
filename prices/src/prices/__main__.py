import sys
from inspect import getdoc

from .build import build_prices
from .simplify import simplify
from .update_openrouter import update_from_openrouter


def main():
    actions = build_prices, update_from_openrouter, simplify
    if len(sys.argv) == 2:
        command = sys.argv[1]
        action = next((f for f in actions if f.__name__ == command), None)
        if action:
            action()
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
