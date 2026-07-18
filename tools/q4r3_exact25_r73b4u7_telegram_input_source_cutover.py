#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return payload


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(raw)
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.chmod(mode)
        os.replace(tmp, path)
        path.chmod(mode)
    finally:
        tmp.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_count(source: str, commands: list[str]) -> int:
    return sum(source.count(repr(command)) + source.count(json.dumps(command)) for command in commands)


def snapshot_path(path: Path, backup_dir: Path, index: int) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path), "kind": "absent"}
    if path.is_symlink():
        record.update({"kind": "symlink", "target": os.readlink(path)})
    elif path.exists():
        if not path.is_file():
            raise RuntimeError(f"NON_FILE_SECONDARY_PATH:{path}")
        backup = backup_dir / f"secondary_{index}.bak"
        shutil.copy2(path, backup)
        record.update({"kind": "file", "backup": str(backup), "mode": path.stat().st_mode & 0o777})
    return record


def restore_path(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if path.is_symlink() or path.exists():
        path.unlink()
    if record["kind"] == "symlink":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(record["target"])
    elif record["kind"] == "file":
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record["backup"], path)
        path.chmod(int(record.get("mode", 0o644)))


def as_zero(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def zero_payload() -> dict[str, Any]:
    # String zero is intentional: it remains truthy through legacy `x or fallback`
    # expressions, while int()/float() and the existing renderer still produce 0.
    return {
        "schema": "q4r3_exact25_telegram_zero_compat_input_v1",
        "lane": "ZEL_FOCUS",
        "mode": "shadow",
        "epoch": "q4r3.exact25.shadow.pending",
        "candidate": "0",
        "candidate_count": "0",
        "admitted": "0",
        "admitted_count": "0",
        "open": "0",
        "open_count": "0",
        "closed": "0",
        "closed_count": "0",
        "pnl": "0",
        "pnl_r": "0",
        "net_r": "0",
        "shadow_open": "0",
        "paper_open": "0",
        "live_open": "0",
        "current": {},
        "last_close": "none",
        "last_closed": "none",
        "state": "HOLD_ZERO_EPOCH_PENDING",
        "action": "hold",
        "recent_rows": "0",
        "rows": "0",
        "last12": "0",
        "last12_r": "0",
        "wr": "0",
        "wr_pct": "0",
        "winrate": "0",
        "winrate_pct": "0",
        "win_rate": "0",
        "ev": "0",
        "ev_r": "0",
        "expectancy": "0",
        "expectancy_r": "0",
        "order": "blocked",
        "order_authority": "blocked",
        "exec": "none",
        "execution_authority": "none",
        "runtime_active": False,
        "formal_ledger_bound": False,
        "src": "telegram_zero_compat_input.json",
        "source": "telegram_zero_compat_input.json"
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(args.contract)
    diagnosis_path = Path(contract["diagnosis_status"])
    source_path = Path(contract["telegram_source"])
    canonical_path = Path(contract["canonical_output"])
    compat_path = Path(contract["compat_input"])
    snapshot_path = Path(contract["shadow_snapshot"])
    ledger_path = Path(contract["formal_ledger"])
    backup_root = Path(contract["backup_root"])
    unit = str(contract["telegram_unit"])
    commands = [str(item) for item in contract["expected_commands"]]
    blockers: list[str] = []

    for path in (diagnosis_path, source_path, canonical_path, snapshot_path):
        if not path.is_file():
            blockers.append(f"MISSING:{path}")
    if blockers:
        payload = {"state": "HOLD", "blockers": blockers, "blocker_count": len(blockers), "mutation_count": 0}
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    diagnosis = read_json(diagnosis_path)
    renderer = diagnosis.get("telegram_renderer") if isinstance(diagnosis.get("telegram_renderer"), dict) else {}
    secondary_paths = sorted({Path(str(item)) for item in renderer.get("secondary_json_paths", []) if isinstance(item, str)})
    secondary_paths = [path for path in secondary_paths if path.resolve(strict=False) != canonical_path.resolve(strict=False)]
    source_before = sha256(source_path)
    source_text = source_path.read_text(encoding="utf-8", errors="strict")
    snapshot = read_json(snapshot_path)

    if command_count(source_text, commands) < len(commands):
        blockers.append("TELEGRAM_COMMAND_SOURCE_NOT_RESTORED")
    if len(secondary_paths) != int(contract["expected_secondary_path_count"]):
        blockers.append(f"SECONDARY_PATH_COUNT:{len(secondary_paths)}")
    if snapshot.get("runtime_active") is not False or snapshot.get("formal_ledger_bound") is not False:
        blockers.append("SHADOW_AUTHORITY_NOT_BLOCKED")
    if blockers:
        payload = {"state": "HOLD", "blockers": blockers, "blocker_count": len(blockers), "mutation_count": 0}
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    stamp = str(time.time_ns())
    backup_dir = backup_root / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    canonical_backup = backup_dir / "telegram_status_latest.json.bak"
    shutil.copy2(canonical_path, canonical_backup)
    compat_record = snapshot_path_state = snapshot_path  # keep name collision impossible below
    del compat_record, snapshot_path_state
    compat_snapshot = snapshot_path_fn = None
    del compat_snapshot, snapshot_path_fn
    compat_record_data = snapshot_path(compat_path, backup_dir, 999) if False else None
    # Explicit snapshot avoids shadowing the helper name.
    if compat_path.is_symlink():
        compat_record_state: dict[str, Any] = {"path": str(compat_path), "kind": "symlink", "target": os.readlink(compat_path)}
    elif compat_path.exists():
        compat_backup = backup_dir / "compat_input.bak"
        shutil.copy2(compat_path, compat_backup)
        compat_record_state = {"path": str(compat_path), "kind": "file", "backup": str(compat_backup), "mode": compat_path.stat().st_mode & 0o777}
    else:
        compat_record_state = {"path": str(compat_path), "kind": "absent"}
    secondary_records = [snapshot_path(path, backup_dir, index) for index, path in enumerate(secondary_paths)]
    ledger_before = sha256(ledger_path) if ledger_path.is_file() else ""
    mutations: list[str] = []

    try:
        stop = run(["systemctl", "stop", unit])
        if stop.returncode != 0:
            raise RuntimeError("TELEGRAM_STOP_FAILED:" + stop.stderr[-300:])

        payload_zero = zero_payload()
        atomic_json(compat_path, payload_zero)
        mutations.append("ZERO_COMPAT_INPUT_WRITTEN")

        for path in secondary_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.exists():
                path.unlink()
            path.symlink_to(compat_path)
        mutations.append("LEGACY_INPUTS_CUT_OVER")

        atomic_json(canonical_path, payload_zero)
        mutations.append("CANONICAL_OUTPUT_ZEROED")

        start_epoch = int(time.time())
        start = run(["systemctl", "start", unit])
        if start.returncode != 0:
            raise RuntimeError("TELEGRAM_START_FAILED:" + start.stderr[-300:])
        time.sleep(3)

        active = run(["systemctl", "is-active", unit]).stdout.strip()
        if active != "active":
            raise RuntimeError("TELEGRAM_UNIT_NOT_ACTIVE:" + active)
        compile_result = run(["python3", "-m", "py_compile", str(source_path)])
        if compile_result.returncode != 0:
            raise RuntimeError("TELEGRAM_COMPILE_FAILED:" + compile_result.stderr[-300:])
        if sha256(source_path) != source_before:
            raise RuntimeError("TELEGRAM_SOURCE_CHANGED")

        alias_failures = [
            str(path) for path in secondary_paths
            if not path.is_symlink() or path.resolve(strict=False) != compat_path.resolve(strict=False)
        ]
        if alias_failures:
            raise RuntimeError("LEGACY_INPUT_CUTOVER_FAILED:" + ",".join(alias_failures))

        live = read_json(canonical_path)
        checks = {
            "closed": first(live, "closed_count", "closed"),
            "recent_rows": first(live, "recent_rows", "rows"),
            "last12": first(live, "last12_r", "last12"),
            "wr": first(live, "winrate_pct", "wr", "winrate"),
            "ev": first(live, "ev_r", "ev", "expectancy_r"),
            "pnl": first(live, "pnl_r", "net_r", "pnl"),
        }
        nonzero = [f"{key}={value}" for key, value in checks.items() if not as_zero(value)]
        if nonzero:
            raise RuntimeError("ZERO_OUTPUT_ASSERT_FAILED:" + ",".join(nonzero))
        if str(first(live, "last_close", "last_closed")).lower() not in {"none", "", "{}"}:
            raise RuntimeError("LAST_CLOSE_RESIDUE_REMAINS:" + str(first(live, "last_close", "last_closed")))

        journal = run(["journalctl", "-u", unit, "--since", f"@{start_epoch}", "--no-pager", "-o", "cat"]).stdout
        errors = [line for line in journal.splitlines() if any(token in line for token in ("Traceback", "ERROR", "Exception", "NameError", "TypeError", "AttributeError", "SyntaxError"))]
        if errors:
            raise RuntimeError("TELEGRAM_RUNTIME_ERRORS:" + " | ".join(errors[-5:]))
        if ledger_before and sha256(ledger_path) != ledger_before:
            raise RuntimeError("FORMAL_LEDGER_CHANGED")
        snapshot_after = read_json(snapshot_path)
        if snapshot_after.get("runtime_active") is not False or snapshot_after.get("formal_ledger_bound") is not False:
            raise RuntimeError("SHADOW_RUNTIME_CHANGED")

        result = {
            "schema": "q4r3_exact25_r73b4u7_telegram_input_source_cutover_status_v1",
            "state": "PASS",
            "blockers": [],
            "blocker_count": 0,
            "mutation_count": len(mutations),
            "mutations": mutations,
            "rollback_performed": False,
            "telegram_source_change_count": 0,
            "telegram_command_count": command_count(source_text, commands),
            "telegram_compile_ok": True,
            "telegram_unit_active": True,
            "telegram_runtime_error_count": 0,
            "legacy_input_path_count": len(secondary_paths),
            "legacy_input_cutover_count": len(secondary_paths),
            "canonical_closed_count": 0,
            "canonical_recent_rows": 0,
            "canonical_last12_r": 0.0,
            "canonical_winrate_pct": 0.0,
            "canonical_ev_r": 0.0,
            "canonical_pnl_r": 0.0,
            "canonical_last_close": "none",
            "formal_ledger_change_count": 0,
            "runtime_active": False,
            "next_stage": contract["next_stage"]
        }
        atomic_json(args.status, result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        run(["systemctl", "stop", unit])
        for record in secondary_records:
            restore_path(record)
        restore_path(compat_record_state)
        shutil.copy2(canonical_backup, canonical_path)
        run(["systemctl", "start", unit])
        result = {
            "schema": "q4r3_exact25_r73b4u7_telegram_input_source_cutover_status_v1",
            "state": "HOLD",
            "blockers": [str(exc)],
            "blocker_count": 1,
            "mutation_count": len(mutations),
            "mutations": mutations,
            "rollback_performed": True,
            "telegram_source_change_count": 0,
            "runtime_active": False,
            "next_stage": "R7.3B4U7_DIAGNOSE"
        }
        atomic_json(args.status, result)
        print(json.dumps(result, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
