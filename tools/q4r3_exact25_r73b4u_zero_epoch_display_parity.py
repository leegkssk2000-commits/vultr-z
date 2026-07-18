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

CANONICAL_SOURCE = "shadow_aggregate_snapshot/latest.json"
EXPECTED_WRITERS = {
    "VV": "vwap_revert",
    "TR": "trend_rider",
    "LS": "liquidity_sweep",
    "MO": "momentum_driver",
    "VB": "vol_breakout",
    "MS": "market_structure",
    "SR": "support_resistance",
}
CONFIG_COUNT_KEYS = {"writer_count": 7, "configured_writer_count": 7}
CHART_KEYS = {
    "chart", "chart_data", "chart_rows_data", "candles", "ohlc", "ohlcv",
    "price_series", "price_points", "trace_series", "sparkline", "series", "market_trace"
}
STALE_MARKERS = (
    "q4r3_shadow_closed_ledger_latest.json",
    "telegram_pos_status_latest.json",
    "forward_r_ledger.jsonl",
    "SL_TOUCH_CLOSED",
    "TP_TOUCH_CLOSED",
)
ZERO_KEYS = {
    "sample_count", "closed_count", "closed", "rows", "row_count", "rows_count",
    "recent_rows", "wins", "losses", "breakeven", "candidate", "candidate_count",
    "admitted", "admitted_count", "open", "open_count", "active_count", "shadow_open",
    "paper_open", "live_open", "active_writer_count", "last12", "last12_r", "ev", "ev_r",
    "expectancy_r", "pnl", "pnl_r", "net_r", "total_r", "gross_r", "wr", "wr_pct",
    "winrate", "winrate_pct", "win_rate", "chart_rows", "chart_point_count"
}
SOURCE_KEYS = {"src", "source", "display_source", "ledger_source", "source_path", "source_label"}


def norm(key: str) -> str:
    return key.strip().lower().replace("-", "_").replace(" ", "_")


def run(command: list[str], check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check, timeout=timeout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.chmod(0o644)
        os.replace(tmp, path)
        path.chmod(0o644)
    finally:
        tmp.unlink(missing_ok=True)


def fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    probe = f"{url}{'&' if '?' in url else '?'}r73b4u={time.time_ns()}"
    command = [
        "curl", "-sS", "-L", "--max-time", "15", "-H", "Cache-Control: no-cache",
        "-w", "\n%{http_code}"
    ]
    if url.startswith("https://alimi.z-os.vip/"):
        command.extend(["--resolve", "alimi.z-os.vip:443:127.0.0.1"])
    command.append(probe)
    result = run(command, check=False, timeout=20)
    body, _, raw_code = result.stdout.rpartition("\n")
    try:
        code = int(raw_code or 0)
    except ValueError:
        code = 0
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}
    return code, payload if isinstance(payload, dict) else {}


def trade_like_list(value: list[Any]) -> bool:
    for item in value:
        if isinstance(item, dict):
            keys = {norm(str(key)) for key in item}
            if sum(token in keys for token in ("symbol", "strategy", "side", "reason", "pnl_r")) >= 2:
                return True
    return False


def residuals(payload: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = norm(str(key))
            child = f"{path}.{key}"
            if normalized in SOURCE_KEYS or normalized.endswith("_source"):
                if value != CANONICAL_SOURCE:
                    found.append(f"STALE_SOURCE:{child}={value}")
            if normalized in {"last_close", "last_closed", "last_trade", "last_event"}:
                if str(value).strip().lower() not in {"", "none", "null"}:
                    found.append(f"STALE_LAST_EVENT:{child}={value}")
            if normalized in CHART_KEYS and isinstance(value, list) and value:
                found.append(f"STALE_CHART_DATA:{child}:{len(value)}")
            if normalized in CONFIG_COUNT_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool):
                if int(value) != CONFIG_COUNT_KEYS[normalized]:
                    found.append(f"CONFIG_COUNT_MISMATCH:{child}={value}")
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                if (
                    normalized in ZERO_KEYS or
                    (normalized.endswith("_count") and normalized not in CONFIG_COUNT_KEYS) or
                    normalized.endswith("_pct") or normalized.endswith("_r")
                ) and float(value) != 0.0:
                    found.append(f"NONZERO_METRIC:{child}={value}")
            found.extend(residuals(value, child))
        return found
    if isinstance(payload, list):
        if payload and trade_like_list(payload):
            found.append(f"STALE_TRADE_ROWS:{path}:{len(payload)}")
        for index, value in enumerate(payload):
            found.extend(residuals(value, f"{path}[{index}]"))
        return found
    if isinstance(payload, str):
        for marker in STALE_MARKERS:
            if marker in payload:
                found.append(f"STALE_MARKER:{path}:{marker}")
    return found


def writer_registry_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = payload.get("writers")
    if not isinstance(rows, list) or len(rows) != 7:
        return [f"WRITER_REGISTRY_COUNT={0 if not isinstance(rows, list) else len(rows)}"]
    actual: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            errors.append("WRITER_ROW_NOT_OBJECT")
            continue
        writer_id = str(row.get("writer_id", ""))
        strategy = str(row.get("strategy", ""))
        if writer_id in actual:
            errors.append(f"WRITER_DUPLICATE={writer_id}")
        actual[writer_id] = strategy
        if row.get("state") != "PREBIND" or row.get("active") is not False:
            errors.append(f"WRITER_NOT_PREBIND={writer_id}")
        if int(row.get("closed_count", -1)) != 0 or float(row.get("pnl_r", -1.0)) != 0.0:
            errors.append(f"WRITER_NOT_ZERO={writer_id}")
    if actual != EXPECTED_WRITERS:
        errors.append(f"WRITER_REGISTRY_MISMATCH={actual}")
    if int(payload.get("writer_count", -1)) != 7 or int(payload.get("configured_writer_count", -1)) != 7:
        errors.append("WRITER_CONFIG_COUNT_INVALID")
    if int(payload.get("active_writer_count", -1)) != 0:
        errors.append("ACTIVE_WRITER_COUNT_NONZERO")
    return errors


def restore(path: Path, backup: Path | None, existed: bool) -> None:
    if existed and backup and backup.exists():
        shutil.copy2(backup, path)
    elif not existed:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--adapter-source", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    snapshot = Path(contract["source_snapshot"])
    parent_status = Path(contract["parent_status"])
    adapter_target = Path(contract["adapter_script"])
    runtime = Path(contract["adapter_runtime"])
    alimi_output = Path(contract["alimi_output"])
    telegram_output = Path(contract["telegram_output"])
    ledger = Path(contract["formal_ledger"])
    alimi_template = runtime / "templates/alimi_legacy_schema_template.json"
    telegram_template = runtime / "templates/telegram_legacy_schema_template.json"
    backup_root = runtime / "rollback/r73b4u"
    backup_root.mkdir(parents=True, exist_ok=True)
    required = [snapshot, parent_status, adapter_target, args.adapter_source, alimi_template, telegram_template]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        atomic_json(args.status, {"state": "HOLD", "blockers": ["REQUIRED_INPUT_MISSING:" + ",".join(missing)], "mutation_count": 0})
        return 2
    snap = json.loads(snapshot.read_text(encoding="utf-8"))
    parent = json.loads(parent_status.read_text(encoding="utf-8"))
    blockers: list[str] = []
    if parent.get("state") != "PASS" or parent.get("rollback_performed") is not False:
        blockers.append("R73B4T_PARENT_INVALID")
    if snap.get("sample_count") != 0 or snap.get("closed_count") != 0 or snap.get("runtime_active") is not False:
        blockers.append("SNAPSHOT_NOT_ZERO_PREBIND")
    if snap.get("formal_ledger_bound") is not False:
        blockers.append("FORMAL_LEDGER_BOUND")
    if blockers:
        atomic_json(args.status, {"state": "HOLD", "blockers": blockers, "mutation_count": 0})
        return 2
    ledger_before = sha256(ledger) if ledger.is_file() else ""
    paths = (adapter_target, alimi_output, telegram_output)
    backup_map: dict[Path, tuple[Path | None, bool]] = {}
    for path in paths:
        existed = path.exists()
        backup = backup_root / path.as_posix().lstrip("/") if existed else None
        if existed and backup:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        backup_map[path] = (backup, existed)
    mutations: list[str] = []
    rollback_performed = False
    try:
        shutil.copy2(args.adapter_source, adapter_target)
        adapter_target.chmod(0o755)
        mutations.append("STRICT_DISPLAY_ADAPTER_INSTALLED")
        result = run([
            str(adapter_target), "--snapshot", str(snapshot),
            "--alimi-template", str(alimi_template), "--telegram-template", str(telegram_template),
            "--alimi-output", str(alimi_output), "--telegram-output", str(telegram_output)
        ], check=False)
        if result.returncode != 0:
            raise RuntimeError("STRICT_ADAPTER_RUN_FAILED:" + result.stderr[-300:])
        mutations.extend([
            "ALIMI_RESIDUALS_PURGED", "TELEGRAM_RESIDUALS_PURGED",
            "VIEW_CHART_ZEROED", "WRITERS7_PREBIND_PROJECTED", "TEAM_LANE_CLEARED"
        ])
        run(["systemctl", "start", contract["display_service"]])
        run(["systemctl", "restart", contract["telegram_unit"]])
        mutations.extend(["DISPLAY_SERVICE_REFRESHED", "TELEGRAM_RESTARTED"])
        time.sleep(2)
        http_status, alimi = fetch_json(contract["alimi_endpoint"])
        telegram = json.loads(telegram_output.read_text(encoding="utf-8"))
        alimi_residuals = residuals(alimi)
        telegram_residuals = residuals(telegram)
        alimi_writer_errors = writer_registry_errors(alimi)
        telegram_writer_errors = writer_registry_errors(telegram)
        if http_status != 200:
            raise RuntimeError(f"ALIMI_ENDPOINT_HTTP_{http_status}")
        if alimi_residuals:
            raise RuntimeError("ALIMI_RESIDUALS:" + "|".join(alimi_residuals[:12]))
        if telegram_residuals:
            raise RuntimeError("TELEGRAM_RESIDUALS:" + "|".join(telegram_residuals[:12]))
        if alimi_writer_errors:
            raise RuntimeError("ALIMI_WRITERS7:" + "|".join(alimi_writer_errors[:12]))
        if telegram_writer_errors:
            raise RuntimeError("TELEGRAM_WRITERS7:" + "|".join(telegram_writer_errors[:12]))
        if alimi.get("source_snapshot_sha256") != telegram.get("source_snapshot_sha256"):
            raise RuntimeError("DISPLAY_SNAPSHOT_HASH_MISMATCH")
        if alimi.get("epoch_id") != telegram.get("epoch_id"):
            raise RuntimeError("DISPLAY_EPOCH_MISMATCH")
        if ledger_before and sha256(ledger) != ledger_before:
            raise RuntimeError("FORMAL_LEDGER_CHANGED")
        payload = {
            "schema": "q4r3_exact25_r73b4u_zero_epoch_display_parity_status_v2",
            "state": "PASS", "blockers": [], "blocker_count": 0,
            "mutation_count": len(mutations), "mutations": mutations,
            "rollback_performed": False, "endpoint_http_status": http_status,
            "alimi_residual_count": 0, "telegram_residual_count": 0,
            "alimi_closed_count": alimi.get("closed_count"),
            "telegram_closed_count": telegram.get("closed_count"),
            "alimi_rows": alimi.get("rows"), "telegram_recent_rows": telegram.get("recent_rows"),
            "alimi_pnl_r": alimi.get("pnl_r"), "telegram_pnl_r": telegram.get("pnl_r"),
            "writer_registry_count": len(alimi.get("writers", [])),
            "active_writer_count": alimi.get("active_writer_count"),
            "chart_point_count": alimi.get("chart_point_count"),
            "team_lane_count": len(alimi.get("team_lanes", [])),
            "source_snapshot_sha256": alimi.get("source_snapshot_sha256"),
            "formal_ledger_change_count": 0, "runtime_active": False,
            "next_stage": contract["next_stage"]
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        blockers.append(str(exc))
        rollback_performed = True
        for path, (backup, existed) in backup_map.items():
            try:
                restore(path, backup, existed)
            except OSError:
                blockers.append(f"ROLLBACK_FILE_FAILED:{path}")
        run(["systemctl", "start", contract["display_service"]], check=False)
        run(["systemctl", "restart", contract["telegram_unit"]], check=False)
        payload = {
            "schema": "q4r3_exact25_r73b4u_zero_epoch_display_parity_status_v2",
            "state": "HOLD", "blockers": blockers, "blocker_count": len(blockers),
            "mutation_count": len(mutations), "mutations": mutations,
            "rollback_performed": rollback_performed, "runtime_active": False,
            "next_stage": "R7.3B4U_DIAGNOSE"
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
