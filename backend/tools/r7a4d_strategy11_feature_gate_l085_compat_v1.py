from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "backend/tools/r7a4d_strategy11_feature_gate_l085_common_v1.py"
name = "r7a4d_strategy11_feature_gate_l085_common_compat"
spec = importlib.util.spec_from_file_location(name, COMMON)
if spec is None or spec.loader is None:
    raise RuntimeError("COMMON_SPEC_FAILED")
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
original = module.strict_json


def no_change_baseline(path: Path) -> Any:
    value = original(path)
    if isinstance(value, dict) and path.name == "summary.json" and "candidate" in value:
        value = dict(value)
        value["surgery"] = None
    return value


module.strict_json = no_change_baseline
raise SystemExit(module.main())
