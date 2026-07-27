from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
import math
import os
import sys
import tempfile
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EXACT_PATH = ROOT / "backend/tools/r7a4d_strategy11_exact.py"
INTERVAL_MS = 900_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
FRESH_ROLES = ("F1", "F2", "F3")
SEALED_ROLES = ("Z1", "Z2")
ALL_ROLES = FRESH_ROLES + SEALED_ROLES
PIPELINE_VERSION = "R7A4D_STRATEGY11_EVIDENCE_PIPELINE_V1"
FUNDING_ENDPOINTS = (
    "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate",
    "https://open-api.bingx.com/openApi/swap/v3/quote/fundingRate",
)


def _load_exact() -> Any:
    name = "r7a4d_strategy11_exact_for_evidence_v1"
    spec = importlib.util.spec_from_file_location(name, EXACT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("EXACT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


exact = _load_exact()
base = exact.base


def strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_sha(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def metric(value: Any, default: float = 0.0) -> float:
    return float(value) if finite(value) else default


def iso(ms: int) -> str:
    return pd.Timestamp(ms, unit="ms", tz="UTC").isoformat()


def align_closed_end(now_ms: int) -> int:
    return ((now_ms // INTERVAL_MS) - 1) * INTERVAL_MS


def validate_frame(frame: pd.DataFrame, *, start_ms: int, end_ms: int, expected_rows: int) -> list[str]:
    blockers: list[str] = []
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return ["COLUMNS_MISSING:" + ",".join(sorted(required - set(frame.columns)))]
    if len(frame) != expected_rows:
        blockers.append(f"ROWS:{len(frame)}!={expected_rows}")
    timestamps = pd.to_numeric(frame["timestamp_ms"], errors="coerce")
    if timestamps.isna().any():
        blockers.append("TIMESTAMP_NONNUMERIC")
    else:
        ts = timestamps.astype("int64")
        if ts.duplicated().any():
            blockers.append("DUPLICATE_TIMESTAMP")
        if not ts.is_monotonic_increasing:
            blockers.append("TIMESTAMP_NOT_SORTED")
        if len(ts) > 1 and not bool((ts.diff().dropna() == INTERVAL_MS).all()):
            blockers.append("TIMESTAMP_GAP")
        if len(ts) and (int(ts.iloc[0]) != start_ms or int(ts.iloc[-1]) != end_ms):
            blockers.append("BOUNDARY_MISMATCH")
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        blockers.append("OHLCV_NONFINITE")
    if bool((numeric[["open", "high", "low", "close"]] <= 0.0).any().any()):
        blockers.append("PRICE_NONPOSITIVE")
    if bool((numeric["volume"] < 0.0).any()):
        blockers.append("VOLUME_NEGATIVE")
    if bool((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()):
        blockers.append("HIGH_INVARIANT")
    if bool((numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()):
        blockers.append("LOW_INVARIANT")
    return blockers


def _funding_rows(payload: Mapping[str, Any]) -> list[Any]:
    data: Any = payload.get("data")
    if isinstance(data, Mapping):
        for key in ("data", "rows", "list", "fundingRates"):
            if isinstance(data.get(key), list):
                return list(data[key])
    return list(data) if isinstance(data, list) else []


def _parse_funding(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    raw_ts = row.get("fundingTime", row.get("time", row.get("timestamp")))
    raw_rate = row.get("fundingRate", row.get("rate"))
    try:
        timestamp_ms = int(float(raw_ts))
        if timestamp_ms < 10_000_000_000:
            timestamp_ms *= 1000
        elif timestamp_ms > 10_000_000_000_000:
            timestamp_ms //= 1000
        rate = float(raw_rate)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rate):
        return None
    return {"timestamp_ms": timestamp_ms, "funding_rate": rate}


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    for endpoint in FUNDING_ENDPOINTS:
        try:
            query = urllib.parse.urlencode({
                "symbol": symbol[:-4] + "-USDT",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            })
            payload = base._request_json(endpoint + "?" + query)
            if payload.get("code") not in (None, 0, "0"):
                raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
            rows = [item for item in (_parse_funding(row) for row in _funding_rows(payload)) if item]
            rows = sorted({int(row["timestamp_ms"]): row for row in rows}.values(), key=lambda row: row["timestamp_ms"])
            rows = [row for row in rows if start_ms <= int(row["timestamp_ms"]) <= end_ms]
            if not rows:
                raise ValueError("NO_FUNDING_ROWS")
            return rows, endpoint
        except Exception as exc:
            errors.append(f"{endpoint}:{type(exc).__name__}:{exc}")
    raise RuntimeError("FUNDING_FETCH_FAILED:" + "|".join(errors))


def authority_last_end(manifest: Mapping[str, Any]) -> int:
    rows = [row for row in manifest.get("rows", []) if isinstance(row, Mapping)]
    values = [int(row.get("end_ms") or 0) for row in rows]
    if not values or max(values) <= 0:
        raise ValueError("AUTHORITY_MANIFEST_END_MISSING")
    return max(values)


def prepare_data(args: argparse.Namespace) -> int:
    authority_manifest_path = Path(args.authority_manifest).resolve()
    out = Path(args.out).resolve()
    ssot = strict_json(Path(args.ssot).resolve())
    authority_manifest = strict_json(authority_manifest_path)
    last_authority_end_ms = authority_last_end(authority_manifest)
    evaluation_bars = int(args.evaluation_bars)
    warmup_bars = int(args.warmup_bars)
    expected_rows = evaluation_bars + warmup_bars
    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000) if args.as_of_ms is None else int(args.as_of_ms)
    latest_end_ms = align_closed_end(now_ms)
    total_eval_bars = evaluation_bars * len(ALL_ROLES)
    first_eval_start = latest_end_ms - (total_eval_bars - 1) * INTERVAL_MS

    blockers: list[str] = []
    if first_eval_start <= last_authority_end_ms:
        blockers.append(f"INSUFFICIENT_NEW_DATA:{iso(first_eval_start)}<={iso(last_authority_end_ms)}")

    windows: list[dict[str, Any]] = []
    for index, role in enumerate(ALL_ROLES):
        eval_start = first_eval_start + index * evaluation_bars * INTERVAL_MS
        eval_end = eval_start + (evaluation_bars - 1) * INTERVAL_MS
        fetch_start = eval_start - warmup_bars * INTERVAL_MS
        windows.append({
            "window_id": role,
            "kind": "FRESH" if role in FRESH_ROLES else "SEALED_FINAL_HOLDBACK",
            "evaluation_start_ms": eval_start,
            "evaluation_end_ms": eval_end,
            "evaluation_start": iso(eval_start),
            "evaluation_end": iso(eval_end),
            "fetch_start_ms": fetch_start,
            "fetch_end_ms": eval_end,
            "fetch_rows": expected_rows,
            "warmup_bars": warmup_bars,
            "evaluation_bars": evaluation_bars,
        })

    data_rows: list[dict[str, Any]] = []
    if not blockers:
        for window in windows:
            role = str(window["window_id"])
            target_root = out / ("fresh" if role in FRESH_ROLES else "sealed")
            for symbol in SYMBOLS:
                try:
                    frame, endpoint, requests = base._fetch_exact(
                        symbol,
                        start_ms=int(window["fetch_start_ms"]),
                        end_ms=int(window["fetch_end_ms"]),
                        expected_rows=expected_rows,
                    )
                    errors = validate_frame(frame, start_ms=int(window["fetch_start_ms"]), end_ms=int(window["fetch_end_ms"]), expected_rows=expected_rows)
                    if errors:
                        raise ValueError("|".join(errors))
                    path = target_root / "market" / f"{role}-{symbol}.csv"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_csv(path, index=False)
                    data_rows.append({
                        **window,
                        "symbol": symbol,
                        "state": "PASS",
                        "source": endpoint,
                        "request_count": requests,
                        "path": str(path.relative_to(out)),
                        "sha256": sha256(path),
                    })
                except Exception as exc:
                    error = f"MARKET_FETCH:{role}:{symbol}:{type(exc).__name__}:{exc}"
                    blockers.append(error)
                    data_rows.append({**window, "symbol": symbol, "state": "HOLD", "error": error})

    funding_rows: dict[str, list[dict[str, Any]]] = {}
    funding_sources: dict[str, str] = {}
    funding_start = int(windows[0]["evaluation_start_ms"]) if windows else 0
    funding_end = int(windows[-1]["evaluation_end_ms"]) if windows else 0
    if not blockers:
        for symbol in SYMBOLS:
            try:
                rows, endpoint = fetch_funding(symbol, funding_start, funding_end)
                funding_rows[symbol] = rows
                funding_sources[symbol] = endpoint
                path = out / "fresh" / "funding" / f"{symbol}.json"
                atomic_json(path, {"symbol": symbol, "source": endpoint, "rows": rows})
            except Exception as exc:
                blockers.append(f"FUNDING:{symbol}:{type(exc).__name__}:{exc}")

    fresh_rows = [row for row in data_rows if row.get("kind") == "FRESH"]
    sealed_rows = [row for row in data_rows if row.get("kind") == "SEALED_FINAL_HOLDBACK"]
    common = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "authority": "READ_ONLY_NEW_DATA_EVIDENCE_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "authority_manifest_sha256": sha256(authority_manifest_path),
        "authority_data_set_sha256": authority_manifest.get("data_set_sha256"),
        "authority_last_end_ms": last_authority_end_ms,
        "authority_last_end": iso(last_authority_end_ms),
        "as_of_ms": now_ms,
        "latest_closed_end_ms": latest_end_ms,
        "latest_closed_end": iso(latest_end_ms),
        "interval_ms": INTERVAL_MS,
        "evaluation_bars": evaluation_bars,
        "warmup_bars": warmup_bars,
        "symbols": list(SYMBOLS),
        "evaluation_periods_non_overlapping": True,
        "warmup_overlap_allowed": True,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
    }
    fresh_manifest = {
        **common,
        "kind": "FRESH_RESEARCH",
        "window_count": len(FRESH_ROLES),
        "windows": [window for window in windows if window["window_id"] in FRESH_ROLES],
        "files": fresh_rows,
        "funding_sources": funding_sources,
        "funding_event_counts": {symbol: len(rows) for symbol, rows in funding_rows.items()},
        "combined_fee_slippage_bps_per_side": ssot["cost_stress"]["combined_fee_slippage_bps_per_side"],
        "combined_cost_source": ssot["cost_stress"]["combined_cost_source"],
    }
    sealed_manifest = {
        **common,
        "kind": "SEALED_FINAL_HOLDBACK",
        "window_count": len(SEALED_ROLES),
        "windows": [window for window in windows if window["window_id"] in SEALED_ROLES],
        "files": sealed_rows,
        "sealed": True,
        "repair_read_allowed": False,
        "one_shot_only": True,
    }
    atomic_json(out / "fresh" / "manifest.json", fresh_manifest)
    atomic_json(out / "sealed" / "manifest.json", sealed_manifest)
    atomic_json(out / "summary.json", {
        **common,
        "fresh_manifest_sha256": sha256(out / "fresh" / "manifest.json"),
        "sealed_manifest_sha256": sha256(out / "sealed" / "manifest.json"),
        "fresh_file_count": len(fresh_rows),
        "sealed_file_count": len(sealed_rows),
        "next": "EVALUATE_BASELINE_EVIDENCE" if not blockers else "WAIT_DATA_OR_REPAIR_SOURCE",
    })
    print(json.dumps({"STATE": common["state"], "BLOCKERS": blockers, "LATEST": iso(latest_end_ms)}, sort_keys=True))
    return 0


@dataclass(frozen=True)
class EvidenceSurgery:
    surgery_id: str
    feature: str
    kind: str
    value: Any
    block_when: str


@dataclass
class EvidencePosition:
    qty: float
    initial_qty: float
    entry: float
    risk: float
    sl: float
    initial_sl: float
    tp: float
    initial_tp: float
    opened_at: str
    opened_index: int
    signal_ts: str
    why: str
    skill: str
    tags: tuple[str, ...]
    features: dict[str, Any]
    entry_cost_pct: float
    bars_open: int = 0
    realized_pct: float = 0.0
    realized_cost_pct: float = 0.0
    partial_done: bool = False
    pending_stop: float | None = None
    max_high: float = -math.inf
    min_low: float = math.inf
    max_high_index: int = 0
    min_low_index: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    qty_timeline: list[dict[str, Any]] = field(default_factory=list)


def surgery_from(value: Mapping[str, Any] | None) -> EvidenceSurgery | None:
    if not value:
        return None
    return EvidenceSurgery(
        surgery_id=str(value.get("surgery_id") or "UNKNOWN"),
        feature=str(value.get("feature") or ""),
        kind=str(value.get("kind") or "numeric"),
        value=value.get("value"),
        block_when=str(value.get("block_when") or "GE"),
    )


def surgery_allows(spec: EvidenceSurgery | None, features: Mapping[str, Any]) -> bool:
    if spec is None:
        return True
    raw = features.get(spec.feature)
    if spec.kind == "bool":
        matched = bool(raw) is bool(spec.value)
    elif not finite(raw):
        matched = False
    elif spec.block_when == "LE":
        matched = float(raw) <= float(spec.value)
    else:
        matched = float(raw) >= float(spec.value)
    return not matched


def close_trade(position: EvidencePosition, *, exit_price: float, exit_ts: str, exit_index: int, reason: str, cost_rate: float, symbol: str, window_id: str, path_ambiguous: bool = False) -> dict[str, Any]:
    gross = position.qty * ((exit_price / position.entry) - 1.0) * 100.0
    exit_cost = position.qty * cost_rate * 100.0
    net_before_funding = position.realized_pct + gross - position.entry_cost_pct - position.realized_cost_pct - exit_cost
    mfe_pct = ((position.max_high / position.entry) - 1.0) * 100.0 if position.max_high > 0 else 0.0
    mae_pct = ((position.entry / position.min_low) - 1.0) * 100.0 if position.min_low > 0 else 0.0
    risk_pct = position.risk / position.entry * 100.0
    return {
        "window_id": window_id,
        "symbol": symbol,
        "entry_ts": position.opened_at,
        "exit_ts": exit_ts,
        "entry_price": position.entry,
        "exit_price": exit_price,
        "initial_qty": position.initial_qty,
        "final_qty": position.qty,
        "initial_sl": position.initial_sl,
        "initial_tp": position.initial_tp,
        "risk_price": position.risk,
        "risk_pct": risk_pct,
        "gross_and_realized_return_pct": position.realized_pct + gross,
        "entry_cost_pct": position.entry_cost_pct,
        "realized_partial_cost_pct": position.realized_cost_pct,
        "exit_cost_pct": exit_cost,
        "net_return_pct_before_funding": net_before_funding,
        "net_return_pct": net_before_funding,
        "exit_reason": reason,
        "signal_ts": position.signal_ts,
        "signal_why": position.why,
        "signal_skill": position.skill,
        "signal_tags": list(position.tags),
        "features": position.features,
        "mfe_price": position.max_high,
        "mae_price": position.min_low,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "mfe_r": mfe_pct / risk_pct if risk_pct > 0 else None,
        "mae_r": mae_pct / risk_pct if risk_pct > 0 else None,
        "bars_to_mfe": position.max_high_index - position.opened_index,
        "bars_to_mae": position.min_low_index - position.opened_index,
        "bars_held": max(0, exit_index - position.opened_index + 1),
        "events": position.events,
        "qty_timeline": position.qty_timeline,
        "path_ambiguous": path_ambiguous,
    }


def replay_evidence(frame: pd.DataFrame, features: pd.DataFrame, strategy: Callable[..., dict[str, Any]], gate: Any, exit_spec: Any, surgery: EvidenceSurgery | None, *, window_id: str, symbol: str, warmup_bars: int, history_bars: int, cost_bps_per_side: float, entry_delay_bars: int) -> dict[str, Any]:
    cost_rate = cost_bps_per_side / 10_000.0
    position: EvidencePosition | None = None
    pending: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    counters = defaultdict(int)

    for index in range(warmup_bars, len(frame)):
        row = features.iloc[index]
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        timestamp = pd.Timestamp(row["timestamp"]).isoformat()
        atr = metric(row.get("atr14"))

        if pending is not None and position is None:
            pending["delay_remaining"] = int(pending.get("delay_remaining") or 0) - 1
            if pending["delay_remaining"] <= 0:
                raw_risk = metric(pending.get("entry")) - metric(pending.get("sl"))
                raw_reward = metric(pending.get("tp")) - metric(pending.get("entry"))
                size = metric(pending.get("size"))
                risk = raw_risk * exit_spec.stop_mult
                reward = raw_reward * exit_spec.target_mult
                if risk > 0.0 and reward > 0.0 and size > 0.0:
                    target = open_ + reward
                    if exit_spec.runner_target_r is not None:
                        target = open_ + risk * exit_spec.runner_target_r
                    position = EvidencePosition(
                        qty=size,
                        initial_qty=size,
                        entry=open_,
                        risk=risk,
                        sl=open_ - risk,
                        initial_sl=open_ - risk,
                        tp=target,
                        initial_tp=target,
                        opened_at=timestamp,
                        opened_index=index,
                        signal_ts=str(pending.get("signal_ts") or timestamp),
                        why=str(pending.get("why") or "unknown"),
                        skill=str(pending.get("skill") or "none"),
                        tags=tuple(str(value) for value in (pending.get("tags") or [])),
                        features=dict(pending.get("features") or {}),
                        entry_cost_pct=size * cost_rate * 100.0,
                        max_high=high,
                        min_low=low,
                        max_high_index=index,
                        min_low_index=index,
                        events=[{"type": "ENTRY", "ts": timestamp, "price": open_, "qty": size}],
                        qty_timeline=[{"ts": timestamp, "qty": size}],
                    )
                pending = None

        if position is not None:
            position.bars_open += 1
            if high > position.max_high:
                position.max_high = high
                position.max_high_index = index
            if low < position.min_low:
                position.min_low = low
                position.min_low_index = index
            if position.pending_stop is not None:
                old = position.sl
                position.sl = max(position.sl, position.pending_stop)
                if position.sl > old:
                    position.events.append({"type": "STOP_UPDATE", "ts": timestamp, "old": old, "new": position.sl})
                position.pending_stop = None
            if exit_spec.time_stop_bars is not None and position.bars_open >= exit_spec.time_stop_bars:
                trades.append(close_trade(position, exit_price=open_, exit_ts=timestamp, exit_index=index, reason="TIME_STOP", cost_rate=cost_rate, symbol=symbol, window_id=window_id))
                position = None
            else:
                hit_sl = low <= position.sl
                hit_tp = high >= position.tp
                if hit_sl or hit_tp:
                    exit_price = position.sl if hit_sl else position.tp
                    reason = "SL_CONSERVATIVE_SAME_BAR" if hit_sl and hit_tp else ("SL" if hit_sl else "TP")
                    trades.append(close_trade(position, exit_price=exit_price, exit_ts=timestamp, exit_index=index, reason=reason, cost_rate=cost_rate, symbol=symbol, window_id=window_id, path_ambiguous=bool(hit_sl and hit_tp)))
                    position = None
                else:
                    if exit_spec.partial_r is not None and not position.partial_done and high >= position.entry + position.risk * exit_spec.partial_r:
                        partial_qty = position.qty * exit_spec.partial_fraction
                        partial_price = position.entry + position.risk * exit_spec.partial_r
                        position.realized_pct += partial_qty * ((partial_price / position.entry) - 1.0) * 100.0
                        position.realized_cost_pct += partial_qty * cost_rate * 100.0
                        position.qty -= partial_qty
                        position.partial_done = True
                        position.pending_stop = position.entry * (1.0 + cost_rate * 2.0)
                        position.events.append({"type": "PARTIAL", "ts": timestamp, "price": partial_price, "qty": partial_qty, "remaining_qty": position.qty})
                        position.qty_timeline.append({"ts": timestamp, "qty": position.qty})
                    favorable_r = (high - position.entry) / max(position.risk, 1e-12)
                    if exit_spec.breakeven_r is not None and favorable_r >= exit_spec.breakeven_r:
                        candidate_stop = position.entry * (1.0 + cost_rate * 2.0)
                        position.pending_stop = max(position.pending_stop or position.sl, candidate_stop)
                    if exit_spec.trail_activate_r is not None and exit_spec.trail_atr_mult is not None and favorable_r >= exit_spec.trail_activate_r and atr > 0.0:
                        candidate_stop = close - atr * exit_spec.trail_atr_mult
                        position.pending_stop = max(position.pending_stop or position.sl, candidate_stop)

        if index >= len(frame) - 1:
            break
        history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
        state = {
            "position_side": "long" if position is not None else "",
            "position_qty": position.qty if position is not None else 0.0,
            "avg_entry": position.entry if position is not None else 0.0,
            "add_count": 0,
            "last_add_price": position.entry if position is not None else 0.0,
        }
        result = exact._call_strategy(strategy, history, state)
        counters["call_count"] += 1
        action = str(result.get("action") or "hold").lower()
        side = str(result.get("side") or "").lower()
        if side == "short" and action in {"enter", "add", "reduce"}:
            counters["short_signal_count"] += 1
            continue
        if action in {"add", "reduce"}:
            counters["ignored_add_reduce"] += 1
            continue
        if position is not None or pending is not None or action != "enter" or side != "long":
            continue
        feature_values = exact.feature_snapshot(features.iloc[index].to_dict())
        if not exact.gate_allows(gate, feature_values):
            counters["blocked_gate"] += 1
            continue
        if not surgery_allows(surgery, feature_values):
            counters["blocked_surgery"] += 1
            continue
        pending = dict(result)
        pending["signal_ts"] = pd.Timestamp(frame["timestamp"].iloc[index]).isoformat()
        pending["features"] = feature_values
        pending["delay_remaining"] = max(1, int(entry_delay_bars))

    if position is not None:
        last = features.iloc[-1]
        trades.append(close_trade(position, exit_price=float(last["close"]), exit_ts=pd.Timestamp(last["timestamp"]).isoformat(), exit_index=len(frame) - 1, reason="WINDOW_END", cost_rate=cost_rate, symbol=symbol, window_id=window_id))
    return {"stats": base._stats(trades), "trades": trades, **dict(counters)}


def funding_rate_quantiles(funding: Mapping[str, list[dict[str, Any]]]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for symbol, rows in funding.items():
        positive = np.array([max(0.0, float(row["funding_rate"])) for row in rows], dtype=float)
        result[symbol] = {
            "p75": float(np.quantile(positive, 0.75)) if len(positive) else 0.0,
            "p95": float(np.quantile(positive, 0.95)) if len(positive) else 0.0,
        }
    return result


def qty_at(trade: Mapping[str, Any], timestamp: str) -> float:
    target = pd.Timestamp(timestamp).value
    qty = float(trade.get("initial_qty") or 0.0)
    for row in trade.get("qty_timeline") or []:
        try:
            if pd.Timestamp(row["ts"]).value <= target:
                qty = float(row["qty"])
        except Exception:
            continue
    return qty


def apply_funding(trades: Sequence[dict[str, Any]], funding: Mapping[str, list[dict[str, Any]]], scenario: str, quantiles: Mapping[str, Mapping[str, float]]) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for source in trades:
        trade = dict(source)
        symbol = str(trade["symbol"])
        entry_ms = int(pd.Timestamp(trade["entry_ts"]).timestamp() * 1000)
        exit_ms = int(pd.Timestamp(trade["exit_ts"]).timestamp() * 1000)
        events = [row for row in funding.get(symbol, []) if entry_ms <= int(row["timestamp_ms"]) <= exit_ms]
        total = 0.0
        details: list[dict[str, Any]] = []
        for row in events:
            ts = iso(int(row["timestamp_ms"]))
            observed = float(row["funding_rate"])
            if scenario == "OBSERVED":
                rate = observed
            elif scenario == "ADVERSE_P75":
                rate = float(quantiles[symbol]["p75"])
            else:
                rate = float(quantiles[symbol]["p95"])
            qty = qty_at(trade, ts)
            cost_pct = qty * rate * 100.0
            total += cost_pct
            details.append({"ts": ts, "rate": rate, "observed_rate": observed, "qty": qty, "cost_pct": cost_pct})
        trade["funding_scenario"] = scenario
        trade["funding_cost_pct"] = total
        trade["funding_events"] = details
        trade["net_return_pct"] = float(trade["net_return_pct_before_funding"]) - total
        adjusted.append(trade)
    return adjusted


def combine_stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return base._stats([dict(trade) for trade in trades])


def adjusted_ratio(raw: Any, trade_count: int, *, cap: float, prior: int) -> float:
    value = min(cap, max(0.0, metric(raw, 1.0)))
    weight = trade_count / max(1.0, trade_count + prior)
    return 1.0 + (value - 1.0) * weight


def safe_authority_score(result: Mapping[str, Any], ssot: Mapping[str, Any]) -> float:
    evaluation = result.get("evaluation") if isinstance(result.get("evaluation"), Mapping) else {}
    metrics = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), Mapping) else {}
    all_stats = metrics.get("all") if isinstance(metrics.get("all"), Mapping) else {}
    n = int(all_stats.get("trade_count") or 0)
    safety = ssot["ranking_safety"]
    pf = adjusted_ratio(all_stats.get("net_profit_factor"), n, cap=float(safety["profit_factor_cap_for_score"]), prior=int(safety["bayesian_shrinkage_trade_prior"]))
    payoff = adjusted_ratio(all_stats.get("payoff_ratio"), n, cap=float(safety["payoff_ratio_cap_for_score"]), prior=int(safety["bayesian_shrinkage_trade_prior"]))
    return metric(all_stats.get("net_return_pct_sum")) * 5.0 + (pf - 1.0) * 22.0 + payoff * 1.5 + metric(all_stats.get("win_rate_pct")) * 0.12 - metric(all_stats.get("max_drawdown_pct")) * 1.25 + math.log1p(n)


def select_baseline(summary: Mapping[str, Any], ssot: Mapping[str, Any]) -> dict[str, Any] | None:
    rows = [row for row in summary.get("results", []) if isinstance(row, Mapping)]
    if not rows and isinstance(summary.get("best"), Mapping):
        rows = [summary["best"]]
    if not rows:
        return None
    return dict(sorted(rows, key=lambda row: safe_authority_score(row, ssot), reverse=True)[0])


def load_fresh_data(data_root: Path) -> tuple[dict[tuple[str, str], pd.DataFrame], dict[tuple[str, str], pd.DataFrame], dict[str, list[dict[str, Any]]], Mapping[str, Any]]:
    manifest = strict_json(data_root / "manifest.json")
    if manifest.get("state") != "PASS" or manifest.get("blockers"):
        raise RuntimeError("FRESH_MANIFEST_NOT_PASS")
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    features: dict[tuple[str, str], pd.DataFrame] = {}
    for row in manifest.get("files", []):
        if not isinstance(row, Mapping) or row.get("state") != "PASS":
            continue
        role, symbol = str(row["window_id"]), str(row["symbol"])
        path = data_root.parent / str(row["path"])
        if sha256(path) != row.get("sha256"):
            raise RuntimeError(f"FRESH_SHA_MISMATCH:{role}:{symbol}")
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
        frame["ts"] = frame["timestamp_ms"]
        frames[(role, symbol)] = frame
        features[(role, symbol)] = exact.compute_feature_frame(frame)
    funding: dict[str, list[dict[str, Any]]] = {}
    for symbol in SYMBOLS:
        payload = strict_json(data_root / "funding" / f"{symbol}.json")
        funding[symbol] = [dict(row) for row in payload.get("rows", []) if isinstance(row, Mapping)]
    return frames, features, funding, manifest


def block_bootstrap(returns: Sequence[float], samples: int, confidence: float, seed: int) -> dict[str, Any]:
    values = np.asarray(list(returns), dtype=float)
    n = len(values)
    if n < 2:
        return {"state": "HOLD", "blocker": "BOOTSTRAP_TRADES_LT_2", "samples": samples}
    block = max(1, int(round(math.sqrt(n))))
    rng = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    sums = np.empty(samples, dtype=float)
    for i in range(samples):
        draw: list[float] = []
        while len(draw) < n:
            start = int(rng.integers(0, n))
            for j in range(block):
                draw.append(float(values[(start + j) % n]))
                if len(draw) >= n:
                    break
        arr = np.asarray(draw, dtype=float)
        means[i] = float(arr.mean())
        sums[i] = float(arr.sum())
    alpha = (1.0 - confidence) / 2.0
    return {
        "state": "PASS",
        "samples": samples,
        "confidence": confidence,
        "block_length": block,
        "mean_return_ci": [float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))],
        "net_sum_ci": [float(np.quantile(sums, alpha)), float(np.quantile(sums, 1.0 - alpha))],
        "p_mean_le_zero": float(np.mean(means <= 0.0)),
    }


def sample_moments(values: Sequence[float]) -> tuple[float, float]:
    data = np.asarray(list(values), dtype=float)
    if len(data) < 3:
        return 0.0, 3.0
    mean = float(data.mean())
    std = float(data.std(ddof=1))
    if std <= 0:
        return 0.0, 3.0
    centered = (data - mean) / std
    return float(np.mean(centered ** 3)), float(np.mean(centered ** 4))


def deflated_sharpe(returns: Sequence[float], trials: int) -> dict[str, Any]:
    values = np.asarray(list(returns), dtype=float)
    n = len(values)
    if n < 3 or float(values.std(ddof=1)) <= 0.0:
        return {"state": "HOLD", "blocker": "DSR_INSUFFICIENT_RETURNS"}
    sr = float(values.mean() / values.std(ddof=1) * math.sqrt(n))
    skew, kurt = sample_moments(values)
    variance = max(1e-12, (1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr) / max(1, n - 1))
    normal = NormalDist()
    effective_trials = max(2, int(trials))
    gamma = 0.5772156649015329
    z1 = normal.inv_cdf(max(1e-9, min(1 - 1e-9, 1.0 - 1.0 / effective_trials)))
    z2 = normal.inv_cdf(max(1e-9, min(1 - 1e-9, 1.0 - 1.0 / (effective_trials * math.e))))
    expected_max = math.sqrt(variance) * ((1.0 - gamma) * z1 + gamma * z2)
    probability = normal.cdf((sr - expected_max) / math.sqrt(max(1e-12, variance)))
    return {
        "state": "PASS",
        "method": "BAILEY_LOPEZ_DE_PRADO_APPROXIMATION",
        "observed_sharpe": sr,
        "expected_max_sharpe": expected_max,
        "skew": skew,
        "kurtosis": kurt,
        "trial_count": effective_trials,
        "deflated_sharpe_probability": probability,
    }


def evaluate_strategy(root: Path, authority_root: Path, data_root: Path, ssot: Mapping[str, Any], strategy_id: str, out: Path) -> dict[str, Any]:
    exact_summary_path = authority_root / "strategy11_exact_v1" / strategy_id / "summary.json"
    exact_summary = strict_json(exact_summary_path)
    selected = select_baseline(exact_summary, ssot)
    result_blockers: list[str] = []
    if selected is None:
        payload = {"strategy_id": strategy_id, "state": "HOLD", "blockers": ["NO_AUTHORITY_CANDIDATE"]}
        atomic_json(out / strategy_id / "summary.json", payload)
        return payload

    candidate = selected.get("candidate") if isinstance(selected.get("candidate"), Mapping) else {}
    gate = exact._gate_from(candidate)
    exit_spec = exact._exit_from(candidate)
    surgery = surgery_from(selected.get("surgery") if isinstance(selected.get("surgery"), Mapping) else None)
    symbols = tuple(symbol for symbol in selected.get("symbols", []) if symbol in SYMBOLS)
    if not symbols:
        symbols = tuple(symbol for symbol in candidate.get("symbol_whitelist", []) if symbol in SYMBOLS)
    if not symbols:
        symbols = SYMBOLS[:2]

    registry = base._load_registry(root)
    strategy = base._load_canonical_strategy(root, strategy_id, registry[strategy_id])
    frames, features, funding, manifest = load_fresh_data(data_root)
    combined_cost = float(ssot["cost_stress"]["combined_fee_slippage_bps_per_side"])
    cost_multipliers = [float(value) for value in ssot["cost_stress"]["fee_slippage_combined_multipliers"]]
    latency_scenarios = list(ssot["cost_stress"]["latency_scenarios"])
    funding_scenarios = list(ssot["cost_stress"]["funding_scenarios"])
    quantiles = funding_rate_quantiles(funding)
    warmup_bars = int(manifest["warmup_bars"])
    history_bars = int(ssot["data_adequacy"]["history_bars"])

    scenario_rows: list[dict[str, Any]] = []
    baseline_trades: list[dict[str, Any]] = []
    per_window_baseline: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cost_mult in cost_multipliers:
        for latency_name in latency_scenarios:
            delay = 1 if latency_name == "NEXT_BAR_OPEN" else 2
            raw_trades: list[dict[str, Any]] = []
            for role in FRESH_ROLES:
                for symbol in symbols:
                    replay = replay_evidence(
                        frames[(role, symbol)], features[(role, symbol)], strategy, gate, exit_spec, surgery,
                        window_id=role, symbol=symbol, warmup_bars=warmup_bars, history_bars=history_bars,
                        cost_bps_per_side=combined_cost * cost_mult, entry_delay_bars=delay,
                    )
                    raw_trades.extend(replay["trades"])
            for funding_name in funding_scenarios:
                adjusted = apply_funding(raw_trades, funding, funding_name, quantiles)
                stats = combine_stats(adjusted)
                scenario_rows.append({
                    "strategy_id": strategy_id,
                    "cost_multiplier": cost_mult,
                    "latency_scenario": latency_name,
                    "funding_scenario": funding_name,
                    "trade_count": stats.get("trade_count"),
                    "win_rate_pct": stats.get("win_rate_pct"),
                    "net_return_pct_sum": stats.get("net_return_pct_sum"),
                    "net_profit_factor": stats.get("net_profit_factor"),
                    "payoff_ratio": stats.get("payoff_ratio"),
                    "max_drawdown_pct": stats.get("max_drawdown_pct"),
                })
                if cost_mult == 1.0 and latency_name == "NEXT_BAR_OPEN" and funding_name == "OBSERVED":
                    baseline_trades = adjusted
                    for trade in adjusted:
                        per_window_baseline[str(trade["window_id"])].append(trade)

    baseline_stats = combine_stats(baseline_trades)
    safety = ssot["ranking_safety"]
    n = int(baseline_stats.get("trade_count") or 0)
    pf_adjusted = adjusted_ratio(baseline_stats.get("net_profit_factor"), n, cap=float(safety["profit_factor_cap_for_score"]), prior=int(safety["bayesian_shrinkage_trade_prior"]))
    payoff_adjusted = adjusted_ratio(baseline_stats.get("payoff_ratio"), n, cap=float(safety["payoff_ratio_cap_for_score"]), prior=int(safety["bayesian_shrinkage_trade_prior"]))
    window_stats = {role: combine_stats(per_window_baseline.get(role, [])) for role in FRESH_ROLES}
    positive_windows = sum(metric(row.get("net_return_pct_sum")) > 0.0 for row in window_stats.values())
    positive_pct = positive_windows / len(FRESH_ROLES) * 100.0
    completeness_fields = ("mfe_pct", "mae_pct", "mfe_r", "mae_r", "bars_to_mfe", "bars_to_mae", "bars_held")
    evidence_complete = all(all(key in trade and (trade[key] is not None or key in {"mfe_r", "mae_r"}) for key in completeness_fields) for trade in baseline_trades)
    returns = [float(trade["net_return_pct"]) for trade in baseline_trades]
    stats_cfg = ssot["statistical_validation"]
    bootstrap = block_bootstrap(returns, int(stats_cfg["bootstrap_samples"]), float(stats_cfg["bootstrap_confidence_level"]), seed=int(stable_sha(strategy_id)[:8], 16))
    dsr = deflated_sharpe(returns, trials=25)
    if n < int(ssot["data_adequacy"]["min_fresh_trades_per_promoted_candidate"]):
        result_blockers.append(f"FRESH_TRADES_LT_MIN:{n}")
    if not evidence_complete:
        result_blockers.append("MFE_MAE_INCOMPLETE")
    if len(scenario_rows) != len(cost_multipliers) * len(latency_scenarios) * len(funding_scenarios):
        result_blockers.append("STRESS_GRID_INCOMPLETE")
    if bootstrap.get("state") != "PASS":
        result_blockers.append(str(bootstrap.get("blocker") or "BOOTSTRAP_HOLD"))
    if dsr.get("state") != "PASS":
        result_blockers.append(str(dsr.get("blocker") or "DSR_HOLD"))

    strategy_out = out / strategy_id
    strategy_out.mkdir(parents=True, exist_ok=True)
    atomic_json(strategy_out / "baseline_trades.json", {"strategy_id": strategy_id, "trades": baseline_trades})
    atomic_json(strategy_out / "stress_grid.json", {"strategy_id": strategy_id, "rows": scenario_rows})
    atomic_json(strategy_out / "statistics.json", {"strategy_id": strategy_id, "bootstrap": bootstrap, "deflated_sharpe": dsr})
    payload = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "authority": "READ_ONLY_BASELINE_EVIDENCE_NO_EXECUTION",
        "state": "PASS" if not result_blockers else "HOLD",
        "strategy_id": strategy_id,
        "authority_exact_summary_sha256": sha256(exact_summary_path),
        "selected_authority_result_sha256": stable_sha(selected),
        "candidate": candidate,
        "mode": selected.get("mode"),
        "surgery": selected.get("surgery"),
        "symbols": list(symbols),
        "baseline": {
            **baseline_stats,
            "net_profit_factor_adjusted": pf_adjusted,
            "payoff_ratio_adjusted": payoff_adjusted,
            "positive_fresh_windows": positive_windows,
            "positive_fresh_windows_pct": positive_pct,
            "mfe_mae_completeness_pct": 100.0 if evidence_complete else 0.0,
        },
        "window_stats": window_stats,
        "stress_scenario_count": len(scenario_rows),
        "stress_grid_complete": len(scenario_rows) == len(cost_multipliers) * len(latency_scenarios) * len(funding_scenarios),
        "bootstrap": bootstrap,
        "deflated_sharpe": dsr,
        "raw_low_sample_ratios_not_used_for_ranking": n < int(safety["min_trades_for_profit_factor_ranking"]),
        "ranking_safety": {
            "trade_count": n,
            "raw_profit_factor": baseline_stats.get("net_profit_factor"),
            "adjusted_profit_factor": pf_adjusted,
            "raw_payoff_ratio": baseline_stats.get("payoff_ratio"),
            "adjusted_payoff_ratio": payoff_adjusted,
            "prior_trades": safety["bayesian_shrinkage_trade_prior"],
            "score_cap": safety["profit_factor_cap_for_score"],
        },
        "blockers": result_blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "shadow_allowed": False,
        "execution_allowed": False,
    }
    atomic_json(strategy_out / "summary.json", payload)
    return payload


def strategy_ids(authority_root: Path) -> list[str]:
    return sorted(path.parent.name for path in (authority_root / "strategy11_exact_v1").glob("*/summary.json"))


def evaluate_batch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    authority_root = Path(args.authority_root).resolve()
    data_root = Path(args.data_root).resolve()
    out = Path(args.out).resolve()
    ssot = strict_json(Path(args.ssot).resolve())
    ids = strategy_ids(authority_root)
    if len(ids) != 25:
        raise RuntimeError(f"AUTHORITY_STRATEGY_COUNT:{len(ids)}")
    start = (int(args.batch_index) - 1) * 5
    selected_ids = ids[start:start + 5]
    if len(selected_ids) != 5:
        raise RuntimeError(f"BATCH_SIZE:{len(selected_ids)}")
    rows: list[dict[str, Any]] = []
    for sid in selected_ids:
        print(f"EVIDENCE_START strategy={sid}", flush=True)
        try:
            payload = evaluate_strategy(root, authority_root, data_root, ssot, sid, out)
            rows.append({"strategy_id": sid, "state": payload.get("state"), "blockers": payload.get("blockers", [])})
            print(f"EVIDENCE_END strategy={sid} state={payload.get('state')}", flush=True)
        except Exception as exc:
            blocker = f"{type(exc).__name__}:{exc}"
            rows.append({"strategy_id": sid, "state": "HOLD", "blockers": [blocker]})
            atomic_json(out / sid / "summary.json", {"strategy_id": sid, "state": "HOLD", "blockers": [blocker]})
            print(f"EVIDENCE_END strategy={sid} state=HOLD error={blocker}", flush=True)
    atomic_json(out / f"batch-{args.batch_index}-status.json", {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "state": "PASS",
        "batch_index": int(args.batch_index),
        "strategy_count": len(rows),
        "rows": rows,
        "canonical_mutated": False,
        "execution_allowed": False,
    })
    return 0


def bh_fdr(pvalues: Mapping[str, float], q: float) -> dict[str, Any]:
    ordered = sorted((float(value), key) for key, value in pvalues.items())
    m = len(ordered)
    threshold_index = -1
    for index, (pvalue, _) in enumerate(ordered, start=1):
        if pvalue <= q * index / max(1, m):
            threshold_index = index
    passed = {key for _, key in ordered[:threshold_index]} if threshold_index > 0 else set()
    adjusted: dict[str, float] = {}
    running = 1.0
    for reverse_index in range(m - 1, -1, -1):
        pvalue, key = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, pvalue * m / rank)
        adjusted[key] = min(1.0, running)
    return {"q": q, "passed": sorted(passed), "adjusted_pvalues": adjusted}


def pbo_estimate(summaries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    roles = list(FRESH_ROLES)
    logits: list[float] = []
    observations: list[dict[str, Any]] = []
    ids = sorted(summaries)
    if len(ids) < 2:
        return {"state": "HOLD", "blocker": "PBO_STRATEGIES_LT_2"}
    for train_size in (1, 2):
        for train_roles in itertools.combinations(roles, train_size):
            test_roles = tuple(role for role in roles if role not in train_roles)
            train_scores: dict[str, float] = {}
            test_scores: dict[str, float] = {}
            for sid, summary in summaries.items():
                windows = summary.get("window_stats") if isinstance(summary.get("window_stats"), Mapping) else {}
                train_scores[sid] = sum(metric((windows.get(role) or {}).get("net_return_pct_sum")) for role in train_roles)
                test_scores[sid] = sum(metric((windows.get(role) or {}).get("net_return_pct_sum")) for role in test_roles)
            selected = max(ids, key=lambda sid: (train_scores[sid], sid))
            ranked_test = sorted(ids, key=lambda sid: (test_scores[sid], sid))
            rank = ranked_test.index(selected) + 1
            percentile = min(1 - 1e-6, max(1e-6, (rank - 0.5) / len(ranked_test)))
            logit = math.log(percentile / (1.0 - percentile))
            logits.append(logit)
            observations.append({"train_roles": list(train_roles), "test_roles": list(test_roles), "selected": selected, "test_rank": rank, "test_percentile": percentile, "logit": logit})
    return {"state": "PASS", "split_count": len(logits), "pbo": sum(value < 0.0 for value in logits) / len(logits) if logits else 1.0, "observations": observations}


def aggregate(args: argparse.Namespace) -> int:
    evidence_root = Path(args.evidence_root).resolve()
    fresh_manifest_path = Path(args.fresh_manifest).resolve()
    sealed_manifest_path = Path(args.sealed_manifest).resolve()
    ssot_path = Path(args.ssot).resolve()
    out = Path(args.out).resolve()
    ssot = strict_json(ssot_path)
    fresh = strict_json(fresh_manifest_path)
    sealed = strict_json(sealed_manifest_path)
    summaries = {path.parent.name: strict_json(path) for path in sorted(evidence_root.glob("*/summary.json"))}
    blockers: list[str] = []
    if len(summaries) != 25:
        blockers.append(f"EVIDENCE_STRATEGY_COUNT:{len(summaries)}")
    if fresh.get("state") != "PASS" or fresh.get("blockers"):
        blockers.append("FRESH_DATA_NOT_PASS")
    if sealed.get("state") != "PASS" or sealed.get("blockers"):
        blockers.append("SEALED_DATA_NOT_PASS")
    if int(fresh.get("window_count") or 0) < int(ssot["data_adequacy"]["min_distinct_fresh_windows"]):
        blockers.append("FRESH_WINDOW_COUNT_LOW")
    if int(sealed.get("window_count") or 0) < int(ssot["data_adequacy"]["min_sealed_final_holdback_windows"]):
        blockers.append("SEALED_WINDOW_COUNT_LOW")
    if sealed.get("repair_read_allowed") is not False or sealed.get("one_shot_only") is not True:
        blockers.append("SEALED_CONTRACT_INVALID")

    pvalues: dict[str, float] = {}
    eligible: list[str] = []
    total_trades = 0
    mfe_complete = True
    stress_complete = True
    stats_complete = True
    for sid, summary in summaries.items():
        baseline = summary.get("baseline") if isinstance(summary.get("baseline"), Mapping) else {}
        total_trades += int(baseline.get("trade_count") or 0)
        if float(baseline.get("mfe_mae_completeness_pct") or 0.0) != 100.0:
            mfe_complete = False
        if summary.get("stress_grid_complete") is not True:
            stress_complete = False
        bootstrap = summary.get("bootstrap") if isinstance(summary.get("bootstrap"), Mapping) else {}
        dsr = summary.get("deflated_sharpe") if isinstance(summary.get("deflated_sharpe"), Mapping) else {}
        if bootstrap.get("state") != "PASS" or dsr.get("state") != "PASS":
            stats_complete = False
        if finite(bootstrap.get("p_mean_le_zero")):
            pvalues[sid] = float(bootstrap["p_mean_le_zero"])
        if int(baseline.get("trade_count") or 0) >= int(ssot["data_adequacy"]["min_fresh_trades_per_promoted_candidate"]):
            eligible.append(sid)

    if not eligible:
        blockers.append("NO_CANDIDATE_WITH_MIN_FRESH_TRADES")
    if not mfe_complete:
        blockers.append("MFE_MAE_COMPLETENESS_NOT_100")
    if not stress_complete:
        blockers.append("COST_FUNDING_LATENCY_STRESS_INCOMPLETE")
    if not stats_complete:
        blockers.append("STATISTICAL_EVIDENCE_INCOMPLETE")
    fdr = bh_fdr(pvalues, float(ssot["statistical_validation"]["fdr_q"])) if pvalues else {"q": ssot["statistical_validation"]["fdr_q"], "passed": [], "adjusted_pvalues": {}}
    pbo = pbo_estimate(summaries)
    if pbo.get("state") != "PASS":
        blockers.append(str(pbo.get("blocker") or "PBO_NOT_IMPLEMENTED"))
    elif float(pbo.get("pbo") or 1.0) > float(ssot["statistical_validation"]["probability_of_backtest_overfitting_max"]):
        blockers.append(f"PBO_ABOVE_LIMIT:{pbo.get('pbo')}")

    data_state = "PASS" if not blockers else "HOLD"
    ranking_rows: list[dict[str, Any]] = []
    for sid, summary in summaries.items():
        baseline = summary.get("baseline") if isinstance(summary.get("baseline"), Mapping) else {}
        ranking_rows.append({
            "strategy_id": sid,
            "state": summary.get("state"),
            "trade_count": baseline.get("trade_count"),
            "win_rate_pct": baseline.get("win_rate_pct"),
            "net_return_pct_sum": baseline.get("net_return_pct_sum"),
            "net_profit_factor_raw": baseline.get("net_profit_factor"),
            "net_profit_factor_adjusted": baseline.get("net_profit_factor_adjusted"),
            "payoff_ratio_raw": baseline.get("payoff_ratio"),
            "payoff_ratio_adjusted": baseline.get("payoff_ratio_adjusted"),
            "max_drawdown_pct": baseline.get("max_drawdown_pct"),
            "positive_fresh_windows_pct": baseline.get("positive_fresh_windows_pct"),
            "bootstrap_p": (summary.get("bootstrap") or {}).get("p_mean_le_zero"),
            "bh_adjusted_p": fdr.get("adjusted_pvalues", {}).get(sid),
            "fdr_pass": sid in set(fdr.get("passed", [])),
            "deflated_sharpe_probability": (summary.get("deflated_sharpe") or {}).get("deflated_sharpe_probability"),
            "eligible_for_improvement": sid in eligible,
        })
    ranking_rows.sort(key=lambda row: (bool(row["eligible_for_improvement"]), metric(row["positive_fresh_windows_pct"]), -metric(row["max_drawdown_pct"]), metric(row["net_profit_factor_adjusted"]), metric(row["payoff_ratio_adjusted"]), metric(row["net_return_pct_sum"])), reverse=True)

    out.mkdir(parents=True, exist_ok=True)
    fields = list(ranking_rows[0]) if ranking_rows else ["strategy_id"]
    with (out / "global_ranking.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ranking_rows)
    atomic_json(out / "bh_fdr.json", fdr)
    atomic_json(out / "pbo.json", pbo)
    atomic_json(out / "candidate_queue.json", {
        "state": data_state,
        "max_active_candidates": ssot["repair_budget"]["max_active_candidates"],
        "rows": [row for row in ranking_rows if row["eligible_for_improvement"]][:int(ssot["repair_budget"]["max_active_candidates"])],
        "gemini_allowed": data_state == "PASS",
        "auto_improvement_allowed": data_state == "PASS",
    })
    payload = {
        "schema_version": "1.0",
        "pipeline_version": PIPELINE_VERSION,
        "authority": "READ_ONLY_DATA_ADEQUACY_GATE_NO_EXECUTION",
        "state": data_state,
        "data_adequacy_pass": data_state == "PASS",
        "strategy_count": len(summaries),
        "fresh_window_count": fresh.get("window_count"),
        "sealed_window_count": sealed.get("window_count"),
        "total_fresh_trades": total_trades,
        "eligible_candidate_count": len(eligible),
        "eligible_candidates": eligible,
        "mfe_mae_completeness_100": mfe_complete,
        "stress_grid_complete": stress_complete,
        "statistics_complete": stats_complete,
        "bh_fdr": fdr,
        "pbo": pbo,
        "ssot_sha256": sha256(ssot_path),
        "fresh_manifest_sha256": sha256(fresh_manifest_path),
        "sealed_manifest_sha256": sha256(sealed_manifest_path),
        "gemini_allowed": data_state == "PASS",
        "auto_improvement_allowed": data_state == "PASS",
        "shadow_allowed": False,
        "execution_allowed": False,
        "blockers": blockers,
        "next": "GEMINI_MULTI_SOURCE_RESEARCH" if data_state == "PASS" else "WAIT_NEW_DATA_OR_EVIDENCE_REPAIR",
    }
    atomic_json(out / "summary.json", payload)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"data_adequacy={data_state}\n")
    print(json.dumps({"STATE": data_state, "ELIGIBLE": eligible, "BLOCKERS": blockers}, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare-data")
    prepare.add_argument("--root", default=".")
    prepare.add_argument("--authority-manifest", required=True)
    prepare.add_argument("--ssot", required=True)
    prepare.add_argument("--out", required=True)
    prepare.add_argument("--evaluation-bars", type=int, default=480)
    prepare.add_argument("--warmup-bars", type=int, default=220)
    prepare.add_argument("--as-of-ms", type=int)
    evaluate = sub.add_parser("evaluate-batch")
    evaluate.add_argument("--root", default=".")
    evaluate.add_argument("--authority-root", required=True)
    evaluate.add_argument("--data-root", required=True)
    evaluate.add_argument("--ssot", required=True)
    evaluate.add_argument("--out", required=True)
    evaluate.add_argument("--batch-index", type=int, required=True)
    aggregate_parser = sub.add_parser("aggregate")
    aggregate_parser.add_argument("--evidence-root", required=True)
    aggregate_parser.add_argument("--fresh-manifest", required=True)
    aggregate_parser.add_argument("--sealed-manifest", required=True)
    aggregate_parser.add_argument("--ssot", required=True)
    aggregate_parser.add_argument("--out", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare-data":
        return prepare_data(args)
    if args.command == "evaluate-batch":
        return evaluate_batch(args)
    return aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
