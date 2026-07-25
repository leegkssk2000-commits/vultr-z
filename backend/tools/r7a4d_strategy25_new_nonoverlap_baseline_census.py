from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.strategy25.indicator_contract_repair_adapter_v2 import REPAIR_SPECS
from backend.strategy25.indicator_contract_repair_loader_v2 import load_repaired_strategy
from backend.tools.r7a4d_strategy25_runtime_owner_contract_audit import EXPECTED_IDS


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
OUTPUT_DIR = "artifacts/strategy25_new_nonoverlap_baseline_census_v1"


def _load_base_runner() -> Any:
    module_name = "r7a4d_strategy25_census_base_runner_v1"
    spec = importlib.util.spec_from_file_location(module_name, BASE_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base_runner()


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


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


def _score(stats: Mapping[str, Any], positive_symbols: int) -> float:
    trades = int(stats.get("trade_count") or 0)
    net = _number(stats.get("net_return_pct_sum"), -1000.0)
    pf = _number(stats.get("net_profit_factor"), 0.0)
    payoff = _number(stats.get("payoff_ratio"), 0.0)
    if trades <= 0:
        return -1e9
    return (
        net * math.log1p(trades)
        + max(pf - 1.0, -2.0) * 10.0
        + max(payoff - 1.0, -2.0) * 2.0
        + positive_symbols * 1.5
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--window-bars", type=int, default=1200)
    parser.add_argument("--warmup-bars", type=int, default=220)
    parser.add_argument("--history-bars", type=int, default=220)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = root / OUTPUT_DIR
    if args.warmup_bars < 100 or args.warmup_bars >= args.window_bars:
        raise ValueError("WARMUP_CONTRACT_INVALID")
    if args.history_bars < 100:
        raise ValueError("HISTORY_CONTRACT_INVALID")

    previous_end_ms = int(pd.Timestamp(base.FIXED_END_ISO).timestamp() * 1000)
    previous_end_ms = (previous_end_ms // base.INTERVAL_MS) * base.INTERVAL_MS
    previous_total_bars = int(base.WINDOW_BARS) * 2
    previous_start_ms = previous_end_ms - (previous_total_bars - 1) * base.INTERVAL_MS
    census_end_ms = previous_start_ms - base.INTERVAL_MS
    census_start_ms = census_end_ms - (args.window_bars - 1) * base.INTERVAL_MS

    registry = base._load_registry(root)
    blockers: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    fetch_results: list[dict[str, Any]] = []

    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, request_count = base._fetch_exact(
                symbol,
                start_ms=census_start_ms,
                end_ms=census_end_ms,
                expected_rows=args.window_bars,
            )
            frames[symbol] = frame
            fetch_results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "rows": len(frame),
                    "start": pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
                    "end": pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
                    "endpoint": endpoint,
                    "request_count": request_count,
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    results: list[dict[str, Any]] = []
    all_trades: dict[str, list[dict[str, Any]]] = {}
    if not blockers:
        for strategy_id in EXPECTED_IDS:
            try:
                canonical = base._load_canonical_strategy(root, strategy_id, registry[strategy_id])
                effective = load_repaired_strategy(root, strategy_id) if strategy_id in REPAIR_SPECS else canonical
                variant = "CONTRACT_REPAIRED_CHILD" if strategy_id in REPAIR_SPECS else "CANONICAL_OWNER_LOCKED"
                symbol_rows: list[dict[str, Any]] = []
                runs: list[dict[str, Any]] = []
                trade_rows: list[dict[str, Any]] = []

                for symbol in base.SYMBOLS:
                    replay = base._replay(
                        frames[symbol],
                        effective,
                        warmup_bars=args.warmup_bars,
                        history_bars=args.history_bars,
                        cost_bps_per_side=args.cost_bps_per_side,
                    )
                    runs.append(replay)
                    for trade in replay.get("trades", []):
                        if isinstance(trade, dict):
                            trade_rows.append({"symbol": symbol, **trade})
                    symbol_rows.append(
                        {
                            "symbol": symbol,
                            "stats": replay["stats"],
                            "signal_count": replay.get("signal_count"),
                            "short_signal_count": replay.get("short_signal_count"),
                            "rejected_entry_count": replay.get("rejected_entry_count"),
                            "add_count": replay.get("add_count"),
                            "reduce_count": replay.get("reduce_count"),
                        }
                    )

                stats = base._aggregate(runs)
                positive_symbols = sum(
                    _number(row["stats"].get("net_return_pct_sum")) > 0.0
                    for row in symbol_rows
                )
                trade_count = int(stats.get("trade_count") or 0)
                net = _number(stats.get("net_return_pct_sum"), -math.inf)
                pf = _number(stats.get("net_profit_factor"), 0.0)
                payoff = _number(stats.get("payoff_ratio"), 0.0)
                strict_eligible = bool(
                    trade_count >= 20
                    and net > 0.0
                    and pf > 1.0
                    and positive_symbols >= 3
                    and payoff >= 0.95
                )
                diagnostic_eligible = bool(trade_count >= 20 and positive_symbols >= 2)
                result = {
                    "strategy_id": strategy_id,
                    "status": "PASS",
                    "variant": variant,
                    "stats": stats,
                    "positive_symbols": positive_symbols,
                    "strict_selection_eligible": strict_eligible,
                    "diagnostic_selection_eligible": diagnostic_eligible,
                    "selection_score": _score(stats, positive_symbols),
                    "symbols": symbol_rows,
                }
                results.append(result)
                all_trades[strategy_id] = trade_rows
            except Exception as exc:
                error = f"{strategy_id}:{type(exc).__name__}:{exc}"
                blockers.append(error)
                results.append({"strategy_id": strategy_id, "status": "HOLD", "error": error})

    strict = sorted(
        [row for row in results if row.get("strict_selection_eligible")],
        key=lambda row: float(row["selection_score"]),
        reverse=True,
    )
    diagnostic = sorted(
        [row for row in results if row.get("diagnostic_selection_eligible")],
        key=lambda row: float(row["selection_score"]),
        reverse=True,
    )
    selected = strict[0] if strict else (diagnostic[0] if diagnostic else None)
    selection_mode = "STRICT_ECONOMIC" if strict else ("DIAGNOSTIC_BEST_AVAILABLE" if selected else "NONE")
    selected_id = str(selected["strategy_id"]) if selected else None

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_NEW_NONOVERLAP_CENSUS_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "interval": base.INTERVAL,
        "symbols": list(base.SYMBOLS),
        "census_window": {
            "start": pd.Timestamp(census_start_ms, unit="ms", tz="UTC").isoformat(),
            "end": pd.Timestamp(census_end_ms, unit="ms", tz="UTC").isoformat(),
            "bars": args.window_bars,
            "warmup_bars": args.warmup_bars,
            "evaluation_bars": args.window_bars - args.warmup_bars,
        },
        "nonoverlap_proof": {
            "prior_two_window_start": pd.Timestamp(previous_start_ms, unit="ms", tz="UTC").isoformat(),
            "prior_two_window_end": pd.Timestamp(previous_end_ms, unit="ms", tz="UTC").isoformat(),
            "census_end_before_prior_start_by_ms": previous_start_ms - census_end_ms,
            "overlap": False,
        },
        "cost_bps_per_side": args.cost_bps_per_side,
        "fetch_results": fetch_results,
        "results": results,
        "strict_eligible_ids": [row["strategy_id"] for row in strict],
        "selected_strategy_id": selected_id,
        "selection_mode": selection_mode,
        "selected_summary": selected,
        "selected_trades": all_trades.get(selected_id, []) if selected_id else [],
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "next": "RUN_SINGLE_LOSS_CAUSE_ANATOMY_AND_SURGERY" if selected_id and not blockers else "HOLD_NO_CENSUS_CANDIDATE",
    }
    _atomic_json(output_dir / "summary.json", report)
    print(
        json.dumps(
            {
                "STATE": report["state"],
                "BLOCKERS": len(blockers),
                "STRICT_ELIGIBLE": report["strict_eligible_ids"],
                "SELECTED": selected_id,
                "MODE": selection_mode,
                "SELECTED_STATS": selected.get("stats") if selected else None,
                "SELECTED_POSITIVE_SYMBOLS": selected.get("positive_symbols") if selected else None,
                "NEXT": report["next"],
            },
            sort_keys=True,
        )
    )
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
