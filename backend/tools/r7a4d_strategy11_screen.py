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

import pandas as pd

from backend.strategy25.strategy11_feature_library_v1 import (
    EXIT_SPECS,
    FAMILY_MAP,
    ExitSpec,
    GateSpec,
    compute_feature_frame,
    feature_snapshot,
    gate_allows,
    gate_specs_for,
)


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
INTERVAL_MS = 900_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
# BingX public kline retention no longer serves the original Aug-Nov 2025 anchors.
# These ten 900-bar windows are all mutually non-overlapping, remain before the
# current evaluation date, and preserve the S/V/H role split without reusing a
# window inside this funnel.
ANCHOR_ENDS = (
    "2025-12-15T00:00:00Z",
    "2026-01-05T00:00:00Z",
    "2026-01-25T00:00:00Z",
    "2026-02-15T00:00:00Z",
    "2026-03-05T00:00:00Z",
    "2026-03-25T00:00:00Z",
    "2026-04-15T00:00:00Z",
    "2026-05-05T00:00:00Z",
    "2026-05-25T00:00:00Z",
    "2026-06-15T00:00:00Z",
)
WINDOW_ROLES = ("S1", "S2", "S3", "S4", "S5", "S6", "V1", "V2", "H1", "H2")
WINDOW_BARS = 900
WARMUP_BARS = 220
HISTORY_BARS = 220
COST_BPS_PER_SIDE = 4.0


def _load_base() -> Any:
    name = "r7a4d_strategy11_base_runner"
    spec = importlib.util.spec_from_file_location(name, BASE_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base()


@dataclass(frozen=True)
class RawSignal:
    signal_index: int
    signal_ts: str
    entry: float
    sl: float
    tp: float
    size: float
    why: str
    skill: str
    tags: tuple[str, ...]
    features: dict[str, Any]


@dataclass
class Position:
    qty: float
    entry: float
    risk: float
    sl: float
    tp: float
    opened_at: str
    signal: RawSignal
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


def _call_strategy(strategy: Callable[..., dict[str, Any]], history: pd.DataFrame) -> dict[str, Any]:
    attempts = (
        lambda: strategy(history, state={}, risk_action="hold"),
        lambda: strategy(history, state={}),
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


def _raw_signals(
    frame: pd.DataFrame,
    feature_frame: pd.DataFrame,
    strategy: Callable[..., dict[str, Any]],
    *,
    warmup_bars: int,
    history_bars: int,
) -> tuple[list[RawSignal], int, int]:
    signals: list[RawSignal] = []
    calls = 0
    short_count = 0
    for index in range(warmup_bars, len(frame) - 1):
        history = frame.iloc[max(0, index - history_bars + 1) : index + 1].copy()
        result = _call_strategy(strategy, history)
        calls += 1
        action = str(result.get("action") or "hold").lower()
        side = str(result.get("side") or "").lower()
        if action != "enter":
            continue
        if side == "short":
            short_count += 1
            continue
        if side != "long":
            continue
        entry = float(result.get("entry") or 0.0) if _finite(result.get("entry")) else 0.0
        sl = float(result.get("sl") or 0.0) if _finite(result.get("sl")) else 0.0
        tp = float(result.get("tp") or 0.0) if _finite(result.get("tp")) else 0.0
        size = float(result.get("size") or 0.0) if _finite(result.get("size")) else 0.0
        if entry <= 0.0 or sl <= 0.0 or tp <= 0.0 or size <= 0.0:
            continue
        signals.append(
            RawSignal(
                signal_index=index,
                signal_ts=pd.Timestamp(frame["timestamp"].iloc[index]).isoformat(),
                entry=entry,
                sl=sl,
                tp=tp,
                size=size,
                why=str(result.get("why") or "unknown"),
                skill=str(result.get("skill") or "none"),
                tags=tuple(str(item) for item in (result.get("tags") or [])),
                features=feature_snapshot(feature_frame.iloc[index].to_dict()),
            )
        )
    return signals, calls, short_count


def _close_trade(
    position: Position,
    *,
    exit_price: float,
    exit_ts: str,
    reason: str,
    cost_rate: float,
) -> dict[str, Any]:
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
        "signal_ts": position.signal.signal_ts,
        "signal_why": position.signal.why,
        "signal_skill": position.signal.skill,
        "signal_tags": list(position.signal.tags),
        "features": position.signal.features,
    }


def _simulate(
    frame: pd.DataFrame,
    signals: Iterable[RawSignal],
    gate: GateSpec,
    exit_spec: ExitSpec,
    *,
    warmup_bars: int,
    cost_bps_per_side: float,
) -> dict[str, Any]:
    cost_rate = cost_bps_per_side / 10_000.0
    accepted = {
        signal.signal_index + 1: signal
        for signal in signals
        if gate_allows(gate, signal.features)
    }
    trades: list[dict[str, Any]] = []
    position: Position | None = None
    blocked = 0
    for signal in signals:
        if not gate_allows(gate, signal.features):
            blocked += 1

    for index in range(warmup_bars + 1, len(frame)):
        row = frame.iloc[index]
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        timestamp = pd.Timestamp(row["timestamp"]).isoformat()
        atr = float(row.get("atr14") or 0.0) if _finite(row.get("atr14")) else 0.0

        if position is None:
            signal = accepted.get(index)
            if signal is not None:
                raw_risk = signal.entry - signal.sl
                raw_reward = signal.tp - signal.entry
                risk = raw_risk * exit_spec.stop_mult
                reward = raw_reward * exit_spec.target_mult
                if risk > 0.0 and reward > 0.0:
                    target = open_ + reward
                    if exit_spec.runner_target_r is not None:
                        target = open_ + risk * exit_spec.runner_target_r
                    position = Position(
                        qty=signal.size,
                        entry=open_,
                        risk=risk,
                        sl=open_ - risk,
                        tp=target,
                        opened_at=timestamp,
                        signal=signal,
                        entry_cost_pct=signal.size * cost_rate * 100.0,
                    )
            continue

        position.bars_open += 1
        if position.pending_stop is not None:
            position.sl = max(position.sl, position.pending_stop)
            position.pending_stop = None

        if exit_spec.time_stop_bars is not None and position.bars_open >= exit_spec.time_stop_bars:
            trades.append(_close_trade(position, exit_price=open_, exit_ts=timestamp, reason="TIME_STOP", cost_rate=cost_rate))
            position = None
            continue

        hit_sl = low <= position.sl
        hit_tp = high >= position.tp
        if hit_sl or hit_tp:
            exit_price = position.sl if hit_sl else position.tp
            reason = "SL_CONSERVATIVE_SAME_BAR" if hit_sl and hit_tp else ("SL" if hit_sl else "TP")
            trades.append(_close_trade(position, exit_price=exit_price, exit_ts=timestamp, reason=reason, cost_rate=cost_rate))
            position = None
            continue

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

    if position is not None:
        last = frame.iloc[-1]
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
        "blocked_signal_count": blocked,
        "accepted_signal_count": len(accepted),
    }


def _combine(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    trades = [trade for row in rows for trade in row.get("trades", []) if isinstance(trade, dict)]
    stats = base._stats(trades)
    stats["max_drawdown_pct_conservative_sum"] = sum(float(row.get("stats", {}).get("max_drawdown_pct") or 0.0) for row in rows)
    return stats


def _metric(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


def _symbol_whitelist(selection_rows: list[dict[str, Any]]) -> tuple[str, ...]:
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for symbol in SYMBOLS:
        rows = [row for row in selection_rows if row["symbol"] == symbol]
        stats = _combine(rows)
        score = (
            _metric(stats.get("net_return_pct_sum")) * 5.0
            + (_metric(stats.get("net_profit_factor")) - 1.0) * 3.0
            + math.log1p(int(stats.get("trade_count") or 0))
        )
        scored.append((score, symbol, stats))
    qualified = [
        symbol
        for _, symbol, stats in scored
        if int(stats.get("trade_count") or 0) >= 3
        and _metric(stats.get("net_return_pct_sum")) > 0.0
        and _metric(stats.get("net_profit_factor")) >= 1.0
    ]
    if len(qualified) >= 2:
        return tuple(qualified[:4])
    return tuple(symbol for _, symbol, _ in sorted(scored, reverse=True)[:2])


def _positive_windows(rows: list[dict[str, Any]], roles: tuple[str, ...], whitelist: tuple[str, ...]) -> int:
    total = 0
    for role in roles:
        stats = _combine([row for row in rows if row["window_id"] == role and row["symbol"] in whitelist])
        if _metric(stats.get("net_return_pct_sum")) > 0.0:
            total += 1
    return total


def _positive_symbols(rows: list[dict[str, Any]], roles: tuple[str, ...], whitelist: tuple[str, ...]) -> int:
    total = 0
    for symbol in whitelist:
        stats = _combine([row for row in rows if row["window_id"] in roles and row["symbol"] == symbol])
        if _metric(stats.get("net_return_pct_sum")) > 0.0:
            total += 1
    return total


def _lane_pass(lane: str, selection: Mapping[str, Any], validation: Mapping[str, Any], holdout: Mapping[str, Any], pos_sel: int, pos_val: int, pos_hold: int, whitelist: tuple[str, ...]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(whitelist) < 2:
        reasons.append("SYMBOLS_LT_2")
    if int(selection.get("trade_count") or 0) < 20:
        reasons.append("SELECTION_TRADES_LT_20")
    if int(validation.get("trade_count") or 0) < 5:
        reasons.append("VALIDATION_TRADES_LT_5")
    if int(holdout.get("trade_count") or 0) < 5:
        reasons.append("HOLDOUT_TRADES_LT_5")
    if pos_sel < 3:
        reasons.append("SELECTION_POSITIVE_WINDOWS_LT_3")
    if pos_val < 1:
        reasons.append("VALIDATION_POSITIVE_WINDOWS_LT_1")
    if pos_hold < 1:
        reasons.append("HOLDOUT_POSITIVE_WINDOWS_LT_1")

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
        if _metric(selection.get("payoff_ratio")) <= 0.90:
            reasons.append("SELECTION_PAYOFF_LE_0_90")

    for prefix, stats in (("VALIDATION", validation), ("HOLDOUT", holdout)):
        if _metric(stats.get("net_return_pct_sum")) <= 0.0:
            reasons.append(f"{prefix}_NET_NOT_POSITIVE")
        if _metric(stats.get("net_profit_factor")) <= 1.0:
            reasons.append(f"{prefix}_PF_NOT_ABOVE_1")
        if lane == "WINRATE" and _metric(stats.get("win_rate_pct")) < 35.0:
            reasons.append(f"{prefix}_WR_LT_35")
    return not reasons, reasons


def _score(lane: str, selection: Mapping[str, Any], validation: Mapping[str, Any], holdout: Mapping[str, Any], pos_sel: int, pos_val: int, pos_hold: int, whitelist: tuple[str, ...]) -> float:
    net = _metric(selection.get("net_return_pct_sum"))
    pf = _metric(selection.get("net_profit_factor"))
    payoff = _metric(selection.get("payoff_ratio"))
    wr = _metric(selection.get("win_rate_pct"))
    dd = _metric(selection.get("max_drawdown_pct_conservative_sum"))
    trades = int(selection.get("trade_count") or 0)
    val_net = _metric(validation.get("net_return_pct_sum"))
    hold_net = _metric(holdout.get("net_return_pct_sum"))
    if lane == "RETURN":
        return net * 6.0 + (pf - 1.0) * 18.0 + payoff * 2.0 + wr * 0.08 - dd * 1.5 + val_net * 4.0 + hold_net * 5.0 + (pos_sel + pos_val + pos_hold) * 2.0 + len(whitelist) * 1.5 + math.log1p(trades)
    return wr * 0.35 + net * 4.0 + (pf - 1.0) * 15.0 + payoff * 1.5 - dd + val_net * 3.0 + hold_net * 4.0 + (pos_sel + pos_val + pos_hold) * 2.0 + len(whitelist) + math.log1p(trades)


def _candidate_record(strategy_id: str, gate: GateSpec, exit_spec: ExitSpec, rows: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    selection_roles = WINDOW_ROLES[:6]
    validation_roles = WINDOW_ROLES[6:8]
    holdout_roles = WINDOW_ROLES[8:]
    selection_rows = [row for row in rows if row["window_id"] in selection_roles]
    whitelist = _symbol_whitelist(selection_rows)
    selection = _combine([row for row in rows if row["window_id"] in selection_roles and row["symbol"] in whitelist])
    validation = _combine([row for row in rows if row["window_id"] in validation_roles and row["symbol"] in whitelist])
    holdout = _combine([row for row in rows if row["window_id"] in holdout_roles and row["symbol"] in whitelist])
    pos_sel = _positive_windows(rows, selection_roles, whitelist)
    pos_val = _positive_windows(rows, validation_roles, whitelist)
    pos_hold = _positive_windows(rows, holdout_roles, whitelist)
    passed, reasons = _lane_pass(lane, selection, validation, holdout, pos_sel, pos_val, pos_hold, whitelist)
    return {
        "strategy_id": strategy_id,
        "family": FAMILY_MAP[strategy_id],
        "lane": lane,
        "gate": {
            "gate_id": gate.gate_id,
            "required": list(gate.required),
            "forbidden": list(gate.forbidden),
            "description": gate.description,
        },
        "exit": {
            "exit_id": exit_spec.exit_id,
            "stop_mult": exit_spec.stop_mult,
            "target_mult": exit_spec.target_mult,
            "breakeven_r": exit_spec.breakeven_r,
            "partial_r": exit_spec.partial_r,
            "partial_fraction": exit_spec.partial_fraction,
            "runner_target_r": exit_spec.runner_target_r,
            "trail_activate_r": exit_spec.trail_activate_r,
            "trail_atr_mult": exit_spec.trail_atr_mult,
            "time_stop_bars": exit_spec.time_stop_bars,
        },
        "symbol_whitelist": list(whitelist),
        "selection": selection,
        "validation": validation,
        "holdout": holdout,
        "positive_windows": {"selection": pos_sel, "validation": pos_val, "holdout": pos_hold},
        "positive_symbols_selection": _positive_symbols(rows, selection_roles, whitelist),
        "pass": passed,
        "failure_reasons": reasons,
        "score": _score(lane, selection, validation, holdout, pos_sel, pos_val, pos_hold, whitelist),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--window-bars", type=int, default=WINDOW_BARS)
    parser.add_argument("--warmup-bars", type=int, default=WARMUP_BARS)
    parser.add_argument("--history-bars", type=int, default=HISTORY_BARS)
    parser.add_argument("--cost-bps-per-side", type=float, default=COST_BPS_PER_SIDE)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    strategy_id = str(args.strategy_id)
    if strategy_id not in FAMILY_MAP:
        raise ValueError(f"STRATEGY_UNKNOWN:{strategy_id}")
    registry = base._load_registry(root)
    strategy = base._load_canonical_strategy(root, strategy_id, registry[strategy_id])
    output_dir = root / "artifacts/strategy11_screen_v1" / strategy_id

    blockers: list[str] = []
    fetch_results: list[dict[str, Any]] = []
    raw_by_window_symbol: dict[tuple[str, str], list[RawSignal]] = {}
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    raw_counts: list[dict[str, Any]] = []

    for role, anchor in zip(WINDOW_ROLES, ANCHOR_ENDS):
        end_ms = int(pd.Timestamp(anchor).timestamp() * 1000)
        end_ms = (end_ms // INTERVAL_MS) * INTERVAL_MS
        start_ms = end_ms - (args.window_bars - 1) * INTERVAL_MS
        for symbol in SYMBOLS:
            try:
                frame, endpoint, request_count = base._fetch_exact(symbol, start_ms=start_ms, end_ms=end_ms, expected_rows=args.window_bars)
                features = compute_feature_frame(frame)
                signals, calls, short_count = _raw_signals(frame, features, strategy, warmup_bars=args.warmup_bars, history_bars=args.history_bars)
                frames[(role, symbol)] = features
                raw_by_window_symbol[(role, symbol)] = signals
                fetch_results.append({"window_id": role, "symbol": symbol, "status": "PASS", "rows": len(frame), "endpoint": endpoint, "request_count": request_count})
                raw_counts.append({"window_id": role, "symbol": symbol, "long_signal_count": len(signals), "short_signal_count": short_count, "call_count": calls})
            except Exception as exc:
                error = f"{role}:{symbol}:{type(exc).__name__}:{exc}"
                blockers.append(error)
                fetch_results.append({"window_id": role, "symbol": symbol, "status": "HOLD", "error": error})

    candidates: list[dict[str, Any]] = []
    if not blockers:
        for gate in gate_specs_for(strategy_id):
            for exit_spec in EXIT_SPECS:
                rows: list[dict[str, Any]] = []
                for role in WINDOW_ROLES:
                    for symbol in SYMBOLS:
                        replay = _simulate(
                            frames[(role, symbol)],
                            raw_by_window_symbol[(role, symbol)],
                            gate,
                            exit_spec,
                            warmup_bars=args.warmup_bars,
                            cost_bps_per_side=args.cost_bps_per_side,
                        )
                        rows.append({"window_id": role, "symbol": symbol, **replay})
                for lane in ("RETURN", "WINRATE"):
                    candidates.append(_candidate_record(strategy_id, gate, exit_spec, rows, lane))

    candidates.sort(key=lambda item: float(item["score"]), reverse=True)
    accepted = [item for item in candidates if item["pass"]]
    top_return = sorted((item for item in candidates if item["lane"] == "RETURN"), key=lambda item: float(item["score"]), reverse=True)[:12]
    top_winrate = sorted((item for item in candidates if item["lane"] == "WINRATE"), key=lambda item: float(item["score"]), reverse=True)[:12]
    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_SCREEN_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "strategy_id": strategy_id,
        "family": FAMILY_MAP[strategy_id],
        "interval": "15m",
        "symbols": list(SYMBOLS),
        "window_contract": {
            "anchors": list(ANCHOR_ENDS),
            "roles": list(WINDOW_ROLES),
            "window_bars": args.window_bars,
            "warmup_bars": args.warmup_bars,
            "evaluation_bars": args.window_bars - args.warmup_bars,
            "history_bars": args.history_bars,
            "cost_bps_per_side": args.cost_bps_per_side,
            "completed_bar_only": True,
            "next_bar_open": True,
            "same_bar_sl_tp": "SL_FIRST_CONSERVATIVE",
            "long_only": True,
            "state_normalized_entry_screen": True,
        },
        "gate_count": len(gate_specs_for(strategy_id)),
        "exit_count": len(EXIT_SPECS),
        "candidate_count": len(candidates),
        "accepted_count": len(accepted),
        "accepted_candidates": accepted[:20],
        "top_return": top_return,
        "top_winrate": top_winrate,
        "raw_signal_counts": raw_counts,
        "fetch_results": fetch_results,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "shadow_allowed": False,
        "execution_allowed": False,
        "next": "AGGREGATE_AND_EXACT_REPLAY" if not blockers else "HOLD_DATA_OR_RUNTIME_BLOCKER",
    }
    _atomic_json(output_dir / "summary.json", report)
    print(json.dumps({
        "STATE": report["state"],
        "STRATEGY": strategy_id,
        "FAMILY": report["family"],
        "RAW_LONG_SIGNALS": sum(item["long_signal_count"] for item in raw_counts),
        "CANDIDATES": len(candidates),
        "ACCEPTED": len(accepted),
        "BEST_RETURN": top_return[0] if top_return else None,
        "BEST_WINRATE": top_winrate[0] if top_winrate else None,
        "BLOCKERS": blockers,
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
