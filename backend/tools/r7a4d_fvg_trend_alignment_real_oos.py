from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from backend.strategy25.fvg_trend_alignment_child_v1 import (
    CHILD_MANIFEST,
    POLICY_ID,
    load_fvg_trend_aligned_strategy,
)
from backend.strategy25.indicator_contract_repair_loader_v1 import load_repaired_strategy


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
OUTPUT_DIR = "artifacts/r7a4d_fvg_trend_alignment_real_oos_v1"
STRATEGY_ID = "fvg_revert"


def _load_base_runner() -> Any:
    module_name = "r7a4d_strategy_indicator_repairs_real_oos_for_fvg_gate_v1"
    spec = importlib.util.spec_from_file_location(module_name, BASE_RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base_runner()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


def _tracked_gate(strategy: Callable[..., dict[str, Any]]) -> tuple[Callable[..., dict[str, Any]], dict[str, int]]:
    counter = {"blocked_long_entry_count": 0, "call_count": 0}

    def tracked(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = strategy(*args, **kwargs)
        counter["call_count"] += 1
        indicators = result.get("indicators") if isinstance(result, Mapping) else None
        if isinstance(indicators, Mapping) and indicators.get("trend_alignment_gate_blocked") is True:
            counter["blocked_long_entry_count"] += 1
        return result

    return tracked, counter


def _window_pass(candidate: Mapping[str, Any], repaired: Mapping[str, Any], positive_symbols: int, gate_blocks: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    candidate_trades = int(candidate.get("trade_count") or 0)
    candidate_net = _number(candidate.get("net_return_pct_sum"), -math.inf)
    candidate_pf = _number(candidate.get("net_profit_factor"), 0.0)
    candidate_payoff = _number(candidate.get("payoff_ratio"), 0.0)
    repaired_net = _number(repaired.get("net_return_pct_sum"), 0.0)
    repaired_pf = _number(repaired.get("net_profit_factor"), 0.0)
    repaired_payoff = _number(repaired.get("payoff_ratio"), 0.0)

    if candidate_trades < 5:
        reasons.append("TRADE_COUNT_LT_5")
    if candidate_net <= 0.0:
        reasons.append("NET_NOT_POSITIVE")
    if candidate_net <= repaired_net:
        reasons.append("NET_NOT_BETTER_THAN_CURRENT_REPAIR")
    if candidate_pf <= 1.0:
        reasons.append("PF_NOT_ABOVE_1")
    if repaired_pf > 0.0 and candidate_pf < repaired_pf:
        reasons.append("PF_BELOW_CURRENT_REPAIR")
    if repaired_payoff > 0.0 and candidate_payoff < repaired_payoff * 0.95:
        reasons.append("PAYOFF_DEGRADED_GT_5PCT")
    if positive_symbols < 3:
        reasons.append("POSITIVE_SYMBOLS_LT_3")
    if gate_blocks <= 0:
        reasons.append("NO_BEHAVIORAL_DELTA")
    return not reasons, reasons


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
    output_dir = root / OUTPUT_DIR
    total_bars = args.window_bars * 2
    end_ms = int(pd.Timestamp(args.fixed_end).timestamp() * 1000)
    end_ms = (end_ms // base.INTERVAL_MS) * base.INTERVAL_MS
    start_ms = end_ms - (total_bars - 1) * base.INTERVAL_MS

    if args.warmup_bars < 100 or args.warmup_bars >= args.window_bars:
        raise ValueError("WARMUP_CONTRACT_INVALID")
    if args.history_bars < 100:
        raise ValueError("HISTORY_CONTRACT_INVALID")
    if args.cost_bps_per_side < 0.0:
        raise ValueError("COST_CONTRACT_INVALID")

    registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    strategy_path = root / "backend/strategies/fvg_revert.py"
    protected_paths = [registry_path, strategy_path]
    before = {str(path): _sha256(path) for path in protected_paths}

    registry = base._load_registry(root)
    canonical = base._load_canonical_strategy(root, STRATEGY_ID, registry[STRATEGY_ID])
    repaired = load_repaired_strategy(root, STRATEGY_ID)
    gated = load_fvg_trend_aligned_strategy(root)

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
            fetch_results.append(
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "rows": len(frame),
                    "start": pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
                    "end": pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
                    "endpoint": endpoint,
                    "request_count": requests,
                }
            )
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    windows: list[dict[str, Any]] = []
    if not blockers:
        for window_index in range(2):
            start = window_index * args.window_bars
            end = start + args.window_bars
            canonical_runs: list[dict[str, Any]] = []
            repaired_runs: list[dict[str, Any]] = []
            gated_runs: list[dict[str, Any]] = []
            symbol_rows: list[dict[str, Any]] = []
            total_gate_blocks = 0

            for symbol in base.SYMBOLS:
                window = frames[symbol].iloc[start:end].reset_index(drop=True)
                canonical_replay = base._replay(
                    window,
                    canonical,
                    warmup_bars=args.warmup_bars,
                    history_bars=args.history_bars,
                    cost_bps_per_side=args.cost_bps_per_side,
                )
                repaired_replay = base._replay(
                    window,
                    repaired,
                    warmup_bars=args.warmup_bars,
                    history_bars=args.history_bars,
                    cost_bps_per_side=args.cost_bps_per_side,
                )
                tracked, counter = _tracked_gate(gated)
                gated_replay = base._replay(
                    window,
                    tracked,
                    warmup_bars=args.warmup_bars,
                    history_bars=args.history_bars,
                    cost_bps_per_side=args.cost_bps_per_side,
                )
                total_gate_blocks += int(counter["blocked_long_entry_count"])
                canonical_runs.append(canonical_replay)
                repaired_runs.append(repaired_replay)
                gated_runs.append(gated_replay)
                symbol_rows.append(
                    {
                        "symbol": symbol,
                        "canonical": canonical_replay["stats"],
                        "current_repair": repaired_replay["stats"],
                        "trend_aligned_child": gated_replay["stats"],
                        "gate_blocked_long_entry_count": counter["blocked_long_entry_count"],
                        "candidate_minus_current_repair_net_pct": (
                            _number(gated_replay["stats"].get("net_return_pct_sum"))
                            - _number(repaired_replay["stats"].get("net_return_pct_sum"))
                        ),
                    }
                )

            canonical_stats = base._aggregate(canonical_runs)
            repaired_stats = base._aggregate(repaired_runs)
            gated_stats = base._aggregate(gated_runs)
            positive_symbols = sum(
                _number(row["trend_aligned_child"].get("net_return_pct_sum")) > 0.0
                for row in symbol_rows
            )
            passed, reasons = _window_pass(gated_stats, repaired_stats, positive_symbols, total_gate_blocks)
            windows.append(
                {
                    "window_id": f"W{window_index + 1}",
                    "start": pd.Timestamp(frames[base.SYMBOLS[0]]["timestamp"].iloc[start]).isoformat(),
                    "end": pd.Timestamp(frames[base.SYMBOLS[0]]["timestamp"].iloc[end - 1]).isoformat(),
                    "canonical": canonical_stats,
                    "current_repair": repaired_stats,
                    "trend_aligned_child": gated_stats,
                    "positive_symbols": positive_symbols,
                    "gate_blocked_long_entry_count": total_gate_blocks,
                    "economic_pass": passed,
                    "failure_reasons": reasons,
                    "symbols": symbol_rows,
                }
            )

    after = {str(path): _sha256(path) for path in protected_paths}
    mutation_paths = [path for path in before if before[path] != after[path]]
    if mutation_paths:
        blockers.append("PROTECTED_MUTATION:" + ",".join(mutation_paths))

    survivor = bool(not blockers and len(windows) == 2 and all(window["economic_pass"] for window in windows))
    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_RESEARCH_NO_EXECUTION",
        "strategy_id": STRATEGY_ID,
        "policy_id": POLICY_ID,
        "state": "PASS" if not blockers else "HOLD",
        "two_window_economic_survivor": survivor,
        "fixed_end": pd.Timestamp(end_ms, unit="ms", tz="UTC").isoformat(),
        "interval": base.INTERVAL,
        "symbols": list(base.SYMBOLS),
        "window_bars": args.window_bars,
        "warmup_bars": args.warmup_bars,
        "evaluation_bars_per_window": args.window_bars - args.warmup_bars,
        "history_bars": args.history_bars,
        "cost_bps_per_side": args.cost_bps_per_side,
        "execution_model": {
            "completed_bar_only": True,
            "next_bar_open": True,
            "same_bar_sl_tp": "SL_FIRST_CONSERVATIVE",
            "runtime_side": "LONG_ONLY",
        },
        "child_manifest": dict(CHILD_MANIFEST),
        "fetch_results": fetch_results,
        "windows": windows,
        "blockers": blockers,
        "protected_mutation_paths": mutation_paths,
        "canonical_sources_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "next": (
            "THIRD_NONOVERLAP_WINDOW_FVG_TREND_ALIGNMENT"
            if survivor
            else "REJECT_TREND_ALIGNMENT_GATE_AND_TEST_NEXT_SINGLE_CAUSAL_FILTER"
        ),
    }
    _atomic_json(output_dir / "summary.json", report)
    print(
        json.dumps(
            {
                "STATE": report["state"],
                "BLOCKERS": len(blockers),
                "SURVIVOR": survivor,
                "WINDOWS": [
                    {
                        "id": window["window_id"],
                        "pass": window["economic_pass"],
                        "current_net": window["current_repair"]["net_return_pct_sum"],
                        "candidate_net": window["trend_aligned_child"]["net_return_pct_sum"],
                        "candidate_pf": window["trend_aligned_child"]["net_profit_factor"],
                        "positive_symbols": window["positive_symbols"],
                        "gate_blocks": window["gate_blocked_long_entry_count"],
                        "reasons": window["failure_reasons"],
                    }
                    for window in windows
                ],
                "NEXT": report["next"],
            },
            sort_keys=True,
        )
    )
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
