from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd

from backend.strategy25.strategy11_feature_library_v1 import (
    FAMILY_MAP,
    ExitSpec,
    GateSpec,
    compute_feature_frame,
    feature_snapshot,
    gate_allows,
)


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
INTERVAL_MS = 900_000
ALL_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
ANCHOR_ENDS = (
    "2025-08-15T00:00:00Z",
    "2025-09-15T00:00:00Z",
    "2025-10-15T00:00:00Z",
    "2025-11-15T00:00:00Z",
    "2025-12-15T00:00:00Z",
    "2026-01-15T00:00:00Z",
    "2026-02-15T00:00:00Z",
    "2026-03-15T00:00:00Z",
    "2026-04-15T00:00:00Z",
    "2026-05-15T00:00:00Z",
    "2026-06-15T00:00:00Z",
    "2026-07-15T00:00:00Z",
)
WINDOW_ROLES = ("S1", "S2", "S3", "S4", "S5", "S6", "V1", "V2", "H1", "H2", "F1", "F2")
WINDOW_BARS = 900
WARMUP_BARS = 220
HISTORY_BARS = 220
COST_BPS_PER_SIDE = 4.0


def _load_base() -> Any:
    name = "r7a4d_strategy11_exact_base_runner"
    spec = importlib.util.spec_from_file_location(name, BASE_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base()


@dataclass(frozen=True)
class SurgerySpec:
    surgery_id: str
    feature: str
    kind: str
    value: Any
    block_when: str


@dataclass
class Position:
    qty: float
    entry: float
    risk: float
    sl: float
    tp: float
    opened_at: str
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


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _metric(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


def _call_strategy(strategy: Callable[..., dict[str, Any]], history: pd.DataFrame, state: Mapping[str, Any]) -> dict[str, Any]:
    attempts = (
        lambda: strategy(history, state=dict(state), risk_action="hold"),
        lambda: strategy(history, state=dict(state)),
        lambda: strategy(history, risk_action="hold"),
        lambda: strategy(history),
    )
    last_error: Exception | None = None
    for attempt in attempts:
        try:
            result = attempt()
            if not isinstance(result, dict):
                raise TypeError("STRATEGY_RESULT_NOT_DICT")
            return result
        except TypeError as exc:
            last_error = exc
    raise RuntimeError(f"STRATEGY_CALL_FAILED:{type(last_error).__name__}:{last_error}")


def _gate_from(candidate: Mapping[str, Any]) -> GateSpec:
    gate = candidate.get("gate") if isinstance(candidate.get("gate"), Mapping) else {}
    return GateSpec(
        gate_id=str(gate.get("gate_id") or "BASE"),
        family=str(candidate.get("family") or FAMILY_MAP[str(candidate.get("strategy_id"))]),
        required=tuple(str(value) for value in (gate.get("required") or [])),
        forbidden=tuple(str(value) for value in (gate.get("forbidden") or [])),
        description=str(gate.get("description") or ""),
    )


def _exit_from(candidate: Mapping[str, Any]) -> ExitSpec:
    value = candidate.get("exit") if isinstance(candidate.get("exit"), Mapping) else {}
    return ExitSpec(
        exit_id=str(value.get("exit_id") or "ORIG"),
        stop_mult=_metric(value.get("stop_mult"), 1.0),
        target_mult=_metric(value.get("target_mult"), 1.0),
        breakeven_r=_metric(value.get("breakeven_r")) if value.get("breakeven_r") is not None else None,
        partial_r=_metric(value.get("partial_r")) if value.get("partial_r") is not None else None,
        partial_fraction=_metric(value.get("partial_fraction")),
        runner_target_r=_metric(value.get("runner_target_r")) if value.get("runner_target_r") is not None else None,
        trail_activate_r=_metric(value.get("trail_activate_r")) if value.get("trail_activate_r") is not None else None,
        trail_atr_mult=_metric(value.get("trail_atr_mult")) if value.get("trail_atr_mult") is not None else None,
        time_stop_bars=int(value.get("time_stop_bars")) if value.get("time_stop_bars") is not None else None,
    )


def _surgery_allows(spec: SurgerySpec | None, features: Mapping[str, Any]) -> bool:
    if spec is None:
        return True
    raw = features.get(spec.feature)
    if spec.kind == "bool":
        matched = bool(raw) is bool(spec.value)
    else:
        if not _finite(raw):
            matched = False
        elif spec.block_when == "LE":
            matched = float(raw) <= float(spec.value)
        else:
            matched = float(raw) >= float(spec.value)
    return not matched


def _close_trade(position: Position, *, exit_price: float, exit_ts: str, reason: str, cost_rate: float) -> dict[str, Any]:
    gross = position.qty * ((exit_price / position.entry) - 1.0) * 100.0
    exit_cost = position.qty * cost_rate * 100.0
    net = position.realized_pct + gross - position.entry_cost_pct - position.realized_cost_pct - exit_cost
    return {
        "entry_ts": position.opened_at,
        "exit_ts": exit_ts,
        "entry_price": position.entry,
        "exit_price": exit_price,
        "qty": position.qty,
        "net_return_pct": net,
        "exit_reason": reason,
        "signal_ts": position.signal_ts,
        "signal_why": position.why,
        "signal_skill": position.skill,
        "signal_tags": list(position.tags),
        "features": position.features,
    }


def _replay(
    frame: pd.DataFrame,
    features: pd.DataFrame,
    strategy: Callable[..., dict[str, Any]],
    gate: GateSpec,
    exit_spec: ExitSpec,
    surgery: SurgerySpec | None,
    *,
    warmup_bars: int,
    history_bars: int,
    cost_bps_per_side: float,
) -> dict[str, Any]:
    cost_rate = cost_bps_per_side / 10_000.0
    position: Position | None = None
    pending: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    call_count = 0
    blocked_gate = 0
    blocked_surgery = 0
    ignored_add_reduce = 0
    short_signals = 0

    for index in range(warmup_bars, len(frame)):
        row = features.iloc[index]
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        timestamp = pd.Timestamp(row["timestamp"]).isoformat()
        atr = _metric(row.get("atr14"))

        if pending is not None and position is None:
            raw_risk = _metric(pending.get("entry")) - _metric(pending.get("sl"))
            raw_reward = _metric(pending.get("tp")) - _metric(pending.get("entry"))
            size = _metric(pending.get("size"))
            risk = raw_risk * exit_spec.stop_mult
            reward = raw_reward * exit_spec.target_mult
            if risk > 0.0 and reward > 0.0 and size > 0.0:
                target = open_ + reward
                if exit_spec.runner_target_r is not None:
                    target = open_ + risk * exit_spec.runner_target_r
                position = Position(
                    qty=size,
                    entry=open_,
                    risk=risk,
                    sl=open_ - risk,
                    tp=target,
                    opened_at=timestamp,
                    signal_ts=str(pending.get("signal_ts") or timestamp),
                    why=str(pending.get("why") or "unknown"),
                    skill=str(pending.get("skill") or "none"),
                    tags=tuple(str(value) for value in (pending.get("tags") or [])),
                    features=dict(pending.get("features") or {}),
                    entry_cost_pct=size * cost_rate * 100.0,
                )
            pending = None

        if position is not None:
            position.bars_open += 1
            if position.pending_stop is not None:
                position.sl = max(position.sl, position.pending_stop)
                position.pending_stop = None
            if exit_spec.time_stop_bars is not None and position.bars_open >= exit_spec.time_stop_bars:
                trades.append(_close_trade(position, exit_price=open_, exit_ts=timestamp, reason="TIME_STOP", cost_rate=cost_rate))
                position = None
            else:
                hit_sl = low <= position.sl
                hit_tp = high >= position.tp
                if hit_sl or hit_tp:
                    exit_price = position.sl if hit_sl else position.tp
                    reason = "SL_CONSERVATIVE_SAME_BAR" if hit_sl and hit_tp else ("SL" if hit_sl else "TP")
                    trades.append(_close_trade(position, exit_price=exit_price, exit_ts=timestamp, reason=reason, cost_rate=cost_rate))
                    position = None
                else:
                    if (
                        exit_spec.partial_r is not None
                        and not position.partial_done
                        and high >= position.entry + position.risk * exit_spec.partial_r
                    ):
                        partial_qty = position.qty * exit_spec.partial_fraction
                        partial_price = position.entry + position.risk * exit_spec.partial_r
                        position.realized_pct += partial_qty * ((partial_price / position.entry) - 1.0) * 100.0
                        position.realized_cost_pct += partial_qty * cost_rate * 100.0
                        position.qty -= partial_qty
                        position.partial_done = True
                        position.pending_stop = position.entry * (1.0 + cost_rate * 2.0)
                    favorable_r = (high - position.entry) / max(position.risk, 1e-12)
                    if exit_spec.breakeven_r is not None and favorable_r >= exit_spec.breakeven_r:
                        position.pending_stop = max(position.pending_stop or position.sl, position.entry * (1.0 + cost_rate * 2.0))
                    if (
                        exit_spec.trail_activate_r is not None
                        and exit_spec.trail_atr_mult is not None
                        and favorable_r >= exit_spec.trail_activate_r
                        and atr > 0.0
                    ):
                        position.pending_stop = max(position.pending_stop or position.sl, close - atr * exit_spec.trail_atr_mult)

        if index >= len(frame) - 1:
            break
        history = frame.iloc[max(0, index - history_bars + 1) : index + 1].copy()
        state = {
            "position_side": "long" if position is not None else "",
            "position_qty": position.qty if position is not None else 0.0,
            "avg_entry": position.entry if position is not None else 0.0,
            "add_count": 0,
            "last_add_price": position.entry if position is not None else 0.0,
        }
        result = _call_strategy(strategy, history, state)
        call_count += 1
        action = str(result.get("action") or "hold").lower()
        side = str(result.get("side") or "").lower()
        if side == "short" and action in {"enter", "add", "reduce"}:
            short_signals += 1
            continue
        if action in {"add", "reduce"}:
            ignored_add_reduce += 1
            continue
        if position is not None or action != "enter" or side != "long":
            continue
        feature_values = feature_snapshot(features.iloc[index].to_dict())
        if not gate_allows(gate, feature_values):
            blocked_gate += 1
            continue
        if not _surgery_allows(surgery, feature_values):
            blocked_surgery += 1
            continue
        pending = dict(result)
        pending["signal_ts"] = pd.Timestamp(frame["timestamp"].iloc[index]).isoformat()
        pending["features"] = feature_values

    if position is not None:
        last = features.iloc[-1]
        trades.append(
            _close_trade(
                position,
                exit_price=float(last["close"]),
                exit_ts=pd.Timestamp(last["timestamp"]).isoformat(),
                reason="WINDOW_END",
                cost_rate=cost_rate,
            )
        )

    return {
        "stats": base._stats(trades),
        "trades": trades,
        "call_count": call_count,
        "blocked_gate": blocked_gate,
        "blocked_surgery": blocked_surgery,
        "ignored_add_reduce": ignored_add_reduce,
        "short_signal_count": short_signals,
    }


def _combine(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    trades = [trade for row in rows for trade in row.get("trades", []) if isinstance(trade, dict)]
    stats = base._stats(trades)
    stats["max_drawdown_pct_conservative_sum"] = sum(_metric(row.get("stats", {}).get("max_drawdown_pct")) for row in rows)
    return stats


def _positive_windows(rows: list[dict[str, Any]], roles: tuple[str, ...]) -> int:
    return sum(_metric(_combine([row for row in rows if row["window_id"] == role]).get("net_return_pct_sum")) > 0.0 for role in roles)


def _positive_symbols(rows: list[dict[str, Any]], roles: tuple[str, ...], symbols: tuple[str, ...]) -> int:
    return sum(_metric(_combine([row for row in rows if row["window_id"] in roles and row["symbol"] == symbol]).get("net_return_pct_sum")) > 0.0 for symbol in symbols)


def _evaluate(rows: list[dict[str, Any]], lane: str, symbols: tuple[str, ...]) -> dict[str, Any]:
    groups = {
        "selection": WINDOW_ROLES[:6],
        "validation": WINDOW_ROLES[6:8],
        "holdout": WINDOW_ROLES[8:10],
        "fresh": WINDOW_ROLES[10:],
        "all": WINDOW_ROLES,
    }
    metrics = {name: _combine([row for row in rows if row["window_id"] in roles]) for name, roles in groups.items()}
    positive_windows = {name: _positive_windows(rows, roles) for name, roles in groups.items() if name != "all"}
    positive_symbols = {name: _positive_symbols(rows, roles, symbols) for name, roles in groups.items() if name != "all"}
    reasons: list[str] = []
    selection = metrics["selection"]
    if int(selection.get("trade_count") or 0) < 20:
        reasons.append("SELECTION_TRADES_LT_20")
    if positive_windows["selection"] < 3:
        reasons.append("SELECTION_POSITIVE_WINDOWS_LT_3")
    if positive_symbols["selection"] < min(2, len(symbols)):
        reasons.append("SELECTION_POSITIVE_SYMBOLS_LT_2")
    if lane == "RETURN":
        if _metric(selection.get("net_return_pct_sum")) <= 1.0:
            reasons.append("SELECTION_NET_LE_1")
        if _metric(selection.get("net_profit_factor")) <= 1.10:
            reasons.append("SELECTION_PF_LE_1_10")
        if _metric(selection.get("payoff_ratio")) <= 1.50:
            reasons.append("SELECTION_PAYOFF_LE_1_50")
    else:
        if _metric(selection.get("win_rate_pct")) < 40.0:
            reasons.append("SELECTION_WR_LT_40")
        if _metric(selection.get("net_return_pct_sum")) <= 0.50:
            reasons.append("SELECTION_NET_LE_0_5")
        if _metric(selection.get("net_profit_factor")) <= 1.05:
            reasons.append("SELECTION_PF_LE_1_05")

    for name in ("validation", "holdout", "fresh"):
        stats = metrics[name]
        if int(stats.get("trade_count") or 0) < 4:
            reasons.append(f"{name.upper()}_TRADES_LT_4")
        if _metric(stats.get("net_return_pct_sum")) <= 0.0:
            reasons.append(f"{name.upper()}_NET_NOT_POSITIVE")
        if _metric(stats.get("net_profit_factor")) <= 1.0:
            reasons.append(f"{name.upper()}_PF_NOT_ABOVE_1")
        if positive_windows[name] < 1:
            reasons.append(f"{name.upper()}_POSITIVE_WINDOWS_LT_1")
        if lane == "WINRATE" and _metric(stats.get("win_rate_pct")) < 35.0:
            reasons.append(f"{name.upper()}_WR_LT_35")

    combined = metrics["all"]
    if int(combined.get("trade_count") or 0) < 35:
        reasons.append("ALL_TRADES_LT_35")
    if _metric(combined.get("net_return_pct_sum")) <= 2.0:
        reasons.append("ALL_NET_LE_2")
    if _metric(combined.get("net_profit_factor")) <= 1.10:
        reasons.append("ALL_PF_LE_1_10")
    if positive_windows["selection"] + positive_windows["validation"] + positive_windows["holdout"] + positive_windows["fresh"] < 7:
        reasons.append("ALL_POSITIVE_WINDOWS_LT_7")

    score = (
        _metric(combined.get("net_return_pct_sum")) * 5.0
        + (_metric(combined.get("net_profit_factor")) - 1.0) * 22.0
        + _metric(combined.get("payoff_ratio")) * 1.5
        + _metric(combined.get("win_rate_pct")) * (0.12 if lane == "RETURN" else 0.30)
        - _metric(combined.get("max_drawdown_pct_conservative_sum")) * 1.25
        + sum(positive_windows.values()) * 2.0
        + sum(positive_symbols.values())
        + math.log1p(int(combined.get("trade_count") or 0))
    )
    return {
        "pass": not reasons,
        "failure_reasons": reasons,
        "metrics": metrics,
        "positive_windows": positive_windows,
        "positive_symbols": positive_symbols,
        "score": score,
    }


def _candidate_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    gate = candidate.get("gate") if isinstance(candidate.get("gate"), Mapping) else {}
    exit_value = candidate.get("exit") if isinstance(candidate.get("exit"), Mapping) else {}
    return (
        candidate.get("lane"), gate.get("gate_id"), exit_value.get("exit_id"), tuple(candidate.get("symbol_whitelist") or [])
    )


def _candidate_pool(screen: Mapping[str, Any]) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for key in ("accepted_candidates", "top_return", "top_winrate"):
        values = screen.get(key) if isinstance(screen.get(key), list) else []
        pool.extend(dict(value) for value in values if isinstance(value, Mapping))
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for candidate in pool:
        key = _candidate_key(candidate)
        prior = unique.get(key)
        if prior is None or _metric(candidate.get("score"), -math.inf) > _metric(prior.get("score"), -math.inf):
            unique[key] = candidate
    return sorted(unique.values(), key=lambda value: (bool(value.get("pass")), _metric(value.get("score"), -math.inf)), reverse=True)[:2]


def _surgery_candidates(trades: list[dict[str, Any]]) -> list[SurgerySpec]:
    if len(trades) < 12:
        return []
    features = [trade.get("features") if isinstance(trade.get("features"), Mapping) else {} for trade in trades]
    returns = [_metric(trade.get("net_return_pct")) for trade in trades]
    total_wins = sum(value > 0.0 for value in returns)
    candidates: list[tuple[float, SurgerySpec]] = []
    keys = sorted({key for row in features for key in row})
    for key in keys:
        values = [row.get(key) for row in features]
        if all(isinstance(value, bool) for value in values if value is not None):
            for block_value in (True, False):
                indexes = [i for i, value in enumerate(values) if bool(value) is block_value]
                if len(indexes) < 5:
                    continue
                losses = sum(returns[i] < 0.0 for i in indexes)
                wins = sum(returns[i] > 0.0 for i in indexes)
                precision = losses / len(indexes)
                preserved_wins = total_wins - wins
                if precision >= 0.65 and preserved_wins >= max(3, math.ceil(total_wins * 0.70)):
                    score = precision * len(indexes) - wins * 0.75
                    candidates.append((score, SurgerySpec(f"BLOCK_{key}_{block_value}", key, "bool", block_value, "EQ")))
            continue
        numeric = np.array([float(value) if _finite(value) else np.nan for value in values], dtype=float)
        clean = numeric[np.isfinite(numeric)]
        if len(clean) < 10:
            continue
        for quantile in (0.25, 0.50, 0.75):
            threshold = float(np.quantile(clean, quantile))
            for direction in ("LE", "GE"):
                indexes = [i for i, value in enumerate(numeric) if np.isfinite(value) and ((value <= threshold) if direction == "LE" else (value >= threshold))]
                if len(indexes) < 5:
                    continue
                losses = sum(returns[i] < 0.0 for i in indexes)
                wins = sum(returns[i] > 0.0 for i in indexes)
                precision = losses / len(indexes)
                preserved_wins = total_wins - wins
                if precision >= 0.68 and preserved_wins >= max(3, math.ceil(total_wins * 0.70)):
                    score = precision * len(indexes) - wins
                    candidates.append((score, SurgerySpec(f"BLOCK_{key}_{direction}_{threshold:.6g}", key, "numeric", threshold, direction)))
    candidates.sort(key=lambda item: item[0], reverse=True)
    unique: dict[str, SurgerySpec] = {}
    for _, candidate in candidates:
        unique.setdefault(candidate.surgery_id, candidate)
    return list(unique.values())[:2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--screen-summary", required=True)
    parser.add_argument("--window-bars", type=int, default=WINDOW_BARS)
    parser.add_argument("--warmup-bars", type=int, default=WARMUP_BARS)
    parser.add_argument("--history-bars", type=int, default=HISTORY_BARS)
    parser.add_argument("--cost-bps-per-side", type=float, default=COST_BPS_PER_SIDE)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    strategy_id = str(args.strategy_id)
    screen = json.loads(Path(args.screen_summary).read_text(encoding="utf-8"))
    if strategy_id != str(screen.get("strategy_id")):
        raise ValueError("SCREEN_STRATEGY_MISMATCH")
    candidates = _candidate_pool(screen)
    output_dir = root / "artifacts/strategy11_exact_v1" / strategy_id
    blockers: list[str] = []
    if not candidates:
        report = {
            "schema_version": "1.0", "authority": "READ_ONLY_EXACT_NO_EXECUTION", "state": "PASS",
            "strategy_id": strategy_id, "family": FAMILY_MAP[strategy_id], "candidate_count": 0,
            "results": [], "accepted_count": 0, "blockers": [], "next": "NO_SCREEN_CANDIDATE",
            "canonical_mutated": False, "registry_mutated": False, "route_allowed": False,
            "shadow_allowed": False, "execution_allowed": False,
        }
        _atomic_json(output_dir / "summary.json", report)
        print(json.dumps({"STATE": "PASS", "STRATEGY": strategy_id, "RESULT": "NO_SCREEN_CANDIDATE"}))
        return 0

    symbols = tuple(sorted({symbol for candidate in candidates for symbol in candidate.get("symbol_whitelist", []) if symbol in ALL_SYMBOLS}))
    if not symbols:
        symbols = ALL_SYMBOLS[:2]
    registry = base._load_registry(root)
    strategy = base._load_canonical_strategy(root, strategy_id, registry[strategy_id])
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    features: dict[tuple[str, str], pd.DataFrame] = {}
    fetch_results: list[dict[str, Any]] = []
    for role, anchor in zip(WINDOW_ROLES, ANCHOR_ENDS):
        end_ms = int(pd.Timestamp(anchor).timestamp() * 1000)
        end_ms = (end_ms // INTERVAL_MS) * INTERVAL_MS
        start_ms = end_ms - (args.window_bars - 1) * INTERVAL_MS
        for symbol in symbols:
            try:
                frame, endpoint, requests = base._fetch_exact(symbol, start_ms=start_ms, end_ms=end_ms, expected_rows=args.window_bars)
                frames[(role, symbol)] = frame
                features[(role, symbol)] = compute_feature_frame(frame)
                fetch_results.append({"window_id": role, "symbol": symbol, "status": "PASS", "rows": len(frame), "endpoint": endpoint, "request_count": requests})
            except Exception as exc:
                error = f"{role}:{symbol}:{type(exc).__name__}:{exc}"
                blockers.append(error)
                fetch_results.append({"window_id": role, "symbol": symbol, "status": "HOLD", "error": error})

    results: list[dict[str, Any]] = []
    if not blockers:
        for candidate in candidates:
            lane = str(candidate.get("lane") or "RETURN")
            candidate_symbols = tuple(symbol for symbol in candidate.get("symbol_whitelist", []) if symbol in symbols)
            if len(candidate_symbols) < 2:
                candidate_symbols = symbols
            gate = _gate_from(candidate)
            exit_spec = _exit_from(candidate)
            rows: list[dict[str, Any]] = []
            for role in WINDOW_ROLES:
                for symbol in candidate_symbols:
                    replay = _replay(
                        frames[(role, symbol)], features[(role, symbol)], strategy, gate, exit_spec, None,
                        warmup_bars=args.warmup_bars, history_bars=args.history_bars, cost_bps_per_side=args.cost_bps_per_side,
                    )
                    rows.append({"window_id": role, "symbol": symbol, **replay})
            evaluation = _evaluate(rows, lane, candidate_symbols)
            base_result = {
                "mode": "BASE_EXACT",
                "candidate": candidate,
                "symbols": list(candidate_symbols),
                "evaluation": evaluation,
                "surgery": None,
                "rows": [{"window_id": row["window_id"], "symbol": row["symbol"], "stats": row["stats"], "blocked_gate": row["blocked_gate"], "blocked_surgery": row["blocked_surgery"], "ignored_add_reduce": row["ignored_add_reduce"]} for row in rows],
            }
            results.append(base_result)

            tuning_trades = [trade for row in rows if row["window_id"] in WINDOW_ROLES[:8] for trade in row.get("trades", [])]
            for surgery in _surgery_candidates(tuning_trades):
                surgery_rows: list[dict[str, Any]] = []
                for role in WINDOW_ROLES:
                    for symbol in candidate_symbols:
                        replay = _replay(
                            frames[(role, symbol)], features[(role, symbol)], strategy, gate, exit_spec, surgery,
                            warmup_bars=args.warmup_bars, history_bars=args.history_bars, cost_bps_per_side=args.cost_bps_per_side,
                        )
                        surgery_rows.append({"window_id": role, "symbol": symbol, **replay})
                surgery_eval = _evaluate(surgery_rows, lane, candidate_symbols)
                results.append({
                    "mode": "SINGLE_CAUSE_SURGERY",
                    "candidate": candidate,
                    "symbols": list(candidate_symbols),
                    "evaluation": surgery_eval,
                    "surgery": {
                        "surgery_id": surgery.surgery_id,
                        "feature": surgery.feature,
                        "kind": surgery.kind,
                        "value": surgery.value,
                        "block_when": surgery.block_when,
                    },
                    "rows": [{"window_id": row["window_id"], "symbol": row["symbol"], "stats": row["stats"], "blocked_gate": row["blocked_gate"], "blocked_surgery": row["blocked_surgery"], "ignored_add_reduce": row["ignored_add_reduce"]} for row in surgery_rows],
                })

    results.sort(key=lambda value: (bool(value["evaluation"]["pass"]), _metric(value["evaluation"]["score"], -math.inf)), reverse=True)
    accepted = [value for value in results if value["evaluation"]["pass"]]
    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_EXACT_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "strategy_id": strategy_id,
        "family": FAMILY_MAP[strategy_id],
        "symbols_fetched": list(symbols),
        "candidate_count": len(candidates),
        "result_count": len(results),
        "accepted_count": len(accepted),
        "best": results[0] if results else None,
        "accepted": accepted[:5],
        "results": results[:8],
        "fetch_results": fetch_results,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "shadow_allowed": False,
        "execution_allowed": False,
        "next": "FINAL_DIVERSIFIED_ROSTER" if accepted else "KEEP_RESEARCH_HOLD",
    }
    _atomic_json(output_dir / "summary.json", report)
    print(json.dumps({
        "STATE": report["state"], "STRATEGY": strategy_id, "CANDIDATES": len(candidates),
        "RESULTS": len(results), "ACCEPTED": len(accepted), "BEST": results[0] if results else None,
        "BLOCKERS": blockers,
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
