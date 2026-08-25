#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
H5_ROUTE = ROOT / "backend/research/g4_h5_bottleneck_route_latest.json"
LEAGUE = ROOT / "backend/research/rebuild/a1_strategy25_improvement_league_latest.json"
DEFAULT_OUT = ROOT / "backend/research/g4_failover_rotation_latest.json"
SCHEMA = "zel.g4.failover_rotation.v1"
FAILOVER_ROUTE = "FAILOVER_TO_NEXT5_OR_NEW_MECHANISM_NOW"
FRESH_ROUTE = "FRESH_SAMPLE_EXPANSION_TOP10_DILUTION"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def rotate(h5: Mapping[str, Any], league: Mapping[str, Any]) -> dict[str, Any]:
    old = [str(x) for x in (h5.get("active_top5") or [])]
    if len(old) != 5 or len(set(old)) != 5:
        raise RuntimeError(f"ACTIVE_TOP5_INVALID:{old}")

    routes = [dict(x) for x in (h5.get("routes") or []) if isinstance(x, Mapping)]
    route_map = {str(x.get("strategy_id")): x for x in routes}
    if set(route_map) != set(old):
        raise RuntimeError(f"ROUTE_COVERAGE_INVALID:{sorted(route_map)}")

    failover = [sid for sid in old if route_map[sid].get("route") == FAILOVER_ROUTE]
    retained = [sid for sid in old if route_map[sid].get("route") == FRESH_ROUTE]
    other = [sid for sid in old if sid not in failover and sid not in retained]
    if len(failover) != 4 or len(retained) != 1 or other:
        raise RuntimeError(f"EXPECTED_4_FAILOVER_1_FRESH:failover={failover}:retained={retained}:other={other}")

    next5 = [str(x) for x in (league.get("challenger_next5") or [])]
    if len(next5) != 5 or len(set(next5)) != 5:
        raise RuntimeError(f"CHALLENGER_NEXT5_INVALID:{next5}")
    eligible = [sid for sid in next5 if sid not in old]
    if len(eligible) < len(failover):
        raise RuntimeError(f"INSUFFICIENT_UNIQUE_CHALLENGERS:{eligible}")

    chosen = eligible[: len(failover)]
    replacement_map = [
        {
            "slot": old.index(src) + 1,
            "replaced_strategy_id": src,
            "replacement_strategy_id": dst,
            "source_role": "CHALLENGER_NEXT5",
            "reason": str(route_map[src].get("route_reason") or FAILOVER_ROUTE),
        }
        for src, dst in zip(failover, chosen)
    ]
    replacement_lookup = {x["replaced_strategy_id"]: x["replacement_strategy_id"] for x in replacement_map}
    new_slate = [replacement_lookup.get(sid, sid) for sid in old]
    if len(new_slate) != 5 or len(set(new_slate)) != 5:
        raise RuntimeError(f"NEW_SLATE_INVALID:{new_slate}")

    retained_lanes = []
    for sid in retained:
        row = route_map[sid]
        retained_lanes.append({
            "strategy_id": sid,
            "route": row.get("route"),
            "candidate_id": row.get("candidate_id"),
            "candidate_trades": row.get("candidate_trades"),
            "candidate_net_expectancy_bps": row.get("candidate_net_expectancy_bps"),
            "candidate_profit_factor": row.get("candidate_profit_factor"),
            "candidate_drawdown_bps": row.get("candidate_drawdown_bps"),
            "candidate_retention_pct": row.get("candidate_retention_pct"),
            "h5_blockers": row.get("h5_blockers") or [],
            "top10_profit_share": row.get("top10_profit_share"),
            "top10_limit": row.get("top10_limit"),
            "top10_excess": row.get("top10_excess"),
            "fresh_oos_required_before_survivor": True,
        })

    result = {
        "schema_version": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_G4_FAILOVER_ROTATION_BOUND",
        "source_h5_state": h5.get("state"),
        "old_active_top5": old,
        "challenger_next5": next5,
        "replacement_map": replacement_map,
        "new_g4_slate": new_slate,
        "retained_strategy_ids": retained,
        "retained_fresh_lanes": retained_lanes,
        "reserve_challengers": [sid for sid in eligible if sid not in chosen],
        "failover_count": len(failover),
        "retained_count": len(retained),
        "formal_league_active_top5_mutated": False,
        "same_axis_repeat_allowed": False,
        "h5_threshold_weakening_allowed": False,
        "post_outcome_trade_deletion_allowed": False,
        "holdout_economics_inspected": False,
        "fresh_oos_required_before_survivor": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": "EVALUATE_NEW_G4_SLATE_AND_EXPAND_TREND_RIDER_FRESH_SAMPLE",
    }
    result["receipt_sha256"] = stable(result)
    return result


def run(out: Path) -> dict[str, Any]:
    result = rotate(read(H5_ROUTE), read(LEAGUE))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    old = ["a", "b", "c", "d", "e"]
    h5 = {
        "state": "PASS_G4_H5_ANTI_STALL_ROUTE_BOUND",
        "active_top5": old,
        "routes": [
            {"strategy_id": "a", "route": FAILOVER_ROUTE, "route_reason": "x"},
            {"strategy_id": "b", "route": FRESH_ROUTE, "candidate_id": "b1", "candidate_trades": 58, "top10_profit_share": 0.86, "top10_limit": 0.8, "top10_excess": 0.06},
            {"strategy_id": "c", "route": FAILOVER_ROUTE, "route_reason": "x"},
            {"strategy_id": "d", "route": FAILOVER_ROUTE, "route_reason": "x"},
            {"strategy_id": "e", "route": FAILOVER_ROUTE, "route_reason": "x"},
        ],
    }
    league = {"challenger_next5": ["f", "g", "h", "i", "j"]}
    r = rotate(h5, league)
    assert r["new_g4_slate"] == ["f", "b", "g", "h", "i"]
    assert r["reserve_challengers"] == ["j"]
    assert r["failover_count"] == 4 and r["retained_count"] == 1
    assert r["formal_league_active_top5_mutated"] is False
    assert r["execution_authority"] == "NONE" and r["order_authority"] == "BLOCKED"
    print("PASS_G4_FAILOVER_ROTATION_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out.resolve())
    print(json.dumps({
        "state": result["state"],
        "new_g4_slate": result["new_g4_slate"],
        "reserve": result["reserve_challengers"],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
