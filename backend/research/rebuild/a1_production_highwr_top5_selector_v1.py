from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

MIN_WR = 0.50
LANE_ORDER = [
    "trend_rider_primary_wr8125",
    "trend_rider_broad_wr7000",
    "break_and_continue_main",
    "keltner_trend_main",
    "supertrend_pullback_main",
]
EXCLUDED_ROLES = {
    "FORMAL",
    "FORMAL_REPLAY",
    "ACTIVE_DEEP",
    "GENERIC_REPLAY",
    "FRESH_FORWARD",
    "FRESH_GROWTH",
    "UNPROMOTED_CHILD",
    "UNPROMOTED_CHALLENGER",
}
ALLOWED_MAIN_ROLES = {
    "MAIN",
    "PRODUCTION_MAIN",
    "FROZEN_PRODUCTION_MAIN",
    "INCUMBENT",
    "FROZEN_MAIN",
    "FROZEN_WINNER_BENCHMARK",
    "FROZEN_BROAD_CONTROL",
    "FROZEN_G4_MAIN",
}


def _wr(row: Dict[str, Any]) -> float | None:
    value = row.get("win_rate")
    if value is None:
        metrics = row.get("metrics") or {}
        value = metrics.get("win_rate")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify(row: Dict[str, Any]) -> Dict[str, Any]:
    lane_id = str(row.get("lane_id") or "")
    role = str(row.get("role") or row.get("source_role") or "").upper()
    wr = _wr(row)
    promoted = bool(row.get("promotion_authority") or row.get("production_headline_eligible"))

    reasons: List[str] = []
    if not lane_id:
        reasons.append("MISSING_LANE_ID")
    elif lane_id not in LANE_ORDER:
        reasons.append(f"UNKNOWN_PRODUCTION_LANE:{lane_id}")
    if role in EXCLUDED_ROLES:
        reasons.append(f"EXCLUDED_ROLE:{role}")
    if role not in ALLOWED_MAIN_ROLES:
        reasons.append(f"NOT_MAIN_ROLE:{role or 'MISSING'}")
    if wr is None:
        reasons.append("MISSING_WIN_RATE")
    elif wr < MIN_WR:
        reasons.append(f"WR_BELOW_50:{wr:.6f}")
    if role in {"FRESH_FORWARD", "FRESH_GROWTH", "UNPROMOTED_CHILD", "UNPROMOTED_CHALLENGER"} and not promoted:
        reasons.append("UNPROMOTED_EVIDENCE")

    eligible = not reasons
    return {"eligible": eligible, "reasons": reasons, "win_rate": wr, "role": role, "lane_id": lane_id}


def select(rows: Iterable[Dict[str, Any]], lane_order: Iterable[str] = LANE_ORDER) -> Dict[str, Any]:
    by_lane: Dict[str, List[Dict[str, Any]]] = {}
    rejected: List[Dict[str, Any]] = []
    for row in rows:
        lane_id = str(row.get("lane_id") or "")
        verdict = classify(row)
        if verdict["eligible"]:
            by_lane.setdefault(lane_id, []).append(row)
        else:
            rejected.append({
                "lane_id": lane_id,
                "strategy_id": row.get("strategy_id"),
                "candidate_id": row.get("candidate_id"),
                **verdict,
            })

    selected: List[Dict[str, Any]] = []
    for lane_id in lane_order:
        candidates = by_lane.get(lane_id, [])
        if not candidates:
            selected.append({
                "lane_id": lane_id,
                "role": "VACANT_PENDING_HIGHWR_MAIN_PROVENANCE",
                "production_headline_eligible": False,
                "reason": "NO_VERIFIED_WR50_MAIN_FOR_LANE; LOW_WR_FALLBACK_FORBIDDEN",
            })
            continue
        candidates.sort(
            key=lambda x: (
                _wr(x) or 0.0,
                int(x.get("completed_trades") or x.get("trade_count") or 0),
                float(x.get("net_pnl_bps") or 0.0),
            ),
            reverse=True,
        )
        selected.append(candidates[0])

    return {
        "schema_version": "zel.a1_production_highwr_top5_selection.v2",
        "selection_unit": "lane_id",
        "minimum_production_win_rate": MIN_WR,
        "low_wr_fallback_allowed": False,
        "selected": selected,
        "rejected": rejected,
    }


def _self_test() -> None:
    rows = [
        {"lane_id": "trend_rider_primary_wr8125", "strategy_id": "trend_rider", "role": "FROZEN_WINNER_BENCHMARK", "win_rate": 0.8125, "completed_trades": 16, "production_headline_eligible": True},
        {"lane_id": "trend_rider_broad_wr7000", "strategy_id": "trend_rider", "role": "FROZEN_BROAD_CONTROL", "win_rate": 0.70, "completed_trades": 30, "production_headline_eligible": True},
        {"lane_id": "break_and_continue_main", "strategy_id": "break_and_continue", "role": "FROZEN_PRODUCTION_MAIN", "win_rate": 5/9, "completed_trades": 9, "production_headline_eligible": True},
        {"lane_id": "keltner_trend_main", "strategy_id": "keltner_trend", "role": "FROZEN_G4_MAIN", "win_rate": 0.50, "completed_trades": 10, "production_headline_eligible": True},
        {"lane_id": "supertrend_pullback_main", "strategy_id": "supertrend_pullback", "role": "FROZEN_G4_MAIN", "win_rate": 0.50, "completed_trades": 8, "production_headline_eligible": True},
        {"lane_id": "trend_rider_primary_wr8125", "strategy_id": "trend_rider", "role": "FORMAL_REPLAY", "win_rate": 0.46, "completed_trades": 30},
        {"lane_id": "break_and_continue_main", "strategy_id": "break_and_continue", "role": "GENERIC_REPLAY", "win_rate": 0.2963, "completed_trades": 27},
        {"lane_id": "supertrend_pullback_main", "strategy_id": "supertrend_pullback", "role": "FRESH_GROWTH", "win_rate": 0.50, "completed_trades": 10, "promotion_authority": False},
        {"lane_id": "trend_ma_macd_main", "strategy_id": "trend_ma_macd", "role": "FROZEN_MAIN", "win_rate": 0.60, "completed_trades": 10, "production_headline_eligible": True},
    ]
    out = select(rows)
    selected = out["selected"]
    assert [x["lane_id"] for x in selected] == LANE_ORDER
    assert selected[0]["win_rate"] == 0.8125
    assert selected[1]["win_rate"] == 0.70
    assert abs(selected[2]["win_rate"] - 5/9) < 1e-12
    assert selected[3]["win_rate"] == 0.50
    assert selected[4]["win_rate"] == 0.50
    assert sum(1 for x in selected if x.get("strategy_id") == "trend_rider") == 2
    assert all(x.get("strategy_id") != "trend_ma_macd" for x in selected)
    assert not any(str(x.get("role", "")).startswith("VACANT_") for x in selected)
    rejected_roles = {x["role"] for x in out["rejected"]}
    assert "FORMAL_REPLAY" in rejected_roles
    assert "GENERIC_REPLAY" in rejected_roles
    assert "FRESH_GROWTH" in rejected_roles
    assert any("UNKNOWN_PRODUCTION_LANE:trend_ma_macd_main" in x["reasons"] for x in out["rejected"])
    assert out["low_wr_fallback_allowed"] is False
    print("PASS_A1_PRODUCTION_HIGHWR_TOP5_SELECTOR_V2_SELF_TEST")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--rows")
    p.add_argument("--out")
    args = p.parse_args()
    if args.self_test:
        _self_test()
        return
    if not args.rows or not args.out:
        p.error("--rows and --out are required unless --self-test")
    rows = json.loads(Path(args.rows).read_text())
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("targets") or rows.get("production_top5") or []
    result = select(rows)
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
