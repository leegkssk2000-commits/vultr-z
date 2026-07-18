#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v6 = load("r73b4_v6", HERE / "q4r3_exact25_r73b4_readonly_display_parity_smoke_v6.py")
collector = v6.collector


def output_path() -> Path | None:
    try:
        return Path(sys.argv[sys.argv.index("--output") + 1])
    except (ValueError, IndexError):
        return None


if __name__ == "__main__":
    result = int(collector.main())
    path = output_path()
    if path and path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        diagnostics = {}
        diagnostics.update(v6.base.DIAGNOSTICS)
        diagnostics.update(v6.DIAGNOSTICS)
        payload["binding_discovery"] = diagnostics
        payload["telegram_unit_context"] = {
            key: str(value)
            for key, value in v6.base.CONTEXTS.get(v6.base.TELEGRAM_UNIT, {}).get("info", {}).items()
        }
        payload["view_unit_context"] = {
            key: str(value)
            for key, value in v6.base.CONTEXTS.get(v6.base.CONTROL_UNIT, {}).get("info", {}).items()
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    raise SystemExit(result)
