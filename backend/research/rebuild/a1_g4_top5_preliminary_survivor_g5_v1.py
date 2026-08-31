#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_g4_top5_preliminary_survivor_g5_v1.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
CONVEYOR = ROOT / "backend/research/rebuild/a1_g4_g5_parallel_conveyor_v1_latest.json"
OUT_DEFAULT = ROOT / "backend/research/rebuild/a1_g4_top5_preliminary_survivor_g5_v1_latest.json"
SCHEMA = "zel.a1.g4_top5.preliminary_survivor_g5.receipt.v1"
EXPECTED = {
    "trend_rider_primary_wr8125",
    "trend_rider_broad_wr7000",
    "break_and_continue_main",
    "keltner_trend_main",
    "supertrend_pullback_main",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def top5_map(top5: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = [dict(x) for x in top5.get("top5") or [] if isinstance(x, Mapping)]
    out = {str(x.get("lane_id") or ""): x for x in rows}
    if len(rows) != 5 or set(out) != EXPECTED:
        raise RuntimeError(f"EXACT_CURRENT_TOP5_DRIFT:{sorted(out)}")
    return out


def run(out: Path) -> dict[str, Any]:
    c = read(CONTRACT)
    top5 = read(TOP5)
    conveyor = read(CONVEYOR)
    if c.get("state") != "G4_TOP5_PRELIMINARY_SURVIVOR_G5_PARALLEL_ACTIVE":
        raise RuntimeError("CONTRACT_STATE_DRIFT")
    if conveyor.get("state") != "G4_G5_PARALLEL_CONVEYOR_ACTIVE":
        raise RuntimeError("BASE_CONVEYOR_NOT_ACTIVE")
    if conveyor.get("g5_prep_state") != "G5_PREP_READY":
        raise RuntimeError("G5_PREP_NOT_READY")
    if int(c["top5_policy"]["exact_top5_required"]) != 5:
        raise RuntimeError("TOP5_COUNT_POLICY_DRIFT")
    if int(c["parallel_policy"]["formal_g5_credit_before_formal_g4_pass"]) != 0:
        raise RuntimeError("FORMAL_G5_CREDIT_LEAK_POLICY")

    tmap = top5_map(top5)
    base_lanes = conveyor.get("lanes") or {}
    lanes: dict[str, Any] = {}

    for lane_id in sorted(EXPECTED):
        top = tmap[lane_id]
        base = dict(base_lanes.get(lane_id) or {})
        if lane_id != "trend_rider_primary_wr8125" and not base:
            raise RuntimeError(f"BASE_LANE_MISSING:{lane_id}")

        common = {
            "strategy": top.get("strategy"),
            "strategy_id": top.get("strategy_id"),
            "lane_id": lane_id,
            "roadmap_status": "PRELIMINARY_SURVIVOR_G5_ENROLLED",
            "roadmap_g4_complete_for_forward_progress": True,
            "formal_g4_terminal_state_preserved": top.get("terminal_state"),
            "formal_g4_pass": top.get("terminal_state") == "G4_PASS_SURVIVOR_READY",
            "formal_g5_pass": False,
            "formal_g5_credit_from_pre_g4": 0,
            "missing_g4_T_collects_in_parallel": lane_id in {
                "break_and_continue_main", "keltner_trend_main", "supertrend_pullback_main"
            },
            "selection_authority": False,
            "promotion_authority": False,
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        }

        if lane_id == "trend_rider_broad_wr7000":
            lanes[lane_id] = {
                **common,
                "g5_mode": "FORMAL_G5_EXISTING",
                "g5_state": base.get("formal_g5_state"),
                "formal_g5_T": int(base.get("formal_g5_postlock_closed_T") or 0),
                "formal_g5_w2_target_T": int(base.get("formal_g5_w2_target_T") or 0),
                "formal_g5_w3_target_T": int(base.get("formal_g5_w3_target_T") or 0),
                "combined_oos": base.get("formal_g5_combined_oos"),
                "checks": base.get("formal_g5_checks"),
                "next": base.get("next"),
            }
            continue

        if lane_id in {"break_and_continue_main", "keltner_trend_main", "supertrend_pullback_main"}:
            lanes[lane_id] = {
                **common,
                "g5_mode": "PRELIMINARY_G5_SHADOW_PAPER_WITH_G4_T_PARALLEL",
                "g5_state": base.get("state"),
                "g4_fresh_closed_T": int(base.get("g4_fresh_closed_T") or 0),
                "pre_g5_shadow_T": int(base.get("pre_g5_shadow_T") or 0),
                "pre_g5_paper_T": int(base.get("pre_g5_paper_T") or 0),
                "formal_g5_T": 0,
                "shadow_metrics": base.get("shadow_metrics"),
                "stress_cost_2x_metrics": base.get("stress_cost_2x_metrics"),
                "paper_sim": base.get("paper_sim"),
                "checks": base.get("checks"),
                "next_diagnostic_checkpoint_T": base.get("next_diagnostic_checkpoint_T"),
                "next": "CONTINUE_G4_DEFICIT_T_AND_G5_DIAGNOSTICS_IN_PARALLEL",
            }
            continue

        hist = top.get("historical_robustness_falsification") or {}
        lanes[lane_id] = {
            **common,
            "g5_mode": "PRELIMINARY_G5_DIAGNOSTIC_REPLACEMENT_REQUIRED",
            "g5_state": "G5_ENROLLED_WAIT_EXECUTABLE_REPLACEMENT_ARCHITECTURE",
            "g4_repair_axis_exhausted": top.get("terminal_state") == "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED",
            "g4_fresh_closed_T": 0,
            "pre_g5_shadow_T": 0,
            "pre_g5_paper_T": 0,
            "formal_g5_T": 0,
            "missing_g4_T_collects_in_parallel": False,
            "missing_T_parallel_state": "REPLACEMENT_ARCHITECTURE_REQUIRED_BEFORE_NEW_PROSPECTIVE_T",
            "historical_diagnostic_only": {
                "full6m_closed_T": hist.get("full6m_closed_T"),
                "full6m_net_pnl_bps": hist.get("full6m_net_pnl_bps"),
                "full6m_net_expectancy_bps": hist.get("full6m_net_expectancy_bps"),
                "full6m_profit_factor": hist.get("full6m_profit_factor"),
                "recent3m_closed_T": hist.get("recent3m_closed_T"),
                "recent3m_net_pnl_bps": hist.get("recent3m_net_pnl_bps"),
                "recent3m_net_expectancy_bps": hist.get("recent3m_net_expectancy_bps"),
                "recent3m_profit_factor": hist.get("recent3m_profit_factor"),
                "formal_credit": 0,
            },
            "next": "FREEZE_REPLACEMENT_ARCHITECTURE_WHILE_OTHER_G5_LANES_CONTINUE",
        }

    result = {
        "schema_version": SCHEMA,
        "state": "G4_TOP5_PRELIMINARY_SURVIVOR_G5_PARALLEL_ACTIVE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "roadmap_order": c["roadmap_order"],
        "current_transition": "G4_TO_G5",
        "current_stage": "G5",
        "g6_or_later_unlocked": False,
        "top5_ssot_path": str(TOP5.relative_to(ROOT)),
        "base_conveyor_path": str(CONVEYOR.relative_to(ROOT)),
        "lanes": lanes,
        "summary": {
            "exact_top5": 5,
            "preliminary_survivor_g5_enrolled": 5,
            "formal_g4_survivors": sum(1 for x in lanes.values() if x["formal_g4_pass"]),
            "formal_g5_active": sum(1 for x in lanes.values() if x["g5_mode"] == "FORMAL_G5_EXISTING"),
            "preliminary_g5_shadow_paper_active": sum(1 for x in lanes.values() if x["g5_mode"] == "PRELIMINARY_G5_SHADOW_PAPER_WITH_G4_T_PARALLEL"),
            "g4_deficit_T_parallel_collectors": sum(1 for x in lanes.values() if x["missing_g4_T_collects_in_parallel"]),
            "replacement_required_g5_enrolled": sum(1 for x in lanes.values() if x["g5_mode"] == "PRELIMINARY_G5_DIAGNOSTIC_REPLACEMENT_REQUIRED"),
            "formal_g5_credit_leaked_from_pre_g4": 0,
            "roadmap_blocking_on_missing_g4_T": False,
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
    print(json.dumps({"state": result["state"], "summary": result["summary"], "out": str(out)}, sort_keys=True))
    return result


def self_test() -> int:
    c = read(CONTRACT)
    assert c["current_transition"] == "G4_TO_G5"
    assert c["roadmap_order"][3].startswith("G4_") and c["roadmap_order"][4].startswith("G5_")
    assert c["top5_policy"]["roadmap_status_for_all_top5"] == "PRELIMINARY_SURVIVOR_G5_ENROLLED"
    assert c["top5_policy"]["missing_g4_T_collects_in_parallel"] is True
    assert c["top5_policy"]["g6_or_later_before_g5_terminal"] is False
    assert c["parallel_policy"]["paper_mode"] == "PAPER_SIM_ONLY"
    assert c["parallel_policy"]["paper_order_submission"] is False
    assert c["authority"]["order_authority"] == "BLOCKED"
    assert c["authority"]["live_trade_authority"] == "BLOCKED"
    print("PASS_G4_TOP5_PRELIMINARY_SURVIVOR_G5_CONTRACT")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    return self_test() if args.self_test else (run(args.out) and 0)


if __name__ == "__main__":
    raise SystemExit(main())
