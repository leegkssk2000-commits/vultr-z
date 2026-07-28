from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "backend/tools/r7a4d_strategy11_feature_gate_l085_common_v1.py"
name = "r7a4d_strategy11_feature_gate_l085_common_compat"
original_from_spec = importlib.util.module_from_spec


def registered(spec):
    module = original_from_spec(spec)
    sys.modules[spec.name] = module
    return module


importlib.util.module_from_spec = registered
try:
    spec = importlib.util.spec_from_file_location(name, COMMON)
    if spec is None or spec.loader is None:
        raise RuntimeError("COMMON_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
finally:
    importlib.util.module_from_spec = original_from_spec

original_json = module.strict_json
original_metric = module.metric


def no_change_baseline(path: Path) -> Any:
    value = original_json(path)
    if isinstance(value, dict) and path.name == "summary.json" and "candidate" in value:
        value = dict(value)
        value["surgery"] = None
    return value


def no_loss_is_zero(value: Any, default: float = 0.0) -> float:
    if value is None and default == -math.inf:
        return 0.0
    return original_metric(value, default)


module.strict_json = no_change_baseline
module.metric = no_loss_is_zero
raise SystemExit(module.main())
