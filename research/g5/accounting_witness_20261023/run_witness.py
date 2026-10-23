#!/usr/bin/env python3
"""Reproduce this archived G5 witness only. No markets, collectors or claims."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import socket
import sys
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
import audit_ks
import q0_readonly_audit
import st_witness
from verify_inputs import external_output, strict_json, verify

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "INPUT_MANIFEST.json"


def save(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def summarize(ks, q0, st):
    rows = {}
    for name, value in ks["lanes"].items():
        scenario = value["frozen_scenario_only"]
        one, two = scenario["cost1x"], scenario["cost2x"]
        rows[name] = dict(identity=value["identity"], state_path=value["state_path"],
            state_sha256=value["state_sha256"], boundary_ms=value["boundary_ms"],
            stored_closed_T=value["monitor_closed_T"], stored_row_verified_T=value["verified_stored_fresh_closed_rows_T"],
            source_and_native_cost_verified_closed_T=0, actual_open_T=None, censored_T=None,
            raw_market_gap_count=None, duplicate_trade_T=value["duplicate_trade_ids"],
            model_net1x_trade_bps=one["net_sum_trade_bps"], model_net2x_trade_bps=two["net_sum_trade_bps"],
            model_PF1x=one["profit_factor"], model_PF2x=two["profit_factor"], model_WR_pct=one["win_rate_pct"],
            model_realized_sequential_DD_trade_bps=one["realized_sequential_trade_bps_drawdown"],
            model_max_loss_streak_trades=one["max_loss_streak"], model_basis="FROZEN_FIXED_20BPS_AND_40BPS_PER_T",
            first_blocker=value["first_blocker"], details="KS_WITNESS.json")
    one, two = q0["model_diagnostic"]["cost1x"], q0["model_diagnostic"]["cost2x"]
    rows["Q0 Convex Channel Breakout"] = dict(identity=q0["identity"], state_path=q0["state_path"],
        state_sha256=q0["state_sha256"], boundary_ms=q0["boundary_ms"],
        stored_closed_T=q0["counts"]["finalized_event_T"], stored_row_verified_T=q0["counts"]["closed_verified_ledger_T"],
        source_and_native_cost_verified_closed_T=0, actual_open_T=q0["counts"]["open_T"], censored_T=q0["counts"]["censored_open_T"],
        raw_market_gap_count=None, duplicate_trade_T=q0["integrity"]["duplicate_event_ids"],
        stop_witness_T=q0["counts"]["stop_witness_T"], stop_1m_rows=q0["counts"]["minute_rows_verified"],
        stop_1m_gap_count=0, missing_entry_source_T=q0["integrity"]["missing_entry_4h_source_T"],
        missing_nonstop_exit_source_T=q0["integrity"]["missing_nonstop_exit_4h_source_T"],
        model_net1x_trade_bps=one["sum_trade_bps"], model_net2x_trade_bps=two["sum_trade_bps"],
        model_PF1x=one["PF"], model_PF2x=two["PF"], model_WR_pct=one["WR_percent"],
        model_realized_grouped_DD_trade_bps=one["realized_closed_group_DD_trade_bps"],
        model_max_loss_streak_exit_groups=one["max_negative_exit_group_streak"],
        model_basis=q0["model_diagnostic"]["basis"], first_blocker=q0["official_accounting"]["first_field"], details="Q0_WITNESS.json")
    for name, value in st["lanes"].items():
        rows[name] = dict(identity=value["rule_id"], state_path=value["state_path"], state_sha256=value["state_sha256"],
            boundary_ms=value["boundary_ms"], stored_closed_T=value["stored_finalized_T"],
            stored_row_verified_T=value["stored_closed_row_integrity_verified_T"], source_and_native_cost_verified_closed_T=0,
            actual_open_T=value["actual_open_T"], censored_T=value["unresolved_censored_T"],
            unresolved_signal_T=value["unresolved_signal_T"], raw_market_gap_count=None, duplicate_trade_T=value["duplicate_event_T"],
            last_scanned_bar_open_ms=value["last_scanned_bar_open_ms"],
            model_net1x_trade_bps=None, model_net2x_trade_bps=None, model_PF1x=None, model_PF2x=None,
            model_WR_pct=None, model_basis="NOT_RUN_INPUT_BLOCKED", first_blocker=value["first_blocker"], details="ST_WITNESS.json")
    for row in rows.values():
        row.update(status="G5_ACCOUNTING_INPUT_BLOCKED", native_actual_net1x_bps=None, native_actual_net2x_bps=None,
                   account_DD_pct=None, ordinary_winner_retention=None, large_winner_retention=None,
                   formal_pass_authority=False, g5a_rows_reusable_for_g5b=False)
    return rows


def run(root, output):
    root = root.resolve()
    output = external_output(root, output)
    manifest = strict_json(MANIFEST.read_text())
    before = verify(root, manifest)
    with patch.object(socket, "socket", side_effect=RuntimeError("NETWORK_FORBIDDEN_IN_READONLY_WITNESS")), \
         patch.object(socket, "create_connection", side_effect=RuntimeError("NETWORK_FORBIDDEN_IN_READONLY_WITNESS")):
        ks = audit_ks.build(root)
        q0 = q0_readonly_audit.build(root)
        st = st_witness.build(root)
    if q0["integrity"]["state_and_event_chain_errors"] or q0["model_diagnostic"] is None:
        raise ValueError("Q0_INTEGRITY_FAILED")
    if any(v["integrity_errors"] for v in st["lanes"].values()):
        raise ValueError("ST_INTEGRITY_FAILED")
    if before != verify(root, manifest):
        raise ValueError("INPUTS_CHANGED_DURING_READ")
    lanes = summarize(ks, q0, st)
    monitor = strict_json((root / "research/g5/TOP5_G5A_PHASE1_STATUS_V1.json").read_text())
    for name, row in lanes.items():
        if row["stored_closed_T"] != monitor["lanes"][name]["fresh_closed_T"]:
            raise ValueError("MONITOR_CLOSED_COUNT_MISMATCH:" + name)
    output.mkdir(parents=True, exist_ok=False)
    for item in manifest["files"]:
        target = output / "frozen_input" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / item["path"]).read_bytes())
    # Snapshot bytes must match too; no conversion or stale-data substitution.
    verify(output / "frozen_input", manifest)
    hashes = {}
    for filename, value in [("KS_WITNESS.json", ks), ("Q0_WITNESS.json", q0), ("ST_WITNESS.json", st)]:
        hashes[filename] = save(output / filename, value)
    handoff = dict(schema="zel.g5.accounting_handoff.v1", source_commit=manifest["source_commit"],
        source_observation_ms=monitor["observed_at_ms"], evidence_scope="ARCHIVED_NATIVE_G5_STORED_ROW_DIAGNOSTIC_ONLY",
        environment=dict(python=platform.python_version(), platform=platform.platform()),
        input_manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        input_contract="Exact pinned bytes, original lane identities/boundaries/cost models. No source collection or strategy replay.",
        command="python research/g5/accounting_witness_20261023/run_witness.py --source-root . --output-dir <NEW_DIRECTORY_OUTSIDE_CHECKOUT>",
        canonical_preflight="PINNED_BYTES_AND_ROW_COUNTS_VERIFIED; FULL_NATIVE_SOURCE_ACCOUNTING_BLOCKED",
        formal_pass_authority=False, g5a_rows_reusable_for_g5b=False, formal_credit=0,
        model_units="SUM_OF_EQUAL_NOTIONAL_TRADE_BPS; NOT_ACCOUNT_RETURN; 2X_COST_NOT_2X_LEVERAGE",
        missing_values="null means NOT_MEASURED_OR_NOT_PROVEN; never zero-filled",
        source_files_unchanged=True, market_network_calls=0, collector_invocations=0,
        economic_heavy_runs=0, economic_claims=0, production_ledger_writes=0, orders=0,
        proven_parser_defect="Original monitor defaults or hard-codes unknown open counts to zero. This add-only witness uses null and separately retains six unresolved Squeeze censored campaigns.",
        stale_policy="No new stale threshold invented; no assertion of current freshness. Squeeze source cursor is archived and older than monitor.",
        owner_handoff="Only existing A owner may consider formal consumption after live owner/claim/slot re-read and release. This command is read-only; it does not grant or consume economic authority.",
        lanes=lanes, output_sha256=hashes)
    hashes["G5_ACCOUNTING_HANDOFF.json"] = save(output / "G5_ACCOUNTING_HANDOFF.json", handoff)
    save(output / "OUTPUT_HASHES.json", hashes)
    return handoff


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    value = run(args.source_root, args.output_dir)
    print(json.dumps({"result": "G5_ACCOUNTING_INPUT_BLOCKED", "lanes": {k: v["stored_closed_T"] for k, v in value["lanes"].items()}, "formal_credit": 0}))
