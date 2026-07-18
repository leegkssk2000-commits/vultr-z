#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

TEXT_SUFFIXES = {".py", ".sh", ".js", ".ts", ".tsx", ".html", ".css", ".json", ".service", ".timer", ".conf", ".caddy", ".txt"}
WRITE_MARKERS = ("write_text", "json.dump", "json.dumps", "os.replace", "shutil.copy", "copyfile", "install ", "cp ", ">", "atomic")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path, limit: int) -> str:
    try:
        if not path.is_file() or path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def line_hits(text: str, names: list[str]) -> dict[str, list[int]]:
    rows = text.splitlines()
    return {name: [i for i, row in enumerate(rows, 1) if name.lower() in row.lower()][:20] for name in names}


def classify(path: Path, text: str, names: list[str]) -> str:
    if path.name in names:
        return "EXACT_TARGET_FILE"
    lowered = text.lower()
    if path.suffix in {".service", ".timer"}:
        return "SYSTEMD_REFERENCE"
    if any(marker in lowered for marker in WRITE_MARKERS):
        return "WRITER_CANDIDATE"
    return "REFERENCE"


def scan(contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    names = [str(v) for v in contract["target_names"]]
    excluded = set(str(v) for v in contract.get("excluded_names", []))
    limits = contract["limits"]
    max_files = int(limits["max_files"])
    max_bytes = int(limits["max_file_bytes"])
    max_matches = int(limits["max_matches"])
    records: list[dict[str, Any]] = []
    scanned = 0
    unreadable = 0
    seen: set[str] = set()
    for root_value in contract["scan_roots"]:
        root = Path(root_value)
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in excluded]
            for filename in files:
                scanned += 1
                if scanned > max_files or len(records) >= max_matches:
                    return records, {"scanned_file_count": scanned, "unreadable_count": unreadable, "scan_truncated": 1}
                path = Path(current) / filename
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                exact = filename in names
                if not exact and path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Caddyfile", "nginx.conf"}:
                    continue
                text = read_text(path, max_bytes)
                if not text and not exact:
                    continue
                if exact or any(name.lower() in text.lower() for name in names):
                    try:
                        stat = path.stat()
                        records.append({
                            "path": str(path),
                            "kind": classify(path, text, names),
                            "size_bytes": stat.st_size,
                            "mtime_ns": stat.st_mtime_ns,
                            "sha256": sha256(path) if path.is_file() else "",
                            "line_hits": line_hits(text, names),
                            "write_marker_count": sum(text.lower().count(marker) for marker in WRITE_MARKERS),
                        })
                    except OSError:
                        unreadable += 1
    return records, {"scanned_file_count": scanned, "unreadable_count": unreadable, "scan_truncated": 0}


def systemd_units(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    unit_paths = [Path(row["path"]) for row in records if row["kind"] == "SYSTEMD_REFERENCE"]
    for path in unit_paths:
        unit = path.name
        active = subprocess.run(["systemctl", "show", unit, "-p", "ActiveState", "--value"], text=True, capture_output=True, check=False, timeout=10).stdout.strip()
        enabled = subprocess.run(["systemctl", "is-enabled", unit], text=True, capture_output=True, check=False, timeout=10).stdout.strip()
        output.append({"unit": unit, "fragment_path": str(path), "active": active, "enabled": enabled})
    return output


def build(contract: dict[str, Any], records: list[dict[str, Any]], scan_meta: dict[str, int]) -> dict[str, Any]:
    target = "view_contract_latest.json"
    exact = [r for r in records if Path(r["path"]).name == target]
    refs = [r for r in records if r["line_hits"].get(target)]
    writers = [r for r in refs if r["kind"] == "WRITER_CANDIDATE"]
    units = systemd_units(records)
    blockers: list[str] = []
    if not exact:
        blockers.append("ALIMI_VIEW_CONTRACT_FILE_NOT_FOUND")
    if not refs:
        blockers.append("ALIMI_VIEW_CONTRACT_REFERENCE_NOT_FOUND")
    if not writers and not units:
        blockers.append("ALIMI_VIEW_CONTRACT_OWNER_NOT_FOUND")
    if scan_meta.get("scan_truncated"):
        blockers.append("DISCOVERY_SCAN_TRUNCATED")
    return {
        "schema": "q4r3_exact25_r73b4s1_alimi_surface_resolver_status_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "read_only": True,
        "mutation_count": 0,
        "target_file_count": len(exact),
        "reference_count": len(refs),
        "writer_candidate_count": len(writers),
        "systemd_owner_count": len(units),
        "target_files": exact,
        "writer_candidates": writers,
        "systemd_owners": units,
        "records": records,
        **scan_meta,
        "next_stage": contract["next_stage"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    records, meta = scan(contract)
    result = build(contract, records, meta)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("state", "blocker_count", "target_file_count", "reference_count", "writer_candidate_count", "systemd_owner_count", "scanned_file_count", "scan_truncated")}, sort_keys=True))
    if result["state"] != "PASS":
        print("R73B4S1_DETAIL=" + json.dumps({"blockers": result["blockers"], "target_files": [r["path"] for r in result["target_files"]], "writer_candidates": [r["path"] for r in result["writer_candidates"]], "systemd_owners": result["systemd_owners"]}, sort_keys=True))
    return 0 if result["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
