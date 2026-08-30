#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as core

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_extended_historical_fasttrack_v1.json"
BREAK_SALVAGE_CONTRACT = ROOT / "backend/research/contracts/a1_break_reclaim_breakout_g4_fresh_v1.json"
SCHEMA = "zel.a1.top5.g4.extended_historical_fasttrack.receipt.v1"
PREP_SCHEMA = "zel.a1.top5.g5.fasttrack_prep.receipt.v1"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def horizon_metrics(trades: list[Mapping[str, Any]], start_utc: str, end_utc: str) -> dict[str, Any]:
    start_ms, end_ms = core.utc_ms(start_utc), core.utc_ms(end_utc)
    rows = core.window_rows(trades, start_ms, end_ms)
    days = (end_ms - start_ms) / 86_400_000.0
    return {"start_utc": start_utc, "end_utc": end_utc, **core.metrics(rows, days), "trade_ids": [x["trade_id"] for x in rows]}


def positive_month_count(windows: list[Mapping[str, Any]], start_utc: str) -> int:
    start_ms = core.utc_ms(start_utc)
    n = 0
    for row in windows:
        if core.utc_ms(str(row["start_utc"])) < start_ms:
            continue
        exp = row.get("net_expectancy_bps")
        if int(row.get("closed_T") or 0) > 0 and exp is not None and float(exp) > 0.0:
            n += 1
    return n


def horizon_pass(metrics: Mapping[str, Any], cfg: Mapping[str, Any], positive_months: int) -> bool:
    pf = metrics.get("profit_factor")
    pf_ok = bool(metrics.get("profit_factor_unbounded")) or (pf is not None and float(pf) > float(cfg["profit_factor_gt"]))
    return bool(
        int(metrics.get("closed_T") or 0) >= int(cfg["minimum_closed_T"])
        and float(metrics.get("net_pnl_bps") or 0.0) > float(cfg["net_pnl_bps_gt"])
        and metrics.get("net_expectancy_bps") is not None
        and float(metrics["net_expectancy_bps"]) > float(cfg["net_expectancy_bps_gt"])
        and pf_ok
        and positive_months >= int(cfg["minimum_positive_months"])
    )


def classify_fasttrack(p3: bool, p6: bool) -> str:
    if p3 and p6:
        return "G4_HISTORICAL_SURVIVOR_READY_FORWARD_DEFERRED"
    if p3 or p6:
        return "G4_HISTORICAL_MIXED_TRANSPLANT_DONOR_ONLY"
    return "G4_FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED"


def self_test() -> None:
    cfg = {"minimum_closed_T": 18, "net_pnl_bps_gt": 0.0, "net_expectancy_bps_gt": 0.0, "profit_factor_gt": 1.0, "minimum_positive_months": 2}
    ok = {"closed_T": 20, "net_pnl_bps": 100.0, "net_expectancy_bps": 5.0, "profit_factor": 1.2, "profit_factor_unbounded": False}
    bad = {"closed_T": 20, "net_pnl_bps": -1.0, "net_expectancy_bps": -0.05, "profit_factor": 0.9, "profit_factor_unbounded": False}
    assert horizon_pass(ok, cfg, 2)
    assert not horizon_pass(ok, cfg, 1)
    assert not horizon_pass(bad, cfg, 3)
    assert classify_fasttrack(True, True) == "G4_HISTORICAL_SURVIVOR_READY_FORWARD_DEFERRED"
    assert classify_fasttrack(True, False) == "G4_HISTORICAL_MIXED_TRANSPLANT_DONOR_ONLY"
    assert classify_fasttrack(False, False) == "G4_FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED"
    print("PASS_A1_TOP5_G4_EXTENDED_HISTORICAL_FASTTRACK_V1_SELF_TEST")


def run(base_out: Path, base_escrow: Path, out: Path, prep_out: Path) -> dict[str, Any]:
    contract = read(CONTRACT)
    if contract.get("state") != "PREREGISTERED_BEFORE_RECENT_HISTORICAL_RESULTS":
        raise RuntimeError("FASTTRACK_CONTRACT_NOT_PREREGISTERED")
    if contract["evidence_semantics"].get("historical_trade_credit_to_fresh_g4_T") != 0:
        raise RuntimeError("HISTORICAL_FRESH_CREDIT_FORBIDDEN")
    if contract["fasttrack_policy"].get("no_post_result_threshold_change") is not True:
        raise RuntimeError("FASTTRACK_POLICY_MUST_BE_FROZEN")

    core.CONTRACT = CONTRACT
    core.SCHEMA = "zel.a1.top5.g4.extended_historical_base.receipt.v1"
    core.ESCROW_SCHEMA = "zel.a1.top5.g5.extended_historical_base_escrow.v1"
    base = core.run(base_out, base_escrow)

    fast = contract["fasttrack_policy"]
    c3, c6 = fast["recent_3m"], fast["recent_6m"]
    lanes: dict[str, Any] = {}
    survivors: list[str] = []
    mixed: list[str] = []
    failed: list[str] = []
    transplant_candidates: list[dict[str, Any]] = []

    for lane_id, lane in base["lanes"].items():
        trades = list(lane["trades"])
        m3 = horizon_metrics(trades, c3["start_utc"], c3["end_utc"])
        m6 = horizon_metrics(trades, c6["start_utc"], c6["end_utc"])
        p3m = positive_month_count(lane["windows"], c3["start_utc"])
        p6m = positive_month_count(lane["windows"], c6["start_utc"])
        p3, p6 = horizon_pass(m3, c3, p3m), horizon_pass(m6, c6, p6m)
        state = classify_fasttrack(p3, p6)
        donor_status = "ROBUST_DONOR" if p3 and p6 else ("CONDITIONAL_DONOR" if p3 or p6 else "DO_NOT_TRANSPLANT_FROM_THIS_LANE")
        lanes[lane_id] = {
            "lane_id": lane_id,
            "architecture": lane["architecture"],
            "legacy_six_window_state": lane["state"],
            "recent_3m": {**m3, "positive_months": p3m, "gate_pass": p3},
            "recent_6m": {**m6, "positive_months": p6m, "gate_pass": p6},
            "fasttrack_state": state,
            "donor_status": donor_status,
            "fresh_g4_credit_T": 0,
            "g5_credit_T": 0,
            "fresh_confirmation_still_required_in_parallel": True,
        }
        if state == "G4_HISTORICAL_SURVIVOR_READY_FORWARD_DEFERRED":
            survivors.append(lane_id)
        elif state == "G4_HISTORICAL_MIXED_TRANSPLANT_DONOR_ONLY":
            mixed.append(lane_id)
        else:
            failed.append(lane_id)
        if donor_status != "DO_NOT_TRANSPLANT_FROM_THIS_LANE":
            for module in contract["donor_module_registry"].get(lane_id, []):
                transplant_candidates.append({
                    "source_lane_id": lane_id,
                    "module": module,
                    "donor_status": donor_status,
                    "parent_specific_replay_required": True,
                    "rr_exit_must_remain_parent_native": True,
                })

    salvage = read(BREAK_SALVAGE_CONTRACT)
    dev = salvage.get("source_development", {})
    if dev.get("state") == "PASS_DEVELOPMENT_ELIGIBLE_FOR_NEW_G4_CHALLENGER":
        for module in contract["donor_module_registry"].get("break_salvage_independent", []):
            transplant_candidates.append({
                "source_lane_id": "break_salvage_independent",
                "module": module,
                "donor_status": "INDEPENDENT_DEVELOPMENT_DONOR_FRESH6_PENDING",
                "development_metrics": dev.get("development_metrics"),
                "parent_specific_replay_required": True,
                "rr_exit_must_remain_parent_native": True,
            })

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_G4_EXTENDED_3M_6M_FASTTRACK_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": core.file_sha(CONTRACT),
        "base_accelerator_receipt_sha256": base["receipt_sha256"],
        "base_master_sha": contract["base_master_sha"],
        "lane_count": len(lanes),
        "lanes": lanes,
        "historical_survivor_lane_ids": survivors,
        "mixed_donor_lane_ids": mixed,
        "architecture_replacement_lane_ids": failed,
        "transplant_candidates": transplant_candidates,
        "transplant_candidate_count": len(transplant_candidates),
        "fasttrack_semantics": {
            "historical_survivor_label": fast["terminal_label"],
            "legacy_fresh_g4_pass_not_claimed": True,
            "next_roadmap_prep_or_shadow_allowed_for_historical_survivor": True,
            "fresh_collectors_continue_unchanged": True,
            "fresh_failure_invalidates_fasttrack_survivor": True,
            "historical_credit_to_fresh_g4_T": 0,
            "historical_credit_to_g5_T": 0,
        },
        "break_salvage_fresh6": base["break_salvage_fresh6"],
        "fresh_authority_unchanged": base["fresh_authority_unchanged"],
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["deterministic_result_sha256"] = core.stable({k: v for k, v in result.items() if k not in {"observed_at_utc", "receipt_sha256", "deterministic_result_sha256"}})
    result["receipt_sha256"] = core.stable({k: v for k, v in result.items() if k != "receipt_sha256"})

    prep_entries = {
        lane_id: {
            "state": "G5_OR_NEXT_ROADMAP_PREP_ALLOWED_HISTORICAL_FASTTRACK",
            "lane_id": lane_id,
            "source_fasttrack_receipt_sha256": result["receipt_sha256"],
            "legacy_fresh_g4_pass_claimed": False,
            "fresh_confirmation_continues_in_parallel": True,
            "invalid_if_fresh_confirmation_fails": True,
            "formal_g5_T": 0,
            "historical_credit_to_g5_T": 0,
            "activation_id": None,
            "cohort_id": None,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }
        for lane_id in survivors
    }
    prep = {
        "schema_version": PREP_SCHEMA,
        "state": "FASTTRACK_PREP_READY" if prep_entries else "NO_FASTTRACK_SURVIVOR",
        "entries": prep_entries,
        "source_fasttrack_receipt_sha256": result["receipt_sha256"],
        "transplant_candidates": transplant_candidates,
        "fresh_g4_credit_T": 0,
        "formal_g5_T": 0,
        "historical_credit_to_g5_T": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    prep["receipt_sha256"] = core.stable(prep)

    out.parent.mkdir(parents=True, exist_ok=True)
    prep_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    prep_out.write_text(json.dumps(prep, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "historical_survivors": survivors,
        "mixed_donors": mixed,
        "architecture_replacement": failed,
        "transplant_candidate_count": len(transplant_candidates),
        "lane_summary": {k: {"state": v["fasttrack_state"], "m3": v["recent_3m"], "m6": v["recent_6m"]} for k, v in lanes.items()},
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-out", default="out/a1_top5_g4_extended_historical_base_v1.json")
    p.add_argument("--base-escrow", default="out/a1_top5_g4_extended_historical_base_escrow_v1.json")
    p.add_argument("--out", default="out/a1_top5_g4_extended_historical_fasttrack_v1.json")
    p.add_argument("--prep-out", default="out/a1_top5_g5_fasttrack_prep_v1.json")
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        self_test()
        return
    run(Path(a.base_out), Path(a.base_escrow), Path(a.out), Path(a.prep_out))


if __name__ == "__main__":
    main()
