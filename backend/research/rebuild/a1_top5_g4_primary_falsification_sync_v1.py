#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "backend/research/rebuild/a1_top5_g4_primary_donor_decomposition_v1_latest.json"
TERMINAL = ROOT / "backend/research/rebuild/a1_top5_g4_terminal_latest.json"
SSOT = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
MERGED_EVIDENCE_SHA = "59ac8075f2cc57c2cac8548794d21265daec71fb"


def read(path: Path) -> dict[str, Any]:
    v = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(v, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return v


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=False, allow_nan=False) + "\n", encoding="utf-8")


def apply() -> tuple[dict[str, Any], dict[str, Any]]:
    e = read(EVIDENCE)
    t = read(TERMINAL)
    s = read(SSOT)
    if e.get("state") != "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED" or int(e.get("winner_count") or -1) != 0:
        raise RuntimeError("PRIMARY_FALSIFICATION_EVIDENCE_NOT_FINAL")
    if int((e.get("parent_metrics_6m") or {}).get("closed_T") or 0) != 224:
        raise RuntimeError("PRIMARY_224T_EVIDENCE_REQUIRED")
    if float((e.get("parent_metrics_recent3m") or {}).get("net_pnl_bps") or 0.0) >= 0:
        raise RuntimeError("PRIMARY_RECENT3M_FAILURE_REQUIRED")
    if e.get("formal_credit") != {"fresh_g4_T": 0, "g5_T": 0}:
        raise RuntimeError("FORMAL_CREDIT_DRIFT")

    targets = [x for x in t.get("targets") or [] if isinstance(x, dict)]
    primary = next((x for x in targets if x.get("strategy") == "TrendRider Primary"), None)
    if primary is None:
        raise RuntimeError("TERMINAL_PRIMARY_MISSING")
    if primary.get("terminal_state") not in {"WAIT_NEW_T", "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED"}:
        raise RuntimeError(f"UNEXPECTED_PRIMARY_TERMINAL:{primary.get('terminal_state')}")
    primary.update({
        "supersedes_terminal_state": "WAIT_NEW_T",
        "terminal_state": "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED",
        "historical_robustness_evidence_path": str(EVIDENCE.relative_to(ROOT)),
        "historical_robustness_evidence_merged_sha": MERGED_EVIDENCE_SHA,
        "historical_robustness_closed_T": int(e["parent_metrics_6m"]["closed_T"]),
        "historical_robustness_net_pnl_bps": float(e["parent_metrics_6m"]["net_pnl_bps"]),
        "historical_robustness_profit_factor": e["parent_metrics_6m"].get("profit_factor"),
        "recent3m_closed_T": int(e["parent_metrics_recent3m"]["closed_T"]),
        "recent3m_net_pnl_bps": float(e["parent_metrics_recent3m"]["net_pnl_bps"]),
        "recent3m_net_expectancy_bps": float(e["parent_metrics_recent3m"]["net_expectancy_bps"]),
        "recent3m_profit_factor": e["parent_metrics_recent3m"].get("profit_factor"),
        "fixed_donor_decomposition_cells": int(e["cell_count"]),
        "fixed_donor_decomposition_winners": int(e["winner_count"]),
        "root_cause": "ROBUST_HISTORICAL_ECONOMIC_FAILURE_PLUS_FIXED_DONOR_DECOMPOSITION_EXHAUSTED",
        "salvageable_now": False,
        "why_not_wait_new_t": "WAIT_NEW_T_NO_LONGER_JUSTIFIED_AFTER_224T_HISTORICAL_ROBUSTNESS_REPLAY_SHOWED_RECENT3M_ECONOMIC_COLLAPSE_AND_0_OF_4_PREREGISTERED_DONOR_CELLS_PASSED",
        "next": "ARCHITECTURE_REPLACEMENT_DO_NOT_WAIT_FOR_MORE_PRIMARY_PARENT_T"
    })
    t["source_master_sha"] = MERGED_EVIDENCE_SHA
    t["state"] = "G4_TERMINAL_TARGET_SET_COMPLETE"
    summary = t.setdefault("summary", {})
    summary["target_g4_pass_survivor_ready"] = 0
    summary["target_wait_new_t"] = sum(1 for x in targets if x.get("terminal_state") == "WAIT_NEW_T")
    summary["target_architecture_replacement_required"] = sum(1 for x in targets if x.get("terminal_state") == "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED")
    summary["unresolved"] = 0
    t["primary_falsification_sync"] = {
        "state": "SYNCED",
        "evidence_path": str(EVIDENCE.relative_to(ROOT)),
        "evidence_state": e["state"],
        "winner_count": int(e["winner_count"]),
        "formal_credit": e["formal_credit"],
        "fresh_6T_is_not_automatic_pass": bool(e["fresh_6T_is_not_automatic_pass"]),
        "historical_evidence_used_for_falsification_not_promotion": True
    }

    top5 = [x for x in s.get("top5") or [] if isinstance(x, dict)]
    sp = next((x for x in top5 if x.get("lane_id") == "trend_rider_primary_wr8125"), None)
    if sp is None:
        raise RuntimeError("SSOT_PRIMARY_MISSING")
    if sp.get("terminal_state") not in {"WAIT_NEW_T", "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED"}:
        raise RuntimeError(f"UNEXPECTED_SSOT_PRIMARY:{sp.get('terminal_state')}")
    sp.pop("fresh_to_25", None)
    sp.update({
        "current_role": "ARCHITECTURE_REPLACEMENT_REQUIRED",
        "terminal_state": "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED",
        "terminal_reason": "ROBUST_HISTORICAL_ECONOMIC_FAILURE_PLUS_FIXED_DONOR_DECOMPOSITION_EXHAUSTED",
        "terminal_source_path": str(TERMINAL.relative_to(ROOT)),
        "survivor": False,
        "historical_robustness_falsification": {
            "source_path": str(EVIDENCE.relative_to(ROOT)),
            "source_merged_sha": MERGED_EVIDENCE_SHA,
            "full6m_closed_T": int(e["parent_metrics_6m"]["closed_T"]),
            "full6m_net_pnl_bps": float(e["parent_metrics_6m"]["net_pnl_bps"]),
            "full6m_net_expectancy_bps": float(e["parent_metrics_6m"]["net_expectancy_bps"]),
            "full6m_profit_factor": e["parent_metrics_6m"].get("profit_factor"),
            "recent3m_closed_T": int(e["parent_metrics_recent3m"]["closed_T"]),
            "recent3m_net_pnl_bps": float(e["parent_metrics_recent3m"]["net_pnl_bps"]),
            "recent3m_net_expectancy_bps": float(e["parent_metrics_recent3m"]["net_expectancy_bps"]),
            "recent3m_profit_factor": e["parent_metrics_recent3m"].get("profit_factor"),
            "donor_cells": int(e["cell_count"]),
            "donor_winners": int(e["winner_count"]),
            "formal_credit": e["formal_credit"],
            "interpretation": "FALSIFICATION_ONLY_NOT_G4_PROMOTION_EVIDENCE"
        },
        "next": "ARCHITECTURE_REPLACEMENT_DO_NOT_WAIT_FOR_MORE_PRIMARY_PARENT_T"
    })
    s.setdefault("record_policy", {})["primary_224T_historical_robustness_can_falsify_but_not_promote"] = True
    s["record_policy"]["primary_donor_decomposition_zero_winner_forbids_wait_new_t_as_resolution"] = True
    s["g4_terminal_sync"] = {
        "state": "SYNCED_PRIMARY_FALSIFICATION_COMPLETE",
        "source_path": str(TERMINAL.relative_to(ROOT)),
        "source_terminal_state": t["state"],
        "primary_terminal_state": sp["terminal_state"],
        "unresolved": 0,
        "stale_rescue_pending_allowed": False,
        "evidence_path": str(EVIDENCE.relative_to(ROOT))
    }

    if int(t["summary"]["target_wait_new_t"]) != 0:
        raise RuntimeError("WAIT_NEW_T_REMAINS_AFTER_PRIMARY_FALSIFICATION")
    if int(t["summary"]["target_architecture_replacement_required"]) != 5:
        raise RuntimeError("EXPECTED_FIVE_REPLACEMENT_TARGETS")
    if sp["terminal_state"] != "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED":
        raise RuntimeError("SSOT_SYNC_FAILED")
    return t, s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.apply:
        e = read(EVIDENCE)
        assert e["state"] == "FALSIFIED_ARCHITECTURE_REPLACEMENT_REQUIRED"
        assert e["winner_count"] == 0
        assert e["fresh_6T_is_not_automatic_pass"] is True
        print("PASS_PRIMARY_FALSIFICATION_SYNC_SELF_TEST")
        return 0
    t, s = apply()
    write(TERMINAL, t)
    write(SSOT, s)
    print(json.dumps({
        "terminal_primary": next(x for x in t["targets"] if x.get("strategy") == "TrendRider Primary")["terminal_state"],
        "wait_new_t": t["summary"]["target_wait_new_t"],
        "replacement_required": t["summary"]["target_architecture_replacement_required"],
        "ssot_primary": next(x for x in s["top5"] if x.get("lane_id") == "trend_rider_primary_wr8125")["terminal_state"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
