"""Offline saved-ledger attribution, with no I/O or evaluator imports.

The caller owns strict artifact/receipt/source validation. Both public functions
return JSON-serializable dictionaries: financial Decimal values are strings,
counts and millisecond bar labels are integers. Nothing selects execution rows.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext

ZERO = Decimal(0)
PROXY_FIELDS = ("symbol", "side", "signal_ts", "entry_ts")
VECTOR_FIELDS = ("gross_bps", "cost_1x_bps", "cost_2x_bps", "net_1x_bps", "net_2x_bps")
CLOCK_CAVEAT = (
    "exit_ts is a bar-open label, not an observed fill or outcome-availability timestamp. "
    "SL observes that bar high/low; TIMEOUT observes its close. Same-bar ordering is unknown."
)


def _d(value):
    if isinstance(value, bool):
        raise ValueError("BOOLEAN_IS_NOT_NUMERIC")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("NONFINITE_VALUE")
    return result


def _json(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json(val) for key, val in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(val) for val in value]
    return value


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def event_proxy(row):
    """Cross-snapshot matching proxy, explicitly not native intent identity."""
    return tuple(row[key] for key in PROXY_FIELDS)


def event_id(row):
    return _sha(dict(zip(PROXY_FIELDS, event_proxy(row))))


def _identity(row):
    return {"event_proxy_sha256": event_id(row),
            "event_proxy": dict(zip(PROXY_FIELDS, event_proxy(row))),
            "native_intent_sha": row.get("intent_sha"),
            "parent_intent_sha": row.get("parent_intent_sha"),
            "feature_sha": row.get("feature_sha"),
            "cost_snapshot_sha": row.get("cost_snapshot_sha"),
            "exit_ts": row["exit_ts"]}


def _rows(receipt):
    rows = receipt.get("trades")
    if not isinstance(rows, list) or receipt.get("completed_trades") != len(rows):
        raise ValueError("COMPLETE_ROWS_AND_COUNT_REQUIRED")
    seen = set()
    for row in rows:
        proxy = event_proxy(row)
        if proxy in seen:
            raise ValueError("AMBIGUOUS_DUPLICATE_EVENT_PROXY")
        seen.add(proxy)
        for key in ("signal_ts", "entry_ts", "exit_ts"):
            if type(row[key]) is not int:
                raise ValueError("INTEGER_BAR_TIMESTAMP_REQUIRED:" + key)
        if not row["signal_ts"] <= row["entry_ts"] <= row["exit_ts"]:
            raise ValueError("INVALID_BAR_TIME_ORDER")
        _d(row["gross_bps"])
        _d(row["net_bps"])
        if _d(row["realized_cost_bps"]) < 0:
            raise ValueError("NEGATIVE_STORED_COST")
    return rows


def _net(row, multiple):
    return _d(row["gross_bps"]) - multiple * _d(row["realized_cost_bps"])


def _vector(rows):
    gross = sum((_d(r["gross_bps"]) for r in rows), ZERO)
    cost = sum((_d(r["realized_cost_bps"]) for r in rows), ZERO)
    return {"gross_bps": gross, "cost_1x_bps": cost, "cost_2x_bps": cost * 2,
            "net_1x_bps": gross - cost, "net_2x_bps": gross - cost * 2}


def _subtract(left, right):
    return {key: left[key] - right[key] for key in VECTOR_FIELDS}


def _curve(values):
    cumulative = peak = dd = ZERO
    streak = longest = 0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        dd = max(dd, peak - cumulative)
        streak = streak + 1 if value < 0 else 0
        longest = max(longest, streak)
    return {"terminal_sum_trade_bps": cumulative,
            "drawdown_sum_trade_bps": dd,
            "max_consecutive_negative_observations": longest}


def _cohorts(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["exit_ts"]].append(row)
    return [(ts, groups[ts]) for ts in sorted(groups)]


def _chronology(rows, multiple):
    ordered = sorted(rows, key=lambda r: (r["exit_ts"], r["entry_ts"], event_proxy(r)))
    cohorts = _cohorts(rows)
    return {
        "original_receipt_order": {**_curve([_net(r, multiple) for r in rows]),
                                   "unit": "individual trade; native receipt is entry-ordered"},
        "exit_bar_individual": {**_curve([_net(r, multiple) for r in ordered]),
                                "unit": "individual trade; same-bar tie order arbitrary",
                                "tie_break": "entry_ts then event proxy"},
        "exit_bar_cohort": {**_curve([sum((_net(r, multiple) for r in group), ZERO)
                                      for _, group in cohorts]),
                            "unit": "exit-bar cohort, all simultaneous labels netted once",
                            "cohort_count": len(cohorts),
                            "multi_trade_cohorts": sum(len(group) > 1 for _, group in cohorts)},
        "account_drawdown": None, "portfolio_NAV": False,
        "mark_to_market_and_intrabar_drawdown": None, "clock_caveat": CLOCK_CAVEAT,
    }


def _metrics(rows, multiple):
    vals = [_net(r, multiple) for r in rows]
    positive = sum((x for x in vals if x > 0), ZERO)
    negative = -sum((x for x in vals if x < 0), ZERO)
    count = len(rows)
    gross = sum((_d(r["gross_bps"]) for r in rows), ZERO)
    cost = sum((_d(r["realized_cost_bps"]) for r in rows), ZERO) * multiple
    return {"trades": count, "gross_sum_trade_bps": gross, "cost_sum_trade_bps": cost,
            "net_sum_trade_bps": gross - cost, "net_per_trade_bps": (gross - cost) / count if count else None,
            "wins": sum(x > 0 for x in vals), "losses": sum(x < 0 for x in vals),
            "flat": sum(x == 0 for x in vals),
            "win_rate": Decimal(sum(x > 0 for x in vals)) / count if count else None,
            "profit_factor": positive / negative if negative else None,
            "profit_factor_null_reason": "NO_NEGATIVE_OUTCOMES" if not negative else None,
            "positive_profit_trade_bps": positive, "absolute_loss_trade_bps": negative}


def _date(ts, form="%Y-%m-%d"):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).strftime(form)


def _session(row):
    hour = datetime.fromtimestamp(row["signal_ts"] / 1000, timezone.utc).hour
    return "APAC" if hour < 8 else "EU" if hour < 16 else "US"


def _groups(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return sorted(groups.items())


def _group_reports(rows, key):
    return [{"group": name, "event_proxy_sha256s": [event_id(r) for r in group],
             "cost_1x": _metrics(group, 1), "cost_2x_posthoc": _metrics(group, 2)}
            for name, group in _groups(rows, key)]


def _leave_groups_out(rows, key):
    total = _vector(rows)
    return [{"group": name, "excluded_trade_count": len(group),
             "remaining_trade_count": len(rows) - len(group),
             "excluded_event_proxy_sha256s": [event_id(r) for r in group],
             "excluded_outcomes": _vector(group),
             "descriptive_remaining_outcomes": _subtract(total, _vector(group))}
            for name, group in _groups(rows, key)]


def _top_winners(rows, multiple):
    ranked = sorted((r for r in rows if _net(r, multiple) > 0),
                    key=lambda r: (-_net(r, multiple), event_proxy(r)))
    total = sum((_net(r, multiple) for r in rows), ZERO)
    profit = sum((_net(r, multiple) for r in ranked), ZERO)
    records = []
    for k in (1, 3, 5, 10):
        chosen = ranked[:k]
        amount = sum((_net(r, multiple) for r in chosen), ZERO)
        records.append({"top_k": k, "actual_count": len(chosen),
                        "identities": [_identity(r) for r in chosen],
                        "contribution_trade_bps": amount,
                        "share_of_positive_profit": amount / profit if profit else None,
                        "share_of_signed_total_net": amount / total if total else None,
                        "descriptive_remaining_net_trade_bps": total - amount})
    return records


def _occupancy(rows):
    """Half-open closed-row interval accounting; never an admission simulator."""
    enters, exits, zero = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        if row["entry_ts"] == row["exit_ts"]:
            zero[row["entry_ts"]].append(row)
        else:
            enters[row["entry_ts"]].append(row)
            exits[row["exit_ts"]].append(row)
    times = sorted(set(enters) | set(exits) | set(zero))
    active, timeline, segments = {}, [], []
    for index, ts in enumerate(times):
        for row in exits[ts]:
            active.pop(event_proxy(row))
        after_exits = len(active)
        for row in enters[ts]:
            active[event_proxy(row)] = row
        timeline.append({"ts_ms": ts, "exit_count": len(exits[ts]),
                         "entry_count": len(enters[ts]), "zero_span_rows": len(zero[ts]),
                         "active_after_exits_before_entries": after_exits,
                         "active_after_all_same_time_events": len(active)})
        if index + 1 < len(times) and active:
            group = [active[key] for key in sorted(active)]
            segments.append({"start_ts": ts, "end_ts": times[index + 1],
                             "active_count": len(group),
                             "event_proxy_sha256s": [event_id(r) for r in group],
                             "retrospective_member_final_outcomes": _vector(group)})
    if active:
        raise AssertionError("CLOSED_ROW_OCCUPANCY_DID_NOT_CLEAR")
    unique = {}
    for segment in segments:
        key = tuple(segment["event_proxy_sha256s"])
        if key not in unique:
            unique[key] = {**segment, "intervals": []}
        unique[key]["intervals"].append({"start_ts": segment["start_ts"], "end_ts": segment["end_ts"]})
    worst = {}
    for multiple in (1, 2):
        key = f"net_{multiple}x_bps"
        worst[f"cost_{multiple}x"] = sorted(
            unique.values(), key=lambda r: (r["retrospective_member_final_outcomes"][key],
                                            r["start_ts"], r["event_proxy_sha256s"]))[:10]
    return {"interval_definition": "[entry_ts, exit_ts), exits before entries at equal timestamps",
            "scope": "Only closed receipt rows; open/rejected parent intents and capital constraints are not simulated.",
            "clock_caveat": CLOCK_CAVEAT,
            "zero_bar_span_count": sum(map(len, zero.values())),
            "zero_bar_span_event_proxy_sha256s": [event_id(r) for ts in sorted(zero) for r in zero[ts]],
            "zero_span_caveat": "Zero bar-label span is not evidence of zero actual intrabar occupancy.",
            "maximum_simultaneously_active_closed_rows": max((r["active_count"] for r in segments), default=0),
            "closed_row_position_milliseconds": sum((r["exit_ts"] - r["entry_ts"] for r in rows), 0),
            "timeline": timeline, "distinct_active_membership_count": len(unique),
            "worst_active_cohorts_by_final_member_outcome": worst,
            "cohort_outcome_caveat": "Final outcomes of active members are retrospective labels, not current basket MTM or information available during the interval.",
            "candidate_capacity_or_admission_claim": False}


def _october_clusters(rows):
    october = [r for r in rows if _date(r["exit_ts"], "%m") == "10"]
    result = {}
    for multiple in (1, 2):
        runs, pending = [], []

        def finish():
            if pending:
                members = [r for _, group in pending for r in group]
                runs.append({"first_exit_bar_ts": pending[0][0], "last_exit_bar_ts": pending[-1][0],
                             "negative_cohorts": len(pending), "trades": len(members),
                             "event_proxy_sha256s": [event_id(r) for r in members],
                             "outcomes": _vector(members)})
                pending.clear()

        for ts, group in _cohorts(october):
            if sum((_net(r, multiple) for r in group), ZERO) < 0:
                pending.append((ts, group))
            else:
                finish()
        finish()
        losers = [r for r in october if _net(r, multiple) < 0]
        result[f"cost_{multiple}x"] = {
            "october_exit_trade_count": len(october), "loser_count": len(losers),
            "loser_only_exit_day_groups": _group_reports(losers, lambda r: _date(r["exit_ts"])),
            "consecutive_negative_exit_cohort_runs": runs,
            "run_definition": "Adjacent observed October exit cohorts with aggregate net<0; gaps without closes are not new observations. Mixed winning/losing trades stay together.",
        }
    return result


def _winner_ids(rows, multiple):
    return [_identity(r) for r in rows if _net(r, multiple) > 0]


def _large_unknown():
    return {"state": "NOT_AVAILABLE", "large_count": None, "ordinary_count": None,
            "definition": None,
            "reason": "No frozen large/ordinary winner definition and no MFE trace supplied; rank diagnostics are not a replacement definition."}


def build_attribution(receipt, cohort_label):
    """Attribute all supplied closed rows, preserving them and all winners."""
    rows = _rows(receipt)
    with localcontext() as ctx:
        ctx.prec = 80
        report = {
            "schema_version": "zel.d.current_trendrider.saved_attribution.v1",
            "cohort_label": cohort_label, "receipt_sha256": receipt.get("receipt_sha256"),
            "validation_scope": "Caller must bind raw/source/receipt identity; this module checks rows, counts and proxy uniqueness only.",
            "units": "Unweighted sums of per-trade bps; no quantities, account PnL, NAV or capital normalization.",
            "numeric_encoding": "Decimal(saved numeric spellings), precision80, JSON decimal strings; source float residual separately reported.",
            "cost_contract": "1x=gross-stored realized_cost_bps; 2x=gross-2*stored realized_cost_bps. No separate funding/fee addition or double count. 2x is posthoc arithmetic, not a run input.",
            "fee_funding_component_split": None,
            "fee_funding_split_reason": "Rows expose total realized cost; this report does not infer a component breakdown or alter it.",
            "cost_1x": {**_metrics(rows, 1), "chronology": _chronology(rows, 1)},
            "cost_2x_posthoc": {**_metrics(rows, 2), "chronology": _chronology(rows, 2)},
            "native_saved_metrics": copy.deepcopy(receipt.get("metrics")),
            "native_drawdown_basis": "Original row order; in this native pipeline rows are entry_ts,symbol ordered, not realized exit order.",
            "original_order_is_entry_then_symbol": rows == sorted(rows, key=lambda r: (r["entry_ts"], r["symbol"])),
            "saved_net_minus_decimal_recomputed_bps": sum((_d(r["net_bps"]) - _net(r, 1) for r in rows), ZERO),
            "reason_counts": dict(sorted(Counter(r.get("reason") for r in rows).items())),
            "monthly": {"entry_month_utc": _group_reports(rows, lambda r: _date(r["entry_ts"], "%Y-%m")),
                        "exit_bar_month_utc": _group_reports(rows, lambda r: _date(r["exit_ts"], "%Y-%m"))},
            "october_loser_clusters_retrospective": _october_clusters(rows),
            "same_time_occupancy_diagnostic": _occupancy(rows),
            "leave_one_group_out_diagnostic": {
                "not_candidate_results": True,
                "symbol": _leave_groups_out(rows, lambda r: r["symbol"]),
                "entry_day_utc": _leave_groups_out(rows, lambda r: _date(r["entry_ts"])),
                "signal_session_utc": _leave_groups_out(rows, _session),
                "session_definition": "APAC 00<=hour<08; EU08<=hour<16; US16<=hour<24, UTC signal-bar label. Descriptive native session convention only.",
            },
            "top_winner_drop_diagnostic": {"not_candidate_results": True,
                                            "cost_1x": _top_winners(rows, 1),
                                            "cost_2x": _top_winners(rows, 2)},
            "baseline_retention": {"retained_rows": len(rows), "baseline_rows": len(rows),
                                   "row_retention_fraction": Decimal(1) if rows else None,
                                   "cost_1x_all_winner_identities": _winner_ids(rows, 1),
                                   "cost_2x_all_winner_identities": _winner_ids(rows, 2),
                                   "large_ordinary_winner_classification": _large_unknown(),
                                   "candidate_retention_measured": False},
            "september_winners": {
                "entry_month_basis": _winner_ids([r for r in rows if _date(r["entry_ts"], "%m") == "09"], 1),
                "exit_month_basis": _winner_ids([r for r in rows if _date(r["exit_ts"], "%m") == "09"], 1),
                "large_ordinary_classification": _large_unknown(),
            },
            "negative_control": {"state": receipt.get("negative_control_state"),
                                 "gate": copy.deepcopy(receipt.get("negative_control_gate")),
                                 "source_scope": "Copied receipt status, not freshly measured superiority or a 255-only independent test.",
                                 "new_control_run": "NOT_RUN"},
            "source_feature_limits": {"MFE_MAE_recovery": "NOT_AVAILABLE",
                                      "feature_bodies_and_available_ts": "NOT_AVAILABLE_IN_SAVED_ROWS",
                                      "future_labels_are_execution_features": False},
            "rows": [{"original_index": index, **_identity(row), "saved_row": copy.deepcopy(row),
                      "retrospective_only": {"net_1x_bps": _net(row, 1), "net_2x_bps": _net(row, 2),
                                             "winner_1x": _net(row, 1) > 0, "winner_2x": _net(row, 2) > 0,
                                             "outcome_available_ts": None, "MFE": None, "MAE": None,
                                             "recovery_winner": None}}
                     for index, row in enumerate(rows)],
            "economic_replay": False, "candidate_result": False,
        }
        return _json(report)


def _winner_comparison(old_rows, new_map, multiple):
    records = []
    for row in old_rows:
        before = _net(row, multiple)
        if before <= 0:
            continue
        later = new_map.get(event_proxy(row))
        after = _net(later, multiple) if later is not None else None
        records.append({"old_identity": _identity(row),
                        "new_identity": _identity(later) if later is not None else None,
                        "old_net_bps": before, "new_net_bps": after,
                        "proxy_present": later is not None,
                        "still_positive": after > 0 if after is not None else False,
                        "net_change_bps": after - before if after is not None else None,
                        "status": "REMOVED" if later is None else "NONPOSITIVE" if after <= 0 else "POSITIVE_WORSENED" if after < before else "POSITIVE_IMPROVED" if after > before else "POSITIVE_UNCHANGED"})
    return {"baseline_winners": len(records), "proxy_retained": sum(r["proxy_present"] for r in records),
            "positive_retained": sum(r["still_positive"] for r in records),
            "status_counts": dict(sorted(Counter(r["status"] for r in records).items())),
            "identities": records, "large_ordinary_classification": _large_unknown()}


def compare_snapshots(old, new):
    """Match event proxies while keeping native identities/outcomes separate."""
    old_rows, new_rows = _rows(old), _rows(new)
    old_map, new_map = ({event_proxy(r): r for r in rows} for rows in (old_rows, new_rows))
    common = sorted(old_map.keys() & new_map.keys())
    removed = [old_map[k] for k in sorted(old_map.keys() - new_map.keys())]
    added = [new_map[k] for k in sorted(new_map.keys() - old_map.keys())]
    with localcontext() as ctx:
        ctx.prec = 80
        common_old, common_new = [old_map[k] for k in common], [new_map[k] for k in common]
        common_delta = _subtract(_vector(common_new), _vector(common_old))
        addition, removal = _vector(added), _vector(removed)
        observed_delta = _subtract(_vector(new_rows), _vector(old_rows))
        reconstructed = {key: common_delta[key] + addition[key] - removal[key] for key in VECTOR_FIELDS}
        if observed_delta != reconstructed:
            raise AssertionError("ATTRIBUTION_DOES_NOT_RECONCILE")
        changes = []
        for key in common:
            before, after = old_map[key], new_map[key]
            fields = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
            changes.append({"old_identity": _identity(before), "new_identity": _identity(after),
                            "changed_fields": fields,
                            "outcome_changed_fields": [k for k in fields if k in {"entry", "exit", "exit_ts", "reason", "gross_bps", "realized_cost_bps", "net_bps"}],
                            "old_outcomes": _vector([before]), "new_outcomes": _vector([after]),
                            "outcome_delta": _subtract(_vector([after]), _vector([before]))})
        prefix_equal = len(new_rows) >= len(old_rows) and new_rows[:len(old_rows)] == old_rows
        identical = old_rows == new_rows
        label = "IDENTICAL_ROWS" if identical else "APPEND_ONLY_ROWS" if prefix_equal else "ROLLING_RECOMPUTED_NOT_APPEND_ONLY"
        return _json({
            "schema_version": "zel.d.current_trendrider.snapshot_comparison.v1",
            "old_receipt_sha256": old.get("receipt_sha256"), "new_receipt_sha256": new.get("receipt_sha256"),
            "event_proxy_fields": list(PROXY_FIELDS),
            "event_proxy_caveat": "A matching event proxy is not proof of the same native intent, features, prices, costs or economic window.",
            "classification": label, "old_trades": len(old_rows), "new_trades": len(new_rows),
            "common_events": len(common), "removed_events": len(removed), "new_events": len(added),
            "common_any_field_changed": sum(bool(r["changed_fields"]) for r in changes),
            "common_economic_fields_changed": sum(bool(r["outcome_changed_fields"]) for r in changes),
            "common_field_change_counts": dict(sorted(Counter(k for r in changes for k in r["changed_fields"]).items())),
            "source_windows_equal": old.get("source") == new.get("source"),
            "old_source": copy.deepcopy(old.get("source")), "new_source": copy.deepcopy(new.get("source")),
            "prospective_boundary_equal": old.get("prospective_boundary_utc") == new.get("prospective_boundary_utc"),
            "old_prospective_boundary": old.get("prospective_boundary_utc"),
            "new_prospective_boundary": new.get("prospective_boundary_utc"),
            "decomposition": {"old_total": _vector(old_rows), "new_total": _vector(new_rows),
                              "common_old": _vector(common_old), "common_new": _vector(common_new),
                              "common_delta": common_delta, "removed_old_outcomes": removal,
                              "added_new_outcomes": addition, "observed_total_delta": observed_delta,
                              "common_delta_plus_added_minus_removed": reconstructed,
                              "exact_decimal_reconciliation": True},
            "common_records": changes,
            "removed_records": [{**_identity(r), "saved_row": copy.deepcopy(r), "outcomes": _vector([r])} for r in removed],
            "new_records": [{**_identity(r), "saved_row": copy.deepcopy(r), "outcomes": _vector([r])} for r in added],
            "baseline_winner_retention_1x": _winner_comparison(old_rows, new_map, 1),
            "baseline_winner_retention_2x": _winner_comparison(old_rows, new_map, 2),
            "september_winner_retention": {
                "entry_month_1x": _winner_comparison([r for r in old_rows if _date(r["entry_ts"], "%m") == "09"], new_map, 1),
                "exit_month_1x": _winner_comparison([r for r in old_rows if _date(r["exit_ts"], "%m") == "09"], new_map, 1),
                "entry_month_2x": _winner_comparison([r for r in old_rows if _date(r["entry_ts"], "%m") == "09"], new_map, 2),
            },
            "economic_improvement_or_alpha_claim": False,
            "reason": "Different stored rolling snapshots and costs; this is provenance/outcome attribution, not a controlled candidate run or account NAV comparison.",
        })
