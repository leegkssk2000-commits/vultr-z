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

from backend.strategy25.strategy_family_indicator_search_v2 import variants_for, wrap_strategy


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
OUTPUT_DIR = "artifacts/vol_spike_base_fresh_holdout_check_v1"
STRATEGY_ID = "vol_spike_fade"
WINDOW_BARS = 700
WARMUP_BARS = 180
HISTORY_BARS = 220
COST_BPS_PER_SIDE = 4.0


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load(BASE_PATH, "r7a4d_vol_spike_base_check_base_v1")


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


def _aggregate_window_stats(windows: list[Mapping[str, Any]]) -> dict[str, Any]:
    trade_count = sum(int(row["stats"].get("trade_count") or 0) for row in windows)
    win_count = sum(int(row["stats"].get("win_count") or 0) for row in windows)
    loss_count = sum(int(row["stats"].get("loss_count") or 0) for row in windows)
    net = sum(_number(row["stats"].get("net_return_pct_sum")) for row in windows)
    gross_gain = sum(_number(row["stats"].get("average_win_pct")) * int(row["stats"].get("win_count") or 0) for row in windows)
    gross_loss = sum(_number(row["stats"].get("average_loss_pct_abs")) * int(row["stats"].get("loss_count") or 0) for row in windows)
    average_win = gross_gain / win_count if win_count else None
    average_loss = gross_loss / loss_count if loss_count else None
    return {
        "trade_count": trade_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate_pct": win_count / trade_count * 100.0 if trade_count else None,
        "net_return_pct_sum": net,
        "net_profit_factor": gross_gain / gross_loss if gross_loss > 0.0 else (999.0 if gross_gain > 0.0 else None),
        "average_win_pct": average_win,
        "average_loss_pct_abs": average_loss,
        "payoff_ratio": average_win / average_loss if average_win is not None and average_loss not in (None, 0.0) else None,
        "max_drawdown_pct_conservative_sum": sum(_number(row["stats"].get("max_drawdown_pct")) for row in windows),
    }


def _window(frames: Mapping[str, pd.DataFrame], strategy, index: int, label: str) -> dict[str, Any]:
    start = index * WINDOW_BARS
    end = start + WINDOW_BARS
    replays = []
    symbols = []
    for symbol in base.SYMBOLS:
        replay = base._replay(
            frames[symbol].iloc[start:end].reset_index(drop=True),
            strategy,
            warmup_bars=WARMUP_BARS,
            history_bars=HISTORY_BARS,
            cost_bps_per_side=COST_BPS_PER_SIDE,
        )
        replays.append(replay)
        symbols.append({"symbol": symbol, "stats": replay["stats"], "signal_count": replay.get("signal_count")})
    stats = base._aggregate(replays)
    return {
        "window_id": label,
        "stats": stats,
        "positive_symbols": sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in symbols),
        "symbols": symbols,
    }


def _selection_contract(windows: list[Mapping[str, Any]], combined: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    validation = windows[-1]
    if int(combined.get("trade_count") or 0) < 25:
        reasons.append("SELECTION_TRADES_LT_25")
    if _number(combined.get("net_return_pct_sum")) <= 1.0:
        reasons.append("SELECTION_NET_LE_1PCT")
    if _number(combined.get("net_profit_factor")) <= 1.05:
        reasons.append("SELECTION_PF_LE_1_05")
    if _number(combined.get("payoff_ratio")) <= 1.5:
        reasons.append("SELECTION_PAYOFF_LE_1_5")
    if sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in windows) < 3:
        reasons.append("POSITIVE_WINDOWS_LT_3_OF_5")
    if int(validation["stats"].get("trade_count") or 0) < 4:
        reasons.append("VALIDATION_TRADES_LT_4")
    if _number(validation["stats"].get("net_return_pct_sum")) <= 0.0:
        reasons.append("VALIDATION_NET_NOT_POSITIVE")
    if _number(validation["stats"].get("net_profit_factor")) <= 1.0:
        reasons.append("VALIDATION_PF_NOT_ABOVE_1")
    return not reasons, reasons


def _fresh_contract(window: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons = []
    stats = window["stats"]
    if int(stats.get("trade_count") or 0) < 4:
        reasons.append("FRESH_HOLDOUT_TRADES_LT_4")
    if _number(stats.get("net_return_pct_sum")) <= 0.0:
        reasons.append("FRESH_HOLDOUT_NET_NOT_POSITIVE")
    if _number(stats.get("net_profit_factor")) <= 1.0:
        reasons.append("FRESH_HOLDOUT_PF_NOT_ABOVE_1")
    if int(window["positive_symbols"]) < 2:
        reasons.append("FRESH_HOLDOUT_POSITIVE_SYMBOLS_LT_2")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    prior_end_ms = int(pd.Timestamp(base.FIXED_END_ISO).timestamp() * 1000)
    prior_end_ms = (prior_end_ms // base.INTERVAL_MS) * base.INTERVAL_MS
    prior_start_ms = prior_end_ms - (int(base.WINDOW_BARS) * 2 - 1) * base.INTERVAL_MS
    prior_single_end_ms = prior_start_ms - base.INTERVAL_MS
    prior_single_start_ms = prior_single_end_ms - (1200 - 1) * base.INTERVAL_MS
    original_lab_end_ms = prior_single_start_ms - base.INTERVAL_MS
    original_lab_start_ms = original_lab_end_ms - (WINDOW_BARS * 5 - 1) * base.INTERVAL_MS
    fresh_end_ms = original_lab_start_ms - base.INTERVAL_MS
    fresh_start_ms = fresh_end_ms - (WINDOW_BARS - 1) * base.INTERVAL_MS
    expected_rows = WINDOW_BARS * 6

    blockers = []
    frames = {}
    fetch_results = []
    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, requests = base._fetch_exact(symbol, start_ms=fresh_start_ms, end_ms=original_lab_end_ms, expected_rows=expected_rows)
            frames[symbol] = frame
            fetch_results.append({"symbol": symbol, "status": "PASS", "rows": len(frame), "endpoint": endpoint, "request_count": requests})
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    registry = base._load_registry(root)
    canonical = base._load_canonical_strategy(root, STRATEGY_ID, registry[STRATEGY_ID])
    base_spec = next(spec for spec in variants_for(STRATEGY_ID) if spec.variant_id == "BASE")
    strategy = wrap_strategy(canonical, base_spec)

    labels = ["FRESH_HOLDOUT", "D1", "D2", "D3", "V1", "H1"]
    selection = []
    fresh = None
    if not blockers:
        selection = [_window(frames, strategy, index, labels[index]) for index in range(1, 6)]
        fresh = _window(frames, strategy, 0, labels[0])

    combined = _aggregate_window_stats(selection) if selection else None
    selection_pass, selection_reasons = _selection_contract(selection, combined) if selection else (False, ["NO_SELECTION"])
    fresh_pass, fresh_reasons = _fresh_contract(fresh) if fresh else (False, ["NO_FRESH_HOLDOUT"])
    accepted = bool(selection_pass and fresh_pass and not blockers)

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_BASELINE_CONFIRMATION_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "strategy_id": STRATEGY_ID,
        "variant_id": "BASE",
        "selection_windows": selection,
        "selection_combined": combined,
        "selection_pass": selection_pass,
        "selection_reasons": selection_reasons,
        "fresh_holdout": fresh,
        "fresh_holdout_pass": fresh_pass,
        "fresh_holdout_reasons": fresh_reasons,
        "meaningful_positive_accepted": accepted,
        "fetch_results": fetch_results,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "shadow_allowed": False,
        "next": "THIRD_OOS_CONFIRMATION" if accepted else "NEXT_STRATEGY_FAMILY_CANDIDATE",
    }
    _atomic_json(root / OUTPUT_DIR / "summary.json", report)
    print(json.dumps({
        "STATE": report["state"],
        "SELECTION": combined,
        "SELECTION_PASS": selection_pass,
        "SELECTION_REASONS": selection_reasons,
        "FRESH_HOLDOUT": None if fresh is None else fresh["stats"],
        "FRESH_POSITIVE_SYMBOLS": None if fresh is None else fresh["positive_symbols"],
        "FRESH_PASS": fresh_pass,
        "FRESH_REASONS": fresh_reasons,
        "ACCEPTED": accepted,
        "NEXT": report["next"],
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
