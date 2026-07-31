from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import pandas as pd

VERSION = "ZEL_HISTORICAL_OOS_EXACT25_REPLAY_V1"
EXPECTED_STRATEGY_COUNT = 25
EXPECTED_DATA_STATE = "PASS_HISTORICAL_OOS_DATA_READY"
EXPECTED_DATA_ROWS = 302_400
EXPECTED_WINDOWS_PER_INTERVAL = 3
WARMUP_BARS = 240
FRAME_LIMIT = 420
RISK_UNIT_USDT = 1.0
FEE_RATE = 0.0005
SLIPPAGE_BPS = 1.0
MAX_HOLD_MIN = 120.0
CANONICAL_PRODUCER_UNIT = "q4r3-exact25-shadow-producer.service"
CANONICAL_WRITER_UNIT = "q4r3-exact25-persistent-single-event-writer.service"
FORMAL_LEDGER = Path("/home/z/z/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl")

_WORKER_SOURCE_ROOT: Path | None = None
_WORKER_DATA_ROOT: Path | None = None
_WORKER_INTERVAL: str | None = None
_WORKER_MANIFEST: dict[str, Any] | None = None
_WORKER_FUNDING: dict[str, list[dict[str, Any]]] | None = None
_WORKER_PRODUCER: Any = None
_WORKER_REGISTRY: dict[str, Any] | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def parse_epoch(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return number if math.isfinite(number) else None
    try:
        return pd.Timestamp(value).timestamp()
    except Exception:
        return None


def run_text(*args: str) -> tuple[int, str]:
    process = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return process.returncode, process.stdout.strip()


def service_snapshot(unit: str) -> dict[str, Any]:
    rc, text = run_text(
        "systemctl", "show", unit,
        "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
        "-p", "MainPID", "-p", "Result", "-p", "NRestarts",
    )
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return {
        "unit": unit,
        "rc": rc,
        "load_state": values.get("LoadState"),
        "active_state": values.get("ActiveState"),
        "sub_state": values.get("SubState"),
        "main_pid": int(values.get("MainPID") or 0),
        "result": values.get("Result"),
        "restart_count": int(values.get("NRestarts") or 0),
    }


def formal_prefix_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        empty = hashlib.sha256(b"").hexdigest()
        return {"path": str(path), "row_count": 0, "prefix_sha256": empty}
    rows = path.read_bytes().splitlines(keepends=True)
    return {
        "path": str(path),
        "row_count": len(rows),
        "prefix_sha256": hashlib.sha256(b"".join(rows)).hexdigest(),
    }


def verify_formal_prefix(before: Mapping[str, Any], path: Path) -> dict[str, Any]:
    count = int(before["row_count"])
    if not path.exists():
        rows: list[bytes] = []
    else:
        rows = path.read_bytes().splitlines(keepends=True)
    prefix = b"".join(rows[:count])
    after_prefix = hashlib.sha256(prefix).hexdigest()
    return {
        "row_count_before": count,
        "row_count_after": len(rows),
        "prefix_sha256_before": before["prefix_sha256"],
        "prefix_sha256_after": after_prefix,
        "prefix_unchanged": after_prefix == before["prefix_sha256"] and len(rows) >= count,
    }


def tree_hash(root: Path, relative_paths: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        path = root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_data_manifest(data_root: Path, interval: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = load_json(data_root / "manifest.json")
    if manifest.get("state") != EXPECTED_DATA_STATE:
        raise RuntimeError(f"DATA_STATE_MISMATCH:{manifest.get('state')}")
    if int(manifest.get("total_market_rows") or 0) != EXPECTED_DATA_ROWS:
        raise RuntimeError("DATA_ROW_COUNT_MISMATCH")
    if manifest.get("forward_overlap_count") != 0:
        raise RuntimeError("FORWARD_OVERLAP_FORBIDDEN")
    if manifest.get("historical_data_is_promotion_authority") is not False:
        raise RuntimeError("HISTORICAL_PROMOTION_AUTHORITY_FORBIDDEN")
    if manifest.get("final_holdout_accessed") is not False:
        raise RuntimeError("FINAL_HOLDOUT_ACCESSED")
    if manifest.get("execution_authority") != "NONE" or manifest.get("order_authority") != "BLOCKED":
        raise RuntimeError("DATA_AUTHORITY_FLAGS_UNSAFE")
    files = [
        row for row in manifest.get("files", [])
        if isinstance(row, dict) and row.get("kind") == "market" and row.get("interval") == interval
    ]
    expected = len(manifest.get("symbols") or []) * EXPECTED_WINDOWS_PER_INTERVAL
    if len(files) != expected:
        raise RuntimeError(f"INTERVAL_FILE_COUNT:{len(files)}!={expected}")
    for row in files:
        path = data_root / str(row["path"])
        if not path.is_file():
            raise RuntimeError(f"DATA_FILE_MISSING:{path}")
        if sha256_path(path) != row.get("sha256"):
            raise RuntimeError(f"DATA_FILE_SHA_MISMATCH:{row.get('path')}")
    return manifest, sorted(files, key=lambda row: (str(row["window_id"]), str(row["symbol"])))


def load_funding(data_root: Path, manifest: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for symbol in manifest.get("symbols") or []:
        path = data_root / "funding" / f"{symbol}.json"
        if not path.is_file():
            result[str(symbol)] = []
            continue
        payload = load_json(path)
        rows = []
        for row in payload.get("rows") or []:
            if not isinstance(row, dict):
                continue
            ts = safe_float(row.get("timestamp_ms"))
            rate = safe_float(row.get("funding_rate"))
            if ts is None or rate is None:
                continue
            rows.append({"timestamp_ms": int(ts), "funding_rate": rate})
        result[str(symbol)] = sorted(rows, key=lambda row: row["timestamp_ms"])
    return result


def import_producer(source_root: Path) -> Any:
    path = source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"
    if not path.is_file():
        raise RuntimeError(f"PRODUCER_MISSING:{path}")
    name = f"zel_historical_replay_producer_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("PRODUCER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def init_worker(source_root: str, data_root: str, interval: str) -> None:
    global _WORKER_SOURCE_ROOT, _WORKER_DATA_ROOT, _WORKER_INTERVAL
    global _WORKER_MANIFEST, _WORKER_FUNDING, _WORKER_PRODUCER, _WORKER_REGISTRY
    os.environ.update({
        "Q4R3_SHADOW_ONLY": "1",
        "Q4R3_PAPER_ENABLED": "0",
        "Q4R3_LIVE_ENABLED": "0",
        "Q4R3_ORDER_ENABLED": "0",
        "Q4R3_HISTORICAL_BACKFILL_ALLOWED": "0",
        "Q4R3_EPOCH_ID": "EXACT25_EDGE_V1",
        "Q4R3_PRODUCER_STAGE": "FIRST_FORWARD_CANARY",
    })
    _WORKER_SOURCE_ROOT = Path(source_root)
    _WORKER_DATA_ROOT = Path(data_root)
    _WORKER_INTERVAL = interval
    _WORKER_MANIFEST, _ = validate_data_manifest(_WORKER_DATA_ROOT, interval)
    _WORKER_FUNDING = load_funding(_WORKER_DATA_ROOT, _WORKER_MANIFEST)
    _WORKER_PRODUCER = import_producer(_WORKER_SOURCE_ROOT)
    _, _WORKER_REGISTRY = _WORKER_PRODUCER.load_registry(_WORKER_SOURCE_ROOT)
    if len(_WORKER_REGISTRY) != EXPECTED_STRATEGY_COUNT:
        raise RuntimeError("WORKER_REGISTRY_NOT_EXACT25")


def funding_estimate(position: Mapping[str, Any], exit_ts: str, rows: Sequence[Mapping[str, Any]]) -> tuple[float, int]:
    entry_epoch = parse_epoch(position.get("entry_ts"))
    exit_epoch = parse_epoch(exit_ts)
    if entry_epoch is None or exit_epoch is None:
        return 0.0, 0
    entry_ms = int(entry_epoch * 1000)
    exit_ms = int(exit_epoch * 1000)
    notional = float(position["entry_price"]) * float(position.get("original_qty") or position["qty"])
    side_factor = -1.0 if str(position.get("side")) == "long" else 1.0
    total = 0.0
    count = 0
    for row in rows:
        ts_ms = int(row["timestamp_ms"])
        if entry_ms < ts_ms <= exit_ms:
            total += notional * float(row["funding_rate"]) * side_factor
            count += 1
    return total, count


def frame_from_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise RuntimeError(f"CSV_COLUMNS_MISSING:{path}")
    frame = frame.sort_values("timestamp_ms").drop_duplicates("timestamp_ms").reset_index(drop=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    return frame


def replay_lane(
    strategy_id: str,
    owner: Any,
    file_row: Mapping[str, Any],
    frame: pd.DataFrame,
    funding_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    assert _WORKER_PRODUCER is not None
    producer = _WORKER_PRODUCER
    interval = str(file_row["interval"])
    symbol = str(file_row["symbol"])
    window_id = str(file_row["window_id"])
    position: MutableMapping[str, Any] | None = None
    closed: list[dict[str, Any]] = []
    calls = signals = valid_entries = opens = adds = partials = strategy_exits = 0
    error_count = 0
    error_samples: list[dict[str, Any]] = []
    first_index = max(WARMUP_BARS - 1, 0)

    for index in range(first_index, len(frame)):
        last = frame.iloc[index]
        current = frame.iloc[max(0, index - FRAME_LIMIT + 1): index + 1].copy()
        current_price = float(last["close"])
        last_ts_iso = pd.Timestamp(last["timestamp"]).isoformat()
        candle = {key: float(last[key]) for key in ("open", "high", "low", "close")}
        now_epoch = producer.parse_time(last_ts_iso) or 0.0
        features = producer.feature_snapshot(current)
        strategy_state = None

        try:
            if isinstance(position, dict):
                producer.mark_excursions(position, candle)
                price_exit = producer.bar_exit(position, candle, now_epoch, MAX_HOLD_MIN)
                if price_exit is not None:
                    exit_price, reason = price_exit
                    funding_pnl, funding_count = funding_estimate(position, last_ts_iso, funding_rows)
                    row = producer.close_position(
                        position, exit_price, last_ts_iso, reason, features, FEE_RATE, SLIPPAGE_BPS
                    )
                    row.update({
                        "event_id": f"historical.{interval}.{window_id}.{row['event_id']}",
                        "position_id": f"historical.{interval}.{window_id}.{row['position_id']}",
                        "data_interval": interval,
                        "window_id": window_id,
                        "data_source_path": file_row["path"],
                        "data_source_sha256": file_row["sha256"],
                        "historical_oos": True,
                        "funding_pnl_estimate_usdt": funding_pnl,
                        "funding_event_count": funding_count,
                        "realized_R_including_funding_estimate": float(row["realized_R"]) + funding_pnl / float(row["initial_risk_usdt"]),
                        "funding_model": "ENTRY_NOTIONAL_STATIC_ESTIMATE_NON_PROMOTABLE",
                        "captured_at": last_ts_iso,
                    })
                    closed.append(row)
                    position = None
                else:
                    strategy_state = {
                        "position_side": position.get("side"),
                        "position_qty": position.get("qty"),
                        "avg_entry": position.get("entry_price"),
                        "add_count": position.get("add_count", 0),
                        "last_add_price": position.get("entry_price"),
                    }

            calls += 1
            result = owner.strategy(current, state=strategy_state, risk_action="hold")
            if not isinstance(result, dict):
                raise RuntimeError("STRATEGY_RESULT_NOT_DICT")
            action = str(result.get("action") or "hold").lower()
            if action not in {"hold", "none", "flat"}:
                signals += 1

            if isinstance(position, dict):
                if action in {"reduce", "partial", "partial30"}:
                    if producer.apply_partial_reduce(position, result, current_price, FEE_RATE, SLIPPAGE_BPS):
                        partials += 1
                elif action == "add":
                    if producer.apply_add(position, result, current_price, RISK_UNIT_USDT, FEE_RATE, SLIPPAGE_BPS):
                        adds += 1
                elif action in {"exit", "close", "stop"}:
                    funding_pnl, funding_count = funding_estimate(position, last_ts_iso, funding_rows)
                    row = producer.close_position(
                        position, current_price, last_ts_iso, f"strategy_{action}", features, FEE_RATE, SLIPPAGE_BPS
                    )
                    row.update({
                        "event_id": f"historical.{interval}.{window_id}.{row['event_id']}",
                        "position_id": f"historical.{interval}.{window_id}.{row['position_id']}",
                        "data_interval": interval,
                        "window_id": window_id,
                        "data_source_path": file_row["path"],
                        "data_source_sha256": file_row["sha256"],
                        "historical_oos": True,
                        "funding_pnl_estimate_usdt": funding_pnl,
                        "funding_event_count": funding_count,
                        "realized_R_including_funding_estimate": float(row["realized_R"]) + funding_pnl / float(row["initial_risk_usdt"]),
                        "funding_model": "ENTRY_NOTIONAL_STATIC_ESTIMATE_NON_PROMOTABLE",
                        "captured_at": last_ts_iso,
                    })
                    closed.append(row)
                    position = None
                    strategy_exits += 1
            else:
                if producer.valid_entry(result, current_price) is not None:
                    valid_entries += 1
                new_position = producer.make_position(
                    strategy_id,
                    str(getattr(owner, "owner_sha256", "")),
                    symbol,
                    interval,
                    result,
                    current,
                    RISK_UNIT_USDT,
                    FEE_RATE,
                    SLIPPAGE_BPS,
                )
                if new_position is not None:
                    new_position["position_id"] = f"historical.{interval}.{window_id}.{new_position['position_id']}"
                    new_position["event_id"] = new_position["position_id"]
                    position = new_position
                    opens += 1
        except Exception as exc:
            error_count += 1
            if len(error_samples) < 20:
                error_samples.append({
                    "index": index,
                    "timestamp": last_ts_iso,
                    "error": f"{type(exc).__name__}:{exc}",
                })

    censored = 1 if isinstance(position, dict) else 0
    return {
        "strategy_id": strategy_id,
        "owner_sha256": str(getattr(owner, "owner_sha256", "")),
        "symbol": symbol,
        "interval": interval,
        "window_id": window_id,
        "source_path": file_row["path"],
        "source_sha256": file_row["sha256"],
        "bar_count": len(frame),
        "warmup_bars": min(WARMUP_BARS, len(frame)),
        "strategy_call_count": calls,
        "signal_count": signals,
        "valid_entry_count": valid_entries,
        "open_count": opens,
        "close_count": len(closed),
        "add_count": adds,
        "partial_count": partials,
        "strategy_exit_count": strategy_exits,
        "censored_open_at_window_end": censored,
        "error_count": error_count,
        "error_samples": error_samples,
        "closed_rows": closed,
    }


def replay_strategy(strategy_id: str) -> dict[str, Any]:
    if _WORKER_REGISTRY is None or _WORKER_DATA_ROOT is None or _WORKER_INTERVAL is None or _WORKER_MANIFEST is None or _WORKER_FUNDING is None:
        raise RuntimeError("WORKER_NOT_INITIALIZED")
    owner = _WORKER_REGISTRY[strategy_id]
    files = [
        row for row in _WORKER_MANIFEST.get("files", [])
        if isinstance(row, dict) and row.get("kind") == "market" and row.get("interval") == _WORKER_INTERVAL
    ]
    lane_results = []
    for file_row in sorted(files, key=lambda row: (str(row["window_id"]), str(row["symbol"]))):
        frame = frame_from_csv(_WORKER_DATA_ROOT / str(file_row["path"]))
        lane_results.append(
            replay_lane(
                strategy_id,
                owner,
                file_row,
                frame,
                _WORKER_FUNDING.get(str(file_row["symbol"]), []),
            )
        )
    return {"strategy_id": strategy_id, "owner_sha256": str(getattr(owner, "owner_sha256", "")), "lanes": lane_results}


def max_drawdown(values: Sequence[float]) -> float:
    equity = peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return 999.0 if gains > 0 else None
    return gains / losses


def metrics(rows: Sequence[Mapping[str, Any]], field: str = "realized_R") -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: parse_epoch(row.get("exit_ts")) or 0.0)
    values = [float(row[field]) for row in ordered if safe_float(row.get(field)) is not None]
    count = len(values)
    return {
        "sample_count": count,
        "net_R": sum(values),
        "expectancy_R": statistics.fmean(values) if values else None,
        "median_R": statistics.median(values) if values else None,
        "profit_factor": profit_factor(values),
        "max_drawdown_R": max_drawdown(values),
        "win_rate_pct": (sum(value > 0 for value in values) / count * 100.0) if values else None,
        "average_MFE_R": statistics.fmean(float(row.get("MFE_R") or 0.0) for row in ordered) if ordered else None,
        "average_MAE_R": statistics.fmean(float(row.get("MAE_R") or 0.0) for row in ordered) if ordered else None,
        "average_exposure_min": statistics.fmean(float(row.get("time_exposure_min") or 0.0) for row in ordered) if ordered else None,
        "fee_usdt": sum(float(row.get("fee") or 0.0) for row in ordered),
        "slippage_usdt": sum(float(row.get("slippage") or 0.0) for row in ordered),
        "funding_pnl_estimate_usdt": sum(float(row.get("funding_pnl_estimate_usdt") or 0.0) for row in ordered),
    }


def claim_tier(sample_count: int) -> str:
    if sample_count == 0:
        return "ZERO_TRADES_HOLD"
    if sample_count < 20:
        return "LOW_SAMPLE_HOLD"
    if sample_count < 100:
        return "HYPOTHESIS_ONLY"
    if sample_count < 300:
        return "COMPONENT_RESEARCH_REVIEW"
    return "INTEGRATED_RESEARCH_REVIEW"


def failure_fingerprint(summary: Mapping[str, Any], base: Mapping[str, Any]) -> str:
    errors = int(summary.get("error_count") or 0)
    entries = int(summary.get("valid_entry_count") or 0)
    closed = int(base.get("sample_count") or 0)
    expectancy = safe_float(base.get("expectancy_R"))
    pf = safe_float(base.get("profit_factor"))
    if errors:
        return "STRATEGY_EXECUTION_ERRORS"
    if entries == 0:
        return "ZERO_TRADES_GATE_OR_NO_OPPORTUNITY"
    if closed == 0:
        return "ENTRIES_WITHOUT_CLOSED_TRADES"
    if expectancy is not None and abs(expectancy) < 0.05:
        return "NEAR_BREAKEVEN"
    if expectancy is not None and expectancy > 0 and pf is not None and pf >= 1.0:
        return "POSITIVE_OOS_CANDIDATE_UNPROMOTED"
    return "NEGATIVE_OR_UNSTABLE_OOS_EDGE"


def grouped_metrics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "unknown")].append(row)
    return {name: metrics(items) for name, items in sorted(groups.items())}


def aggregate_strategy(result: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lanes = list(result.get("lanes") or [])
    rows = [row for lane in lanes for row in lane.get("closed_rows") or []]
    counters = {
        name: sum(int(lane.get(name) or 0) for lane in lanes)
        for name in (
            "bar_count", "strategy_call_count", "signal_count", "valid_entry_count", "open_count",
            "close_count", "add_count", "partial_count", "strategy_exit_count",
            "censored_open_at_window_end", "error_count",
        )
    }
    base = metrics(rows, "realized_R")
    with_funding = metrics(rows, "realized_R_including_funding_estimate")
    summary = {
        "strategy_id": result["strategy_id"],
        "owner_sha256": result["owner_sha256"],
        "lane_count": len(lanes),
        **counters,
        "closed_metrics_ex_funding": base,
        "closed_metrics_including_funding_estimate": with_funding,
        "by_symbol": grouped_metrics(rows, "symbol"),
        "by_window": grouped_metrics(rows, "window_id"),
        "by_side": grouped_metrics(rows, "side"),
        "by_regime": grouped_metrics(rows, "regime"),
        "claim_tier": claim_tier(int(base["sample_count"])),
        "failure_fingerprint": failure_fingerprint(counters, base),
        "selection_authority": False,
        "promotion_authority": False,
        "action": "hold",
        "error_samples": [sample for lane in lanes for sample in lane.get("error_samples") or []][:50],
    }
    return summary, rows


def write_scoreboard(path: Path, scorecards: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "strategy_id", "claim_tier", "failure_fingerprint", "strategy_call_count", "signal_count",
        "valid_entry_count", "open_count", "close_count", "censored_open_at_window_end", "error_count",
        "net_R_ex_funding", "expectancy_R_ex_funding", "profit_factor_ex_funding", "max_drawdown_R_ex_funding",
        "win_rate_pct", "net_R_including_funding_estimate", "average_MFE_R", "average_MAE_R", "average_exposure_min",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for card in scorecards:
            base = card["closed_metrics_ex_funding"]
            funded = card["closed_metrics_including_funding_estimate"]
            writer.writerow({
                "strategy_id": card["strategy_id"],
                "claim_tier": card["claim_tier"],
                "failure_fingerprint": card["failure_fingerprint"],
                "strategy_call_count": card["strategy_call_count"],
                "signal_count": card["signal_count"],
                "valid_entry_count": card["valid_entry_count"],
                "open_count": card["open_count"],
                "close_count": card["close_count"],
                "censored_open_at_window_end": card["censored_open_at_window_end"],
                "error_count": card["error_count"],
                "net_R_ex_funding": base["net_R"],
                "expectancy_R_ex_funding": base["expectancy_R"],
                "profit_factor_ex_funding": base["profit_factor"],
                "max_drawdown_R_ex_funding": base["max_drawdown_R"],
                "win_rate_pct": base["win_rate_pct"],
                "net_R_including_funding_estimate": funded["net_R"],
                "average_MFE_R": base["average_MFE_R"],
                "average_MAE_R": base["average_MAE_R"],
                "average_exposure_min": base["average_exposure_min"],
            })


def self_test() -> None:
    rows = [
        {"exit_ts": "2026-01-01T00:00:00Z", "realized_R": 1.0, "realized_R_including_funding_estimate": 0.9, "MFE_R": 1.4, "MAE_R": -0.3, "time_exposure_min": 30, "fee": 0.1, "slippage": 0.02, "funding_pnl_estimate_usdt": -0.1},
        {"exit_ts": "2026-01-01T01:00:00Z", "realized_R": -0.5, "realized_R_including_funding_estimate": -0.45, "MFE_R": 0.2, "MAE_R": -0.7, "time_exposure_min": 45, "fee": 0.1, "slippage": 0.02, "funding_pnl_estimate_usdt": 0.05},
        {"exit_ts": "2026-01-01T02:00:00Z", "realized_R": 0.25, "realized_R_including_funding_estimate": 0.2, "MFE_R": 0.5, "MAE_R": -0.1, "time_exposure_min": 15, "fee": 0.1, "slippage": 0.02, "funding_pnl_estimate_usdt": -0.05},
    ]
    result = metrics(rows)
    assert result["sample_count"] == 3
    assert abs(result["net_R"] - 0.75) < 1e-12
    assert abs(float(result["profit_factor"]) - 2.5) < 1e-12
    assert claim_tier(0) == "ZERO_TRADES_HOLD"
    assert claim_tier(19) == "LOW_SAMPLE_HOLD"
    assert claim_tier(20) == "HYPOTHESIS_ONLY"
    assert claim_tier(100) == "COMPONENT_RESEARCH_REVIEW"
    assert claim_tier(300) == "INTEGRATED_RESEARCH_REVIEW"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root")
    parser.add_argument("--data-root")
    parser.add_argument("--interval", choices=("1m", "15m"))
    parser.add_argument("--output-dir")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not all((args.source_root, args.data_root, args.interval, args.output_dir)):
        parser.error("source-root, data-root, interval and output-dir are required")

    source_root = Path(args.source_root).resolve()
    data_root = Path(args.data_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(int(args.workers), 8))

    manifest, files = validate_data_manifest(data_root, args.interval)
    producer = import_producer(source_root)
    _, registry = producer.load_registry(source_root)
    if len(registry) != EXPECTED_STRATEGY_COUNT:
        raise RuntimeError(f"REGISTRY_COUNT:{len(registry)}")
    strategy_paths = [str(getattr(owner, "owner_path", "")) for owner in registry.values()]
    if any(not path for path in strategy_paths):
        raise RuntimeError("OWNER_PATH_MISSING")

    source_tree_before = tree_hash(source_root, strategy_paths)
    producer_before = sha256_path(source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py")
    manifest_before = sha256_path(source_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json")
    canonical_producer_before = service_snapshot(CANONICAL_PRODUCER_UNIT)
    canonical_writer_before = service_snapshot(CANONICAL_WRITER_UNIT)
    formal_before = formal_prefix_snapshot(FORMAL_LEDGER)
    if canonical_producer_before["active_state"] != "active" or canonical_writer_before["active_state"] != "active":
        raise RuntimeError("CANONICAL_RUNTIME_NOT_ACTIVE")

    started = time.monotonic()
    raw_results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    context = mp.get_context("fork")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=init_worker,
        initargs=(str(source_root), str(data_root), args.interval),
    ) as executor:
        futures = {executor.submit(replay_strategy, strategy_id): strategy_id for strategy_id in sorted(registry)}
        for future in as_completed(futures):
            strategy_id = futures[future]
            try:
                raw_results.append(future.result())
                print(json.dumps({"strategy_id": strategy_id, "state": "DONE"}), flush=True)
            except Exception as exc:
                failures.append({"strategy_id": strategy_id, "error": f"{type(exc).__name__}:{exc}"})
                print(json.dumps({"strategy_id": strategy_id, "state": "FAILED", "error": failures[-1]["error"]}), flush=True)

    scorecards: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for result in sorted(raw_results, key=lambda row: row["strategy_id"]):
        card, rows = aggregate_strategy(result)
        scorecards.append(card)
        all_rows.extend(rows)

    canonical_producer_after = service_snapshot(CANONICAL_PRODUCER_UNIT)
    canonical_writer_after = service_snapshot(CANONICAL_WRITER_UNIT)
    formal_after = verify_formal_prefix(formal_before, FORMAL_LEDGER)
    source_tree_after = tree_hash(source_root, strategy_paths)
    producer_after = sha256_path(source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py")
    manifest_after = sha256_path(source_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json")

    runtime_safe = (
        canonical_producer_after["active_state"] == "active"
        and canonical_writer_after["active_state"] == "active"
        and canonical_producer_before["main_pid"] == canonical_producer_after["main_pid"]
        and canonical_writer_before["main_pid"] == canonical_writer_after["main_pid"]
        and formal_after["prefix_unchanged"] is True
        and source_tree_before == source_tree_after
        and producer_before == producer_after
        and manifest_before == manifest_after
    )
    infrastructure_complete = len(raw_results) == EXPECTED_STRATEGY_COUNT and not failures
    state = "PASS" if runtime_safe and infrastructure_complete else "HOLD"
    verdict = "HISTORICAL_OOS_EXACT25_REPLAY_COMPLETE" if state == "PASS" else "HISTORICAL_OOS_EXACT25_REPLAY_HOLD"

    scorecards = sorted(
        scorecards,
        key=lambda card: (
            -(safe_float(card["closed_metrics_ex_funding"].get("expectancy_R"), -1e9) or -1e9),
            -int(card["closed_metrics_ex_funding"].get("sample_count") or 0),
            str(card["strategy_id"]),
        ),
    )
    fingerprint_counts: dict[str, int] = defaultdict(int)
    tier_counts: dict[str, int] = defaultdict(int)
    for card in scorecards:
        fingerprint_counts[str(card["failure_fingerprint"])] += 1
        tier_counts[str(card["claim_tier"])] += 1

    report = {
        "schema_version": "zel.historical_oos_exact25_replay.result.v1",
        "version": VERSION,
        "state": state,
        "verdict": verdict,
        "generated_at": now_iso(),
        "elapsed_sec": time.monotonic() - started,
        "interval": args.interval,
        "workers": workers,
        "data": {
            "root": str(data_root),
            "manifest_sha256": sha256_path(data_root / "manifest.json"),
            "authority_end": manifest.get("authority_end"),
            "symbol_count": len(manifest.get("symbols") or []),
            "symbols": manifest.get("symbols"),
            "window_count": len({str(row["window_id"]) for row in files}),
            "file_count": len(files),
            "market_row_count": sum(int(row["rows"]) for row in files),
            "forward_overlap_count": 0,
            "final_holdout_accessed": False,
        },
        "source": {
            "root": str(source_root),
            "strategy_count": len(registry),
            "strategy_tree_sha256_before": source_tree_before,
            "strategy_tree_sha256_after": source_tree_after,
            "strategy_tree_unchanged": source_tree_before == source_tree_after,
            "producer_sha256_before": producer_before,
            "producer_sha256_after": producer_after,
            "producer_unchanged": producer_before == producer_after,
            "manifest_sha256_before": manifest_before,
            "manifest_sha256_after": manifest_after,
            "manifest_unchanged": manifest_before == manifest_after,
        },
        "canonical_runtime": {
            "producer_before": canonical_producer_before,
            "producer_after": canonical_producer_after,
            "writer_before": canonical_writer_before,
            "writer_after": canonical_writer_after,
            "producer_pid_unchanged": canonical_producer_before["main_pid"] == canonical_producer_after["main_pid"],
            "writer_pid_unchanged": canonical_writer_before["main_pid"] == canonical_writer_after["main_pid"],
            "formal_ledger": formal_after,
        },
        "replay": {
            "strategy_count_expected": EXPECTED_STRATEGY_COUNT,
            "strategy_count_completed": len(scorecards),
            "strategy_failure_count": len(failures),
            "strategy_failures": failures,
            "closed_trade_count": len(all_rows),
            "strategy_call_count": sum(int(card["strategy_call_count"]) for card in scorecards),
            "signal_count": sum(int(card["signal_count"]) for card in scorecards),
            "valid_entry_count": sum(int(card["valid_entry_count"]) for card in scorecards),
            "open_count": sum(int(card["open_count"]) for card in scorecards),
            "censored_open_at_window_end": sum(int(card["censored_open_at_window_end"]) for card in scorecards),
            "error_count": sum(int(card["error_count"]) for card in scorecards),
            "claim_tier_counts": dict(sorted(tier_counts.items())),
            "failure_fingerprint_counts": dict(sorted(fingerprint_counts.items())),
            "aggregate_metrics_ex_funding": metrics(all_rows, "realized_R"),
            "aggregate_metrics_including_funding_estimate": metrics(all_rows, "realized_R_including_funding_estimate"),
            "funding_model": "ENTRY_NOTIONAL_STATIC_ESTIMATE_NON_PROMOTABLE",
            "same_bar_collision_policy": "STOP_FIRST",
            "window_end_open_policy": "CENSORED_EXCLUDED_FROM_ECONOMIC_METRICS",
            "max_hold_min": MAX_HOLD_MIN,
            "fee_rate_per_side": FEE_RATE,
            "slippage_bps_per_side": SLIPPAGE_BPS,
        },
        "scorecards": scorecards,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "paper_enabled": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }

    atomic_json(output_dir / "report.json", report)
    write_scoreboard(output_dir / "scoreboard.csv", scorecards)
    with gzip.open(output_dir / "trades.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in sorted(all_rows, key=lambda item: (parse_epoch(item.get("exit_ts")) or 0.0, str(item.get("event_id")))):
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    atomic_json(output_dir / "summary.json", {
        "state": state,
        "verdict": verdict,
        "interval": args.interval,
        "closed_trade_count": len(all_rows),
        "strategy_count_completed": len(scorecards),
        "strategy_failure_count": len(failures),
        "error_count": report["replay"]["error_count"],
        "claim_tier_counts": report["replay"]["claim_tier_counts"],
        "failure_fingerprint_counts": report["replay"]["failure_fingerprint_counts"],
        "canonical_runtime_safe": runtime_safe,
        "research_only": True,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    })
    print(json.dumps(load_json(output_dir / "summary.json"), sort_keys=True))
    return 0 if state == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
