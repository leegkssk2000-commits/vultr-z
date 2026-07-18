#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return obj


def atomic_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(raw)
    try:
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def scalar(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in obj:
            return obj[key]
    return default


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "active", "blocked"}


def fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    cmd = ["curl", "-sS", "-L", "--max-time", "15", "-H", "Cache-Control: no-cache", "-w", "\n%{http_code}"]
    if url.startswith("https://alimi.z-os.vip/"):
        cmd += ["--resolve", "alimi.z-os.vip:443:127.0.0.1"]
    cmd.append(f"{url}{'&' if '?' in url else '?'}r73b4w={time.time_ns()}")
    p = run(cmd, timeout=20)
    body, _, code_raw = p.stdout.rpartition("\n")
    try:
        code = int(code_raw)
    except ValueError:
        code = 0
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        obj = {}
    return code, obj if isinstance(obj, dict) else {}


def unit_properties(unit: str) -> dict[str, str]:
    p = run(["systemctl", "show", unit, "-p", "Id", "-p", "LoadState", "-p", "ActiveState", "-p", "FragmentPath", "-p", "ExecStart"])
    result: dict[str, str] = {}
    for line in p.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            result[k] = v
    return result


def discover_unit(contract: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    p = run(["systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"])
    required_unit = [s.lower() for s in contract["required_unit_tokens_any"]]
    forbidden_unit = [s.lower() for s in contract["forbidden_unit_tokens"]]
    required_exec = [s.lower() for s in contract["required_exec_tokens_any"]]
    forbidden_exec = [s.lower() for s in contract["forbidden_exec_tokens"]]
    inspected: list[dict[str, str]] = []
    candidates: list[dict[str, str]] = []
    for line in p.stdout.splitlines():
        unit = line.split()[0] if line.split() else ""
        if not unit.endswith(".service"):
            continue
        low = unit.lower()
        if not any(token in low for token in required_unit):
            continue
        props = unit_properties(unit)
        exec_start = props.get("ExecStart", "")
        joined = f"{unit} {exec_start} {props.get('FragmentPath','')}".lower()
        record = {"unit": unit, "active": props.get("ActiveState", ""), "exec_start": exec_start, "fragment": props.get("FragmentPath", "")}
        inspected.append(record)
        if any(token in joined for token in forbidden_unit + forbidden_exec):
            continue
        if not any(token in joined for token in required_exec):
            continue
        candidates.append(record)
    return candidates, inspected


def journal_error_count(unit: str, since_epoch: int) -> int:
    p = run(["journalctl", "-u", unit, "--since", f"@{since_epoch}", "--no-pager", "-o", "cat"])
    rx = re.compile(r"traceback|exception|\berror\b|failed|fatal", re.I)
    return sum(1 for line in p.stdout.splitlines() if rx.search(line))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--status", type=Path, required=True)
    args = ap.parse_args()
    contract = read_json(args.contract)
    parent_path = Path(contract["parent_status"])
    snapshot_path = Path(contract["shadow_snapshot"])
    telegram_path = Path(contract["telegram_artifact"])
    ledger_path = Path(contract["formal_ledger"])
    blockers: list[str] = []

    for p in (parent_path, snapshot_path, telegram_path):
        if not p.is_file():
            blockers.append(f"MISSING_REQUIRED:{p}")
    if blockers:
        payload = {"state": "HOLD", "blockers": blockers, "blocker_count": len(blockers), "mutation_count": 0}
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    parent = read_json(parent_path)
    snapshot_before = read_json(snapshot_path)
    telegram_before = read_json(telegram_path)
    if parent.get("state") != contract["required_parent_state"]:
        blockers.append("PARENT_NOT_PASS")
    if int(parent.get("mutation_count", -1)) != int(contract["required_parent_mutation_count"]):
        blockers.append("PARENT_MUTATION_COUNT_INVALID")
    if snapshot_before.get("runtime_active") is not False:
        blockers.append("RUNTIME_ALREADY_ACTIVE")
    if snapshot_before.get("formal_ledger_bound") is not False:
        blockers.append("FORMAL_LEDGER_ALREADY_BOUND")
    if float(scalar(telegram_before, "closed_count", "closed", default=-1)) != 0:
        blockers.append("TELEGRAM_NOT_ZERO_EPOCH")
    if float(scalar(telegram_before, "pnl_r", "net_r", default=-1)) != 0.0:
        blockers.append("TELEGRAM_PNL_NOT_ZERO")

    candidates, inspected = discover_unit(contract)
    if len(candidates) != 1:
        blockers.append(f"SHADOW_UNIT_COUNT_{len(candidates)}")
    if blockers:
        payload = {
            "state": "HOLD", "blockers": blockers, "blocker_count": len(blockers), "mutation_count": 0,
            "resolved_shadow_unit_count": len(candidates), "candidates": candidates, "inspected": inspected,
            "next_stage": "R7.3B4W_DIAGNOSE_START_AUTHORITY"
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    unit = candidates[0]["unit"]
    backup_root = Path(contract["backup_root"])
    backup_root.mkdir(parents=True, exist_ok=True)
    receipt = backup_root / f"{time.time_ns()}.json"
    ledger_before = sha256(ledger_path)
    start_epoch = int(time.time())
    was_active = run(["systemctl", "is-active", unit]).stdout.strip() == "active"
    mutation_count = 0
    rollback_performed = False

    try:
        atomic_json(receipt, {"unit": unit, "was_active": was_active, "ledger_sha256": ledger_before, "snapshot": snapshot_before})
        if not was_active:
            p = run(["systemctl", "start", unit])
            if p.returncode != 0:
                raise RuntimeError("SHADOW_UNIT_START_FAILED:" + p.stderr[-400:])
            mutation_count = 1
        time.sleep(int(contract["settle_seconds"]))
        unit_active = run(["systemctl", "is-active", unit]).stdout.strip() == "active"
        if not unit_active:
            raise RuntimeError("SHADOW_UNIT_NOT_ACTIVE")
        errors = journal_error_count(unit, start_epoch)
        if errors:
            raise RuntimeError(f"SHADOW_RUNTIME_ERRORS:{errors}")

        snapshot_after = read_json(snapshot_path)
        telegram_after = read_json(telegram_path)
        alimi_status, alimi = fetch_json(contract["alimi_endpoint"])
        ledger_after = sha256(ledger_path)

        runtime_active = snapshot_after.get("runtime_active") is True
        formal_bound = snapshot_after.get("formal_ledger_bound") is True
        order_value = str(scalar(snapshot_after, "order", "order_authority", default=scalar(telegram_after, "order", default=""))).lower()
        exec_value = str(scalar(snapshot_after, "exec", "execution_authority", default=scalar(telegram_after, "exec", default=""))).lower()
        paper_open = int(scalar(snapshot_after, "paper_open", default=scalar(telegram_after, "paper_open", default=0)) or 0)
        live_open = int(scalar(snapshot_after, "live_open", default=scalar(telegram_after, "live_open", default=0)) or 0)

        checks = {
            "runtime_active": runtime_active,
            "formal_ledger_bound": formal_bound,
            "formal_ledger_change_count": 0 if ledger_after == ledger_before else 1,
            "order_blocked": order_value in {"blocked", "false", "none"} or "block" in order_value,
            "execution_none": exec_value in {"none", "false", "disabled", ""},
            "paper_open": paper_open,
            "live_open": live_open,
            "alimi_http_status": alimi_status,
        }
        if not checks["runtime_active"]:
            raise RuntimeError("RUNTIME_ACTIVE_NOT_CONFIRMED")
        if checks["formal_ledger_bound"]:
            raise RuntimeError("FORMAL_LEDGER_BOUND_UNEXPECTED")
        if checks["formal_ledger_change_count"] != 0:
            raise RuntimeError("FORMAL_LEDGER_CHANGED")
        if not checks["order_blocked"] or not checks["execution_none"]:
            raise RuntimeError("ORDER_OR_EXECUTION_AUTHORITY_OPEN")
        if paper_open != 0 or live_open != 0:
            raise RuntimeError("PAPER_OR_LIVE_POSITION_OPEN")
        if alimi_status != 200:
            raise RuntimeError(f"ALIMI_HTTP_{alimi_status}")

        payload = {
            "schema": "q4r3_exact25_r73b4w_zero_epoch_shadow_start_canary_status_v1",
            "state": "PASS", "blockers": [], "blocker_count": 0,
            "mutation_count": mutation_count, "rollback_performed": False,
            "resolved_shadow_unit_count": 1, "shadow_unit": unit,
            "unit_active_after_start": True, "shadow_runtime_error_count": 0,
            "runtime_active": True, "formal_ledger_bound": False,
            "formal_ledger_change_count": 0, "order_blocked": True,
            "execution_none": True, "paper_open": 0, "live_open": 0,
            "epoch_closed": int(scalar(snapshot_after, "closed_count", "closed", default=0) or 0),
            "pnl_r": float(scalar(snapshot_after, "pnl_r", "net_r", default=0.0) or 0.0),
            "telegram_closed_count": int(scalar(telegram_after, "closed_count", "closed", default=0) or 0),
            "telegram_pnl_r": float(scalar(telegram_after, "pnl_r", "net_r", default=0.0) or 0.0),
            "alimi_http_status": alimi_status,
            "rollback_ready": receipt.is_file(),
            "next_stage": contract["next_stage"],
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        if mutation_count and not was_active:
            run(["systemctl", "stop", unit])
            rollback_performed = True
        payload = {
            "schema": "q4r3_exact25_r73b4w_zero_epoch_shadow_start_canary_status_v1",
            "state": "HOLD", "blockers": [str(exc)], "blocker_count": 1,
            "mutation_count": mutation_count, "rollback_performed": rollback_performed,
            "resolved_shadow_unit_count": 1, "shadow_unit": unit,
            "runtime_active": False, "next_stage": "R7.3B4W_DIAGNOSE_START_CANARY"
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
