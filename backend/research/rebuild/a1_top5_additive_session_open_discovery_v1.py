#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_top5_additive_entry_union_v1 import evaluate

SCHEMA = "zel.a1.top5.additive_session_open_discovery.v1"
SOURCE = {
    "workflow_run_id": 32989455128,
    "artifact_id": 9614562185,
    "artifact_name": "a1-a4-exact-parent-repair-32989455128-1",
    "artifact_digest": "sha256:18d5432facd4f4776d564ed916ceb3dfc7a659732f1ca403630a0de8b3bd7eae",
    "workflow_head_sha": "de3e4173933567f973487e568b2930e0865db490",
}
SOURCE_FILES = {
    "keltner_trend": "keltner_trend_exact_parent.json",
    "supertrend_pullback": "supertrend_pullback_exact_parent.json",
}
LANE_IDS = {
    "keltner_trend": "keltner_trend_main",
    "supertrend_pullback": "supertrend_pullback_main",
}
EXPECTED_PARENT = {
    "keltner_trend": {"trades": 10, "win_rate": 0.5, "net_pnl_bps": 11583.28886165358, "net_expectancy_bps": 1158.328886165358, "profit_factor": 22.683937912169547, "drawdown_bps": 212.6882556068265},
    "supertrend_pullback": {"trades": 8, "win_rate": 0.5, "net_pnl_bps": 6463.155460281641, "net_expectancy_bps": 807.8944325352052, "profit_factor": 11.035858718022977, "drawdown_bps": 245.7358707597723},
}
EXPECTED_DISCOVERY_PASS = {
    "keltner_trend": "US_OPEN_16_UTC",
    "supertrend_pullback": "APAC_OPEN_00_UTC",
}
SESSION_OPEN_VALUES = [(0, "APAC_OPEN_00_UTC"), (8, "EU_OPEN_08_UTC"), (16, "US_OPEN_16_UTC")]


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def near(a: Any, b: Any, eps: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= eps * max(1.0, abs(float(b)))


def hour(trade: Mapping[str, Any]) -> int:
    return datetime.fromtimestamp(int(trade["signal_ts"]) / 1000.0, tz=timezone.utc).hour


def trade_key(trade: Mapping[str, Any]) -> tuple[Any, ...]:
    return (trade.get("symbol"), trade.get("signal_ts"), trade.get("entry_ts"), trade.get("side"))


def compact_trade(trade: Mapping[str, Any]) -> dict[str, Any]:
    keep = (
        "symbol", "signal_ts", "entry_ts", "exit_ts", "side", "entry", "exit",
        "gross_bps", "net_bps", "reason", "intent_sha", "policy_sha", "config_sha",
    )
    return {k: trade.get(k) for k in keep if k in trade}


def materialize(strategy_id: str, broad: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if broad.get("strategy_id") != strategy_id:
        raise RuntimeError(f"SOURCE_STRATEGY_MISMATCH:{strategy_id}:{broad.get('strategy_id')}")
    broad_trades = [dict(x) for x in broad.get("trades") or []]
    if not broad_trades:
        raise RuntimeError(f"SOURCE_TRADES_EMPTY:{strategy_id}")
    parent_trades = [compact_trade(x) for x in broad_trades if hour(x) in (13, 14, 15)]
    parent = {
        "schema_version": "zel.a1.top5.frozen_highwr_parent.v1",
        "state": "FROZEN_HIGHWR_PARENT_CORPUS",
        "strategy_id": strategy_id,
        "lane_id": LANE_IDS[strategy_id],
        "role": "FROZEN_PARENT_FOR_ADDITIVE_T_EXPANSION_ONLY",
        "membership_rule": {"axis": "SESSION_PRICE_DISCOVERY_OWNER_ONLY", "signal_hour_utc_in": [13, 14, 15], "outcome_blind": True},
        "source_artifact": SOURCE,
        "source_broad_parent_receipt_sha256": broad.get("receipt_sha256"),
        "source_broad_parent_trade_count": len(broad_trades),
        "trades": parent_trades,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    parent["receipt_sha256"] = stable(parent)

    candidates = []
    for h, value in SESSION_OPEN_VALUES:
        rows = [compact_trade(x) for x in broad_trades if hour(x) == h]
        candidates.append({
            "axis_value": value,
            "signal_hour_utc_equals": h,
            "trade_count": len(rows),
            "trade_identity_sha256": stable([trade_key(x) for x in rows]),
            "trades": rows,
        })
    family = {
        "schema_version": "zel.a1.top5.additive_session_open_family.v1",
        "state": "DEVELOPMENT_DISCOVERY_FAMILY_FROZEN",
        "strategy_id": strategy_id,
        "parent_lane_id": LANE_IDS[strategy_id],
        "axis": "FROZEN_SESSION_OPEN_TRANSITION_ONLY",
        "session_open_taxonomy": {"APAC_OPEN_00_UTC": 0, "EU_OPEN_08_UTC": 8, "US_OPEN_16_UTC": 16},
        "candidate_values_predeclared": [v for _, v in SESSION_OPEN_VALUES],
        "candidates": candidates,
        "numeric_threshold_sweep": False,
        "outcome_used_at_runtime": False,
        "development_selection_requires_fresh_prospective_confirmation": True,
        "source_artifact": SOURCE,
        "source_broad_parent_receipt_sha256": broad.get("receipt_sha256"),
        "source_broad_parent_trade_count": len(broad_trades),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    family["receipt_sha256"] = stable(family)
    return parent, family


def evaluate_family(strategy_id: str, parent: Mapping[str, Any], family: Mapping[str, Any]) -> dict[str, Any]:
    expected_parent = EXPECTED_PARENT[strategy_id]
    rows = []
    for candidate in family.get("candidates") or []:
        receipt = evaluate(parent, {"strategy_id": strategy_id, "trades": candidate.get("trades") or []})
        for key, expected in expected_parent.items():
            actual = receipt["parent_metrics"][key]
            if isinstance(expected, float):
                if not near(actual, expected):
                    raise RuntimeError(f"FROZEN_PARENT_METRIC_MISMATCH:{strategy_id}:{key}:{actual}:{expected}")
            elif actual != expected:
                raise RuntimeError(f"FROZEN_PARENT_METRIC_MISMATCH:{strategy_id}:{key}:{actual}:{expected}")
        rows.append({
            "axis_value": candidate["axis_value"],
            "signal_hour_utc_equals": candidate["signal_hour_utc_equals"],
            "source_trade_count": candidate["trade_count"],
            "source_trade_identity_sha256": candidate["trade_identity_sha256"],
            "additive_receipt": receipt,
            "development_pass": receipt["state"] == "PASS_ADD_ONLY_ENTRY_LANE",
        })
    rows.sort(key=lambda x: x["signal_hour_utc_equals"])
    passes = [x for x in rows if x["development_pass"]]
    expected = EXPECTED_DISCOVERY_PASS[strategy_id]
    if [x["axis_value"] for x in passes] != [expected]:
        raise RuntimeError(f"DISCOVERY_PASS_SET_CHANGED:{strategy_id}:{[x['axis_value'] for x in passes]}:{expected}")
    chosen = passes[0]
    ar = chosen["additive_receipt"]
    return {
        "strategy_id": strategy_id,
        "frozen_parent_lane_id": parent.get("lane_id"),
        "frozen_parent_receipt_sha256": parent.get("receipt_sha256"),
        "family_receipt_sha256": family.get("receipt_sha256"),
        "axis": family.get("axis"),
        "candidates": rows,
        "development_pass_count": 1,
        "development_discovery_candidate": {
            "axis_value": chosen["axis_value"],
            "signal_hour_utc_equals": chosen["signal_hour_utc_equals"],
            "parent_trade_count": ar["parent_trade_count"],
            "added_only_trade_count": ar["added_only_trade_count"],
            "combined_trade_count": ar["combined_trade_count"],
            "parent_match_pct": ar["parent_match_pct"],
            "parent_metrics": ar["parent_metrics"],
            "added_only_metrics": ar["added_only_metrics"],
            "combined_metrics": ar["combined_metrics"],
            "fresh_prospective_required": True,
            "promotion_allowed_from_this_receipt": False,
        },
        "state": "PASS_DEVELOPMENT_DISCOVERY_FRESH_REQUIRED",
    }


def run(artifact_dir: Path, out_dir: Path) -> dict[str, Any]:
    parents = {}
    families = {}
    results = {}
    for sid, filename in SOURCE_FILES.items():
        broad = read(artifact_dir / filename)
        parent, family = materialize(sid, broad)
        parents[sid] = parent
        families[sid] = family
        results[sid] = evaluate_family(sid, parent, family)

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_TWO_ADD_ONLY_DEVELOPMENT_DISCOVERIES_FRESH_REQUIRED",
        "mode": "FROZEN_HIGHWR_PARENT_PLUS_SESSION_OPEN_APPEND_ONLY",
        "source_artifact": SOURCE,
        "by_strategy": results,
        "policy": {
            "parent_match_required_pct": 100.0,
            "parent_trade_delete_forbidden": True,
            "parent_trade_rewrite_forbidden": True,
            "replacement_or_subset_child_for_t_expansion_forbidden": True,
            "only_unseen_trades_may_append": True,
            "session_open_values_predeclared": [v for _, v in SESSION_OPEN_VALUES],
            "numeric_threshold_sweep_forbidden": True,
            "development_discovery_cannot_promote": True,
            "fresh_prospective_confirmation_required": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)

    out_dir.mkdir(parents=True, exist_ok=True)
    for sid in parents:
        (out_dir / f"a1_{sid}_highwr_frozen_parent_v1.json").write_text(json.dumps(parents[sid], ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        (out_dir / f"a1_{sid}_session_open_add_lane_v1.json").write_text(json.dumps(families[sid], ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    (out_dir / "a1_top5_additive_session_open_discovery_latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert [v for _, v in SESSION_OPEN_VALUES] == ["APAC_OPEN_00_UTC", "EU_OPEN_08_UTC", "US_OPEN_16_UTC"]
    assert set(EXPECTED_DISCOVERY_PASS) == {"keltner_trend", "supertrend_pullback"}
    p = {"strategy_id": "demo", "trades": [
        {"symbol":"BTC-USDT","signal_ts":1,"entry_ts":2,"exit_ts":3,"side":"long","entry":100.0,"exit":101.0,"gross_bps":100.0,"net_bps":90.0,"reason":"TP"},
        {"symbol":"ETH-USDT","signal_ts":4,"entry_ts":5,"exit_ts":6,"side":"long","entry":100.0,"exit":99.0,"gross_bps":-10.0,"net_bps":-20.0,"reason":"SL"},
    ]}
    lane = {"strategy_id":"demo","trades":[
        {"symbol":"SOL-USDT","signal_ts":7,"entry_ts":8,"exit_ts":9,"side":"long","entry":100.0,"exit":102.0,"gross_bps":130.0,"net_bps":110.0,"reason":"TP"},
        {"symbol":"XRP-USDT","signal_ts":10,"entry_ts":11,"exit_ts":12,"side":"long","entry":100.0,"exit":102.0,"gross_bps":130.0,"net_bps":110.0,"reason":"TP"},
    ]}
    r = evaluate(p, lane)
    assert r["parent_match_pct"] == 100.0 and r["combined_trade_count"] == 4
    assert r["state"] == "PASS_ADD_ONLY_ENTRY_LANE"
    print("PASS_A1_TOP5_ADDITIVE_SESSION_OPEN_DISCOVERY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", type=Path)
    ap.add_argument("--out-dir", type=Path, default=Path("out/a1_top5_additive_session_open_v1"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.artifact_dir is None:
        raise RuntimeError("--artifact-dir required")
    result = run(args.artifact_dir, args.out_dir)
    brief = {
        "state": result["state"],
        "keltner": result["by_strategy"]["keltner_trend"]["development_discovery_candidate"],
        "supertrend": result["by_strategy"]["supertrend_pullback"]["development_discovery_candidate"],
        "receipt_sha256": result["receipt_sha256"],
    }
    print("A1_TOP5_ADDITIVE_SESSION_OPEN=" + json.dumps(brief, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
