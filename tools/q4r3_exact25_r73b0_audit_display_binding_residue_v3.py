#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Iterable

TEXT_SUFFIXES = {".py", ".sh", ".service", ".timer", ".json", ".md", ".txt", ".conf"}
MAX_BYTES = 2_000_000
MAX_LINE_HITS = 40
MAX_NONCRITICAL_RECORDS = 5000

PATTERNS: dict[str, re.Pattern[str]] = {
    "telegram": re.compile(r"\btelegram\b", re.IGNORECASE),
    "alimi": re.compile(r"\balimi\b", re.IGNORECASE),
    "view": re.compile(r"(?<![A-Za-z0-9_])/?view(?![A-Za-z0-9_])", re.IGNORECASE),
    "display": re.compile(r"\bdisplay(?:er|_lock|_mirror|_writer)?\b", re.IGNORECASE),
    "mirror": re.compile(r"\bmirror(?:ed|ing|_writer)?\b", re.IGNORECASE),
    "writer": re.compile(r"\bwriter\b|write_text\s*\(|json\.dump\s*\(|atomic[_-]?write", re.IGNORECASE),
    "ledger": re.compile(r"\b(?:formal[_ -]?)?ledger\b", re.IGNORECASE),
    "recent_trace": re.compile(r"\brecent[_ -]?trace\b", re.IGNORECASE),
    "closed_count": re.compile(r"\bclosed[_ -]?count\b", re.IGNORECASE),
    "winrate": re.compile(r"\bwin[_ -]?rate\b|\bwinrate\b", re.IGNORECASE),
    "pnl": re.compile(r"(?<![A-Za-z0-9_])/?pnl(?![A-Za-z0-9_])", re.IGNORECASE),
    "pos": re.compile(r"(?<![A-Za-z0-9_])/?pos(?![A-Za-z0-9_])", re.IGNORECASE),
    "six_c_lock": re.compile(r"6c[_ -]?lock|telegram_only_6c_lock|s4g8r7f8t", re.IGNORECASE),
}
PATH_TOKENS = (
    "telegram", "alimi", "view", "display", "mirror", "writer", "recent_trace",
    "winrate", "pnl", "6c_lock", "telegram_only_6c_lock", "s4g8r7f8t",
)
CRITICAL_CLASSES = {
    "CANONICAL_OWNER_CANDIDATE",
    "ACTIVE_OVERWRITER_CANDIDATE",
    "STATIC_DISPLAY_LOCK",
}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}


def command_snapshot(args: list[str]) -> tuple[list[str], str | None]:
    try:
        result = subprocess.run(args, check=False, text=True, capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"{type(exc).__name__}:{exc}"
    if result.returncode != 0:
        message = (result.stderr or result.stdout or f"returncode={result.returncode}").strip()
        return [], message[:500]
    return [line.strip() for line in result.stdout.splitlines() if line.strip()], None


def matching_lines(path: Path) -> list[dict[str, object]]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return []
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != "Caddyfile":
            return []
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    hits: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), 1):
        labels = sorted(label for label, pattern in PATTERNS.items() if pattern.search(line))
        if labels:
            hits.append({"line": number, "terms": labels, "text": line[:500]})
            if len(hits) >= MAX_LINE_HITS:
                break
    return hits


def walk_files(root: Path, excluded: set[Path]) -> Iterable[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    output: list[Path] = []
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        dirs[:] = [
            name for name in dirs
            if name not in SKIP_DIRS
            and not any((current_path / name).resolve(strict=False) == blocked for blocked in excluded)
        ]
        for name in files:
            output.append(current_path / name)
    return output


def path_relevant(path: Path) -> bool:
    lowered = str(path).lower()
    return any(token in lowered for token in PATH_TOKENS)


def classify(path: str, hits: list[dict[str, object]], active_names: set[str]) -> str:
    lower = path.lower()
    joined = " ".join(str(hit.get("text", "")).lower() for hit in hits)
    name = Path(path).name
    active = name in active_names or any(name in item for item in active_names)
    if any(token in lower for token in ("backup", "archive", ".bak", ".disabled", "legacy")):
        return "ARCHIVE_OR_BACKUP"
    if re.search(r"6c[_ -]?lock|telegram_only_6c_lock|s4g8r7f8t", joined, re.IGNORECASE):
        return "STATIC_DISPLAY_LOCK"
    writer_signal = "writer" in lower or bool(PATTERNS["writer"].search(joined))
    if active and writer_signal:
        return "ACTIVE_OVERWRITER_CANDIDATE"
    if active:
        return "CANONICAL_OWNER_CANDIDATE"
    if path_relevant(Path(path)):
        return "DISABLED_RESIDUE"
    return "UNCLASSIFIED_REVIEW_REQUIRED"


def unique_existing(paths: list[Path]) -> tuple[list[Path], list[str]]:
    existing: list[Path] = []
    missing: list[str] = []
    seen: set[Path] = set()
    for path in paths:
        if not path.exists():
            missing.append(str(path))
            continue
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        existing.append(path)
    return existing, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--r73a", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    blockers: list[str] = []
    warnings: list[str] = []
    try:
        r73a = json.loads(args.r73a.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        r73a = {}
    if r73a.get("state") != "PASS" or r73a.get("runtime_active") is not False:
        blockers.append("R73A_NOT_PASS")

    required_candidates = [args.root / "backend", args.root / "runtime"]
    required_roots, required_missing = unique_existing(required_candidates)
    if required_missing:
        blockers.append("REQUIRED_SCAN_ROOT_UNREADABLE")

    systemd_candidates = [
        Path("/etc/systemd/system"), Path("/run/systemd/system"),
        Path("/usr/lib/systemd/system"), Path("/lib/systemd/system"),
    ]
    systemd_roots, systemd_missing = unique_existing(systemd_candidates)
    if not systemd_roots:
        blockers.append("SYSTEMD_SCAN_ROOT_UNAVAILABLE")

    optional_candidates = [Path("/usr/local/bin"), args.root / "tools"]
    optional_roots, optional_missing = unique_existing(optional_candidates)
    if optional_missing:
        warnings.append("OPTIONAL_SCAN_ROOT_MISSING")

    roots, _ = unique_existing(required_roots + systemd_roots + optional_roots)
    output_root = args.output.parent.resolve(strict=False)
    excluded = {output_root}

    active_units, service_error = command_snapshot([
        "systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager",
    ])
    active_timers, timer_error = command_snapshot([
        "systemctl", "list-timers", "--all", "--no-legend", "--no-pager",
    ])
    systemctl_errors = [error for error in (service_error, timer_error) if error]
    if systemctl_errors:
        blockers.append("SYSTEMD_QUERY_FAILED")
    active_names = {line.split()[0] for line in active_units + active_timers if line.split()}

    records: list[dict[str, object]] = []
    suppressed_noncritical_count = 0
    for root in roots:
        for path in walk_files(root, excluded):
            hits = matching_lines(path)
            if not hits and not path_relevant(path):
                continue
            classification = classify(str(path), hits, active_names)
            record = {
                "path": str(path),
                "classification": classification,
                "active_name_match": Path(path).name in active_names,
                "hits": hits,
            }
            if classification not in CRITICAL_CLASSES and len(records) >= MAX_NONCRITICAL_RECORDS:
                suppressed_noncritical_count += 1
                continue
            records.append(record)

    groups = {
        "active_units": [line for line in active_units if any(pattern.search(line) for pattern in PATTERNS.values())],
        "active_timers": [line for line in active_timers if any(pattern.search(line) for pattern in PATTERNS.values())],
        "unit_file_hits": [r for r in records if str(r["path"]).endswith((".service", ".timer"))],
        "script_hits": [r for r in records if str(r["path"]).endswith((".py", ".sh"))],
        "runtime_artifacts": [r for r in records if "/runtime/" in str(r["path"])],
        "static_lock_hits": [r for r in records if r["classification"] == "STATIC_DISPLAY_LOCK"],
        "writer_candidates": [
            r for r in records
            if r["classification"] in {"CANONICAL_OWNER_CANDIDATE", "ACTIVE_OVERWRITER_CANDIDATE"}
        ],
        "archive_or_backup_hits": [r for r in records if r["classification"] == "ARCHIVE_OR_BACKUP"],
    }
    required_groups = {
        "active_units", "active_timers", "unit_file_hits", "script_hits", "runtime_artifacts",
        "static_lock_hits", "writer_candidates", "archive_or_backup_hits",
    }
    if set(groups) != required_groups:
        blockers.append("INVENTORY_INCOMPLETE")

    blocker_set = sorted(set(blockers))
    payload = {
        "schema": "q4r3_exact25_r73b0_display_binding_residue_audit_v2",
        "state": "PASS" if not blocker_set else "HOLD",
        "blockers": blocker_set,
        "blocker_count": len(blocker_set),
        "warnings": sorted(set(warnings)),
        "warning_count": len(set(warnings)),
        "required_scan_root_error_count": len(required_missing),
        "required_scan_root_errors": required_missing,
        "optional_scan_root_missing_count": len(optional_missing) + len(systemd_missing),
        "optional_scan_root_missing": optional_missing + systemd_missing,
        "systemctl_errors": systemctl_errors,
        "mutation_count": 0,
        "cleanup_applied": False,
        "inventory_complete": not blocker_set,
        "record_count": len(records),
        "suppressed_noncritical_record_count": suppressed_noncritical_count,
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
        "state": payload["state"],
        "blocker_count": payload["blocker_count"],
        "warning_count": payload["warning_count"],
        "record_count": payload["record_count"],
        "suppressed_noncritical_record_count": payload["suppressed_noncritical_record_count"],
        "writer_candidate_count": len(groups["writer_candidates"]),
        "static_lock_count": len(groups["static_lock_hits"]),
        "cleanup_applied": False,
    }, sort_keys=True))
    return 0 if payload["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
