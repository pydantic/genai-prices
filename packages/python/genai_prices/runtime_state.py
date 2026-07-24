from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import cache

from .data_snapshot import DataSnapshot
from .units import UnitRegistry


@dataclass(frozen=True)
class RuntimeData:
    registry: UnitRegistry
    snapshot: DataSnapshot


_lock = threading.RLock()
_runtime_data: RuntimeData | None = None
_generation = 0


@cache
def _bundled_runtime_data() -> RuntimeData:
    from .data import providers
    from .data_units import unit_data

    return RuntimeData(
        registry=UnitRegistry(unit_data),
        snapshot=DataSnapshot(providers=providers, from_auto_update=False),
    )


def get_runtime_data() -> RuntimeData:
    global _runtime_data

    if _runtime_data is not None:
        return _runtime_data

    with _lock:
        if _runtime_data is None:
            _runtime_data = _bundled_runtime_data()
        return _runtime_data


def begin_update() -> int:
    global _generation

    with _lock:
        _generation += 1
        return _generation


def activate_runtime_data(generation: int, candidate: RuntimeData) -> bool:
    global _runtime_data

    with _lock:
        if generation != _generation:
            return False
        _runtime_data = candidate
        return True


def replace_snapshot(snapshot: DataSnapshot | None) -> RuntimeData:
    global _generation, _runtime_data

    with _lock:
        _generation += 1
        current = get_runtime_data()
        _runtime_data = RuntimeData(
            registry=current.registry,
            snapshot=snapshot if snapshot is not None else _bundled_runtime_data().snapshot,
        )
        return _runtime_data


def restore_bundled_providers(generation: int) -> bool:
    global _runtime_data

    with _lock:
        if generation != _generation:
            return False
        current = get_runtime_data()
        _runtime_data = RuntimeData(registry=current.registry, snapshot=_bundled_runtime_data().snapshot)
        return True
