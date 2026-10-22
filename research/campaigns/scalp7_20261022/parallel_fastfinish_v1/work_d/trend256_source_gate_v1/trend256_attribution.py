#!/usr/bin/env python3
"""Read-only attribution of the pinned 256-row Trend Rider receipt.

No replay, prices, feature reconstruction, candidate filter, position sizing or
policy defaults. Decimal outputs are JSON strings calculated from the saved
numeric spellings; the receipt's original float metrics remain separately named.
Sum-of-trade-bps curves are diagnostic accounting curves, never portfolio NAV.

Native signature: exact_parent_repair_batch_v1.stable, and long_only evaluator
transform's receipt signature excluding receipt_sha256. The native function was
checked without importing/executing an evaluator (which can fetch market data).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path


PINS = {
    "long256": {
        "raw_sha256": "686c5574c2554867b8cdb38fcb23f2de50fa9c3837dd9406d0be4a168b976fb9",
        "receipt_sha256": "4515dfa653d0ebf25029ee6b1eb0a9a54f81c8c4f65d3fbaecc30f9efc334c70",
        "schema_version": "zel.a1.trend_rider.long_only_exact_parent_economics.v1",
        "completed_trades": 256,
        "run_id": 37989679810,
        "artifact_id": 11646670634,
        "artifact_member": "long_only_prospective.json",
    },
    "liquid123": {
        "raw_sha256": "ddeadab19a915bf43cee8534f44369cd7ff5805aacf10331a308e4201dc17028",
        "receipt_sha256": "a98f502f1b161bff5309a22bba320fd3f8725874e9303991ac8bb5f960ac0a43",
        "schema_version": "zel.a1.trend_rider.liquid6_losing_basket_guard_child.v1",
        "completed_trades": 123,
        "run_id": 37995747426,
        "artifact_id": 11647389180,
        "artifact_member": "child.json",
    },
}
HOUR_MS = 3_600_000  # Receipt's frozen 1h interval; not a research threshold.
ZERO = Decimal(0)
IDENTITY_FIELDS = ("symbol", "signal_ts", "entry_ts", "exit_ts", "side", "intent_sha")
ROW_FIELDS = {
    "config_sha", "cost_snapshot_sha", "entry", "entry_delay_bars", "entry_ts",
    "exit", "exit_ts", "feature_sha", "gross_bps", "intent_geometry",
    "intent_sha", "net_bps", "parent_entry_ts", "parent_intent_sha", "policy_sha",
    "realized_cost_bps", "reason", "side", "signal_ts", "symbol",
}
SIGNING_SOURCE = {
    "path": "backend/research/rebuild/a1_trend_rider_exact_parent_repair_batch_v1.py",
    "file_sha256": "b878606b67ed1153cbb95b8a357055b2a1824e64e2652a22e7d830552957d45d",
    "function": "stable",
    "exclusion": "receipt_sha256",
}


class InputError(ValueError):
    pass


def stable(value):
    """Exactly the native serialization, not an arbitrary JSON normalization."""
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=str,
    ).encode()).hexdigest()


def decimal(value):
    if isinstance(value, bool):
        raise InputError("BOOLEAN_IS_NOT_A_NUMBER")
    result = Decimal(str(value))
    if not result.is_finite():
        raise InputError("FINITE_NUMBER_REQUIRED")
    return result


def identity(row):
    return stable({key: row[key] for key in IDENTITY_FIELDS})


def _reject_constant(value):
    raise InputError("NONFINITE_JSON:" + value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def _verify_semantic(receipt, lane):
    pin = PINS[lane]
    if not isinstance(receipt, dict):
        raise InputError("OBJECT_REQUIRED")
    signed = stable({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    if signed != pin["receipt_sha256"] or receipt.get("receipt_sha256") != signed:
        raise InputError("RECEIPT_IDENTITY_MISMATCH:" + lane)
    if receipt.get("schema_version") != pin["schema_version"]:
        raise InputError("SCHEMA_MISMATCH:" + lane)
    rows = receipt.get("trades")
    if not isinstance(rows, list) or len(rows) != pin["completed_trades"]:
        raise InputError("COMPLETE_LEDGER_REQUIRED:" + lane)
    if receipt.get("completed_trades") != len(rows):
        raise InputError("TRADE_COUNT_MISMATCH:" + lane)
    if len({identity(row) for row in rows}) != len(rows):
        raise InputError("DUPLICATE_TRADE_IDENTITY:" + lane)


def load_verified(path, lane="long256"):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PINS[lane]["raw_sha256"]:
        raise InputError("RAW_FILE_IDENTITY_MISMATCH:" + lane)
    receipt = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    _verify_semantic(receipt, lane)
    return receipt


def net(row, multiple):
    """2x means gross - 2 * saved realized cost, never saved net - 2 * cost."""
    if multiple not in (1, 2):
        raise InputError("ONLY_SAVED_1X_AND_POSTHOC_2X_REPORTS")
    return decimal(row["gross_bps"]) - multiple * decimal(row["realized_cost_bps"])


def path_statistics(values):
    cumulative = peak = drawdown = ZERO
    streak = longest = 0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
        streak = streak + 1 if value < 0 else 0
        longest = max(longest, streak)
    return {"terminal_sum_trade_bps": cumulative,
            "maximum_drawdown_sum_trade_bps": drawdown,
            "maximum_consecutive_negative_observations": longest}


def chronology_statistics(rows, multiple):
    """Exit timestamps are bar labels, not observed execution/availability times."""
    ordered = sorted(rows, key=lambda r: (r["exit_ts"], r["entry_ts"], r["symbol"], r["intent_sha"]))
    cohorts = defaultdict(list)
    for row in rows:
        cohorts[row["exit_ts"]].append(net(row, multiple))
    original = path_statistics([net(row, multiple) for row in rows])
    original.update({"observation_unit": "one trade in receipt order",
                     "ordering": "unchanged original row order (entry order in this receipt)"})
    closed = path_statistics([net(row, multiple) for row in ordered])
    closed.update({"observation_unit": "one trade",
                   "ordering": "exit bar, entry bar, symbol, intent_sha",
                   "same_bar_order_is_arbitrary": True})
    grouped = path_statistics([sum(cohorts[ts], ZERO) for ts in sorted(cohorts)])
    grouped.update({"observation_unit": "all trades sharing an exit bar summed once",
                    "cohort_count": len(cohorts),
                    "multi_trade_cohort_count": sum(len(v) > 1 for v in cohorts.values()),
                    "within_bar_drawdown_observable": False})
    return {"original_row_order": original, "exit_bar_order_individual": closed,
            "exit_bar_cohort_net": grouped, "portfolio_NAV": False,
            "clock_caveat": "Exit bar labels do not establish intrabar fill order or outcome availability."}


def metrics(rows, multiple):
    """Pure descriptive arithmetic; the caller supplies every row."""
    with localcontext() as ctx:
        ctx.prec = 80
        gross = sum((decimal(r["gross_bps"]) for r in rows), ZERO)
        cost = sum((decimal(r["realized_cost_bps"]) for r in rows), ZERO) * multiple
        values = [net(r, multiple) for r in rows]
        positive = sum((v for v in values if v > 0), ZERO)
        negative = -sum((v for v in values if v < 0), ZERO)
        n = len(rows)
        return {"trades": n, "gross_sum_trade_bps": gross,
                "cost_sum_trade_bps": cost, "net_sum_trade_bps": sum(values, ZERO),
                "gross_per_trade_bps": gross / n if n else None,
                "cost_per_trade_bps": cost / n if n else None,
                "net_per_trade_bps": sum(values, ZERO) / n if n else None,
                "wins": sum(v > 0 for v in values), "losses": sum(v < 0 for v in values),
                "flat": sum(v == 0 for v in values),
                "win_rate": Decimal(sum(v > 0 for v in values)) / n if n else None,
                "positive_profit_trade_bps": positive, "absolute_loss_trade_bps": negative,
                "profit_factor": positive / negative if negative else None,
                "profit_factor_null_reason": "NO_NEGATIVE_OUTCOMES" if not negative else None,
                "chronology": chronology_statistics(rows, multiple)}


def _date(ts, month=False):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m" if month else "%Y-%m-%d")


def group_report(rows, field, month=False):
    groups = defaultdict(list)
    for row in rows:
        key = _date(row[field], month) if field.endswith("_ts") else row[field]
        groups[key].append(row)
    return [{"group": key, "row_identity_sha256s": [identity(r) for r in group],
             "cost_1x": metrics(group, 1), "cost_2x_posthoc": metrics(group, 2)}
            for key, group in sorted(groups.items())]


def concentration(rows, multiple):
    ranked = sorted((r for r in rows if net(r, multiple) > 0),
                    key=lambda r: (-net(r, multiple), identity(r)))
    total = sum((net(r, multiple) for r in rows), ZERO)
    positive = sum((net(r, multiple) for r in ranked), ZERO)
    result = []
    for k in (1, 3, 5, 10):
        chosen = ranked[:k]
        contribution = sum((net(r, multiple) for r in chosen), ZERO)
        result.append({"top_k": k, "actual_rows": len(chosen),
                       "row_identity_sha256s": [identity(r) for r in chosen],
                       "positive_contribution_trade_bps": contribution,
                       "share_of_positive_profit": contribution / positive if positive else None,
                       "share_of_signed_total_net": contribution / total if total else None,
                       "descriptive_leave_out_net_trade_bps": total - contribution})
    losses = sorted((r for r in rows if net(r, multiple) < 0),
                    key=lambda r: (net(r, multiple), identity(r)))
    return {"retrospective_only": True, "not_candidate_deletion": True,
            "winner_count": len(ranked), "top_winners": result,
            "worst_10_losses": [{"row_identity_sha256": identity(r),
                                  "net_trade_bps": net(r, multiple)} for r in losses[:10]]}


def _validate_long_rows(receipt):
    rows = receipt["trades"]
    sources = {r["symbol"]: r for r in receipt["source"]["symbols"]}
    if receipt["source"]["interval"] != "1h":
        raise InputError("SOURCE_CLOCK_NOT_1H")
    for row in rows:
        if set(row) != ROW_FIELDS or row["side"] != "long":
            raise InputError("ROW_SCHEMA_OR_SIDE_MISMATCH")
        geometry = row["intent_geometry"]
        if stable({k: v for k, v in geometry.items() if k != "geometry_sha256"}) != geometry["geometry_sha256"]:
            raise InputError("GEOMETRY_IDENTITY_MISMATCH")
        for key in ("symbol", "signal_ts", "side", "feature_sha", "config_sha", "policy_sha"):
            if geometry[key] != row[key]:
                raise InputError("GEOMETRY_ROW_MISMATCH:" + key)
        if geometry["intent_sha"] != row["parent_intent_sha"]:
            raise InputError("PARENT_INTENT_GEOMETRY_MISMATCH")
        if not (row["parent_entry_ts"] - row["signal_ts"] == HOUR_MS
                and row["entry_ts"] - row["parent_entry_ts"] == HOUR_MS
                and row["entry_delay_bars"] == 1
                and row["entry_ts"] <= row["exit_ts"]):
            raise InputError("TIMESTAMP_CHAIN_MISMATCH")
        source = sources[row["symbol"]]
        if not (source["first_post_boundary_ts"] <= row["signal_ts"]
                <= row["exit_ts"] <= source["last_post_boundary_ts"]):
            raise InputError("ROW_OUTSIDE_SOURCE_WINDOW")
        if geometry["tp"] is not None or geometry["timeout"] != {"bars": 48}:
            raise InputError("FROZEN_GEOMETRY_CHANGED")
        if row["reason"] == "SL" and row["exit"] != geometry["sl"]:
            raise InputError("SAVED_SL_PRICE_MISMATCH")
        if row["reason"] == "TIMEOUT" and row["exit_ts"] - row["entry_ts"] != 48 * HOUR_MS:
            raise InputError("SAVED_TIMEOUT_MISMATCH")
        if row["reason"] not in ("SL", "TIMEOUT"):
            raise InputError("UNKNOWN_EXIT_REASON")
        if decimal(row["realized_cost_bps"]) < 0:
            raise InputError("NEGATIVE_REALIZED_COST")
        # This is the original float expression; no accounting tolerance is invented.
        if row["gross_bps"] - row["realized_cost_bps"] != row["net_bps"]:
            raise InputError("NATIVE_NET_ACCOUNTING_MISMATCH")
    ids = sorted(identity(row) for row in rows)
    if stable(ids) != receipt["exact_parent_integrity"]["child_trade_identity_sha256"]:
        raise InputError("CHILD_TRADE_IDENTITY_MISMATCH")


def build_attribution(receipt):
    """Requires the exact signed 256-row receipt, never a filtered substitute."""
    _verify_semantic(receipt, "long256")
    _validate_long_rows(receipt)
    with localcontext() as ctx:
        ctx.prec = 80
        rows = receipt["trades"]
        audited = []
        for index, row in enumerate(rows):
            gross, n1, n2 = decimal(row["gross_bps"]), net(row, 1), net(row, 2)
            audited.append({
                "original_row_index": index, "row_identity_sha256": identity(row),
                "saved_row": copy.deepcopy(row),
                "retrospective_outcomes_not_execution_features": {
                    "net_1x_recomputed_trade_bps": n1, "net_2x_posthoc_trade_bps": n2,
                    "saved_net_minus_decimal_recomputed_bps": decimal(row["net_bps"]) - n1,
                    "winner_1x": n1 > 0, "winner_2x": n2 > 0,
                    "positive_gross_nonpositive_net_1x": gross > 0 and n1 <= 0,
                    "positive_net_1x_nonpositive_net_2x": n1 > 0 and n2 <= 0,
                    "entry_day_utc": _date(row["entry_ts"]),
                    "exit_bar_day_utc": _date(row["exit_ts"]),
                    "holding_bar_label_span_hours": (row["exit_ts"] - row["entry_ts"]) // HOUR_MS,
                    "entry_below_frozen_long_stop": row["entry"] < row["intent_geometry"]["sl"],
                    "MFE": None, "MAE": None, "recovery_winner": None,
                    "intrabar_fill_ts": None, "outcome_available_ts": None,
                },
            })
        cost_cross = {
            "definition": "No fitted small-profit threshold: only crossings of saved cost boundaries.",
            "gross_positive_net_1x_nonpositive": [identity(r) for r in rows if decimal(r["gross_bps"]) > 0 and net(r, 1) <= 0],
            "net_1x_positive_net_2x_nonpositive": [identity(r) for r in rows if net(r, 1) > 0 and net(r, 2) <= 0],
            "gross_positive_net_2x_nonpositive": [identity(r) for r in rows if decimal(r["gross_bps"]) > 0 and net(r, 2) <= 0],
        }
        ownership = receipt["native_policy_ownership"]
        summary = {
            "schema_version": "zel.d.trend256.saved_attribution.v1",
            "state": "SOURCE_FEATURE_BLOCKED", "candidate_state": "NO_CAUSAL_CHILD",
            "candidate_count": 0,
            "input_binding": copy.deepcopy(PINS["long256"]),
            "signature_method": SIGNING_SOURCE,
            "hash_verification_scope": "Pinned byte/content integrity, not a digital signer, certified market data or independent proof of real fills.",
            "lineage": {k: receipt[k] for k in (
                "parent_receipt_sha256", "contract_sha256", "policy_sha", "config_sha",
                "cost_authority_sha256", "evidence_sha", "boundary_utc", "prospective_boundary_utc")},
            "units": {
                "economic_values": "Unweighted sum of saved per-trade bps; no quantity, money or NAV mapping.",
                "decimal_encoding": "JSON strings, Decimal(saved numeric spelling), precision 80; native float rounding residual reported.",
                "cost_2x": "posthoc gross - 2*realized_cost_bps, not execution input, cost3, or a fresh run",
                "drawdown": "Sum-of-trade-bps accounting curves, no mark-to-market, intrabar drawdown, capital or NAV claim.",
            },
            "cost_1x": metrics(rows, 1), "cost_2x_posthoc": metrics(rows, 2),
            "native_saved_metrics": copy.deepcopy(receipt["metrics"]),
            "native_saved_net_sum_bps_decimal": sum((decimal(r["net_bps"]) for r in rows), ZERO),
            "native_saved_net_minus_recomputed_sum_bps": sum((decimal(r["net_bps"]) - net(r, 1) for r in rows), ZERO),
            "original_order_is_entry_then_symbol": rows == sorted(rows, key=lambda r: (r["entry_ts"], r["symbol"])),
            "reason_counts": dict(sorted(Counter(r["reason"] for r in rows).items())),
            "entry_below_frozen_long_stop": {
                "row_identity_sha256s": [identity(r) for r in rows if r["entry"] < r["intent_geometry"]["sl"]],
                "handling": "Original rows and stop-touch economics preserved. This geometry can book a positive SL; no gap repricing, repair or exclusion performed.",
            },
            "concentration_1x": concentration(rows, 1),
            "concentration_2x_posthoc": concentration(rows, 2),
            "cost_crossings": cost_cross,
            "all_closed_rows_preserved": {
                "count": len(rows), "child_trade_identity_sha256": stable(sorted(identity(r) for r in rows)),
                "all_1x_winner_identity_sha256s": [identity(r) for r in rows if net(r, 1) > 0],
                "all_2x_winner_identity_sha256s": [identity(r) for r in rows if net(r, 2) > 0],
                "candidate_retention_or_improvement_claim": False,
            },
            "inherited_parent_scope_not_closed_long_subset": {
                "native_policy_ownership": copy.deepcopy(ownership),
                "open_intents_count": len(receipt["open_intents"]),
                "rejected_intents_count": len(receipt["ownership_rejected_intents"]),
                "open_intents": copy.deepcopy(receipt["open_intents"]),
                "open_intents_hash_matches_native": stable(receipt["open_intents"]) == ownership["open_intents_sha256"],
                "rejected_intents_hash_matches_native": stable(receipt["ownership_rejected_intents"]) == ownership["rejected_intents_sha256"],
                "scope": "Copied parent 301 closed + 1 open + 1889 rejected; not 256 long-only admission outcomes. No PnL assigned to open/rejected rows.",
            },
            "source_feature_gate": {
                "available": ["sealed parent signal geometry", "signal/parent-entry/delayed-entry/exit bar labels", "entry/exit price", "gross/net/realized cost", "identity hashes"],
                "missing": ["feature values and available_ts at the original signal", "prior-completed BTC/ETH trend/volatility features", "signal close and feature provenance needed for entry-chase", "holding OHLC path", "MFE/MAE/recovery trace", "intrabar fill/stop/partial lifecycle and outcome available_ts", "full child admission/rejection chronology after changed exits or entries"],
                "feature_hash_is_feature_values": False,
                "recovery_classification": "UNKNOWN_ALL_256",
                "all_winner_recovery_status": "UNKNOWN; final win and TIMEOUT do not prove recovery or safe early exit",
                "exit_clock": "Native evaluator stores exit bar open ts. SL uses that bar low/high; TIMEOUT uses that bar close. Neither gives actual intrabar availability.",
                "native_execution_model_caveat": "Saved delayed evaluator fills at sealed stop on touch and at timeout close; it records no separate gap/partial/stop-update events. Do not upgrade this to a real-fill guarantee.",
                "group_labels_are_runtime_inputs": False,
            },
            "by_reason_retrospective": group_report(rows, "reason"),
            "by_symbol_retrospective": group_report(rows, "symbol"),
            "execution_authority": "NONE", "order_authority": "BLOCKED",
            "new_price_feature_calculation": False, "economic_replay": False,
        }
        daily = {"retrospective_only": True, "entry_day_utc": group_report(rows, "entry_ts"),
                 "exit_bar_day_utc": group_report(rows, "exit_ts")}
        monthly = {"retrospective_only": True, "entry_month_utc": group_report(rows, "entry_ts", True),
                   "exit_bar_month_utc": group_report(rows, "exit_ts", True)}
        return {"SUMMARY.json": summary, "ROWS_AUDIT.json": audited,
                "DAILY_OUTCOMES.json": daily, "MONTHLY_OUTCOMES.json": monthly}


def liquid_identity_note(receipt):
    _verify_semantic(receipt, "liquid123")
    return {"input_binding": copy.deepcopy(PINS["liquid123"]),
            "native_saved_metrics": copy.deepcopy(receipt["metrics"]),
            "portfolio_risk_budget": copy.deepcopy(receipt["portfolio_risk_budget"]),
            "portfolio_risk_scales_in_rows": sorted({str(r["portfolio_risk_scale"]) for r in receipt["trades"]}),
            "economic_units": "Saved gross/net/realized_cost_bps are scaled; instrument_* fields are separate unscaled values.",
            "merged_with_long256": False, "overlap_or_blend_reconstructed": False}


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def run(long_path, output_dir, liquid_path=None):
    long_receipt = load_verified(long_path)
    reports = build_attribution(long_receipt)
    if liquid_path is not None:
        reports["SUMMARY.json"]["liquid123_separate_identity_only"] = liquid_identity_note(load_verified(liquid_path, "liquid123"))
    output_dir = Path(output_dir)
    # An existing directory, including an empty one, is never reused.
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, content in reports.items():
        with (output_dir / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2,
                                    allow_nan=False, default=_json_default) + "\n")
    return reports["SUMMARY.json"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long-only-receipt", type=Path, required=True)
    parser.add_argument("--liquid-receipt", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = run(args.long_only_receipt, args.output_dir, args.liquid_receipt)
    print(json.dumps({"state": summary["state"], "candidate_state": summary["candidate_state"],
                      "trades": summary["cost_1x"]["trades"], "output_dir": str(args.output_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
