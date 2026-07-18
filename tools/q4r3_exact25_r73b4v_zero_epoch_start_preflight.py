#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

ERROR_RE = re.compile(r"Traceback|\bERROR\b|Exception|NameError|TypeError|AttributeError|SyntaxError", re.I)
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
EMPTY_ZERO_VALUES = (None, "", "-", "—", "–")


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"NOT_JSON_OBJECT:{path}")
    return payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    temp = Path(raw)
    try:
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.chmod(0o644)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def first_present(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def deep_first(payload: Any, *keys: str, default: Any = None) -> Any:
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                return payload[key]
        for value in payload.values():
            found = deep_first(value, *keys, default=None)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = deep_first(value, *keys, default=None)
            if found is not None:
                return found
    return default


def number(value: Any, default: float = float("nan")) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    match = NUMBER_RE.search(str(value))
    return float(match.group(0)) if match else default


def zero(value: Any, allow_empty: bool = False) -> bool:
    if allow_empty and value in EMPTY_ZERO_VALUES:
        return True
    parsed = number(value)
    return parsed == 0.0


def none_value(value: Any) -> bool:
    return value in (None, "", {}, []) or str(value).strip().lower() in {"none", "null", "{}", "[]"}


def command_count(source: str, commands: list[str]) -> int:
    return sum(source.count(command) for command in commands)


def fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    probe = f"{url}{'&' if '?' in url else '?'}preflight={time.time_ns()}"
    command = [
        "curl", "-sS", "-L", "--max-time", "15",
        "-H", "Cache-Control: no-cache",
        "-w", "\n%{http_code}",
    ]
    if url.startswith("https://alimi.z-os.vip/"):
        command.extend(["--resolve", "alimi.z-os.vip:443:127.0.0.1"])
    command.append(probe)
    result = run(command, timeout=20)
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


def semantic_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "closed": deep_first(payload, "closed_count", "closed", default=None),
        "recent_rows": deep_first(payload, "recent_rows", "rows", default=None),
        "last12": deep_first(payload, "last12_r", "last12", default=None),
        "winrate": deep_first(payload, "winrate_pct", "wr_pct", "wr", "winrate", "win_rate", default=None),
        "ev": deep_first(payload, "ev_r", "ev", "expectancy_r", "expectancy", default=None),
        "pnl": deep_first(payload, "pnl_r", "net_r", "pnl", default=None),
        "last_close": deep_first(payload, "last_close", "last_closed", default=None),
        "epoch": deep_first(payload, "epoch", "epoch_id", default=None),
        "runtime_active": deep_first(payload, "runtime_active", default=None),
        "formal_ledger_bound": deep_first(payload, "formal_ledger_bound", default=None),
    }


def zero_metric_blockers(
    prefix: str,
    metrics: dict[str, Any],
    require_last_close: bool,
    allow_empty_as_zero: bool = False,
) -> list[str]:
    blockers: list[str] = []
    for name in ("closed", "recent_rows", "last12", "winrate", "ev", "pnl"):
        if not zero(metrics[name], allow_empty=allow_empty_as_zero):
            blockers.append(f"{prefix}_{name.upper()}_NOT_ZERO:{metrics[name]}")
    if require_last_close and not none_value(metrics["last_close"]):
        blockers.append(f"{prefix}_LAST_CLOSE_NOT_NONE:{metrics['last_close']}")
    return blockers


def active_legacy_units(tokens: list[str]) -> list[str]:
    commands = (
        ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"],
        ["systemctl", "list-units", "--type=timer", "--state=active", "--no-legend", "--no-pager"],
    )
    lines: list[str] = []
    for command in commands:
        result = run(command)
        if result.returncode == 0:
            lines.extend(result.stdout.splitlines())
    lowered = [token.lower() for token in tokens]
    return sorted({line.strip() for line in lines if any(token in line.lower() for token in lowered)})


def journal_errors(unit: str) -> list[str]:
    since = run(["systemctl", "show", unit, "-p", "ActiveEnterTimestamp", "--value"]).stdout.strip()
    command = ["journalctl", "-u", unit, "--no-pager", "-o", "cat"]
    if since:
        command.extend(["--since", since])
    else:
        command.extend(["-n", "100"])
    result = run(command)
    return [line for line in result.stdout.splitlines() if ERROR_RE.search(line)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(args.contract)
    parent_path = Path(contract["parent_status"])
    telegram_path = Path(contract["telegram_artifact"])
    snapshot_path = Path(contract["shadow_snapshot"])
    ledger_path = Path(contract["formal_ledger"])
    source_path = Path(contract["telegram_source"])
    view_path = Path(contract["view_index"])
    unit = str(contract["telegram_unit"])
    endpoint_url = str(contract["alimi_endpoint"])
    blockers: list[str] = []

    required = (parent_path, telegram_path, snapshot_path, source_path, view_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        blockers.append("REQUIRED_INPUT_MISSING:" + ",".join(missing))
        result = {
            "schema": "q4r3_exact25_r73b4v_zero_epoch_start_preflight_status_v1",
            "state": "HOLD",
            "blockers": blockers,
            "blocker_count": len(blockers),
            "mutation_count": 0,
            "next_stage": "R7.3B4V_DIAGNOSE",
        }
        atomic_json(args.status, result)
        print(json.dumps(result, sort_keys=True))
        return 2

    parent = read_json(parent_path)
    source = source_path.read_text(encoding="utf-8", errors="strict")
    view = view_path.read_text(encoding="utf-8", errors="strict")
    snapshot_before = read_json(snapshot_path)
    telegram_before = read_json(telegram_path)
    ledger_before = sha256(ledger_path) if ledger_path.is_file() else ""

    if parent.get("state") != "PASS":
        blockers.append(f"B4U9_PARENT_STATE:{parent.get('state')}")
    if int(parent.get("mutation_count", -1)) != 1:
        blockers.append(f"B4U9_PARENT_MUTATION_COUNT:{parent.get('mutation_count')}")
    if parent.get("runtime_active") is not False:
        blockers.append(f"B4U9_PARENT_RUNTIME_ACTIVE:{parent.get('runtime_active')}")
    if int(parent.get("formal_ledger_change_count", -1)) != 0:
        blockers.append(f"B4U9_PARENT_LEDGER_CHANGE:{parent.get('formal_ledger_change_count')}")

    required_commands = [str(item) for item in contract["required_commands"]]
    source_command_count = command_count(source, required_commands)
    if source_command_count < len(required_commands):
        blockers.append(f"TELEGRAM_COMMAND_COUNT:{source_command_count}")
    if str(contract["required_telegram_boundary_marker"]) not in source:
        blockers.append("TELEGRAM_B4U9_BOUNDARY_MISSING")
    compile_result = run(["python3", "-m", "py_compile", str(source_path)])
    if compile_result.returncode != 0:
        blockers.append("TELEGRAM_COMPILE_FAILED:" + compile_result.stderr[-300:])
    unit_active = run(["systemctl", "is-active", unit]).stdout.strip()
    if unit_active != "active":
        blockers.append(f"TELEGRAM_UNIT_NOT_ACTIVE:{unit_active}")
    errors = journal_errors(unit) if unit_active == "active" else []
    if errors:
        blockers.append("TELEGRAM_RUNTIME_ERRORS:" + " | ".join(errors[-5:]))

    telegram_metrics_before = semantic_metrics(telegram_before)
    blockers.extend(zero_metric_blockers("TELEGRAM", telegram_metrics_before, require_last_close=True))
    if telegram_metrics_before["runtime_active"] is not False:
        blockers.append(f"TELEGRAM_RUNTIME_ACTIVE:{telegram_metrics_before['runtime_active']}")
    if telegram_metrics_before["formal_ledger_bound"] is not False:
        blockers.append(f"TELEGRAM_LEDGER_BOUND:{telegram_metrics_before['formal_ledger_bound']}")

    snapshot_metrics_before = semantic_metrics(snapshot_before)
    if snapshot_metrics_before["runtime_active"] is not False:
        blockers.append(f"SNAPSHOT_RUNTIME_ACTIVE:{snapshot_metrics_before['runtime_active']}")
    if snapshot_metrics_before["formal_ledger_bound"] is not False:
        blockers.append(f"SNAPSHOT_LEDGER_BOUND:{snapshot_metrics_before['formal_ledger_bound']}")
    for key in ("candidate", "candidate_count", "admitted", "admitted_count", "open", "open_count", "closed", "closed_count", "shadow_open", "paper_open", "live_open"):
        value = first_present(snapshot_before, key, default=None)
        if value is not None and not zero(value):
            blockers.append(f"SNAPSHOT_{key.upper()}_NOT_ZERO:{value}")

    http_status_before, alimi_before = fetch_json(endpoint_url)
    if http_status_before != 200:
        blockers.append(f"ALIMI_HTTP_STATUS:{http_status_before}")
    alimi_metrics_before = semantic_metrics(alimi_before)
    blockers.extend(
        zero_metric_blockers(
            "ALIMI",
            alimi_metrics_before,
            require_last_close=False,
            allow_empty_as_zero=True,
        )
    )

    forbidden_markers = [str(item) for item in contract["forbidden_view_markers"]]
    view_legacy_marker_count = sum(view.count(marker) for marker in forbidden_markers)
    if view_legacy_marker_count:
        blockers.append(f"VIEW_LEGACY_MARKER_COUNT:{view_legacy_marker_count}")
    if str(contract["required_view_source_label"]) not in view:
        blockers.append("VIEW_CANONICAL_SOURCE_LABEL_MISSING")
    configured_writer_ready = "configured=7" in view and "active=0" in view
    if not configured_writer_ready:
        blockers.append("VIEW_WRITERS7_NOT_READY")
    expected_writer_ids = set(str(key) for key in contract["expected_writer_registry"])
    missing_writer_ids = sorted(writer_id for writer_id in expected_writer_ids if writer_id not in view)
    if missing_writer_ids:
        blockers.append("VIEW_WRITER_IDS_MISSING:" + ",".join(missing_writer_ids))

    legacy_units = active_legacy_units([str(item) for item in contract["forbidden_unit_tokens"]])
    if legacy_units:
        blockers.append("LEGACY_OVERWRITER_UNITS_ACTIVE:" + " | ".join(legacy_units))

    time.sleep(2)
    telegram_after = read_json(telegram_path)
    snapshot_after = read_json(snapshot_path)
    http_status_after, alimi_after = fetch_json(endpoint_url)
    telegram_metrics_after = semantic_metrics(telegram_after)
    snapshot_metrics_after = semantic_metrics(snapshot_after)
    alimi_metrics_after = semantic_metrics(alimi_after)

    if telegram_metrics_before != telegram_metrics_after:
        blockers.append("TELEGRAM_SEMANTIC_STATE_CHANGED_DURING_PREFLIGHT")
    if snapshot_metrics_before != snapshot_metrics_after:
        blockers.append("SNAPSHOT_SEMANTIC_STATE_CHANGED_DURING_PREFLIGHT")
    if http_status_after != 200 or alimi_metrics_before != alimi_metrics_after:
        blockers.append("ALIMI_SEMANTIC_STATE_CHANGED_DURING_PREFLIGHT")
    if telegram_metrics_after["epoch"] is not None and alimi_metrics_after["epoch"] is not None:
        if str(telegram_metrics_after["epoch"]) != str(alimi_metrics_after["epoch"]):
            blockers.append(
                f"SURFACE_EPOCH_MISMATCH:{telegram_metrics_after['epoch']}!={alimi_metrics_after['epoch']}"
            )
    formal_ledger_change_count = 0
    if ledger_before and sha256(ledger_path) != ledger_before:
        formal_ledger_change_count = 1
        blockers.append("FORMAL_LEDGER_CHANGED_DURING_PREFLIGHT")

    state = "PASS" if not blockers else "HOLD"
    result = {
        "schema": "q4r3_exact25_r73b4v_zero_epoch_start_preflight_status_v1",
        "state": state,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "mutation_count": 0,
        "parent_state": parent.get("state"),
        "telegram_command_count": source_command_count,
        "telegram_compile_ok": compile_result.returncode == 0,
        "telegram_unit_active": unit_active == "active",
        "telegram_runtime_error_count": len(errors),
        "telegram_closed_count": number(telegram_metrics_after["closed"], 0.0),
        "telegram_recent_rows": number(telegram_metrics_after["recent_rows"], 0.0),
        "telegram_last12_r": number(telegram_metrics_after["last12"], 0.0),
        "telegram_winrate_pct": number(telegram_metrics_after["winrate"], 0.0),
        "telegram_ev_r": number(telegram_metrics_after["ev"], 0.0),
        "telegram_pnl_r": number(telegram_metrics_after["pnl"], 0.0),
        "telegram_last_close": "none" if none_value(telegram_metrics_after["last_close"]) else telegram_metrics_after["last_close"],
        "alimi_http_status": http_status_after,
        "alimi_closed_count": number(alimi_metrics_after["closed"], 0.0),
        "alimi_recent_rows": number(alimi_metrics_after["recent_rows"], 0.0),
        "alimi_last12_r": number(alimi_metrics_after["last12"], 0.0),
        "alimi_winrate_pct": number(alimi_metrics_after["winrate"], 0.0),
        "alimi_ev_r": number(alimi_metrics_after["ev"], 0.0),
        "alimi_pnl_r": number(alimi_metrics_after["pnl"], 0.0),
        "configured_writer_count": 7 if configured_writer_ready else 0,
        "active_writer_count": 0 if configured_writer_ready else None,
        "writer_registry_ids": sorted(expected_writer_ids),
        "runtime_active": snapshot_metrics_after["runtime_active"],
        "formal_ledger_bound": snapshot_metrics_after["formal_ledger_bound"],
        "formal_ledger_change_count": formal_ledger_change_count,
        "legacy_view_marker_count": view_legacy_marker_count,
        "legacy_overwriter_unit_count": len(legacy_units),
        "semantic_stability_samples": 2,
        "next_stage": contract["next_stage"] if state == "PASS" else "R7.3B4V_DIAGNOSE",
    }
    atomic_json(args.status, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
