#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOTS = ("LBot", "MBot", "OBot", "SBot")
FORBIDDEN_PACKAGE_TERMS = (
    "create_order(", "place_order(", "submit_order(", "cancel_order(",
    "ccxt.", "os.environ", "subprocess.", "requests.", "socket.",
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def boundary_owner(evidence: dict[str, Any], bot: str) -> tuple[str, str] | None:
    component = (evidence.get("components") or {}).get(bot)
    if not isinstance(component, dict):
        return None
    candidates = component.get("candidates") or []
    owners = [row for row in candidates if isinstance(row, dict) and row.get("boundary") == "CORE_SEMANTIC_OWNER"]
    if len(owners) != 1:
        return None
    return str(owners[0].get("path") or ""), str(owners[0].get("sha256") or "")


def validate(root: Path, manifest: dict[str, Any], evidence: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    if evidence.get("state") != "PASS" or evidence.get("verdict") != "R061_BOT_BOUNDARIES_LOCKED":
        blockers.append("R061_BOUNDARY_EVIDENCE_NOT_PASS")
    summary = evidence.get("summary") or {}
    if summary.get("candidate_count") != 14:
        blockers.append("R061_CANDIDATE_PARITY_INVALID")
    if summary.get("core_owner_count") != 4:
        blockers.append("R061_CORE_OWNER_COUNT_INVALID")
    if summary.get("unresolved_boundary_count") != 0:
        blockers.append("R061_UNRESOLVED_BOUNDARY_PRESENT")

    if manifest.get("schema") != "q4r3_canonical_bot_package_manifest_v1":
        blockers.append("MANIFEST_SCHEMA_INVALID")
    if manifest.get("status") != "design_locked_not_activated":
        blockers.append("MANIFEST_STATUS_INVALID")
    for key in ("runtime_binding", "systemd_binding", "direct_order_allowed", "external_advisor_included"):
        if manifest.get(key) is not False:
            blockers.append(f"MANIFEST_{key.upper()}_INVALID")
    if manifest.get("execution_authority") != "none":
        blockers.append("MANIFEST_EXECUTION_AUTHORITY_INVALID")

    owners = manifest.get("owners") or {}
    if set(owners) != set(BOTS):
        blockers.append("MANIFEST_OWNER_SET_INVALID")
    owner_report: dict[str, Any] = {}
    for bot in BOTS:
        row = owners.get(bot) if isinstance(owners, dict) else None
        expected = boundary_owner(evidence, bot)
        if not isinstance(row, dict) or expected is None:
            blockers.append(f"{bot}:OWNER_RECORD_INVALID")
            continue
        expected_path, expected_sha = expected
        if row.get("source_path") != expected_path:
            blockers.append(f"{bot}:SOURCE_PATH_MISMATCH")
        if row.get("source_sha256") != expected_sha:
            blockers.append(f"{bot}:SOURCE_SHA_MISMATCH")
        module_name, class_name = str(row.get("canonical_module") or ":").split(":", 1)
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            instance = cls()
        except Exception as exc:
            blockers.append(f"{bot}:IMPORT_FAILED:{type(exc).__name__}")
            continue
        if getattr(instance, "bot_id", None) != bot:
            blockers.append(f"{bot}:BOT_ID_INVALID")
        owner_report[bot] = {
            "source_path": expected_path,
            "source_sha256": expected_sha,
            "canonical_module": row.get("canonical_module"),
            "semantic_role": getattr(instance, "semantic_role", None),
            "required_evidence": list(getattr(instance, "required_evidence", ())),
        }

    package_dir = root / "canonical/bots"
    package_files = sorted(package_dir.glob("*.py"))
    forbidden_hits: list[str] = []
    for path in package_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for term in FORBIDDEN_PACKAGE_TERMS:
            if term in text:
                forbidden_hits.append(f"{path.relative_to(root)}:{term}")
    if forbidden_hits:
        blockers.append("FORBIDDEN_AUTHORITY_SURFACE_PRESENT")

    report = {
        "owner_count": len(owner_report),
        "owners": owner_report,
        "package_file_count": len(package_files),
        "package_hashes": {str(path.relative_to(root)): digest(path) for path in package_files},
        "forbidden_hits": forbidden_hits,
        "runtime_binding": False,
        "execution_authority": "none",
        "next_route": "BUILD_TEAM_TO_BOT_TYPED_BINDING_WITHOUT_RUNTIME_ACTIVATION",
    }
    return blockers, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--boundary-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.root))
    manifest = load(args.manifest)
    evidence = load(args.boundary_evidence)
    blockers, report = validate(args.root, manifest, evidence)
    payload = {
        "schema": "q4r3_team_advisor_r07_canonical_bot_packages_validation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS" if not blockers else "HOLD",
        "verdict": "R07_CANONICAL_BOT_PACKAGES_LOCK_PASS" if not blockers else "R07_CANONICAL_BOT_PACKAGES_INVALID",
        "blockers": blockers,
        "report": report,
        "authority": {
            "observer_only": True,
            "runtime_mutation_performed": False,
            "systemd_mutation_performed": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "execution_authority": "none",
        },
        "action": "hold",
    }
    write_atomic(args.output, payload)
    print(json.dumps({
        "state": payload["state"],
        "verdict": payload["verdict"],
        "blocker_count": len(blockers),
        "owner_count": report["owner_count"],
        "forbidden_hit_count": len(report["forbidden_hits"]),
    }, sort_keys=True))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
