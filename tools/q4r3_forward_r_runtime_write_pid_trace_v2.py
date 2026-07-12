from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional

EXPECTED_FREEZE_STATE = "FROZEN_OBSERVER_RESERVE"
BASE_PATH = Path(__file__).with_name("q4r3_forward_r_runtime_write_pid_trace.py")


def _load_base():
    spec = importlib.util.spec_from_file_location("q4r3_forward_r_runtime_write_pid_trace_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"BASE_TRACE_MODULE_LOAD_FAILED:{BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_base()
_ORIGINAL_LOAD_JSON = BASE.load_json


def freeze_state(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    full = payload.get("full") if isinstance(payload.get("full"), dict) else {}
    values = [
        payload.get("raschke_state"),
        payload.get("state"),
        full.get("state"),
    ]
    normalized = {str(value).strip() for value in values if value not in (None, "")}
    if len(normalized) != 1:
        return None
    return next(iter(normalized))


def normalize_freeze_manifest(payload: Any) -> Any:
    state = freeze_state(payload)
    if state != EXPECTED_FREEZE_STATE or not isinstance(payload, dict):
        return payload
    normalized: Dict[str, Any] = dict(payload)
    normalized["raschke_state"] = EXPECTED_FREEZE_STATE
    return normalized


def load_json_compat(path: Path) -> Any:
    payload = _ORIGINAL_LOAD_JSON(path)
    if Path(path) == BASE.FREEZE_IN:
        return normalize_freeze_manifest(payload)
    return payload


def main() -> None:
    BASE.load_json = load_json_compat
    BASE.main()


if __name__ == "__main__":
    main()
