#!/usr/bin/env python3
"""Read-only archived Squeeze/Trend G5 witness; never invokes a collector.

Hash integrity proves storage consistency, not market provenance or fills.
Unknown open counts remain null. Unresolved censored campaigns are not closes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from math import fsum
from pathlib import Path

SOURCE_SHA = "dd59cdb4fa5d6347cb40f55c8e014ef790c0fe63"
BASE = "backend/research/rebuild/"
LANES = {
    "Squeeze-KR3 Unified": {
        "stem": "g5_squeeze_kr3_unified", "kind": "squeeze",
        "rule_id": "SQUEEZE_KR3_UNIFIED_V1_FUTURE_DUAL_GENERATOR",
        "boundary_ms": 1789243200000, "bar_ms": 14400000,
        "contract": "backend/research/contracts/squeeze_kr3_unified_g5a_collector_v1.json",
    },
    "TrendRider Unified": {
        "stem": "g5_trend_rider_unified", "kind": "trend",
        "rule_id": "TREND_RIDER_UNIFIED_V1_CAUSAL_POLICY",
        "boundary_ms": 1789221600000, "bar_ms": 3600000,
        "contract": "backend/research/contracts/trendrider_unified_g5a_collector_v1.json",
    },
}


def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False,
                                    default=str).encode()).hexdigest()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def classify_records(rows, kind, rule_id, boundary_ms):
    """Fail before counting if an identity/boundary differs from the frozen lane."""
    if any(r.get("rule_id") != rule_id for r in rows):
        raise ValueError("RULE_ID_MISMATCH")
    if any(int(r.get("signal_ts", -1)) < boundary_ms for r in rows):
        raise ValueError("PRE_BOUNDARY_ROW")
    ids = [r.get("event_id") for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_EVENT_ID")
    if kind == "squeeze":
        signals = {r["campaign_id"]: r for r in rows if r.get("kind") == "SIGNAL_CAPTURED"}
        finalized = {r["campaign_id"]: r for r in rows if r.get("kind") == "LIFECYCLE_FINALIZED"}
        if len(signals) != sum(r.get("kind") == "SIGNAL_CAPTURED" for r in rows):
            raise ValueError("DUPLICATE_SIGNAL_CAMPAIGN")
        if len(finalized) != sum(r.get("kind") == "LIFECYCLE_FINALIZED" for r in rows):
            raise ValueError("DUPLICATE_FINALIZED_CAMPAIGN")
        if not set(finalized) <= set(signals):
            raise ValueError("FINALIZED_WITHOUT_SIGNAL")
        for cid, r in finalized.items():
            if r.get("censored") is not False or r.get("unknown_exit") is not False:
                raise ValueError("CENSORED_OR_UNKNOWN_FINALIZED")
            if int(r["exit_ts"]) <= int(r["entry_ts"]):
                raise ValueError("INVALID_LIFECYCLE_ORDER")
            for key in ("symbol", "side", "signal_ts", "entry_ts", "component", "cost_model_sha256"):
                if r.get(key) != signals[cid].get(key):
                    raise ValueError("SIGNAL_FINALIZED_IDENTITY_MISMATCH:" + key)
        unmatched = [signals[k] for k in signals.keys() - finalized.keys()]
        return {"stored_finalized_T": len(finalized), "signal_T": len(signals),
                "unresolved_signal_T": len(unmatched),
                "unresolved_censored_T": sum(r.get("censored") is True for r in unmatched),
                "actual_open_T": None, "closed_rows": list(finalized.values()),
                "unresolved_campaign_ids": sorted(r["campaign_id"] for r in unmatched)}
    if any(r.get("lifecycle_state") != "SIGNAL_CAPTURED_AWAIT_ECONOMIC_COMPLETION" for r in rows):
        raise ValueError("UNSUPPORTED_TREND_LIFECYCLE_STATE")
    return {"stored_finalized_T": 0, "signal_T": len(rows),
            "unresolved_signal_T": len(rows), "unresolved_censored_T": None,
            "actual_open_T": None, "closed_rows": [], "unresolved_campaign_ids": None}


def native_chain_check(source, rows):
    """Execute the existing pure validator body, without importing collector I/O."""
    tree = ast.parse(source.read_text(), filename=str(source))
    picked = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SCHEMA" for t in node.targets):
            picked.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in ("stable", "validate_chain"):
            picked.append(node)
    if len(picked) != 3:
        raise ValueError("NATIVE_VALIDATOR_SHAPE_CHANGED")
    prefix = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[prefix] + picked, type_ignores=[]))
    ns = {"hashlib": hashlib, "json": json}
    exec(compile(module, str(source), "exec"), ns)
    ns["validate_chain"](rows)


def build(root):
    root = Path(root)
    monitor_path = root / "research/g5/TOP5_G5A_PHASE1_STATUS_V1.json"
    monitor = json.loads(monitor_path.read_text())
    result = {"schema": "zel.g5.st.readonly.witness.v1", "source_commit": SOURCE_SHA,
              "monitor_sha256": digest(monitor_path),
              "monitor_observed_at_ms": monitor["observed_at_ms"],
              "formal_pass_authority": False, "g5a_rows_reusable_for_g5b": False,
              "new_collection": False, "new_replay": False, "lanes": {}}
    for name, cfg in LANES.items():
        state_path = root / (BASE + cfg["stem"] + "_state_v1.json")
        events_path = root / (BASE + cfg["stem"] + "_events_v1.jsonl")
        code_path = root / (BASE + cfg["stem"] + "_collector_v1.py")
        contract_path = root / cfg["contract"]
        state = json.loads(state_path.read_text())
        rows = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        core = dict(state); state_seal = core.pop("state_sha256")
        errors = []
        if stable(core) != state_seal: errors.append("STATE_INTERNAL_HASH_MISMATCH")
        if digest(state_path) != monitor["lanes"][name]["state_sha256"]: errors.append("MONITOR_STATE_HASH_MISMATCH")
        if state["rule_id"] != cfg["rule_id"]: errors.append("STATE_RULE_ID_MISMATCH")
        if state["boundary_ms"] != cfg["boundary_ms"]: errors.append("STATE_BOUNDARY_MISMATCH")
        if digest(contract_path) != state["contract_sha256"]: errors.append("CONTRACT_HASH_MISMATCH")
        code_bindings = {}
        dependencies = (("generator_sha256", "squeeze_kr3_future_dual_generator_v1.py"),
                        ("arbiter_sha256", "squeeze_kr3_native_sleeve_v1.py")) if cfg["kind"] == "squeeze" else (("policy_sha256", "trend_rider_unified_v1_policy.py"),)
        for field, filename in dependencies:
            actual_sha = digest(root / (BASE + filename))
            code_bindings[field] = {"path": BASE + filename, "recorded_sha256": state[field],
                                    "actual_sha256": actual_sha, "matches": actual_sha == state[field]}
            if actual_sha != state[field]: errors.append("FROZEN_CODE_HASH_MISMATCH:" + field)
            if any(r.get(field) != state[field] for r in rows): errors.append("EVENT_CODE_HASH_MISMATCH:" + field)
        native = "PASS"
        try:
            native_chain_check(code_path, rows)
        except (RuntimeError, ValueError, KeyError) as exc:
            native = str(exc); errors.append("NATIVE_CHAIN:" + str(exc))
        classified = classify_records(rows, cfg["kind"], cfg["rule_id"], cfg["boundary_ms"])
        closed = sorted(classified.pop("closed_rows"), key=lambda x: (x["exit_ts"], x["campaign_id"]))
        independent_chain_errors = []
        previous = None
        for index, row in enumerate(rows):
            core = dict(row); supplied = core.pop("record_sha256")
            if stable(core) != supplied or row["seq"] != index or row["prev_sha256"] != previous:
                independent_chain_errors.append(index)
            previous = supplied
        if independent_chain_errors: errors.append("INDEPENDENT_CHAIN_MISMATCH")
        if cfg["kind"] == "squeeze":
            for symbol, cost in state["cost_models"].items():
                if stable(cost["model"]) != cost["model_sha256"]: errors.append("COST_MODEL_HASH:" + symbol)
            signals = {r["campaign_id"]: r for r in rows if r.get("kind") == "SIGNAL_CAPTURED"}
            for row in rows:
                cost = state["cost_models"][row["symbol"]]
                if row["cost_model_sha256"] != cost["model_sha256"]: errors.append("EVENT_COST_MODEL_HASH")
            delay = [r["observed_at_ms"] - r["entry_ts"] for r in signals.values()]
            first = "raw_lifecycle_preimage"
            blockers = [first, "source_window_preimage", "native_entry_exit_fills_and_weighted_legs", "signed_funding_settlement_history", "market_received_at_or_available_at"]
            last_scan = state["last_scanned_closed_4h_ms"]
            cost_models = state["cost_models"]
        else:
            delay = [r["observed_at_ms"] - r["signal_bar_close_ms"] for r in rows]
            first = "completed_lifecycle_rows"
            blockers = [first, "entry_and_exit_fill_rows", "source_bar_tail_preimage", "cost_snapshot_preimage", "signed_funding_settlement_history", "market_received_at_or_available_at"]
            last_scan = state["last_scanned_closed_1h_ms"]
            cost_models = None
        result["lanes"][name] = {
            **classified, "rule_id": cfg["rule_id"], "boundary_ms": cfg["boundary_ms"],
            "boundary_utc": stamp(cfg["boundary_ms"]), "state_path": str(state_path.relative_to(root)),
            "state_sha256": digest(state_path), "events_path": str(events_path.relative_to(root)),
            "events_sha256": digest(events_path), "collector_sha256": digest(code_path),
            "code_bindings": code_bindings,
            "contract_sha256": digest(contract_path), "event_rows": len(rows),
            "native_chain_validation": native, "independent_chain_errors": independent_chain_errors,
            "stored_closed_count_matches_monitor": classified["stored_finalized_T"] == monitor["lanes"][name]["fresh_closed_T"],
            "stored_closed_row_integrity_verified_T": 0 if errors else len(closed),
            "source_and_cost_verified_closed_T": 0,
            "monitor_reported_open_T": monitor["lanes"][name]["fresh_open_T"],
            "monitor_missing_open_defaults_to_zero": "open_T" not in state and "censored_open_T" not in state,
            "duplicate_event_T": len(rows) - len({r["event_id"] for r in rows}),
            "event_sequence_gaps": 0 if not independent_chain_errors else None,
            "market_candle_gap_count": None, "market_duplicate_bar_count": None,
            "last_scanned_bar_open_ms": last_scan, "last_scanned_bar_open_utc": stamp(last_scan),
            "last_completed_bar_age_at_monitor_ms": monitor["observed_at_ms"] - last_scan - cfg["bar_ms"],
            "event_observed_delay_ms": {"basis": "observed_at_ms minus modeled entry_ts" if cfg["kind"] == "squeeze" else "observed_at_ms minus signal_bar_close_ms", "minimum": min(delay) if delay else None, "maximum": max(delay) if delay else None, "is_market_delivery_latency": False},
            "symbol_event_counts": dict(Counter(r["symbol"] for r in rows)),
            "recorded_cost_models_only": cost_models,
            "logged_finalized_gross_bps_sum_unverified_fills": fsum(r["gross_bps"] for r in closed) if closed else None,
            "closed_row_projection": [{k: r.get(k) for k in ("campaign_id", "component", "symbol", "side", "entry_ts", "exit_ts", "gross_bps", "cost_model_sha256", "raw_lifecycle_sha256", "source_window_sha256")} for r in closed],
            "net1x_bps": None, "net2x_bps": None, "cost1x_bps": None, "cost2x_bps": None,
            "PF": None, "WR_pct": None, "realized_DD_bps": None, "account_DD_pct": None,
            "max_loss_streak": None, "ordinary_winner_retention": None, "large_winner_retention": None,
            "integrity": "STORAGE_VALID_SOURCE_ACCOUNTING_UNVERIFIED" if not errors else "FAIL",
            "integrity_errors": errors, "status": "G5_ACCOUNTING_INPUT_BLOCKED",
            "first_blocker": errors[0] if errors else first, "missing_inputs": blockers,
            "existing_accountant": "c70_tm_capreuse_account_v1.campaign and c63_c70_trader_account_v1.campaign require full native raw legs and source/cost packet; persisted event summaries are insufficient" if cfg["kind"] == "squeeze" else "g5_trend_rider_unified_collector_v1 stores signal summaries only; no closed lifecycle rows to account",
            "economic_arithmetic": "NOT_RUN_INPUT_BLOCKED",
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(build(args.root), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
