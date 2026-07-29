from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay
from backend.tools import r7a4d_strategy11_supertrend_seed_repair_v1 as seed

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair
prior = replay.prior

STRATEGY_ID = "trend_rider"
VERSION = "R7A4D_STRATEGY11_TREND_RIDER_HTF_ALIGNMENT_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def metric(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def compare(candidate: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    c_loss = candidate.get("loss_metrics") or {}
    c_stress = (candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}
    control_trades = int(control.get("trade_count") or 0)
    candidate_trades = int(candidate.get("trade_count") or 0)
    retention = candidate_trades / max(1, control_trades) * 100.0
    payoff_delta = metric(candidate.get("payoff_ratio")) - metric(control.get("payoff_ratio"))
    checks = {
        "minimum_trades": candidate_trades >= 5,
        "retention_ge_80": retention >= 80.0,
        "net_improves": metric(candidate.get("net_return_pct_sum")) > metric(control.get("net_return_pct_sum")),
        "pf_improves": metric(candidate.get("net_profit_factor")) > metric(control.get("net_profit_factor")),
        "payoff_not_materially_worse": payoff_delta >= -0.15,
        "dd_nonworse": metric(candidate.get("max_drawdown_pct"), math.inf) <= metric(control.get("max_drawdown_pct"), math.inf),
        "avg_loss_nonworse": metric(c_loss.get("avg_loss_R"), -math.inf) >= metric((control.get("loss_metrics") or {}).get("avg_loss_R"), -math.inf),
        "positive_windows_nonworse": metric(candidate.get("positive_fresh_windows_pct")) >= metric(control.get("positive_fresh_windows_pct")),
        "worst_loss_l090": metric(c_loss.get("normal_worst_net_loss_R"), -math.inf) >= -0.90,
        "stress_worst_l095": metric(c_stress.get("normal_worst_net_loss_R"), -math.inf) >= -0.95,
        "parity_pass": candidate.get("parity", {}).get("state") == "PASS",
        "duplicate_zero": int(candidate.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
    }
    return {
        "state": "PASS_DIAGNOSTIC_PARETO" if all(checks.values()) else "NO_DIAGNOSTIC_PARETO",
        "checks": checks,
        "retention_pct": retention,
        "trade_delta": candidate_trades - control_trades,
        "net_delta_pct_points": metric(candidate.get("net_return_pct_sum")) - metric(control.get("net_return_pct_sum")),
        "pf_delta": metric(candidate.get("net_profit_factor")) - metric(control.get("net_profit_factor")),
        "payoff_delta": payoff_delta,
        "dd_delta_pct_points": metric(candidate.get("max_drawdown_pct")) - metric(control.get("max_drawdown_pct")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--fresh-root", type=Path, required=True)
    ap.add_argument("--evidence-root", type=Path, required=True)
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--source-run-id", required=True)
    ap.add_argument("--source-head-sha", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    baseline = json.loads(prior.find_summary(args.evidence_root.resolve(), STRATEGY_ID).read_text())
    source_config = dict(baseline["candidate"])
    base_gate = exact._gate_from(source_config)
    if base_gate.required or base_gate.forbidden:
        raise RuntimeError("EXPECTED_EMPTY_BASE_GATE")
    exit_spec = exact._exit_from(source_config)
    surgery = p.surgery_from(baseline.get("surgery"))
    symbols = tuple(str(x) for x in baseline.get("symbols", []))
    frames, features, funding, manifest = p.load_fresh_data(args.fresh_root.resolve())
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = repair.market_sha_map(manifest)
    registry = base._load_registry(args.root.resolve())
    strategy_source_sha = str(registry[STRATEGY_ID]["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(args.root.resolve(), STRATEGY_ID, registry[STRATEGY_ID])
    original_supertrend = strategy.__globals__.get("_supertrend")
    if not callable(original_supertrend):
        raise RuntimeError("SUPERTREND_GLOBAL_NOT_CALLABLE")
    strategy.__globals__["_supertrend"] = seed.corrected_supertrend

    policy = json.loads(args.policy.read_text())
    common = {
        "strategy": strategy,
        "surgery": surgery,
        "symbols": symbols,
        "frames": frames,
        "features": features,
        "funding": funding,
        "quantiles": quantiles,
        "manifest": manifest,
        "market_shas": market_shas,
        "strategy_source_sha": strategy_source_sha,
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "normal_cap_r": float(policy["loss_ladder"][0]["normal_worst_net_loss_R_min"]),
        "stress_cap_r": float(policy["loss_ladder"][0]["stress_worst_net_loss_R_min"]),
        "out": args.out.resolve() / STRATEGY_ID,
        "exit_spec": exit_spec,
    }

    control_config = {**source_config, "candidate_id": "CONTROL_REPAIRED_SEED", "axis": "CONTROL"}
    control = replay.evaluate(variant_id="CONTROL_REPAIRED_SEED", config=control_config, gate=base_gate, **common)

    candidate_config = {
        **source_config,
        "candidate_id": "HTF_UP_ALIGNMENT",
        "axis": "TREND_REGIME_GATE",
        "kind": "GATE",
        "gate": {
            "gate_id": "HTF_UP_ALIGNMENT",
            "family": "trend",
            "description": "Require portable higher-timeframe up alignment; no window or symbol exclusion.",
            "required": ["htf_trend_up"],
            "forbidden": [],
        },
    }
    candidate_gate = exact._gate_from(candidate_config)
    if tuple(candidate_gate.required) != ("htf_trend_up",) or candidate_gate.forbidden:
        raise RuntimeError("HTF_GATE_SHAPE_MISMATCH")
    candidate = replay.evaluate(variant_id="HTF_UP_ALIGNMENT", config=candidate_config, gate=candidate_gate, **common)
    relation = compare(candidate, control)

    result = {
        "schema_version": "strategy11.trend_rider_htf_alignment.v1",
        "version": VERSION,
        "state": "PASS_TREND_RIDER_HTF_ALIGNMENT_DIAGNOSTIC_COMPLETE",
        "strategy_id": STRATEGY_ID,
        "single_axis": "TREND_REGIME_GATE_HTF_ALIGNMENT",
        "control": {
            "trade_count": control.get("trade_count"),
            "win_rate_pct": control.get("win_rate_pct"),
            "net_pct": control.get("net_return_pct_sum"),
            "profit_factor": control.get("net_profit_factor"),
            "payoff": control.get("payoff_ratio"),
            "max_drawdown_pct": control.get("max_drawdown_pct"),
            "positive_windows_pct": control.get("positive_fresh_windows_pct"),
            "summary_sha": stable_sha(control),
        },
        "candidate": {
            "trade_count": candidate.get("trade_count"),
            "win_rate_pct": candidate.get("win_rate_pct"),
            "net_pct": candidate.get("net_return_pct_sum"),
            "profit_factor": candidate.get("net_profit_factor"),
            "payoff": candidate.get("payoff_ratio"),
            "max_drawdown_pct": candidate.get("max_drawdown_pct"),
            "avg_loss_r": (candidate.get("loss_metrics") or {}).get("avg_loss_R"),
            "worst_loss_r": (candidate.get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "stress_worst_loss_r": ((candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "positive_windows_pct": candidate.get("positive_fresh_windows_pct"),
            "relation": relation,
            "summary_sha": stable_sha(candidate),
        },
        "window_exclusion_used": False,
        "symbol_exclusion_used": False,
        "threshold_sweep_used": False,
        "same_axis_generation": 1,
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        "canonical_source_modified": False,
        "registry_modified": False,
        **SAFETY,
    }
    result["diagnostic_sha"] = stable_sha(result)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "final.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": result["state"], "relation": relation["state"], "control_trades": control.get("trade_count"), "candidate_trades": candidate.get("trade_count")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
