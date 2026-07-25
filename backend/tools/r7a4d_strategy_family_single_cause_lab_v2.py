from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from backend.strategy25.strategy_family_indicator_search_v2 import variants_for, wrap_strategy


ROOT = Path(__file__).resolve().parents[2]
PARENT_PATH = ROOT / "backend/tools/r7a4d_strategy_family_single_cause_lab.py"


def _load_parent() -> Any:
    name = "r7a4d_strategy_family_single_cause_parent_v2"
    spec = importlib.util.spec_from_file_location(name, PARENT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("PARENT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parent = _load_parent()
    parent.variants_for = variants_for
    parent.wrap_strategy = wrap_strategy
    return int(parent.main())


if __name__ == "__main__":
    raise SystemExit(main())
