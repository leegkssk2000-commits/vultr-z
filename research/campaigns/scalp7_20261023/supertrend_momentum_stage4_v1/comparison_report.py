"""Pure POST-RUN A-result comparison; no replay, data fetch, file or ledger writes.

compare(parent_rows, child_rows, manifest, *, unresolved_parent,
        unresolved_child, censored_parent, censored_child) -> JSON-compatible dict.

Manifest schema: parent_identity, child_identity (distinct strings), input_sha256
(64 hex), bounds={start_ms,end_ms}, symbols (the exact frozen seven below),
six_symbol_cohort (the exact observed six below, DIAGNOSTIC ONLY), normalization below,
comparison_protocol below, model_cost_bps={"1x":20,"2x":40}, and
large_winner_reference_ids (preregistered parent trade IDs, post-run labels only).

Closed row schema: trade_id, signal_identity (respective result identity),
original_signal_identity (parent identity), symbol, signal_ts_ms, entry_ts_ms,
exit_ts_ms, outcome_available_ts_ms, gross_trade_bps, normalization. signal_ts_ms
is the native ORIGINAL SIGNAL-BAR OPEN timestamp, not a reconstructed close.
Child rows
also require parent_trade_id (parent ID or null for a genuinely new signal).
Linked children retain the original entry timestamp and cannot exit earlier.
Gross bps are BEFORE modeled costs and MUST already be normalized by A to
unit gross entry notional; this
module cannot infer or repair a notional denominator. All four unfinished inputs
are explicit lists of records with symbol. An optional entry_ts_ms permits
unfinished-interval conflict checks; its absence leaves position chronology
UNVERIFIED and the result on HOLD. Unfinished positions occupy through DEV end.
Actual fee/funding/fill evidence and
account NAV are not supplied by this schema and are never synthesized.
Declared rows do not prove original A fill integrity or native 4h timing; A's
separate source/fill gate must verify those against frozen source evidence.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import re

PROTOCOL = "FULL_CHRONOLOGY_SAME_EXIT_TS_COHORTS_V1"
NORMALIZATION = "UNIT_GROSS_NOTIONAL_TRADE_BPS"
COSTS = {"1x": 20.0, "2x": 40.0}
FROZEN_SYMBOLS = ("1000PEPE-USDT", "BCH-USDT", "BTC-USDT", "ETH-USDT", "HYPE-USDT", "LINK-USDT", "SOL-USDT")
OBSERVED_SIX = ("1000PEPE-USDT", "BCH-USDT", "BTC-USDT", "ETH-USDT", "HYPE-USDT", "SOL-USDT")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _clock(value):
    _require(type(value) is int and value >= 0, "NONNEGATIVE_INTEGER_CLOCK_REQUIRED")
    return value


def _key(row):
    return row["original_signal_identity"], row["symbol"], row["signal_ts_ms"]


def _validate(rows, identity, manifest, *, child=False):
    _require(isinstance(rows, list), "EXPLICIT_ROW_LIST_REQUIRED")
    ids, signals = set(), set()
    start, end = (manifest["bounds"][k] for k in ("start_ms", "end_ms"))
    for row in rows:
        _require(isinstance(row["trade_id"], str) and row["trade_id"] and row["trade_id"] not in ids, "DUPLICATE_OR_MISSING_TRADE_ID")
        ids.add(row["trade_id"])
        _require(row["signal_identity"] == identity and row["original_signal_identity"] == manifest["parent_identity"], "IDENTITY_DRIFT")
        _require(row["symbol"] in manifest["symbols"] and row["normalization"] == NORMALIZATION, "SYMBOL_OR_NOTIONAL_CONTRACT_DRIFT")
        times = [_clock(row[k]) for k in ("signal_ts_ms", "entry_ts_ms", "exit_ts_ms", "outcome_available_ts_ms")]
        _require(start <= times[0] <= times[1] < times[2] <= times[3] < end, "CLOSED_ROW_CLOCK_OR_BOUNDARY_INVALID")
        _require(type(row["gross_trade_bps"]) in (int, float) and math.isfinite(row["gross_trade_bps"]), "FINITE_NORMALIZED_GROSS_REQUIRED")
        _require(_key(row) not in signals, "DUPLICATE_ORIGINAL_SIGNAL")
        signals.add(_key(row))
        if child:
            _require("parent_trade_id" in row and (row["parent_trade_id"] is None or isinstance(row["parent_trade_id"], str)), "EXPLICIT_PARENT_LINK_REQUIRED")
    prior_exit = {}
    for row in sorted(rows, key=lambda r: (r["entry_ts_ms"], r["trade_id"])):
        _require(row["entry_ts_ms"] > prior_exit.get(row["symbol"], -1), "SAME_SYMBOL_CLOSED_POSITION_OVERLAP")
        prior_exit[row["symbol"]] = row["exit_ts_ms"]


def _unfinished_conflicts(closed, unfinished, start, end):
    known = [r for r in unfinished if "entry_ts_ms" in r]
    for row in known:
        entry = _clock(row["entry_ts_ms"])
        _require(start <= entry < end, "UNFINISHED_ENTRY_OUTSIDE_DEV")
        _require(not any(r["symbol"] == row["symbol"] and r["exit_ts_ms"] >= entry for r in closed), "CLOSED_UNFINISHED_POSITION_OVERLAP")
    _require(len({r["symbol"] for r in known}) == len(known), "UNFINISHED_POSITION_OVERLAP")
    return "UNKNOWN_MISSING_ENTRY_CLOCK" if len(known) != len(unfinished) else "KNOWN_INTERVALS_CHECKED"


def _runs(values):
    runs, current = [], []
    for value in values + [0.0]:
        if value < 0:
            current.append(value)
        elif current:
            runs.append(current)
            current = []
    longest = max(runs, key=len, default=[])
    return {"max_consecutive_negative": len(longest), "negative_run_count": len(runs),
            "longest_run_net_bps": math.fsum(longest),
            "worst_run_net_bps": min((math.fsum(r) for r in runs), default=0.0)}


def _metrics(rows, cost):
    ordered = sorted(rows, key=lambda r: (r["exit_ts_ms"], r["symbol"], r["trade_id"]))
    nets = [float(r["gross_trade_bps"]) - cost for r in ordered]
    cohorts = defaultdict(list)
    for row, net in zip(ordered, nets):
        cohorts[row["exit_ts_ms"]].append(net)
    values = [math.fsum(cohorts[t]) for t in sorted(cohorts)]
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gains, losses = math.fsum(x for x in nets if x > 0), -math.fsum(x for x in nets if x < 0)
    return {"T": len(rows), "Net_bps": math.fsum(nets), "PF": gains / losses if losses else None,
            "PF_status": "DEFINED" if losses else "UNDEFINED_NO_NEGATIVE_NET_TRADES",
            "win_count": sum(x > 0 for x in nets), "loss_count": sum(x < 0 for x in nets),
            "win_rate": sum(x > 0 for x in nets) / len(nets) if nets else None,
            "realized_exit_cohort_trade_bps_DD": drawdown,
            "row_streak_order_dependent": _runs(nets), "exit_cohort_streak": _runs(values),
            "simultaneous_negative_cohorts": [{"exit_ts_ms": t, "trade_count": len(cohorts[t]),
                "negative_trade_count": sum(v < 0 for v in cohorts[t]), "cohort_net_bps": math.fsum(cohorts[t])}
                for t in sorted(cohorts) if len(cohorts[t]) > 1 and math.fsum(cohorts[t]) < 0]}


def compare(parent_rows, child_rows, manifest, *, unresolved_parent,
            unresolved_child, censored_parent, censored_child):
    """Consume already-produced A rows; an improvement is REVIEW, never PASS."""
    _require(isinstance(manifest, dict), "MANIFEST_REQUIRED")
    _require(all(isinstance(manifest.get(k), str) and manifest[k] for k in ("parent_identity", "child_identity"))
             and manifest["parent_identity"] != manifest["child_identity"], "DISTINCT_FROZEN_IDENTITIES_REQUIRED")
    _require(isinstance(manifest.get("input_sha256"), str) and re.fullmatch(r"[0-9a-fA-F]{64}", manifest["input_sha256"]), "EXACT_INPUT_SHA256_REQUIRED")
    _require(manifest["comparison_protocol"] == PROTOCOL and manifest["normalization"] == NORMALIZATION
             and manifest["model_cost_bps"] == COSTS, "COMPARISON_PROTOCOL_OR_COST_DRIFT")
    start, end = (_clock(manifest["bounds"][k]) for k in ("start_ms", "end_ms"))
    _require(start < end, "NONEMPTY_FIXED_BOUNDARY_REQUIRED")
    universe, six = manifest["symbols"], manifest["six_symbol_cohort"]
    _require(isinstance(universe, list) and len(universe) == 7 and all(isinstance(s, str) for s in universe)
             and set(universe) == set(FROZEN_SYMBOLS), "EXACT_SEVEN_SYMBOL_UNIVERSE_REQUIRED")
    _require(isinstance(six, list) and len(six) == 6 and all(isinstance(s, str) for s in six)
             and set(six) == set(OBSERVED_SIX), "EXACT_SIX_SYMBOL_DIAGNOSTIC_COHORT_REQUIRED")
    _validate(parent_rows, manifest["parent_identity"], manifest)
    _validate(child_rows, manifest["child_identity"], manifest, child=True)
    unfinished = {"parent_unresolved": unresolved_parent, "child_unresolved": unresolved_child,
                  "parent_censored": censored_parent, "child_censored": censored_child}
    for records in unfinished.values():
        _require(isinstance(records, list) and all(isinstance(r, dict) and r.get("symbol") in universe for r in records), "EXPLICIT_UNFINISHED_RECORDS_REQUIRED")
    pending_validation = {
        "parent": _unfinished_conflicts(parent_rows, unresolved_parent + censored_parent, start, end),
        "child": _unfinished_conflicts(child_rows, unresolved_child + censored_child, start, end)}
    parent = {r["trade_id"]: r for r in parent_rows}
    parent_signals = {_key(r): r["trade_id"] for r in parent_rows}
    paired, added = {}, []
    for row in child_rows:
        ref = row["parent_trade_id"]
        if ref is None:
            _require(_key(row) not in parent_signals, "EXISTING_PARENT_SIGNAL_REQUIRES_LINK")
            added.append(row)
        else:
            _require(ref in parent and ref not in paired and _key(parent[ref]) == _key(row), "INVALID_OR_REUSED_PARENT_LINK")
            _require(row["entry_ts_ms"] == parent[ref]["entry_ts_ms"] and row["exit_ts_ms"] >= parent[ref]["exit_ts_ms"], "CHILD_EXIT_ONLY_AXIS_DRIFT")
            paired[ref] = row
    large = manifest["large_winner_reference_ids"]
    _require(isinstance(large, list) and len(large) == len(set(large)) and set(large) <= parent.keys(), "LARGE_WINNER_REFERENCE_NOT_PARENT_SUBSET")
    _require(all(parent[k]["gross_trade_bps"] - COSTS["1x"] > 0 for k in large), "LARGE_WINNER_REFERENCE_MUST_BE_PARENT_WINNER")
    removed = [r for k, r in parent.items() if k not in paired]
    metrics = {"parent": {}, "child": {}, "delta": {}}
    attribution = {}
    for level, cost in COSTS.items():
        before, after = _metrics(parent_rows, cost), _metrics(child_rows, cost)
        days = (end - start) / 86_400_000
        for value in (before, after):
            value["trades_per_calendar_day"] = value["T"] / days
        metrics["parent"][level], metrics["child"][level] = before, after
        metrics["delta"][level] = {k: after[k] - before[k] if before[k] is not None and after[k] is not None else None
                                  for k in ("T", "Net_bps", "PF", "win_count", "loss_count", "win_rate", "realized_exit_cohort_trade_bps_DD", "trades_per_calendar_day")}
        for field in ("row_streak_order_dependent", "exit_cohort_streak"):
            metrics["delta"][level][field] = {key: after[field][key] - before[field][key] for key in before[field]}
        metrics["delta"][level]["simultaneous_negative_cohort_count"] = len(after["simultaneous_negative_cohorts"]) - len(before["simultaneous_negative_cohorts"])
        common = math.fsum(paired[k]["gross_trade_bps"] - parent[k]["gross_trade_bps"] for k in paired)
        added_net, removed_net = (math.fsum(r["gross_trade_bps"] - cost for r in rows) for rows in (added, removed))
        _require(math.isclose(metrics["delta"][level]["Net_bps"], common + added_net - removed_net, abs_tol=1e-7), "FULL_CHRONOLOGY_ATTRIBUTION_MISMATCH")
        attribution[level] = {"common_delta_bps": common, "new_entry_net_bps": added_net,
                              "missing_parent_net_bps": removed_net, "reconciled": True}
    winners = {k for k, row in parent.items() if row["gross_trade_bps"] > COSTS["1x"]}
    retention = {}
    for label, ids in (("all_parent_winners_1x", winners), ("preregistered_large_winners", set(large)),
                       ("ordinary_parent_winners_1x", winners - set(large))):
        rows = []
        for ref in sorted(ids):
            child = paired.get(ref)
            rows.append({"parent_trade_id": ref, "child_trade_id": child["trade_id"] if child else None,
                         "parent_net_bps": {lev: parent[ref]["gross_trade_bps"] - cost for lev, cost in COSTS.items()},
                         "child_net_bps": {lev: child["gross_trade_bps"] - cost if child else None for lev, cost in COSTS.items()},
                         "child_positive": {lev: child["gross_trade_bps"] - cost > 0 if child else False for lev, cost in COSTS.items()}})
        retention[label] = {"parent_count": len(ids), "paired_count": len(ids & paired.keys()),
                            "retained_positive_count": {lev: sum(r["child_positive"][lev] for r in rows) for lev in COSTS},
                            "parent_net_sum": {lev: math.fsum(r["parent_net_bps"][lev] for r in rows) for lev in COSTS},
                            "child_paired_net_sum": {lev: math.fsum(r["child_net_bps"][lev] for r in rows if r["child_trade_id"] is not None) for lev in COSTS},
                            "aggregate_note": "Missing pairs contribute zero only to this signed diagnostic aggregate; no unknown fill is synthesized and unfinished results remain HOLD.",
                            "missing_parent_ids": sorted(ids - paired.keys()), "paired_values": rows}
    incomplete = any(unfinished.values())
    classification = "HOLD_INCOMPLETE" if incomplete else "REJECT_NO_COST2_IMPROVEMENT" if metrics["delta"]["2x"]["Net_bps"] <= 0 else "A_REVIEW_REQUIRED"
    return {"schema": "zel.supertrend.stage4.comparison_report.v1", "classification": classification,
            "execution_model": "MODELED_FIXED_COST_NOT_REAL_FUNDING_FILL", "metrics": metrics,
            "model_round_trip_cost_bps": deepcopy(COSTS), "actual_fee_bps": None, "actual_funding_bps": None,
            "account_NAV_return": None, "account_NAV_DD": None, "MTM_DD": None,
            "streak_note": "Row order=(exit_ts_ms,symbol,trade_id), tie-order dependent. Cohorts sum simultaneous exits before DD/streak; zero breaks a negative run.",
            "drawdown_note": "Sum of unit-notional trade-bps at actual supplied exit timestamps; not account NAV or MTM drawdown.",
            "unfinished_counts": {k: len(v) for k, v in unfinished.items()},
            "unfinished_position_clock_validation": pending_validation,
            "attribution_scope": "Arithmetic reconciliation only; missing unfinished clocks do not prove legal chronology. A must prove source/fill integrity separately.",
            "universe_contract": {"allowed_symbols": deepcopy(universe), "six_symbol_diagnostic_cohort": deepcopy(six),
                "parent_traded_symbols": sorted({r["symbol"] for r in parent_rows}), "child_traded_symbols": sorted({r["symbol"] for r in child_rows}),
                "runtime_symbol_filter_applied": False},
            "six_symbol_post_run_diagnostic": {side: {lev: _metrics([r for r in rows if r["symbol"] in six], cost)
                for lev, cost in COSTS.items()} for side, rows in (("parent", parent_rows), ("child", child_rows))},
            "winner_retention_post_run_only": retention, "full_chronology_attribution": attribution,
            "new_child_trade_ids": [r["trade_id"] for r in added], "missing_parent_trade_ids": [r["trade_id"] for r in removed],
            "frozen_manifest": deepcopy(manifest), "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
            "supplied_rows_sha256": {side: hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                                     for side, rows in (("parent", parent_rows), ("child", child_rows))},
            "promotion": False, "policy_features_from_outcomes": False,
            "acceptance_note": "Only non-improving Net2 is an explicit rejection here; PF/DD/streak/winner tradeoffs remain for A. No PASS or unapproved threshold."}
