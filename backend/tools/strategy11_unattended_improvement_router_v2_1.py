from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from backend.tools import strategy11_unattended_improvement_v2 as v2

VERSION = "STRATEGY11_UNATTENDED_IMPROVEMENT_ROUTER_V2_1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def validate_authority(value: Mapping[str, Any]) -> None:
    if value.get("strategy_id") != "alpha_combo":
        raise ValueError("ALPHA_AUTHORITY_STRATEGY_INVALID")
    if value.get("route") != "ALPHA_W1_MULTIOBJECTIVE_CONFIRMATION":
        raise ValueError("ALPHA_AUTHORITY_ROUTE_INVALID")
    if list(value.get("active_candidate_queue") or []) != ["TIME54", "TIME60"]:
        raise ValueError("ALPHA_AUTHORITY_QUEUE_INVALID")
    if value.get("same_dataset_generation_budget_exhausted") is not True:
        raise ValueError("ALPHA_GENERATION_BUDGET_NOT_EXHAUSTED")
    controls = value.get("controls")
    if not isinstance(controls, Mapping) or not {"TIME54", "TIME60", "STOP065_PROFIT_CONTROL"}.issubset(controls):
        raise ValueError("ALPHA_CONTROLS_INCOMPLETE")
    for key, expected in v2.SAFETY.items():
        if value.get(key) != expected:
            raise ValueError(f"ALPHA_AUTHORITY_SAFETY_MISMATCH:{key}")


def route_alpha(out: Path, authority: Mapping[str, Any]) -> None:
    plan_path = out / "plan.json"
    ledger_path = out / "search_ledger.json"
    coverage_path = out / "coverage.json"
    plan = read_json(plan_path)
    ledger = read_json(ledger_path)
    coverage = read_json(coverage_path)

    alpha_rows = [row for row in plan.get("rows", []) if row.get("strategy_id") == "alpha_combo"]
    if len(alpha_rows) > 1:
        raise ValueError("ALPHA_PLAN_DUPLICATE")
    removed_candidates = sum(len(row.get("candidate_ids") or []) for row in alpha_rows)
    plan["rows"] = [row for row in plan.get("rows", []) if row.get("strategy_id") != "alpha_combo"]
    plan["active_strategy_ids"] = [sid for sid in plan.get("active_strategy_ids", []) if sid != "alpha_combo"]
    plan["active_strategy_count"] = len(plan["rows"])
    plan["candidate_count"] = sum(len(row.get("candidate_ids") or []) for row in plan["rows"])
    plan["special_routes"] = [{
        "strategy_id": "alpha_combo",
        "route": authority["route"],
        "active_candidate_queue": list(authority["active_candidate_queue"]),
        "payoff_reference": authority["payoff_reference"],
        "source_pr": authority["source_pr"],
        "source_head_sha": authority["source_head_sha"],
        "source_run_id": authority["source_run_id"],
        "source_artifact_id": authority["source_artifact_id"],
        "same_dataset_generation_budget_exhausted": True,
        "requires_w1_fresh_non_overlap": True,
        "requires_new_sealed_holdback": True,
        "promotion_authority": False,
    }]
    plan["alpha_general_lane_candidate_count_removed"] = removed_candidates
    plan["alpha_authority_sha256"] = v2.stable_sha(authority)
    plan["router_version"] = VERSION
    plan["next"] = "LANE_AWARE_REPLAY_PLUS_ALPHA_W1_ROUTE" if plan["candidate_count"] else "ALPHA_W1_ROUTE_OR_WAIT"

    ledger_rows = [row for row in ledger.get("rows", []) if row.get("strategy_id") == "alpha_combo"]
    if len(ledger_rows) != 1:
        raise ValueError(f"ALPHA_LEDGER_ROW_COUNT:{len(ledger_rows)}")
    row = ledger_rows[0]
    prior = row.get("incumbent_snapshot")
    if not isinstance(prior, Mapping) or not isinstance(prior.get("candidate_config"), Mapping):
        raise ValueError("ALPHA_PRIOR_CONFIG_MISSING")
    time54 = dict(authority["controls"]["TIME54"])
    config = dict(prior["candidate_config"])
    config["candidate_id"] = "TIME54_AUTHORITY_CONTROL"
    config["axis"] = "ALPHA_MULTIOBJECTIVE_AUTHORITY"
    config["kind"] = "CONTROL"
    config["exit"] = dict(time54["exit"])
    snapshot = {
        "trade_count": int(time54["trade_count"]),
        "win_rate_pct": time54["win_rate_pct"],
        "net_return_pct_sum": time54["net_return_pct_sum"],
        "net_profit_factor": time54["net_profit_factor"],
        "payoff_ratio": time54["payoff_ratio"],
        "max_drawdown_pct": time54["max_drawdown_pct"],
        "positive_fresh_windows_pct": time54["positive_fresh_windows_pct"],
        "candidate_config_sha256": v2.stable_sha(config),
        "source_candidate_config_sha256": time54["candidate_config_sha256"],
        "candidate_config": config,
    }
    row["lane"] = "D_QUALITY_OPTIMIZATION"
    row["incumbent_snapshot"] = snapshot
    row["special_route"] = authority["route"]
    row["active_candidate_queue"] = list(authority["active_candidate_queue"])
    row["payoff_reference"] = authority["payoff_reference"]
    row["authority_sha256"] = v2.stable_sha(authority)
    row["same_dataset_generation_budget_exhausted"] = True
    row["requires_w1_fresh_non_overlap"] = True
    row["requires_new_sealed_holdback"] = True

    ledger["alpha_special_route"] = plan["special_routes"][0]
    ledger["alpha_authority_sha256"] = v2.stable_sha(authority)
    ledger["router_version"] = VERSION
    coverage["alpha_special_route_count"] = 1
    coverage["alpha_general_lane_candidate_count_removed"] = removed_candidates
    coverage["alpha_authority_sha256"] = v2.stable_sha(authority)
    coverage["router_version"] = VERSION

    for payload in (plan, ledger, coverage):
        payload.update(v2.SAFETY)
    v2.write_json(plan_path, plan)
    v2.write_json(ledger_path, ledger)
    v2.write_json(coverage_path, coverage)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--baseline-final", required=True)
    parser.add_argument("--alpha-authority", required=True)
    parser.add_argument("--previous-ledger")
    parser.add_argument("--now-utc")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    authority = read_json(Path(args.alpha_authority).resolve())
    validate_authority(authority)
    delegate = SimpleNamespace(
        policy=args.policy,
        catalog=args.catalog,
        baseline_final=args.baseline_final,
        previous_ledger=args.previous_ledger,
        now_utc=args.now_utc,
        out=args.out,
    )
    result = v2.build_plan(delegate)
    if result not in (0,):
        return result
    out = Path(args.out).resolve()
    route_alpha(out, authority)
    plan = read_json(out / "plan.json")
    print(json.dumps({
        "state": plan["state"],
        "router": VERSION,
        "active_lane_strategies": plan["active_strategy_count"],
        "lane_candidates": plan["candidate_count"],
        "alpha_route": plan["special_routes"][0]["route"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
