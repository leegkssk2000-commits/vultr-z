from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


def load_helper(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("sr_w1_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("HELPER_LOAD_SPEC")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.STRATEGY_ID = "sr_levels"
    return module


def metric(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def trace(strategy: Any, helper: Any, frames: Mapping[str, Any], symbols: tuple[str, ...]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    predicates: Counter[str] = Counter()
    calls = 0
    for symbol in symbols:
        frame = frames[symbol]
        for index in range(220, len(frame) - 1):
            history = frame.iloc[max(0, index - 219): index + 1].copy()
            result = helper.exact._call_strategy(
                strategy,
                history,
                {"position_side": "", "position_qty": 0.0, "avg_entry": 0.0, "add_count": 0, "last_add_price": 0.0},
            )
            calls += 1
            reasons[str(result.get("why") or result.get("reason") or "UNSPECIFIED")] += 1
            actions[str(result.get("action") or "hold").lower()] += 1
            indicators = result.get("indicators")
            if isinstance(indicators, Mapping):
                for name in ("long_break", "short_break", "reclaim_long", "reclaim_short"):
                    if indicators.get(name) is True:
                        predicates[name] += 1
    return {
        "call_count": calls,
        "reason_counts": dict(reasons.most_common()),
        "action_counts": dict(sorted(actions.items())),
        "enter_count": actions.get("enter", 0),
        "long_break_true_count": predicates["long_break"],
        "short_break_true_count": predicates["short_break"],
        "long_reclaim_true_count": predicates["reclaim_long"],
        "short_reclaim_true_count": predicates["reclaim_short"],
    }


def classify(control: Mapping[str, Any], candidate: Mapping[str, Any], stress: Mapping[str, Any], before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    c = control["metrics"]
    v = candidate["metrics"]
    s = stress["metrics"]
    blockers: list[str] = []
    minimum = 5
    if int(after.get("long_break_true_count") or 0) <= int(before.get("long_break_true_count") or 0):
        blockers.append("LONG_BREAK_NOT_RECOVERED")
    if int(after.get("short_break_true_count") or 0) <= int(before.get("short_break_true_count") or 0):
        blockers.append("SHORT_BREAK_NOT_RECOVERED")
    if int(v["trade_count"]) < minimum:
        blockers.append(f"CANDIDATE_TRADES_LT_{minimum}:{v['trade_count']}")
    if int(v["trade_count"]) <= int(c["trade_count"]):
        blockers.append(f"TRADES_NOT_RECOVERED:{v['trade_count']}<={c['trade_count']}")
    if metric(v["net_return_pct_sum"]) <= 0.0:
        blockers.append("CANDIDATE_NET_NOT_POSITIVE")
    if metric(v["net_profit_factor"]) <= 1.0:
        blockers.append("CANDIDATE_PF_NOT_GT_ONE")
    if metric(s["net_return_pct_sum"]) <= 0.0:
        blockers.append("STRESS_NET_NOT_POSITIVE")
    if metric(s["net_profit_factor"]) <= 1.0:
        blockers.append("STRESS_PF_NOT_GT_ONE")
    if metric(v["worst_net_loss_R"], -math.inf) < -0.90:
        blockers.append(f"NORMAL_WORST_R_LT_-0.90:{v['worst_net_loss_R']:.6f}")
    if metric(s["worst_net_loss_R"], -math.inf) < -0.95:
        blockers.append(f"STRESS_WORST_R_LT_-0.95:{s['worst_net_loss_R']:.6f}")
    if int(v["trade_count"]) < minimum:
        state = "HOLD_W1_LOW_SAMPLE"
    elif blockers:
        state = "REJECT_W1_SR_LEVELS_REPAIR"
    else:
        state = "PASS_W1_SR_LEVELS_REPAIR_CONFIRMATION"
    return state, blockers, {
        "trade_delta": int(v["trade_count"]) - int(c["trade_count"]),
        "net_delta_pct_points": metric(v["net_return_pct_sum"]) - metric(c["net_return_pct_sum"]),
        "profit_factor_delta": metric(v["net_profit_factor"]) - metric(c["net_profit_factor"]),
        "drawdown_delta_pct_points": metric(v["max_drawdown_pct"]) - metric(c["max_drawdown_pct"]),
        "minimum_fresh_trades": minimum,
        "normal_worst_R_min": -0.90,
        "stress_worst_R_min": -0.95,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compute-root", type=Path, required=True)
    parser.add_argument("--helper-root", type=Path, required=True)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--baseline-fresh-manifest", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-w1-end", default="2026-08-01T08:30:00Z")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    compute_root = args.compute_root.resolve()
    helper_root = args.helper_root.resolve()
    sys.path.insert(0, str(compute_root))
    helper = load_helper(helper_root / "backend/tools/r7a4d_strategy11_fvg_w1_repair_economics_v1.py")
    from backend.tools import r7a4d_strategy11_sr_levels_prior_range_repair_v1 as sr_repair

    native_status, manifest, manifest_path = helper.verify_native(args.native_root.resolve(), args.expected_w1_end)
    manifest_sha = helper.file_sha(manifest_path)
    non_overlap = helper.verify_non_overlap(args.baseline_fresh_manifest.resolve(), manifest)

    summary_path = sr_repair.prior.find_summary(args.evidence_root.resolve(), "sr_levels")
    baseline = helper.strict_json(summary_path)
    source_config = baseline["candidate"]
    gate = helper.exact._gate_from(source_config)
    exit_spec = helper.exact._exit_from(source_config)
    surgery = sr_repair.p.surgery_from(baseline.get("surgery"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    if not symbols:
        raise RuntimeError("SYMBOLS_MISSING")

    registry = helper.base._load_registry(compute_root)
    registry_row = registry["sr_levels"]
    canonical_sha = str(registry_row["canonical_engine"]["source_sha256"])
    control_strategy = helper.base._load_canonical_strategy(compute_root, "sr_levels", registry_row)
    candidate_strategy, repair_manifest = sr_repair.load_patched_strategy(compute_root, canonical_sha)
    patched_sha = str(repair_manifest["patched_source_sha"])

    frames, features, funding = helper.load_w1(args.native_root.resolve(), manifest)
    for symbol in symbols:
        if symbol not in frames:
            raise RuntimeError(f"W1_SYMBOL_MISSING:{symbol}")

    before = trace(control_strategy, helper, frames, symbols)
    after = trace(candidate_strategy, helper, frames, symbols)
    common = {
        "frames": frames,
        "features": features,
        "funding": funding,
        "symbols": symbols,
        "gate": gate,
        "exit_spec": exit_spec,
        "surgery": surgery,
        "manifest_sha": manifest_sha,
    }
    control_a = helper.replay_variant(control_strategy, variant_id="NO_CHANGE_CONTROL", strategy_source_sha=canonical_sha, cost_bps=4.0, entry_delay_bars=1, funding_mode="OBSERVED", **common)
    control_b = helper.replay_variant(control_strategy, variant_id="NO_CHANGE_CONTROL", strategy_source_sha=canonical_sha, cost_bps=4.0, entry_delay_bars=1, funding_mode="OBSERVED", **common)
    candidate_a = helper.replay_variant(candidate_strategy, variant_id="PRIOR_ONLY_SR_RANGE_REPAIR", strategy_source_sha=patched_sha, cost_bps=4.0, entry_delay_bars=1, funding_mode="OBSERVED", **common)
    candidate_b = helper.replay_variant(candidate_strategy, variant_id="PRIOR_ONLY_SR_RANGE_REPAIR", strategy_source_sha=patched_sha, cost_bps=4.0, entry_delay_bars=1, funding_mode="OBSERVED", **common)
    if helper.stable_sha(control_a) != helper.stable_sha(control_b):
        raise RuntimeError("CONTROL_AB_PARITY")
    if helper.stable_sha(candidate_a) != helper.stable_sha(candidate_b):
        raise RuntimeError("CANDIDATE_AB_PARITY")
    stress = helper.replay_variant(candidate_strategy, variant_id="PRIOR_ONLY_SR_RANGE_REPAIR__STRESS", strategy_source_sha=patched_sha, cost_bps=8.0, entry_delay_bars=2, funding_mode="ADVERSE_P95", **common)

    state, blockers, comparison = classify(control_a, candidate_a, stress, before, after)
    result = {
        "schema_version": "strategy11.sr_levels_w1_repair_economics.v1",
        "version": "R7A4D_STRATEGY11_SR_LEVELS_W1_REPAIR_ECONOMICS_V1",
        "state": state,
        "blockers": blockers,
        "next": "NEW_SEALED_SR_LEVELS_CONFIRMATION" if state == "PASS_W1_SR_LEVELS_REPAIR_CONFIRMATION" else "END_LEGACY25_SALVAGE_ROUTE_ALPHA_GEN2",
        "strategy_id": "sr_levels",
        "symbols": list(symbols),
        "source_w1_run_id": str(native_status.get("source_w1_run_id") or "30692822412"),
        "source_w1_manifest_sha256": manifest_sha,
        "source_w1_evaluation_start": manifest.get("evaluation_start"),
        "source_w1_evaluation_end": manifest.get("evaluation_end"),
        "baseline_summary_path": str(summary_path),
        "canonical_strategy_source_sha": canonical_sha,
        "candidate_strategy_source_sha": patched_sha,
        "repair": repair_manifest,
        "non_overlap": non_overlap,
        "before_trace": before,
        "after_trace": after,
        "a_b_parity": "PASS",
        "control": {k: v for k, v in control_a.items() if k != "trades"},
        "candidate": {k: v for k, v in candidate_a.items() if k != "trades"},
        "stress": {k: v for k, v in stress.items() if k != "trades"},
        "comparison": comparison,
        "normal_cost_bps_per_side": 4.0,
        "stress_cost_bps_per_side": 8.0,
        "normal_entry_delay_bars": 1,
        "stress_entry_delay_bars": 2,
        "normal_funding_mode": "OBSERVED",
        "stress_funding_mode": "ADVERSE_P95",
        "research_only": True,
        "promotion_authority": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_bound": False,
        "native_w1_chain_modified": False,
    }
    result["result_sha256"] = helper.stable_sha(result)
    out = args.out.resolve()
    helper.write_json(out / "status.json", result)
    helper.write_json(out / "control-trades.json", {"strategy_id": "sr_levels", "trades": control_a["trades"]})
    helper.write_json(out / "candidate-trades.json", {"strategy_id": "sr_levels", "trades": candidate_a["trades"]})
    helper.write_json(out / "stress-trades.json", {"strategy_id": "sr_levels", "trades": stress["trades"]})
    print(json.dumps({
        "state": state,
        "blockers": blockers,
        "before_trace": before,
        "after_trace": after,
        "control": control_a["metrics"],
        "candidate": candidate_a["metrics"],
        "stress": stress["metrics"],
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
