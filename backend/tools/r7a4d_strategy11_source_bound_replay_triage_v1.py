from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha, validate_source

VERSION = "R7A4D_STRATEGY11_SOURCE_BOUND_REPLAY_TRIAGE_V1"


def _num(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _candidate_relation(candidate: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
    candidate_loss = candidate.get("loss_metrics") or {}
    control_loss = control.get("loss_metrics") or {}
    checks = {
        "trades_nonzero": int(candidate.get("trade_count") or 0) > 0,
        "net_nonworse": _num(candidate.get("net_return_pct_sum")) >= _num(control.get("net_return_pct_sum")),
        "pf_nonworse": _num(candidate.get("net_profit_factor")) >= _num(control.get("net_profit_factor")),
        "payoff_nonworse": _num(candidate.get("payoff_ratio")) >= _num(control.get("payoff_ratio")),
        "dd_nonworse": _num(candidate.get("max_drawdown_pct")) <= _num(control.get("max_drawdown_pct")),
        "avg_loss_nonworse": _num(candidate_loss.get("avg_loss_R"), -999.0) >= _num(control_loss.get("avg_loss_R"), -999.0),
        "worst_loss_nonworse": _num(candidate_loss.get("normal_worst_net_loss_R"), -999.0) >= _num(control_loss.get("normal_worst_net_loss_R"), -999.0),
        "positive_windows_nonworse": _num(candidate.get("positive_fresh_windows_pct")) >= _num(control.get("positive_fresh_windows_pct")),
    }
    improved = sorted(key for key, passed in checks.items() if passed)
    degraded = sorted(key for key, passed in checks.items() if not passed)
    ladder = candidate.get("ladder_check") or {}
    if ladder.get("research_pass") is True:
        state = "PASS_L090_RESEARCH_CANDIDATE"
        next_axis = "L085"
    elif int(candidate.get("trade_count") or 0) == 0:
        state = "REJECT_ZERO_TRADES_AXIS"
        next_axis = "NEXT_DISTINCT_CAUSAL_AXIS"
    elif ladder.get("average_loss_nonworse") is False and _num(candidate.get("net_return_pct_sum")) > 0 and _num(candidate.get("net_profit_factor")) > 1:
        state = "NEAR_PASS_LOSS_SHAPE"
        next_axis = "BREAKEVEN_OR_MFE_TRAILING_OR_TIME_STOP"
    elif _num(candidate.get("positive_fresh_windows_pct")) < 70.0:
        state = "LOW_WINDOW_BREADTH"
        next_axis = "WAIT_NEW_NONOVERLAP_OR_REGIME_AXIS"
    elif _num(ladder.get("trade_retention_pct")) < 80.0:
        state = "RETENTION_HARD_GATE"
        next_axis = "NEXT_DISTINCT_CAUSAL_AXIS"
    else:
        state = "NO_PARETO_DOMINANCE"
        next_axis = "NEXT_DISTINCT_CAUSAL_AXIS"
    return {
        "state": state,
        "next_axis": next_axis,
        "checks": checks,
        "improved_dimensions": improved,
        "degraded_dimensions": degraded,
        "research_pass": ladder.get("research_pass") is True,
    }


def _validate_summary_source(path: Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    source_id = f"replay_summary:{document.get('strategy_id', path.parent.name)}"
    source = validate_source(source_id, {
        "source_kind": "REPLAY_SUMMARY",
        "artifact": str(path),
        "run_id": run_id,
        "artifact_sha": canonical_sha(document),
        "document": document,
        "transform": "DIRECT_ARTIFACT",
        "inference_used": False,
        "private_fields_present": False,
        "stale": False,
    })
    return document, source


def triage(replay_root: Path, run_id: str, source_plan_sha: str) -> dict[str, Any]:
    strategy_paths = []
    for path in replay_root.rglob("summary.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if row.get("strategy_id") and row.get("variants") and row.get("capability_marker") == "MULTIMODAL_RESCUE_L090_REPLAY":
            strategy_paths.append(path)
    rows = []
    source_inventory = []
    for path in sorted(strategy_paths):
        summary, source = _validate_summary_source(path, run_id)
        source_inventory.append({key: source[key] for key in ("source_id", "source_kind", "artifact", "run_id", "artifact_sha", "transform")})
        variants = summary["variants"]
        control = next((row for row in variants if row.get("variant_id") == "NO_CHANGE_CONTROL"), None)
        if not isinstance(control, Mapping):
            raise ValueError(f"CONTROL_MISSING:{summary['strategy_id']}")
        candidate_rows = []
        for candidate in variants:
            if candidate.get("variant_id") == "NO_CHANGE_CONTROL":
                continue
            relation = _candidate_relation(candidate, control)
            candidate_rows.append({
                "candidate_id": candidate.get("variant_id"),
                "candidate_config_sha": candidate.get("candidate_config_sha256"),
                "axis": (candidate.get("candidate_config") or {}).get("axis"),
                "trade_count": candidate.get("trade_count"),
                "win_rate_pct": candidate.get("win_rate_pct"),
                "net_pct": candidate.get("net_return_pct_sum"),
                "profit_factor": candidate.get("net_profit_factor"),
                "payoff": candidate.get("payoff_ratio"),
                "max_drawdown_pct": candidate.get("max_drawdown_pct"),
                "avg_loss_r": (candidate.get("loss_metrics") or {}).get("avg_loss_R"),
                "worst_loss_r": (candidate.get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
                "stress_worst_loss_r": ((candidate.get("stress_2x_p95_plus_one") or {}).get("loss_metrics") or {}).get("normal_worst_net_loss_R"),
                "retention_pct": (candidate.get("ladder_check") or {}).get("trade_retention_pct"),
                "positive_windows_pct": candidate.get("positive_fresh_windows_pct"),
                "relation": relation,
                "variant_sha": canonical_sha(candidate),
            })
        survivors = [row for row in candidate_rows if row["relation"]["research_pass"]]
        near = [row for row in candidate_rows if row["relation"]["state"] == "NEAR_PASS_LOSS_SHAPE"]
        strategy_state = "PASS_L090" if survivors else "NEAR_PASS_LOSS_SHAPE" if near else "NEXT_DISTINCT_CAUSAL_AXIS"
        rows.append({
            "strategy_id": summary["strategy_id"],
            "source_summary_sha": source["artifact_sha"],
            "source_path": str(path),
            "strategy_state": strategy_state,
            "control_sha": canonical_sha(control),
            "candidates": candidate_rows,
            "l090_survivor_ids": [row["candidate_id"] for row in survivors],
            "near_pass_ids": [row["candidate_id"] for row in near],
            "proposal_contract_state": "HOLD_PRE_W1_OOS_AND_CAPACITY_FIELDS_UNAVAILABLE",
            "proposal_created": False,
            "reason_codes": ["PRE_W1_ONLY", "NO_W1_W2_W3_NEW_SEALED", "NO_CAPACITY_AUTHORITY"],
        })
    duplicate_keys = []
    seen = {}
    for row in rows:
        for candidate in row["candidates"]:
            key = (row["strategy_id"], candidate["axis"], candidate["candidate_config_sha"], source_plan_sha)
            if key in seen:
                duplicate_keys.append(key)
            seen[key] = candidate["variant_sha"]
    l090 = [
        {"strategy_id": row["strategy_id"], "candidate_id": candidate_id}
        for row in rows for candidate_id in row["l090_survivor_ids"]
    ]
    near = [
        {"strategy_id": row["strategy_id"], "candidate_id": candidate_id}
        for row in rows for candidate_id in row["near_pass_ids"]
    ]
    result = {
        "schema_version": "strategy11.source_bound_replay_triage.v1",
        "version": VERSION,
        "state": "PASS_SOURCE_BOUND_REPLAY_TRIAGE",
        "source_run_id": run_id,
        "source_plan_sha": source_plan_sha,
        "source_inventory": source_inventory,
        "source_inventory_sha": canonical_sha(source_inventory),
        "strategy_count": len(rows),
        "candidate_count": sum(len(row["candidates"]) for row in rows),
        "l090_candidates": l090,
        "near_pass_loss_shape": near,
        "duplicate_strategy_axis_config_data_count": len(duplicate_keys),
        "rows": rows,
        "installed_chain_usage": {
            "source_binding_contract": "PASS",
            "proposal_contract": "HOLD_UNTIL_W1_W2_W3_NEW_SEALED_AND_CAPACITY",
            "classifier": "NOT_RUN_PRE_W1",
            "correlation_analyzer": "NOT_RUN_WITHOUT_MULTIPLE_L090_SURVIVORS",
            "portfolio_governor": "NOT_RUN_PRE_SHADOW",
            "model_risk": "NOT_RUN_PRE_SHADOW",
        },
        "next": "L085_FOR_SURVIVORS_ELSE_NEXT_DISTINCT_AXIS_WITH_SEARCH_LEDGER",
        "research_only": True,
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }
    result["triage_sha"] = canonical_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-plan-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = triage(args.replay_root, args.run_id, args.source_plan_sha)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "triage.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["state"], "strategies=", result["strategy_count"], "l090=", len(result["l090_candidates"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
