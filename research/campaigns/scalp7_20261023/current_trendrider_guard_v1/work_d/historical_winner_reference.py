"""Compare published historical winners with saved receipts; no replay or filtering.

The reference is a frozen selection from previously published top-k identity lists,
not a newly ranked/recomputed historical ledger. Event proxies are correspondence
keys only: unchanged timestamps do not prove unchanged native features or costs.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

PROXY_FIELDS = ("symbol", "side", "signal_ts", "entry_ts")
HASH_FIELDS = ("feature_sha", "intent_sha", "parent_intent_sha", "cost_snapshot_sha", "config_sha", "policy_sha")
LIMITATIONS = {
    "economic_replay": "NOT_RUN",
    "old_summary_recomputed": False,
    "account_NAV": "NOT_RUN",
    "strategy_filter_effect_established": False,
    "feature_body_equality_established": False,
    "causal_absence_explanation": "NOT_ESTABLISHED",
    "interpretation": "Saved outcome correspondence only. Visible-window metadata is not feature-body or lookback evidence.",
}


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def seal_reference(reference):
    """Return a detached snapshot with a reproducibility digest, not a signature."""
    result = copy.deepcopy(reference)
    result.pop("reference_content_sha256", None)
    result["reference_content_sha256"] = canonical_sha256(result)
    return result


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("INVALID_TIMESTAMP")
    return value


def event_proxy(row):
    if not isinstance(row.get("symbol"), str) or not row["symbol"] or row.get("side") not in ("long", "short"):
        raise ValueError("INVALID_EVENT_PROXY")
    return row["symbol"], row["side"], _integer(row["signal_ts"]), _integer(row["entry_ts"])


def _number(value):
    if isinstance(value, bool):
        raise ValueError("INVALID_OUTCOME_NUMBER")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("INVALID_OUTCOME_NUMBER") from None
    if not result.is_finite():
        raise ValueError("INVALID_OUTCOME_NUMBER")
    return result


def _utc(ts):
    return datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _relation(ts, first, last):
    return "BEFORE" if ts < first else "AFTER" if ts > last else "WITHIN"


def _window(row, windows):
    window = windows.get(row["symbol"])
    if window is None:
        return {"classification": "SOURCE_WINDOW_UNBOUND", "metadata": None}
    first = _integer(window["first_post_boundary_ts"])
    last = _integer(window["last_post_boundary_ts"])
    if first > last:
        raise ValueError("INVALID_SOURCE_WINDOW")
    signal = _relation(row["signal_ts"], first, last)
    entry = _relation(row["entry_ts"], first, last)
    classification = ("BEFORE_CURRENT_VISIBLE_SOURCE_WINDOW" if signal == entry == "BEFORE" else
                      "AFTER_CURRENT_VISIBLE_SOURCE_WINDOW" if signal == entry == "AFTER" else
                      "WITHIN_CURRENT_VISIBLE_SOURCE_WINDOW" if signal == entry == "WITHIN" else
                      "STRADDLES_CURRENT_VISIBLE_SOURCE_WINDOW")
    return {"classification": classification, "signal_relation": signal, "entry_relation": entry,
            "metadata": copy.deepcopy(window), "first_visible_utc": _utc(first), "last_visible_utc": _utc(last)}


def compare_reference(reference, currentreceipt):
    """Pure comparison of a sealed published reference and one saved receipt.

    No mutation, strategy call, new historical ranking, aggregate P&L or account
    accounting. Exact proxy duplicates are rejected instead of arbitrarily joined.
    Source-file hashes are provenance supplied by the reference producer; the CLI
    additionally pins exact bytes of both new inputs.
    """
    if reference.get("reference_content_sha256") != seal_reference(reference)["reference_content_sha256"]:
        raise ValueError("REFERENCE_CONTENT_DIGEST_MISMATCH")
    if reference.get("schema_version") != "work_d.historical_published_top10_reference.v1":
        raise ValueError("REFERENCE_SCHEMA_MISMATCH")
    if currentreceipt.get("challenger_id") != reference["expected_challenger_id"]:
        raise ValueError("CURRENT_LANE_MISMATCH")
    if currentreceipt.get("schema_version") != reference["old_input_binding"]["schema_version"]:
        raise ValueError("CURRENT_SCHEMA_MISMATCH")
    index = {}
    for row in currentreceipt["trades"]:
        key = event_proxy(row)
        if key in index:
            raise ValueError("DUPLICATE_CURRENT_EVENT_PROXY")
        index[key] = row
    windows = {}
    for window in currentreceipt.get("source", {}).get("symbols", []):
        if window["symbol"] in windows:
            raise ValueError("DUPLICATE_SYMBOL_SOURCE_WINDOW")
        windows[window["symbol"]] = window
    published_ids = []
    for group in reference["published_topk_1x"]:
        for identity in group["row_identity_sha256s"]:
            if identity not in published_ids:
                published_ids.append(identity)
    if [r["row_identity_sha256"] for r in reference["rows"]] != published_ids:
        raise ValueError("PUBLISHED_SELECTION_MISMATCH")
    rows = []
    seen = set()
    for rank, historical in enumerate(reference["rows"], 1):
        if historical["published_rank"] != rank:
            raise ValueError("PUBLISHED_RANK_MISMATCH")
        old = historical["saved_row"]
        key = event_proxy(old)
        if key in seen:
            raise ValueError("DUPLICATE_REFERENCE_EVENT_PROXY")
        seen.add(key)
        current = index.get(key)
        window = _window(old, windows)
        result = {
            "published_rank": rank, "historical_row_identity_sha256": historical["row_identity_sha256"],
            "event_proxy": dict(zip(PROXY_FIELDS, key)),
            "signal_utc": _utc(old["signal_ts"]), "entry_utc": _utc(old["entry_ts"]),
            "historical_saved_row": copy.deepcopy(old),
            "historical_published_outcomes": copy.deepcopy(historical["retrospective_outcomes_not_execution_features"]),
            "current_saved_row": copy.deepcopy(current),
            "event_proxy_match": current is not None, "source_window": window,
            "status": "PRESENT_EVENT_PROXY" if current is not None else "ABSENT_" + window["classification"],
            "absence_does_not_establish_strategy_filter_effect": True,
            "same_proxy_does_not_establish_same_feature_body": True,
            "outcomes": {}, "changed_hash_fields": {},
        }
        for field in ("gross_bps", "net_bps", "realized_cost_bps"):
            oldvalue = _number(old[field])
            newvalue = None if current is None else _number(current[field])
            result["outcomes"][field] = {
                "historical_saved_value": str(oldvalue),
                "current_saved_value": None if newvalue is None else str(newvalue),
                "current_minus_historical_saved_value": None if newvalue is None else str(newvalue - oldvalue),
                "changed": None if newvalue is None else newvalue != oldvalue,
                "unit": "trade_bps_not_account_NAV",
            }
        if current is not None:
            result["full_saved_row_identical"] = old == current
            result["changed_hash_fields"] = {field: {"historical": old.get(field), "current": current.get(field)}
                                             for field in HASH_FIELDS if old.get(field) != current.get(field)}
        else:
            result["full_saved_row_identical"] = None
        rows.append(result)
    by_id = {row["historical_row_identity_sha256"]: row for row in rows}
    group_results = []
    for group in reference["published_topk_1x"]:
        selected = [by_id[identity] for identity in group["row_identity_sha256s"]]
        counts = {}
        for row in selected:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        group_results.append({"historical_published_group_verbatim": copy.deepcopy(group), "correspondence_counts": counts})
    return {
        "schema_version": "work_d.historical_winner_reference_comparison.v1",
        "historical_completion_commit": reference["historical_completion_commit"],
        "historical_source_file_pins": copy.deepcopy(reference["historical_source_file_pins"]),
        "reference_content_sha256": reference["reference_content_sha256"],
        "old_input_binding": copy.deepcopy(reference["old_input_binding"]),
        "historical_published_topk_2x_verbatim": copy.deepcopy(reference.get("published_topk_2x", [])),
        "current_identity": {field: currentreceipt.get(field) for field in
                             ("challenger_id", "schema_version", "receipt_sha256", "parent_receipt_sha256", "completed_trades",
                              "config_sha", "policy_sha", "contract_sha256", "cost_authority_sha256", "evidence_sha",
                              "boundary_utc", "prospective_boundary_utc")},
        "historical_topk_correspondence": group_results, "rows": rows,
        "limitations": copy.deepcopy(LIMITATIONS),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--current", action="append", required=True, metavar="LABEL=PATH")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = Path(args.reference).read_bytes()
    reference = json.loads(raw)
    output = {"schema_version": "work_d.historical_winner_reference_bundle.v1",
              "reference_file": {"path": args.reference, "sha256": hashlib.sha256(raw).hexdigest()}, "cohorts": {}}
    for item in args.current:
        label, path = item.split("=", 1)
        if not label or label in output["cohorts"]:
            raise ValueError("DUPLICATE_OR_EMPTY_COHORT_LABEL")
        currentraw = Path(path).read_bytes()
        compared = compare_reference(reference, json.loads(currentraw))
        compared["current_source_file"] = {"path": path, "sha256": hashlib.sha256(currentraw).hexdigest()}
        output["cohorts"][label] = compared
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
