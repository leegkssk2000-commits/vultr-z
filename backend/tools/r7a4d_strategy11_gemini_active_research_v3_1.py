from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
V3_PATH = ROOT / "backend/tools/r7a4d_strategy11_gemini_active_research_v3.py"


def load_v3() -> Any:
    name = "r7a4d_strategy11_gemini_active_research_v3_for_shape_fix"
    spec = importlib.util.spec_from_file_location(name, V3_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("V3_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v3 = load_v3()


def strict_object_response(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "HOLD", "blockers": ["GEMINI_NON_JSON"], "raw_response": text[:30000]}
    if isinstance(payload, Mapping):
        return dict(payload)
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], Mapping):
        row = dict(payload[0])
        row.setdefault("response_shape_repair", "UNWRAPPED_SINGLE_OBJECT_ARRAY")
        return row
    return {
        "status": "HOLD",
        "blockers": ["NON_OBJECT_JSON"],
        "observed_top_level_type": type(payload).__name__,
        "observed_list_length": len(payload) if isinstance(payload, list) else None,
    }


v3.json_response = strict_object_response


if __name__ == "__main__":
    raise SystemExit(v3.main())
