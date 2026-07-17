#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load("r73b4_v4", HERE / "q4r3_exact25_r73b4_readonly_display_parity_smoke_v4.py")
collector = base.collector


def fetch_view(urls: list[str]) -> tuple[str, str, list[str]]:
    url, text, errors = base.fetch_view(urls)
    if url:
        return url, text, errors
    for candidate in urls:
        if not candidate.startswith("https://alimi.vip"):
            continue
        command = [
            "curl", "-fsSL", "--max-time", "12",
            "--resolve", "alimi.vip:443:127.0.0.1", candidate,
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=15)
        label = candidate + "#local-tls-sni"
        if result.returncode == 0 and result.stdout:
            base.LAST_VIEW = (label, result.stdout[:collector.MAX_BYTES])
            base.DIAGNOSTICS["view_local_tls_sni"] = True
            return base.LAST_VIEW[0], base.LAST_VIEW[1], errors
        errors.append(f"{label}:curl={result.returncode}")
    base.DIAGNOSTICS["view_local_tls_sni"] = False
    return "", "", errors


def output_path() -> Path | None:
    try:
        return Path(sys.argv[sys.argv.index("--output") + 1])
    except (ValueError, IndexError):
        return None


collector.fetch_view = fetch_view


if __name__ == "__main__":
    result = int(collector.main())
    path = output_path()
    if path and path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["binding_discovery"] = base.DIAGNOSTICS
        payload["telegram_unit_context"] = {
            key: str(value) for key, value in base.CONTEXTS.get(base.TELEGRAM_UNIT, {}).get("info", {}).items()
        }
        payload["view_unit_context"] = {
            key: str(value) for key, value in base.CONTEXTS.get(base.CONTROL_UNIT, {}).get("info", {}).items()
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    raise SystemExit(result)
