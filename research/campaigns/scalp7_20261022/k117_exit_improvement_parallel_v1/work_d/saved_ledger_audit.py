"""Hash-pinned K117 saved-row audit. No price import, strategy replay or mutation."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import math

HERE = Path(__file__).resolve().parent
CONTRACT = json.loads((HERE / "exact117_input_contract.json").read_text())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def key(row):
    return (row["symbol"], int(row["side"]), int(row["signal_ts_ms"]))


def close_bps(a, b):
    return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-8)


def checked_inputs(directory):
    directory = Path(directory)
    data = {}
    for name, digest in CONTRACT["input_sha256"].items():
        raw = (directory / name).read_bytes()
        if sha(raw) != digest:
            raise ValueError("PINNED_INPUT_CHANGED:" + name)
        data[name] = raw
    rows_raw = gzip.decompress(data["ROWS.json.gz"])
    if sha(rows_raw) != CONTRACT["rows_uncompressed_sha256"]:
        raise ValueError("UNCOMPRESSED_ROWS_CHANGED")
    summary = json.loads(data["SUMMARY.json"])
    freeze = json.loads(data["EXECUTION_FREEZE.json"])
    if summary["rows_sha256"] != sha(rows_raw) or summary["candidate"] != CONTRACT["identity"] or freeze["candidate"] != CONTRACT["identity"]:
        raise ValueError("BASELINE_IDENTITY_OR_ROW_BINDING_CHANGED")
    if freeze["owner"] != CONTRACT["owner"]:
        raise ValueError("OWNER_MISMATCH")
    return json.loads(rows_raw), summary, freeze


def _initial_risk(row):
    sig = row["signal"]
    entry = row["entry_prices"][row["symbol"]]
    risk = row["side"] * (entry - sig["stop_price"])
    if risk <= 0:
        risk = sig["meta"]["fallback_stop_atr_mult"] * sig["meta"]["atr_price"]
    if risk <= 0:
        raise ValueError("NONPOSITIVE_INITIAL_RISK")
    return risk


def build_evidence(payload, summary):
    """All117 coverage; final outcomes below are explicitly retrospective labels."""
    rows, rawrows = payload["trades"], payload["raw_trades"]
    if len(rows) != CONTRACT["expected_rows"] or len(rawrows) != CONTRACT["expected_rows"]:
        raise ValueError("EXACT117_REQUIRED")
    if payload["unresolved"] or payload["boundary_excluded"]:
        raise ValueError("BASELINE_RESOLUTION_CHANGED")
    rawmap = {key(row): row for row in rawrows}
    if len(rawmap) != 117 or len({key(row) for row in rows}) != 117 or set(rawmap) != {key(row) for row in rows}:
        raise ValueError("LIFECYCLE_KEY_SET_MISMATCH")
    carrymap = {}
    for item in payload["carry_scenario"]:
        k = tuple(item["key"])
        if k not in rawmap or k in carrymap:
            raise ValueError("CARRY_KEY_MISMATCH")
        carrymap[k] = item
    exported = []
    for row in rows:
        k = key(row); original = rawmap[k]; sig = row["signal"]
        if row["management_comparison_identity"] != CONTRACT["identity"] or row["identity"] != CONTRACT["lineage_identity"]:
            raise ValueError("CURRENT117_IDENTITY_MISMATCH")
        if row["partition"] != "rolling" or row["execution_profile"] != "UTC_NEXT_OPEN_STOP_FIRST_GAPS_UNRESOLVED_V2":
            raise ValueError("EXECUTION_CONTRACT_MISMATCH")
        if not sig["meta"]["feature_available_ts_ms"] <= row["signal_ts_ms"] <= row["entry_ts_ms"] <= row["exit_ts_ms"] <= row["outcome_available_ts_ms"]:
            raise ValueError("CAUSAL_CLOCK_MISMATCH")
        frozen = float(sig["meta"]["frozen_cost_bps"])
        rawcost = float(original["cost_bps"])
        extra = float(carrymap[k]["extra_bps"]) if k in carrymap else 0.0
        if extra < 0 or not close_bps(frozen, rawcost) or not close_bps(row["cost_bps"], rawcost + extra):
            raise ValueError("REFERENCE_OR_CARRY_COST_MISMATCH")
        if not close_bps(row["gross_bps"], original["gross_bps"]):
            raise ValueError("RAW_GROSS_CHANGED")
        net1 = row["gross_bps"] - row["cost_bps"]
        net2 = row["gross_bps"] - 2 * row["cost_bps"]
        if not close_bps(net1, row["net_bps"]):
            raise ValueError("NET_RECONCILIATION_FAILED")
        entry = row["entry_prices"][row["symbol"]]
        exit_price = row["exit_prices"][row["symbol"]]
        expected_be = entry * (1 + row["side"] * (frozen + 2.0) / 10000)
        price_match = math.isclose(exit_price, expected_be, rel_tol=1e-12, abs_tol=1e-12)
        terminal_gross = row["side"] * (exit_price / entry - 1) * 10000
        be_terminal = row["reason"] == "STOP_FIRST" and row["mfe_R"] >= sig["meta"]["be_arm_r"] and price_match
        cross = net1 > 0 and net2 < 0
        item = {
            "trade_key": list(k), "window_label": row["window_label"],
            "entry_known": {"signal_ts_ms": row["signal_ts_ms"], "signal_open_ts_ms": row["signal_open_ts_ms"],
                "entry_ts_ms": row["entry_ts_ms"], "feature_available_ts_ms": sig["meta"]["feature_available_ts_ms"],
                "side": row["side"], "entry_price": entry, "initial_stop": sig["stop_price"],
                "initial_risk_price": _initial_risk(row), "BE_arm_R_existing": sig["meta"]["be_arm_r"],
                "partial_fraction_existing": sig["partial_fraction"], "partial_target_R_existing": sig["partial_take_profit_r"],
                "frozen_reference_cost_bps": frozen},
            "outcome_labels_NOT_EXECUTION_FEATURES": {"exit_ts_ms": row["exit_ts_ms"],
                "outcome_available_ts_ms": row["outcome_available_ts_ms"], "reason": row["reason"],
                "exit_price": exit_price, "observed_final_mfe_R": row["mfe_R"], "observed_final_mae_R": row["mae_R"],
                "gross_bps": row["gross_bps"], "net1x_bps": net1, "net2x_bps_posthoc": net2,
                "cost_cross_1x_winner_2x_loser": cross,
                "winner_cohort": "large_existing_mfe_R_ge2" if net1 > 0 and row["mfe_R"] >= 2 else "ordinary" if net1 > 0 else "loss"},
            "cost_separation": {"entry_frozen_reference_bps": frozen, "raw_engine_reference_bps": rawcost,
                "extra_carry_scenario_bps": extra, "final_total_cost_bps": row["cost_bps"],
                "carry_detail": deepcopy(carrymap.get(k)), "cost2x_is_posthoc_not_BE_input": True},
            "terminal_BE_formula_evidence": {"formula_price": expected_be, "exit_price_matches_formula": price_match,
                "STOP_FIRST_with_observed_1R_and_formula_match": be_terminal,
                "terminal_no_partial_gross_bps": terminal_gross,
                "terminal_price_match_is_not_arm_or_stop_update_trace": True},
            "required_native_trace": {"BE_first_arm_ts_ms": None, "BE_next_stop_activation_ts_ms": None,
                "actual_effective_stop_bar_ms": None, "partial_fill_events": None,
                "runner_activation_ts_ms": None, "terminal_precedence_trace": None,
                "status": "NOT_IN_SAVED_LEDGER_PASSIVE_OBSERVER_REQUIRED"},
        }
        exported.append(item)
    crossrows = [r for r in exported if r["outcome_labels_NOT_EXECUTION_FEATURES"]["cost_cross_1x_winner_2x_loser"]]
    be_cross = [r for r in crossrows if r["terminal_BE_formula_evidence"]["STOP_FIRST_with_observed_1R_and_formula_match"]]
    two_bps = [r for r in be_cross if close_bps(r["outcome_labels_NOT_EXECUTION_FEATURES"]["net1x_bps"], 2.0)]
    other_be = [r for r in be_cross if r not in two_bps]
    inferred = []
    for item in other_be:
        entry = item["entry_known"]
        terminal = item["terminal_BE_formula_evidence"]["terminal_no_partial_gross_bps"]
        fraction = entry["partial_fraction_existing"]
        partial_full_position_bps = entry["partial_target_R_existing"] * entry["initial_risk_price"] / entry["entry_price"] * 10000
        realized = fraction * partial_full_position_bps
        remaining = 1 - fraction
        implied_gross = realized + remaining * terminal
        inferred.append({"trade_key": item["trade_key"], "classification": "CONFIGURED_PARTIAL_ALGEBRA_INFERENCE_NOT_EVENT_TRACE",
            "assumed_single_partial_fraction": fraction, "assumed_remaining_fraction": remaining,
            "inferred_realized_gross_bps": realized, "remaining_terminal_gross_bps": remaining * terminal,
            "implied_total_gross_bps": implied_gross,
            "saved_gross_bps": item["outcome_labels_NOT_EXECUTION_FEATURES"]["gross_bps"],
            "matches_saved_gross_with_float_tolerance": close_bps(implied_gross, item["outcome_labels_NOT_EXECUTION_FEATURES"]["gross_bps"]),
            "partial_fill_time_or_event_observed": False})
    remaining_three = [r for r in crossrows if r not in be_cross]
    groups = Counter(r["outcome_labels_NOT_EXECUTION_FEATURES"]["winner_cohort"] for r in exported)
    if (len(crossrows), len(be_cross), len(two_bps), len(other_be), len(remaining_three)) != (28, 25, 24, 1, 3):
        raise ValueError("PINNED_COST_CROSS_COHORT_CHANGED")
    if groups != {"large_existing_mfe_R_ge2": 36, "ordinary": 35, "loss": 46}:
        raise ValueError("PINNED_WINNER_COHORT_CHANGED")
    return {"schema": "zel.work_d.k117.saved_ledger_evidence.v1",
        "classification": CONTRACT["output_classification"], "baseline_commit": CONTRACT["baseline_commit"],
        "identity": CONTRACT["identity"], "input_contract_sha256": sha((HERE / "exact117_input_contract.json").read_bytes()),
        "input_sha256": deepcopy(CONTRACT["input_sha256"]), "rows_uncompressed_sha256": CONTRACT["rows_uncompressed_sha256"],
        "baseline_metrics_quoted_unchanged": deepcopy(summary["child"]),
        "K126_large34_preservation_quoted_from_summary_not_recomputed": deepcopy(summary["cohorts"]["large_winners"]),
        "all117_coverage": {"T": 117, "win1x": 71, "loss1x": 46, "win2x": sum(r["outcome_labels_NOT_EXECUTION_FEATURES"]["net2x_bps_posthoc"] > 0 for r in exported),
            "loss2x": sum(r["outcome_labels_NOT_EXECUTION_FEATURES"]["net2x_bps_posthoc"] < 0 for r in exported),
            "winner_categories": dict(groups), "terminal_BE_formula_match_T_all117": sum(r["terminal_BE_formula_evidence"]["STOP_FIRST_with_observed_1R_and_formula_match"] for r in exported)},
        "cost_cross_28": {"T": len(crossrows), "net1x_trade_bps": sum(r["outcome_labels_NOT_EXECUTION_FEATURES"]["net1x_bps"] for r in crossrows),
            "net2x_trade_bps_posthoc": sum(r["outcome_labels_NOT_EXECUTION_FEATURES"]["net2x_bps_posthoc"] for r in crossrows),
            "keys": [r["trade_key"] for r in crossrows], "BE_terminal_match_T": len(be_cross), "approximately_plus2_T": len(two_bps),
            "BE_terminal_keys": [r["trade_key"] for r in be_cross], "approximately_plus2_keys": [r["trade_key"] for r in two_bps],
            "one_partial_algebra_inference": inferred,
            "remaining_three": [{"key": r["trade_key"], **r["outcome_labels_NOT_EXECUTION_FEATURES"]} for r in remaining_three]},
        "winner_counterexample_scope": {"all71_winner_keys": [r["trade_key"] for r in exported if r["outcome_labels_NOT_EXECUTION_FEATURES"]["net1x_bps"] > 0],
            "large36_keys": [r["trade_key"] for r in exported if r["outcome_labels_NOT_EXECUTION_FEATURES"]["winner_cohort"] == "large_existing_mfe_R_ge2"],
            "ordinary35_keys": [r["trade_key"] for r in exported if r["outcome_labels_NOT_EXECUTION_FEATURES"]["winner_cohort"] == "ordinary"],
            "recovery_after_tighter_exit": "NOT_IDENTIFIABLE_FROM_FINAL_ROWS; requires causal native trace plus A counterfactual chronology",
            "saved_MFE_is_not_executable_capture": True},
        "rows": exported, "new_candidate": 0, "price_replays": 0, "new_economic_comparisons": 0,
        "event_trace_executed": False, "account_NAV_claim": False,
        "conclusion": "Existing BE includes frozen reference cost. Terminal-price algebra alone shows no proven accounting defect and does not justify cost2x buffer tightening."}


def audit(directory):
    payload, summary, _ = checked_inputs(directory)
    return build_evidence(payload, summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(args.baseline_dir)
    with Path(args.output).open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": args.output, "T": len(result["rows"]), "new_candidate": 0, "price_replays": 0}))


if __name__ == "__main__":
    main()
