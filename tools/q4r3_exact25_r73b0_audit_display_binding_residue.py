#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Iterable

TERMS = (
    "telegram", "alimi", "view", "display", "mirror", "writer", "ledger",
    "trace", "closed", "winrate", "pnl", "pos", "6c_lock",
    "telegram_only_6c_lock", "s4g8r7f8t",
)
TEXT_SUFFIXES = {".py", ".sh", ".service", ".timer", ".json", ".md", ".txt", ".conf"}
MAX_BYTES = 2_000_000


def command_lines(args: list[str]) -> list[str]:
    try:
        result = subprocess.run(args, check=False, text=True, capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def matching_lines(path: Path) -> list[dict[str, object]]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return []
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Caddyfile"}:
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    hits: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), 1):
        lowered = line.lower()
        terms = sorted({term for term in TERMS if term in lowered})
        if terms:
            hits.append({"line": number, "terms": terms, "text": line[:500]})
            if len(hits) >= 40:
                break
    return hits


def walk_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    output: list[Path] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in {".git", ".venv", "venv", "node_modules", "__pycache__"}]
        for name in files:
            output.append(Path(current) / name)
    return output


def classify(path: str, hits: list[dict[str, object]], active_names: set[str]) -> str:
    lower = path.lower()
    joined = " ".join(str(hit.get("text", "")).lower() for hit in hits)
    name = Path(path).name
    active = name in active_names or any(name in item for item in active_names)
    if any(token in lower for token in ("backup", "archive", ".bak", ".disabled", "legacy")):
        return "ARCHIVE_OR_BACKUP"
    if "telegram_only_6c_lock" in joined or "s4g8r7f8t" in joined or "6c_lock" in joined:
        return "STATIC_DISPLAY_LOCK"
    if active and any(token in joined for token in ("write_text", "json.dump", "atomic", "replace(", "open(")):
        return "ACTIVE_OVERWRITER_CANDIDATE"
    if active:
        return "CANONICAL_OWNER_CANDIDATE"
    if any(token in lower for token in ("view", "telegram", "pnl", "trace")):
        return "DISABLED_RESIDUE"
    return "UNCLASSIFIED_REVIEW_REQUIRED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--r73a", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    blockers: list[str] = []
    try:
        r73a = json.loads(args.r73a.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        r73a = {}
    if r73a.get("state") != "PASS" or r73a.get("runtime_active") is not False:
        blockers.append("R73A_NOT_PASS")

    roots = [
        Path("/etc/systemd/system"), Path("/usr/lib/systemd/system"), Path("/usr/local/bin"),
        args.root / "backend", args.root / "tools", args.root / "runtime",
    ]
    root_errors = [str(root) for root in roots if not root.exists()]

    active_units = command_lines(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"])
    active_timers = command_lines(["systemctl", "list-timers", "--all", "--no-legend", "--no-pager"])
    active_names = {line.split()[0] for line in active_units + active_timers if line.split()}

    records: list[dict[str, object]] = []
    for root in roots:
        for path in walk_files(root):
            hits = matching_lines(path)
            lower_name = str(path).lower()
            if not hits and not any(term in lower_name for term in TERMS):
                continue
            records.append({
                "path": str(path),
                "classification": classify(str(path), hits, active_names),
                "active_name_match": Path(path).name in active_names,
                "hits": hits,
            })

    groups = {
        "active_units": [line for line in active_units if any(term in line.lower() for term in TERMS)],
        "active_timers": [line for line in active_timers if any(term in line.lower() for term in TERMS)],
        "unit_file_hits": [r for r in records if str(r["path"]).endswith((".service", ".timer"))],
        "script_hits": [r for r in records if str(r["path"]).endswith((".py", ".sh"))],
        "runtime_artifacts": [r for r in records if "/runtime/" in str(r["path"])],
        "static_lock_hits": [r for r in records if r["classification"] == "STATIC_DISPLAY_LOCK"],
        "writer_candidates": [r for r in records if "OWNER_CANDIDATE" in str(r["classification"]) or "OVERWRITER" in str(r["classification"])],
        "archive_or_backup_hits": [r for r in records if r["classification"] == "ARCHIVE_OR_BACKUP"],
    }
    if root_errors:
        blockers.append("SCAN_ROOT_UNREADABLE")
    if any(name not in groups for name in (
        "active_units", "active_timers", "unit_file_hits", "script_hits", "runtime_artifacts",
        "static_lock_hits", "writer_candidates", "archive_or_backup_hits",
    )):
        blockers.append("INVENTORY_INCOMPLETE")

    payload = {
        "schema": "q4r3_exact25_r73b0_display_binding_residue_audit_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": sorted(set(blockers)),
        "blocker_count": len(set(blockers)),
        "scan_root_error_count": len(root_errors),
        "scan_root_errors": root_errors,
        "mutation_count": 0,
        "cleanup_applied": False,
        "inventory_complete": not blockers,
        "record_count": len(records),
        "classification_counts": {
            label: sum(1 for record in records if record["classification"] == label)
            for label in sorted({str(record["classification"]) for record in records})
        },
        "groups": groups,
        "next_stage": "R7.3B1_SINGLE_OWNER_QUARANTINE_PLAN",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "state": payload["state"], "blocker_count": payload["blocker_count"],
        "record_count": payload["record_count"], "writer_candidate_count": len(groups["writer_candidates"]),
        "static_lock_count": len(groups["static_lock_hits"]), "cleanup_applied": False,
    }, sort_keys=True))
    return 0 if payload["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
