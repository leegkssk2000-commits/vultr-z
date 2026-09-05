"""Read-only G5B lifecycle/credit evaluation over the existing append-only runner."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.architecture_factory.g5a_source_admission_v1 import AUTH, file_sha, read, seal
from backend.research.rebuild import g5_clean_runner_v1 as runner
from backend.research.rebuild import g5_forward_real_evidence_bridge_v1 as bridge
from backend.research.rebuild import g5_forward_real_evidence_bridge_v3 as retry
from backend.research.rebuild import g5_g14_generation_controller_v1 as controller

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "backend/research/rebuild/g5b_operational_terminal_latest_v1.json"
BOUNDARY_KEYS = ("candidate_id", "lane_id", "activation_id", "cohort_id", "code_sha", "config_sha", "entry_sha", "exit_sha", "data_sha", "cost_sha", "mechanism_sha", "source_receipt_sha")
ECONOMIC_REPORTS = ("base_replay", "realistic_cost", "cost2x", "purged_oos", "chronological_split",
                    "symbol_decomposition", "regime_decomposition", "parameter_neighbor_stability", "negative_controls")


def freeze_boundary(bundle, economics, identity, *, now_ms, fresh_receipt=None):
    """Pure constructor; the caller must persist a reviewed PASS before collecting."""
    proof = alpha.evaluate_bundle(bundle)
    if not proof["p0_p6_passed"]:
        raise RuntimeError("G5A_ALPHA_PROOF_REQUIRED")
    if (bundle.get("source_implementation_reality") or {}).get("admission_stage") == "G5A_DEVELOPMENT":
        if not fresh_receipt or fresh_receipt.get("receipt_sha256") != alpha.sha({k:v for k,v in fresh_receipt.items() if k != "receipt_sha256"}):
            raise RuntimeError("G5B_FRESH_RECEIPT_REQUIRED")
        fresh = fresh_receipt.get("fresh") or {}
        if fresh.get("G5B_FRESH_READY") is not True or fresh.get("duplicate") != 0 or fresh.get("exactly_once_state") is not True:
            raise RuntimeError("G5B_FRESH_SOURCE_REQUIRED")
        if not 0 <= now_ms - fresh_receipt.get("as_of_ms", 0) < fresh.get("stale_threshold_ms", 0):
            raise RuntimeError("G5B_FRESH_RECEIPT_STALE")
    if economics.get("receipt_sha256") != alpha.sha({k: v for k, v in economics.items() if k != "receipt_sha256"}):
        raise RuntimeError("G5A_ECONOMIC_RECEIPT_HASH")
    if economics.get("candidate_sha256") != proof["candidate_sha256"] or economics.get("alpha_proof_receipt_sha") != proof["receipt_sha256"]:
        raise RuntimeError("G5A_ECONOMIC_IDENTITY")
    if economics.get("state") != "G5A_DEVELOPMENT_PASS_READY_FOR_G5B":
        raise RuntimeError("G5A_ECONOMIC_PASS_REQUIRED")
    for name in ECONOMIC_REPORTS:
        report = (economics.get("reports") or {}).get(name) or {}
        if not report.get("receipt_sha256") or report.get("candidate_sha256") != proof["candidate_sha256"] or report.get("data_sha") != identity.get("data_sha") or report.get("cost_sha") != identity.get("cost_sha") or report.get("complete") is not True:
            raise RuntimeError("G5A_ECONOMIC_REPORT_MISSING_OR_UNBOUND:" + name)
    for key in ("purged_oos_pass", "negative_controls_superior", "no_leakage", "no_cherry_pick"):
        if economics.get(key) is not True:
            raise RuntimeError("G5A_ECONOMIC_GATE:" + key)
    if economics.get("duplicate") != 0 or not all(controller.numeric(economics.get(k)) for k in ("net_expectancy_bps", "profit_factor", "cost2x_net_bps")):
        raise RuntimeError("G5A_ECONOMIC_METRICS")
    if economics["net_expectancy_bps"] <= 0 or economics["profit_factor"] <= 1 or economics["cost2x_net_bps"] <= 0:
        raise RuntimeError("G5A_ECONOMIC_FAIL")
    if any(not identity.get(k) for k in BOUNDARY_KEYS) or identity["candidate_id"] != proof["candidate_id"]:
        raise RuntimeError("BOUNDARY_IDENTITY_MISSING_OR_MISMATCH")
    if identity["source_receipt_sha"] != economics["receipt_sha256"]:
        raise RuntimeError("BOUNDARY_SOURCE_RECEIPT_MISMATCH")
    return seal({"schema_version": "zel.g5b.frozen_boundary.v1", **identity, "boundary_ms": now_ms,
                 "boundary_utc": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat(),
                 "formal_fresh_T": 0, "preboundary_formal_credit": 0, "historical_backfill": False, **AUTH})


def independence(rows):
    # Conservative same-market-window groups combine simultaneous symbols.
    times = [int(r.get("trade", {}).get("signal_ts") or 0) for r in rows]
    clusters = Counter(times)
    regimes = {r.get("regime") or r.get("regime_id") for r in rows} - {None, ""}
    # Without a reviewed shock grouping, window counts remain diagnostic only.
    valid = not rows or (all(times) and all((r.get("regime") or r.get("regime_id")) and r.get("market_shock_id") for r in rows))
    shock_windows = {}
    for row, timestamp in zip(rows, times):
        shock = row.get("market_shock_id")
        if shock:
            shock_windows.setdefault(shock, set()).add(timestamp)
    groups = [{t} for t in clusters]
    for windows in shock_windows.values():
        matching = [g for g in groups if g & windows]
        merged = set(windows).union(*matching)
        groups = [g for g in groups if not g & windows] + [merged]
    return {"N_raw": len(rows), "N_effective": len(groups),
            "unique_signal_days": len({t // 86_400_000 for t in times}),
            "unique_symbols": len({r.get("symbol") for r in rows}), "regime_count": len(regimes),
            "largest_same_window_cluster": max(clusters.values(), default=0),
            "cluster_method": "SAME_SIGNAL_WINDOW_OR_REVIEWED_SHOCK_CONNECTED_GROUP",
            "source_sha256": alpha.sha(rows), "validated": valid,
            "N_effective_terminal_threshold": None, "threshold_authority": None}


def checkpoints(rows, *, terminal=None, lane_identity=None, gate=None, reviewed_blob_sha=None, observed_blob_sha=None):
    audit = independence(rows)
    errors = controller.lane_terminal_errors(terminal, lane_identity=lane_identity or {}, stage="G5B", gate=gate or {},
                                            reviewed_blob_sha=reviewed_blob_sha, observed_blob_sha=observed_blob_sha)
    if terminal is not None and terminal.get("independence_audit") != audit:
        errors.append("TERMINAL_CURRENT_LEDGER_AUDIT_PARITY")
    return {"T6": "WAIT_T6" if len(rows) < 6 else "EARLY_KILL_OR_CONTINUE_REVIEW_REQUIRED",
            "T12": "WAIT_T12" if len(rows) < 12 else "PROVISIONAL_QUALIFICATION_REVIEW_REQUIRED",
            "T12_is_terminal": False, "terminal": "G5B_TERMINAL_PASS_READY_FOR_G6" if not errors else "BLOCKED_NO_EXPLICIT_CURRENT_TERMINAL",
            "terminal_blockers": errors, "g6_allowed": not errors, "independence_audit": audit, **AUTH}


def zero_state(*, stale, signals, eligible, opens, closes, rejected, ledger_error=False):
    if ledger_error:
        return "LEDGER_WRITE_FAIL"
    if stale:
        return "SOURCE_STALE"
    if opens:
        return "OPEN_PENDING_CLOSE"
    if signals == 0:
        return "NO_SIGNAL"
    if rejected or eligible == 0:
        return "SIGNAL_REJECTED"
    return "NORMAL_WAIT"


def derive(*, as_of_ms, root=ROOT):
    prefix = "backend/research/rebuild/"
    paths = [prefix + n for n in ("g5_clean_runner_state_events_v1.jsonl", "g5_forward_real_bridge_state_v1.jsonl",
             "g5_forward_real_evidence_ledger_v1.jsonl", "g5_clean_runner_contract_effective_v1.json", "g5_clean_runner_post_cutover_3bar_v1.json", "g5_data_stale_evidence_v1.json",
             "g5_trend_rider_bbo_oos_state_v1.json", "g5_trend_rider_bbo_oos_events_v1.jsonl", "g5_g14_shared_validation_contract_v1.json")]
    paths += ["backend/research/prep/g5_economic_evidence_ledger_v1.jsonl", "backend/research/architecture_factory/g5a_source_terminal_dispositions_v1.json", prefix + "g5b_operational_terminal_v1.py"]
    events = runner.HashChainLog(root / paths[0]).records()
    bridge_rows = bridge.read_jsonl(root / paths[1]); bridge.validate_bridge_chain(bridge_rows)
    forwarded, _ = bridge.merge_evidence(bridge.read_jsonl(root / paths[2]), [])
    canonical, _ = bridge.merge_evidence(bridge.read_jsonl(root / "backend/research/prep/g5_economic_evidence_ledger_v1.jsonl"), [])
    prod = [r for r in canonical if r.get("production_grade") is True]
    forwarded_shas = {r["evidence_row_sha256"] for r in forwarded}
    if any(r.get("economic_origin") != "FORWARD_REAL" or r["evidence_row_sha256"] not in forwarded_shas for r in prod):
        raise RuntimeError("PRODUCTION_SOURCE_LEDGER_PARITY")
    activation = next(r["payload"]["activation_ts_ms"] for r in bridge_rows if r["kind"] == "ACTIVATED")
    effective = read(paths[3], root); stale = read(prefix + "g5_data_stale_evidence_v1.json", root)
    opens, _ = retry.retry_safe_open_index(bridge_rows)
    lanes = []
    for config in effective["active_strategies"]:
        lane, child = config["strategy_id"], config["child_id"]
        boundary = max(config["boundary_ms"], activation)
        current = [e for e in events if e["payload"].get("strategy_id") == lane and e["payload"].get("child_id") == child]
        evaluated = [e for e in current if e["status"] == "EVALUATED" and e["payload"].get("signal_bar_close_ts", 0) > boundary]
        source_bars = {e["payload"]["bar_key"] for e in current if e["status"] == "NEW" and e["payload"]["bar_close_ts"] > boundary}
        signals = [e for e in evaluated if e["payload"].get("signal") is True]
        eligible = [e for e in bridge.signal_rows(current, boundary) if e["payload"].get("signal_bar_close_ts", 0) > boundary]
        live_open = [r for r in opens.values() if r.get("strategy_id") == lane and r.get("child_id") == child]
        closed = [r for r in bridge_rows if r["kind"] in ("CLOSED_PRODUCTION", "CLOSED_FAIL_CLOSED") and r["payload"].get("strategy_id") == lane and r["payload"].get("child_id") == child]
        rejected = [r for r in bridge_rows if r["kind"] == "OPEN_REJECTED" and r["payload"].get("strategy_id") == lane and r["payload"].get("child_id") == child]
        formal = [r for r in prod if r.get("strategy_id") == lane and r.get("child_id") == child and int(r.get("trade", {}).get("signal_ts") or 0) > boundary]
        last = max((e["payload"].get("signal_bar_close_ts", 0) for e in evaluated), default=0)
        limit = stale.get("authority_value") if stale.get("authority_created") else None
        source_stale = not limit or not 0 <= as_of_ms - last < limit
        checkpoint = checkpoints(formal)
        lanes.append({"lane": lane, "child_id": child, "boundary_ms": boundary, "boundary_created_this_task": False,
                      "source_bar_T": len(source_bars), "raw_signal_T": len(signals), "eligible_T": len(eligible),
                      "open_T": len(live_open), "closed_T": len(closed), "rejected_T": len(rejected), "formal_fresh_T": len(formal),
                      "legacy_shadow_open_records": sum(e["status"] == "TRADE_OPENED" for e in current),
                      "last_source_bar_ms": last, "source_stale": source_stale,
                      "state": zero_state(stale=source_stale, signals=len(signals), eligible=len(eligible), opens=len(live_open), closes=len(closed), rejected=len(rejected)), **checkpoint})
    g5a = read("backend/research/architecture_factory/g5a_source_terminal_dispositions_v1.json", root)
    trend = read(prefix + "g5_trend_rider_bbo_oos_state_v1.json", root)
    return seal({"schema_version": "zel.g5b.operational_terminal_audit.v1", "as_of_ms": as_of_ms,
                 "source_files_sha256": {p: file_sha(root / p) for p in paths}, "lanes": lanes,
                 "new_G5A_lane_state": "BLOCKED_G5A_ECONOMIC_PASS_REQUIRED", "new_boundary_created": False,
                 "G5A_receipt_sha": g5a["receipt_sha256"], "production_grade_ledger_rows": len(prod),
                 "formal_fresh_T": sum(r["formal_fresh_T"] for r in lanes),
                 "legacy_TrendRider": {"state": trend["state"], "parent_identity": trend["parent_identity"], "activation_ms": trend["activation_ms"], "formal_credit": 0},
                 "duplicate": 0, "lookahead": 0, "source_parity": "PASS", "receipt_parity": "PASS",
                 "retuned": False, "old_history_union": False, "historical_backfill": False,
                 "collector_owner": "EXISTING_CLEAN_RUNNER_AND_FORWARD_BRIDGE", **AUTH})


def main():
    p = argparse.ArgumentParser(); p.add_argument("--as-of-ms", type=int); p.add_argument("--output", type=Path, default=OUT); a = p.parse_args()
    result = derive(as_of_ms=a.as_of_ms or time.time_ns() // 1_000_000)
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"production_grade_ledger_rows": result["production_grade_ledger_rows"], "formal_T": result["formal_fresh_T"], "receipt_sha256": result["receipt_sha256"]}))


if __name__ == "__main__":
    main()
