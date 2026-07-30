from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.tools.strategy11_bounded_internal_mutation_v3 import build_candidates

VERSION = "STRATEGY11_V3_INTERNAL_REGIME_ORCHESTRATOR"
SAFETY = {"research_only": True, "promotion_authority": False, "protected_mutations": 0, "execution_allowed": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "runtime_bound": False}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def controls(baseline: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in baseline.get("rows", []):
        if not isinstance(row, Mapping) or not row.get("strategy_id"):
            continue
        control = next((dict(value) for value in row.get("variants", []) if isinstance(value, Mapping) and value.get("variant_id") == "NO_CHANGE_CONTROL"), None)
        if control:
            output[str(row["strategy_id"])] = control
    return output


def lane(count: int) -> str:
    return "A_ENTRY_LIVENESS_REPAIR" if count <= 0 else "B_COVERAGE_EXPANSION" if count <= 4 else "C_DISCOVERY_OPTIMIZATION" if count <= 9 else "D_QUALITY_OPTIMIZATION"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True); parser.add_argument("--baseline", required=True); parser.add_argument("--policy", required=True); parser.add_argument("--previous-ledger"); parser.add_argument("--out", required=True)
    args = parser.parse_args()
    registry = read_json(Path(args.registry).resolve())
    baseline = read_json(Path(args.baseline).resolve())
    policy = read_json(Path(args.policy).resolve())
    previous = read_json(Path(args.previous_ledger).resolve()) if args.previous_ledger and Path(args.previous_ledger).exists() else {"cycle_index": 0, "rows": []}
    previous_map = {str(row.get("strategy_id")): row for row in previous.get("rows", []) if isinstance(row, Mapping)}
    control_map = controls(baseline)
    rows: list[dict[str, Any]] = []; no_action: list[dict[str, Any]] = []; ledger_rows: list[dict[str, Any]] = []
    cycle = int(previous.get("cycle_index") or 0) + 1
    for registry_row in registry["rows"]:
        strategy_id = str(registry_row["strategy_id"])
        if strategy_id == "alpha_combo":
            no_action.append({"strategy_id": strategy_id, "reason": "ALPHA_TIME54_TIME60_W1_AUTHORITY"})
            continue
        control = control_map.get(strategy_id)
        if control is None:
            raise RuntimeError(f"CONTROL_MISSING:{strategy_id}")
        current_lane = lane(int(control.get("trade_count") or 0))
        prior = previous_map.get(strategy_id, {})
        tested = {str(value) for value in prior.get("tested_candidate_ids", [])}
        candidates = build_candidates(registry_row, current_lane, tested, int(policy["internal_mutation"]["max_candidates_per_strategy_cycle"]))
        if not candidates:
            no_action.append({"strategy_id": strategy_id, "reason": "NO_SAFE_UNTESTED_INTERNAL_AXIS", "lane": current_lane})
        else:
            rows.append({"strategy_id": strategy_id, "family": registry_row["family"], "lane": current_lane, "incumbent_trade_count": int(control.get("trade_count") or 0), "candidate_ids": [row["candidate_id"] for row in candidates], "candidate_specs": {row["candidate_id"]: row for row in candidates}, "selection_reason": "BOUNDED_INTERNAL_AND_REGIME_EDGE_SEARCH", "cycle_index": cycle})
        ledger_rows.append({"strategy_id": strategy_id, "tested_candidate_ids": sorted(tested | {row["candidate_id"] for row in candidates}), "last_cycle": cycle, "incumbent_config_sha256": control.get("candidate_config_sha256")})
    plan = {"schema_version": "3.0", "version": VERSION, "state": "PASS_V3_PLAN" if rows else "COMPLETE_NO_SAFE_UNTESTED_AXIS", "cycle_index": cycle, "strategy_count_total": len(registry["rows"]), "active_strategy_count": len(rows), "active_strategy_ids": [row["strategy_id"] for row in rows], "candidate_count": sum(len(row["candidate_ids"]) for row in rows), "rows": rows, "no_action": no_action, "alpha_special_route": "ALPHA_W1_MULTIOBJECTIVE_CONFIRMATION", "blind_cartesian_product_used": False, **SAFETY}
    ledger = {"schema_version": "3.0", "version": VERSION, "state": "PLAN_READY", "cycle_index": cycle, "rows": ledger_rows, "plan_sha256": stable_sha(plan), **SAFETY}
    out = Path(args.out).resolve(); write_json(out / "plan.json", plan); write_json(out / "search_ledger.json", ledger)
    print(json.dumps({"state": plan["state"], "strategies": len(rows), "candidates": plan["candidate_count"], "cycle": cycle}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
