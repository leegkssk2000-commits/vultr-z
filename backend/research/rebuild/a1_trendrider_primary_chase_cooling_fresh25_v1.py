#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/rebuild/a1_trendrider_primary_chase_cooling_fresh25_contract_v1.json"
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
FRESH2 = ROOT / "backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json"
LOSS = ROOT / "backend/research/rebuild/a1_recent_loss_cluster_actionable_latest.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
SCHEMA = "zel.a1.trendrider.primary.chase_cooling_fresh25.v1"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def key(row: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return str(row["symbol"]), int(row["signal_ts"]), int(row["entry_ts"]), str(row["side"])


def metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in rows]
    if not vals:
        return {"trades": 0, "net_pnl_bps": 0.0, "net_expectancy_bps": None, "profit_factor": None, "profit_factor_unbounded": False, "win_rate": None, "drawdown_bps": 0.0}
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp, gl = sum(wins), sum(losses)
    eq = peak = worst = 0.0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        worst = max(worst, peak - eq)
    return {
        "trades": len(vals),
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals),
        "profit_factor": gp / gl if gl > 0 else None,
        "profit_factor_unbounded": bool(gp > 0 and gl == 0),
        "win_rate": len(wins) / len(vals),
        "drawdown_bps": worst,
    }


def payoff(rows: list[Mapping[str, Any]]) -> float | None:
    wins = [float(x["net_bps"]) for x in rows if float(x["net_bps"]) > 0]
    losses = [-float(x["net_bps"]) for x in rows if float(x["net_bps"]) < 0]
    if not wins or not losses:
        return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def strict(parent: list[dict[str, Any]], added: list[dict[str, Any]]) -> tuple[bool, dict[str, bool], dict[str, Any], dict[str, Any], float | None]:
    pm = metrics(parent)
    am = metrics(added)
    combined = parent + added
    cm = metrics(combined)
    pp = payoff(parent)
    cp = payoff(combined)
    checks = {
        "combined_wr_non_decrease": float(cm["win_rate"] or 0) >= float(pm["win_rate"] or 0),
        "combined_pnl_non_decrease": float(cm["net_pnl_bps"] or 0) >= float(pm["net_pnl_bps"] or 0),
        "combined_expectancy_non_decrease": float(cm["net_expectancy_bps"] or 0) >= float(pm["net_expectancy_bps"] or 0),
        "combined_pf_non_decrease": bool(cm.get("profit_factor_unbounded")) or (cm.get("profit_factor") is not None and float(cm["profit_factor"]) >= float(pm["profit_factor"])),
        "combined_payoff_non_decrease": pp is None or (cp is not None and cp >= pp),
        "combined_dd_non_increase": float(cm["drawdown_bps"] or 0) <= float(pm["drawdown_bps"] or 0),
        "added_wr_at_least_parent": float(am["win_rate"] or 0) >= float(pm["win_rate"] or 0),
        "added_expectancy_at_least_parent": float(am["net_expectancy_bps"] or 0) >= float(pm["net_expectancy_bps"] or 0),
        "added_pf_at_least_parent": bool(am.get("profit_factor_unbounded")) or (am.get("profit_factor") is not None and float(am["profit_factor"]) >= float(pm["profit_factor"])),
        "added_pnl_positive": float(am["net_pnl_bps"] or 0) > 0,
    }
    return all(checks.values()), checks, am, cm, cp


def target(loss: Mapping[str, Any]) -> dict[str, Any]:
    for row in loss.get("targets") or []:
        if isinstance(row, Mapping) and row.get("strategy_id") == "trend_rider":
            return dict(row)
    raise RuntimeError("TREND_RIDER_LOSS_TARGET_MISSING")


def validate_sources(contract: Mapping[str, Any], parent_doc: Mapping[str, Any], fresh_doc: Mapping[str, Any], loss_doc: Mapping[str, Any], top5_doc: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if contract.get("state") != "FROZEN_PRIMARY_CHASE_COOLING_FRESH25_CONTRACT":
        raise RuntimeError("PRIMARY_CHASE_CONTRACT_STATE_INVALID")
    core = dict(contract)
    supplied = str(core.pop("receipt_sha256", ""))
    if supplied != stable(core):
        raise RuntimeError("PRIMARY_CHASE_CONTRACT_RECEIPT_MISMATCH")

    hist = contract["historical_strict_ceiling_diagnostic"]
    if parent_doc.get("receipt_sha256") != hist["parent_receipt_sha256"]:
        raise RuntimeError("PRIMARY_PARENT_RECEIPT_CHANGED")
    if fresh_doc.get("receipt_sha256") != hist["fresh2_receipt_sha256"]:
        raise RuntimeError("PRIMARY_FRESH2_RECEIPT_CHANGED")
    if len(parent_doc.get("trades") or []) != 16 or len(fresh_doc.get("trades") or []) != 2:
        raise RuntimeError("PRIMARY_FROZEN_COUNTS_CHANGED")

    root = target(loss_doc)
    cause = root.get("actionable_root_cause") or {}
    if cause.get("axis") != "CHASE_ATR":
        raise RuntimeError(f"PRIMARY_ROOT_CAUSE_CHANGED:{cause.get('axis')}")
    if root.get("recommended_route") != "PREREGISTER_PREENTRY_STRUCTURAL_CHILD:CHASE_ATR:BORROW_EXISTING_CAUSAL_GEOMETRY_ONLY":
        raise RuntimeError("PRIMARY_ROOT_CAUSE_ROUTE_CHANGED")
    if int(root.get("leakage_lookahead") or 0) != 0 or root.get("post_outcome_threshold_sweep") is not False:
        raise RuntimeError("PRIMARY_ROOT_CAUSE_INTEGRITY_INVALID")
    if root.get("integrity_defects"):
        raise RuntimeError("PRIMARY_ROOT_CAUSE_INTEGRITY_DEFECT")

    primary = None
    for row in top5_doc.get("top5") or []:
        if isinstance(row, Mapping) and row.get("rank") == 1 and row.get("strategy_id") == "trend_rider":
            primary = dict(row)
            break
    if primary is None:
        raise RuntimeError("PRIMARY_TOP5_ROW_MISSING")
    ceiling = primary.get("latest_strict_ceiling") or {}
    fresh = primary.get("fresh_to_25") or {}
    if int(ceiling.get("T") or 0) != 24 or int(fresh.get("T_needed") or 0) != 1:
        raise RuntimeError("PRIMARY_STRICT24_SSOT_CHANGED")
    ref = float(fresh.get("reference_min_winner_bps") or 0)
    expected = float(hist["reference_required_one_unseen_winner_bps"])
    if abs(ref - expected) > 1e-9:
        raise RuntimeError("PRIMARY_REFERENCE_WINNER_CHANGED")
    return root, primary


def run() -> dict[str, Any]:
    contract = read(CONTRACT)
    parent_doc = read(PARENT)
    fresh_doc = read(FRESH2)
    loss_doc = read(LOSS)
    top5_doc = read(TOP5)
    root, primary = validate_sources(contract, parent_doc, fresh_doc, loss_doc, top5_doc)

    hist = contract["historical_strict_ceiling_diagnostic"]
    boundary_ms = int(contract["preregistered_root_cause"]["boundary_ms"])
    parent = [dict(x) for x in parent_doc.get("trades") or []]
    fixed = [dict(x) for x in fresh_doc.get("trades") or []] + [dict(x) for x in hist["oracle_donor_rows"]]
    fixed_keys = [key(x) for x in parent + fixed]
    if len(fixed_keys) != len(set(fixed_keys)):
        raise RuntimeError("PRIMARY_FIXED_BASELINE_DUPLICATE_KEY")
    fixed_key_set = set(fixed_keys)

    ledger = [dict(x) for x in root.get("preentry_trade_ledger") or []]
    post = sorted([x for x in ledger if int(x.get("signal_ts") or 0) > boundary_ms], key=key)
    accepted = [x for x in post if x.get("chase_cooling_or_flat") is True]
    rejected = [x for x in post if x.get("chase_cooling_or_flat") is not True]
    if any(key(x) in fixed_key_set for x in accepted):
        raise RuntimeError("PRIMARY_POST_BOUNDARY_OVERLAPS_FIXED_BASELINE")

    strict_pass, checks, added_metrics, combined_metrics, combined_payoff = strict(parent, fixed + accepted)
    causal_fresh_ready = bool(accepted) and int(combined_metrics["trades"]) >= 25
    candidate_pass = causal_fresh_ready and strict_pass

    if not accepted:
        state = "WAIT_PRIMARY_CHASE_COOLING_FRESH_T"
        nxt = "COLLECT_POST_BOUNDARY_CHASE_COOLING_T"
    elif candidate_pass:
        state = "PASS_PRIMARY_STRICT25_CAUSAL_CONFIRMATION_CANDIDATE"
        nxt = "INDEPENDENT_REVIEW_BEFORE_SSOT_SURVIVOR_UPDATE"
    else:
        state = "HOLD_PRIMARY_CHASE_COOLING_FRESH_ECONOMIC"
        nxt = "KEEP_PARENT_LOCKED_AND_DO_NOT_DELETE_ACCEPTED_T"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "trend_rider",
        "lane_id": "trend_rider_primary_wr8125",
        "changed_axis": "PREENTRY_CHASE_COOLING_OR_FLAT_ONLY",
        "contract_receipt_sha256": contract["receipt_sha256"],
        "latest_loss_receipt_sha256": loss_doc.get("receipt_sha256"),
        "latest_target_receipt_sha256": root.get("receipt_sha256"),
        "top5_state": top5_doc.get("state"),
        "historical_strict_ceiling_T": int((primary.get("latest_strict_ceiling") or {}).get("T") or 0),
        "reference_required_one_unseen_winner_bps": hist["reference_required_one_unseen_winner_bps"],
        "boundary_ms": boundary_ms,
        "boundary_utc": contract["preregistered_root_cause"]["boundary_utc"],
        "raw_post_boundary_T": len(post),
        "fresh_accepted_T": len(accepted),
        "fresh_rejected_T": len(rejected),
        "fresh_accepted_rows": [{k: x.get(k) for k in ("symbol", "signal_ts", "entry_ts", "exit_ts", "side", "net_bps", "chase_atr", "prior_chase_atr", "chase_cooling_or_flat", "reason")} for x in accepted],
        "fresh_rejected_keys": [list(key(x)) for x in rejected],
        "fixed_diagnostic_added_T": len(fixed),
        "combined_T": combined_metrics["trades"],
        "strict_all_metric_pass": strict_pass,
        "strict_checks": checks,
        "added_metrics": added_metrics,
        "combined_metrics": combined_metrics,
        "combined_payoff": combined_payoff,
        "causal_fresh_confirmation_ready": causal_fresh_ready,
        "strict25_causal_candidate_pass": candidate_pass,
        "historical_oracle_is_promotion_evidence": false,
        "same_sample_root_cause_is_promotion_evidence": false,
        "all_accepted_post_boundary_trades_append_only": true,
        "post_outcome_trade_deletion": false,
        "old_history_union": false,
        "numeric_threshold_sweep": false,
        "production_mutated": false,
        "top5_ssot_mutated": false,
        "g5_broad_mutated": false,
        "selection_authority": false,
        "promotion_authority": false,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "hold",
        "next": nxt,
    }
    result["receipt_sha256"] = stable(result)
    return result


def self_test() -> int:
    contract = read(CONTRACT)
    assert contract["borrowed_existing_causal_geometry"]["numeric_threshold_added"] is False
    assert contract["borrowed_existing_causal_geometry"]["threshold_sweep"] is False
    assert contract["policy"]["post_outcome_trade_deletion"] is False
    result = run()
    assert result["changed_axis"] == "PREENTRY_CHASE_COOLING_OR_FLAT_ONLY"
    assert result["old_history_union"] is False
    assert result["numeric_threshold_sweep"] is False
    assert result["selection_authority"] is False and result["promotion_authority"] is False
    assert result["execution_authority"] == "NONE"
    assert result["order_authority"] == "BLOCKED" and result["live_trade_authority"] == "BLOCKED"
    assert all(int(x["signal_ts"]) > int(result["boundary_ms"]) for x in result["fresh_accepted_rows"])
    print("PASS_A1_TRENDRIDER_PRIMARY_CHASE_COOLING_FRESH25_V1_SELF_TEST")
    print(json.dumps({k: result[k] for k in ("state", "raw_post_boundary_T", "fresh_accepted_T", "combined_T", "strict_all_metric_pass", "next")}, sort_keys=True))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_primary_chase_cooling_fresh25_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("state", "raw_post_boundary_T", "fresh_accepted_T", "combined_T", "strict_all_metric_pass", "next", "receipt_sha256")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
