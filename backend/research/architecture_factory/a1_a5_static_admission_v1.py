"""Static fail-fast stage before any new A5 market evaluator dispatch.

Old saved A5 results stay immutable. Never auto-rewrite source rules, threshold,
position, fill or cost, or count rejected specs as economic failures.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ops.issue1388_candidate_static_preflight_v1 import inspect_spec


def evaluate_queue(econ: Any, queue: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the original engine output unchanged when all inputs are executable."""
    if not queue:
        return econ.evaluate_queue([])
    rejected: dict[str, dict[str, Any]] = {}
    eligible: list[Mapping[str, Any]] = []
    ids: set[str] = set()
    for candidate in queue:
        cid = str(candidate.get("candidate_id") or "")
        if not cid or cid in ids:
            raise ValueError("STATIC_ADMISSION_DUPLICATE_OR_MISSING_ID")
        ids.add(cid)
        spec = candidate.get("executable_spec")
        if not isinstance(spec, Mapping):
            findings = ["EXECUTABLE_SPEC_MISSING"]
        else:
            findings = inspect_spec(spec, issue1388_scope=False)["hard_issues"]
        # The sole #1388 owner enforces timeframe separately. This A5 helper
        # cannot grant authority or change the original A5 campaign scope.
        if findings:
            rejected[cid] = {
                "candidate_id": cid,
                "state": "REJECT_UNEXECUTABLE_SPEC",
                "economic_pass": False,
                "error": "STATIC_PRE_MARKET_RULE_BLOCK:" + ",".join(findings),
                "source_economic_run_started": False,
                "source_economic_claim_consumed": False,
            }
        else:
            eligible.append(candidate)
    if not rejected:
        return econ.evaluate_queue(list(queue))
    tested = econ.evaluate_queue(eligible) if eligible else {
        "schema_version": "zel.a1_gen2_generic_dev_econ.v3",
        "development_only": True,
        "mixed_scope": True,
        "cost_bps_per_trade": 14.0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "rows": [],
    }
    used = {str(x.get("candidate_id")): dict(x) for x in tested["rows"]}
    if any(str(c.get("candidate_id")) not in used for c in eligible):
        raise RuntimeError("STATIC_PRE_MARKET_ELIGIBLE_OUTPUT_MISSING")
    if len(used) != len(eligible):
        raise RuntimeError("STATIC_PRE_MARKET_ECONOMIC_ROW_CARDINALITY_DRIFT")
    result = dict(tested)
    result["rows"] = [rejected.get(str(c["candidate_id"]), used.get(str(c["candidate_id"]))) for c in queue]
    result["passes"] = [r for r in result["rows"] if r.get("economic_pass") is True]
    result["candidate_count"] = len(result["rows"])
    result["economic_pass_count"] = len(result["passes"])
    result["economic_fail_count"] = sum(r.get("state") == "FAIL_DEVELOPMENT_ECONOMICS" for r in result["rows"])
    result["insufficient_event_count"] = sum(r.get("state") == "FAIL_INSUFFICIENT_EVENTS" for r in result["rows"])
    result["source_skip_count"] = sum(str(r.get("state") or "").startswith("SKIP_") for r in result["rows"])
    result["spec_reject_count"] = sum(str(r.get("state") or "").startswith("REJECT_") for r in result["rows"])
    result["static_admission"] = {
        "blocked_count": len(rejected),
        "market_evaluation_bypassed_for": sorted(rejected),
        "did_not_modify_candidate_rules": True,
        "no_economic_authority_added": True,
    }
    return result
