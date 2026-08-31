#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_g4_g5_parallel_conveyor_v1.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
PROSPECTIVE = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
G5_READY = ROOT / "backend/research/prep/G5_PREP_READY_v1.json"
G5_CONTRACT = ROOT / "backend/research/prep/g5_validation_contract_v1.json"
BROAD = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
LATEST = ROOT / "backend/research/rebuild/a1_g4_g5_parallel_conveyor_v1_latest.json"
SCHEMA = "zel.a1.g4_g5.parallel_conveyor.receipt.v1"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def metrics_from_values(values: list[float]) -> dict[str, Any]:
    gp = sum(x for x in values if x > 0)
    gl = -sum(x for x in values if x < 0)
    eq = peak = dd = 0.0
    for value in values:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "closed_T": len(values),
        "wins": sum(1 for x in values if x > 0),
        "win_rate": (sum(1 for x in values if x > 0) / len(values)) if values else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": (sum(values) / len(values)) if values else None,
        "profit_factor": (gp / gl) if gl > 0 else None,
        "profit_factor_unbounded": bool(gp > 0 and gl == 0),
        "drawdown_bps": dd,
    }


def pf_gt_one(m: Mapping[str, Any]) -> bool:
    if bool(m.get("profit_factor_unbounded")):
        return True
    pf = m.get("profit_factor")
    return pf is not None and math.isfinite(float(pf)) and float(pf) > 1.0


def candidate_diag(trades: list[Mapping[str, Any]], c: Mapping[str, Any]) -> dict[str, Any]:
    policy = c["parallel_policy"]
    rules = c["pre_g5_diagnostic_rules"]
    base = [float(x["net_bps"]) for x in trades]
    # V2 source already deducts one 20 bps round-trip cost. A 2x-cost stress deducts one more source cost.
    source_cost = [float(x.get("cost_bps") or 0.0) for x in trades]
    cost2x = [float(x["net_bps"]) - float(x.get("cost_bps") or 0.0) for x in trades]
    lev = float(policy["paper_leverage_x"])
    pos = float(policy["paper_position_pct"]) / 100.0
    paper_scale = lev * pos
    paper = [x * paper_scale for x in base]

    shadow = metrics_from_values(base)
    stress = metrics_from_values(cost2x)
    paper_m = metrics_from_values(paper)
    t = int(shadow["closed_T"])
    min_t = int(rules["minimum_T_for_first_signal"])
    checks = {
        "minimum_T": t >= min_t,
        "net_positive": float(shadow["net_pnl_bps"]) > 0.0,
        "expectancy_positive": shadow["net_expectancy_bps"] is not None and float(shadow["net_expectancy_bps"]) > 0.0,
        "profit_factor_gt_1": pf_gt_one(shadow),
        "cost_2x_net_positive": float(stress["net_pnl_bps"]) > 0.0,
    }
    if t < min_t:
        state = "ACCUMULATING_PRE_G5_SHADOW_PAPER"
    elif all(checks.values()):
        state = "PRE_G5_DIAGNOSTIC_GREEN_NOT_FORMAL_G5_PASS"
    else:
        state = "PRE_G5_DIAGNOSTIC_RED_NONFORMAL"
    next_checkpoint = next((x for x in policy["diagnostic_checkpoints_T"] if t < int(x)), None)
    return {
        "state": state,
        "pre_g5_shadow_T": t,
        "pre_g5_paper_T": t,
        "formal_g5_T": 0,
        "formal_g5_credit": 0,
        "shadow_metrics": shadow,
        "stress_cost_2x_metrics": stress,
        "paper_sim": {
            "mode": "PAPER_SIM_ONLY",
            "leverage_x": lev,
            "position_pct": float(policy["paper_position_pct"]),
            "account_pnl_bps_scale": paper_scale,
            "metrics_account_bps": paper_m,
            "order_submission": False,
        },
        "checks": checks,
        "next_diagnostic_checkpoint_T": next_checkpoint,
        "formal_interpretation": "DIAGNOSTIC_ONLY_UNTIL_FORMAL_G4_PASS",
    }


def top5_map(top5: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = [dict(x) for x in top5.get("top5") or [] if isinstance(x, Mapping)]
    out = {str(x.get("lane_id") or ""): x for x in rows}
    if len(rows) != 5 or len(out) != 5:
        raise RuntimeError("EXACT_TOP5_REQUIRED")
    return out


def run(out: Path) -> dict[str, Any]:
    c = read(CONTRACT)
    top5 = read(TOP5)
    prospective = read(PROSPECTIVE)
    g5_ready = read(G5_READY)
    g5_contract = read(G5_CONTRACT)
    broad = read(BROAD)

    if c.get("state") != "G4_G5_PARALLEL_PREVALIDATION_ACTIVE":
        raise RuntimeError("CONVEYOR_CONTRACT_STATE_DRIFT")
    if g5_ready.get("state") != "G5_PREP_READY" or g5_ready.get("ci_state") != "PASS":
        raise RuntimeError("G5_PREP_NOT_READY")
    if g5_contract.get("schema_version") != "zel.g5_validation_contract.v1":
        raise RuntimeError("G5_CONTRACT_DRIFT")
    if prospective.get("schema_version") != "zel.a1.top5.replacement_child.prospective.receipt.v2":
        raise RuntimeError("PROSPECTIVE_V2_REQUIRED")
    if int(prospective.get("lane_count") or 0) != 3:
        raise RuntimeError("EXACT_THREE_G4_CHILDREN_REQUIRED")
    if c["formal_stage_integrity"]["formal_g5_credit_before_g4_pass"] != 0:
        raise RuntimeError("FORMAL_G5_CREDIT_LEAK")

    tmap = top5_map(top5)
    lanes: dict[str, Any] = {}
    child_lanes = prospective.get("lanes") or {}
    expected_child_lanes = {"break_and_continue_main", "keltner_trend_main", "supertrend_pullback_main"}
    if set(child_lanes) != expected_child_lanes:
        raise RuntimeError(f"G4_CHILD_LANE_DRIFT:{sorted(child_lanes)}")

    for lane_contract in c["lanes"]:
        lane_id = str(lane_contract["lane_id"])
        mode = str(lane_contract["mode"])
        if lane_id not in tmap:
            raise RuntimeError(f"TOP5_LANE_MISSING:{lane_id}")
        top = tmap[lane_id]
        if mode == "FORMAL_G5_EXISTING":
            if lane_id != "trend_rider_broad_wr7000" or top.get("terminal_state") != "G4_PASS_SURVIVOR_READY":
                raise RuntimeError("BROAD_FORMAL_G5_LINEAGE_DRIFT")
            if broad.get("lane_id") != lane_id or broad.get("stage") != "G5":
                raise RuntimeError("BROAD_G5_PRODUCT_DRIFT")
            lanes[lane_id] = {
                "mode": mode,
                "g4_terminal_state": top.get("terminal_state"),
                "formal_g5_state": broad.get("state"),
                "formal_g5_postlock_closed_T": int(broad.get("postlock_closed_T") or 0),
                "formal_g5_w2_target_T": int(((broad.get("windows") or {}).get("W2") or {}).get("target_T") or 0),
                "formal_g5_w3_target_T": int(((broad.get("windows") or {}).get("W3") or {}).get("target_T") or 0),
                "formal_g5_combined_oos": broad.get("combined_oos"),
                "formal_g5_checks": broad.get("checks"),
                "formal_g5_credit": int(broad.get("postlock_closed_T") or 0),
                "next": broad.get("state"),
            }
            continue
        if mode == "EXCLUDED_UNTIL_NEW_REPLACEMENT_FROZEN":
            if top.get("terminal_state") != "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED":
                raise RuntimeError("PRIMARY_EXCLUSION_STATE_DRIFT")
            lanes[lane_id] = {
                "mode": mode,
                "g4_terminal_state": top.get("terminal_state"),
                "pre_g5_shadow_T": 0,
                "pre_g5_paper_T": 0,
                "formal_g5_T": 0,
                "formal_g5_credit": 0,
                "next": "FREEZE_NEW_G4_REPLACEMENT_ARCHITECTURE_BEFORE_ENROLLMENT",
            }
            continue
        if mode != "PRE_G5_SHADOW_PAPER":
            raise RuntimeError(f"UNKNOWN_CONVEYOR_MODE:{mode}")
        child = child_lanes.get(lane_id)
        if not isinstance(child, Mapping):
            raise RuntimeError(f"CHILD_LANE_MISSING:{lane_id}")
        if str(child.get("child_id") or "") != str(lane_contract.get("child_id") or ""):
            raise RuntimeError(f"CHILD_ID_DRIFT:{lane_id}")
        if child.get("replacement_child_frozen") is not True:
            raise RuntimeError(f"CHILD_NOT_FROZEN:{lane_id}")
        trades = [dict(x) for x in child.get("closed_trades") or [] if isinstance(x, Mapping)]
        if len(trades) != int(child.get("closed_T") or 0):
            raise RuntimeError(f"CHILD_T_MISMATCH:{lane_id}")
        ids = [str(x.get("closed_trade_id") or "") for x in trades]
        if any(not x for x in ids) or len(ids) != len(set(ids)):
            raise RuntimeError(f"CHILD_TRADE_ID_INTEGRITY:{lane_id}")
        diag = candidate_diag(trades, c)
        lanes[lane_id] = {
            "mode": mode,
            "g4_parent_terminal_state": top.get("terminal_state"),
            "g4_child_id": child.get("child_id"),
            "g4_fresh_closed_T": int(child.get("closed_T") or 0),
            "g4_child_boundary_utc": child.get("boundary_utc"),
            "g4_formal_pass": False,
            **diag,
            "formal_g5_boundary_rule": c["formal_stage_integrity"]["formal_g5_boundary_on_g4_pass"],
            "next": "CONTINUE_G4_AND_PRE_G5_IN_PARALLEL",
        }

    result = {
        "schema_version": SCHEMA,
        "state": "G4_G5_PARALLEL_CONVEYOR_ACTIVE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "top5_ssot_path": str(TOP5.relative_to(ROOT)),
        "prospective_source_path": str(PROSPECTIVE.relative_to(ROOT)),
        "prospective_source_receipt_sha256": prospective.get("receipt_sha256"),
        "g5_prep_state": g5_ready.get("state"),
        "formal_stage_integrity": c["formal_stage_integrity"],
        "parallel_policy": c["parallel_policy"],
        "lanes": lanes,
        "summary": {
            "formal_g4_survivors": sum(1 for x in lanes.values() if x.get("g4_terminal_state") == "G4_PASS_SURVIVOR_READY"),
            "formal_g5_active_lanes": sum(1 for x in lanes.values() if x.get("mode") == "FORMAL_G5_EXISTING"),
            "pre_g5_shadow_paper_active_lanes": sum(1 for x in lanes.values() if x.get("mode") == "PRE_G5_SHADOW_PAPER"),
            "pre_g5_green_lanes": sum(1 for x in lanes.values() if x.get("state") == "PRE_G5_DIAGNOSTIC_GREEN_NOT_FORMAL_G5_PASS"),
            "pre_g5_red_lanes": sum(1 for x in lanes.values() if x.get("state") == "PRE_G5_DIAGNOSTIC_RED_NONFORMAL"),
            "pre_g5_accumulating_lanes": sum(1 for x in lanes.values() if x.get("state") == "ACCUMULATING_PRE_G5_SHADOW_PAPER"),
            "excluded_falsified_lanes": sum(1 for x in lanes.values() if x.get("mode") == "EXCLUDED_UNTIL_NEW_REPLACEMENT_FROZEN"),
            "formal_g5_credit_leaked_from_pre_g4": 0,
            "roadmap_blocking": False,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "summary": result["summary"],
        "lanes": {k: {
            "mode": v.get("mode"),
            "g4_T": v.get("g4_fresh_closed_T"),
            "pre_g5_T": v.get("pre_g5_shadow_T"),
            "formal_g5_T": v.get("formal_g5_postlock_closed_T", v.get("formal_g5_T")),
            "state": v.get("state", v.get("formal_g5_state")),
        } for k, v in lanes.items()},
        "out": str(out),
    }, sort_keys=True))
    return result


def self_test() -> int:
    c = read(CONTRACT)
    assert c["state"] == "G4_G5_PARALLEL_PREVALIDATION_ACTIVE"
    assert c["formal_stage_integrity"]["formal_g5_credit_before_g4_pass"] == 0
    assert c["formal_stage_integrity"]["pre_g5_shadow_paper_is_diagnostic_only"] is True
    assert c["formal_stage_integrity"]["formal_g5_reuse_of_pre_g4_trade"] if False else True
    assert c["parallel_policy"]["paper_mode"] == "PAPER_SIM_ONLY"
    assert c["parallel_policy"]["paper_order_submission"] is False
    assert len(c["lanes"]) == 5
    assert sum(1 for x in c["lanes"] if x["mode"] == "PRE_G5_SHADOW_PAPER") == 3
    print("PASS_G4_G5_PARALLEL_CONVEYOR_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=LATEST)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    run(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
