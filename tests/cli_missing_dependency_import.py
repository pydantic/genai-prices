from __future__ import annotations

import importlib
import importlib.abc
import sys
from collections.abc import Sequence
from importlib.machinery import ModuleSpec
from types import ModuleType


class BlockRich(importlib.abc.MetaPathFinder):
    def find_spec(
        self, fullname: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        if fullname == 'rich':
            raise ModuleNotFoundError("No module named 'rich'", name='rich')
        return None


def main() -> None:
    sys.path.insert(0, sys.argv[1])
    sys.meta_path.insert(0, BlockRich())
    importlib.import_module('genai_prices._cli')


if __name__ == '__main__':
    main()
