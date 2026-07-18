#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

WRITER_TEXT = "configured=7 · active=0 · VV/TR/LS/MO/VB/MS/SR"
ERROR_RE = re.compile(r"Traceback|\bERROR\b|Exception|NameError|TypeError|AttributeError|SyntaxError", re.I)


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return payload


def atomic_text(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(raw)
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(mode)
        os.replace(tmp, path)
        path.chmod(mode)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", 0o644)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metric(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def latest_backup(pattern: str) -> Path:
    candidates = [Path(item) for item in glob.glob(pattern)]
    candidates = [item for item in candidates if item.is_file()]
    if not candidates:
        raise RuntimeError("TELEGRAM_PREPATCH_BACKUP_NOT_FOUND")
    return max(candidates, key=lambda item: item.stat().st_mtime_ns)


def command_count(source: str) -> int:
    return sum(source.count(token) for token in ('"/pos"', "'/pos'", '"/pnl"', "'/pnl'", '"/view"', "'/view'"))


def exact_view_patch(source: str, display_label: str) -> tuple[str, int]:
    patched = source.replace("q4r3_shadow_closed_ledger_latest.json", display_label)
    patched = patched.replace("A/B/G/D team lane", "")
    patterns = (
        r"configured=7\s*·\s*active=0\s*·\s*VV/TR/LS/MO/VB/MS/SR(?:\s*[—-]+\s*)*",
        r"writer_count\s*=\s*\$\{[^}]+\}(?:\s*·\s*[^<`\"']+)?",
        r"writer_count\s*=\s*0(?:\s*·\s*[^<`\"']+)?",
    )
    replacement_count = 0
    for pattern in patterns:
        patched, count = re.subn(pattern, WRITER_TEXT, patched, count=1, flags=re.I)
        replacement_count += count
        if count:
            break
    return patched, replacement_count


def snapshot_path(path: Path, backup_dir: Path, index: int) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path), "kind": "absent"}
    if path.is_symlink():
        record.update({"kind": "symlink", "target": os.readlink(path)})
    elif path.exists():
        backup = backup_dir / f"secondary.{index}.bak"
        if path.is_file():
            shutil.copy2(path, backup)
            record.update({"kind": "file", "backup": str(backup), "mode": path.stat().st_mode & 0o777})
        else:
            raise RuntimeError(f"SECONDARY_PATH_NOT_FILE:{path}")
    return record


def restore_path(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if path.is_symlink() or path.exists():
        path.unlink()
    kind = record["kind"]
    if kind == "symlink":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(record["target"])
    elif kind == "file":
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record["backup"], path)
        path.chmod(int(record.get("mode", 0o644)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(args.contract)
    parent_path = Path(contract["parent_status"])
    diagnosis_path = Path(contract["diagnosis_status"])
    source_path = Path(contract["telegram_source"])
    canonical_path = Path(contract["canonical_telegram_artifact"])
    view_path = Path(contract["view_index"])
    ledger_path = Path(contract["formal_ledger"])
    snapshot_path_file = Path(contract["shadow_snapshot"])
    blockers: list[str] = []

    for required in (parent_path, diagnosis_path, source_path, canonical_path, view_path, snapshot_path_file):
        if not required.exists():
            blockers.append(f"MISSING:{required}")
    if blockers:
        payload = {"state": "HOLD", "blockers": blockers, "blocker_count": len(blockers), "mutation_count": 0}
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    parent = read_json(parent_path)
    diagnosis = read_json(diagnosis_path)
    canonical = read_json(canonical_path)
    shadow = read_json(snapshot_path_file)
    renderer = diagnosis.get("telegram_renderer", {}) if isinstance(diagnosis.get("telegram_renderer"), dict) else {}
    secondary_paths = sorted({Path(str(item)) for item in renderer.get("secondary_json_paths", []) if isinstance(item, str)})

    if parent.get("state") != "PASS":
        blockers.append("B4U3U4_PARENT_NOT_PASS")
    if int(metric(canonical, "closed_count", "closed", default=-1)) != 0:
        blockers.append("CANONICAL_CLOSED_NOT_ZERO")
    if int(metric(canonical, "recent_rows", "rows", default=-1)) != 0:
        blockers.append("CANONICAL_RECENT_ROWS_NOT_ZERO")
    if float(metric(canonical, "pnl_r", "net_r", default=-1.0)) != 0.0:
        blockers.append("CANONICAL_PNL_NOT_ZERO")
    if shadow.get("runtime_active") is not False or shadow.get("formal_ledger_bound") is not False:
        blockers.append("SHADOW_AUTHORITY_NOT_BLOCKED")
    if len(secondary_paths) < 1:
        blockers.append("SECONDARY_PATH_INVENTORY_EMPTY")
    if blockers:
        payload = {"state": "HOLD", "blockers": blockers, "blocker_count": len(blockers), "mutation_count": 0}
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    backup_root = args.status.parent / "rollback"
    backup_root.mkdir(parents=True, exist_ok=True)
    live_source_backup = backup_root / "telegram_live_before_recovery.py"
    view_backup = backup_root / "view_before_recovery.html"
    shutil.copy2(source_path, live_source_backup)
    shutil.copy2(view_path, view_backup)
    source_mode = source_path.stat().st_mode & 0o777
    view_mode = view_path.stat().st_mode & 0o777
    ledger_before = sha256(ledger_path) if ledger_path.is_file() else ""
    secondary_records = [snapshot_path(path, backup_root, index) for index, path in enumerate(secondary_paths)]
    mutations: list[str] = []

    try:
        prepatch = latest_backup(contract["telegram_backup_glob"])
        original_source = prepatch.read_text(encoding="utf-8", errors="strict")
        if command_count(original_source) < int(contract["pass_conditions"]["telegram_command_count_min"]):
            raise RuntimeError("PREPATCH_SOURCE_COMMANDS_MISSING")
        compile(original_source, str(prepatch), "exec")
        atomic_text(source_path, original_source, source_mode or 0o755)
        mutations.append("TELEGRAM_SOURCE_RESTORED_PRE_AST_REWRITE")

        for path in secondary_paths:
            if path.resolve(strict=False) == canonical_path.resolve(strict=False):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.exists():
                path.unlink()
            path.symlink_to(canonical_path)
        mutations.append("TELEGRAM_SECONDARY_SOURCES_CANONICAL_ALIASED")

        view_source = view_path.read_text(encoding="utf-8", errors="strict")
        patched_view, view_replacement_count = exact_view_patch(view_source, contract["display_label"])
        if view_replacement_count < 1 and WRITER_TEXT not in patched_view:
            raise RuntimeError("VIEW_WRITER_CARD_EXACT_PATCH_NOT_FOUND")
        atomic_text(view_path, patched_view, view_mode or 0o644)
        mutations.append("VIEW_WRITERS7_EXACT_LABEL_LOCKED")

        compile_result = run(["python3", "-m", "py_compile", str(source_path)])
        if compile_result.returncode != 0:
            raise RuntimeError("TELEGRAM_COMPILE_FAILED:" + compile_result.stderr[-400:])
        restored_source = source_path.read_text(encoding="utf-8")
        commands = command_count(restored_source)
        if commands < int(contract["pass_conditions"]["telegram_command_count_min"]):
            raise RuntimeError(f"TELEGRAM_COMMAND_COUNT_LOW:{commands}")

        start_epoch = int(time.time())
        restart = run(["systemctl", "restart", contract["telegram_unit"]])
        if restart.returncode != 0:
            raise RuntimeError("TELEGRAM_RESTART_FAILED:" + restart.stderr[-400:])
        time.sleep(3)
        active = run(["systemctl", "is-active", contract["telegram_unit"]]).stdout.strip()
        if active != "active":
            raise RuntimeError(f"TELEGRAM_UNIT_NOT_ACTIVE:{active}")
        journal = run([
            "journalctl", "-u", contract["telegram_unit"], "--since", f"@{start_epoch}",
            "--no-pager", "-o", "cat"
        ]).stdout
        startup_errors = [line for line in journal.splitlines() if ERROR_RE.search(line)]
        if startup_errors:
            raise RuntimeError("TELEGRAM_STARTUP_ERRORS:" + " | ".join(startup_errors[-5:]))

        alias_failures = []
        for path in secondary_paths:
            if not path.is_symlink() or path.resolve(strict=False) != canonical_path.resolve(strict=False):
                alias_failures.append(str(path))
        if alias_failures:
            raise RuntimeError("SECONDARY_ALIAS_FAILURE:" + ",".join(alias_failures))
        view_live = view_path.read_text(encoding="utf-8")
        if WRITER_TEXT not in view_live:
            raise RuntimeError("VIEW_WRITER_TEXT_NOT_EXACT")
        if "q4r3_shadow_closed_ledger_latest.json" in view_live or "A/B/G/D team lane" in view_live:
            raise RuntimeError("VIEW_RESIDUE_REMAINS")
        if ledger_before and sha256(ledger_path) != ledger_before:
            raise RuntimeError("FORMAL_LEDGER_CHANGED")
        shadow_after = read_json(snapshot_path_file)
        if shadow_after.get("runtime_active") is not False or shadow_after.get("formal_ledger_bound") is not False:
            raise RuntimeError("SHADOW_RUNTIME_CHANGED")

        payload = {
            "schema": "q4r3_exact25_r73b4u5_telegram_pos_recovery_status_v1",
            "state": "PASS",
            "blockers": [],
            "blocker_count": 0,
            "mutation_count": len(mutations),
            "mutations": mutations,
            "rollback_performed": False,
            "restored_from_backup": str(prepatch),
            "telegram_command_count": commands,
            "telegram_compile_ok": True,
            "telegram_unit_active": True,
            "telegram_startup_error_count": 0,
            "secondary_source_alias_count": len(secondary_paths),
            "canonical_closed_count": int(metric(canonical, "closed_count", "closed", default=0)),
            "canonical_recent_rows": int(metric(canonical, "recent_rows", "rows", default=0)),
            "canonical_pnl_r": float(metric(canonical, "pnl_r", "net_r", default=0.0)),
            "view_writer_card_exact": True,
            "formal_ledger_change_count": 0,
            "runtime_active": False,
            "next_stage": contract["next_stage"],
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        shutil.copy2(live_source_backup, source_path)
        source_path.chmod(source_mode or 0o755)
        shutil.copy2(view_backup, view_path)
        view_path.chmod(view_mode or 0o644)
        for record in secondary_records:
            restore_path(record)
        run(["systemctl", "restart", contract["telegram_unit"]])
        payload = {
            "schema": "q4r3_exact25_r73b4u5_telegram_pos_recovery_status_v1",
            "state": "HOLD",
            "blockers": [str(exc)],
            "blocker_count": 1,
            "mutation_count": len(mutations),
            "mutations": mutations,
            "rollback_performed": True,
            "runtime_active": False,
            "next_stage": "R7.3B4U5_DIAGNOSE",
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
