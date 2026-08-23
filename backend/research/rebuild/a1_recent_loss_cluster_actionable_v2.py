#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as v1

POST_OUTCOME_AXES = {"COST_TO_ABS_GROSS", "REALIZED_COST_BPS", "REASON", "HOLD_BARS"}
PREENTRY_AXES = {"SYMBOL", "SIDE", "SESSION", "CHASE_ATR", "ST_GAP_ATR", "ATR_PCT"}


def _frozen_h5_session(ts_ms: int) -> str:
    h = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).hour
    return "APAC" if h < 8 else "EU" if h < 16 else "US"


def _material(c: dict[str, Any]) -> bool:
    axis = str(c.get("axis") or "")
    if axis in {"SYMBOL", "SIDE", "SESSION"}:
        return float(c.get("loss_streak_share") or 0.0) >= 0.75 and float(c.get("delta_share") or 0.0) >= 0.25
    if axis in {"CHASE_ATR", "ST_GAP_ATR", "ATR_PCT"}:
        return abs(float(c.get("relative_delta") or 0.0)) >= 0.25
    return False


def _route(strategy_id: str, candidates: list[dict[str, Any]], streak: int) -> tuple[str, dict[str, Any] | None]:
    if streak < 3:
        return "NO_STREAK_TRIGGER_CONTINUE_COLLECTION", None
    actionable = [c for c in candidates if str(c.get("axis") or "") in PREENTRY_AXES and _material(c)]
    if not actionable:
        return f"REQUIRE_STRATEGY_NATIVE_PREENTRY_FEATURE_ATTRIBUTION:{strategy_id}", None
    root = actionable[0]
    axis = str(root["axis"])
    if axis in {"SYMBOL", "SIDE", "SESSION"}:
        return f"PREREGISTER_PREENTRY_CONTEXT_CHILD:{axis}:{root.get('value')}:ONE_AXIS_ONLY", root
    return f"PREREGISTER_PREENTRY_STRUCTURAL_CHILD:{axis}:BORROW_EXISTING_CAUSAL_GEOMETRY_ONLY", root


def diagnose(strategy_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    # Force the already-frozen H5 taxonomy; do not learn session boundaries from losses.
    old_session = v1._session
    try:
        v1._session = _frozen_h5_session
        row = v1.diagnose(strategy_id, receipt)
    finally:
        v1._session = old_session

    ranked = [dict(x) for x in row.get("ranked_causal_hypotheses") or []]
    route, root = _route(strategy_id, ranked, int(row.get("current_loss_streak") or 0))
    row["forensic_raw_recommended_route"] = row.get("recommended_route")
    row["recommended_route"] = route
    row["actionable_root_cause"] = root
    row["actionable_preentry_hypotheses"] = [x for x in ranked if str(x.get("axis") or "") in PREENTRY_AXES]
    row["diagnostic_only_post_outcome_hypotheses"] = [x for x in ranked if str(x.get("axis") or "") in POST_OUTCOME_AXES]
    row["post_outcome_axes_forbidden_for_runtime_filter"] = sorted(POST_OUTCOME_AXES)
    row["session_taxonomy"] = "APAC_UTC_00_07__EU_UTC_08_15__US_UTC_16_23"
    row["session_taxonomy_authority"] = "backend/research/rebuild/a1_trend_rider_h4_h5_hardening_v1.py"
    row["outcome_fitted_session_boundary"] = False
    row["receipt_sha256"] = v1.sha({k: val for k, val in row.items() if k != "receipt_sha256"})
    return row


def run(out: Path) -> dict[str, Any]:
    results = []
    with tempfile.TemporaryDirectory(prefix="a1_loss_cluster_actionable_v2_") as td:
        for sid in v1.TARGETS:
            receipt = v1._run_receipt(sid, Path(td) / f"{sid}.json")
            results.append(diagnose(sid, receipt))
    triggered = [x for x in results if int(x.get("current_loss_streak") or 0) >= 3]
    row = {
        "schema_version": "zel.a1.recent_loss_cluster_actionable.v2",
        "state": "LOSS_CLUSTER_REPAIR_REQUIRED" if triggered else "NO_MULTI_LOSS_CLUSTER_TRIGGER",
        "trigger_min_consecutive_losses": 3,
        "targets": results,
        "triggered_strategy_ids": [x["strategy_id"] for x in triggered],
        "policy": "KEEP_INCUMBENT_FROZEN; POST_OUTCOME_AXES_DIAGNOSTIC_ONLY; ACTION_ONLY_PREENTRY_AXIS; FROZEN_H5_SESSION_TAXONOMY; NEW_FRESH_BOUNDARY; NO_POST_OUTCOME_RETUNE",
        **v1.AUTH,
    }
    row["receipt_sha256"] = v1.sha(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return row


def self_test() -> int:
    assert _frozen_h5_session(15 * 3600 * 1000) == "EU"
    assert _frozen_h5_session(16 * 3600 * 1000) == "US"
    fake = {"axis": "SESSION", "value": "US", "loss_streak_share": 0.75, "delta_share": 0.45}
    route, root = _route("trend_rider", [
        {"axis": "COST_TO_ABS_GROSS", "relative_delta": 3.0, "diagnostic_score": 9.0}, fake
    ], 4)
    assert root == fake and route.startswith("PREREGISTER_PREENTRY_CONTEXT_CHILD:SESSION:US")
    route2, root2 = _route("keltner_trend", [
        {"axis": "REASON", "value": "SL", "loss_streak_share": 1.0, "delta_share": 0.6}
    ], 4)
    assert root2 is None and route2.startswith("REQUIRE_STRATEGY_NATIVE_PREENTRY_FEATURE_ATTRIBUTION")
    print("PASS_A1_RECENT_LOSS_CLUSTER_ACTIONABLE_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_recent_loss_cluster_actionable_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({
        "state": r["state"],
        "triggered": r["triggered_strategy_ids"],
        "routes": {x["strategy_id"]: x["recommended_route"] for x in r["targets"]},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
