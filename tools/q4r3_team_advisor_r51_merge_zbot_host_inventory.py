#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

SPEC_PATH = Path(__file__).with_name("q4r3_team_advisor_r51_zbot_audit_spec.py")
spec = importlib.util.spec_from_file_location("r51_zbot_host_spec", SPEC_PATH)
assert spec and spec.loader
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

HOST_ROOT = Path("/usr/local/bin")
ALLOWED_SUFFIXES = {".py", ".sh", ""}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError("STATUS_NOT_OBJECT")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    status_path = args.status.resolve()
    payload = read_json(status_path)
    report = payload["report"]
    coverage = {name: list(paths) for name, paths in report["surface_coverage"].items()}
    candidates = list(report["candidates"])
    host_candidates: list[str] = []

    if HOST_ROOT.is_dir():
        for path in HOST_ROOT.iterdir():
            if not path.is_file() or "zbot" not in path.name.lower() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            host_candidates.append(str(path))
            candidates.append(str(path))
            combined = f"{str(path).lower()}\n{text.lower()}"
            for surface, markers in rules.SURFACES.items():
                if any(marker.lower() in combined for marker in markers):
                    coverage.setdefault(surface, []).append(str(path))

    coverage = {name: sorted(set(paths)) for name, paths in coverage.items()}
    candidates = sorted(set(candidates))
    missing = [name for name, paths in coverage.items() if not paths]
    if report.get("canonical_owner_count") != 1 and "unique_canonical_owner" not in missing:
        missing.append("unique_canonical_owner")

    report["surface_coverage"] = coverage
    report["candidates"] = candidates
    report["candidate_count"] = len(candidates)
    report["host_runtime_candidates"] = sorted(set(host_candidates))
    report["host_runtime_candidate_count"] = len(set(host_candidates))
    report["missing_surfaces"] = sorted(missing)
    report["missing_surface_count"] = len(missing)
    report["ready_surface_count"] = len(rules.SURFACES) - len(missing)
    payload["state"] = "PASS" if not missing and not payload.get("blockers") else "HOLD"
    payload["verdict"] = "R51_ZBOT_SGRADE_GAP_AUDIT_PASS" if payload["state"] == "PASS" else "R51_ZBOT_SGRADE_GAPS_CLASSIFIED"
    report["sgrade_ready"] = payload["state"] == "PASS"
    report["next_route"] = "R5.2_ZBOT_CANONICAL_PROVIDER_POLICY" if payload["state"] == "HOLD" else "R5.6_ZBOT_SGRADE_LOCK"
    atomic_json(status_path, payload)

    print(json.dumps({
        "host_runtime_candidate_count": report["host_runtime_candidate_count"],
        "ready_surface_count": report["ready_surface_count"],
        "missing_surface_count": report["missing_surface_count"],
        "state": payload["state"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
