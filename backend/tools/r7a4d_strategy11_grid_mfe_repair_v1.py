from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from backend.strategy25.strategy11_feature_library_v1 import GateSpec
from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair

STRATEGY_ID = "grid_rebalance"
SOURCE_VARIANT_ID = "SF__REJECTION_LONG"
VERSION = "R7A4D_STRATEGY11_GRID_MFE_REPAIR_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def find_source_variant(root: Path) -> Path:
    matches: list[Path] = []
    for path in sorted(root.rglob(f"{STRATEGY_ID}/{SOURCE_VARIANT_ID}/summary.json")):
        try:
            payload = strict_json(path)
        except Exception:
            continue
        config = payload.get("candidate_config") or {}
        if config.get("strategy_id") == STRATEGY_ID and config.get("candidate_id") == SOURCE_VARIANT_ID:
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError(f"SOURCE_VARIANT_MATCH:{len(matches)}")
    return matches[0]


def path_shape(trades: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [row for row in trades if metric(row.get("net_return_pct")) < 0.0]
    mfe_over_1 = [row for row in losses if metric(row.get("mfe_r")) >= 1.0]
    mfe_over_15 = [row for row in losses if metric(row.get("mfe_r")) >= 1.5]
    return {
        "trade_count": len(trades),
        "loss_count": len(losses),
        "losses_mfe_ge_1r": len(mfe_over_1),
        "losses_mfe_ge_1_5r": len(mfe_over_15),
        "loss_mfe_r": sorted(metric(row.get("mfe_r")) for row in losses),
        "loss_bars_held": sorted(int(row.get("bars_held") or 0) for row in losses),
        "source_trade_ledger_sha": stable_sha(trades),
    }


def compare(candidate: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    candidate_loss = candidate.get("loss_metrics") or {}
    control_loss = control.get("loss_metrics") or {}
    candidate_stress = (candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}
    checks = {
        "trade_retention_ge_80pct": int(candidate.get("trade_count") or 0) >= math.ceil(int(control.get("trade_count") or 0) * 0.80),
        "net_improved": metric(candidate.get("net_return_pct_sum")) > metric(control.get("net_return_pct_sum")),
        "pf_improved": metric(candidate.get("net_profit_factor")) > metric(control.get("net_profit_factor")),
        "payoff_nonworse": metric(candidate.get("payoff_ratio")) >= metric(control.get("payoff_ratio")) * 0.95,
        "dd_nonworse": metric(candidate.get("max_drawdown_pct")) <= metric(control.get("max_drawdown_pct")),
        "avg_loss_nonworse": metric(candidate_loss.get("avg_loss_R"), -math.inf) >= metric(control_loss.get("avg_loss_R"), -math.inf),
        "worst_loss_l090": metric(candidate_loss.get("normal_worst_net_loss_R"), -math.inf) >= -0.90,
        "stress_worst_l095": metric(candidate_stress.get("normal_worst_net_loss_R"), -math.inf) >= -0.95,
        "positive_windows_nonworse": metric(candidate.get("positive_fresh_windows_pct")) >= metric(control.get("positive_fresh_windows_pct")),
        "parity_pass": candidate.get("parity", {}).get("state") == "PASS",
        "duplicate_zero": int(candidate.get("parity", {}).get("duplicate_trade_count") or 0) == 0,
    }
    deltas = {
        "trade_count": int(candidate.get("trade_count") or 0) - int(control.get("trade_count") or 0),
        "net_pct_points": metric(candidate.get("net_return_pct_sum")) - metric(control.get("net_return_pct_sum")),
        "profit_factor": metric(candidate.get("net_profit_factor")) - metric(control.get("net_profit_factor")),
        "payoff": metric(candidate.get("payoff_ratio")) - metric(control.get("payoff_ratio")),
        "drawdown_pct_points": metric(candidate.get("max_drawdown_pct")) - metric(control.get("max_drawdown_pct")),
        "avg_loss_r": metric(candidate_loss.get("avg_loss_R"), -math.inf) - metric(control_loss.get("avg_loss_R"), -math.inf),
    }
    return {
        "state": "PASS_DIAGNOSTIC_PARETO" if all(checks.values()) else "NO_DIAGNOSTIC_PARETO",
        "checks": checks,
        "deltas": deltas,
        "ai_review_state": "WAIT_GROQ_QUOTA",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source_path = find_source_variant(args.replay_root.resolve())
    source_summary = strict_json(source_path)
    source_config = source_summary["candidate_config"]
    gate = GateSpec(**dict(source_config["gate"]))
    if tuple(gate.required) != ("rejection_long",):
        raise RuntimeError("SOURCE_GATE_NOT_REJECTION_LONG")
    source_exit = exact._exit_from({"exit": source_config["exit"]})
    surgery = p.surgery_from(source_config.get("surgery"))
    symbols = tuple(str(value) for value in source_config["symbols"])
    candidate_exit = replace(
        source_exit,
        exit_id=f"{source_exit.exit_id}_TRAIL100_ATR075",
        trail_activate_r=1.0,
        trail_atr_mult=0.75,
    )

    frames, features, funding, manifest = p.load_fresh_data(args.fresh_root.resolve())
    quantiles = p.funding_rate_quantiles(funding)
    market_shas = repair.market_sha_map(manifest)
    registry = base._load_registry(args.root.resolve())
    strategy_source_sha = str(registry[STRATEGY_ID]["canonical_engine"]["source_sha256"])
    strategy = base._load_canonical_strategy(args.root.resolve(), STRATEGY_ID, registry[STRATEGY_ID])
    policy = strict_json(args.policy.resolve())
    normal_cap = float(policy["loss_ladder"][0]["normal_worst_net_loss_R_min"])
    stress_cap = float(policy["loss_ladder"][0]["stress_worst_net_loss_R_min"])

    common = {
        "strategy": strategy,
        "gate": gate,
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
        "normal_cap_r": normal_cap,
        "stress_cap_r": stress_cap,
        "out": args.out.resolve() / STRATEGY_ID,
    }
    control_config = dict(source_config)
    control = replay.evaluate(
        variant_id="CONTROL_REJECTION_RR150",
        config={**control_config, "candidate_id": "CONTROL_REJECTION_RR150", "axis": "CONTROL"},
        exit_spec=source_exit,
        **common,
    )
    candidate_config = {
        **source_config,
        "candidate_id": "TRAIL100_ATR075",
        "axis": "MFE_TRAILING",
        "exit": candidate_exit.__dict__,
    }
    candidate = replay.evaluate(
        variant_id="TRAIL100_ATR075",
        config=candidate_config,
        exit_spec=candidate_exit,
        **common,
    )
    source_trades = strict_json(source_path.parent / "replay-A.json")["trades"]
    comparison = compare(candidate, control)
    result = {
        "schema_version": "strategy11.grid_mfe_repair.v1",
        "version": VERSION,
        "state": "PASS_GRID_MFE_DIAGNOSTIC_COMPLETE",
        "strategy_id": STRATEGY_ID,
        "source_variant_id": SOURCE_VARIANT_ID,
        "source_summary_sha": stable_sha(source_summary),
        "source_path_shape": path_shape(source_trades),
        "control": {
            "trade_count": control.get("trade_count"),
            "win_rate_pct": control.get("win_rate_pct"),
            "net_pct": control.get("net_return_pct_sum"),
            "profit_factor": control.get("net_profit_factor"),
            "payoff": control.get("payoff_ratio"),
            "max_drawdown_pct": control.get("max_drawdown_pct"),
            "avg_loss_r": (control.get("loss_metrics") or {}).get("avg_loss_R"),
            "summary_sha": stable_sha(control),
        },
        "candidate": {
            "candidate_id": "TRAIL100_ATR075",
            "axis": "MFE_TRAILING",
            "trade_count": candidate.get("trade_count"),
            "win_rate_pct": candidate.get("win_rate_pct"),
            "net_pct": candidate.get("net_return_pct_sum"),
            "profit_factor": candidate.get("net_profit_factor"),
            "payoff": candidate.get("payoff_ratio"),
            "max_drawdown_pct": candidate.get("max_drawdown_pct"),
            "avg_loss_r": (candidate.get("loss_metrics") or {}).get("avg_loss_R"),
            "worst_loss_r": (candidate.get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "stress_worst_loss_r": ((candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
            "comparison": comparison,
            "summary_sha": stable_sha(candidate),
        },
        "next": "GROQ_AND_WORKERS_AI_REVIEW_THEN_L090" if comparison["state"] == "PASS_DIAGNOSTIC_PARETO" else "REJECT_AXIS_AND_KEEP_RESEARCH_CONTROL",
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        **SAFETY,
    }
    result["diagnostic_sha"] = stable_sha(result)
    atomic_json(args.out.resolve() / "final.json", result)
    print(result["state"], comparison["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
