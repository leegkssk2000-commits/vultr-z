"""K117 saved-ledger observability review; no market reads or strategy replay.

Final excursions/outcomes are retrospective labels, never decision inputs.
This module imports no native engine and implements no proposed trading rule.
The prior ALL126 geometry/path export is deliberately not an input.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path


BASELINE_COMMIT = "8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8"
BASELINE_IDENTITY = "scalp7_k126_veto_objective_completed_fresh_touch_v1"
ROWS_PLAIN_SHA256 = "7cba96a0627dbec42459f344a6e8e7dd70d97f87d71dfb573e10975153d7d0a7"
PINS = {
    "SUMMARY.json": "c2dfcdbec704fb7ab020c2d4d53293fd03dab5820672e0ac6fb4f9aa6094e5ae",
    "ROWS.json.gz": "ab48ec1bd90479ae95fb432838a30e9e23b060c3002c70f14dd09b6a869ca4e9",
    "EXECUTION_FREEZE.json": "918d00133ddb1b498bd93353a48f6e8a75f2da83b4062e3430db52b99b57ef0a",
    "ARITHMETIC_AUDIT.json": "a9832e7fab8b07f2918e82a26fdfa52840a448e8ecfe737a1495d85a4e8a1f2c",
    "objective_lifetime.py": "40659bc91044cca35ea6fc0aad383487b59ac16ec8aeb74639f8f5663e131bb7",
    "run_compare.py": "6072afe404b0341c20975430ca51fcd32f89be8405a6432aa020d53b0dd81538",
}
NATIVE_EXIT_SOURCE_SHA256 = "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2"


def key(row):
    return str(row["symbol"]), int(row["side"]), int(row["signal_ts_ms"])


def net(row, multiple=1):
    return float(row["gross_bps"]) - multiple * float(row["cost_bps"])


def brief(row):
    return {"key": list(key(row)), "net1x": net(row), "net2x": net(row, 2),
            "gross_bps": row["gross_bps"], "hold_bars": row["hold_bars"],
            "final_mfe_R_DIAGNOSTIC": row["mfe_R"],
            "final_mae_R_DIAGNOSTIC": row["mae_R"],
            "saved_exit_reason_NOT_CAUSE": row["reason"]}


def describe(rows):
    return {"count": len(rows), "net1x": sum(net(r) for r in rows),
            "net2x": sum(net(r, 2) for r in rows),
            "gross_negative_count": sum(float(r["gross_bps"]) < 0 for r in rows),
            "base_loss_count": sum(net(r) < 0 for r in rows),
            "base_winner_count": sum(net(r) > 0 for r in rows),
            "keys": [list(key(r)) for r in rows]}


def load(directory):
    data = {}
    for name, pin in PINS.items():
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin:
            raise ValueError("PIN_CHANGED:" + name)
        if name == "ROWS.json.gz":
            raw = gzip.decompress(raw)
            if hashlib.sha256(raw).hexdigest() != ROWS_PLAIN_SHA256:
                raise ValueError("ROWS_PLAIN_CHANGED")
            data[name] = json.loads(raw)
        elif name.endswith(".json"):
            data[name] = json.loads(raw)
        # Code is pinned/read as bytes only; never imported or executed.
    return data


def saved_loss_runs(rows, multiple):
    runs, current = [], []
    for row in rows:  # preserve saved native row/tie order
        if net(row, multiple) < 0:
            current.append(row)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def review(directory: Path):
    data = load(directory)
    ledger = data["ROWS.json.gz"]
    rows = ledger["trades"]
    summary = data["SUMMARY.json"]
    if summary["candidate"] != BASELINE_IDENTITY:
        raise ValueError("BASELINE_IDENTITY_CHANGED")
    rowmap = {key(r): r for r in rows}
    if len(rows) != 117 or len(rowmap) != 117:
        raise ValueError("ALL117_REQUIRED")
    if ledger["unresolved"] or ledger["boundary_excluded"]:
        raise ValueError("SAVED_BASELINE_BOUNDARY_CHANGED")
    losses = [r for r in rows if net(r) < 0]
    winners = [r for r in rows if net(r) > 0]
    if len(losses) != 46 or len(winners) != 71:
        raise ValueError("BASELINE_SIGN_COUNTS_CHANGED")
    for multiple in (1, 2):
        if not math.isclose(sum(net(r, multiple) for r in rows),
                            summary["child"][f"cost{multiple}x"]["Net_bps"], abs_tol=1e-7):
            raise ValueError("SAVED_NET_ARITHMETIC_MISMATCH")

    # These eleven exact accepted successor records do contain a touch clock.
    # The 215 expiry records describe expired setups, not the accepted setups;
    # nearest-date/symbol matches would fabricate lineage and are not attempted.
    touch_matches = {}
    for trace in ledger["native_traces"]:
        if trace.get("next_decision") != "ACCEPTED":
            continue
        k = (str(trace["symbol"]), int(trace["rejected_side"]), int(trace["new_turn_ts_ms"]))
        if k not in rowmap:
            continue
        if k in touch_matches:
            raise ValueError("NONUNIQUE_ACCEPTED_TOUCH_TRACE")
        row = rowmap[k]
        if int(trace["accepted_entry_ts_ms"]) != int(row["entry_ts_ms"]):
            raise ValueError("TOUCH_ENTRY_CLOCK_MISMATCH")
        if not int(trace["rejected_decision_ts_ms"]) < int(trace["new_touch_ts_ms"]) <= int(row["signal_ts_ms"]):
            raise ValueError("TOUCH_TRACE_NONCAUSAL")
        touch_matches[k] = trace

    records = []
    for row in rows:
        signal, meta = row["signal"], row["signal"]["meta"]
        side, symbol = int(row["side"]), row["symbol"]
        entry, terminal = float(row["entry_prices"][symbol]), float(row["exit_prices"][symbol])
        stop, atr = float(signal["stop_price"]), float(meta["atr_price"])
        fallback = side * (entry - stop) <= 0
        if fallback:
            stop = entry - side * float(meta["fallback_stop_atr_mult"]) * atr
        risk = side * (entry - stop)
        if risk <= 0 or atr <= 0:
            raise ValueError("INVALID_FROZEN_RISK")
        mfe, mae = float(row["mfe_R"]), float(row["mae_R"])
        be_arm = float(meta["be_arm_r"])
        if be_arm != 1.0 or signal["partial_take_profit_r"] != 2.0:
            raise ValueError("FROZEN_EXISTING_PROGRESS_THRESHOLDS_CHANGED")
        trace = touch_matches.get(key(row))
        early_stop = row["reason"] in {"STOP_FIRST", "OPEN_GAP_STOP"}
        callback_count = int(row["hold_bars"]) - (1 if early_stop else 0)
        if callback_count < 0:
            raise ValueError("NEGATIVE_CALLBACK_COUNT")
        records.append({
            "key": list(key(row)),
            "signal_open_ts_ms": row["signal_open_ts_ms"],
            "signal_available_ts_ms": row["signal_ts_ms"],
            "feature_available_ts_ms": meta["feature_available_ts_ms"],
            "entry_ts_ms": row["entry_ts_ms"],
            "touch_provenance": {
                "status": "EXACT_ACCEPTED_POST_REJECTION_TOUCH" if trace else "UNKNOWN_NOT_IN_SAVED_ACCEPTED_TRACE",
                "touch_open_ts_ms": trace["new_touch_open_ts_ms"] if trace else None,
                "touch_available_ts_ms": trace["new_touch_ts_ms"] if trace else None,
                "preceding_explicit_rejection_decision_ts_ms": trace["rejected_decision_ts_ms"] if trace else None,
                "nearest_expiry_event_joined": False,
            },
            "entry_frozen": {"entry_price": entry, "initial_admitted_stop": stop,
                             "fallback_applied": fallback, "initial_risk_price": risk,
                             "signal_atr_price": atr, "initial_risk_signal_atr": risk / atr},
            "known_execution_envelope_from_saved_row": {
                "exit_ts_ms": row["exit_ts_ms"], "outcome_available_ts_ms": row["outcome_available_ts_ms"],
                "outcome_time_precision": row["outcome_time_precision"],
                "completed_pre_exit_callback_count_implied_by_fixed_engine": callback_count,
                "pre_exit_callback_price_sequence": None,
                "first_structural_failure_available_ts_ms": None,
                "first_adverse_move_available_ts_ms": None,
                "first_recovery_available_ts_ms": None,
                "first_040R_crossing_ts_ms": None,
                "first_BE_activation_ts_ms": None,
                "first_partial_fill_ts_ms": None,
                "stop_before_after_each_callback": None,
                "MFE_MAE_order": "UNKNOWN_FROM_TERMINAL_EXTREMA",
                "terminal_stop_bar_extrema_credited": False,
                "zero_pre_exit_callback_opportunity": callback_count == 0,
            },
            "outcome_labels_NOT_EXECUTION_FEATURES": {
                **brief(row),
                "gross_negative": row["gross_bps"] < 0,
                "cost_only_base_loss": row["gross_bps"] >= 0 and net(row) < 0,
                "base_winner_flips_at_cost2x": net(row) > 0 and net(row, 2) < 0,
                "existing_BE_ever_reached_in_credited_prefix": mfe >= be_arm,
                "existing_partial_level_ever_reached_in_credited_prefix": mfe >= float(signal["partial_take_profit_r"]),
                "existing_runner_level_ever_reached_in_credited_prefix": mfe >= 3.0,
                "final_mfe_price": mfe * risk, "final_mae_price": mae * risk,
                "signed_terminal_price_change": side * (terminal - entry),
                "adverse_extremum_before_favorable_terminal_price": mae > 0 and side * (terminal - entry) > 0,
                "recovery_witness_limit": "Earlier surviving-bar adverse range plus favorable terminal price; NOT first-adverse-close recovery or known intrabar order.",
            },
        })

    slices = {}
    for name, group in (("loss46", losses), ("winner71", winners)):
        slices[name] = {
            "below_existing_040R_scratch_hurdle": describe([r for r in group if r["mfe_R"] < .4]),
            "reached_040R_but_below_existing_1R_BE": describe([r for r in group if .4 <= r["mfe_R"] < 1]),
            "reached_existing_1R_BE": describe([r for r in group if r["mfe_R"] >= 1]),
        }
    early_losses = [r for r in losses if r["hold_bars"] == 1 and r["reason"] in {"STOP_FIRST", "OPEN_GAP_STOP"}]
    recovery = [r for r in winners if r["mae_R"] > 0 and r["side"] *
                (r["exit_prices"][r["symbol"]] - r["entry_prices"][r["symbol"]]) > 0]
    run_links = {}
    for multiple in (1, 2):
        level = f"cost{multiple}x"
        canonical = [rowmap[tuple(k)] for k in summary["child"][level]["longest_loss_run_keys"]]
        runs = saved_loss_runs(rows, multiple)
        worst = min(runs, key=lambda run: sum(net(r, multiple) for r in run))
        if not math.isclose(sum(net(r, multiple) for r in canonical),
                            summary["child"][level]["longest_loss_run_bps"], abs_tol=1e-7):
            raise ValueError("CANONICAL_LONGEST_RUN_MISMATCH")
        if not math.isclose(sum(net(r, multiple) for r in worst),
                            summary["child"][level]["worst_loss_run_bps"], abs_tol=1e-7):
            raise ValueError("WORST_AMOUNT_RUN_MISMATCH")
        run_links[level] = {
            "canonical_longest_count_run": describe(canonical),
            "worst_loss_amount_run": describe(worst),
            "longest_count_ties": sum(len(run) == len(canonical) for run in runs),
            "canonical_keys_from_summary_not_reselected": True,
            "saved_native_tie_order_preserved": True,
        }
    return {
        "schema": "zel.k117.saved_ledger_observability_review.v1",
        "baseline_commit": BASELINE_COMMIT, "baseline_identity": BASELINE_IDENTITY,
        "classification": "ALL117_SAVED_LEDGER_OBSERVABILITY_NOT_NEW_POLICY_RESULT",
        "input_sha256": PINS, "rows_plain_sha256": ROWS_PLAIN_SHA256,
        "native_exit_source_sha256": NATIVE_EXIT_SOURCE_SHA256,
        "native_price_replays": 0, "new_policy_evaluations": 0,
        "market_api_calls": 0, "old_ALL126_used_as_K117": False,
        "rows": 117, "base_losses": 46, "base_winners": 71,
        "existing_baseline_QUOTED_NOT_NEW_ECONOMICS": summary["child"],
        "new_progress_observability_partition_DIAGNOSTIC_ONLY": slices,
        "cost_only_base_losses": [brief(r) for r in losses if r["gross_bps"] >= 0],
        "base_winners_flipping_at_cost2x": describe([r for r in winners if net(r, 2) < 0]),
        "first_bar_stop_losses_no_post_entry_closed_bar_exit_opportunity": describe(early_losses),
        "adverse_range_then_favorable_terminal_winners": describe(recovery),
        "recovery_examples_DIAGNOSTIC_ONLY": [brief(r) for r in sorted(recovery, key=lambda r: -r["mae_R"])[:6]],
        "exact_accepted_touch_trace_coverage": {
            "known": len(touch_matches), "unknown": 117 - len(touch_matches),
            "known_base_losses": sum(key(r) in touch_matches for r in losses),
            "known_base_winners": sum(key(r) in touch_matches for r in winners),
            "all130_rejection_traces_read": len(ledger["native_traces"]),
            "all215_expired_setup_records_read_but_not_misjoined": len(ledger["objective_expiry_events"]),
        },
        "current_run_membership_links": run_links,
        "interpretation": [
            "All46 base losses have credited final MFE_R below the existing1R BE trigger. Monotone native MFE therefore excludes earlier activation of the existing1R BE,2R partial or3R runner in those trades; terminal stop-bar extrema remain uncredited.",
            "32 losses never reached existing0.40R progress;14 did reach it but remained below1R. Four and three winners respectively occupy those same progress ranges. This is an overlap diagnosis, not an executable future-MFE filter.",
            "Two base losses had nonnegative gross price result and became losses only after costs; neither is labeled gross price failure.",
            "Two first-held-bar protective stops leave zero completed post-entry callback opportunity. A new close-confirmed exit retaining entry/stop-first cannot preempt those stops.",
            "70 winners have a credited earlier adverse range and favorable terminal price. The ledger does not identify first adverse close, onset time, recovery time, MAE/MFE order, or what a proposed earlier exit could fill.",
            "The first execution-observable failure, stop trajectory, progress crossing times, partial and scratch scheduling need one passive native K117 trace by A. Saved terminal labels cannot supply that sequence.",
            "Known touch clocks are joined only from exact accepted K117 post-rejection traces; other origins remain unknown. Expired objective events and the old126 diagnostic are not substituted for accepted117 state provenance.",
            "Canonical longest-count and worst-amount runs are separately linked. Cost2x runs mix baseline price losses and previously profitable but cost-fragile rows; no streak is redefined away.",
        ],
        "rule_from_this_ledger": "NO_DISTINCT_CAUSAL_RULE; terminal outcome partition alone does not define a new causal exit",
        "missing_single_artifact": "K117 all117 per-bar passive exit trace with callback-before/after stop, observed progress, reservation/fill ordering and availability timestamps, joined to native accepted touch lineage.",
        "all117": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(args.input_dir)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"all117": result["rows"], "loss46": result["base_losses"],
                      "winner71": result["base_winners"], "new_policy_evaluations": 0,
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
