"""Pure, fail-closed Squeeze lot evidence accounting; no runtime or market calls.

Artifacts are provided by an authenticated upstream collector.  Content hashes
prove consistency, not that HTTP requests happened: this module cannot establish
source readiness, create a boundary, register a lane, or start collection.

All monetary amounts are quote-currency cash, with base-quantity depth fills.
Funding uses signed settlement rates and the actual lot quantity at settlement.
No DEV cost/funding proxy or default zero substitutes for missing evidence.

Production limitation: consumption prefixes are validated within one campaign.
Different lots sharing one book need an authenticated global fill-prefix witness
from the dispatcher; that integration is absent. A later lot with a nonzero
external prefix is rejected, not credited. Passing this per-campaign validator
does not establish cross-lot shared-book or runtime readiness.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

FIVE_MIN_MS = 300_000
CROSS_LOT_SHARED_BOOK_SUPPORTED = False
IDENTITY_KEYS = (
    "strategy_name", "strategy_digest", "candidate_id", "candidate_ordinal",
    "lane_id", "strategy_id", "child_id", "activation_id", "cohort_id",
    "implementation_code_sha", "adapter_code_sha", "entry_sha", "exit_sha",
    "config_sha", "data_sha", "cost_sha", "mechanism_sha", "source_receipt_sha", "fee_authority_sha",
)
FROZEN = {
    "strategy_name": "Squeeze Continuation v1",
    "candidate_id": "C70_TM_CAPREUSE_V1", "candidate_ordinal": 82,
    "lane_id": "SQUEEZE_CONTINUATION_V1_G5B_FRESH",
    "strategy_digest": "5c63d3a69e1398dd1fae1076c9e8bdc29b8252a3188ac6b6a79571b363b22a16",
    "implementation_code_sha": "57e687ddda322c8ee347ad8f7e32a92a1328b918",
    "entry_sha": "0b11cfe382c202b8df1affd054e2ce1bc7e805f1d6132aaf9069219c4532fc82",
    "exit_sha": "673f353408884a8d2510185c1544bcd2afab9fa1448eff25ccfebeffd552fc91",
}
AUTH = {"selection": False, "promotion": False, "execution": "NONE",
        "order": "BLOCKED", "live": "BLOCKED", "g6_allowed": False}
NUMERIC_OUTPUTS = (
    "gross_mid_cash", "slippage_cash", "fee_cash", "funding_cash", "net_cash",
    "realized_partial_cash", "remaining_mark_cash", "remaining_exit_cost_cash",
    "MFE_bps", "MAE_bps",
)


class EvidenceError(ValueError):
    pass


def require(condition: Any, reason: str) -> None:
    if not condition:
        raise EvidenceError(reason)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def seal(value: Mapping[str, Any]) -> dict[str, Any]:
    core = copy.deepcopy(dict(value))
    core.pop("receipt_sha256", None)
    return {**core, "receipt_sha256": stable_sha(core)}


def check_seal(value: Any, label: str) -> Mapping[str, Any]:
    require(isinstance(value, Mapping), label + "_MISSING")
    core = {k: v for k, v in value.items() if k != "receipt_sha256"}
    require(value.get("receipt_sha256") == stable_sha(core), label + "_HASH")
    return value


def number(value: Any, label: str, *, positive: bool = False) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), label + "_MISSING_OR_NONFINITE")
    require(not positive or value > 0, label + "_NONPOSITIVE")
    return float(value)


def timestamp(value: Any, label: str) -> int:
    require(type(value) is int and value > 0, label + "_TIMESTAMP")
    return value


def raw_number(value: Any, label: str, *, positive: bool = False) -> float:
    """Exchange JSON often represents prices/rates as decimal strings."""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError as exc:
            raise EvidenceError(label + "_RAW_NUMBER") from exc
    return number(value, label, positive=positive)


def same(actual: Any, expected: float, label: str) -> None:
    require(math.isclose(number(actual, label), expected, rel_tol=1e-10, abs_tol=1e-10),
            label + "_RECONCILIATION")


def identity(value: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    require(all(expected.get(k) not in (None, "") for k in IDENTITY_KEYS), "IDENTITY_EXPECTED_MISSING")
    require(all(expected.get(k) == v for k, v in FROZEN.items()), "FROZEN_IDENTITY_DRIFT")
    require(all(value.get(k) == expected[k] for k in IDENTITY_KEYS), "IDENTITY_PARITY")
    for key in IDENTITY_KEYS:
        if key.endswith("sha") or key == "strategy_digest":
            text = expected[key]
            require(isinstance(text, str) and len(text) in (40, 64)
                    and all(c in "0123456789abcdef" for c in text), "IDENTITY_HASH_FORMAT:" + key)


def source(value: Any, label: str, *, as_of_ms: int) -> Mapping[str, Any]:
    result = check_seal(value, label)
    require(isinstance(result.get("source_endpoint"), str) and result["source_endpoint"], label + "_SOURCE")
    require(result.get("origin") == "FORWARD_REAL" and result.get("proxy") is False, label + "_PROXY")
    require(timestamp(result.get("observed_ts"), label) <= as_of_ms, label + "_FUTURE")
    require(isinstance(result.get("raw"), (Mapping, list)), label + "_RAW_MISSING")
    return result


def depth_vwap_base(levels: Sequence[Sequence[Any]], base_qty: float, *,
                    consumed_base_before: float = 0.0) -> float:
    """Consume base_qty after earlier fills on the same observed order book."""
    left = number(base_qty, "BASE_QTY", positive=True)
    skip = number(consumed_base_before, "DEPTH_CONSUMED_BEFORE")
    require(skip >= 0, "DEPTH_CONSUMED_BEFORE_NEGATIVE")
    paid = 0.0
    require(isinstance(levels, (list, tuple)) and levels, "DEPTH_EMPTY")
    for row in levels:
        require(isinstance(row, (list, tuple)) and len(row) == 2, "DEPTH_LEVEL")
        price, quantity = (raw_number(row[0], "DEPTH_PRICE", positive=True),
                           raw_number(row[1], "DEPTH_QTY", positive=True))
        already_used = min(skip, quantity)
        skip -= already_used
        quantity -= already_used
        used = min(left, quantity)
        paid += used * price
        left -= used
    require(skip <= 1e-12 and left <= max(1e-12, base_qty * 1e-12), "DEPTH_BASE_QTY_UNFILLED")
    return paid / base_qty


def _depth(value: Any, *, symbol: str, qty: float, buy: bool,
           due_ts: int, as_of_ms: int, consumed_before: float = 0.0) -> dict[str, Any]:
    depth = source(value, "DEPTH", as_of_ms=as_of_ms)
    require(depth.get("symbol") == symbol and depth.get("source_endpoint") == "/openApi/swap/v2/quote/depth", "DEPTH_SOURCE_PARITY")
    raw = depth["raw"]
    requested = timestamp(depth.get("requested_ts"), "DEPTH_REQUEST")
    exchange = timestamp(raw.get("time"), "DEPTH_EXCHANGE")
    require(due_ts <= requested <= depth["observed_ts"] and due_ts <= exchange <= depth["observed_ts"], "DEPTH_POINT_IN_TIME")
    bids, asks = raw["bids"], raw["asks"]
    # Validate every retained level and the exchange order, not just the fill prefix.
    for levels, descending in ((bids, True), (asks, False)):
        require(isinstance(levels, list) and levels, "DEPTH_EMPTY")
        prices = [raw_number(r[0], "DEPTH_PRICE", positive=True) for r in levels]
        require(prices == sorted(set(prices), reverse=descending), "DEPTH_ORDER_OR_DUPLICATE")
        for row in levels:
            require(len(row) == 2, "DEPTH_LEVEL")
            raw_number(row[1], "DEPTH_QTY", positive=True)
    bid, ask = float(bids[0][0]), float(asks[0][0])
    require(bid < ask, "DEPTH_CROSSED")
    mid, best = (bid + ask) / 2, ask if buy else bid
    vwap = depth_vwap_base(asks if buy else bids, qty, consumed_base_before=consumed_before)
    return {"bid": bid, "ask": ask, "mid": mid, "vwap": vwap,
            "spread_cash": abs(best - mid) * qty,
            "impact_cash": abs(vwap - best) * qty,
            "slippage_cash": abs(vwap - mid) * qty,
            "observed_ts": depth["observed_ts"], "depth_sha": depth["receipt_sha256"]}


def _fee(value: Any, *, observed_ts: int, notional: float, expected_sha: str) -> float:
    fee = source(value, "FEE", as_of_ms=observed_ts)
    require(fee["receipt_sha256"] == expected_sha, "FEE_FROZEN_AUTHORITY_PARITY")
    require(fee.get("source_kind") == "OFFICIAL_TAKER_FEE", "FEE_AUTHORITY_KIND")
    require(timestamp(fee.get("effective_from_ms"), "FEE_EFFECTIVE_FROM") <= observed_ts
            < timestamp(fee.get("effective_until_ms"), "FEE_EFFECTIVE_UNTIL"), "FEE_EFFECTIVE_INTERVAL")
    rate = raw_number(fee["raw"].get("taker_fee_bps"), "FEE_RATE")
    require(rate >= 0, "FEE_NEGATIVE")
    return notional * rate / 10_000


def validate_leg(leg: Mapping[str, Any], expected_identity: Mapping[str, Any], *,
                 boundary_ms: int, as_of_ms: int) -> dict[str, Any]:
    """Validate a self-contained observed fill.  Legs never receive formal T."""
    result = {"schema_version": "zel.squeeze_g5b.leg_validation.v1", "record_id": leg.get("leg_id"),
              "record_kind": "LEG", "lot_id": leg.get("lot_id"), "campaign_id": leg.get("campaign_id"),
              "as_of_ms": as_of_ms, "boundary_ms": boundary_ms,
              "identity": dict(expected_identity), "inputs": copy.deepcopy(dict(leg)),
              "input_sha": stable_sha(leg), "production_grade": False,
              "formal_fresh_T": 0, "derived": None, "blockers": [], **AUTH}
    try:
        identity(leg, expected_identity)
        timestamp(boundary_ms, "BOUNDARY"); timestamp(as_of_ms, "AS_OF")
        require(all(isinstance(leg.get(k), str) and leg[k] for k in
                    ("leg_id", "lot_id", "campaign_id", "symbol", "signal_sha")), "LEG_IDS_MISSING")
        require(leg.get("side") == "long", "FROZEN_LONG_SIDE_REQUIRED")
        require(leg.get("kind") in ("ENTRY", "PARTIAL", "FINAL_EXIT"), "LEG_KIND")
        require(type(leg.get("leg_sequence")) is int and leg["leg_sequence"] >= 0, "LEG_SEQUENCE")
        require(leg.get("duplicate") == 0 and leg.get("lookahead") == 0
                and leg.get("historical_backfill") is False, "LEG_CAUSALITY_FLAGS")
        decision = timestamp(leg.get("decision_ts"), "DECISION")
        decision_observed = timestamp(leg.get("decision_observed_ts"), "DECISION_OBSERVED")
        due = timestamp(leg.get("due_open_ts"), "DUE_OPEN")
        observed = timestamp(leg.get("observed_ts"), "OBSERVED")
        require(boundary_ms < decision <= decision_observed <= observed <= as_of_ms, "LEG_TIME_ORDER")
        bar = source(leg.get("decision_bar"), "DECISION_BAR", as_of_ms=decision_observed)
        require(bar.get("symbol") == leg["symbol"]
                and timestamp(bar["raw"].get("bar_close_ts"), "DECISION_CLOSE") <= bar["observed_ts"], "DECISION_COMPLETED_BAR")
        if leg["kind"] == "ENTRY":
            require(bar["raw"]["bar_close_ts"] > boundary_ms
                    and leg["signal_sha"] == bar["receipt_sha256"], "ENTRY_SIGNAL_BOUNDARY_OR_SHA")
        # A continuous next bar opens at this completed bar's close. Actual
        # receipt/execution lag remains in observed timestamps, never in due.
        require(bar["raw"]["bar_close_ts"] == decision == due, "NEXT_OPEN_DECISION_BAR_PARITY")
        qty = number(leg.get("base_qty"), "LEG_QTY", positive=True)
        nq = number(leg.get("normalized_qty"), "NORMALIZED_QTY", positive=True)
        require(nq <= 1.0, "NORMALIZED_QTY_CAP")
        d = _depth(leg.get("depth"), symbol=leg["symbol"], qty=qty,
                   buy=leg["kind"] == "ENTRY", due_ts=decision_observed, as_of_ms=as_of_ms,
                   consumed_before=number(leg.get("depth_consumed_base_before"), "DEPTH_CONSUMED_BEFORE"))
        require(observed == d["observed_ts"], "LEG_DEPTH_TIMESTAMP_PARITY")
        same(leg.get("delay_ms"), observed - due, "DELAY")
        notional = qty * d["vwap"]
        same(leg.get("notional"), notional, "NOTIONAL")
        fee = _fee(leg.get("fee_authority"), observed_ts=observed, notional=notional,
                   expected_sha=expected_identity["fee_authority_sha"])
        same(leg.get("fee_cash"), fee, "FEE_CASH")
        same(leg.get("slippage_cash"), d["slippage_cash"], "SLIPPAGE")
        same(leg.get("impact_cash"), d["impact_cash"], "IMPACT")
        direction = -1 if leg["kind"] == "ENTRY" else 1
        result.update(production_grade=True, derived={**d, "base_qty": qty, "normalized_qty": nq,
                      "fee_cash": fee, "notional": notional,
                      "mid_cash": direction * qty * d["mid"], "execution_cash": direction * notional})
    except (EvidenceError, KeyError, TypeError, IndexError, AttributeError) as exc:
        result["blockers"] = [str(exc) if isinstance(exc, EvidenceError) else "MALFORMED_LEG:" + type(exc).__name__]
    return seal(result)


def _d3_original_safety_intent(partial: Mapping[str, Any], final: Mapping[str, Any]) -> None:
    """Only a pre-existing D3 joint intent may decide FINAL before partial fills.

    Both fill legs bind the same original decision and IDs. The final fill may
    use that book's remainder or wait for later executable depth; it may not
    relabel an ordinary post-partial BE/SMA10 decision as the D3 safety action.
    """
    witness = check_seal(partial.get("decision_intent"), "D3_ORIGINAL_INTENT")
    require(final.get("decision_intent") == witness, "D3_ORIGINAL_INTENT_PARITY")
    require(partial.get("reason") == "D3_PROFIT_PARTIAL_NEXT_OPEN"
            and final.get("reason") == "D3_SMA10_SAFETY_CLOSE_NEXT_OPEN", "D3_ORIGINAL_INTENT_REASON")
    require(all(partial.get(k) == final.get(k) for k in
                ("decision_ts", "decision_observed_ts", "due_open_ts", "decision_bar")), "D3_SAME_DECISION_REQUIRED")
    expected = {
        "kind": "D3_PARTIAL_WITH_SMA10_SAFETY", "strategy_digest": partial["strategy_digest"],
        "lot_id": partial["lot_id"], "campaign_id": partial["campaign_id"],
        "signal_sha": partial["signal_sha"], "partial_leg_id": partial["leg_id"],
        "final_leg_id": final["leg_id"], "decision_ts": partial["decision_ts"],
        "decision_observed_ts": partial["decision_observed_ts"], "due_open_ts": partial["due_open_ts"],
        "decision_bar_sha": partial["decision_bar"]["receipt_sha256"],
        "created_at_ms": partial["decision_observed_ts"],
        "partial_reason": partial["reason"], "final_reason": final["reason"],
    }
    require({k: v for k, v in witness.items() if k != "receipt_sha256"} == expected,
            "D3_ORIGINAL_INTENT_BINDING")


def _funding(value: Any, legs: Sequence[Mapping[str, Any]], *, symbol: str,
             start_ms: int, end_ms: int, as_of_ms: int) -> float:
    funding = check_seal(value, "FUNDING")
    calendar = source(funding.get("calendar"), "FUNDING_CALENDAR", as_of_ms=as_of_ms)
    require(calendar.get("source_kind") == "OFFICIAL_SETTLEMENT_CALENDAR"
            and calendar.get("symbol") == symbol, "FUNDING_CALENDAR_SOURCE")
    raw = calendar["raw"]
    require(raw["coverage_start_ms"] <= start_ms <= end_ms <= raw["coverage_end_ms"], "FUNDING_COVERAGE")
    times = raw["settlement_ts"]
    require(isinstance(times, list) and all(type(t) is int for t in times)
            and times == sorted(set(times)), "FUNDING_CALENDAR_DUPLICATE_OR_ORDER")
    expected = [t for t in times if start_ms < t <= end_ms]
    rows = funding.get("rows")
    require(isinstance(rows, list) and [r.get("ts_ms") for r in rows] == expected, "FUNDING_SETTLEMENT_COVERAGE")
    total = 0.0
    for row in rows:
        ts = row["ts_ms"]
        require(not any(l["observed_ts"] == ts for l in legs), "FUNDING_FILL_TIMESTAMP_AMBIGUOUS")
        qty = sum((1 if l["kind"] == "ENTRY" else -1) * l["base_qty"]
                  for l in legs if l["observed_ts"] < ts)
        same(row.get("qty_at_settlement"), qty, "FUNDING_QTY")
        rate_src = source(row.get("rate_source"), "FUNDING_RATE", as_of_ms=as_of_ms)
        mark_src = source(row.get("mark_source"), "FUNDING_MARK", as_of_ms=as_of_ms)
        require(rate_src.get("source_endpoint") == "/openApi/swap/v2/quote/fundingRate"
                and rate_src.get("symbol") == mark_src.get("symbol") == symbol, "FUNDING_SOURCE_PARITY")
        require(rate_src["raw"].get("fundingTime") == mark_src["raw"].get("time") == ts
                and ts <= rate_src["observed_ts"] and ts <= mark_src["observed_ts"], "FUNDING_SETTLEMENT_TIMESTAMP")
        rate = raw_number(rate_src["raw"].get("fundingRate"), "SIGNED_FUNDING_RATE")
        mark = raw_number(mark_src["raw"].get("markPrice"), "FUNDING_MARK", positive=True)
        same(row.get("signed_cash"), qty * mark * rate, "FUNDING_CASH")
        total += qty * mark * rate
    return total


def _path(value: Any, *, symbol: str, start_ms: int, end_ms: int,
          entry_mid: float, as_of_ms: int) -> dict[str, Any]:
    path = source(value, "PATH", as_of_ms=as_of_ms)
    require(path.get("symbol") == symbol and path.get("source_endpoint") == "/openApi/swap/v3/quote/klines"
            and path.get("interval_ms") == FIVE_MIN_MS, "PATH_SOURCE_PARITY")
    first = ((start_ms + FIVE_MIN_MS - 1) // FIVE_MIN_MS) * FIVE_MIN_MS
    expected = list(range(first, end_ms - FIVE_MIN_MS + 1, FIVE_MIN_MS))
    rows = path["raw"]
    require(expected and isinstance(rows, list), "PATH_NO_COMPLETE_BARS")
    require([r.get("open_ts") for r in rows] == expected, "PATH_CONTINUITY_OR_DUPLICATE")
    highs, lows = [], []
    for row in rows:
        require(row.get("close_ts") == row["open_ts"] + FIVE_MIN_MS
                and row["close_ts"] <= path["observed_ts"], "PATH_CAUSAL_COMPLETION")
        op, hi, lo, cl = [raw_number(row.get(k), "PATH_" + k.upper(), positive=True)
                          for k in ("open", "high", "low", "close")]
        require(lo <= min(op, cl) <= max(op, cl) <= hi, "PATH_OHLC")
        highs.append(hi); lows.append(lo)
    high_row, low_row = rows[highs.index(max(highs))], rows[lows.index(min(lows))]
    high_ts, low_ts = high_row["open_ts"], low_row["open_ts"]
    order = ("MFE_BAR_BEFORE_MAE_BAR" if high_ts < low_ts else
             "MAE_BAR_BEFORE_MFE_BAR" if low_ts < high_ts else "SAME_BAR_ORDER_UNKNOWN")
    last_close = rows[-1]["close_ts"]
    return {"MFE_bps": max(0.0, max(highs) / entry_mid - 1) * 10_000,
            "MAE_bps": max(0.0, 1 - min(lows) / entry_mid) * 10_000,
            "MFE_witness_bar_ms": [high_row["open_ts"], high_row["close_ts"]],
            "MAE_witness_bar_ms": [low_row["open_ts"], low_row["close_ts"]],
            "extrema_order": order, "within_bar_extrema_order_observed": False,
            "entry_partial_interval_excluded_ms": [start_ms, first] if first > start_ms else None,
            "exit_partial_interval_excluded_ms": [last_close, end_ms] if last_close < end_ms else None,
            "scope": "FULLY_OBSERVED_COMPLETE_5M_BARS_ONLY", "path_sha": path["receipt_sha256"]}


def campaign_evidence(campaign: Mapping[str, Any], legs: Sequence[Mapping[str, Any]],
                      funding: Any, path: Any, expected_identity: Mapping[str, Any], *,
                      boundary_ms: int, as_of_ms: int) -> dict[str, Any]:
    """Reconcile one independent root/reuse lot. CLOSED credit is at most one.

    OPEN/CENSORED requires a current mark depth and fee authority to reserve the
    remaining execution cost; it never fabricates a final exit or formal T.
    Symbol-wide normalized-cap validation belongs to the lifecycle dispatcher.
    """
    result = {"schema_version": "zel.squeeze_g5b.campaign_evidence.v1", "record_kind": "CAMPAIGN",
              "record_id": str(campaign.get("campaign_id", "")) + ":" + str(as_of_ms),
              "lot_id": campaign.get("lot_id"), "campaign_id": campaign.get("campaign_id"),
              "status": campaign.get("status"), "as_of_ms": as_of_ms,
              "boundary_ms": boundary_ms, "identity": dict(expected_identity),
              "inputs": copy.deepcopy({"campaign": campaign, "legs": legs, "funding": funding, "path": path}),
              "input_sha": stable_sha({"campaign": campaign, "legs": legs, "funding": funding, "path": path}),
              "production_grade": False, "formal_fresh_T": 0, "preboundary_formal_credit": 0,
              "historical_backfill": False, "blockers": [], "path_audit": None,
              "metrics": {k: None for k in NUMERIC_OUTPUTS}, **AUTH}
    try:
        identity(campaign, expected_identity)
        timestamp(as_of_ms, "AS_OF"); timestamp(boundary_ms, "BOUNDARY")
        require(campaign.get("status") in ("OPEN", "CENSORED", "CLOSED"), "CAMPAIGN_STATUS")
        require(campaign.get("side") == "long" and all(campaign.get(k) for k in
                    ("campaign_id", "lot_id", "root_lot_id", "symbol", "signal_sha")), "CAMPAIGN_IDENTITY")
        require(isinstance(legs, (list, tuple)) and legs, "LEGS_MISSING")
        require(len({l.get("leg_id") for l in legs}) == len(legs), "LEG_DUPLICATE")
        require([l.get("leg_sequence") for l in legs] == list(range(len(legs)))
                and [l["observed_ts"] for l in legs] == sorted(l["observed_ts"] for l in legs), "LEG_CHRONOLOGY")
        checks = [validate_leg(l, expected_identity, boundary_ms=boundary_ms, as_of_ms=as_of_ms) for l in legs]
        failures = [b for c in checks for b in c["blockers"]]
        require(not failures, "LEG_INVALID:" + ";".join(failures))
        require(all(all(l.get(k) == campaign.get(k) for k in
                        ("lot_id", "campaign_id", "symbol", "side", "signal_sha")) for l in legs), "CAMPAIGN_LEG_PARITY")
        consumed = {}
        for index, leg in enumerate(legs):
            depth_sha = leg["depth"]["receipt_sha256"]
            side_key = (depth_sha, leg["kind"] == "ENTRY")
            same(leg["depth_consumed_base_before"], consumed.get(side_key, 0.0), "DEPTH_BATCH_CONSUMPTION")
            if index and leg["observed_ts"] == legs[index - 1]["observed_ts"]:
                previous = legs[index - 1]
                require(previous["kind"] == "PARTIAL" and leg["kind"] == "FINAL_EXIT"
                        and previous["depth"]["receipt_sha256"] == depth_sha, "EQUAL_TIMESTAMP_BATCH_ORDER")
            consumed[side_key] = consumed.get(side_key, 0.0) + leg["base_qty"]
        kinds = [l["kind"] for l in legs]
        require(kinds[0] == "ENTRY" and kinds.count("ENTRY") == 1 and kinds.count("PARTIAL") <= 1
                and kinds.count("FINAL_EXIT") <= 1, "LEG_LIFECYCLE")
        partial = None
        for leg in legs[1:]:
            # Completed-close decisions precede an equal-clock fill. Without
            # separate event-order evidence an equal timestamp cannot own it.
            require(leg["decision_ts"] > legs[0]["observed_ts"], "EXIT_DECISION_BEFORE_OR_AT_ENTRY_FILL")
            if leg["kind"] == "PARTIAL":
                partial = leg
            elif leg["kind"] == "FINAL_EXIT" and partial is not None:
                if leg["decision_ts"] <= partial["observed_ts"]:
                    require(leg.get("reason") == "D3_SMA10_SAFETY_CLOSE_NEXT_OPEN",
                            "FINAL_DECISION_BEFORE_OR_AT_PARTIAL_FILL")
                    _d3_original_safety_intent(partial, leg)
        closed = campaign["status"] == "CLOSED"
        require((closed and kinds[-1] == "FINAL_EXIT") or (not closed and "FINAL_EXIT" not in kinds), "CLOSED_FINAL_EXIT_PARITY")
        initial = number(campaign.get("initial_base_qty"), "INITIAL_QTY", positive=True)
        normalized = number(campaign.get("initial_normalized_qty"), "INITIAL_NORMALIZED", positive=True)
        same(legs[0]["base_qty"], initial, "ENTRY_QTY")
        same(legs[0]["normalized_qty"], normalized, "ENTRY_NORMALIZED")
        remaining, remaining_n = 0.0, 0.0
        for l in legs:
            same(l.get("remaining_qty_before"), remaining, "REMAINING_BEFORE")
            same(l.get("remaining_normalized_before"), remaining_n, "NORMALIZED_BEFORE")
            if l["kind"] == "PARTIAL":
                same(l["base_qty"], initial / 3, "PARTIAL_ONE_THIRD")
            change = 1 if l["kind"] == "ENTRY" else -1
            remaining += change * l["base_qty"]
            remaining_n += change * l["normalized_qty"]
            same(l["normalized_qty"], l["base_qty"] / initial * normalized, "LOT_SCALE")
            require(remaining >= -1e-10 and -1e-10 <= remaining_n <= 1 + 1e-10, "LOT_CAP_OR_OVERCLOSE")
            same(l.get("remaining_qty_after"), remaining, "REMAINING_AFTER")
            same(l.get("remaining_normalized_after"), remaining_n, "NORMALIZED_AFTER")
        require((closed and abs(remaining) <= 1e-10) or (not closed and remaining > 0), "CLOSED_QUANTITY_PARITY")
        require((closed and campaign.get("final_exit_ts") == legs[-1]["observed_ts"])
                or (not closed and campaign.get("final_exit_ts") is None), "FINAL_EXIT_TIMESTAMP")
        same(campaign.get("remaining_base_qty"), remaining, "CAMPAIGN_REMAINING")
        start = legs[0]["observed_ts"]
        end = legs[-1]["observed_ts"] if closed else as_of_ms
        funding_cash = _funding(funding, legs, symbol=campaign["symbol"], start_ms=start, end_ms=end, as_of_ms=as_of_ms)
        path_audit = _path(path, symbol=campaign["symbol"], start_ms=start, end_ms=end,
                           entry_mid=checks[0]["derived"]["mid"], as_of_ms=as_of_ms)
        derived = [c["derived"] for c in checks]
        fees = sum(d["fee_cash"] for d in derived)
        slips = sum(d["slippage_cash"] for d in derived)
        gross = sum(d["mid_cash"] for d in derived)
        exec_cash = sum(d["execution_cash"] for d in derived)
        mark_cash, remaining_cost = 0.0, 0.0
        if not closed:
            mark = _depth(campaign.get("mark_depth"), symbol=campaign["symbol"], qty=remaining,
                          buy=False, due_ts=legs[-1]["observed_ts"], as_of_ms=as_of_ms)
            require(mark["observed_ts"] == as_of_ms, "MARK_NOT_CURRENT")
            mark_cash = remaining * mark["mid"]
            remaining_cost = mark["slippage_cash"] + _fee(campaign.get("mark_fee_authority"),
                                  observed_ts=as_of_ms, notional=remaining * mark["vwap"],
                                  expected_sha=expected_identity["fee_authority_sha"])
        net = exec_cash + mark_cash - fees - funding_cash - remaining_cost
        same(net, gross + mark_cash - slips - fees - funding_cash - remaining_cost, "CASH_BRIDGE")
        partial_cash = sum(d["execution_cash"] - d["fee_cash"] for l, d in zip(legs, derived) if l["kind"] == "PARTIAL")
        if "claimed_net_cash" in campaign:
            same(campaign["claimed_net_cash"], net, "CLAIMED_NET")
        result.update(production_grade=True, formal_fresh_T=int(closed),
                      metrics={"gross_mid_cash": gross + mark_cash, "slippage_cash": slips,
                               "fee_cash": fees, "funding_cash": funding_cash, "net_cash": net,
                               "realized_partial_cash": partial_cash, "remaining_mark_cash": mark_cash,
                               "remaining_exit_cost_cash": remaining_cost,
                               "MFE_bps": path_audit["MFE_bps"], "MAE_bps": path_audit["MAE_bps"]},
                      path_audit=path_audit, leg_receipts=[c["receipt_sha256"] for c in checks])
    except (EvidenceError, KeyError, TypeError, IndexError, AttributeError) as exc:
        result["blockers"] = [str(exc) if isinstance(exc, EvidenceError) else "MALFORMED_CAMPAIGN:" + type(exc).__name__]
    return seal(result)


class EvidenceLedger:
    """One hash-chained writer with process lock, fsync, and ID conflict checks.

    append returns APPENDED or NOOP. A second credited CLOSED receipt conflicts;
    earlier blocked receipts remain immutable when genuine components arrive.
    The caller must still use the existing workflow concurrency owner.
    """
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @staticmethod
    def _signal_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
        campaign = record["inputs"]["campaign"]
        return tuple(campaign[k] for k in ("lane_id", "cohort_id", "symbol", "signal_sha"))

    @staticmethod
    def _validate_record(record: Mapping[str, Any]) -> None:
        check_seal(record, "RECORD")
        kwargs = {k: record.get(k) for k in ("boundary_ms", "as_of_ms")}
        if record.get("record_kind") == "LEG":
            expected = validate_leg(record["inputs"], record["identity"], **kwargs)
        elif record.get("record_kind") == "CAMPAIGN":
            args = record["inputs"]
            expected = campaign_evidence(args["campaign"], args["legs"], args["funding"],
                                         args["path"], record["identity"], **kwargs)
        else:
            raise EvidenceError("RECORD_KIND")
        require(expected == record, "RECORD_RECOMPUTATION_PARITY")

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows, previous, ids, closed, credited_signals = [], None, set(), set(), set()
        for line in self.path.read_text().splitlines():
            require(bool(line.strip()), "LEDGER_EMPTY_LINE")
            event = json.loads(line)
            check_seal(event, "LEDGER_EVENT")
            require(event.get("seq") == len(rows) and event.get("previous_sha") == previous, "LEDGER_CHAIN")
            payload = check_seal(event.get("payload"), "LEDGER_PAYLOAD")
            self._validate_record(payload)
            key = (payload.get("record_kind"), payload.get("record_id"))
            require(key not in ids and all(key), "LEDGER_DUPLICATE_ID")
            ids.add(key)
            if payload.get("record_kind") == "CAMPAIGN" and payload.get("formal_fresh_T") == 1:
                close_key = (payload.get("lot_id"), payload.get("campaign_id"))
                require(close_key not in closed, "LEDGER_DUPLICATE_CLOSE")
                closed.add(close_key)
                signal_key = self._signal_key(payload)
                require(signal_key not in credited_signals, "LEDGER_DUPLICATE_SIGNAL_CREDIT")
                credited_signals.add(signal_key)
            previous = event["receipt_sha256"]
            rows.append(event)
        return rows

    def append(self, record: Mapping[str, Any]) -> str:
        self._validate_record(record)
        require(record.get("record_kind") in ("LEG", "CAMPAIGN") and record.get("record_id"), "RECORD_ID")
        require(record.get("formal_fresh_T") in (0, 1) and all(record.get(k) == v for k, v in AUTH.items()), "RECORD_AUTHORITY")
        if record.get("formal_fresh_T") == 1:
            require(record.get("record_kind") == "CAMPAIGN" and record.get("status") == "CLOSED"
                    and record.get("production_grade") is True and record.get("blockers") == [], "RECORD_FORMAL_CREDIT")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + ".lock").open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            rows = self.records()
            for event in rows:
                old = event["payload"]
                if (old["record_kind"], old["record_id"]) == (record["record_kind"], record["record_id"]):
                    require(old["receipt_sha256"] == record["receipt_sha256"], "LEDGER_ID_CONFLICT")
                    return "NOOP"
                if old.get("record_kind") == record["record_kind"] == "CAMPAIGN" and old.get("formal_fresh_T") == record.get("formal_fresh_T") == 1:
                    require((old.get("lot_id"), old.get("campaign_id")) != (record.get("lot_id"), record.get("campaign_id")), "LEDGER_CLOSE_CONFLICT")
                    require(self._signal_key(old) != self._signal_key(record), "LEDGER_SIGNAL_CREDIT_CONFLICT")
            event = seal({"seq": len(rows), "previous_sha": rows[-1]["receipt_sha256"] if rows else None,
                          "payload": dict(record)})
            with self.path.open("a") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
                handle.flush(); os.fsync(handle.fileno())
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return "APPENDED"
