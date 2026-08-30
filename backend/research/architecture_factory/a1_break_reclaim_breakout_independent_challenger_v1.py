#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as econ
from backend.research.rebuild.a1_break_keltner_reclaim_latched_owner_v2 import latched_state_from_values

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_break_reclaim_breakout_independent_challenger_v1.json"
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
SEED_REPLAY = ROOT / "backend/research/rebuild/a1_top5_entry_transplant_replay_latest.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_break_reclaim_breakout_independent_challenger_latest.json"
SCHEMA = "zel.a1.break.reclaim_breakout_independent_challenger.receipt.v1"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def cutoff_ms(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def build_features(rows: list[dict[str, float]], spec: Mapping[str, Any]) -> tuple[dict[str, list[float | None]], econ.Expr]:
    features: dict[str, list[float | None]] = {}
    engine = econ.Expr(rows, features)
    for f in spec.get("features") or []:
        name = str(f.get("name") or "").strip()
        formula = econ._feature_formula(str(f.get("formula") or ""))
        if not name or not formula:
            raise RuntimeError("FEATURE_EMPTY")
        engine.validate(formula)
        arr: list[float | None] = []
        features[name] = arr
        for i in range(len(rows)):
            engine.i = i
            try:
                value = engine.eval(formula, i)
                arr.append(float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None)
            except (TypeError, ZeroDivisionError, ValueError):
                arr.append(None)
    return features, econ.Expr(rows, features)


def assert_seed_independent(contract: Mapping[str, Any]) -> dict[str, Any]:
    seed = read(SEED_REPLAY)
    experiment_id = str((contract.get("seed_lineage") or {}).get("seed_experiment_id") or "")
    cells = [x for x in seed.get("cells") or [] if isinstance(x, Mapping) and str(x.get("experiment_id")) == experiment_id]
    if len(cells) != 1:
        raise RuntimeError("SEED_EXPERIMENT_NOT_UNIQUE")
    cell = cells[0]
    keys = list(cell.get("accepted_trade_keys") or []) + list(cell.get("rejected_trade_keys") or [])
    if len(keys) != 9:
        raise RuntimeError(f"SEED_PARENT_T_DRIFT:{len(keys)}")
    seed_min_signal = min(int(x[1]) for x in keys)
    boundary = cutoff_ms(str(contract["development_policy"]["boundary_utc"]))
    if seed_min_signal < boundary:
        raise RuntimeError(f"DEVELOPMENT_OVERLAPS_SELECTED_SEED:{seed_min_signal}:{boundary}")
    return {
        "seed_experiment_id": experiment_id,
        "seed_parent_T": len(keys),
        "seed_min_signal_ts": seed_min_signal,
        "development_cutoff_ts": boundary,
        "strict_non_overlap": True,
    }


def validate_pre_result(contract: Mapping[str, Any], freeze: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != "zel.a1.break.reclaim_breakout_independent_challenger.contract.v1":
        raise RuntimeError("CONTRACT_SCHEMA_DRIFT")
    if contract.get("state") != "PREREGISTERED_INDEPENDENT_DEVELOPMENT_REPLAY_BEFORE_RESULT":
        raise RuntimeError("CONTRACT_NOT_PREREGISTERED")
    policy = contract.get("development_policy") or {}
    if policy.get("threshold_sweep") is not False or policy.get("state_rule_variant_sweep") is not False or policy.get("post_result_retune") is not False:
        raise RuntimeError("SWEEP_OR_RETUNE_FORBIDDEN")
    if int(policy.get("paid_ai_calls") or 0) != 0 or float(policy.get("fixed_cost_bps_per_trade") or 0.0) != 20.0:
        raise RuntimeError("COST_OR_PAID_AI_POLICY_DRIFT")
    arch = contract.get("architecture") or {}
    if arch.get("new_trade_population") is not True or int(arch.get("max_hold_bars") or 0) != 6:
        raise RuntimeError("ARCHITECTURE_POPULATION_OR_HORIZON_DRIFT")
    if str((arch.get("ownership_state") or {}).get("rule_hash_semantics")) != "EXACT_REUSE_OF_BREAK_KELTNER_RECLAIM_LATCHED_OWNER_V2_NO_PARAMETER_CHANGE":
        raise RuntimeError("OWNERSHIP_RULE_REUSE_DRIFT")
    children = [x for x in freeze.get("children") or [] if isinstance(x, Mapping) and x.get("lane_id") == "break_and_continue_main"]
    if len(children) != 1:
        raise RuntimeError("BREAK_V2_BASELINE_REQUIRED")
    current = children[0]["development_metrics_at_20bps"]
    locked = contract["break_v2_baseline"]
    for key in ("trades", "net_expectancy_bps", "net_pnl_bps", "profit_factor", "win_rate", "drawdown_bps"):
        if abs(float(current[key]) - float(locked[key])) > 1e-9:
            raise RuntimeError(f"BREAK_V2_BASELINE_DRIFT:{key}")
    if tuple(arch["symbol_universe"]) != tuple(freeze["frozen_symbol_universe"]):
        raise RuntimeError("SYMBOL_UNIVERSE_DRIFT")
    return assert_seed_independent(contract)


def run(output: Path) -> dict[str, Any]:
    contract = read(CONTRACT)
    freeze = read(V2_FREEZE)
    independence = validate_pre_result(contract, freeze)
    arch = contract["architecture"]
    boundary = str(contract["development_policy"]["boundary_utc"])
    old_boundary = econ.BOUNDARY
    try:
        econ.BOUNDARY = boundary
        all_trades: list[dict[str, Any]] = []
        source: dict[str, Any] = {}
        first_ts: int | None = None
        last_ts: int | None = None
        entry_rule = "close > lag('highest50',1) and ema20 > ema50 and vol_ratio(20) >= 1.1"
        for symbol in arch["symbol_universe"]:
            rows = econ.bars(str(symbol), "4h")
            source[str(symbol)] = {"bars": len(rows)}
            if len(rows) < 60:
                raise RuntimeError(f"INSUFFICIENT_HISTORY:{symbol}:{len(rows)}")
            if rows:
                first_ts = min(first_ts if first_ts is not None else int(rows[0]["ts"]), int(rows[0]["ts"]))
                last_ts = max(last_ts if last_ts is not None else int(rows[-1]["ts"]), int(rows[-1]["ts"]))
            features, engine = build_features(rows, arch)
            engine.validate(entry_rule)
            states = latched_state_from_values(
                [float(x["close"]) for x in rows],
                list(features["ema20"]),
                list(features["ema50"]),
            )
            i = 30
            fires = 0
            while i < len(rows) - 1:
                try:
                    fire = bool(states[i]) and bool(engine.eval(entry_rule, i))
                except (TypeError, ZeroDivisionError, ValueError):
                    fire = False
                if not fire:
                    i += 1
                    continue
                fires += 1
                entry_i = i + 1
                exit_i = min(entry_i + int(arch["max_hold_bars"]) - 1, len(rows) - 1)
                entry_px = float(rows[entry_i]["open"])
                exit_px = float(rows[exit_i]["close"])
                gross = (exit_px / entry_px - 1.0) * 10000.0
                net = gross - float(arch["cost_bps_per_trade"])
                all_trades.append({
                    "symbol": str(symbol),
                    "side": "long",
                    "signal_ts": int(rows[i]["ts"]),
                    "entry_ts": int(rows[entry_i]["ts"]),
                    "exit_ts": int(rows[exit_i]["ts"]),
                    "gross_bps": gross,
                    "net_bps": net,
                })
                i = max(i + 1, exit_i + 1)
            source[str(symbol)]["admitted_events"] = fires
            source[str(symbol)]["ownership_true_bars"] = sum(1 for x in states if x)
    finally:
        econ.BOUNDARY = old_boundary

    net = [float(x["net_bps"]) for x in all_trades]
    gross = [float(x["gross_bps"]) for x in all_trades]
    days = max(1e-9, ((last_ts or 0) - (first_ts or 0)) / 86_400_000.0)
    metrics = {
        "trades": len(net),
        "gross_expectancy_bps": sum(gross) / len(gross) if gross else None,
        "net_expectancy_bps": sum(net) / len(net) if net else None,
        "net_pnl_bps": sum(net),
        "profit_factor": econ._pf(net),
        "payoff": econ._payoff(net),
        "win_rate": sum(1 for x in net if x > 0) / len(net) if net else None,
        "drawdown_bps": econ._dd(net),
        "cost_bps_per_trade": float(arch["cost_bps_per_trade"]),
        "events_per_day": len(net) / days,
        "net_bps_per_calendar_day": sum(net) / days,
        "development_days": days,
    }
    p = contract["development_policy"]
    generic_checks = {
        "sample_minimum": len(net) >= int(p["minimum_closed_T"]),
        "net_expectancy_positive": metrics["net_expectancy_bps"] is not None and float(metrics["net_expectancy_bps"]) > float(p["minimum_net_expectancy_bps_exclusive"]),
        "profit_factor_positive": metrics["profit_factor"] is not None and float(metrics["profit_factor"]) > float(p["minimum_profit_factor_exclusive"]),
        "net_per_day_positive": float(metrics["net_bps_per_calendar_day"]) > float(p["minimum_net_bps_per_calendar_day_exclusive"]),
    }
    generic_pass = all(generic_checks.values())
    baseline = contract["break_v2_baseline"]
    improvements = {
        "net_expectancy_bps": metrics["net_expectancy_bps"] is not None and float(metrics["net_expectancy_bps"]) > float(baseline["net_expectancy_bps"]),
        "profit_factor": metrics["profit_factor"] is not None and float(metrics["profit_factor"]) > float(baseline["profit_factor"]),
        "drawdown_bps": float(metrics["drawdown_bps"]) < float(baseline["drawdown_bps"]),
    }
    quality_pass = any(improvements.values())
    final_pass = generic_pass and quality_pass
    delta = {
        "trades": int(metrics["trades"]) - int(baseline["trades"]),
        "net_expectancy_bps": None if metrics["net_expectancy_bps"] is None else float(metrics["net_expectancy_bps"]) - float(baseline["net_expectancy_bps"]),
        "net_pnl_bps": float(metrics["net_pnl_bps"]) - float(baseline["net_pnl_bps"]),
        "profit_factor": None if metrics["profit_factor"] is None else float(metrics["profit_factor"]) - float(baseline["profit_factor"]),
        "win_rate": None if metrics["win_rate"] is None else float(metrics["win_rate"]) - float(baseline["win_rate"]),
        "drawdown_bps": float(metrics["drawdown_bps"]) - float(baseline["drawdown_bps"]),
    }
    state = "PASS_DEVELOPMENT_ELIGIBLE_FOR_NEW_G4_CHALLENGER" if final_pass else "FALSIFIED_RECLAIM_BREAKOUT_GENERALIZATION_V1"
    trade_ids = [[x["symbol"], x["signal_ts"], x["entry_ts"], x["exit_ts"]] for x in all_trades]
    deterministic = {
        "contract_sha256": file_sha(CONTRACT),
        "v2_freeze_sha256": file_sha(V2_FREEZE),
        "seed_replay_sha256": file_sha(SEED_REPLAY),
        "independence": independence,
        "source": source,
        "metrics": metrics,
        "generic_checks": generic_checks,
        "improvements": improvements,
        "delta": delta,
        "trade_ids": trade_ids,
    }
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_master_sha": git_head(),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": file_sha(CONTRACT),
        "v2_freeze_path": str(V2_FREEZE.relative_to(ROOT)),
        "v2_freeze_sha256": file_sha(V2_FREEZE),
        "seed_replay_path": str(SEED_REPLAY.relative_to(ROOT)),
        "seed_replay_sha256": file_sha(SEED_REPLAY),
        "population_independence": independence,
        "challenger_id": arch["challenger_id"],
        "metrics": metrics,
        "generic_development_checks": generic_checks,
        "generic_development_pass": generic_pass,
        "baseline_quality_improvements": improvements,
        "baseline_quality_improvement_pass": quality_pass,
        "delta_vs_break_v2": delta,
        "source_summary": source,
        "trade_identity_sha256": stable(trade_ids),
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "historical_seed_credit_to_g4_T": 0,
        "development_credit_to_g4_T": 0,
        "fresh_g4_T": 0,
        "new_g4_activation_created": False,
        "new_g4_cohort_created": False,
        "next": "FREEZE_NEW_G4_CHALLENGER_WITH_FRESH_BOUNDARY" if final_pass else "STOP_RECLAIM_BREAKOUT_GENERALIZATION_WITHOUT_RULE_CHANGE",
        "deterministic_result_sha256": stable(deterministic),
        **AUTH,
    }
    receipt = dict(result)
    receipt.pop("observed_at_utc", None)
    receipt.pop("source_master_sha", None)
    result["receipt_sha256"] = stable(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = read(CONTRACT)
    assert c["development_policy"]["state_rule_variant_sweep"] is False
    assert c["development_policy"]["post_result_retune"] is False
    assert c["seed_lineage"]["exact_state_rule_source"] == "reclaim_v2"
    assert c["architecture"]["new_trade_population"] is True
    # Exact imported state behavior: transient pullback does not disarm while EMA20>EMA50.
    closes = [9.0, 9.5, 10.2, 9.8, 10.4]
    ema20 = [10.0, 10.0, 10.0, 10.1, 10.1]
    ema50 = [9.0] * 5
    assert latched_state_from_values(closes, ema20, ema50) == [False, False, True, True, True]
    print("PASS_A1_BREAK_RECLAIM_BREAKOUT_INDEPENDENT_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_reclaim_breakout_independent_challenger_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "metrics": r["metrics"],
        "generic_pass": r["generic_development_pass"],
        "quality_pass": r["baseline_quality_improvement_pass"],
        "improvements": r["baseline_quality_improvements"],
        "delta": r["delta_vs_break_v2"],
        "independence": r["population_independence"],
        "deterministic_result_sha256": r["deterministic_result_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
