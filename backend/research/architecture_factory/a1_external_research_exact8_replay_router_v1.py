from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPEC = ROOT / "backend/research/architecture_factory/a1_external_research_exact8_spec_v1.json"
DEFAULT_MANIFEST = ROOT / "backend/research/architecture_factory/a1_external_research_exact8_adapter_manifest_v1.json"

POST_MERGE_SOURCE_AUDIT = {
    "anchor_vwap_trend",
    "bb_revert",
    "break_and_continue",
    "fvg_revert",
    "range_fade",
    "session_bias",
}
HISTORY_8640 = {"rsi_swing_fail"}
PREENTRY_L2_TRADES = {"scalp_snap"}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_plan(spec: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    specs = spec.get("specs") or {}
    if len(specs) != 8 or set(specs) != POST_MERGE_SOURCE_AUDIT | HISTORY_8640 | PREENTRY_L2_TRADES:
        raise RuntimeError("EXACT8_SPEC_SET_REQUIRED")
    if spec.get("threshold_search") is not False or spec.get("holdout_outcomes_accessed") is not False:
        raise RuntimeError("OUTCOME_BLIND_SPEC_REQUIRED")
    if int(spec.get("effect_verified_count", -1)) != 0:
        raise RuntimeError("UNVERIFIED_EFFECT_REQUIRED")

    implemented = {str(x) for x in manifest.get("implemented_parent_ids") or []}
    pending = {str(x) for x in manifest.get("pending_parent_ids") or []}
    if implemented != (POST_MERGE_SOURCE_AUDIT | HISTORY_8640):
        raise RuntimeError("SEVEN_ADAPTER_MANIFEST_REQUIRED")
    if pending != PREENTRY_L2_TRADES:
        raise RuntimeError("SCALP_SNAP_ONLY_PENDING_REQUIRED")
    if bool(manifest.get("fresh_boundary_assigned")):
        raise RuntimeError("PREMERGE_BOUNDARY_FORBIDDEN")
    if int(manifest.get("effect_verified_count", -1)) != 0:
        raise RuntimeError("MANIFEST_EFFECT_MUST_BE_UNVERIFIED")

    rows: list[dict[str, Any]] = []
    for parent_id in sorted(specs):
        child_id = str(specs[parent_id]["child_id"])
        if parent_id in POST_MERGE_SOURCE_AUDIT:
            lane = "POST_MERGE_SOURCE_AUDIT"
            blocker = "MASTER_ADAPTER_AND_TIMESTAMP_SAFE_SOURCE_AUDIT_REQUIRED"
            adapter_ready = True
        elif parent_id in HISTORY_8640:
            lane = "HOLD_HISTORY_8640_RETURNS"
            blocker = "8640_PRIOR_COMPLETED_5M_RETURNS_REQUIRED"
            adapter_ready = True
        else:
            lane = "HOLD_PREENTRY_L2_TRADES_HISTORY"
            blocker = "TIMESTAMPED_PREENTRY_TRADES_AND_ORDERBOOK_DEPTH_REQUIRED"
            adapter_ready = False
        rows.append(
            {
                "parent_id": parent_id,
                "child_id": child_id,
                "adapter_ready": adapter_ready,
                "lane": lane,
                "blocker": blocker,
                "required_data": list(specs[parent_id]["required_data"]),
                "fresh_boundary_assigned": False,
                "replay_state": "NOT_RUN",
                "effect_verified": False,
            }
        )

    counts = {
        "post_merge_source_audit": sum(x["lane"] == "POST_MERGE_SOURCE_AUDIT" for x in rows),
        "hold_history_8640_returns": sum(x["lane"] == "HOLD_HISTORY_8640_RETURNS" for x in rows),
        "hold_preentry_l2_trades_history": sum(x["lane"] == "HOLD_PREENTRY_L2_TRADES_HISTORY" for x in rows),
    }
    plan = {
        "schema_version": "zel.a1_external_research_exact8_replay_router.v1",
        "state": "PASS_EXACT8_REPLAY_LANES_PLANNED_NO_BOUNDARY",
        "strategy_count": len(rows),
        "counts": counts,
        "rows": rows,
        "source_reality_evidence_used": False,
        "fresh_boundary_assigned": False,
        "boundary_assignment_authority": False,
        "replay_performed": False,
        "effect_verified_count": 0,
        "threshold_search": False,
        "holdout_outcomes_accessed": False,
        "synthetic_market_evidence_used": False,
        "next": "MERGE_ADAPTERS_THEN_AUDIT_SOURCE_REALITY_BEFORE_ASSIGNING_ANY_FRESH_BOUNDARY",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    plan["receipt_sha256"] = digest(plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    plan = build_plan(read(args.spec), read(args.manifest))
    if args.self_test:
        assert plan["counts"] == {
            "post_merge_source_audit": 6,
            "hold_history_8640_returns": 1,
            "hold_preentry_l2_trades_history": 1,
        }
        assert plan["fresh_boundary_assigned"] is False
        assert plan["effect_verified_count"] == 0
        assert plan["order_authority"] == "BLOCKED"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
