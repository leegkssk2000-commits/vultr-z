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
from backend.strategy25.strategy_family_indicator_search_v1 import FAMILY_MAP, variants_for, wrap_strategy
from backend.tools.r7a4d_strategy25_runtime_owner_contract_audit import EXPECTED_IDS


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
OUTPUT_ROOT = "artifacts/strategy_family_indicator_lab_v1"
FAMILIES = tuple(sorted(set(FAMILY_MAP.values())))


def _load_base_runner() -> Any:
    module_name = "r7a4d_strategy_family_indicator_lab_base_v1"
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


def _window_summary(runs: list[dict[str, Any]], symbols: list[dict[str, Any]]) -> dict[str, Any]:
    stats = base._aggregate(runs)
    positive_symbols = sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in symbols)
    return {"stats": stats, "positive_symbols": positive_symbols, "symbols": symbols}


def _dev_score(windows: list[dict[str, Any]]) -> float:
    trades = sum(int(row["stats"].get("trade_count") or 0) for row in windows)
    net = sum(_number(row["stats"].get("net_return_pct_sum"), -1000.0) for row in windows)
    pf_values = [_number(row["stats"].get("net_profit_factor"), 0.0) for row in windows]
    payoff_values = [_number(row["stats"].get("payoff_ratio"), 0.0) for row in windows]
    minimum_net = min(_number(row["stats"].get("net_return_pct_sum"), -1000.0) for row in windows)
    positive_window_count = sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in windows)
    positive_symbol_sum = sum(int(row["positive_symbols"]) for row in windows)
    if trades <= 0:
        return -1e9
    return (
        net * 6.0
        + minimum_net * 4.0
        + (min(pf_values) - 1.0) * 8.0
        + (sum(pf_values) / len(pf_values) - 1.0) * 5.0
        + (sum(payoff_values) / len(payoff_values) - 1.0) * 1.5
        + positive_window_count * 3.0
        + positive_symbol_sum * 0.5
        + math.log1p(trades)
    )


def _development_contract(windows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    trades = sum(int(row["stats"].get("trade_count") or 0) for row in windows)
    net = sum(_number(row["stats"].get("net_return_pct_sum")) for row in windows)
    positive_windows = sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in windows)
    minimum_pf = min(_number(row["stats"].get("net_profit_factor"), 0.0) for row in windows)
    if trades < 18:
        reasons.append("DEV_TRADES_LT_18")
    if net <= 0.0:
        reasons.append("DEV_NET_NOT_POSITIVE")
    if positive_windows < 2:
        reasons.append("DEV_POSITIVE_WINDOWS_LT_2")
    if minimum_pf < 0.80:
        reasons.append("DEV_MIN_PF_LT_0_80")
    return not reasons, reasons


def _validation_contract(dev_windows: list[dict[str, Any]], validation: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    dev_ok, dev_reasons = _development_contract(dev_windows)
    if not dev_ok:
        reasons.extend(dev_reasons)
    stats = validation["stats"]
    if int(stats.get("trade_count") or 0) < 4:
        reasons.append("VALIDATION_TRADES_LT_4")
    if _number(stats.get("net_return_pct_sum")) <= 0.0:
        reasons.append("VALIDATION_NET_NOT_POSITIVE")
    if _number(stats.get("net_profit_factor"), 0.0) <= 1.0:
        reasons.append("VALIDATION_PF_NOT_ABOVE_1")
    if int(validation["positive_symbols"]) < 2:
        reasons.append("VALIDATION_POSITIVE_SYMBOLS_LT_2")
    return not reasons, reasons


def _effective_strategy(root: Path, registry: Mapping[str, Any], strategy_id: str):
    canonical = base._load_canonical_strategy(root, strategy_id, registry[strategy_id])
    return load_repaired_strategy(root, strategy_id) if strategy_id in REPAIR_SPECS else canonical


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--family", choices=FAMILIES, required=True)
    parser.add_argument("--window-bars", type=int, default=700)
    parser.add_argument("--warmup-bars", type=int, default=180)
    parser.add_argument("--history-bars", type=int, default=220)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--development-windows", type=int, default=3)
    parser.add_argument("--validation-windows", type=int, default=1)
    parser.add_argument("--holdout-windows", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = root / OUTPUT_ROOT / args.family
    total_windows = args.development_windows + args.validation_windows + args.holdout_windows
    total_bars = args.window_bars * total_windows
    if args.warmup_bars < 100 or args.warmup_bars >= args.window_bars:
        raise ValueError("WARMUP_CONTRACT_INVALID")

    prior_census_end_ms = int(pd.Timestamp(base.FIXED_END_ISO).timestamp() * 1000)
    prior_census_end_ms = (prior_census_end_ms // base.INTERVAL_MS) * base.INTERVAL_MS
    prior_two_window_bars = int(base.WINDOW_BARS) * 2
    prior_two_window_start_ms = prior_census_end_ms - (prior_two_window_bars - 1) * base.INTERVAL_MS
    prior_single_census_end_ms = prior_two_window_start_ms - base.INTERVAL_MS
    prior_single_census_start_ms = prior_single_census_end_ms - (1200 - 1) * base.INTERVAL_MS
    lab_end_ms = prior_single_census_start_ms - base.INTERVAL_MS
    lab_start_ms = lab_end_ms - (total_bars - 1) * base.INTERVAL_MS

    registry = base._load_registry(root)
    strategies = [strategy_id for strategy_id in EXPECTED_IDS if FAMILY_MAP[strategy_id] == args.family]
    blockers: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    fetch_results: list[dict[str, Any]] = []
    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, request_count = base._fetch_exact(
                symbol,
                start_ms=lab_start_ms,
                end_ms=lab_end_ms,
                expected_rows=total_bars,
            )
            frames[symbol] = frame
            fetch_results.append({
                "symbol": symbol,
                "status": "PASS",
                "rows": len(frame),
                "start": pd.Timestamp(frame["timestamp"].iloc[0]).isoformat(),
                "end": pd.Timestamp(frame["timestamp"].iloc[-1]).isoformat(),
                "endpoint": endpoint,
                "request_count": request_count,
            })
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    development_rows: list[dict[str, Any]] = []
    finalists: list[dict[str, Any]] = []
    if not blockers:
        for strategy_id in strategies:
            try:
                effective = _effective_strategy(root, registry, strategy_id)
                for variant in variants_for(strategy_id):
                    wrapped = wrap_strategy(effective, variant)
                    dev_windows: list[dict[str, Any]] = []
                    for window_index in range(args.development_windows):
                        start = window_index * args.window_bars
                        end = start + args.window_bars
                        runs: list[dict[str, Any]] = []
                        symbols: list[dict[str, Any]] = []
                        for symbol in base.SYMBOLS:
                            replay = base._replay(
                                frames[symbol].iloc[start:end].reset_index(drop=True),
                                wrapped,
                                warmup_bars=args.warmup_bars,
                                history_bars=args.history_bars,
                                cost_bps_per_side=args.cost_bps_per_side,
                            )
                            runs.append(replay)
                            symbols.append({"symbol": symbol, "stats": replay["stats"], "signal_count": replay.get("signal_count")})
                        dev_windows.append({"window_id": f"D{window_index + 1}", **_window_summary(runs, symbols)})
                    eligible, reasons = _development_contract(dev_windows)
                    development_rows.append({
                        "family": args.family,
                        "strategy_id": strategy_id,
                        "variant_id": variant.variant_id,
                        "variant_description": variant.description,
                        "development_windows": dev_windows,
                        "development_eligible": eligible,
                        "development_reasons": reasons,
                        "development_score": _dev_score(dev_windows),
                    })
            except Exception as exc:
                blockers.append(f"{strategy_id}:{type(exc).__name__}:{exc}")

        ranked = sorted(development_rows, key=lambda row: float(row["development_score"]), reverse=True)
        for candidate in ranked[: args.top_k]:
            strategy_id = str(candidate["strategy_id"])
            effective = _effective_strategy(root, registry, strategy_id)
            spec = next(spec for spec in variants_for(strategy_id) if spec.variant_id == candidate["variant_id"])
            wrapped = wrap_strategy(effective, spec)
            out_windows: list[dict[str, Any]] = []
            first_out_index = args.development_windows
            for offset in range(args.validation_windows + args.holdout_windows):
                window_index = first_out_index + offset
                start = window_index * args.window_bars
                end = start + args.window_bars
                runs: list[dict[str, Any]] = []
                symbols: list[dict[str, Any]] = []
                for symbol in base.SYMBOLS:
                    replay = base._replay(
                        frames[symbol].iloc[start:end].reset_index(drop=True),
                        wrapped,
                        warmup_bars=args.warmup_bars,
                        history_bars=args.history_bars,
                        cost_bps_per_side=args.cost_bps_per_side,
                    )
                    runs.append(replay)
                    symbols.append({"symbol": symbol, "stats": replay["stats"], "signal_count": replay.get("signal_count")})
                label = "V1" if offset < args.validation_windows else f"H{offset - args.validation_windows + 1}"
                out_windows.append({"window_id": label, **_window_summary(runs, symbols)})
            validation = out_windows[0]
            valid, reasons = _validation_contract(candidate["development_windows"], validation)
            finalists.append({**candidate, "validation_windows": out_windows[: args.validation_windows], "holdout_windows": out_windows[args.validation_windows :], "validation_eligible": valid, "validation_reasons": reasons})

    finalists = sorted(
        finalists,
        key=lambda row: (
            bool(row.get("validation_eligible")),
            _number(row.get("validation_windows", [{}])[0].get("stats", {}).get("net_return_pct_sum"), -1000.0),
            float(row.get("development_score", -1e9)),
        ),
        reverse=True,
    )
    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_FAMILY_INDICATOR_SEARCH_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "family": args.family,
        "strategy_ids": strategies,
        "interval": base.INTERVAL,
        "symbols": list(base.SYMBOLS),
        "window_contract": {
            "lab_start": pd.Timestamp(lab_start_ms, unit="ms", tz="UTC").isoformat(),
            "lab_end": pd.Timestamp(lab_end_ms, unit="ms", tz="UTC").isoformat(),
            "window_bars": args.window_bars,
            "warmup_bars": args.warmup_bars,
            "development_windows": args.development_windows,
            "validation_windows": args.validation_windows,
            "holdout_windows": args.holdout_windows,
            "nonoverlap_with_previous_census": lab_end_ms < prior_single_census_start_ms,
        },
        "cost_bps_per_side": args.cost_bps_per_side,
        "fetch_results": fetch_results,
        "development_results": development_rows,
        "finalists": finalists,
        "family_selected": finalists[0] if finalists else None,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "next": "AGGREGATE_FAMILY_WINNERS_AND_RUN_ONE_CAUSAL_SURGERY" if finalists and not blockers else "HOLD_NO_FAMILY_RESULT",
    }
    _atomic_json(output_dir / "summary.json", report)
    selected = report["family_selected"]
    print(json.dumps({
        "STATE": report["state"],
        "FAMILY": args.family,
        "BLOCKERS": len(blockers),
        "SELECTED": None if selected is None else {"strategy_id": selected["strategy_id"], "variant_id": selected["variant_id"], "dev_score": selected["development_score"], "validation_eligible": selected["validation_eligible"], "validation_stats": selected["validation_windows"][0]["stats"], "holdout_stats": selected["holdout_windows"][0]["stats"] if selected["holdout_windows"] else None},
        "NEXT": report["next"],
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
