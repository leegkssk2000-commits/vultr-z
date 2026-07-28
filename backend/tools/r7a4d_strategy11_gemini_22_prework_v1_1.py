from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
V1_PATH = ROOT / "backend/tools/r7a4d_strategy11_gemini_22_prework_v1.py"


def load_v1() -> Any:
    name = "r7a4d_strategy11_gemini_22_prework_v1_for_normalization"
    spec = importlib.util.spec_from_file_location(name, V1_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("V1_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v1 = load_v1()


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return str(value)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(json_safe(payload), handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def normalized_priority(value: Any) -> int:
    try:
        result = int(float(value))
        return result if result > 0 else 999
    except (TypeError, ValueError):
        text = str(value or "").upper()
        if text in {"HIGH", "P1", "FIRST"}:
            return 1
        if text in {"MEDIUM", "P2", "SECOND"}:
            return 2
        if text in {"LOW", "P3", "THIRD"}:
            return 3
        return 999


def normalize_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            item = item.get("candidate_id", item.get("id", item.get("name")))
        item_s = str(item or "")
        if item_s in v1.CANDIDATE_LIBRARY and item_s not in output:
            output.append(item_s)
    return output[:2]


original_response = v1.v31.strict_object_response


def normalized_response(text: str) -> dict[str, Any]:
    payload = original_response(text)
    for key, id_key in (("strategies", "candidate_ids"), ("rows", "approved_candidate_ids")):
        rows = payload.get(key)
        if not isinstance(rows, list):
            payload[key] = []
            continue
        normalized: list[dict[str, Any]] = []
        for source in rows:
            if not isinstance(source, Mapping):
                continue
            row = dict(source)
            row["priority"] = normalized_priority(row.get("priority"))
            row[id_key] = normalize_ids(row.get(id_key))
            normalized.append(json_safe(row))
        payload[key] = normalized
    return json_safe(payload)


v1.atomic_json = atomic_json
v1.v31.strict_object_response = normalized_response
v1.v31.v3.sanitize = (lambda original: (lambda value, **kwargs: json_safe(original(value, **kwargs))))(v1.v31.v3.sanitize)


if __name__ == "__main__":
    raise SystemExit(v1.main())
