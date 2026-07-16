#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SPEC_PATH = Path(__file__).with_name("q4r3_team_advisor_r51_zbot_audit_spec.py")
spec = importlib.util.spec_from_file_location("r51_zbot_spec", SPEC_PATH)
assert spec and spec.loader
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)

TEXT_SUFFIXES = {".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".service", ".timer", ".md"}
SKIP_PARTS = {
    ".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "__pycache__",
    "backup", "backups", "archive", "archives", "rollback", "restore", "snapshot", "snapshots",
    "quarantine", "trash", "old", "data", "runtime", "evidence", "journal", "logs", "cache", "tmp", "work",
    "test", "tests", "tool", "tools", "script", "scripts",
}
SUPPORT_PREFIXES = ("test_", "verify_", "apply_", "install_", "bootstrap_", "run_", "audit_", "probe_", "smoke_", "check_")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def scan_roots(root: Path) -> tuple[Path, ...]:
    values = [root / "backend", root / "canonical", root / "config", root / "services", root / "systemd"]
    return tuple(value for value in values if value.exists())


def excluded(relative: Path) -> bool:
    lowered = [part.lower() for part in relative.parts]
    if any(part in SKIP_PARTS for part in lowered):
        return True
    if any(part.endswith((".bak", ".old", ".orig")) for part in lowered):
        return True
    return relative.stem.lower().startswith(SUPPORT_PREFIXES)


def files(root: Path) -> Iterable[Path]:
    for base in scan_roots(root):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                relative = path.relative_to(base)
            except ValueError:
                continue
            if excluded(relative):
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            yield path


def affiliated(path: Path, text: str) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    return (
        normalized.endswith("/canonical/zbot.py")
        or "/canonical/zbot/" in normalized
        or "zbot" in path.name.lower()
        or "class zbot" in text.lower()
        or '"component": "zbot"' in text.lower()
    )


def analyze(root: Path, r46_path: Path) -> dict[str, Any]:
    r46 = read_json(r46_path)
    coverage: dict[str, list[str]] = {name: [] for name in rules.SURFACES}
    candidates: list[str] = []
    owner_paths: list[str] = []

    for path in files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not affiliated(path, text):
            continue
        candidates.append(str(path))
        combined = f"{str(path).lower()}\n{text.lower()}"
        for surface, markers in rules.SURFACES.items():
            if any(marker.lower() in combined for marker in markers):
                coverage[surface].append(str(path))
        normalized = str(path).replace("\\", "/").lower()
        if normalized.endswith("/canonical/zbot.py") or "/canonical/zbot/" in normalized:
            owner_paths.append(str(path))

    candidates = sorted(set(candidates))
    owner_paths = sorted(set(owner_paths))
    coverage = {name: sorted(set(paths)) for name, paths in coverage.items()}
    missing = [name for name, paths in coverage.items() if not paths]
    if len(owner_paths) == 1:
        coverage["unique_canonical_owner"] = owner_paths
        missing = [name for name in missing if name != "unique_canonical_owner"]
    elif "unique_canonical_owner" not in missing:
        missing.append("unique_canonical_owner")

    blockers: list[str] = []
    prior = r46.get("report", {})
    if r46.get("state") != "PASS" or not prior.get("sgrade_ready") or prior.get("final_surface_count") != 16:
        blockers.append("R46_LICO_SGRADE_LOCK_NOT_PROVEN")
    if len(owner_paths) > 1:
        blockers.append("ZBOT_DUPLICATE_CANONICAL_OWNER")

    state = "PASS" if not missing and not blockers else "HOLD"
    report = {
        "candidate_count": len(candidates),
        "candidates": candidates,
        "canonical_owner_count": len(owner_paths),
        "canonical_owner_paths": owner_paths,
        "required_surface_count": len(rules.SURFACES),
        "ready_surface_count": len(rules.SURFACES) - len(missing),
        "missing_surface_count": len(missing),
        "missing_surfaces": sorted(missing),
        "surface_coverage": coverage,
        "r46_lico_sgrade_ready": bool(prior.get("sgrade_ready")),
        "paid_provider_policy_required": True,
        "openai_gemini_independence_required": True,
        "runtime_binding": False,
        "same_epoch_auto_apply": False,
        "execution_authority": "none",
        "sgrade_ready": state == "PASS",
        "next_route": "R5.2_ZBOT_CANONICAL_PROVIDER_POLICY" if state == "HOLD" else "R5.6_ZBOT_SGRADE_LOCK",
    }
    return {
        "schema": rules.SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_stage": "R5.1",
        "state": state,
        "verdict": "R51_ZBOT_SGRADE_GAP_AUDIT_PASS" if state == "PASS" else "R51_ZBOT_SGRADE_GAPS_CLASSIFIED",
        "action": "hold",
        "authority": {
            "observer_only": True,
            "proposal_only": True,
            "execution_authority": "none",
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "same_epoch_auto_apply": False,
        },
        "blockers": sorted(set(blockers)),
        "report": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--r46", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = analyze(args.root.resolve(), args.r46.resolve())
    atomic_json(args.output.resolve(), payload)
    report = payload["report"]
    print(json.dumps({
        "state": payload["state"],
        "candidate_count": report["candidate_count"],
        "canonical_owner_count": report["canonical_owner_count"],
        "ready_surface_count": report["ready_surface_count"],
        "missing_surface_count": report["missing_surface_count"],
        "blocker_count": len(payload["blockers"]),
        "verdict": payload["verdict"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
