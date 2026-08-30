#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_g4_recent_historical_accelerator_v1 as core
from backend.research.rebuild import a1_top5_g4_extended_historical_fasttrack_v1 as ext

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_g4_extended_historical_fasttrack_v1.json"
BREAK_SALVAGE_CONTRACT = ROOT / "backend/research/contracts/a1_break_reclaim_breakout_g4_fresh_v1.json"
BREAK_FRESH = ROOT / "backend/research/rebuild/a1_break_reclaim_breakout_g4_fresh_latest.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
V2_FRESH = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
SCHEMA = "zel.a1.top5.g4.extended_historical_fasttrack.receipt.v1"
PREP_SCHEMA = "zel.a1.top5.g5.fasttrack_prep.receipt.v1"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def load_shards(shard_dir: Path, lane_ids: list[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for p in shard_dir.rglob("*.json"):
        try:
            row = read(p)
        except Exception:
            continue
        lane_id = str(row.get("lane_id") or "")
        if lane_id in lane_ids and row.get("state") == "PASS_LANE_SHARD_COMPLETE":
            if lane_id in found:
                raise RuntimeError(f"DUPLICATE_LANE_SHARD:{lane_id}")
            found[lane_id] = row
    missing = [x for x in lane_ids if x not in found]
    if missing:
        raise RuntimeError("MISSING_LANE_SHARDS:" + ",".join(missing))
    return found


def run(shard_dir: Path, out: Path, prep_out: Path) -> dict[str, Any]:
    contract = read(CONTRACT)
    if contract.get("state") != "PREREGISTERED_BEFORE_RECENT_HISTORICAL_RESULTS":
        raise RuntimeError("FASTTRACK_CONTRACT_NOT_PREREGISTERED")
    lane_ids = list(contract["scope"]["include_lane_ids"])
    shards = load_shards(shard_dir, lane_ids)

    protected = (TOP5, V2_FRESH, BREAK_FRESH)
    before_hashes = {str(p.relative_to(ROOT)): core.file_sha(p) for p in protected}
    authority_sets = [x["fresh_authority_hashes_before"] for x in shards.values()]
    if any(x != authority_sets[0] for x in authority_sets[1:]):
        raise RuntimeError("SHARD_AUTHORITY_HASH_DRIFT")

    fast = contract["fasttrack_policy"]
    c3, c6 = fast["recent_3m"], fast["recent_6m"]
    lanes: dict[str, Any] = {}
    survivors: list[str] = []
    mixed: list[str] = []
    failed: list[str] = []
    transplant_candidates: list[dict[str, Any]] = []

    for lane_id in lane_ids:
        lane = shards[lane_id]
        trades = list(lane["trades"])
        m3 = ext.horizon_metrics(trades, c3["start_utc"], c3["end_utc"])
        m6 = ext.horizon_metrics(trades, c6["start_utc"], c6["end_utc"])
        p3m = ext.positive_month_count(lane["windows"], c3["start_utc"])
        p6m = ext.positive_month_count(lane["windows"], c6["start_utc"])
        p3, p6 = ext.horizon_pass(m3, c3, p3m), ext.horizon_pass(m6, c6, p6m)
        state = ext.classify_fasttrack(p3, p6)
        donor_status = "ROBUST_DONOR" if p3 and p6 else ("CONDITIONAL_DONOR" if p3 or p6 else "DO_NOT_TRANSPLANT_FROM_THIS_LANE")
        lanes[lane_id] = {
            "lane_id": lane_id,
            "architecture": lane["architecture"],
            "legacy_six_window_state": lane["legacy_six_window_state"],
            "recent_3m": {**m3, "positive_months": p3m, "gate_pass": p3},
            "recent_6m": {**m6, "positive_months": p6m, "gate_pass": p6},
            "fasttrack_state": state,
            "donor_status": donor_status,
            "fresh_g4_credit_T": 0,
            "g5_credit_T": 0,
            "fresh_confirmation_still_required_in_parallel": True,
            "source_shard_receipt_sha256": lane["receipt_sha256"],
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

    break_fresh = read(BREAK_FRESH)
    break_state = {
        "activation_id": break_fresh["activation_id"],
        "cohort_id": break_fresh["cohort_id"],
        "boundary_utc": break_fresh["prospective_boundary_utc"],
        "fresh_g4_T": break_fresh["fresh_g4_T"],
        "minimum_fresh_T_before_gate": break_fresh["minimum_fresh_T_before_gate"],
        "unchanged": True,
    }

    after_hashes = {str(p.relative_to(ROOT)): core.file_sha(p) for p in protected}
    if before_hashes != after_hashes:
        raise RuntimeError("FRESH_AUTHORITY_MUTATED_BY_SHARD_AGGREGATE")

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_G4_EXTENDED_3M_6M_FASTTRACK_COMPLETE",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_model": "FOUR_LANE_SHARDS_WITH_PERSISTED_ARTIFACTS_NO_FULL_RESTART_ON_SINGLE_LANE_FAILURE",
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": core.file_sha(CONTRACT),
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
        "break_salvage_fresh6": break_state,
        "fresh_authority_unchanged": True,
        "fresh_authority_hashes_before": before_hashes,
        "fresh_authority_hashes_after": after_hashes,
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
    p.add_argument("--shard-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--prep-out", required=True)
    a = p.parse_args()
    run(Path(a.shard_dir), Path(a.out), Path(a.prep_out))


if __name__ == "__main__":
    main()
