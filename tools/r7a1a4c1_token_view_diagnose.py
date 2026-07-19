#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UNIT = "zel-q4r3-telegram-pos-adapter-v2.service"
TOKEN_KEYS = ("ZEL_TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "BOT_TOKEN")
TOKEN_RE = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")
VIEW_NAME = "view_contract_latest.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=timeout)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o644)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def read_process_environment(unit: str) -> dict[str, str]:
    proc = run(["systemctl", "show", unit, "-p", "MainPID", "--value"])
    try:
        pid = int(proc.stdout.strip())
    except Exception:
        return {}
    if pid <= 0:
        return {}
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except Exception:
        return {}
    values: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        values[key.decode("utf-8", errors="ignore")] = value.decode("utf-8", errors="ignore")
    return values


def candidate_files(root: Path) -> list[Path]:
    roots = [Path("/etc/zel"), Path("/etc/systemd/system"), Path("/var/www/z-os-alimi"), root, Path("/usr/local/bin")]
    excluded = ("/.git/", "/backup/", "/backups/", "/rollback/", "/graveyard/", "/archive/", "/node_modules/", "/__pycache__/")
    unique: dict[str, Path] = {}
    for base in roots:
        if not base.exists():
            continue
        try:
            iterator = base.rglob("*") if base.is_dir() else [base]
            for path in iterator:
                try:
                    marker = "/" + str(path).strip("/") + "/"
                    if any(part in marker.lower() for part in excluded):
                        continue
                    if not path.is_file() or path.stat().st_size > 2_000_000:
                        continue
                    unique[str(path)] = path
                except Exception:
                    continue
        except Exception:
            continue
    return list(unique.values())


def discover_token_evidence(root: Path) -> tuple[dict[str, str], dict[str, set[str]], int]:
    values: dict[str, str] = {}
    paths: dict[str, set[str]] = {}
    scanned = 0
    process_env = read_process_environment(UNIT)
    for key in TOKEN_KEYS:
        value = process_env.get(key, "").strip()
        if TOKEN_RE.fullmatch(value):
            fp = fingerprint(value)
            values[fp] = value
            paths.setdefault(fp, set()).add(f"process-environment:{key}")
    for path in candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        scanned += 1
        for match in TOKEN_RE.finditer(text):
            value = match.group(0)
            fp = fingerprint(value)
            values[fp] = value
            paths.setdefault(fp, set()).add(str(path))
    return values, paths, scanned


def telegram_get_me(token: str) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/getMe"
    request = urllib.request.Request(url, headers={"User-Agent": "ZEL-R7A1A4C1/1.0"})
    try:
        raw = urllib.request.urlopen(request, timeout=15).read().decode("utf-8", errors="ignore")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not payload.get("ok"):
            return {"ok": False, "username": None}
        result = payload.get("result") or {}
        return {"ok": True, "username": str(result.get("username") or "")}
    except Exception:
        return {"ok": False, "username": None}


def token_records(values: dict[str, str], paths: dict[str, set[str]], expected_username: str) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    matches: list[str] = []
    for fp in sorted(values):
        probe = telegram_get_me(values[fp])
        username = probe.get("username")
        expected = bool(username and str(username).lower() == expected_username.lower())
        if expected:
            matches.append(fp)
        records.append({
            "fingerprint": fp,
            "source_path_count": len(paths.get(fp, set())),
            "source_paths": sorted(paths.get(fp, set()))[:80],
            "telegram_api_ok": bool(probe.get("ok")),
            "bot_username": username,
            "expected_bot_match": expected,
        })
    return records, matches


def view_references(root: Path) -> tuple[list[str], list[str]]:
    refs: set[str] = set()
    for path in candidate_files(root):
        try:
            if VIEW_NAME in path.read_text(encoding="utf-8", errors="ignore"):
                refs.add(str(path))
        except Exception:
            continue
    active_refs: set[str] = set()
    units = run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"], timeout=30)
    for raw in units.stdout.splitlines():
        unit = raw.split(None, 1)[0] if raw.strip() else ""
        if not unit:
            continue
        show = run(["systemctl", "show", unit, "-p", "ExecStart", "-p", "FragmentPath"], timeout=10)
        text = show.stdout
        for ref in refs:
            if ref in text:
                active_refs.add(unit + "|" + ref)
                continue
            if ref.endswith((".py", ".sh")) and Path(ref).is_file():
                try:
                    if ref in text or Path(ref).name in text:
                        active_refs.add(unit + "|" + ref)
                except Exception:
                    pass
    return sorted(refs), sorted(active_refs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    contract = load_json(Path(args.contract))
    expected_username = str(contract.get("expected_bot_username") or "z_os_zel_bot")
    out_dir = root / "runtime/exact25_edge_v1/r7a1a4c1_token_view_diagnose"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    blockers: list[str] = []

    b2 = load_json(root / "runtime/exact25_edge_v1/r7a1a4b2_telegram_src_provenance_fix/status_latest.json")
    c = load_json(root / "runtime/exact25_edge_v1/r7a1a4c_environment_binding_canary/status_latest.json")
    if b2.get("state") != "PASS":
        blockers.append("R7A1A4B2_NOT_PASS")
    if c.get("state") != "HOLD":
        blockers.append("R7A1A4C_NOT_HOLD")

    values, paths, scanned = discover_token_evidence(root)
    records, expected_matches = token_records(values, paths, expected_username)
    if len(expected_matches) != 1:
        blockers.append(f"EXPECTED_BOT_MATCH_COUNT_{len(expected_matches)}")

    refs, active_refs = view_references(root)
    if not refs:
        blockers.append("VIEW_CONTRACT_REFERENCE_COUNT_0")

    selected = expected_matches[0] if len(expected_matches) == 1 else None
    state = "PASS" if not blockers else "HOLD"
    next_stage = "R7.A1A4C2_CANARY_SCOPE_PATCH" if state == "PASS" else "R7.A1A4C1_DIAGNOSE"
    payload = {
        "schema": "r7a1a4c1_token_view_diagnose_status_v1",
        "official_stage": "R7.A1A4C1",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "mutation_count": 0,
        "runtime_mutation_count": 0,
        "systemd_mutation_count": 0,
        "value_exposure_count": 0,
        "scanned_file_count": scanned,
        "distinct_token_fingerprint_count": len(records),
        "token_records": records,
        "expected_bot_username": expected_username,
        "expected_bot_match_count": len(expected_matches),
        "selected_token_fingerprint": selected,
        "view_contract_reference_count": len(refs),
        "view_contract_reference_paths": refs[:120],
        "view_contract_active_writer_reference_count": len(active_refs),
        "view_contract_active_writer_references": active_refs[:80],
        "view_contract_exact_hash_guard_valid": False if refs else None,
        "next_stage": next_stage,
    }
    atomic_json(status_path, payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A4C1 Token/View Diagnosis",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- distinct token fingerprints: `{len(records)}`",
            f"- expected bot matches: `{len(expected_matches)}`",
            f"- selected fingerprint: `{selected}`",
            f"- view-contract references: `{len(refs)}`",
            f"- active writer references: `{len(active_refs)}`",
            f"- exact hash guard valid: `{False if refs else None}`",
            f"- next: `{next_stage}`",
            "",
            "No credential value is recorded or printed.",
        ]) + "\n",
        encoding="utf-8",
    )

    print("R7A1A4C1_TOKEN_VIEW_DIAGNOSE_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print("MUTATION_COUNT=0")
    print("RUNTIME_MUTATION_COUNT=0")
    print("SYSTEMD_MUTATION_COUNT=0")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"SCANNED_FILE_COUNT={scanned}")
    print(f"DISTINCT_TOKEN_FINGERPRINT_COUNT={len(records)}")
    print(f"EXPECTED_BOT_MATCH_COUNT={len(expected_matches)}")
    print(f"SELECTED_TOKEN_FINGERPRINT={selected}")
    print(f"VIEW_CONTRACT_REFERENCE_COUNT={len(refs)}")
    print(f"VIEW_CONTRACT_ACTIVE_WRITER_REFERENCE_COUNT={len(active_refs)}")
    print("VIEW_CONTRACT_EXACT_HASH_GUARD_VALID=false")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
