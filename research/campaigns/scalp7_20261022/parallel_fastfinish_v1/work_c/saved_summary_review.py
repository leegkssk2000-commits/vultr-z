#!/usr/bin/env python3
"""Read immutable A4 saved receipts; never import an evaluator or collect prices.

Outcome arithmetic and aggregate-inferred membership are retrospective diagnostics,
not source admission records, new signals, policy conditions, or a replay.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT_SHA256 = "5018f26c115a89bf69b3d3cccf0f7ccaac42bb3083bb2d3a6cc4360bb1fa9619"
BATCH_SHA256 = "1c979597753e5f4a1490632df43295f9e2d49991ca46ec6550de0537e050bd89"
PARENT_RECEIPT = "9edb8d722b985af9e6e5f8e77dc560b5473befbaa365e0c61a94838478cfdc9a"
BATCH_RECEIPT = "b00e7cc6fcf5439912a5ba3e7eb3ff9c9d2998ad70adb0ac75ec2d6da2faddc1"
CANDIDATE_SHA = "25f5ccd009e33d477a59bfe3f249663e73ad2c3f8d1832d58d283ed9c6066e3d"
TOLERANCE_BPS = 1e-7


def stable(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def utc(ts):
    return datetime.fromtimestamp(int(ts) / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def trade_identity(row):
    return stable({k: row.get(k) for k in ("symbol", "signal_ts", "entry_ts", "exit_ts", "side", "intent_sha")})


def load_pinned(path, sha):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("INPUT_SHA256_MISMATCH:" + str(path))
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("OBJECT_REQUIRED")
    return result


def risk_geometry(row):
    """Normalize by the directional distance from saved fill to initial SL.

    This is geometric initial risk, not account risk, intrabar path risk, or the
    legacy concentration field named net_R (= net_bps / 100).
    """
    sl = (row.get("intent_geometry") or {}).get("sl")
    entry = row.get("entry")
    side = row.get("side")
    if sl is None or entry is None or side not in ("long", "short"):
        return {"state": "UNKNOWN_MISSING_INITIAL_STOP_OR_FILL", "initial_risk_bps": None}
    if not all(math.isfinite(float(v)) for v in (sl, entry)) or float(entry) <= 0:
        return {"state": "INVALID_PRICE", "initial_risk_bps": None}
    distance = (float(entry) - float(sl)) * (1 if side == "long" else -1)
    if distance <= 0:
        return {"state": "INVALID_NONPOSITIVE_DIRECTIONAL_INITIAL_RISK", "initial_risk_bps": None}
    risk = distance / float(entry) * 10000
    gross, cost = float(row["gross_bps"]), float(row["realized_cost_bps"])
    return {"state": "SAVED_FILL_TO_INITIAL_SL_GEOMETRY", "initial_risk_bps": risk,
        "gross_initial_risk_R": gross / risk,
        "cost_initial_risk_R": cost / risk,
        "net1_initial_risk_R": float(row["net_bps"]) / risk,
        "net2_initial_risk_R": (gross - 2 * cost) / risk}


def drawdown(values):
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def summarize_rows(rows):
    net = [float(r["net_bps"]) for r in rows]
    gross = sum(float(r["gross_bps"]) for r in rows)
    cost = sum(float(r["realized_cost_bps"]) for r in rows)
    profits = sum(v for v in net if v > 0)
    losses = -sum(v for v in net if v < 0)
    grouped = defaultdict(float)
    for row in rows:
        grouped[int(row["exit_ts"])] += float(row["net_bps"])
    risk_rows = [risk_geometry(row) for row in rows]
    valid = [r for r in risk_rows if r["initial_risk_bps"] is not None]
    return {"T": len(rows), "positive_net_count": sum(v > 0 for v in net),
        "negative_net_count": sum(v < 0 for v in net), "zero_net_count": sum(v == 0 for v in net),
        "gross_bps_sum": gross, "cost_bps_sum": cost, "net1_bps_sum": sum(net),
        "net2_bps_sum": gross - 2 * cost,
        "positive_net_bps_sum": profits, "negative_net_bps_absolute_sum": losses,
        "profit_factor": profits / losses if losses else None,
        "original_row_order_drawdown_bps": drawdown(net),
        "exit_timestamp_grouped_chronological_drawdown_bps": drawdown(grouped[k] for k in sorted(grouped)),
        "exit_timestamp_group_count": len(grouped),
        "risk_geometry_state_counts": dict(Counter(r["state"] for r in risk_rows)),
        "valid_initial_risk_count": len(valid),
        "initial_risk_bps_min": min((r["initial_risk_bps"] for r in valid), default=None),
        "initial_risk_bps_max": max((r["initial_risk_bps"] for r in valid), default=None),
        "net1_initial_risk_R_sum": sum(r["net1_initial_risk_R"] for r in valid),
        "net2_initial_risk_R_sum": sum(r["net2_initial_risk_R"] for r in valid)}


def infer_day_membership(parent_rows, parent_groups, child_groups):
    """Use complete saved day aggregates; never manufacture a source ID set.

    A one-omission unique-net match is only aggregate inference, with a fixed
    tolerance. No subset search, threshold search, raw-price processing, or
    outcome-dependent trading rule is performed.
    """
    by_day = defaultdict(list)
    for row in parent_rows:
        by_day[utc(row["entry_ts"])[:10]].append(row)
    pg = {g["group"]: g for g in parent_groups}
    cg = {g["group"]: g for g in child_groups}
    if set(by_day) != set(pg) or not set(cg).issubset(pg):
        raise ValueError("DAY_GROUP_KEYS_MISMATCH")
    result = {}
    for day, rows in by_day.items():
        p = pg[day]
        c = cg.get(day, {"trade_count": 0, "net_R": 0})
        pn, cn = int(p["trade_count"]), int(c["trade_count"])
        pnet, cnet = float(p["net_R"]) * 100, float(c["net_R"]) * 100
        if pn != len(rows) or abs(pnet - sum(float(r["net_bps"]) for r in rows)) > TOLERANCE_BPS:
            raise ValueError("PARENT_DAY_AGGREGATE_MISMATCH:" + day)
        if not 0 <= cn <= pn or (cn == 0 and abs(cnet) > TOLERANCE_BPS) or (cn == pn and abs(pnet - cnet) > TOLERANCE_BPS):
            raise ValueError("CHILD_DAY_SUBSET_INCONSISTENT:" + day)
        one_omitted = []
        if pn - cn == 1:
            one_omitted = [r for r in rows if abs(float(r["net_bps"]) - (pnet - cnet)) <= TOLERANCE_BPS]
        for row in rows:
            membership, proof = "UNKNOWN", "PARTIAL_DAY_NO_ADMISSION_IDS"
            if cn == 0:
                membership, proof = "EXCLUDED", "COMPLETE_DAY_ZERO_CHILD_COUNT"
            elif cn == pn:
                membership, proof = "RETAINED", "COMPLETE_DAY_EQUAL_PARENT_CHILD_COUNT"
            elif len(one_omitted) == 1:
                membership = "EXCLUDED" if row is one_omitted[0] else "RETAINED"
                proof = "ONE_OMITTED_UNIQUE_NET_AGGREGATE_MATCH"
            result[trade_identity(row)] = {"membership": membership, "proof": proof,
                "authority": "AGGREGATE_INFERRED_MEMBERSHIP/NOT_SOURCE_ADMISSION",
                "entry_day": day, "parent_day_T": pn, "child_day_T": cn}
    return result


def summary_profit_split(metrics):
    net, pf = float(metrics["net_pnl_bps"]), float(metrics["profit_factor"])
    if pf == 1:
        raise ValueError("PROFIT_SPLIT_UNDERDETERMINED")
    negative = net / (pf - 1)
    return {"positive_net_bps_sum": pf * negative, "negative_net_bps_absolute_sum": negative}


def validate_row_geometry(row, strategy_id):
    geom = row["intent_geometry"]
    if stable({k: v for k, v in geom.items() if k != "geometry_sha256"}) != geom["geometry_sha256"]:
        raise ValueError("GEOMETRY_HASH_MISMATCH")
    for field in ("symbol", "side", "signal_ts", "intent_sha", "feature_sha", "config_sha", "policy_sha"):
        if field in row and geom.get(field) != row[field]:
            raise ValueError("GEOMETRY_ROW_CROSSFIELD_MISMATCH:" + field)
    if geom.get("strategy_id") != strategy_id:
        raise ValueError("GEOMETRY_STRATEGY_MISMATCH")


def review(parent, batch):
    for obj, expected in ((parent, PARENT_RECEIPT), (batch, BATCH_RECEIPT)):
        if obj.get("receipt_sha256") != expected or stable({k: v for k, v in obj.items() if k != "receipt_sha256"}) != expected:
            raise ValueError("RECEIPT_BINDING_MISMATCH")
    lane = batch["strategies"]["supertrend_pullback"]
    child = next(c for c in lane["candidates"] if c["changed_axis"] == "VOLATILITY_REGIME_OWNER_ONLY")
    if child["candidate_sha256"] != CANDIDATE_SHA or stable({k: v for k, v in child.items() if k != "candidate_sha256"}) != CANDIDATE_SHA:
        raise ValueError("CANDIDATE_BINDING_MISMATCH")
    rows = parent["trades"]
    if parent["source"]["interval"] != "1h" or len(rows) != 236 or child["completed_trades"] != 117 or lane["parent_receipt_sha256"] != PARENT_RECEIPT:
        raise ValueError("TARGET_IDENTITY_MISMATCH")
    if len({trade_identity(r) for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_TRADE_IDENTITY")
    ownership = parent["native_policy_ownership"]
    opened, rejected = parent["open_intents"], parent["ownership_rejected_intents"]
    if int(parent["intent_count"]) != len(rows) + len(opened) + len(rejected):
        raise ValueError("INTENT_STAGE_CONSERVATION_MISMATCH")
    if stable(opened) != ownership["open_intents_sha256"] or stable(rejected) != ownership["rejected_intents_sha256"]:
        raise ValueError("OWNERSHIP_LIST_HASH_MISMATCH")
    for row in opened:
        validate_row_geometry(row, parent["strategy_id"])
    pm, cm = lane["parent_metrics"], child["metrics"]
    parent_summary = summarize_rows(rows)
    for source, actual in (("gross_pnl_bps", "gross_bps_sum"), ("net_pnl_bps", "net1_bps_sum")):
        if abs(float(pm[source]) - parent_summary[actual]) > TOLERANCE_BPS:
            raise ValueError("PARENT_SUMMARY_RECONCILIATION_FAIL")
    child_wins = round(float(cm["win_rate"]) * int(cm["trades"]))
    csplit = summary_profit_split(cm)
    ccost = float(cm["gross_pnl_bps"]) - float(cm["net_pnl_bps"])
    membership = infer_day_membership(rows, lane["parent_concentration"]["dimensions"]["window"], child["concentration"]["dimensions"]["window"])
    enriched, arithmetic_errors = [], []
    for index, row in enumerate(rows):
        geom = row["intent_geometry"]
        validate_row_geometry(row, parent["strategy_id"])
        snap = parent["execution_snapshots"][row["symbol"]]
        if row["cost_snapshot_sha"] != snap["snapshot_sha256"]:
            raise ValueError("COST_SNAPSHOT_MISMATCH")
        sign = 1 if row["side"] == "long" else -1
        gross_calc = sign * (float(row["exit"]) - float(row["entry"])) / float(row["entry"]) * 10000
        err = max(abs(gross_calc - float(row["gross_bps"])), abs(float(row["gross_bps"]) - float(row["realized_cost_bps"]) - float(row["net_bps"])))
        arithmetic_errors.append(err)
        ident = trade_identity(row)
        nonfund = sum(float(snap[k]) for k in ("fee_bps", "spread_bps", "impact_bps"))
        enriched.append({"parent_row_index": index, "trade_identity": ident,
            "intent_sha": row["intent_sha"], "symbol": row["symbol"], "side": row["side"],
            "signal_utc": utc(row["signal_ts"]), "entry_utc": utc(row["entry_ts"]), "exit_utc": utc(row["exit_ts"]),
            "exit_reason": row["reason"], "entry": row["entry"], "exit": row["exit"],
            "initial_sl": geom["sl"], "gross_bps": row["gross_bps"], "cost_bps": row["realized_cost_bps"], "net1_bps": row["net_bps"],
            "fee_bps": snap["fee_bps"], "spread_bps": snap["spread_bps"], "impact_bps": snap["impact_bps"],
            "funding_cost_bps_residual": float(row["realized_cost_bps"]) - nonfund,
            "funding_attribution": "SAVED_COST_MINUS_SNAPSHOT_COMPONENTS_NOT_SETTLEMENT_AUDIT",
            "risk": risk_geometry(row), "subset_membership": membership[ident]})
    if max(arithmetic_errors) > TOLERANCE_BPS:
        raise ValueError("ROW_ARITHMETIC_MISMATCH")
    excluded = [r for r in enriched if r["subset_membership"]["membership"] == "EXCLUDED"]
    parent_cost_components = {k: sum(float(r[k]) for r in enriched)
        for k in ("fee_bps", "spread_bps", "impact_bps", "funding_cost_bps_residual")}
    child_cost_components = {k: sum(int(g["trade_count"]) * float(parent["execution_snapshots"][g["group"]][k])
        for g in child["concentration"]["dimensions"]["symbol"])
        for k in ("fee_bps", "spread_bps", "impact_bps")}
    child_cost_components["funding_cost_bps_residual"] = ccost - sum(child_cost_components.values())
    removed_cost_components = {k: parent_cost_components[k] - child_cost_components[k] for k in parent_cost_components}
    group_deltas = {}
    for dim in ("symbol", "side", "session", "window"):
        pg = {g["group"]: g for g in lane["parent_concentration"]["dimensions"][dim]}
        cg = {g["group"]: g for g in child["concentration"]["dimensions"][dim]}
        group_deltas[dim] = [{"group": key, "removed_T": int(g["trade_count"]) - int(cg.get(key, {}).get("trade_count", 0)),
            "removed_net1_bps": (float(g["net_R"]) - float(cg.get(key, {}).get("net_R", 0))) * 100}
            for key, g in pg.items()]
    return {
        "schema_version": "work_c.supertrend_a4_saved_review.v1",
        "state": "SAVED_RECEIPT_DIAGNOSTIC_ONLY_NO_REPLAY_NO_CAUSAL_CHILD",
        "inputs": {"parent_file_sha256": PARENT_SHA256, "batch_file_sha256": BATCH_SHA256,
            "parent_receipt_sha256": PARENT_RECEIPT, "batch_receipt_sha256": BATCH_RECEIPT,
            "batch_git_blob": "97a6bc3d50dfb91ea3d9d3815549327d40dfafad",
            "archived_run_id": 38043785567, "archive_id": 11667302314,
            "archive_sha256": "cf7e88627451201475f7125cda92cba0c5be08b88cd0e0838354259207816a6d"},
        "identity": {"parent": parent["strategy_id"], "child": child["candidate_id"],
            "candidate_sha256": CANDIDATE_SHA, "child_trade_identity_sha256": child["trade_identity_sha256"],
            "child_identity_set_reverified": False, "timeframe": "1h", "symbols": sorted(parent["execution_snapshots"]),
            "policy_path": parent["policy_path"], "policy_blob": parent["policy_sha"], "config_sha": parent["config_sha"],
            "boundary_utc": parent["boundary_utc"], "source": parent["source"],
            "source_first_bar_utc": utc(min(s["first_post_boundary_ts"] for s in parent["source"]["symbols"])),
            "source_last_bar_utc": utc(max(s["last_post_boundary_ts"] for s in parent["source"]["symbols"])),
            "first_entry_utc": utc(min(r["entry_ts"] for r in rows)), "last_entry_utc": utc(max(r["entry_ts"] for r in rows))},
        "units": {"reported_49_58_pct": "ALL_TRADE_COUNT_RETENTION_117/236_NOT_WINNER_RETENTION",
            "legacy_concentration_net_R": "NET_TRADE_BPS_DIVIDED_BY_100_NOT_INITIAL_RISK_R",
            "risk_R_in_this_review": "SAVED_NET_BPS_DIVIDED_BY_DIRECTIONAL_FILL_TO_INITIAL_SL_BPS",
            "stored_DD": "ORIGINAL_SYMBOL_APPEND_ROW_ORDER_NOT_CHRONOLOGICAL_NAV",
            "cost2": "GROSS_MINUS_TWICE_SAVED_TOTAL_COST_NOT_LEVERAGE"},
        "parent_row_arithmetic_max_error_bps": max(arithmetic_errors),
        "signal_entry_exit_stage_audit": {"raw_intents": parent["intent_count"],
            "completed": len(rows), "open_unresolved": len(opened), "ownership_rejected": len(rejected),
            "conservation": "969=236_COMPLETED+5_OPEN+728_OWNERSHIP_REJECTED",
            "native_ownership": ownership,
            "completed_exit_reason_counts": dict(Counter(r["reason"] for r in rows)),
            "ownership_reject_reason_counts": dict(Counter(r["reason"] for r in rejected)),
            "completed_entry_minus_signal_ms_counts": dict(Counter(str(int(r["entry_ts"]) - int(r["signal_ts"])) for r in rows)),
            "row_geometry_crossfield_bindings": "ALL_236_PASS_SYMBOL_SIDE_SIGNAL_INTENT_FEATURE_CONFIG_POLICY_STRATEGY",
            "open_geometry_bindings": "ALL_5_HASH_AND_AVAILABLE_ROW_CROSSFIELDS_PASS",
            "closed_bar_availability": "ONE_HOUR_LABEL_DELTA_OBSERVED; RECEIVED_AT_AND_TRUE_FEATURE_AVAILABLE_AT_UNKNOWN",
            "open_intents_original_records": opened,
            "open_child_membership": "UNKNOWN_CHILD_SUMMARY_EVALUATES_COMPLETED_PARENT_TRADES_ONLY",
            "open_outcomes": "UNKNOWN_NOT_IMPUTED",
            "recovery_winner_or_adverse_close_classification": "UNKNOWN_NO_ORIGINAL_BAR_OR_STATE_PATH",
            "fee_costs": "RESEARCH_MODEL_NOT_ACTUAL_BROKER_FILLS"},
        "parent": parent_summary,
        "child_summary_only": {"T": 117, "positive_net_count": child_wins,
            "nonpositive_net_count": 117 - child_wins,
            "negative_net_count": 117 - child_wins if parent_summary["zero_net_count"] == 0 else None,
            "zero_net_count": 0 if parent_summary["zero_net_count"] == 0 else None,
            "sign_count_basis": "PARENT_HAS_NO_ZERO_NET_ROWS_AND_CHILD_IS_STRICT_SUBSET",
            "gross_bps_sum": cm["gross_pnl_bps"], "cost_bps_sum": ccost, "net1_bps_sum": cm["net_pnl_bps"],
            "net2_bps_sum": float(cm["gross_pnl_bps"]) - 2 * ccost,
            "profit_split_method": "ALGEBRA_FROM_STORED_NET_AND_PROFIT_FACTOR", **csplit,
            "initial_risk_R": "UNKNOWN_WITHOUT_VERIFIED_CHILD_ID_SET"},
        "retention": {"all_trade_count_pct": 100 * 117 / 236,
            "positive_net_trade_count_pct": 100 * child_wins / parent_summary["positive_net_count"],
            "positive_net_pnl_mass_pct_summary_derived": 100 * csplit["positive_net_bps_sum"] / parent_summary["positive_net_bps_sum"]},
        "removed_summary_derived": {"T": 236 - 117, "positive_net_count": parent_summary["positive_net_count"] - child_wins,
            "nonpositive_net_count": 236 - 117 - parent_summary["positive_net_count"] + child_wins,
            "negative_net_count": 236 - 117 - parent_summary["positive_net_count"] + child_wins if parent_summary["zero_net_count"] == 0 else None,
            "gross_bps_sum": parent_summary["gross_bps_sum"] - float(cm["gross_pnl_bps"]),
            "cost_bps_sum": parent_summary["cost_bps_sum"] - ccost,
            "net1_bps_sum": parent_summary["net1_bps_sum"] - float(cm["net_pnl_bps"]),
            "net2_bps_sum": parent_summary["net2_bps_sum"] - (float(cm["gross_pnl_bps"]) - 2 * ccost),
            "forgone_positive_net_bps": parent_summary["positive_net_bps_sum"] - csplit["positive_net_bps_sum"],
            "avoided_negative_net_absolute_bps": parent_summary["negative_net_bps_absolute_sum"] - csplit["negative_net_bps_absolute_sum"],
            "counterfactual_limit": "STRICT_SAVED_SUBSET_ACCOUNTING_NOT_DYNAMIC_ADMISSION_OR_EXIT_POLICY_REPLAY"},
        "cost_components_bps_sums": {"parent": parent_cost_components, "child": child_cost_components,
            "removed": removed_cost_components,
            "child_method": "SAVED_CHILD_SYMBOL_COUNTS_TIMES_FIXED_PARENT_SYMBOL_SNAPSHOTS",
            "funding_method": "RESIDUAL_OF_SAVED_TOTAL_COST_NOT_SIGNED_SETTLEMENT_OR_HISTORICAL_FILL_AUDIT"},
        "aggregate_membership_inference": {"authority": "AGGREGATE_INFERRED_MEMBERSHIP/NOT_SOURCE_ADMISSION",
            "fixed_arithmetic_tolerance_bps": TOLERANCE_BPS,
            "count_by_membership": dict(Counter(r["membership"] for r in membership.values())),
            "count_by_proof": dict(Counter(r["proof"] for r in membership.values())),
            "future_PnL_allowed_use": "RETROSPECTIVE_ONE_OMITTED_AGGREGATE_IDENTITY_INFERENCE_ONLY_NEVER_POLICY_FEATURE",
            "largest_inferred_excluded_winners": sorted([r for r in excluded if r["net1_bps"] > 0], key=lambda r: -r["net1_bps"])[:10],
            "largest_inferred_excluded_losses": sorted([r for r in excluded if r["net1_bps"] < 0], key=lambda r: r["net1_bps"])[:10]},
        "removed_group_deltas": group_deltas,
        "all_parent_rows": enriched,
        "missing": ["Complete immutable 117 admitted trade-ID list matching e42711d8843107a94f32019e0a7d1c7492319e812ddf5be377bbdbdac1365e01",
            "Original raw 1h bars for parent evaluation and separately fetched subset ATR classification",
            "Per-signal ATR14/ATR50 values and available-at/received timestamps, full rejected/no-trade feature records",
            "Original funding settlement rows and historical fill-time spread/impact observations",
            "Intrabar stop/gap/partial-fill path and recovered-adverse-close state",
            "Author/source-complete distinct unexhausted causal lifecycle rule"],
        "limits": ["Hashes of features/geometry do not recover feature values or source-time availability.",
            "Positive outcome, MFE, identity, symbol, date and retrospective membership are not permitted new-policy conditions.",
            "Saved total funding is unsigned absolute-rate model; the residual is not signed historical account funding.",
            "No market data collection, native evaluator, replay, new policy evaluation, or economic credit occurred."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, default=HERE / "inputs/parent236.json")
    parser.add_argument("--batch", type=Path, default=HERE / "inputs/a4_summary.json")
    parser.add_argument("--out", type=Path, default=HERE / "SAVED_SUMMARY_REVIEW.json")
    args = parser.parse_args(argv)
    result = review(load_pinned(args.parent, PARENT_SHA256), load_pinned(args.batch, BATCH_SHA256))
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"state": result["state"], "parent_T": result["parent"]["T"],
        "membership_counts": result["aggregate_membership_inference"]["count_by_membership"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
