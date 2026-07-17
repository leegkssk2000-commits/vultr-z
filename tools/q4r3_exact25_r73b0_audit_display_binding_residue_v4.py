#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def normalize_r73a(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    report = payload.get("report")
    if "runtime_active" not in normalized and isinstance(report, dict):
        normalized["runtime_active"] = report.get("runtime_active")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--r73a", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(args.r73a.read_text(encoding="utf-8"))
    normalized = normalize_r73a(payload)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(normalized, handle, sort_keys=True)
        normalized_path = Path(handle.name)
    try:
        auditor = Path(__file__).with_name("q4r3_exact25_r73b0_audit_display_binding_residue_v3.py")
        result = subprocess.run([
            sys.executable, str(auditor), "--root", str(args.root),
            "--r73a", str(normalized_path), "--output", str(args.output),
        ], check=False)
        return result.returncode
    finally:
        normalized_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
