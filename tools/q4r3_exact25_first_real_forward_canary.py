from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Set, Tuple

EXPECTED_EPOCH = "EXACT25_EDGE_V1"
EXPECTED_NAMESPACE = "EXACT25_EDGE_V1"
EXPECTED_WRITER_SHA256 = "d8120a2b8b4d7ed2ac4d37734eb4d6e37c973dfb163572a6553bd91a13b19e50"
_STOP = False

ID_KEYS = (
    "event_id", "shadow_id", "trade_id", "position_id", "request_id",
    "last_close_event_id", "last_closed_shadow_id",
)
STRATEGY_KEYS = ("strategy_id", "strategy", "strategy_name", "last_strategy")
SYMBOL_KEYS = ("symbol", "asset_symbol", "last_symbol")
SIDE_KEYS = ("side", "last_side")
ENTRY_TS_KEYS = ("entry_ts", "open_ts", "opened_at")
EXIT_TS_KEYS = ("exit_ts", "closed_at", "close_ts")
ENTRY_PRICE_KEYS = ("entry_price", "entry", "avg_entry", "last_entry")
STOP_PRICE_KEYS = ("stop_price", "sl", "stop_loss", "initial_stop_price", "last_sl")
PNL_KEYS = ("realized_pnl_usdt", "realized_pnl", "pnl_usdt", "pnl")
R_KEYS = ("realized_R", "realized_r", "pnl_r", "effective_pnl_r", "last_close_pnl_r")
RISK_KEYS = ("initial_risk_usdt", "risk_usdt", "initial_risk", "risk_amount")
QTY_KEYS = ("qty", "quantity", "size", "base_qty")
NOTIONAL_KEYS = ("notional_usdt", "notional", "position_notional_usdt")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return number
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_time(float(text))
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def atomic_jsonl_append(path: Path, row: Mapping[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    event_id = str(row.get("event_id") or "")
    existing: List[str] = []
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in existing:
            try:
                prior = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(prior, dict) and str(prior.get("event_id") or "") == event_id:
                return False
    text = "\n".join(existing + [json.dumps(dict(row), ensure_ascii=False, sort_keys=True)]) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return True


def first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def fnum(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def walk_dicts(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def closed_marker(row: Mapping[str, Any]) -> bool:
    for key in ("closed", "is_closed", "shadow_closed", "closed_phase_written", "actual_close_written"):
        if row.get(key) is True:
            return True
    status = str(first(row, ("status", "state", "position_status", "last_close_status")) or "").upper()
    if any(token in status for token in ("CLOSED", "EXITED", "CLOSE_WRITTEN", "DONE")):
        return True
    return first(row, EXIT_TS_KEYS) is not None and first(row, STRATEGY_KEYS) is not None


def event_key(row: Mapping[str, Any]) -> str | None:
    value = first(row, ID_KEYS)
    if value not in (None, ""):
        return str(value)
    strategy = first(row, STRATEGY_KEYS)
    symbol = first(row, SYMBOL_KEYS)
    exit_ts = first(row, EXIT_TS_KEYS)
    if strategy and symbol and exit_ts:
        raw = f"{strategy}|{symbol}|{first(row, SIDE_KEYS)}|{exit_ts}"
        return "derived:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return None


def extract_closed_events(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}
    found: Dict[str, Dict[str, Any]] = {}
    for row in walk_dicts(payload):
        if not closed_marker(row):
            continue
        key = event_key(row)
        if not key:
            continue
        candidate = dict(row)
        candidate["_source_path"] = str(path)
        prior = found.get(key)
        if prior is None or len(candidate) > len(prior):
            found[key] = candidate
    return found


def row_fingerprint(row: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_overlay_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for row in walk_dicts(payload):
        if first(row, STRATEGY_KEYS) is None:
            continue
        if first(row, R_KEYS) is None and first(row, PNL_KEYS) is None:
            continue
        rows.append(dict(row))
    return rows


def load_owner_map(path: Path) -> Dict[str, str]:
    payload = load_json(path)
    entries = payload.get("strategies")
    if not isinstance(entries, list) or len(entries) != 25:
        raise RuntimeError("OWNER_MANIFEST_NOT_EXACT25")
    owners: Dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        strategy = str(entry.get("strategy_id") or "").strip()
        owner_sha = str(entry.get("owner_sha256") or entry.get("source_sha256") or "").strip()
        if strategy and len(owner_sha) == 64:
            owners[strategy] = owner_sha
    if len(owners) != 25:
        raise RuntimeError(f"OWNER_MAP_INCOMPLETE:{len(owners)}")
    return owners


def derive_initial_risk_usdt(row: Mapping[str, Any], event: Mapping[str, Any]) -> float | None:
    for source in (row, event):
        direct = fnum(first(source, RISK_KEYS))
        if direct is not None and direct > 0:
            return direct
    entry = fnum(first(row, ENTRY_PRICE_KEYS)) or fnum(first(event, ENTRY_PRICE_KEYS))
    stop = fnum(first(row, STOP_PRICE_KEYS)) or fnum(first(event, STOP_PRICE_KEYS))
    if entry is None or stop is None or entry <= 0 or entry == stop:
        return None
    qty = fnum(first(row, QTY_KEYS)) or fnum(first(event, QTY_KEYS))
    if qty is not None and qty > 0:
        return abs(entry - stop) * qty
    notional = fnum(first(row, NOTIONAL_KEYS)) or fnum(first(event, NOTIONAL_KEYS))
    if notional is not None and notional > 0:
        return notional * abs(entry - stop) / entry
    return None


def normalize_row(row: Mapping[str, Any], event: Mapping[str, Any], owners: Mapping[str, str]) -> Dict[str, Any]:
    strategy = str(first(row, STRATEGY_KEYS) or first(event, STRATEGY_KEYS) or "").strip()
    if strategy not in owners:
        raise RuntimeError(f"STRATEGY_NOT_IN_EXACT25:{strategy}")
    event_id = str(event_key(event) or event_key(row) or "").strip()
    if not event_id:
        raise RuntimeError("EVENT_ID_MISSING")
    entry_ts = first(row, ENTRY_TS_KEYS) or first(event, ENTRY_TS_KEYS)
    exit_ts = first(row, EXIT_TS_KEYS) or first(event, EXIT_TS_KEYS)
    entry_price = fnum(first(row, ENTRY_PRICE_KEYS)) or fnum(first(event, ENTRY_PRICE_KEYS))
    stop_price = fnum(first(row, STOP_PRICE_KEYS)) or fnum(first(event, STOP_PRICE_KEYS))
    realized_pnl = fnum(first(row, PNL_KEYS))
    if realized_pnl is None:
        realized_pnl = fnum(first(event, PNL_KEYS))
    initial_risk = derive_initial_risk_usdt(row, event)
    if initial_risk is None or initial_risk <= 0:
        raise RuntimeError("INITIAL_RISK_USDT_MISSING")
    if realized_pnl is None:
        raise RuntimeError("REALIZED_PNL_USDT_MISSING")
    computed_r = realized_pnl / initial_risk
    reported_r = fnum(first(row, R_KEYS))
    if reported_r is None:
        reported_r = fnum(first(event, R_KEYS))
    if reported_r is not None and abs(reported_r - computed_r) > max(1e-6, abs(computed_r) * 1e-5):
        raise RuntimeError(f"REALIZED_R_FORMULA_MISMATCH:reported={reported_r}:computed={computed_r}")
    entry_epoch = parse_time(entry_ts)
    exit_epoch = parse_time(exit_ts)
    exposure = None
    if entry_epoch is not None and exit_epoch is not None and exit_epoch >= entry_epoch:
        exposure = (exit_epoch - entry_epoch) / 60.0
    normalized = {
        "schema": "q4r3_exact25_first_real_forward_canary_row_v1",
        "canary": True,
        "epoch_id": EXPECTED_EPOCH,
        "measurement_namespace": EXPECTED_NAMESPACE,
        "event_id": event_id,
        "event_type": "CLOSED",
        "strategy_id": strategy,
        "owner_sha256": owners[strategy],
        "symbol": str(first(row, SYMBOL_KEYS) or first(event, SYMBOL_KEYS) or ""),
        "side": str(first(row, SIDE_KEYS) or first(event, SIDE_KEYS) or "").lower(),
        "regime": str(row.get("regime") or event.get("regime") or "unknown"),
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "initial_risk_usdt": initial_risk,
        "realized_pnl_usdt": realized_pnl,
        "realized_R": computed_r,
        "fee": fnum(row.get("fee")) or 0.0,
        "slippage": fnum(row.get("slippage")) or 0.0,
        "latency_ms": fnum(row.get("latency_ms")) or 0.0,
        "MFE_R": fnum(row.get("MFE_R") if "MFE_R" in row else row.get("mfe_r")),
        "MAE_R": fnum(row.get("MAE_R") if "MAE_R" in row else row.get("mae_r")),
        "time_exposure_min": exposure,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "source_close_path": str(event.get("_source_path") or ""),
        "captured_at": now_iso(),
    }
    required = ("symbol", "side", "entry_ts", "exit_ts", "entry_price", "stop_price")
    missing = [key for key in required if normalized.get(key) in (None, "")]
    if missing:
        raise RuntimeError("NORMALIZED_REQUIRED_FIELDS_MISSING:" + ",".join(missing))
    return normalized


def match_new_row(rows: Sequence[Mapping[str, Any]], event: Mapping[str, Any]) -> Mapping[str, Any]:
    strategy = str(first(event, STRATEGY_KEYS) or "")
    symbol = str(first(event, SYMBOL_KEYS) or "")
    event_id = str(event_key(event) or "")
    exact = [row for row in rows if str(event_key(row) or "") == event_id]
    if len(exact) == 1:
        return exact[0]
    compatible = [
        row for row in rows
        if str(first(row, STRATEGY_KEYS) or "") == strategy
        and (not symbol or str(first(row, SYMBOL_KEYS) or "") == symbol)
    ]
    if len(compatible) == 1:
        return compatible[0]
    raise RuntimeError(f"WRITER_NEW_ROW_MATCH_NOT_UNIQUE:exact={len(exact)}:compatible={len(compatible)}")


def backup_paths(paths: Sequence[Path], directory: Path) -> Dict[str, bool]:
    directory.mkdir(parents=True, exist_ok=True)
    existed: Dict[str, bool] = {}
    for index, path in enumerate(paths):
        key = f"{index}_{path.name}"
        existed[key] = path.exists()
        if path.exists():
            shutil.copy2(path, directory / key)
    atomic_json(directory / "manifest.json", {"paths": [str(path) for path in paths], "existed": existed})
    return existed


def restore_paths(paths: Sequence[Path], directory: Path) -> None:
    manifest = load_json(directory / "manifest.json")
    existed = manifest.get("existed") or {}
    for index, path in enumerate(paths):
        key = f"{index}_{path.name}"
        if existed.get(key) is True:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(directory / key, path)
        else:
            path.unlink(missing_ok=True)


def status_payload(state: str, started_at: str, heartbeat: int, writer_invocations: int, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema": "q4r3_exact25_first_real_forward_canary_status_v1",
        "state": state,
        "started_at": started_at,
        "updated_at": now_iso(),
        "pid": os.getpid(),
        "epoch_id": EXPECTED_EPOCH,
        "measurement_namespace": EXPECTED_NAMESPACE,
        "heartbeat_count": heartbeat,
        "writer_invocation_count": writer_invocations,
        "write_enabled": False,
        "canary_enabled": True,
        "activation_allowed": True,
        "shadow_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill_allowed": False,
    }
    payload.update(extra)
    return payload


def validate_environment() -> None:
    expected = {
        "Q4R3_EPOCH_ID": EXPECTED_EPOCH,
        "Q4R3_MEASUREMENT_NAMESPACE": EXPECTED_NAMESPACE,
        "Q4R3_SHADOW_ONLY": "1",
        "Q4R3_PAPER_ENABLED": "0",
        "Q4R3_LIVE_ENABLED": "0",
        "Q4R3_ORDER_ENABLED": "0",
        "Q4R3_HISTORICAL_BACKFILL_ALLOWED": "0",
        "Q4R3_SERVICE_STAGE": "FIRST_REAL_FORWARD_CANARY",
    }
    for key, value in expected.items():
        actual = os.environ.get(key)
        if actual != value:
            raise RuntimeError(f"ENVIRONMENT_GATE_MISMATCH:{key}:expected={value}:actual={actual}")


def validate_gate(path: Path) -> Dict[str, Any]:
    gate = load_json(path)
    required = {
        "epoch_id": EXPECTED_EPOCH,
        "measurement_namespace": EXPECTED_NAMESPACE,
        "shadow_only": True,
        "write_enabled": False,
        "canary_enabled": True,
        "activation_allowed": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill_allowed": False,
    }
    for key, expected in required.items():
        if gate.get(key) != expected:
            raise RuntimeError(f"GATE_MISMATCH:{key}:expected={expected!r}:actual={gate.get(key)!r}")
    return gate


def request_stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def run(args: argparse.Namespace) -> int:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    started_at = now_iso()
    started_epoch = parse_time(started_at) or time.time()
    heartbeat = 0
    writer_invocations = 0
    outputs = [args.writer_latest, args.writer_state, args.writer_overlay]
    try:
        validate_environment()
        validate_gate(args.gate)
        if sha256_file(args.writer) != args.writer_sha256:
            raise RuntimeError("WRITER_SHA_MISMATCH")
        owners = load_owner_map(args.manifest)
        baseline_closed: Set[str] = set()
        for source in args.close_source:
            baseline_closed.update(extract_closed_events(source))
        baseline_overlay = {row_fingerprint(row) for row in extract_overlay_rows(args.writer_overlay)}
        atomic_json(args.status, status_payload(
            "WAITING_REAL_FORWARD_OPEN_CLOSE", started_at, heartbeat, writer_invocations,
            baseline_closed_count=len(baseline_closed), baseline_overlay_row_count=len(baseline_overlay),
            close_sources=[str(path) for path in args.close_source],
        ))
        while not _STOP:
            validate_environment()
            validate_gate(args.gate)
            heartbeat += 1
            found: List[Tuple[str, Dict[str, Any]]] = []
            for source in args.close_source:
                for key, event in extract_closed_events(source).items():
                    if key in baseline_closed:
                        continue
                    exit_epoch = parse_time(first(event, EXIT_TS_KEYS))
                    if exit_epoch is not None and exit_epoch + 1 < started_epoch:
                        continue
                    found.append((key, event))
            if found:
                found.sort(key=lambda item: parse_time(first(item[1], EXIT_TS_KEYS)) or 0)
                event_id, event = found[0]
                transaction_dir = args.backup_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                paths_to_restore = outputs + [args.canary_ledger]
                backup_paths(paths_to_restore, transaction_dir)
                try:
                    before = {row_fingerprint(row) for row in extract_overlay_rows(args.writer_overlay)}
                    completed = subprocess.run(
                        [sys.executable, str(args.writer)],
                        cwd=str(args.root),
                        env=dict(os.environ),
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=args.writer_timeout_sec,
                        check=False,
                    )
                    writer_invocations += 1
                    if completed.returncode != 0:
                        raise RuntimeError(f"WRITER_EXIT_CODE:{completed.returncode}:{completed.stderr[-500:]}")
                    after_rows = extract_overlay_rows(args.writer_overlay)
                    new_rows = [row for row in after_rows if row_fingerprint(row) not in before]
                    if len(new_rows) != 1:
                        raise RuntimeError(f"WRITER_NEW_ROW_COUNT:{len(new_rows)}")
                    matched = match_new_row(new_rows, event)
                    normalized = normalize_row(matched, event, owners)
                    if normalized["event_id"] != event_id:
                        raise RuntimeError("EVENT_ID_NORMALIZATION_MISMATCH")
                    if not atomic_jsonl_append(args.canary_ledger, normalized):
                        raise RuntimeError("FIRST_CANARY_WRITE_DUPLICATE")
                    if atomic_jsonl_append(args.canary_ledger, normalized):
                        raise RuntimeError("REPLAY_DUPLICATE_NOT_REJECTED")
                    result = status_payload(
                        "PASS_FIRST_REAL_FORWARD_CANARY", started_at, heartbeat, writer_invocations,
                        event_id=event_id, strategy_id=normalized["strategy_id"],
                        owner_sha256=normalized["owner_sha256"], symbol=normalized["symbol"],
                        side=normalized["side"], initial_risk_usdt=normalized["initial_risk_usdt"],
                        realized_pnl_usdt=normalized["realized_pnl_usdt"], realized_R=normalized["realized_R"],
                        duplicate_replay_rejected=True, new_writer_row_count=1,
                        transaction_backup=str(transaction_dir), canary_ledger=str(args.canary_ledger),
                        next_action="ENABLE_FORWARD_MEASUREMENT_WRITES_SHADOW_ONLY",
                    )
                    atomic_json(args.result, result)
                    atomic_json(args.status, result)
                    return 0
                except Exception as exc:
                    restore_paths(paths_to_restore, transaction_dir)
                    blocked = status_payload(
                        "FAILED_BLOCKED_ROLLED_BACK", started_at, heartbeat, writer_invocations,
                        event_id=event_id, error=f"{type(exc).__name__}:{exc}",
                        transaction_backup=str(transaction_dir), rollback_complete=True,
                    )
                    atomic_json(args.result, blocked)
                    atomic_json(args.status, blocked)
                    return 1
            atomic_json(args.status, status_payload(
                "WAITING_REAL_FORWARD_OPEN_CLOSE", started_at, heartbeat, writer_invocations,
                baseline_closed_count=len(baseline_closed), close_sources=[str(path) for path in args.close_source],
            ))
            time.sleep(max(1.0, args.poll_sec))
        atomic_json(args.status, status_payload("STOPPED", started_at, heartbeat, writer_invocations))
        return 0
    except Exception as exc:
        blocked = status_payload(
            "BLOCKED", started_at, heartbeat, writer_invocations,
            error=f"{type(exc).__name__}:{exc}",
        )
        atomic_json(args.result, blocked)
        atomic_json(args.status, blocked)
        return 78


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--writer", type=Path, required=True)
    parser.add_argument("--writer-sha256", default=EXPECTED_WRITER_SHA256)
    parser.add_argument("--writer-latest", type=Path, required=True)
    parser.add_argument("--writer-state", type=Path, required=True)
    parser.add_argument("--writer-overlay", type=Path, required=True)
    parser.add_argument("--close-source", type=Path, action="append", required=True)
    parser.add_argument("--canary-ledger", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    parser.add_argument("--writer-timeout-sec", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
