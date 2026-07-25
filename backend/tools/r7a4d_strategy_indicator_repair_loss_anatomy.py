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
from typing import Any, Callable, Mapping

import pandas as pd

from backend.strategy25.indicator_contract_repair_adapter_v1 import REPAIR_SPECS
from backend.strategy25.indicator_contract_repair_loader_v1 import load_repaired_strategy


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
OUTPUT_DIR = ROOT / "artifacts/strategy_indicator_repair_loss_anatomy_v1"


def _load_base_runner() -> Any:
    module_name = "r7a4d_strategy_indicator_repairs_real_oos_base_v1"
    spec = importlib.util.spec_from_file_location(module_name, BASE_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base_runner()


@dataclass
class TracePosition:
    qty: float
    avg_entry: float
    sl: float
    tp: float
    opened_at: str
    signal_at: str
    entry_why: str
    entry_skill: str
    entry_tags: tuple[str, ...]
    entry_indicators: dict[str, Any]
    realized_pct: float = 0.0
    cost_pct: float = 0.0
    add_count: int = 0


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


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


def _safe_indicator_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, bool) or item is None or isinstance(item, str):
            result[str(key)] = item
        elif isinstance(item, (int, float)) and _finite(item):
            result[str(key)] = float(item)
    return result


def _trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return base._stats(trades)


def _close_position(
    position: TracePosition,
    *,
    exit_price: float,
    timestamp: str,
    reason: str,
    cost_rate: float,
) -> dict[str, Any]:
    gross = position.qty * ((exit_price / position.avg_entry) - 1.0) * 100.0
    exit_cost = position.qty * cost_rate * 100.0
    net = position.realized_pct + gross - position.cost_pct - exit_cost
    return {
        "signal_ts": position.signal_at,
        "entry_ts": position.opened_at,
        "exit_ts": timestamp,
        "entry_price": position.avg_entry,
        "exit_price": exit_price,
        "qty": position.qty,
        "net_return_pct": net,
        "exit_reason": reason,
        "add_count": position.add_count,
        "entry_why": position.entry_why,
        "entry_skill": position.entry_skill,
        "entry_tags": list(position.entry_tags),
        "entry_indicators": position.entry_indicators,
    }


def _replay_trace(
    frame: pd.DataFrame,
    strategy: Callable[..., dict[str, Any]],
    *,
    warmup_bars: int,
    history_bars: int,
    cost_bps_per_side: float,
) -> dict[str, Any]:
    cost_rate = cost_bps_per_side / 10_000.0
    position: TracePosition | None = None
    pending: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    signal_events: list[dict[str, Any]] = []
    rejected_entries: list[dict[str, Any]] = []
    add_count = 0
    reduce_count = 0
    call_count = 0

    for index in range(warmup_bars, len(frame)):
        row = frame.iloc[index]
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        timestamp = pd.Timestamp(row["timestamp"]).isoformat()

        if pending is not None:
            action = str(pending.get("action") or "hold").lower()
            side = str(pending.get("side") or "").lower()
            size = float(pending.get("size") or 0.0) if _finite(pending.get("size")) else 0.0
            signal_entry = float(pending.get("entry") or 0.0) if _finite(pending.get("entry")) else 0.0
            signal_sl = float(pending.get("sl") or 0.0) if _finite(pending.get("sl")) else 0.0
            signal_tp = float(pending.get("tp") or 0.0) if _finite(pending.get("tp")) else 0.0
            why = str(pending.get("why") or "unknown")
            skill = str(pending.get("skill") or "none")
            tags = tuple(str(item) for item in (pending.get("tags") or []))
            indicators = _safe_indicator_snapshot(pending.get("indicators"))

            if side == "long" and action == "enter" and position is None:
                risk = signal_entry - signal_sl
                reward = signal_tp - signal_entry
                if size > 0.0 and risk > 0.0 and reward > 0.0:
                    position = TracePosition(
                        qty=size,
                        avg_entry=open_,
                        sl=open_ - risk,
                        tp=open_ + reward,
                        opened_at=timestamp,
                        signal_at=str(pending.get("signal_ts") or timestamp),
                        entry_why=why,
                        entry_skill=skill,
                        entry_tags=tags,
                        entry_indicators=indicators,
                        cost_pct=size * cost_rate * 100.0,
                    )
                else:
                    rejected_entries.append(
                        {
                            "fill_ts": timestamp,
                            "signal_ts": pending.get("signal_ts"),
                            "side": side,
                            "action": action,
                            "why": why,
                            "skill": skill,
                            "size": size,
                            "risk": risk,
                            "reward": reward,
                        }
                    )
            elif side == "long" and action == "add" and position is not None and size > 0.0:
                new_qty = position.qty + size
                position.avg_entry = ((position.avg_entry * position.qty) + (open_ * size)) / new_qty
                position.qty = new_qty
                position.cost_pct += size * cost_rate * 100.0
                position.add_count += 1
                add_count += 1
            elif side == "long" and action == "reduce" and position is not None and size > 0.0:
                reduce_qty = min(size, position.qty)
                position.realized_pct += reduce_qty * ((open_ / position.avg_entry) - 1.0) * 100.0
                position.cost_pct += reduce_qty * cost_rate * 100.0
                position.qty -= reduce_qty
                reduce_count += 1
                if position.qty <= 1e-9:
                    trade = _close_position(
                        position,
                        exit_price=open_,
                        timestamp=timestamp,
                        reason="REDUCE_TO_ZERO",
                        cost_rate=0.0,
                    )
                    trade["qty"] = 0.0
                    trades.append(trade)
                    position = None
            pending = None

        if position is not None:
            hit_sl = low <= position.sl
            hit_tp = high >= position.tp
            if hit_sl or hit_tp:
                exit_price = position.sl if hit_sl else position.tp
                reason = "SL_CONSERVATIVE_SAME_BAR" if hit_sl and hit_tp else ("SL" if hit_sl else "TP")
                trades.append(
                    _close_position(
                        position,
                        exit_price=exit_price,
                        timestamp=timestamp,
                        reason=reason,
                        cost_rate=cost_rate,
                    )
                )
                position = None

        if index >= len(frame) - 1:
            break

        history = frame.iloc[max(0, index - history_bars + 1) : index + 1].copy()
        state = {
            "position_side": "long" if position is not None else "",
            "position_qty": position.qty if position is not None else 0.0,
            "avg_entry": position.avg_entry if position is not None else 0.0,
            "add_count": position.add_count if position is not None else 0,
            "last_add_price": position.avg_entry if position is not None else 0.0,
        }
        result = strategy(history, state=state, risk_action="hold")
        call_count += 1
        if not isinstance(result, dict):
            raise RuntimeError("STRATEGY_RESULT_NOT_DICT")

        action = str(result.get("action") or "hold").lower()
        side = str(result.get("side") or "").lower()
        if action in {"enter", "add", "reduce"}:
            event = {
                "signal_ts": timestamp,
                "side": side,
                "action": action,
                "why": str(result.get("why") or "unknown"),
                "skill": str(result.get("skill") or "none"),
                "tags": [str(item) for item in (result.get("tags") or [])],
                "size": float(result.get("size") or 0.0) if _finite(result.get("size")) else 0.0,
                "entry": float(result.get("entry") or 0.0) if _finite(result.get("entry")) else 0.0,
                "sl": float(result.get("sl") or 0.0) if _finite(result.get("sl")) else 0.0,
                "tp": float(result.get("tp") or 0.0) if _finite(result.get("tp")) else 0.0,
                "indicators": _safe_indicator_snapshot(result.get("indicators")),
            }
            signal_events.append(event)
            event["signal_ts"] = timestamp
            pending = dict(result)
            pending["signal_ts"] = timestamp

    if position is not None:
        last = frame.iloc[-1]
        trades.append(
            _close_position(
                position,
                exit_price=float(last["close"]),
                timestamp=pd.Timestamp(last["timestamp"]).isoformat(),
                reason="WINDOW_END",
                cost_rate=cost_rate,
            )
        )

    return {
        "stats": _trade_stats(trades),
        "trades": trades,
        "signal_events": signal_events,
        "signal_count": len(signal_events),
        "rejected_entries": rejected_entries,
        "rejected_entry_count": len(rejected_entries),
        "add_count": add_count,
        "reduce_count": reduce_count,
        "call_count": call_count,
    }


def _cluster_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["variant"]),
            str(row["strategy_id"]),
            str(row["window_id"]),
            str(row["symbol"]),
            str(row.get("entry_why") or "unknown"),
            str(row.get("entry_skill") or "none"),
            str(row.get("exit_reason") or "unknown"),
        )
        grouped.setdefault(key, []).append(row)

    clusters: list[dict[str, Any]] = []
    for key, items in grouped.items():
        returns = [float(item["net_return_pct"]) for item in items]
        clusters.append(
            {
                "variant": key[0],
                "strategy_id": key[1],
                "window_id": key[2],
                "symbol": key[3],
                "entry_why": key[4],
                "entry_skill": key[5],
                "exit_reason": key[6],
                "trade_count": len(items),
                "win_count": sum(value > 0.0 for value in returns),
                "loss_count": sum(value < 0.0 for value in returns),
                "net_return_pct_sum": sum(returns),
                "average_return_pct": sum(returns) / len(returns),
                "worst_trade_pct": min(returns),
                "best_trade_pct": max(returns),
            }
        )
    return sorted(clusters, key=lambda item: (float(item["net_return_pct_sum"]), -int(item["trade_count"])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--fixed-end", default=base.FIXED_END_ISO)
    parser.add_argument("--window-bars", type=int, default=base.WINDOW_BARS)
    parser.add_argument("--warmup-bars", type=int, default=base.WARMUP_BARS)
    parser.add_argument("--history-bars", type=int, default=base.HISTORY_BARS)
    parser.add_argument("--cost-bps-per-side", type=float, default=base.COST_BPS_PER_SIDE)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = root / "artifacts/strategy_indicator_repair_loss_anatomy_v1"
    total_bars = args.window_bars * 2
    end_ms = int(pd.Timestamp(args.fixed_end).timestamp() * 1000)
    end_ms = (end_ms // base.INTERVAL_MS) * base.INTERVAL_MS
    start_ms = end_ms - (total_bars - 1) * base.INTERVAL_MS

    registry = base._load_registry(root)
    frames: dict[str, pd.DataFrame] = {}
    fetch_results: list[dict[str, Any]] = []
    blockers: list[str] = []

    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, requests = base._fetch_exact(
                symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                expected_rows=total_bars,
            )
            frames[symbol] = frame
            fetch_results.append({"symbol": symbol, "status": "PASS", "rows": len(frame), "endpoint": endpoint, "request_count": requests})
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    run_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    signal_reason_rows: list[dict[str, Any]] = []

    if not blockers:
        for strategy_id in REPAIR_SPECS:
            try:
                strategies = {
                    "baseline": base._load_canonical_strategy(root, strategy_id, registry[strategy_id]),
                    "candidate": load_repaired_strategy(root, strategy_id),
                }
                for window_index in range(2):
                    start = window_index * args.window_bars
                    end = start + args.window_bars
                    window_id = f"W{window_index + 1}"
                    for symbol in base.SYMBOLS:
                        window = frames[symbol].iloc[start:end].reset_index(drop=True)
                        for variant, strategy in strategies.items():
                            replay = _replay_trace(
                                window,
                                strategy,
                                warmup_bars=args.warmup_bars,
                                history_bars=args.history_bars,
                                cost_bps_per_side=args.cost_bps_per_side,
                            )
                            run_rows.append(
                                {
                                    "variant": variant,
                                    "strategy_id": strategy_id,
                                    "window_id": window_id,
                                    "symbol": symbol,
                                    "stats": replay["stats"],
                                    "signal_count": replay["signal_count"],
                                    "rejected_entry_count": replay["rejected_entry_count"],
                                    "add_count": replay["add_count"],
                                    "reduce_count": replay["reduce_count"],
                                    "call_count": replay["call_count"],
                                }
                            )
                            for trade in replay["trades"]:
                                trade_rows.append(
                                    {
                                        "variant": variant,
                                        "strategy_id": strategy_id,
                                        "window_id": window_id,
                                        "symbol": symbol,
                                        **trade,
                                    }
                                )
                            reasons: dict[tuple[str, str, str, str], int] = {}
                            for event in replay["signal_events"]:
                                key = (
                                    str(event.get("side") or ""),
                                    str(event.get("action") or "hold"),
                                    str(event.get("why") or "unknown"),
                                    str(event.get("skill") or "none"),
                                )
                                reasons[key] = reasons.get(key, 0) + 1
                            for key, count in sorted(reasons.items()):
                                signal_reason_rows.append(
                                    {
                                        "variant": variant,
                                        "strategy_id": strategy_id,
                                        "window_id": window_id,
                                        "symbol": symbol,
                                        "side": key[0],
                                        "action": key[1],
                                        "why": key[2],
                                        "skill": key[3],
                                        "count": count,
                                    }
                                )
            except Exception as exc:
                blockers.append(f"{strategy_id}:{type(exc).__name__}:{exc}")

    clusters = _cluster_rows(trade_rows)
    candidate_loss_clusters = [
        row for row in clusters if row["variant"] == "candidate" and float(row["net_return_pct_sum"]) < 0.0
    ]
    strategy_verdicts: list[dict[str, Any]] = []
    for strategy_id in REPAIR_SPECS:
        baseline = [row for row in run_rows if row["strategy_id"] == strategy_id and row["variant"] == "baseline"]
        candidate = [row for row in run_rows if row["strategy_id"] == strategy_id and row["variant"] == "candidate"]
        baseline_trades = sum(int(row["stats"]["trade_count"]) for row in baseline)
        candidate_trades = sum(int(row["stats"]["trade_count"]) for row in candidate)
        baseline_net = sum(float(row["stats"]["net_return_pct_sum"]) for row in baseline)
        candidate_net = sum(float(row["stats"]["net_return_pct_sum"]) for row in candidate)
        identical = bool(
            baseline_trades == candidate_trades
            and abs(baseline_net - candidate_net) <= 1e-12
            and all(
                int(left["signal_count"]) == int(right["signal_count"])
                for left, right in zip(baseline, candidate)
            )
        )
        if candidate_trades == 0:
            verdict = "NO_TRADE_EVIDENCE"
        elif identical:
            verdict = "REPAIR_NO_BEHAVIORAL_DELTA"
        elif candidate_net <= 0.0:
            verdict = "ACTIVE_BUT_NOT_ECONOMIC"
        else:
            per_window = []
            for window_id in ("W1", "W2"):
                per_window.append(
                    sum(
                        float(row["stats"]["net_return_pct_sum"])
                        for row in candidate
                        if row["window_id"] == window_id
                    )
                )
            verdict = "WINDOW_UNSTABLE" if min(per_window) <= 0.0 else "POSITIVE_BUT_UNDERDIVERSIFIED"
        strategy_verdicts.append(
            {
                "strategy_id": strategy_id,
                "verdict": verdict,
                "baseline_trade_count": baseline_trades,
                "candidate_trade_count": candidate_trades,
                "baseline_net_return_pct_sum": baseline_net,
                "candidate_net_return_pct_sum": candidate_net,
                "candidate_minus_baseline_net_pct": candidate_net - baseline_net,
            }
        )

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_RESEARCH_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "fixed_end": pd.Timestamp(end_ms, unit="ms", tz="UTC").isoformat(),
        "interval": base.INTERVAL,
        "symbols": list(base.SYMBOLS),
        "strategies": list(REPAIR_SPECS),
        "window_bars": args.window_bars,
        "warmup_bars": args.warmup_bars,
        "cost_bps_per_side": args.cost_bps_per_side,
        "fetch_results": fetch_results,
        "strategy_verdicts": strategy_verdicts,
        "run_rows": run_rows,
        "signal_reason_rows": signal_reason_rows,
        "trade_rows": trade_rows,
        "loss_clusters": candidate_loss_clusters,
        "worst_candidate_loss_cluster": candidate_loss_clusters[0] if candidate_loss_clusters else None,
        "blockers": blockers,
        "canonical_sources_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "next": "TARGET_SINGLE_WORST_LOSS_CLUSTER_ONLY" if candidate_loss_clusters and not blockers else "KEEP_HOLD_NO_REPAIR_PROMOTION",
    }
    _atomic_json(output_dir / "anatomy.json", report)
    print(
        json.dumps(
            {
                "STATE": report["state"],
                "BLOCKERS": len(blockers),
                "WORST": report["worst_candidate_loss_cluster"],
                "VERDICTS": strategy_verdicts,
                "NEXT": report["next"],
            },
            sort_keys=True,
        )
    )
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
