from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from backend.strategy25.indicator_contract_repair_adapter_v1 import REPAIR_SPECS, transformed_source


class RepairedStrategyLoadError(RuntimeError):
    pass


def load_repaired_namespace(root: str | Path, strategy_id: str) -> dict[str, Any]:
    source = transformed_source(root, strategy_id)
    module_name = f"backend.strategy25.repaired_{strategy_id}_v1"
    source_path = str(Path(root).resolve() / REPAIR_SPECS[strategy_id].implementation_path)

    module = ModuleType(module_name)
    module.__file__ = source_path
    module.__package__ = "backend.strategies"
    namespace = module.__dict__

    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        exec(compile(source, source_path, "exec"), namespace, namespace)
    except Exception:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise

    return namespace


def load_repaired_strategy(root: str | Path, strategy_id: str) -> Callable[..., Any]:
    namespace = load_repaired_namespace(root, strategy_id)
    strategy = namespace.get("strategy")
    if not callable(strategy):
        raise RepairedStrategyLoadError(f"STRATEGY_CALLABLE_MISSING:{strategy_id}")
    return strategy
