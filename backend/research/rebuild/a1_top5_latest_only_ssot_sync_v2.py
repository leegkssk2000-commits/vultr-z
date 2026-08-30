#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SSOT = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
DEFAULT_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
DEFAULT_PROSPECTIVE = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
DEFAULT_G5 = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
DEFAULT_SHADOW = ROOT / "backend/research/prep/g5_trendrider_atr_pct_shadow_probe_latest.json"
DEFAULT_OUT = ROOT / "out/a1_top5_latest_only_ssot_v1.json"


def read(path: Path, *, optional: bool = False) -> dict[str, Any] | None:
    if optional and not path.exists():
        return None
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return x


def sync(ssot: dict[str, Any], freeze: dict[str, Any], prospective: dict[str, Any], g5: dict[str, Any], shadow: dict[str, Any] | None) -> dict[str, Any]:
    out = copy.deepcopy(ssot)
    assert out["schema_version"] == "zel.a1.top5.latest_only_ssot.v1"
    assert out["state"] == "CURRENT_TOP5_ONLY"
    assert freeze["schema_version"] == "zel.a1.top5.replacement_child_freeze.v2"
    assert freeze["state"] == "FROZEN_REPLACEMENT_CHILDREN_V2_PRE_PROSPECTIVE"
    assert prospective["schema_version"] == "zel.a1.top5.replacement_child.prospective.receipt.v2"
    assert prospective["state"] == "PASS_PROSPECTIVE_V2_CHILD_COLLECTION_ACTIVE"
    assert prospective["contract_path"] == "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
    assert prospective["boundary_utc"] == freeze["prospective_boundary"]["utc"]
    assert int(prospective["boundary_ms"]) == int(freeze["prospective_boundary"]["ms"])
    assert list(prospective["frozen_symbol_universe"]) == list(freeze["frozen_symbol_universe"])
    assert float(prospective["fixed_cost_bps_per_trade"]) == float(freeze["cost_model"]["cost_bps_per_trade"])
    assert prospective["g5_broad_population_mutated"] is False
    assert g5["state"] == "WAIT_G5_W2_12"
    assert g5["policy_retune"] is False and g5["threshold_retune"] is False
    assert int(g5["postlock_closed_T"]) == int(g5["windows"]["W2"]["metrics"]["trades"])

    out["replacement_child_sync"] = {
        "state": "THREE_DEVELOPMENT_PASS_CHILDREN_V2_FROZEN_FOR_FRESH_PROSPECTIVE_COLLECTION",
        "freeze_contract_path": "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json",
        "prospective_collector_path": "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json",
        "prospective_receipt_sha256": prospective.get("receipt_sha256"),
        "prospective_boundary_utc": prospective["boundary_utc"],
        "prospective_boundary_ms": prospective["boundary_ms"],
        "frozen_symbol_count": prospective["frozen_symbol_count"],
        "frozen_symbol_universe": prospective["frozen_symbol_universe"],
        "fixed_cost_bps_per_trade": prospective["fixed_cost_bps_per_trade"],
        "predecessor_v1_retired": prospective["predecessor_v1_retired"],
        "predecessor_v1_total_closed_T": prospective["predecessor_v1_total_closed_T"],
        "parent_raw_observer_consumable_T": 0,
        "total_fresh_child_T": prospective["total_closed_T"],
        "selection_authority": False,
        "promotion_authority": False,
    }

    freeze_by_lane = {x["lane_id"]: x for x in freeze["children"]}
    prospect_by_lane = prospective["lanes"]
    expected_lanes = {"break_and_continue_main", "keltner_trend_main", "supertrend_pullback_main"}
    assert set(freeze_by_lane) == expected_lanes
    assert set(prospect_by_lane) == expected_lanes

    for row in out["top5"]:
        lane = row.get("lane_id")
        if lane in expected_lanes:
            f = freeze_by_lane[lane]
            p = prospect_by_lane[lane]
            assert f["child_id"] == p["child_id"]
            assert p["predecessor_v1_consumed_T"] == 0
            assert p["old_parent_raw_observer_consumed_T"] == 0
            dm = f["development_metrics_at_20bps"]
            row["current_role"] = "REPLACEMENT_CHILD_V2_FROZEN_WAIT_FRESH_PROSPECTIVE_T"
            row["replacement_child"] = {
                "child_id": f["child_id"],
                "predecessor_child_id": f["predecessor_child_id"],
                "architecture_family": f["architecture_family"],
                "alpha_dsl_identical_to_v1": f["alpha_dsl_identical_to_v1"],
                "changed_from_v1": f["changed_from_v1"],
                "development_state": f["development_state_at_20bps"],
                "development_T": dm["trades"],
                "development_net_expectancy_bps": dm["net_expectancy_bps"],
                "development_net_pnl_bps": dm["net_pnl_bps"],
                "development_profit_factor": dm["profit_factor"],
                "development_win_rate": dm["win_rate"],
                "development_drawdown_bps": dm["drawdown_bps"],
                "fixed_cost_bps_per_trade": dm["cost_bps_per_trade"],
                "preboundary_arrival_rate_multiplier": f["preboundary_arrival_rate_multiplier"],
                "frozen_symbol_universe": prospective["frozen_symbol_universe"],
                "prospective_boundary_utc": p["boundary_utc"],
                "prospective_boundary_ms": p["boundary_ms"],
                "prospective_closed_T": p["closed_T"],
                "prospective_metrics": p["metrics"],
                "old_parent_raw_observer_burned_T": p["old_parent_raw_observer_burned_T"],
                "old_parent_raw_observer_consumed_T": p["old_parent_raw_observer_consumed_T"],
                "predecessor_v1_consumed_T": p["predecessor_v1_consumed_T"],
                "selection_authority": False,
                "promotion_authority": False,
            }

        if lane == "trend_rider_broad_wr7000":
            row["g5"] = {
                "state": g5["state"],
                "postlock_closed_T": g5["postlock_closed_T"],
                "W2_target_T": g5["windows"]["W2"]["target_T"],
                "W3_target_T": g5["windows"]["W3"]["target_T"],
                "source_path": "backend/research/prep/g5_trendrider_broad30_product_latest.json",
                "source_receipt_sha256": g5.get("receipt_sha256"),
                "source_input_receipt_sha256": g5.get("source_receipt_sha256"),
                "policy_retune": g5["policy_retune"],
                "threshold_retune": g5["threshold_retune"],
            }
            if shadow is not None:
                assert shadow["schema_version"] == "zel.g5.trendrider.atr_pct.shadow_probe.receipt.v1"
                assert shadow["lane_id"] == lane
                assert shadow["parent_mutated"] is False
                assert shadow["current_w2_rows_reused_as_shadow_T"] == 0
                row["g5"]["causal_shadow"] = {
                    "state": shadow["state"],
                    "axis": "ATR_PCT",
                    "source_path": "backend/research/prep/g5_trendrider_atr_pct_shadow_probe_latest.json",
                    "source_receipt_sha256": shadow.get("receipt_sha256"),
                    "probe_boundary_utc": shadow["probe_boundary_utc"],
                    "parent_future_T_after_probe_boundary": shadow["parent_future_T_after_probe_boundary"],
                    "shadow_accepted_T": shadow["shadow_accepted_T"],
                    "shadow_rejected_T": shadow["shadow_rejected_T"],
                    "shadow_metrics": shadow["shadow_metrics"],
                    "economic_roi_credit": False,
                    "selection_authority": False,
                    "promotion_authority": False,
                }

    rules = out.setdefault("reporting_rules", {})
    rules["replacement_child_current_owner"] = "V2_ONLY"
    rules["never_report_v1_replacement_child_as_current"] = True
    rules["g5_causal_shadow_is_not_economic_pass"] = True
    rules["dynamic_progress_sources_must_match_embedded_snapshot"] = True
    out["selection_authority"] = False
    out["promotion_authority"] = False
    out["execution_authority"] = "NONE"
    out["order_authority"] = "BLOCKED"
    out["live_trade_authority"] = "BLOCKED"
    return out


def self_test() -> int:
    assert DEFAULT_FREEZE.name == "a1_top5_replacement_child_freeze_v2.json"
    assert DEFAULT_PROSPECTIVE.name == "a1_top5_replacement_child_prospective_v2_latest.json"
    print("PASS_TOP5_LATEST_ONLY_SSOT_SYNC_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssot", type=Path, default=DEFAULT_SSOT)
    ap.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    ap.add_argument("--prospective", type=Path, default=DEFAULT_PROSPECTIVE)
    ap.add_argument("--g5", type=Path, default=DEFAULT_G5)
    ap.add_argument("--shadow", type=Path, default=DEFAULT_SHADOW)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    out = sync(read(args.ssot), read(args.freeze), read(args.prospective), read(args.g5), read(args.shadow, optional=True))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, sort_keys=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": out["state"],
        "replacement_owner": out["reporting_rules"]["replacement_child_current_owner"],
        "replacement_total_T": out["replacement_child_sync"]["total_fresh_child_T"],
        "g5_T": next(x for x in out["top5"] if x["lane_id"] == "trend_rider_broad_wr7000")["g5"]["postlock_closed_T"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
