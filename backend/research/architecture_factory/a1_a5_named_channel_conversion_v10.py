#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_a5_named_channel_conversion_v9 as v9
from backend.research.architecture_factory import a1_a5_economic_improvement_v6 as v6
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/rebuild/a1_production_highwr_top5_ssot_v1.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_a5_named_channel_conversion_latest.json"
SCHEMA = "zel.a1_a5_named_channel_conversion.v10_highwr_lane_ssot"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _lanes(ssot: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(x) for x in (ssot.get("production_top5") or []) if isinstance(x, Mapping)]
    if len(rows) != 5:
        raise RuntimeError(f"HIGHWR_EXACT5_LANES_REQUIRED:{len(rows)}")
    ids = [str(x.get("lane_id") or "") for x in rows]
    if any(not x for x in ids) or len(set(ids)) != 5:
        raise RuntimeError(f"HIGHWR_UNIQUE_LANE_IDS_REQUIRED:{ids}")
    if bool(ssot.get("low_wr_fallback_allowed")):
        raise RuntimeError("LOW_WR_FALLBACK_MUST_REMAIN_DISABLED")
    return rows


def _focus(lanes: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    counts: dict[str, int] = {}
    for row in lanes:
        sid = str(row.get("strategy_id") or "")
        counts[sid] = counts.get(sid, 0) + 1
    focus: list[str] = []
    blocked: dict[str, str] = {}
    for row in lanes:
        lane_id = str(row.get("lane_id") or "")
        sid = str(row.get("strategy_id") or "")
        if counts.get(sid, 0) > 1:
            blocked[lane_id] = "BLOCKED_DUPLICATE_STRATEGY_ID_REQUIRES_LANE_AWARE_GEMINI_EVALUATOR"
            continue
        if row.get("challenger_parent_eligible") is not True:
            blocked[lane_id] = "BLOCKED_DISPLAY_ONLY_NOT_CHALLENGER_PARENT"
            continue
        if sid not in focus:
            focus.append(sid)
    return focus, blocked


def _pseudo_league(ssot: Mapping[str, Any], focus: list[str]) -> dict[str, Any]:
    return {
        "active_top5": list(focus),
        "rows": [],
        "top5_selection_policy": "HIGHWR_LANE_SSOT_SAFE_EXECUTABLE_SUBSET_ONLY",
        "performance_top5_fully_eligible": False,
        "source": str(SSOT.relative_to(ROOT)),
        "low_wr_fallback_allowed": False,
    }


def run(output: Path) -> dict[str, Any]:
    ssot = _read(SSOT)
    lanes = _lanes(ssot)
    focus, blocked = _focus(lanes)
    if focus != ["break_and_continue"]:
        raise RuntimeError(f"EXPECTED_ONLY_BREAK_GEMINI_PARENT:{focus}")
    pseudo = _pseudo_league(ssot, focus)
    original_focus = v6._focus_order

    def highwr_focus() -> tuple[list[str], dict[str, Any]]:
        return list(focus), dict(pseudo)

    try:
        v6._focus_order = highwr_focus
        result = dict(v9.run(output))
    finally:
        v6._focus_order = original_focus

    bridge = result.get("named_channel_executable_bridge") or {}
    result["schema_version"] = SCHEMA
    result["production_top5_source"] = str(SSOT.relative_to(ROOT))
    result["production_top5_lane_ids"] = [str(x.get("lane_id") or "") for x in lanes]
    result["production_top5_lanes"] = lanes
    result["paid_gemini_current_safe_parent_strategy_ids"] = list(focus)
    result["blocked_lane_routes"] = blocked
    result["trend_rider_paid_gemini_blocked_until_lane_aware"] = True
    result["keltner_supertrend_paid_gemini_blocked_until_valid_parent"] = True
    result["trend_ma_top5_eligible"] = False
    result["low_wr_fallback_allowed"] = False
    result["stale_strategy_level_a5_order_forbidden"] = True
    result["paid_gemini_attempted_named_axis_count"] = int(bridge.get("attempted_named_axis_count") or 0)
    result["paid_gemini_development_economic_pass_count"] = int(result.get("development_economic_pass_count") or 0)
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    sample = {
        "low_wr_fallback_allowed": False,
        "production_top5": [
            {"lane_id": "tr1", "strategy_id": "trend_rider", "challenger_parent_eligible": True},
            {"lane_id": "tr2", "strategy_id": "trend_rider", "challenger_parent_eligible": True},
            {"lane_id": "br", "strategy_id": "break_and_continue", "challenger_parent_eligible": True},
            {"lane_id": "ke", "strategy_id": "keltner_trend", "challenger_parent_eligible": False},
            {"lane_id": "st", "strategy_id": "supertrend_pullback", "challenger_parent_eligible": False},
        ],
    }
    rows = _lanes(sample)
    focus, blocked = _focus(rows)
    assert focus == ["break_and_continue"]
    assert blocked["tr1"].startswith("BLOCKED_DUPLICATE_STRATEGY_ID")
    assert blocked["ke"] == "BLOCKED_DISPLAY_ONLY_NOT_CHALLENGER_PARENT"
    assert v9.v7.v3.AUTH["execution_authority"] == "NONE" and v9.v7.v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_A5_NAMED_CHANNEL_CONVERSION_V10_HIGHWR_SSOT_SELF_TEST")
    print("PASS_PAID_GEMINI_ONLY_SAFE_CURRENT_PARENT_NO_LOW_WR_FALLBACK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=LATEST)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    bridge = r.get("named_channel_executable_bridge") or {}
    print(json.dumps({
        "state": r.get("state"),
        "lanes": r.get("production_top5_lane_ids"),
        "safe_parent": r.get("paid_gemini_current_safe_parent_strategy_ids"),
        "attempted": bridge.get("attempted_named_axis_count"),
        "by_strategy": bridge.get("attempted_named_axes_by_strategy"),
        "development_pass": r.get("development_economic_pass_count"),
        "risk_pass": (r.get("named_channel_risk_sizing_evaluator") or {}).get("economic_pass_count"),
        "paid": r.get("paid_request_count"),
        "receipt": r.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
