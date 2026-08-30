#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
REPLAY = ROOT / "backend/research/rebuild/a1_top5_entry_transplant_replay_latest.json"
CONTRACT = ROOT / "backend/research/contracts/a1_top5_entry_transplant_replay_v1.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
DEFAULT_OUT = ROOT / "backend/research/rebuild/a1_top5_entry_transplant_terminal_latest.json"
SCHEMA = "zel.a1.top5.entry_transplant_terminal.v1"
TERMINAL_STATE = "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED"
TERMINAL_SCOPE = "TOP5_X_FROZEN_V2_ENTRY_TRANSPLANT_PATH_ONLY"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def metric_summary(cell: Mapping[str, Any]) -> dict[str, Any]:
    m = cell.get("metrics") or {}
    return {
        "rank": int(cell.get("rank") or 0),
        "parent_rank": int(cell.get("parent_rank") or 0),
        "parent_lane_id": str(cell.get("parent_lane_id") or ""),
        "parent_strategy_id": str(cell.get("parent_strategy_id") or ""),
        "architecture_id": str(cell.get("architecture_id") or ""),
        "architecture_family": str(cell.get("architecture_family") or ""),
        "T": int(m.get("trades") or 0),
        "wins": int(m.get("wins") or 0),
        "losses": int(m.get("losses") or 0),
        "win_rate": m.get("win_rate"),
        "net_pnl_bps": float(m.get("net_pnl_bps") or 0.0),
        "net_expectancy_bps": m.get("net_expectancy_bps"),
        "profit_factor": m.get("profit_factor"),
        "payoff": m.get("payoff"),
        "drawdown_bps": float(m.get("drawdown_bps") or 0.0),
        "retention_pct": float(cell.get("retention_pct") or 0.0),
        "rejected_T": int(cell.get("rejected_T") or 0),
        "rejected_wins": int(cell.get("rejected_wins") or 0),
        "rejected_losses": int(cell.get("rejected_losses") or 0),
        "win_rate_harm_pp": float(cell.get("win_rate_harm_pp") or 0.0),
        "economic_improvement": bool((cell.get("selection_checks") or {}).get("economic_improvement")),
        "failed_selection_checks": list(cell.get("failed_selection_checks") or []),
        "eligible": bool(cell.get("eligible")),
        "decision": str(cell.get("decision") or ""),
        "experiment_id": str(cell.get("experiment_id") or ""),
    }


def validate_inputs(replay: Mapping[str, Any], contract: Mapping[str, Any], top5: Mapping[str, Any]) -> list[dict[str, Any]]:
    if replay.get("schema_version") != "zel.a1.top5.entry_transplant_replay.receipt.v1":
        raise RuntimeError("REPLAY_SCHEMA_DRIFT")
    if replay.get("state") != "FALSIFIED_NO_ELIGIBLE_TRANSPLANT_WINNER":
        raise RuntimeError(f"REPLAY_NOT_NO_WINNER_TERMINAL:{replay.get('state')}")
    integrity = replay.get("integrity") or {}
    if integrity.get("state") != "PASS":
        raise RuntimeError("REPLAY_INTEGRITY_NOT_PASS")
    expected = int(contract.get("expected_cell_count") or 0)
    cells = [dict(x) for x in replay.get("cells") or [] if isinstance(x, Mapping)]
    if expected != 15 or len(cells) != expected or int(replay.get("cell_count") or 0) != expected:
        raise RuntimeError(f"EXACT_15_CELL_REPLAY_REQUIRED:{expected}:{len(cells)}:{replay.get('cell_count')}")
    if int(replay.get("eligible_cell_count") or 0) != 0:
        raise RuntimeError("ELIGIBLE_CELL_EXISTS_DO_NOT_FALSIFY")
    if replay.get("winner") is not None:
        raise RuntimeError("WINNER_EXISTS_DO_NOT_FALSIFY")
    if any(bool(x.get("eligible")) for x in cells):
        raise RuntimeError("CELL_ELIGIBILITY_MISMATCH")
    if any(str(x.get("decision") or "") != "REPLAY_REJECT" for x in cells):
        raise RuntimeError("NON_REJECT_CELL_WITHOUT_WINNER")
    if not replay.get("deterministic_result_sha256"):
        raise RuntimeError("DETERMINISTIC_RESULT_HASH_REQUIRED")
    wp = contract.get("winner_policy") or {}
    if not bool(wp.get("no_eligible_cell_means_no_winner")):
        raise RuntimeError("WINNER_POLICY_DRIFT")
    top = [x for x in top5.get("top5") or [] if isinstance(x, Mapping)]
    if len(top) != 5:
        raise RuntimeError("CURRENT_TOP5_EXACTLY_5_REQUIRED")
    replay_lanes = {str(x.get("parent_lane_id") or "") for x in cells}
    ssot_lanes = {str(x.get("lane_id") or "") for x in top}
    if replay_lanes != ssot_lanes:
        raise RuntimeError(f"TOP5_REPLAY_LANE_DRIFT:{sorted(replay_lanes)}:{sorted(ssot_lanes)}")
    return cells


def build_terminal(
    replay: Mapping[str, Any], contract: Mapping[str, Any], top5: Mapping[str, Any], *, source_master_sha: str
) -> dict[str, Any]:
    cells = validate_inputs(replay, contract, top5)
    summaries = sorted((metric_summary(x) for x in cells), key=lambda x: (x["rank"], x["parent_rank"], x["architecture_id"]))
    failed_gate_counts: Counter[str] = Counter()
    failed_gate_by_parent: dict[str, Counter[str]] = defaultdict(Counter)
    for row in summaries:
        for gate in row["failed_selection_checks"]:
            failed_gate_counts[str(gate)] += 1
            failed_gate_by_parent[row["parent_lane_id"]][str(gate)] += 1

    best = summaries[0] if summaries else None
    terminal: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": TERMINAL_STATE,
        "scope": TERMINAL_SCOPE,
        "observed_at_utc": now_utc(),
        "source_master_sha": source_master_sha,
        "reason": "NO_ELIGIBLE_TRANSPLANT_WINNER_AFTER_COMPLETE_DETERMINISTIC_15_CELL_REPLAY",
        "replay": {
            "path": str(REPLAY.relative_to(ROOT)),
            "file_sha256": file_sha(REPLAY),
            "receipt_sha256": replay.get("receipt_sha256"),
            "deterministic_result_sha256": replay.get("deterministic_result_sha256"),
            "state": replay.get("state"),
            "integrity_state": (replay.get("integrity") or {}).get("state"),
            "cell_count": len(cells),
            "eligible_cell_count": 0,
            "winner": None,
        },
        "selection_contract": {
            "path": str(CONTRACT.relative_to(ROOT)),
            "file_sha256": file_sha(CONTRACT),
            "frozen_before_results": bool((contract.get("selection_rule") or {}).get("frozen_before_results")),
            "selection_rule": copy.deepcopy(contract.get("selection_rule") or {}),
        },
        "cell_results": summaries,
        "failure_summary": {
            "failed_gate_counts_across_15_cells": dict(sorted(failed_gate_counts.items())),
            "failed_gate_counts_by_parent": {
                lane: dict(sorted(counts.items())) for lane, counts in sorted(failed_gate_by_parent.items())
            },
            "best_ranked_rejected_cell": best,
            "sample_collapse_detected": bool(best and (best["T"] < int((contract.get("selection_rule") or {}).get("minimum_closed_T") or 0))),
            "no_eligible_winner": True,
        },
        "g4_outcome": {
            "g4_pass_credit": 0,
            "historical_replay_is_not_g4_pass": True,
            "winner_freeze_created": False,
            "activation_id": None,
            "cohort_id": None,
            "prospective_boundary": None,
            "fresh_closed_T": 0,
            "wait_new_t_allowed": False,
            "wait_new_t_forbidden_reason": "NO_ARMED_WINNER_COHORT_EXISTS; REPLAY_COMPLETED_WITH_ZERO_ELIGIBLE_WINNERS",
            "architecture_replacement_required": True,
            "next": "STOP_THIS_TRANSPLANT_PATH; DO_NOT_CREATE_G4_ACTIVATION_FROM_A_REJECTED_CELL",
        },
        "work_goal_status": {
            "latest_master_top5_v2_g4_authority_and_duplicate_replay_check": "COMPLETE",
            "transplant_replay_contract_runner_ci_implementation_and_verification": "COMPLETE",
            "pr_ci_15_of_15_result_recovery_and_winner_decision": "COMPLETE_NO_ELIGIBLE_WINNER",
            "winner_freeze_and_new_g4_activation_cohort_collector": "NOT_APPLICABLE_NO_ELIGIBLE_WINNER",
            "fresh_closed_t_gate_and_terminal_receipt_ssot_commit": "TERMINAL_COMPLETE_WITHOUT_ACTIVATION",
        },
        "scope_guards": {
            "does_not_override_existing_per_lane_g4_terminal_states": True,
            "does_not_revoke_existing_trendrider_broad_g4_survivor": True,
            "does_not_consume_or_reset_existing_v2_prospective_collectors": True,
            "does_not_modify_g5": True,
            "does_not_modify_rr_or_exit": True,
            "does_not_modify_live_paper_order_execution": True,
            "historical_backfill_forbidden": True,
            "rejected_cell_activation_forbidden": True,
            "post_result_threshold_retune_forbidden": True,
        },
        **AUTH,
    }
    terminal["receipt_sha256"] = stable(terminal)
    return terminal


def sync_ssot(top5: Mapping[str, Any], terminal: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(top5))
    policy = out.setdefault("record_policy", {})
    policy["entry_transplant_replay_is_not_g4_pass"] = True
    policy["no_eligible_transplant_winner_forbids_new_g4_activation"] = True
    policy["wait_new_t_requires_armed_prospective_cohort"] = True
    policy["rejected_transplant_cell_must_not_be_promoted"] = True
    out["entry_transplant_replay_sync"] = {
        "state": TERMINAL_STATE,
        "scope": TERMINAL_SCOPE,
        "source_replay_path": str(REPLAY.relative_to(ROOT)),
        "source_replay_state": terminal["replay"]["state"],
        "source_deterministic_result_sha256": terminal["replay"]["deterministic_result_sha256"],
        "terminal_receipt_path": str(DEFAULT_OUT.relative_to(ROOT)),
        "terminal_receipt_sha256": terminal["receipt_sha256"],
        "cell_count": terminal["replay"]["cell_count"],
        "eligible_cell_count": 0,
        "winner": None,
        "g4_activation_created": False,
        "cohort_created": False,
        "fresh_closed_t_gate_applicable": False,
        "wait_new_t_allowed": False,
        "terminal_reason": terminal["reason"],
        "best_ranked_rejected_cell": copy.deepcopy(terminal["failure_summary"]["best_ranked_rejected_cell"]),
        "work_goal_status": copy.deepcopy(terminal["work_goal_status"]),
        "does_not_override_existing_per_lane_g4_terminal_states": True,
        "does_not_revoke_existing_trendrider_broad_g4_survivor": True,
        "does_not_consume_or_reset_existing_v2_prospective_collectors": True,
        "selection_authority": False,
        "promotion_authority": False,
    }
    return out


def self_test() -> None:
    contract = {
        "expected_cell_count": 15,
        "winner_policy": {"no_eligible_cell_means_no_winner": True},
        "selection_rule": {"frozen_before_results": True, "minimum_closed_T": 6},
    }
    lanes = [f"lane{i}" for i in range(5)]
    cells = []
    rank = 1
    for lane in lanes:
        for arch in range(3):
            cells.append({
                "rank": rank,
                "parent_rank": lanes.index(lane) + 1,
                "parent_lane_id": lane,
                "parent_strategy_id": lane,
                "architecture_id": f"arch{arch}",
                "architecture_family": f"family{arch}",
                "metrics": {"trades": 2, "wins": 2, "losses": 0, "net_pnl_bps": 10.0, "drawdown_bps": 0.0},
                "retention_pct": 20.0,
                "rejected_T": 7,
                "rejected_wins": 3,
                "rejected_losses": 4,
                "win_rate_harm_pp": 0.0,
                "selection_checks": {"economic_improvement": True},
                "failed_selection_checks": ["sample_minimum", "retention_minimum"],
                "eligible": False,
                "decision": "REPLAY_REJECT",
                "experiment_id": f"e{rank}",
            })
            rank += 1
    replay = {
        "schema_version": "zel.a1.top5.entry_transplant_replay.receipt.v1",
        "state": "FALSIFIED_NO_ELIGIBLE_TRANSPLANT_WINNER",
        "integrity": {"state": "PASS"},
        "cell_count": 15,
        "eligible_cell_count": 0,
        "winner": None,
        "deterministic_result_sha256": "abc",
        "cells": cells,
    }
    top5 = {"top5": [{"lane_id": x} for x in lanes], "record_policy": {}}

    # Use a local builder surrogate because production builder hashes repository files.
    validate_inputs(replay, contract, top5)
    bad = copy.deepcopy(replay)
    bad["eligible_cell_count"] = 1
    try:
        validate_inputs(bad, contract, top5)
    except RuntimeError as exc:
        if "ELIGIBLE_CELL_EXISTS" not in str(exc):
            raise
    else:
        raise RuntimeError("SELF_TEST_EXPECTED_ELIGIBLE_REJECTION")
    print("PASS_A1_TOP5_ENTRY_TRANSPLANT_TERMINAL_V1_SELF_TEST")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--ssot-out", type=Path, default=TOP5)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0

    replay, contract, top5 = read(REPLAY), read(CONTRACT), read(TOP5)
    terminal = build_terminal(replay, contract, top5, source_master_sha=git_head())
    synced = sync_ssot(top5, terminal)
    if not args.dry_run:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(terminal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.ssot_out.write_text(json.dumps(synced, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": terminal["state"],
        "scope": terminal["scope"],
        "cell_count": terminal["replay"]["cell_count"],
        "eligible_cell_count": terminal["replay"]["eligible_cell_count"],
        "winner": terminal["replay"]["winner"],
        "best_ranked_rejected_cell": terminal["failure_summary"]["best_ranked_rejected_cell"],
        "failed_gate_counts": terminal["failure_summary"]["failed_gate_counts_across_15_cells"],
        "activation_id": terminal["g4_outcome"]["activation_id"],
        "cohort_id": terminal["g4_outcome"]["cohort_id"],
        "wait_new_t_allowed": terminal["g4_outcome"]["wait_new_t_allowed"],
        "receipt_sha256": terminal["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
