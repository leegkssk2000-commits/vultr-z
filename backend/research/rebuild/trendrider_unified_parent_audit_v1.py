"""Issue 1272 Stage 0: immutable historical receipt audit, never an evaluator.

Only four explicitly frozen local sources may be read.  Trade-ledger arithmetic
can prove saved membership; it cannot prove a common input clock, decision-time
feature snapshots, or chronology/occupancy execution parity.  Those missing
inputs leave the economic permission gate closed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "trendrider_unified_parent_audit.v1"
SCOPE = "TRENDRIDER_UNIFIED_V1_AFTER_PRIMARY_BROAD_V1"
PREFIX = "backend/research/rebuild/"
SOURCES = {
    "descriptor": (PREFIX + "a1_trend_rider_wr8125_exact_parent_v1.json", "53b40669f5c4048dd99c5d4cf026c2cc74e5198fd7f083d39a4dcbe8799cad06"),
    "primary_source": (PREFIX + "a1_trend_rider_wr8125_upstream_source_receipt_v1.json", "b450c5793171637840a38c57947a52cd01b515c2816117f448dc6af6efc772cc"),
    "primary": (PREFIX + "a1_trendrider_wr8125_exact16_trade_receipt_v1.json", "f0b992200c73e8a4fa6fcf8f4c5e60aabc8f5bbbe0807aea7ee88ddc45435848"),
    "broad": (PREFIX + "a1_trend_rider_broad_wr7000_upstream_source_receipt_v1.json", "62d9327a83e86812f2d731bd75f4e936ed25c1f73b5e07dbe58f224c4370c3c9"),
}
RECEIPTS = {
    "primary_source": ("b064d6ee58c158cdb1169b79d93d1df46ea020d0dde3762703a577f9a3068103", 25),
    "primary": ("98e4abf1c6d7102f930f95db85fb125f6e726765834a8774d4cc24c662446625", 16),
    "broad": ("b9a7cc4c930952e9fae3a4b65012ceb393f0e084ee3c9decbd2854858a4fedd9", 30),
}
IDENTITY_FIELDS = ("symbol", "signal_ts", "entry_ts", "exit_ts", "side", "intent_sha")
OPPORTUNITY_FIELDS = ("symbol", "signal_ts", "side")
ANSWER_FIELDS = ("entry", "exit_ts", "exit", "reason", "gross_bps", "net_bps", "realized_cost_bps")
OVERLAP_FIELDS = ("entry_ts",) + ANSWER_FIELDS
FEATURE_FIELDS = ("session_state", "st_gap_state", "chase_state", "atr_state", "geometry_balance", "directional_persistence_state")
SNAPSHOT_META = ("observed_at_ms", "input_max_ts_ms", "source_sha256")
PRIMARY_ANCHOR = {
    "symbol": "ETH-USDT", "signal_ts": 1787079600000,
    "entry_ts": 1787083200000, "exit_ts": 1787256000000,
    "side": "long", "intent_sha": "7cc8614aaf6eba44b559ee6bbaaef2e6aaad2fd6d179b777bedebd3b4092dadf",
}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_authorized(root: Path, relative: str) -> dict[str, Any]:
    """Reject unknown paths and changed bytes before parsing their contents."""
    allow = {path: sha for path, sha in SOURCES.values()}
    if relative not in allow:
        raise ValueError("UNKNOWN_SOURCE_FORBIDDEN")
    base = root.resolve()
    source = (base / relative).resolve()
    if not source.is_relative_to(base):
        raise ValueError("SOURCE_OUTSIDE_ROOT_FORBIDDEN")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != allow[relative]:
        raise ValueError("FROZEN_SOURCE_FILE_HASH_MISMATCH:" + relative)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("SOURCE_OBJECT_REQUIRED")
    return value


def opportunity_key(row: Mapping[str, Any]) -> tuple[str, int, str]:
    if (not isinstance(row.get("symbol"), str) or not row["symbol"]
            or type(row.get("signal_ts")) is not int
            or row.get("side") not in {"long", "short"}):
        raise ValueError("MALFORMED_OPPORTUNITY_KEY")
    return row["symbol"], row["signal_ts"], row["side"]


def index_rows(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int, str], Mapping[str, Any]]:
    indexed: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    for row in rows:
        key = opportunity_key(row)
        if key in indexed:
            raise ValueError("DUPLICATE_UNDERLYING_OPPORTUNITY")
        indexed[key] = row
    return indexed


def verify_receipt(doc: Mapping[str, Any], expected_hash: str, expected_count: int) -> dict[str, bool]:
    rows = doc.get("trades")
    rows_ok = isinstance(rows, list) and all(isinstance(x, dict) for x in rows)
    no_duplicate = False
    if rows_ok:
        try:
            index_rows(rows)
            no_duplicate = True
        except ValueError:
            pass
    return {
        "receipt_hash": doc.get("receipt_sha256") == expected_hash
            == digest({k: v for k, v in doc.items() if k != "receipt_sha256"}),
        "row_count": rows_ok and len(rows) == expected_count,
        "underlying_unique": no_duplicate,
        "no_execution_authority": doc.get("execution_authority") == "NONE"
            and doc.get("order_authority") == "BLOCKED"
            and doc.get("live_trade_authority") == "BLOCKED"
            and doc.get("promotion_authority") is False
            and doc.get("selection_authority") is False,
    }


def session_state(signal_ts: int) -> str:
    hour = datetime.fromtimestamp(signal_ts / 1000, timezone.utc).hour
    return "APAC" if hour < 8 else "EU" if hour < 16 else "US"


def structural_snapshot_checks(snapshot: Any, decision_ts: int | None) -> dict[str, bool]:
    """Structural rejection checks only; no recovered native clock or feature proof.

    Native signal_ts labels the signal bar's open.  It must not be silently used
    as an independently established decision/observation timestamp.
    """
    exists = isinstance(snapshot, dict)
    value = snapshot if exists else {}
    before = lambda x: type(decision_ts) is int and type(x) is int and 0 <= x <= decision_ts
    source_hash = value.get("source_sha256")
    return {
        "snapshot_present": exists,
        "only_decision_columns": exists and set(value) == set(FEATURE_FIELDS + SNAPSHOT_META),
        "feature_columns_present": exists and all(k in value and value[k] is not None for k in FEATURE_FIELDS),
        "observable_by_decision": before(value.get("observed_at_ms")),
        "input_prefix_causal": before(value.get("input_max_ts_ms")),
        "source_content_hash_present": isinstance(source_hash, str) and len(source_hash) == 64
            and all(c in "0123456789abcdef" for c in source_hash),
        "native_decision_clock_proven": False,
        "feature_taxonomy_and_values_proven": False,
    }


def saved_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Receipt-order arithmetic only; no market data, replay, or marked DD."""
    values = [float(x["net_bps"]) for x in rows]
    if any(not math.isfinite(x) for x in values):
        raise ValueError("NONFINITE_SAVED_PNL")
    wins, losses = [x for x in values if x > 0], [-x for x in values if x < 0]
    gp, gl = sum(wins), sum(losses)
    cumulative = peak = dd = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        dd = max(dd, peak - cumulative)
    costs = sum(float(x["realized_cost_bps"]) for x in rows)
    worst_losses = sorted(-x for x in losses)[:max(1, math.ceil(len(losses) / 10))]
    events = [(x["entry_ts"], 1) for x in rows] + [(x["exit_ts"], -1) for x in rows]
    current = maximum = 0
    for _, change in sorted(events):
        current += change
        maximum = max(maximum, current)
    return {
        "completed_trades": len(values), "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "gross_pnl_bps": sum(float(x["gross_bps"]) for x in rows),
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "average_win_bps": gp / len(wins) if wins else None,
        "average_loss_bps": -gl / len(losses) if losses else None,
        "profit_factor": gp / gl if gl else None,
        "payoff": (gp / len(wins)) / (gl / len(losses)) if wins and losses else None,
        "max_drawdown_bps": dd,
        "realized_cost_bps": costs,
        "cost2_net_pnl_bps": sum(values) - costs,
        "worst_trade_bps": min(values) if values else None,
        "bottom_decile_loss_mean_bps": sum(worst_losses) / len(worst_losses) if worst_losses else None,
        "bottom_decile_loss_count": len(worst_losses),
        "additive_symbol_days": sum(x["exit_ts"] - x["entry_ts"] for x in rows) / 86400000,
        "max_concurrent_independent_saved_rows": maximum,
        "top1_positive_contribution_fraction": max(wins) / gp if wins else None,
        "exposure_semantics": "SUM_OF_INDEPENDENT_FULL_UNIT_SAVED_ROWS_NOT_OCCUPANCY_FULL_OR_ACCOUNT_EXPOSURE",
        "drawdown_semantics": "STORED_RECEIPT_ROW_ORDER_CLOSED_PNL_ONLY_NOT_MARKED_DD",
    }


def metric_parity(observed: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, bool]:
    aliases = {"completed_trades": "trades", "max_drawdown_bps": "drawdown_bps",
               "profit_factor": "net_profit_factor", "payoff": "net_payoff"}
    result = {}
    for key in ("completed_trades", "wins", "win_rate", "net_pnl_bps", "net_expectancy_bps",
                "profit_factor", "payoff", "max_drawdown_bps"):
        value = observed[key]
        target = expected.get(key, expected.get(aliases.get(key, "")))
        if key == "wins" and target is None and expected.get("win_rate") is not None:
            target = round(float(expected["win_rate"]) * int(observed["completed_trades"]))
        result[key] = target is not None and value is not None and math.isclose(
            float(value), float(target), rel_tol=1e-12, abs_tol=1e-8)
    return result


def overlap_parity(primary: Mapping[tuple, Mapping], broad: Mapping[tuple, Mapping]) -> list[dict[str, Any]]:
    mismatches = []
    for key in sorted(primary.keys() & broad.keys()):
        changed = [field for field in OVERLAP_FIELDS if primary[key].get(field) != broad[key].get(field)]
        if changed:
            mismatches.append({"opportunity": list(key), "different_fields": changed})
    return mismatches


def occupancy_diagnostic(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Describe overlapping saved holding intervals; do not simulate a book."""
    pairs = 0
    max_by_symbol = {}
    for symbol in sorted({x["symbol"] for x in rows}):
        selected = [x for x in rows if x["symbol"] == symbol]
        for i, a in enumerate(selected):
            for b in selected[i + 1:]:
                pairs += max(a["entry_ts"], b["entry_ts"]) < min(a["exit_ts"], b["exit_ts"])
        events = [(x["entry_ts"], 1) for x in selected] + [(x["exit_ts"], -1) for x in selected]
        current = maximum = 0
        for _, change in sorted(events):  # Half-open intervals: exits first on equal timestamps.
            current += change
            maximum = max(maximum, current)
        max_by_symbol[symbol] = maximum
    return {"same_symbol_overlapping_pairs": pairs, "maximum_simultaneous_saved_trades_by_symbol": max_by_symbol,
            "interval_semantics": "HALF_OPEN_ENTRY_EXIT", "shared_book_execution_proven": False}


def build_report(root: Path) -> dict[str, dict[str, Any]]:
    """Return documents; caller owns all writes and all execution budgets."""
    audit: dict[str, Any] = {
        "schema_version": SCHEMA, "scope": SCOPE, "state": "BLOCKED_PARENT_PARITY",
        "saved_membership_parity": "BLOCKED", "common_input_parity": "BLOCKED",
        "economic_execution_authorized": False,
        "executions": {"gene_screens": 0, "canonical_candidates": 0, "child_full": 0,
                       "parent_control_replay": 0, "economic_retry": 0, "network_requests": 0},
        "source_inventory": [{"role": role, "path": path, "expected_file_sha256": sha}
                             for role, (path, sha) in SOURCES.items()],
    }
    documents: dict[str, dict[str, Any]] = {
        "PARENT_AUDIT.json": audit,
        "OPPORTUNITIES.json": {"schema_version": SCHEMA, "rows": []},
        "DECISION_FEATURES.json": {"schema_version": SCHEMA, "rows": []},
        "OUTCOME_ANSWERS.json": {"schema_version": SCHEMA, "runtime_decision_use_forbidden": True, "rows": []},
    }
    try:
        sources = {name: read_authorized(root, path) for name, (path, _) in SOURCES.items()}
    except (ValueError, OSError) as exc:
        audit["blockers"] = [str(exc)]
        return documents
    descriptor = sources["descriptor"]
    pdoc, bdoc, upstream = sources["primary"], sources["broad"], sources["primary_source"]
    checks = {name: verify_receipt(sources[name], sha, count) for name, (sha, count) in RECEIPTS.items()}
    audit["receipt_checks"] = checks
    if not all(all(row.values()) for row in checks.values()):
        audit["blockers"] = ["IMMUTABLE_RECEIPT_INTEGRITY_FAILED"]
        return documents
    prows, brows = pdoc["trades"], bdoc["trades"]
    pi, bi, ui = index_rows(prows), index_rows(brows), index_rows(upstream["trades"])
    prefix = sorted(upstream["trades"], key=lambda x: (x["entry_ts"], x["symbol"]))[:24]
    identity = lambda x: {field: x.get(field) for field in IDENTITY_FIELDS}
    selected = [x for x in prefix if session_state(x["signal_ts"]) != "US" or identity(x) == PRIMARY_ANCHOR]
    primary_metrics, broad_metrics = saved_metrics(prows), saved_metrics(brows)
    membership_checks = {
        "descriptor_primary_lane": descriptor.get("lane_id") == "trend_rider_primary_wr8125",
        "descriptor_source_digest": descriptor["historical_source"]["upstream_receipt_sha256"] == RECEIPTS["primary_source"][0],
        "exact16_immutable_membership": [identity(x) for x in selected] == [identity(x) for x in prows],
        "every_exact16_value_preserved": len(selected) == len(prows) and all(
            all(original.get(k) == v for k, v in exact.items()) for original, exact in zip(selected, prows)),
        "primary_metric_parity": all(metric_parity(primary_metrics, descriptor["metrics"]).values()),
        "broad_metric_parity": all(metric_parity(broad_metrics, {**bdoc["metrics"], "completed_trades": 30}).values()),
    }
    overlap_mismatches = overlap_parity(pi, bi)
    membership_checks["overlap_economic_values_identical"] = not overlap_mismatches
    audit.update({
        "saved_membership_parity": "PASS" if all(membership_checks.values()) else "BLOCKED",
        "membership_checks": membership_checks,
        "primary_immutable_identity_sha256": digest([identity(x) for x in prows]),
        "opportunity_identity_fields": list(OPPORTUNITY_FIELDS),
        "counts": {"primary": len(pi), "broad": len(bi), "overlap": len(pi.keys() & bi.keys()),
                   "primary_only": len(pi.keys() - bi.keys()), "broad_only": len(bi.keys() - pi.keys()),
                   "unique_union": len(pi.keys() | bi.keys())},
        "overlap_economic_mismatches": overlap_mismatches,
        "overlap_intent_hashes_equal": sum(pi[k]["intent_sha"] == bi[k]["intent_sha"] for k in pi.keys() & bi.keys()),
        "saved_parent_metrics": {"primary": primary_metrics, "broad": broad_metrics},
        "saved_holding_interval_diagnostic": {"primary": occupancy_diagnostic(prows), "broad": occupancy_diagnostic(brows)},
    })
    primary_clock = upstream["source"]
    broad_clock = bdoc["source"]
    pend = {x["symbol"]: x["last_post_boundary_ts"] for x in primary_clock["symbols"]}
    bend = {x["symbol"]: x["last_post_boundary_ts"] for x in broad_clock["symbols"]}
    missing_common = [list(k) for k in sorted(pi) if pi[k]["signal_ts"] > bend.get(k[0], -1)]
    economic_cost_keys = ("symbol", "fee_bps", "spread_bps", "impact_bps", "funding_p95_abs_bps", "pretrade_verified_cost_bps")
    snapshot_values = lambda doc: {s: {k: v.get(k) for k in economic_cost_keys} for s, v in doc["execution_snapshots"].items()}
    audit["common_input_checks"] = {
        "same_config_digest": upstream["config_sha"] == bdoc["config_sha"],
        "same_cost_authority_digest": upstream["cost_authority_sha256"] == bdoc["cost_authority_sha256"],
        "same_economic_cost_components": snapshot_values(upstream) == snapshot_values(bdoc),
        "same_cost_snapshot_identities": upstream["execution_snapshots"] == bdoc["execution_snapshots"],
        "same_source_clock_metadata": primary_clock == broad_clock,
        "all_primary_signals_in_broad_clock": not missing_common,
        "raw_frozen_input_content_available": False,
        "raw_frozen_input_content_hash_available": False,
        "complete_decision_snapshots_available": False,
        "full_common_signal_ledger_available": False,
        "shared_occupancy_execution_witness_available": False,
    }
    audit["source_clocks"] = {"primary": primary_clock, "broad": broad_clock,
                              "primary_end_ms": pend, "broad_end_ms": bend,
                              "primary_opportunities_outside_broad_clock": missing_common}
    for key in sorted(pi.keys() | bi.keys()):
        underlying = dict(zip(OPPORTUNITY_FIELDS, key))
        oid = digest(underlying)
        categories = [name for name, table in (("primary", pi), ("broad", bi)) if key in table]
        documents["OPPORTUNITIES.json"]["rows"].append({
            "opportunity_id": oid, **underlying, "historical_membership": categories,
            "membership_is_runtime_rule": False,
        })
        references = {}
        for lane, table, full in (("primary", pi, ui), ("broad", bi, bi)):
            if key not in table:
                continue
            row = table[key]
            references[lane] = {"feature_sha": full[key].get("feature_sha"),
                                "feature_snapshot_available": False}
            documents["OUTCOME_ANSWERS.json"]["rows"].append({
                "opportunity_id": oid, "lane": lane, "entry_ts": row["entry_ts"],
                **{field: row[field] for field in ANSWER_FIELDS},
            })
        documents["DECISION_FEATURES.json"]["rows"].append({
            "opportunity_id": oid, "signal_ts": key[1],
            "signal_ts_semantics": "NATIVE_SIGNAL_BAR_OPEN_TIMESTAMP",
            "decision_ts": None, "decision_time_not_proven": True,
            "derived_timestamp_session": session_state(key[1]),
            "session_taxonomy": "APAC_UTC_00_07__EU_UTC_08_15__US_UTC_16_23",
            "snapshot": None, "snapshot_checks": structural_snapshot_checks(None, None),
            "historical_feature_digest_references": references,
            "feature_hash_is_not_feature_snapshot": True,
        })
    audit["blockers"] = [
        "ORIGINAL_FROZEN_OHLCV_AND_INPUT_CONTENT_HASH_NOT_IN_SAVED_RECEIPTS",
        "ORIGINAL_COMPLETE_DECISION_FEATURE_SNAPSHOTS_NOT_IN_SAVED_RECEIPTS",
        "PARENT_CLOCK_ENDPOINTS_DIFFER_PRIMARY_ONLY_OPPORTUNITY_OUTSIDE_BROAD_COVERAGE",
        "COST_COMPONENT_VALUES_MATCH_BUT_ORIGINAL_SNAPSHOT_IDENTITIES_DIFFER",
        "SAVED_COMPLETED_TRADE_LIST_IS_NOT_COMMON_CHRONOLOGICAL_SIGNAL_OCCUPANCY_LEDGER",
    ]
    audit["no_market_fetch_or_replay"] = True
    audit["qualification_credit"] = 0
    return documents
