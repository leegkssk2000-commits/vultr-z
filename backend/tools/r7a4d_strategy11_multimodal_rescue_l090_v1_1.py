from __future__ import annotations

import hashlib
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
ORIGINAL_PATH = ROOT / "backend/tools/r7a4d_strategy11_multimodal_rescue_l090_v1.py"


def load_original() -> Any:
    original_factory = importlib.util.module_from_spec

    def registered(spec):
        module = original_factory(spec)
        sys.modules[spec.name] = module
        return module

    importlib.util.module_from_spec = registered
    try:
        name = "r7a4d_strategy11_multimodal_rescue_l090_v1_normalized"
        spec = importlib.util.spec_from_file_location(name, ORIGINAL_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("MULTIMODAL_ORIGINAL_SPEC_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        importlib.util.module_from_spec = original_factory


original = load_original()


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
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(json_safe(payload), handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def stable_sha(value: Any) -> str:
    raw = json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


original.atomic_json = atomic_json
original.stable_sha = stable_sha
previous_sanitize = original.v3.sanitize
original.v3.sanitize = lambda value, **kwargs: json_safe(previous_sanitize(value, **kwargs))


if __name__ == "__main__":
    raise SystemExit(original.main())
