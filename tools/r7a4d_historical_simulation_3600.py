#!/usr/bin/env python3
from __future__ import annotations

import argparse
import builtins
import hashlib
import importlib.util
import itertools
import json
import math
import os
import re
import socket
import statistics
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from enum import Enum
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, Iterator

import numpy as np
import pandas as pd


class AttrBox(SimpleNamespace):
    def __getattr__(self, name: str) -> Any:
        return None


class SideEffectBlocked(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                line = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                handle.write(line)
                digest.update(line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() and not path.is_symlink() else None


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def snapshot(paths: list[Path]) -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in paths}


def prior_gate(status: dict[str, Any], expected_strategies: int, expected_segments: int, expected_runs: int) -> bool:
    required = {
        "official_stage": "R7.A4C",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": expected_strategies,
        "historical_segment_selected_count": expected_segments,
        "regime_coverage_count": 4,
        "trend_up_fold_count": 6,
        "range_fold_count": 6,
        "trend_down_fold_count": 6,
        "shock_recovery_fold_count": 6,
        "execution_cost_axis_coverage_count": 4,
        "scenario_plan_count": expected_runs,
        "historical_simulation_execution_count": 0,
        "active_entry_count": 0,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "paper_live_order_count": 0,
        "next_stage": "R7.A4D_HISTORICAL_SIMULATION_3600",
    }
    return all(status.get(key) == value for key, value in required.items()) and bool(status.get("lineage_id"))


def _numeric_matrix(rows: list[Any], width: int = 6, sample_limit: int = 2000) -> np.ndarray:
    sample = rows[:sample_limit]
    if len(sample) < 20 or any(not isinstance(row, list) or len(row) != width for row in sample):
        raise ValueError("MARKET_ARRAY_ROWS_INVALID")
    try:
        matrix = np.asarray(sample, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("MARKET_ARRAY_ROWS_NON_NUMERIC") from exc
    if matrix.ndim != 2 or matrix.shape[1] != width or not np.isfinite(matrix).all():
        raise ValueError("MARKET_ARRAY_ROWS_NON_FINITE")
    return matrix


def _timestamp_index(matrix: np.ndarray) -> int:
    candidates: list[int] = []
    for index in range(matrix.shape[1]):
        values = matrix[:, index]
        diffs = np.diff(values)
        if diffs.size == 0:
            continue
        increasing_ratio = float(np.mean(diffs > 0))
        positive_step = float(np.median(diffs[diffs > 0])) if np.any(diffs > 0) else 0.0
        magnitude = float(np.median(np.abs(values)))
        if increasing_ratio >= 0.98 and positive_step > 0 and magnitude >= 1e8:
            candidates.append(index)
    if len(candidates) != 1:
        raise ValueError(f"MARKET_TIMESTAMP_SCHEMA_AMBIGUOUS:{candidates}")
    return candidates[0]


def _mapping_score(matrix: np.ndarray, mapping: tuple[int, int, int, int, int]) -> tuple[float, float, float]:
    open_i, high_i, low_i, close_i, volume_i = mapping
    open_v = matrix[:, open_i]
    high_v = matrix[:, high_i]
    low_v = matrix[:, low_i]
    close_v = matrix[:, close_i]
    volume_v = matrix[:, volume_i]
    valid = (
        (open_v > 0)
        & (high_v > 0)
        & (low_v > 0)
        & (close_v > 0)
        & (volume_v >= 0)
        & (high_v >= np.maximum(open_v, close_v))
        & (low_v <= np.minimum(open_v, close_v))
        & (high_v >= low_v)
    )
    valid_ratio = float(np.mean(valid))
    scale = max(float(np.median(np.abs(close_v))), 1e-12)
    continuity = float(np.median(np.abs(open_v[1:] - close_v[:-1])) / scale)
    valid_prices = np.column_stack((open_v, high_v, low_v, close_v))[valid]
    if valid_prices.size == 0:
        cluster = math.inf
    else:
        row_scale = np.maximum(np.median(np.abs(valid_prices), axis=1), 1e-12)
        row_spread = np.max(valid_prices, axis=1) - np.min(valid_prices, axis=1)
        cluster = float(np.median(row_spread / row_scale))
    return valid_ratio, continuity, cluster


def infer_ohlcv_array_schema(rows: list[Any]) -> dict[str, int]:
    matrix = _numeric_matrix(rows)
    timestamp_i = _timestamp_index(matrix)
    remaining = [index for index in range(matrix.shape[1]) if index != timestamp_i]
    ranked: list[tuple[float, float, float, tuple[int, int, int, int, int]]] = []
    for mapping in itertools.permutations(remaining, 5):
        valid_ratio, continuity, cluster = _mapping_score(matrix, mapping)
        if valid_ratio >= 0.995 and math.isfinite(continuity) and math.isfinite(cluster):
            ranked.append((valid_ratio, -continuity, -cluster, mapping))
    if not ranked:
        raise ValueError("MARKET_OHLCV_SCHEMA_NOT_RESOLVED")
    ranked.sort(reverse=True)
    best = ranked[0]
    if len(ranked) > 1:
        second = ranked[1]
        if all(abs(best[index] - second[index]) < 1e-9 for index in range(3)):
            raise ValueError("MARKET_OHLCV_SCHEMA_AMBIGUOUS")
    open_i, high_i, low_i, close_i, volume_i = best[3]
    return {
        "timestamp": timestamp_i,
        "open": open_i,
        "high": high_i,
        "low": low_i,
        "close": close_i,
        "volume": volume_i,
    }


def load_market_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            rows = payload["rows"]
            if not rows:
                raise ValueError("MARKET_ARRAY_ROWS_EMPTY")
            if isinstance(rows[0], dict):
                frame = pd.DataFrame(rows)
            elif isinstance(rows[0], list):
                schema = infer_ohlcv_array_schema(rows)
                frame = pd.DataFrame({name: [row[index] for row in rows] for name, index in schema.items()})
            else:
                raise ValueError("MARKET_ARRAY_ROW_TYPE_INVALID")
            if payload.get("symbol") is not None:
                frame["symbol"] = str(payload["symbol"])
            timeframe = payload.get("interval") or payload.get("timeframe")
            if timeframe is not None:
                frame["timeframe"] = str(timeframe)
            declared = payload.get("row_count")
            if declared is not None and int(declared) != len(frame):
                raise ValueError(f"MARKET_ROW_COUNT_MISMATCH:{declared}:{len(frame)}")
        else:
            try:
                frame = pd.read_json(path)
            except ValueError:
                frame = pd.read_json(path, lines=True)
    elif suffix == ".csv":
        frame = pd.read_csv(path)
    elif suffix == ".jsonl":
        frame = pd.read_json(path, lines=True)
    elif suffix == ".parquet":
        frame = pd.read_parquet(path)
    elif suffix == ".feather":
        frame = pd.read_feather(path)
    elif suffix == ".npz":
        data = np.load(path, allow_pickle=False)
        frame = pd.DataFrame({key: data[key] for key in data.files})
    else:
        raise ValueError(f"UNSUPPORTED_MARKET_FORMAT:{suffix}")
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("MARKET_DATA_NOT_FRAME")
    frame = frame.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    required = ["open", "high", "low", "close"]
    if any(column not in frame.columns for column in required):
        raise ValueError("MARKET_COLUMNS_MISSING")
    timestamp_candidates = [name for name in ("timestamp", "ts", "time", "datetime", "date", "open_time") if name in frame.columns]
    if not timestamp_candidates:
        raise ValueError("MARKET_TIMESTAMP_MISSING")
    timestamp_col = timestamp_candidates[0]
    for column in required + (["volume"] if "volume" in frame.columns else []):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    timestamp_numeric = pd.to_numeric(frame[timestamp_col], errors="coerce")
    if timestamp_numeric.notna().sum() >= max(2, len(frame) // 2):
        frame["__timestamp"] = timestamp_numeric
    else:
        parsed = pd.to_datetime(frame[timestamp_col], errors="coerce", utc=True)
        frame["__timestamp"] = parsed.astype("int64", errors="ignore")
    frame = frame.dropna(subset=required + ["__timestamp"])
    frame = frame[(frame["high"] >= frame[["open", "close"]].max(axis=1))]
    frame = frame[(frame["low"] <= frame[["open", "close"]].min(axis=1))]
    frame = frame[frame["close"] > 0]
    frame = frame.sort_values("__timestamp").drop_duplicates("__timestamp", keep="last").reset_index(drop=True)
    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    return frame


def load_module(root: Path, repo_path: str, strategy_id: str):
    path = root / repo_path
    module_name = f"r7a4d_strategy_{strategy_id}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def resolve_callable(module: Any, dotted: str) -> tuple[type[Any], str]:
    parts = dotted.split(".")
    if len(parts) != 2:
        raise RuntimeError(f"CALLABLE_FORMAT_INVALID:{dotted}")
    owner = getattr(module, parts[0], None)
    method = getattr(owner, parts[1], None) if isinstance(owner, type) else None
    if not isinstance(owner, type) or not callable(method):
        raise RuntimeError(f"CALLABLE_NOT_RESOLVED:{dotted}")
    return owner, parts[1]


def normalize_intent(value: Any) -> str:
    if isinstance(value, Enum):
        text = str(value.value)
    else:
        inner = getattr(value, "value", None)
        text = str(inner if inner is not None else value)
    text = text.strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def decision_fields(decision: Any) -> dict[str, Any]:
    if isinstance(decision, dict):
        payload = decision.get("payload") if isinstance(decision.get("payload"), dict) else {}
        return {
            "ok": bool(decision.get("ok", True)),
            "intent": normalize_intent(decision.get("intent") or decision.get("action") or "hold"),
            "confidence": float(decision.get("confidence") or 0.0),
            "target_qty": float(decision.get("target_qty") or decision.get("size") or 0.0),
            "target_price": float(decision.get("target_price") or decision.get("entry") or 0.0),
            "reason": str(decision.get("reason") or decision.get("why") or ""),
            "payload": payload,
        }
    payload = getattr(decision, "payload", {})
    return {
        "ok": bool(getattr(decision, "ok", True)),
        "intent": normalize_intent(getattr(decision, "intent", "hold")),
        "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
        "target_qty": float(getattr(decision, "target_qty", 0.0) or 0.0),
        "target_price": float(getattr(decision, "target_price", 0.0) or 0.0),
        "reason": str(getattr(decision, "reason", "") or ""),
        "payload": payload if isinstance(payload, dict) else {},
    }


def build_context(
    strategy_id: str,
    rows: list[dict[str, Any]],
    position: dict[str, Any],
    regime: str,
    cost_profile: dict[str, Any],
) -> AttrBox:
    payload = {
        "ohlcv": rows,
        "candles": rows,
        "bars": rows,
        "symbol": rows[-1].get("symbol") or "UNKNOWN",
        "timeframe": rows[-1].get("timeframe") or "unknown",
        "position_side": position.get("side") or "",
        "position_qty": float(position.get("qty") or 0.0),
        "avg_entry": float(position.get("avg_entry") or 0.0),
        "add_count": int(position.get("add_count") or 0),
        "last_add_price": float(position.get("last_add_price") or 0.0),
        "risk_action": "hold",
        "fee_rate": float(cost_profile["fee_bps_per_side"]) / 10000.0,
        "slippage_bps": float(cost_profile["slippage_bps_per_side"]),
        "latency_bars": int(cost_profile["latency_bars"]),
        "funding_8h": float(cost_profile["funding_bps_per_8h"]) / 10000.0,
        "market_regime": regime,
    }
    return AttrBox(
        signal=AttrBox(payload=payload, symbol=payload["symbol"], strategy_id=strategy_id, confidence=1.0),
        risk=AttrBox(action="hold", blocked=False),
        position=AttrBox(side=payload["position_side"], qty=payload["position_qty"], avg_entry=payload["avg_entry"]),
        market=AttrBox(symbol=payload["symbol"], timeframe=payload["timeframe"]),
        metadata={"historical_simulation": True, "strategy_id": strategy_id, "regime": regime},
    )


@contextmanager
def side_effect_guard(attempts: list[str]) -> Iterator[None]:
    original_open = builtins.open
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    original_popen = subprocess.Popen
    original_run = subprocess.run
    original_check_call = subprocess.check_call
    original_check_output = subprocess.check_output
    original_system = os.system
    original_remove = os.remove
    original_unlink = os.unlink
    original_rename = os.rename
    original_replace = os.replace

    def deny(label: str):
        def blocked(*args: Any, **kwargs: Any) -> Any:
            attempts.append(label)
            raise SideEffectBlocked(label)
        return blocked

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            attempts.append(f"file_write:{file}")
            raise SideEffectBlocked(f"file_write:{file}")
        return original_open(file, mode, *args, **kwargs)

    builtins.open = guarded_open
    socket.socket.connect = deny("socket.connect")  # type: ignore[assignment]
    socket.create_connection = deny("socket.create_connection")  # type: ignore[assignment]
    subprocess.Popen = deny("subprocess.Popen")  # type: ignore[assignment]
    subprocess.run = deny("subprocess.run")  # type: ignore[assignment]
    subprocess.check_call = deny("subprocess.check_call")  # type: ignore[assignment]
    subprocess.check_output = deny("subprocess.check_output")  # type: ignore[assignment]
    os.system = deny("os.system")  # type: ignore[assignment]
    os.remove = deny("os.remove")  # type: ignore[assignment]
    os.unlink = deny("os.unlink")  # type: ignore[assignment]
    os.rename = deny("os.rename")  # type: ignore[assignment]
    os.replace = deny("os.replace")  # type: ignore[assignment]
    try:
        yield
    finally:
        builtins.open = original_open
        socket.socket.connect = original_connect  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]
        subprocess.Popen = original_popen  # type: ignore[assignment]
        subprocess.run = original_run  # type: ignore[assignment]
        subprocess.check_call = original_check_call  # type: ignore[assignment]
        subprocess.check_output = original_check_output  # type: ignore[assignment]
        os.system = original_system  # type: ignore[assignment]
        os.remove = original_remove  # type: ignore[assignment]
        os.unlink = original_unlink  # type: ignore[assignment]
        os.rename = original_rename  # type: ignore[assignment]
        os.replace = original_replace  # type: ignore[assignment]


def timestamp_hours(first: float, second: float) -> float:
    delta = max(float(second) - float(first), 0.0)
    magnitude = max(abs(float(first)), abs(float(second)))
    if magnitude >= 1e14:
        return delta / 3_600_000_000_000.0
    if magnitude >= 1e11:
        return delta / 3_600_000.0
    if magnitude >= 1e8:
        return delta / 3600.0
    return delta / 3600.0


def legacy_signal(fields: dict[str, Any]) -> dict[str, Any]:
    payload = fields.get("payload") if isinstance(fields.get("payload"), dict) else {}
    value = payload.get("legacy_signal")
    return value if isinstance(value, dict) else {}


def round_or_none(value: Any, digits: int = 10) -> float | None:
    try:
        number = float(value)
        return round(number, digits) if math.isfinite(number) else None
    except Exception:
        return None


def simulate_scenario(
    scenario: dict[str, Any],
    segment: pd.DataFrame,
    owner: type[Any],
    method_name: str,
    cost: dict[str, Any],
    perturbation: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    strategy_id = str(scenario["strategy_id"])
    regime = str(scenario["regime"])
    minimum_call_bars = int(contract["minimum_call_bars"])
    max_qty = float(contract["maximum_position_qty"])
    allowed_intents = {str(item) for item in contract.get("allowed_intents", [])}
    fee_rate = float(cost["fee_bps_per_side"]) / 10000.0
    slip_rate = float(cost["slippage_bps_per_side"]) / 10000.0
    funding_rate_8h = float(cost["funding_bps_per_8h"]) / 10000.0
    entry_delay = 1 + int(cost["latency_bars"]) + int(perturbation["additional_entry_delay_bars"])
    exit_delay = 1 + int(cost["latency_bars"]) + int(perturbation["additional_exit_delay_bars"])

    rows = segment.copy().reset_index(drop=True)
    public_columns = [column for column in rows.columns if not str(column).startswith("__")]
    row_records = rows[public_columns].to_dict(orient="records")
    timestamps = rows["__timestamp"].astype(float).tolist()
    instance = owner()

    position: dict[str, Any] = {
        "side": "",
        "qty": 0.0,
        "avg_entry": 0.0,
        "stop": 0.0,
        "tp": 0.0,
        "add_count": 0,
        "last_add_price": 0.0,
    }
    pending: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    current_trade: dict[str, Any] | None = None
    realized = 0.0
    total_cost = 0.0
    equity_peak = 1.0
    max_drawdown = 0.0
    exposure_bars = 0
    signal_count = 0
    enter_signal_count = 0
    add_signal_count = 0
    reduce_signal_count = 0
    exit_signal_count = 0
    short_shadow_signal_count = 0
    invalid_signal_count = 0
    intent_histogram: Counter[str] = Counter()

    def close_qty(quantity: float, raw_price: float, bar_index: int, reason: str) -> None:
        nonlocal realized, total_cost, current_trade
        quantity = min(max(float(quantity), 0.0), float(position["qty"]))
        if quantity <= 0 or position["qty"] <= 0:
            return
        fill = max(float(raw_price) * (1.0 - slip_rate), 1e-12)
        gross = quantity * (fill / float(position["avg_entry"]) - 1.0)
        fee = quantity * fee_rate
        net = gross - fee
        realized += net
        total_cost += fee
        if current_trade is not None:
            current_trade["gross_pnl_pct"] += gross * 100.0
            current_trade["net_pnl_pct"] += net * 100.0
            current_trade["cost_pct"] += fee * 100.0
            current_trade["exit_index"] = bar_index
            current_trade["exit_price"] = fill
            current_trade["exit_reason"] = reason
        remaining = float(position["qty"]) - quantity
        position["qty"] = max(remaining, 0.0)
        if position["qty"] <= 1e-12:
            if current_trade is not None:
                risk = max(float(current_trade["risk_capital_pct"]), 1e-12)
                current_trade["pnl_r"] = float(current_trade["net_pnl_pct"]) / risk
                current_trade["win"] = float(current_trade["net_pnl_pct"]) > 0
                trades.append(current_trade)
            current_trade = None
            position.update({"side": "", "qty": 0.0, "avg_entry": 0.0, "stop": 0.0, "tp": 0.0, "add_count": 0, "last_add_price": 0.0})

    def execute_action(action: dict[str, Any], bar_index: int, open_price: float) -> None:
        nonlocal realized, total_cost, current_trade, invalid_signal_count
        kind = action["kind"]
        target_qty = max(float(action.get("target_qty") or 0.0), 0.0)
        signal = action.get("legacy") if isinstance(action.get("legacy"), dict) else {}
        if kind in {"enter", "add"}:
            quantity = min(target_qty, max(max_qty - float(position["qty"]), 0.0))
            fill = max(open_price * (1.0 + slip_rate), 1e-12)
            stop = float(signal.get("sl") or 0.0)
            tp = float(signal.get("tp") or 0.0)
            if quantity <= 0 or not (0 < stop < fill < tp):
                invalid_signal_count += 1
                return
            fee = quantity * fee_rate
            realized -= fee
            total_cost += fee
            risk_pct = quantity * (fill - stop) / fill * 100.0
            old_qty = float(position["qty"])
            if old_qty <= 0:
                position.update({
                    "side": "long",
                    "qty": quantity,
                    "avg_entry": fill,
                    "stop": stop,
                    "tp": tp,
                    "add_count": 0,
                    "last_add_price": fill,
                })
                current_trade = {
                    "entry_index": bar_index,
                    "entry_price": fill,
                    "exit_index": None,
                    "exit_price": None,
                    "exit_reason": None,
                    "gross_pnl_pct": 0.0,
                    "net_pnl_pct": -fee * 100.0,
                    "cost_pct": fee * 100.0,
                    "risk_capital_pct": risk_pct,
                    "mfe_pct": 0.0,
                    "mae_pct": 0.0,
                    "pnl_r": None,
                    "win": False,
                }
            else:
                new_qty = old_qty + quantity
                position["avg_entry"] = (float(position["avg_entry"]) * old_qty + fill * quantity) / new_qty
                position["qty"] = new_qty
                position["stop"] = max(float(position["stop"]), stop)
                position["tp"] = max(float(position["tp"]), tp)
                position["add_count"] = int(position["add_count"]) + 1
                position["last_add_price"] = fill
                if current_trade is not None:
                    current_trade["net_pnl_pct"] -= fee * 100.0
                    current_trade["cost_pct"] += fee * 100.0
                    current_trade["risk_capital_pct"] += risk_pct
        elif kind == "reduce" and position["qty"] > 0:
            close_qty(target_qty if target_qty > 0 else float(position["qty"]), open_price, bar_index, "signal_reduce")
        elif kind == "exit" and position["qty"] > 0:
            close_qty(float(position["qty"]), open_price, bar_index, "signal_exit")

    for index in range(len(rows)):
        bar = rows.iloc[index]
        open_price = float(bar["open"])
        high_price = float(bar["high"])
        low_price = float(bar["low"])
        close_price = float(bar["close"])

        due = [action for action in pending if int(action["execute_index"]) == index]
        pending = [action for action in pending if int(action["execute_index"]) != index]
        for action in due:
            execute_action(action, index, open_price)

        if position["qty"] > 0:
            exposure_bars += 1
            if index > 0:
                hours = timestamp_hours(timestamps[index - 1], timestamps[index])
                funding = float(position["qty"]) * funding_rate_8h * hours / 8.0
                realized -= funding
                total_cost += funding
                if current_trade is not None:
                    current_trade["net_pnl_pct"] -= funding * 100.0
                    current_trade["cost_pct"] += funding * 100.0
            if current_trade is not None:
                avg = max(float(position["avg_entry"]), 1e-12)
                current_trade["mfe_pct"] = max(float(current_trade["mfe_pct"]), (high_price / avg - 1.0) * 100.0)
                current_trade["mae_pct"] = min(float(current_trade["mae_pct"]), (low_price / avg - 1.0) * 100.0)
            stop_hit = low_price <= float(position["stop"])
            tp_hit = high_price >= float(position["tp"])
            if stop_hit:
                raw_exit = min(open_price, float(position["stop"]))
                close_qty(float(position["qty"]), raw_exit, index, "stop_collision" if tp_hit else "stop")
            elif tp_hit:
                raw_exit = max(open_price, float(position["tp"]))
                close_qty(float(position["qty"]), raw_exit, index, "take_profit")

        unrealized = 0.0
        if position["qty"] > 0:
            unrealized = float(position["qty"]) * (close_price / float(position["avg_entry"]) - 1.0)
        equity = 1.0 + realized + unrealized - (float(position["qty"]) * fee_rate if position["qty"] > 0 else 0.0)
        equity_peak = max(equity_peak, equity)
        if equity_peak > 0:
            max_drawdown = min(max_drawdown, equity / equity_peak - 1.0)

        if index + 1 < minimum_call_bars or index >= len(rows) - 1:
            continue
        ctx = build_context(strategy_id, row_records[: index + 1], position, regime, cost)
        decision = getattr(instance, method_name)(ctx)
        fields = decision_fields(decision)
        intent = str(fields["intent"])
        intent_histogram[intent] += 1
        if intent not in allowed_intents:
            raise ValueError(f"OUTPUT_INTENT_NOT_ALLOWED:{intent}")
        legacy = legacy_signal(fields)
        if str(legacy.get("side") or "").lower() == "short" and str(legacy.get("action") or "").lower() in {"enter", "add"}:
            short_shadow_signal_count += 1
        if not fields["ok"] or intent in {"hold", "block"}:
            continue
        signal_count += 1
        legacy_action = str(legacy.get("action") or "").lower()
        target_qty = float(fields.get("target_qty") or legacy.get("size") or 0.0)
        if intent == "enter_long":
            kind = "add" if position["qty"] > 0 and legacy_action == "add" else "enter"
            if kind == "enter" and (position["qty"] > 0 or any(item["kind"] == "enter" for item in pending)):
                continue
            if kind == "add" and (position["qty"] <= 0 or any(item["kind"] == "add" for item in pending)):
                continue
            execute_index = index + entry_delay
            if execute_index < len(rows):
                pending.append({"kind": kind, "execute_index": execute_index, "target_qty": target_qty, "legacy": legacy})
                if kind == "enter":
                    enter_signal_count += 1
                else:
                    add_signal_count += 1
        elif intent == "reduce" and position["qty"] > 0:
            execute_index = index + exit_delay
            if execute_index < len(rows) and not any(item["kind"] == "reduce" for item in pending):
                pending.append({"kind": "reduce", "execute_index": execute_index, "target_qty": target_qty, "legacy": legacy})
                reduce_signal_count += 1
        elif intent == "exit_long" and position["qty"] > 0:
            execute_index = index + exit_delay
            if execute_index < len(rows) and not any(item["kind"] == "exit" for item in pending):
                pending.append({"kind": "exit", "execute_index": execute_index, "target_qty": float(position["qty"]), "legacy": legacy})
                exit_signal_count += 1

    if position["qty"] > 0:
        close_qty(float(position["qty"]), float(rows.iloc[-1]["close"]), len(rows) - 1, "segment_end")

    trade_returns = [float(trade["net_pnl_pct"]) for trade in trades]
    pnl_rs = [float(trade["pnl_r"]) for trade in trades if trade.get("pnl_r") is not None]
    wins = [value for value in trade_returns if value > 0]
    losses = [value for value in trade_returns if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    final_equity = 1.0 + realized
    return {
        "scenario_id": scenario["scenario_id"],
        "strategy_id": strategy_id,
        "segment_id": scenario["segment_id"],
        "regime": regime,
        "fold": int(scenario["fold"]),
        "cost_profile": scenario["cost_profile"],
        "perturbation": scenario["perturbation"],
        "completed": True,
        "error": None,
        "bars": len(rows),
        "strategy_call_count": max(len(rows) - minimum_call_bars, 0),
        "signal_count": signal_count,
        "enter_signal_count": enter_signal_count,
        "add_signal_count": add_signal_count,
        "reduce_signal_count": reduce_signal_count,
        "exit_signal_count": exit_signal_count,
        "short_shadow_signal_count": short_shadow_signal_count,
        "invalid_signal_count": invalid_signal_count,
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100.0, 10) if trades else 0.0,
        "net_return_pct": round((final_equity - 1.0) * 100.0, 10),
        "total_cost_pct": round(total_cost * 100.0, 10),
        "max_drawdown_pct": round(max_drawdown * 100.0, 10),
        "profit_factor": round(profit_factor, 10) if math.isfinite(profit_factor) else "Infinity",
        "expectancy_r": round(statistics.fmean(pnl_rs), 10) if pnl_rs else 0.0,
        "median_r": round(statistics.median(pnl_rs), 10) if pnl_rs else 0.0,
        "mean_mfe_pct": round(statistics.fmean(float(trade["mfe_pct"]) for trade in trades), 10) if trades else 0.0,
        "mean_mae_pct": round(statistics.fmean(float(trade["mae_pct"]) for trade in trades), 10) if trades else 0.0,
        "exposure_pct": round(exposure_bars / len(rows) * 100.0, 10),
        "intent_histogram": dict(sorted(intent_histogram.items())),
        "trade_exit_histogram": dict(sorted(Counter(str(trade["exit_reason"]) for trade in trades).items())),
        "trade_sample": trades[:5],
    }


def numeric_metric(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(float(value))
    return values


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("completed") is True]
    net = numeric_metric(completed, "net_return_pct")
    dd = numeric_metric(completed, "max_drawdown_pct")
    expectancy = numeric_metric(completed, "expectancy_r")
    trades = sum(int(row.get("trade_count") or 0) for row in completed)
    active = sum(1 for row in completed if int(row.get("trade_count") or 0) > 0)
    return {
        "scenario_count": len(rows),
        "completed_count": len(completed),
        "failed_count": len(rows) - len(completed),
        "trade_count": trades,
        "active_scenario_count": active,
        "active_scenario_rate_pct": round(active / len(completed) * 100.0, 10) if completed else 0.0,
        "net_return_mean_pct": round(statistics.fmean(net), 10) if net else 0.0,
        "net_return_median_pct": round(statistics.median(net), 10) if net else 0.0,
        "net_return_worst_pct": round(min(net), 10) if net else 0.0,
        "max_drawdown_mean_pct": round(statistics.fmean(dd), 10) if dd else 0.0,
        "max_drawdown_worst_pct": round(min(dd), 10) if dd else 0.0,
        "expectancy_r_mean": round(statistics.fmean(expectancy), 10) if expectancy else 0.0,
        "diagnostic_robustness_score": round(
            (statistics.median(net) if net else 0.0)
            + (min(net) if net else 0.0) * 0.25
            + (statistics.fmean(dd) if dd else 0.0) * 0.5,
            10,
        ),
    }


def aggregate_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_cost: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_perturbation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_strategy[str(row.get("strategy_id"))].append(row)
        by_regime[str(row.get("regime"))].append(row)
        by_cost[str(row.get("cost_profile"))].append(row)
        by_perturbation[str(row.get("perturbation"))].append(row)
    strategy_summary = {key: summarize_rows(value) for key, value in sorted(by_strategy.items())}
    ranking = sorted(
        (
            {
                "strategy_id": strategy_id,
                **summary,
            }
            for strategy_id, summary in strategy_summary.items()
        ),
        key=lambda row: (-float(row["diagnostic_robustness_score"]), row["strategy_id"]),
    )
    return {
        "overall": summarize_rows(rows),
        "by_strategy": strategy_summary,
        "by_regime": {key: summarize_rows(value) for key, value in sorted(by_regime.items())},
        "by_cost_profile": {key: summarize_rows(value) for key, value in sorted(by_cost.items())},
        "by_perturbation": {key: summarize_rows(value) for key, value in sorted(by_perturbation.items())},
        "diagnostic_ranking_not_promotion": ranking,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    expected_strategies = int(contract.get("expected_strategy_count", 25))
    expected_segments = int(contract.get("expected_segment_count", 24))
    expected_runs = int(contract.get("expected_scenario_run_count", 3600))
    prior_status = load_json(root / str(contract["prior_status_path"]))
    manifest = load_json(root / str(contract["selected_manifest_path"]))
    plan = load_json(root / str(contract["scenario_plan_path"]))
    registry_path = root / str(contract["registry_path"])
    registry = load_json(registry_path)
    blockers: list[str] = []

    if not prior_gate(prior_status, expected_strategies, expected_segments, expected_runs):
        blockers.append("PRIOR_A4C_STATUS_INVALID")
    lineage_id = prior_status.get("lineage_id")
    if manifest.get("state") != "PASS" or manifest.get("lineage_id") != lineage_id:
        blockers.append("A4C_SELECTED_MANIFEST_MISMATCH")
    if plan.get("state") != "PASS" or plan.get("lineage_id") != lineage_id:
        blockers.append("A4C_SCENARIO_PLAN_MISMATCH")

    scenarios = [row for row in plan.get("scenarios", []) if isinstance(row, dict)]
    if len(scenarios) != expected_runs or len({row.get("scenario_id") for row in scenarios}) != expected_runs:
        blockers.append(f"SCENARIO_PLAN_INVALID:{len(scenarios)}")
    cost_profiles = {str(row["id"]): row for row in contract.get("cost_profiles", []) if isinstance(row, dict) and row.get("id")}
    perturbations = {str(row["id"]): row for row in contract.get("perturbations", []) if isinstance(row, dict) and row.get("id")}
    if sorted(cost_profiles) != ["cost_profile_0", "cost_profile_1", "cost_profile_2"]:
        blockers.append("COST_PROFILE_CONTRACT_INVALID")
    if sorted(perturbations) != ["perturbation_0", "perturbation_1"]:
        blockers.append("PERTURBATION_CONTRACT_INVALID")

    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    if len(entries) != expected_strategies or int(registry.get("active_entry_count", -1)) != 0:
        blockers.append("CANONICAL_REGISTRY_INVALID")
    entry_by_id = {str(row.get("strategy_id")): row for row in entries}
    selected_segments = [row for row in manifest.get("selected_segments", []) if isinstance(row, dict)]
    if len(selected_segments) != expected_segments:
        blockers.append(f"SELECTED_SEGMENT_COUNT_INVALID:{len(selected_segments)}")
    segment_by_id = {str(row.get("segment_id")): row for row in selected_segments}

    canonical_paths = [registry_path, root / "backend/strategy25/canonical_strategy25_config_v1.json"]
    for row in entries:
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        try:
            canonical_paths.append(root / safe_repo_path(str(engine.get("implementation_path") or "")))
        except ValueError as exc:
            blockers.append(str(exc))
    protected_paths = [Path(str(item)) for item in contract.get("protected_paths", [])]
    before = snapshot(canonical_paths + protected_paths)

    segment_frames: dict[str, pd.DataFrame] = {}
    for segment in selected_segments:
        try:
            segment_id = str(segment["segment_id"])
            source_path = safe_repo_path(str(segment["source_path"]))
            path = root / source_path
            if sha256_file(path) != segment.get("source_sha256"):
                raise ValueError("SEGMENT_SOURCE_SHA_MISMATCH")
            frame = load_market_frame(path)
            start = int(segment["start_row"])
            stop = int(segment["end_row_exclusive"])
            sample = frame.iloc[start:stop].copy().reset_index(drop=True)
            if len(sample) != int(contract["segment_bars"]):
                raise ValueError(f"SEGMENT_BAR_COUNT_INVALID:{len(sample)}")
            segment_frames[segment_id] = sample
        except Exception as exc:
            blockers.append(f"SEGMENT_LOAD_FAILED:{segment.get('segment_id')}:{type(exc).__name__}:{exc}")

    strategy_bindings: dict[str, tuple[type[Any], str]] = {}
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    try:
        for strategy_id, row in sorted(entry_by_id.items()):
            try:
                engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
                repo_path = safe_repo_path(str(engine.get("implementation_path") or ""))
                path = root / repo_path
                expected_sha = str(engine.get("source_sha256") or "")
                if expected_sha and sha256_file(path) != expected_sha:
                    raise ValueError("STRATEGY_SOURCE_SHA_MISMATCH")
                module = load_module(root, repo_path, strategy_id)
                strategy_bindings[strategy_id] = resolve_callable(module, str(engine.get("callable") or ""))
            except Exception as exc:
                blockers.append(f"STRATEGY_BIND_FAILED:{strategy_id}:{type(exc).__name__}:{exc}")
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    if blockers:
        status = {
            "official_stage": "R7.A4D",
            "state": "HOLD",
            "blocker_count": len(list(dict.fromkeys(blockers))),
            "blockers": list(dict.fromkeys(blockers)),
            "scenario_plan_count": len(scenarios),
            "historical_simulation_execution_count": 0,
            "completed_scenario_count": 0,
            "failed_scenario_count": 0,
            "next_stage": str(contract["next_stage_fail"]),
        }
        atomic_json(root / str(contract["status_path"]), status)
        for key in ("state", "blocker_count", "scenario_plan_count", "historical_simulation_execution_count", "completed_scenario_count", "failed_scenario_count", "next_stage"):
            print(f"{key.upper()}={status[key]}")
        print("BLOCKERS=" + json.dumps(status["blockers"], ensure_ascii=False))
        print("RC=2")
        return 2

    results: list[dict[str, Any]] = []
    side_effect_attempts: list[str] = []
    sys.path.insert(0, str(root))
    try:
        with side_effect_guard(side_effect_attempts):
            for index, scenario in enumerate(scenarios, start=1):
                strategy_id = str(scenario["strategy_id"])
                segment_id = str(scenario["segment_id"])
                try:
                    owner, method_name = strategy_bindings[strategy_id]
                    row = simulate_scenario(
                        scenario,
                        segment_frames[segment_id],
                        owner,
                        method_name,
                        cost_profiles[str(scenario["cost_profile"])],
                        perturbations[str(scenario["perturbation"])],
                        contract,
                    )
                except Exception as exc:
                    row = {
                        "scenario_id": scenario.get("scenario_id"),
                        "strategy_id": strategy_id,
                        "segment_id": segment_id,
                        "regime": scenario.get("regime"),
                        "fold": scenario.get("fold"),
                        "cost_profile": scenario.get("cost_profile"),
                        "perturbation": scenario.get("perturbation"),
                        "completed": False,
                        "error": f"{type(exc).__name__}:{exc}",
                    }
                results.append(row)
                if index % 100 == 0 or index == expected_runs:
                    completed_now = sum(1 for item in results if item.get("completed") is True)
                    print(f"A4D_PROGRESS={index}/{expected_runs} COMPLETED={completed_now} FAILED={index - completed_now}", flush=True)
    finally:
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass

    after = snapshot(canonical_paths + protected_paths)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    canonical_set = {str(path) for path in canonical_paths}
    protected_set = {str(path) for path in protected_paths}
    canonical_mutation_count = sum(1 for path in mutation_paths if path in canonical_set)
    protected_change_count = sum(1 for path in mutation_paths if path in protected_set)
    completed_count = sum(1 for row in results if row.get("completed") is True)
    failed_count = len(results) - completed_count
    error_histogram = Counter(str(row.get("error") or "").split(":", 1)[0] for row in results if row.get("completed") is not True)

    aggregate = aggregate_results(results)
    aggregate.update({
        "schema": "r7a4d_historical_simulation_3600_aggregate_v1",
        "official_stage": "R7.A4D",
        "lineage_id": lineage_id,
        "simulation_assumption_scope": contract.get("simulation_assumption_scope"),
        "cost_profiles": list(cost_profiles.values()),
        "perturbations": list(perturbations.values()),
        "intrabar_collision_policy": contract.get("intrabar_collision_policy"),
        "end_of_segment_policy": contract.get("end_of_segment_policy"),
    })

    all_blockers: list[str] = []
    if len(results) != expected_runs:
        all_blockers.append(f"EXECUTION_COUNT_INVALID:{len(results)}")
    if completed_count != expected_runs:
        all_blockers.append(f"SCENARIO_FAILURES:{failed_count}")
    if side_effect_attempts:
        all_blockers.append(f"SIDE_EFFECT_ATTEMPTS:{len(side_effect_attempts)}")
    if mutation_paths:
        all_blockers.append("CANONICAL_OR_PROTECTED_MUTATION_DETECTED")
    success = bool(
        not all_blockers
        and len(results) == expected_runs
        and completed_count == expected_runs
        and failed_count == 0
        and not side_effect_attempts
        and canonical_mutation_count == 0
        and protected_change_count == 0
    )
    state = "PASS" if success else "HOLD"
    next_stage = str(contract["next_stage_pass"] if success else contract["next_stage_fail"])

    results_path = root / str(contract["scenario_results_path"])
    results_hash = atomic_jsonl(results_path, results)
    aggregate["state"] = state
    aggregate["scenario_results_sha256"] = results_hash
    atomic_json(root / str(contract["aggregate_path"]), aggregate)
    proof = {
        "schema": "r7a4d_historical_simulation_3600_proof_v1",
        "official_stage": "R7.A4D",
        "state": state,
        "target_commit": args.target_sha,
        "lineage_id": lineage_id,
        "scenario_results_sha256": results_hash,
        "mutation_paths": mutation_paths,
        "side_effect_attempts": side_effect_attempts,
        "error_histogram": dict(sorted(error_histogram.items())),
        "blockers": all_blockers,
    }
    atomic_json(root / str(contract["proof_path"]), proof)
    status = {
        "official_stage": "R7.A4D",
        "state": state,
        "blocker_count": len(all_blockers),
        "blockers": all_blockers,
        "strategy_count": len(strategy_bindings),
        "historical_segment_count": len(segment_frames),
        "scenario_plan_count": len(scenarios),
        "historical_simulation_execution_count": len(results),
        "completed_scenario_count": completed_count,
        "failed_scenario_count": failed_count,
        "strategy_call_count": sum(int(row.get("strategy_call_count") or 0) for row in results),
        "closed_trade_count": sum(int(row.get("trade_count") or 0) for row in results),
        "active_scenario_count": sum(1 for row in results if int(row.get("trade_count") or 0) > 0),
        "short_shadow_signal_count": sum(int(row.get("short_shadow_signal_count") or 0) for row in results),
        "invalid_signal_count": sum(int(row.get("invalid_signal_count") or 0) for row in results),
        "side_effect_attempt_count": len(side_effect_attempts),
        "canonical_mutation_count": canonical_mutation_count,
        "protected_change_count": protected_change_count,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "shadow_start_count": 0,
        "paper_live_order_count": 0,
        "lineage_id": lineage_id,
        "scenario_results_sha256": results_hash,
        "next_stage": next_stage,
        "scenario_results_path": str(results_path),
        "aggregate_path": str(root / str(contract["aggregate_path"])),
        "proof_path": str(root / str(contract["proof_path"])),
    }
    atomic_json(root / str(contract["status_path"]), status)

    for key in (
        "state", "blocker_count", "strategy_count", "historical_segment_count",
        "scenario_plan_count", "historical_simulation_execution_count",
        "completed_scenario_count", "failed_scenario_count", "strategy_call_count",
        "closed_trade_count", "active_scenario_count", "short_shadow_signal_count",
        "invalid_signal_count", "side_effect_attempt_count", "canonical_mutation_count",
        "protected_change_count", "router_mutation_count", "service_mutation_count",
        "shadow_start_count", "paper_live_order_count", "lineage_id",
        "scenario_results_sha256", "next_stage",
    ):
        print(f"{key.upper()}={status[key]}")
    print("ERROR_HISTOGRAM=" + json.dumps(dict(sorted(error_histogram.items())), ensure_ascii=False))
    print("BLOCKERS=" + json.dumps(all_blockers, ensure_ascii=False))
    print("SCENARIO_RESULTS_JSONL=" + status["scenario_results_path"])
    print("AGGREGATE_JSON=" + status["aggregate_path"])
    print("PROOF_JSON=" + status["proof_path"])
    print("RC=" + ("0" if success else "2"))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
