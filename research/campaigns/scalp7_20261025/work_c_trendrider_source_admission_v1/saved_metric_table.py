#!/usr/bin/env python3
"""Reconcile sealed saved ledgers; never import a strategy or run an evaluation.

Only Gross, modeled Cost, Net1 and Net2 arithmetic and saved-row group sums are
derived. PF/WR/DD/streak/R and top-two removal remain copied historical metrics.
Those old metrics have unresolved clock/fill defects and are not validated profit.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

SCHEMA = "zel.work_c.trendrider.saved_metric_accounting.v1"
FILES = {"result": "RESULT.json", "robustness": "ROBUSTNESS.json",
         "traces": "TRACES.json.gz", "failed_filter": "repair_diagnostics_v1/MECHANISM_FIX_RESULT.json"}
FROZEN_SHA256 = {
    "result": "e99bbd783908628572a64875f7d019676fa5d686fdc7e7b29fd24cee2d4fab13",
    "robustness": "d3f716800de6665df0ce0465776bdb938227cf9803d9f1c1fb279d5ddc494cb3",
    "traces": "bc20d7e6b2f931cad8c5cd020fd3b396370dbf80e0bf746dd0fa1330f7e80239",
    "failed_filter": "bdb1883ada490891c17e9980988f4b3b2063cec11dd7d3be257d2519a4393a0e",
}
STAGES = ("S0", "S1", "S2", "S3", "S4")
TOLERANCE = 1e-7
COPIED_METRICS = (
    "PF2_opportunity", "WR2_opportunity", "DD2_realized_exit_leg_bps",
    "max_loss_streak_opportunity", "max_loss_streak_leg",
    "worst_loss_R_from_long_risk", "max_win_R_from_long_risk",
    "Net2_excluding_top2_bps", "largest_2_opportunity_winners_bps",
    "largest_loss_opportunity_bps",
)
ARITHMETIC_FIELDS = ("gross_bps_sum", "modeled_cost_bps_sum", "net1_bps_sum", "net2_bps_sum")


class AccountingError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise AccountingError(reason)


def number(value, name):
    require(type(value) in (int, float) and math.isfinite(value), "FINITE_NUMBER_REQUIRED:" + name)
    return float(value)


def integer(value, name):
    require(type(value) is int and value >= 0, "NONNEGATIVE_INTEGER_REQUIRED:" + name)
    return value


def same(actual, expected, name):
    if type(actual) in (int, float) and type(expected) in (int, float):
        require(abs(number(actual, name) - number(expected, name)) <= TOLERANCE, "RECONCILIATION_MISMATCH:" + name)
    elif isinstance(actual, dict) and isinstance(expected, dict):
        require(set(actual) == set(expected), "RECONCILIATION_KEYS_MISMATCH:" + name)
        for key in actual:
            same(actual[key], expected[key], name + "." + key)
    else:
        require(type(actual) is type(expected) and actual == expected, "RECONCILIATION_MISMATCH:" + name)


def decode_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "DUPLICATE_JSON_KEY:" + key)
            value[key] = item
        return value
    def nonfinite(value):
        raise AccountingError("NONFINITE_JSON:" + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def copied_metrics(metrics):
    output = {}
    for key in COPIED_METRICS:
        value = metrics[key]
        if value is not None:
            number(value, key)
        output[key] = deepcopy(value)
    return output


def explicit_window(window_bounds):
    require(window_bounds is None,
            "ELIGIBLE_WINDOW_UNBOUND:THIS_ISOLATED_AUDIT_ACCEPTS_ONLY_NONE_AND_CANNOT_REPORT_RATES")
    return None


def rates():
    return {"opportunities_per_day": None, "legs_per_day": None,
            "rate_state": "UNBOUND_NO_EXPLICIT_WINDOW_NO_SOURCE_LAST_BAR_CLOSURE"}


def stage_row(stage, saved, trace):
    accepted, rejected = trace["accepted"], trace["rejected"]
    require(isinstance(accepted, list) and isinstance(rejected, list), "SEALED_STAGE_LISTS_REQUIRED:" + stage)
    keys, rejected_keys, leg_keys = set(), set(), set()
    gross = cost = net2 = 0.0
    by_symbol, by_month = defaultdict(float), defaultdict(float)
    legs_count = long_count = short_count = 0
    for opportunity in accepted:
        key, symbol = opportunity["key"], opportunity["symbol"]
        signal_ts = integer(opportunity["signal_ts"], "signal_ts")
        require(key == f"{symbol}|long|{signal_ts}", "OPPORTUNITY_KEY_IDENTITY:" + stage)
        require(key not in keys, "DUPLICATE_OPPORTUNITY_KEY:" + stage + ":" + key)
        keys.add(key)
        require(isinstance(opportunity["legs"], list) and opportunity["legs"], "SEALED_LEGS_REQUIRED:" + key)
        opportunity_net2 = 0.0
        for leg in opportunity["legs"]:
            require(leg["opportunity_key"] == key and leg["symbol"] == symbol, "LEG_PARENT_IDENTITY:" + key)
            identity = (key, leg["kind"], leg["side"], integer(leg["entry_ts"], "leg.entry_ts"),
                        integer(leg["exit_bar_ts"], "leg.exit_bar_ts"))
            require(identity not in leg_keys, "DUPLICATE_SEALED_LEG:" + key)
            leg_keys.add(identity)
            require((leg["kind"], leg["side"]) in (("PRIMARY_LONG", "long"), ("REVERSAL_SHORT", "short")),
                    "UNKNOWN_SEALED_LEG_KIND:" + key)
            g = number(leg["gross_bps"], "gross_bps")
            c = number(leg["modeled_cost_bps"], "modeled_cost_bps")
            n2 = number(leg["Net2_bps"], "leg.Net2_bps")
            require(c >= 0, "NEGATIVE_MODELED_COST")
            same(n2, g - 2 * c, stage + ":LEG_NET2_IDENTITY:" + key)
            gross += g
            cost += c
            net2 += n2
            opportunity_net2 += n2
            legs_count += 1
            long_count += leg["side"] == "long"
            short_count += leg["side"] == "short"
        same(opportunity_net2, opportunity["Net2_bps"], stage + ":OPPORTUNITY_NET2:" + key)
        month = datetime.fromtimestamp(signal_ts / 1000, timezone.utc).strftime("%Y-%m")
        by_symbol[symbol] += opportunity_net2
        by_month[month] += opportunity_net2
    for item in rejected:
        key = item["key"]
        require(key not in rejected_keys and key not in keys, "DUPLICATE_OR_ACCEPTED_REJECTION:" + stage)
        rejected_keys.add(key)
    same(len(keys), saved["accepted_opportunities"], stage + ":ACCEPTED_COUNT")
    same(legs_count, saved["total_legs"], stage + ":LEG_COUNT")
    same(long_count, saved["long_legs"], stage + ":LONG_COUNT")
    same(short_count, saved["reverse_short_legs"], stage + ":SHORT_COUNT")
    same(net2, saved["Net2_sum_trade_bps"], stage + ":SAVED_NET2")
    same(net2, gross - 2 * cost, stage + ":TOTAL_NET2_IDENTITY")
    same(dict(by_month), saved["by_month_Net2"], stage + ":SIGNAL_MONTH_NET2")
    admissions = saved["admissions"]
    for name, value in (("accepted", len(keys)), ("rejected", len(rejected_keys)),
                        ("available_source_opportunities", len(keys) + len(rejected_keys))):
        same(value, admissions[name], stage + ":ADMISSION_COUNT:" + name)
    row = {"stage": stage, "classification": "HISTORICAL_USED_DEV_SAVED_ACCOUNTING_ONLY",
           "economic_status": "CLOCK_AND_FILL_DEFECTS_UNRESOLVED_NOT_VALIDATED_PROFIT",
           "accepted_opportunities": len(keys), "total_legs": legs_count,
           "long_legs": long_count, "reverse_short_legs": short_count,
           "rejected_opportunities": len(rejected_keys), "gross_bps_sum": gross,
           "modeled_cost_bps_sum": cost, "net1_bps_sum": gross - cost, "net2_bps_sum": net2,
           "copied_saved_metrics": copied_metrics(saved),
           "by_symbol_net2_bps": dict(sorted(by_symbol.items())),
           "by_signal_month_net2_bps": dict(sorted(by_month.items())),
           "saved_admissions": deepcopy(admissions), "comparison_vs_S0": None,
           "sealed_accounting_reconciled": True, **rates()}
    return row, keys


def build_table(result, robustness, traces, failed_filter, *, result_sha256=None, window_bounds=None):
    """Pure saved-value accounting; no execution, admission model, or R invention."""
    require(result["schema"] == "zel.trendrider.unified_one_owner_causal_rescue.result.v1", "RESULT_SCHEMA")
    require(robustness["schema"] == "zel.trendrider.unified_rescue.robustness.v1", "ROBUSTNESS_SCHEMA")
    require(traces["schema"] == "zel.trendrider.unified.causal_exit_trace.v1", "TRACES_SCHEMA")
    require(failed_filter["schema"] == "zel.trendrider.unified.stop_cost_screen_result.v1", "FILTER_SCHEMA")
    require(set(result["stage_economics"]) == set(STAGES) and set(traces["stages"]) == set(STAGES), "ALL_S0_S4_STAGES_REQUIRED")
    same(result["freeze_sha256"], robustness["source_freeze_sha256"], "ROBUSTNESS_FREEZE")
    same(result["freeze_sha256"], traces["freeze_sha256"], "TRACE_FREEZE")
    if result_sha256 is not None:
        same(robustness["source_result_sha256"], result_sha256, "ROBUSTNESS_RESULT_BYTES")
    require(robustness["fully_new_unseen_OOS"] is False and robustness["realized_broker_fee_funding"] is False,
            "HISTORICAL_UNKNOWN_EXECUTION_SCOPE_CHANGED")
    require(failed_filter["fresh_prospective"] is False and failed_filter["actual_fee_unknown"] is True,
            "FILTER_HISTORICAL_SCOPE_CHANGED")
    require(traces["not_canonical_trade_ledger"] is True and traces["live_order_authority"] == "BLOCKED", "TRACE_AUTHORITY_CHANGED")
    window = explicit_window(window_bounds)
    rows, accepted_keys = [], {}
    for stage in STAGES:
        row, keys = stage_row(stage, result["stage_economics"][stage], traces["stages"][stage])
        rows.append(row)
        accepted_keys[stage] = keys
    source_counts = result["source_inputs"]["counts"]
    population = integer(source_counts["LIQUID_SELECTED"], "LIQUID_SELECTED") + integer(source_counts["DELAYED_SELECTED"], "DELAYED_SELECTED")
    for row in rows:
        same(row["accepted_opportunities"] + row["rejected_opportunities"], population, row["stage"] + ":SOURCE_POPULATION")
    require(set(result["opportunity_comparison"]) == set(STAGES[1:]), "ALL_SAVED_COMPARISONS_REQUIRED")
    for row in rows[1:]:
        stage = row["stage"]
        comparison = result["opportunity_comparison"][stage]
        same(comparison["common_T"], len(accepted_keys[stage] & accepted_keys["S0"]), stage + ":COMMON_T")
        same(comparison["new_accepted_original_opportunities_T"], len(accepted_keys[stage] - accepted_keys["S0"]), stage + ":NEW_ACCEPTED_T")
        same(comparison["original_admissions_lost"], len(accepted_keys["S0"] - accepted_keys[stage]), stage + ":LOST_ADMISSION_T")
        row["comparison_vs_S0"] = deepcopy(comparison)
    for label, metrics, stage in (("ROBUSTNESS_BASELINE", robustness["baseline_metrics"], "S0"),
                                  ("ROBUSTNESS_FULL", robustness["full_metrics"], "S4"),
                                  ("FAILED_FILTER_BASE", failed_filter["base_S4"], "S4")):
        for key, value in metrics.items():
            same(value, result["stage_economics"][stage][key], label + ":" + key)
    filtered = failed_filter["one_axis_S4"]
    filter_row = {"stage": "S4_PR1471_FAILED_FILTER_SAVED", "classification": "FAILED_FILTER_HISTORICAL_SAVED_METRICS_ONLY",
                  "economic_status": "RETIRED_FAILED_FILTER_NOT_NEW_EVALUATION",
                  "accepted_opportunities": integer(filtered["accepted_opportunities"], "filter.accepted"),
                  "total_legs": integer(filtered["total_legs"], "filter.legs"),
                  "long_legs": integer(filtered["long_legs"], "filter.long"),
                  "reverse_short_legs": integer(filtered["reverse_short_legs"], "filter.short"),
                  "rejected_opportunities": None, "gross_bps_sum": None, "modeled_cost_bps_sum": None,
                  "net1_bps_sum": None, "net2_bps_sum": number(filtered["Net2_sum_trade_bps"], "filter.Net2"),
                  "copied_saved_metrics": copied_metrics(filtered), "by_symbol_net2_bps": None,
                  "by_signal_month_net2_bps": deepcopy(filtered["by_month_Net2"]),
                  "group_sum_basis": "SAVED_FILTER_MONTH_METRICS_NO_FILTER_SEALED_LEGS",
                  "sealed_accounting_reconciled": False,
                  "missing": "FILTER_SEALED_LEGS_NOT_IN_SUPPLIED_ARTIFACT; GROSS_COST_NET1_SYMBOL_SUMS_UNKNOWN",
                  "comparison_vs_saved_S4": {key: deepcopy(failed_filter[key]) for key in
                      ("cost_stop_preentry_rejected_T", "original_S4_acceptances_removed_by_filter_T",
                       "removed_prior_winners_T", "removed_prior_winner_net2")},
                  **rates()}
    same(sum(number(value, "filter.month") for value in filtered["by_month_Net2"].values()),
         filter_row["net2_bps_sum"], "FILTER_SAVED_MONTH_SUM")
    rows.append(filter_row)
    rows.append({"stage": "S4_REALISTIC_NEW_SOURCE", "classification": "NOT_RUN",
                 "economic_status": "NOT_RUN", "accepted_opportunities": None, "total_legs": None,
                 "long_legs": None, "reverse_short_legs": None, "rejected_opportunities": None,
                 **{key: None for key in ARITHMETIC_FIELDS},
                 "copied_saved_metrics": {key: None for key in COPIED_METRICS},
                 "by_symbol_net2_bps": None, "by_signal_month_net2_bps": None,
                 "opportunities_per_day": None, "legs_per_day": None, "rate_state": "NOT_RUN",
                 "sealed_accounting_reconciled": False})
    return {"schema": SCHEMA, "state": "SAVED_LEDGER_ACCOUNTING_ONLY_NOT_NEW_EVALUATION",
            "rows": rows, "source_counts_copied": deepcopy(source_counts),
            "units": {"bps": "SUM_OF_SEALED_ONE_THIRD_NOTIONAL_NORMALIZED_TRADE_BPS_NOT_ACCOUNT_NAV_RETURN",
                      "exposure_weight": "1/3_ALREADY_APPLIED_IN_SAVED_LEGS_DO_NOT_RESCALE",
                      "gross_cost_net": "GROSS_AND_MODELED_COST_FROM_SEALED_LEGS; NET1=GROSS-COST; NET2=GROSS-2COST",
                      "R": "COPIED_ORIGINAL_LONG_RISK_GEOMETRY_R; NOT_EXECUTABLE_ACCOUNT_RISK; NO_NEW_R_DERIVED",
                      "DD": "COPIED_SAVED_REALIZED_EXIT_LEG_BPS_DD_NOT_ACCOUNT_EQUITY_DRAWDOWN",
                      "WR_PF_streak": "COPIED_OPPORTUNITY_METRICS_EXCEPT_EXPLICIT_LEG_STREAK",
                      "month": "UTC_SIGNAL_MONTH_NOT_EXIT_MONTH",
                      "cost": "RESEARCH_MODEL_NOT_ACTUAL_FEE_OR_SIGNED_HISTORICAL_FUNDING"},
            "metric_provenance": {"derived": list(ARITHMETIC_FIELDS) + ["by_symbol_net2_bps", "by_signal_month_net2_bps"],
                                  "copied": list(COPIED_METRICS), "saved_metrics_recomputed": False},
            "window_bounds": window, "window_inferred_from_trades": False,
            "source_timing_copied": deepcopy(result["source_timing"]),
            "source_last_1h_bar_closure": "UNBOUND_NOT_ESTABLISHED_BY_SEEN_TO_TIMESTAMP",
            "fully_new_unseen_OOS": False, "realized_broker_fee_funding": False,
            "new_economic_run_eligible": False, "economic_runs": 0, "market_api_calls": 0,
            "strategy_modules_imported": False, "orders": 0,
            "limitations": [result["limitation"], "Saved timing, short-horizon and fill defects are not repaired by accounting reconciliation.",
                            "Failed-filter symbol leave-one-out values are replay ablations, not by-symbol contributions; they are not relabeled."]}


def audit_paths(result, robustness, traces, failed_filter, *, expected_sha256=None, window_bounds=None):
    expected = FROZEN_SHA256 if expected_sha256 is None else expected_sha256
    require(isinstance(expected, dict) and set(expected) == set(FILES), "EXACT_FOUR_INPUT_SHA_MANIFEST_REQUIRED")
    paths = dict(result=result, robustness=robustness, traces=traces, failed_filter=failed_filter)
    raw = {}
    # All four byte pins must pass before any JSON or gzip is parsed.
    for key, path in paths.items():
        require(isinstance(expected[key], str) and len(expected[key]) == 64, "INVALID_EXPECTED_SHA:" + key)
        raw[key] = Path(path).read_bytes()
        require(hashlib.sha256(raw[key]).hexdigest() == expected[key], "INPUT_SHA256_MISMATCH:" + key)
    parsed = {key: decode_json(gzip.decompress(value) if key == "traces" else value) for key, value in raw.items()}
    report = build_table(**parsed, result_sha256=expected["result"], window_bounds=window_bounds)
    report["input_sha256"] = dict(expected)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--expected-sha256-manifest", type=Path, help="optional explicit exact four-file SHA map")
    parser.add_argument("--output", type=Path, required=True, help="new JSON only; refuses overwrite")
    args = parser.parse_args(argv)
    try:
        expected = decode_json(args.expected_sha256_manifest.read_bytes()) if args.expected_sha256_manifest else None
        report = audit_paths(**{key: args.input_root / name for key, name in FILES.items()},
                             expected_sha256=expected)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
        print(json.dumps({"state": report["state"], "rows": len(report["rows"]), "economic_runs": 0}))
        return 0
    except (AccountingError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"state": "SAVED_ACCOUNTING_BINDING_FAILED", "error": str(error), "economic_runs": 0}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
