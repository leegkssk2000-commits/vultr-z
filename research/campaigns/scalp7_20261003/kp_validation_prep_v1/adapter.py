"""K.P-only preparation bridge. Supplied synthetic inputs; no collector or runner.

The R, funding-boundary and ledger definitions below are proposed protocol
choices, not an approved economic execution profile. ObservedPaper is reused
without changing its frozen strategy or quote-clock decisions. No API in this
module fetches a quote, opens market history, reserves FULL credit or places an
order. Synthetic state never receives genuine-fresh or terminal credit.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.research.rebuild import scalp7_observed_paper_v3 as paper
from backend.research.rebuild import scalp7_positive_lanes_v2 as parent
from backend.research.rebuild.economic7_canonical_history_v1 import atomic_json
from backend.research.rebuild.scalp7_source_data_v2 import SYMBOLS

CANDIDATE = "scalp7_keltner_hg_parent_utc30m_v2"
PARENT_IDENTITY = "389550fddc888266eaf336cdec83a63b05f0e5da198fe21d07a2cf171e4f5710"
PARENT_MODULE_SHA = "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2"
TF_MS = 30 * 60_000
NAMESPACE = "kp30_validation_prep_v1"
STATE_SCHEMA = "kp30.synthetic_preparation_checkpoint.v1"
SEMANTICS = "PROPOSED_NOT_APPROVED_FOR_ECONOMIC_EXECUTION"


class PrepError(RuntimeError):
    pass


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise PrepError("INVALID_NUMBER:" + label)
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise PrepError("INVALID_NUMBER:" + label) from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise PrepError("INVALID_NUMBER:" + label)
    return value


def _time(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise PrepError("INVALID_TIME:" + label)
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PrepError("MISSING_HASH:" + label)
    try:
        int(value, 16)
    except ValueError as exc:
        raise PrepError("INVALID_HASH:" + label) from exc
    return value


def build_candidate_config(
    output_root: Path,
    *,
    t0_ms: int,
    window_end_ms: int,
    runtime_identity: str,
    reference_costs_bps: Mapping[str, float],
) -> dict[str, Any]:
    """Isolate a preparation output, never repoint a shared paper configuration."""
    root = Path(output_root).resolve()
    if root.name != NAMESPACE:
        raise PrepError("KP_ONLY_OUTPUT_NAMESPACE_REQUIRED")
    t0, end = _time(t0_ms, "t0"), _time(window_end_ms, "window_end")
    if t0 % TF_MS or end % TF_MS or end <= t0:
        raise PrepError("UTC30M_WINDOW_BOUNDARIES_REQUIRED")
    if not runtime_identity.startswith("KP30_PREP_SYNTHETIC_"):
        raise PrepError("SYNTHETIC_RUNTIME_IDENTITY_REQUIRED")
    costs = {symbol: _number(cost, "reference_cost", positive=True)
             for symbol, cost in reference_costs_bps.items()}
    if not costs or any(symbol not in SYMBOLS for symbol in costs):
        raise PrepError("KP_SYMBOL_CONFIGURATION_REQUIRED")
    module_sha = hashlib.sha256(Path(parent.__file__).read_bytes()).hexdigest()
    if module_sha != PARENT_MODULE_SHA:
        raise PrepError("FROZEN_PARENT_MODULE_DRIFT")
    return {
        "schema": "kp30.synthetic_preparation_config.v1",
        "candidate": CANDIDATE,
        "parent_identity": PARENT_IDENTITY,
        "parent_module_sha256": module_sha,
        "runtime_identity": runtime_identity,
        "output_root": str(root),
        "input_kind": "SYNTHETIC_ONLY",
        "fresh_start_ms": t0,
        "window_end_ms": end,
        "max_quote_request_ms": 5000,
        "max_pair_skew_ms": 5000,
        "max_quote_gap_ms": 90000,
        "reference_costs_bps": costs,
        "semantics_status": SEMANTICS,
        "execution_authority": "NONE",
        "market_collection_authority": "NONE",
        "new_full_credit": 0,
        "g5a_shortlist": False,
        "g5b_terminal": False,
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }


def inspect_source_index(
    item: Mapping[str, Any], seen: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Metadata-only classification before any uninspected body is opened.

    NOT_PREVIOUSLY_INSPECTED_METADATA is not a genuine-fresh certificate.
    A complete usage inventory and later actual receipt proof remain required.
    """
    reasons: list[str] = []
    required = ("body_sha256", "received_at_ms", "start_ms", "end_exclusive_ms",
                "usage_inventory_sha256", "usage_inventory_complete", "source_id")
    for key in required:
        if item.get(key) is None:
            reasons.append("MISSING_METADATA:" + key)
    if reasons:
        return {"state": "BLOCKED_BEFORE_BODY_READ", "reasons": reasons,
                "body_opened": False, "genuine_fresh": False}
    body = _sha(item["body_sha256"], "source_body")
    _sha(item["usage_inventory_sha256"], "usage_inventory")
    _time(item["received_at_ms"], "received_at")
    start, end = _time(item["start_ms"], "source_start"), _time(item["end_exclusive_ms"], "source_end")
    if end <= start:
        raise PrepError("SOURCE_INTERVAL_INVALID")
    if item["usage_inventory_complete"] is not True:
        reasons.append("USAGE_INVENTORY_INCOMPLETE")
    for old in seen:
        if body == old.get("body_sha256") or (
            old.get("source_id") in ("*", item["source_id"])
            and start < _time(old["end_exclusive_ms"], "seen_end")
            and end > _time(old["start_ms"], "seen_start")
        ):
            reasons.append("SEEN_BODY_OR_INTERVAL")
    return {
        "state": "BLOCKED_BEFORE_BODY_READ" if reasons else "NOT_PREVIOUSLY_INSPECTED_METADATA",
        "reasons": sorted(set(reasons)), "body_opened": False,
        "genuine_fresh": False, "metadata_sha256": paper.digest(dict(item)),
    }


def validate_signal_clock(wrapper: Mapping[str, Any], now_ms: int) -> dict[str, int]:
    signal = wrapper["signal"]
    if signal.get("identity") != CANDIDATE or signal.get("timeframe_min") != 30:
        raise PrepError("KP_EXACT_CANDIDATE_REQUIRED")
    if (signal.get("take_profit_r") is not None or signal.get("lane") != "keltner_holygrail"
            or signal.get("symbol") not in SYMBOLS or signal.get("side") not in (-1, 1)):
        raise PrepError("FROZEN_PARENT_SIGNAL_FIELDS_REQUIRED")
    if signal.get("partial_take_profit_r") != 2.0 or signal.get("partial_fraction") != 0.10:
        raise PrepError("FROZEN_PARENT_PARTIAL_REQUIRED")
    if signal.get("max_hold_bars") != 25 or signal.get("exit_policy") != "KELTNER_HG_FEE_BE_PARTIAL_RUNNER":
        raise PrepError("FROZEN_PARENT_LIFECYCLE_REQUIRED")
    meta = signal["meta"]
    if meta.get("spec_sha256") != parent.SPEC_SHA256 or meta.get("regime") not in parent.SPEC["keltner"]["regimes"]:
        raise PrepError("FROZEN_PARENT_SPEC_REQUIRED")
    if meta.get("be_arm_r") != 1.0 or meta.get("fallback_stop_atr_mult") != 1.2 or meta["entry_cost_gate"].get("min_ratio") != 4.5:
        raise PrepError("FROZEN_PARENT_GEOMETRY_REQUIRED")
    opened = _time(signal["signal_open_ts_ms"], "signal_open")
    close = _time(wrapper["decision_bar_close_ms"], "decision_close")
    available = _time(wrapper["bar_available_ts_ms"], "bar_available")
    signal_ms = _time(signal["signal_ts_ms"], "signal")
    observed = _time(wrapper["observed_at_ms"], "decision_processing")
    now = _time(now_ms, "processing")
    if opened % TF_MS or close != opened + TF_MS:
        raise PrepError("UTC30M_COMPLETE_BAR_REQUIRED")
    if not close <= available <= signal_ms <= observed <= now:
        raise PrepError("SIGNAL_BEFORE_COMPLETE_BAR_OR_AVAILABILITY")
    if meta.get("feature_available_ts_ms") != signal_ms:
        raise PrepError("FROZEN_FEATURE_AVAILABILITY_BINDING_REQUIRED")
    _sha(wrapper["record_sha256"], "signal_receipt")
    _sha(wrapper["source_bar_sha256"], "source_bar")
    return {"bar_close_ms": close, "bar_available_ms": available,
            "signal_ms": signal_ms, "decision_processed_ms": observed}


def proposed_initial_r(signal: Mapping[str, Any], entry_price: float) -> dict[str, Any]:
    """Reuse parent entry gate/fallback; subsequent BE/trailing never changes R."""
    if signal.get("identity") != CANDIDATE:
        raise PrepError("KP_EXACT_CANDIDATE_REQUIRED")
    entry = _number(entry_price, "entry", positive=True)
    admission = parent.entry_admission(signal, entry)
    if not admission["allowed"]:
        raise PrepError("PARENT_ENTRY_REJECT:" + admission["reason"])
    risk = int(signal["side"]) * (entry - float(admission["stop_price"]))
    risk = _number(risk, "effective_initial_price_risk", positive=True)
    return {"semantics_status": SEMANTICS, "effective_initial_stop": admission["stop_price"],
            "initial_price_risk": risk, "initial_risk_bps": risk / entry * 10000,
            "changes_with_be_or_trailing": False, "economic_execution_allowed": False}


def prepared_preflight(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Classify supplied read-only receipts; never opens an indexed payload.

    This bridge is permanently nonexecuting. A fully bound future protocol still
    needs a separately reviewed market-capable runner before execution readiness.
    Synthetic PASS is only a technical test result, not source/fresh evidence.
    """
    blockers: list[dict[str, str]] = []
    checks = {
        "normal_current_candidate_census": "Recover current ledger, lock, process and saved-result receipts through an authorized read-only path.",
        "usage_inventory_complete": "Bind full metadata-only seen inventory including later observations before opening uninspected input.",
        "source_receipt_clock_hash_bound": "Preserve source body, native/receipt/usable/processing clock and immutable receipt hashes.",
        "protocol_approved": "Approve the exact proposed G5A OOS then G5B protocol before market execution.",
        "g5a_shortlist_receipt_bound": "Complete separately approved purged unseen G5A OOS and bind shortlist receipt before G5B activation.",
        "windows_and_purge_embargo_bound": "Bind exact UTC windows, source dependencies, boundary ownership and proposed embargo.",
        "frozen_parent_and_runtime_pins_match": "Verify parent, runtime, input, cost, protocol and window pins before reservation.",
        "exact_identity_execution_approval_bound": "Bind separately authorized exact runtime identity, cumulative FULL count and single owner.",
        "no_active_same_identity_writer": "Recover and reconcile current reservations, locks and processes before starting.",
        "quantity_lineage_bound": "Bind original quantity/notional and each partial/exit remaining quantity to receipt evidence.",
        "pit_cost_decomposition_bound": "Bind PIT fee and embedded-versus-additional spread/slippage sources without double debit.",
        "signed_funding_interval_complete": "Bind signed settlements and complete interval receipts; absent funding remains null.",
        "intrabar_order_provenance_bound": "Preserve required observed event order; sparse bid/ask does not certify full intrabar paths.",
        "terminal_and_independence_contract_bound": "Approve applicable terminal units, retention denominator and effective-N definition/cutoffs.",
    }
    for name, action in checks.items():
        if facts.get(name) is not True:
            blockers.append({"code": name.upper(), "required_action": action})
    if facts.get("evidence_kind") != "REAL_SOURCE_RECEIPTS":
        blockers.append({"code": "SYNTHETIC_IS_NOT_REAL_SOURCE_EVIDENCE", "required_action": "Keep synthetic proofs separate from actual authorized source receipts."})
    blockers.append({"code": "PREPARATION_BRIDGE_HAS_NO_MARKET_RUNNER", "required_action": "Separately review and authorize K.P-only production wiring; no market execution API is supplied here."})
    return {"state": "EXECUTION_BLOCKED", "execution_ready": False,
            "synthetic_integration_reported_pass": facts.get("synthetic_integration_pass") is True,
            "candidate": CANDIDATE, "semantics_status": SEMANTICS, "blockers": blockers,
            "new_full_authorized_here": 0, "g5b_activated_here": False,
            "index_payload_opened": False}


def _receipt(quote: Mapping[str, Any], processed: int) -> dict[str, Any]:
    usable = paper._usable(quote)
    if usable > processed:
        raise PrepError("PROCESSING_BEFORE_USABLE_QUOTE")
    return {"request_ms": _time(quote["requested_at_ms"], "quote_request"),
            "received_ms": _time(quote["received_at_ms"], "quote_receipt"),
            "source_ms": quote.get("source_ts_ms"), "usable_ms": usable,
            "processed_ms": processed, "body_sha256": _sha(quote.get("body_sha256"), "quote_body"),
            "receipt_sha256": _sha(quote.get("receipt_sha256"), "quote_receipt"),
            "clock_proof_sha256": paper.digest(quote["clock_proof"]),
            "actual_exchange_fill": False}


def link_cashflows(
    row: Mapping[str, Any],
    *,
    original_qty: float | None,
    quantity_lineage: Mapping[str, Any] | None = None,
    pit_costs: Mapping[str, Mapping[str, Any]],
    funding: Sequence[Mapping[str, Any]] | None,
    funding_coverage: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Append-only proposed reporting projection, never substitutes source fills.

    Gross already crosses observed bid/ask. Spread is attribution, not another
    debit. PIT net excludes the frozen reference reserve so actual signed funding
    does not silently accumulate with the old absolute-rate reserve. Settlement
    exposure is (entry, exit], before a simultaneous partial/final close.
    Missing cost/funding/quantity evidence stays null with explicit blockers.
    """
    signal, symbol = row["signal"], row["signal"]["symbol"]
    entry = _number(row["entry_prices"][symbol], "entry", positive=True)
    side = int(signal["side"])
    risk = proposed_initial_r(signal, entry)
    entry_ms = _time(row["entry_ts_ms"], "entry")
    terminal = "exit_ts_ms" in row
    end_ms = _time(row["exit_ts_ms"], "exit") if terminal else None
    blockers: list[str] = []
    qty = None if original_qty is None else _number(original_qty, "original_qty", positive=True)
    if qty is None:
        blockers.append("ORIGINAL_QUANTITY_LINEAGE_MISSING")
    elif quantity_lineage is None:
        blockers.append("ORIGINAL_QUANTITY_SOURCE_RECEIPT_MISSING")
    else:
        _sha(quantity_lineage.get("body_sha256"), "original_quantity")
        if (_time(quantity_lineage["known_at_ms"], "quantity_known_at") > entry_ms
                or quantity_lineage.get("original_qty") != qty
                or quantity_lineage.get("kind") not in ("PAPER_ORIGINAL_QUANTITY_MODEL", "ACCOUNT_SOURCE_QUANTITY")):
            raise PrepError("ORIGINAL_QUANTITY_SOURCE_BINDING")
    original_notional = None if qty is None else qty * entry
    remaining, realized, events = 1.0, 0.0, []
    inputs = [{"kind": "ENTRY", "stamp": entry_ms, "fraction": 1.0,
               "price": entry, "quotes": row["entry_quote_receipts"], "trigger": None}]
    previous = entry_ms
    for part in row.get("partials", []):
        stamp = _time(part["filled_at_ms"], "partial")
        if stamp < previous or (end_ms is not None and stamp > end_ms):
            raise PrepError("PARTIAL_EVENT_ORDER")
        fraction = _number(part["fraction"], "partial_fraction", positive=True)
        if len(inputs) != 1 or not math.isclose(fraction, 0.10, abs_tol=1e-12):
            raise PrepError("FROZEN_PARTIAL_ONCE_OR_ORIGINAL_FRACTION")
        inputs.append({"kind": "PARTIAL", "stamp": stamp, "fraction": fraction,
                       "price": _number(part["prices"][symbol], "partial_price", positive=True),
                       "quotes": part["quote_receipts"], "trigger": part["trigger"]})
        previous = stamp
    if terminal:
        if end_ms is None or end_ms < previous:
            raise PrepError("EXIT_EVENT_ORDER")
        inputs.append({"kind": "EXIT", "stamp": end_ms, "fraction": 1.0 - sum(x["fraction"] for x in inputs[1:]),
                       "price": _number(row["exit_prices"][symbol], "exit_price", positive=True),
                       "quotes": row["exit_quote_receipts"], "trigger": row["trigger"]})
    fee_total = slippage_total = 0.0
    cost_complete = True
    for event in inputs:
        kind, stamp, fraction, price = event["kind"], event["stamp"], event["fraction"], event["price"]
        receipt = _receipt(event["quotes"][symbol], stamp)
        expected_price = paper.ObservedPaper._prices(signal, event["quotes"], kind == "ENTRY")[symbol]
        if not math.isclose(price, expected_price, rel_tol=0, abs_tol=1e-12):
            raise PrepError("EVENT_PRICE_OBSERVED_QUOTE_MISMATCH")
        trigger = event["trigger"]
        if trigger is not None and not _time(trigger["decision_ms"], "trigger") < receipt["request_ms"]:
            raise PrepError("ACTION_QUOTE_REQUEST_NOT_AFTER_TRIGGER")
        gross = 0.0 if kind == "ENTRY" else fraction * side * (price / entry - 1) * 10000
        if kind != "ENTRY":
            remaining -= fraction
            realized += gross
        cost = pit_costs.get(kind)
        fee = spread = slippage = None
        if cost is None or any(cost.get(k) is None for k in ("fee_bps", "spread_bps", "slippage_bps", "known_at_ms", "body_sha256")):
            blockers.append("PIT_COST_LINEAGE_MISSING:" + kind)
            cost_complete = False
        else:
            if cost.get("symbol") != symbol:
                raise PrepError("PIT_COST_SYMBOL_MISMATCH")
            if (cost.get("spread_semantics") != "EMBEDDED_IN_OBSERVED_BID_ASK"
                    or cost.get("slippage_semantics") not in (
                        "ADDITIONAL_MODEL_DEBIT_NOT_EMBEDDED_IN_QUOTED_PRICE", "EMBEDDED_IN_OBSERVED_PRICE")):
                raise PrepError("AMBIGUOUS_EMBEDDED_OR_ADDITIONAL_COST")
            if _time(cost["known_at_ms"], "cost_known_at") > stamp:
                raise PrepError("FUTURE_COST_INFORMATION")
            _sha(cost["body_sha256"], "pit_cost")
            values = [_number(cost[k], k) for k in ("fee_bps", "spread_bps", "slippage_bps")]
            if any(value < 0 for value in values):
                raise PrepError("NEGATIVE_COST_COMPONENT")
            fee, spread, slippage = [fraction * price / entry * value for value in values]
            fee_total += fee
            if cost["slippage_semantics"] == "ADDITIONAL_MODEL_DEBIT_NOT_EMBEDDED_IN_QUOTED_PRICE":
                slippage_total += slippage
        events.append({"kind": kind, "processed_ms": stamp, "trigger": copy.deepcopy(trigger),
                       "quote": receipt, "price": price, "original_fraction": fraction,
                       "original_qty": qty, "event_qty": None if qty is None else qty * fraction,
                       "remaining_qty": None if qty is None else qty * remaining,
                       "original_notional": original_notional,
                       "event_notional": None if qty is None else qty * fraction * price,
                       "gross_original_notional_bps": gross, "fee_bps": fee,
                       "spread_attribution_bps_in_observed_gross": spread, "slippage_bps": slippage,
                       "pit_cost_source": copy.deepcopy(cost), "source_fill_kind": "OBSERVED_QUOTE_PAPER_NOT_EXCHANGE_FILL"})
    settlements: list[dict[str, Any]] = []
    funding_total: float | None = None
    if funding is None or funding_coverage is None or end_ms is None:
        blockers.append("SIGNED_FUNDING_COMPLETE_INTERVAL_MISSING")
    else:
        if (funding_coverage.get("complete") is not True
                or funding_coverage.get("start_ms") != entry_ms
                or funding_coverage.get("end_ms") != end_ms):
            blockers.append("SIGNED_FUNDING_COVERAGE_MISMATCH")
        else:
            _sha(funding_coverage.get("body_sha256"), "funding_coverage")
            funding_total, seen = 0.0, set()
            for settlement in funding:
                if settlement.get("symbol") != symbol:
                    raise PrepError("FUNDING_SYMBOL_MISMATCH")
                stamp = _time(settlement["settlement_ms"], "funding_settlement")
                if _time(settlement["received_at_ms"], "funding_receipt") < stamp:
                    raise PrepError("FUNDING_RECEIPT_BEFORE_SETTLEMENT")
                if not entry_ms < stamp <= end_ms:
                    raise PrepError("FUNDING_OUTSIDE_PROPOSED_INTERVAL")
                source_sha = _sha(settlement.get("body_sha256"), "funding_settlement")
                if stamp in seen:
                    raise PrepError("DUPLICATE_FUNDING_SETTLEMENT")
                seen.add(stamp)
                signed_rate = _number(settlement["signed_rate"], "signed_funding_rate")
                mark = _number(settlement["mark_price"], "settlement_mark", positive=True)
                exposed = 1.0 - sum(x["fraction"] for x in inputs if x["kind"] == "PARTIAL" and x["stamp"] < stamp)
                debit_bps = side * signed_rate * exposed * mark / entry * 10000
                funding_total += debit_bps
                settlements.append({"settlement_ms": stamp, "signed_rate": signed_rate,
                                    "remaining_original_fraction": exposed,
                                    "remaining_qty": None if qty is None else qty * exposed,
                                    "settlement_notional": None if qty is None else qty * exposed * mark,
                                    "signed_debit_original_notional_bps": debit_bps,
                                    "body_sha256": source_sha, "source_receipt": copy.deepcopy(settlement)})
    net = realized - fee_total - slippage_total - funding_total if terminal and cost_complete and funding_total is not None else None
    return {"schema": "kp30.proposed_cashflow_lineage.v1", "semantics_status": SEMANTICS,
            "candidate": CANDIDATE, "source_trade_key": row["key"],
            "source_row_sha256": paper.digest(dict(row)), "initial_r": risk,
            "cashflows": events, "funding_settlements": settlements,
            "quantity_lineage": copy.deepcopy(quantity_lineage),
            "remaining_original_fraction": remaining, "closed": terminal,
            "gross_original_notional_bps": realized, "fee_bps": fee_total if cost_complete else None,
            "slippage_bps": slippage_total if cost_complete else None, "signed_funding_debit_bps": funding_total,
            "net_original_notional_bps": net,
            "net_pnl_r": None if net is None else net / risk["initial_risk_bps"],
            "fee_r": None if not cost_complete else fee_total / risk["initial_risk_bps"],
            "slippage_r": None if not cost_complete else slippage_total / risk["initial_risk_bps"],
            "funding_r": None if funding_total is None else funding_total / risk["initial_risk_bps"],
            "reference_reserve_bps_reported_separately": row.get("cost_bps"),
            "reference_reserve_subtracted_in_pit_net": False,
            "spread_subtracted_twice": False, "blockers": sorted(set(blockers)),
            "terminal_eligible": False, "account_nav_or_dd_certified": False}


class PrepCheckpoint:
    """One isolated synthetic writer, hash-bound state and preserved attempts.

    Recovery is explicit. INTERRUPTED/FAILED never becomes NOT_RUN and does not
    create an attempt or reset consumed credit. This is not an execution ledger.
    """

    def __init__(self, config: Mapping[str, Any], *, recover: bool = False):
        self.config = copy.deepcopy(dict(config))
        self.out = Path(config["output_root"]).resolve()
        if (self.out.name != NAMESPACE or config.get("input_kind") != "SYNTHETIC_ONLY"
                or config.get("execution_authority") != "NONE" or config.get("candidate") != CANDIDATE
                or config.get("parent_identity") != PARENT_IDENTITY
                or config.get("parent_module_sha256") != PARENT_MODULE_SHA
                or not str(config.get("runtime_identity", "")).startswith("KP30_PREP_SYNTHETIC_")
                or config.get("market_collection_authority") != "NONE"
                or config.get("new_full_credit") != 0 or config.get("g5a_shortlist") is not False
                or config.get("g5b_terminal") is not False or config.get("order_authority") != "BLOCKED"
                or config.get("live_authority") != "BLOCKED" or config.get("semantics_status") != SEMANTICS
                or any(config.get(name) != expected for name, expected in (
                    ("max_quote_request_ms", 5000), ("max_pair_skew_ms", 5000), ("max_quote_gap_ms", 90000)))):
            raise PrepError("SYNTHETIC_ISOLATED_CONFIGURATION_REQUIRED")
        start = _time(config.get("fresh_start_ms"), "config_start")
        end = _time(config.get("window_end_ms"), "config_end")
        if start % TF_MS or end % TF_MS or end <= start:
            raise PrepError("UTC30M_WINDOW_BOUNDARIES_REQUIRED")
        if (not config.get("reference_costs_bps")
                or any(symbol not in SYMBOLS for symbol in config["reference_costs_bps"])):
            raise PrepError("KP_SYMBOL_CONFIGURATION_REQUIRED")
        for value in config["reference_costs_bps"].values():
            _number(value, "reference_cost", positive=True)
        if hashlib.sha256(Path(parent.__file__).read_bytes()).hexdigest() != PARENT_MODULE_SHA:
            raise PrepError("FROZEN_PARENT_MODULE_DRIFT")
        self.out.mkdir(parents=True, exist_ok=True)
        self.lock = (self.out / "writer.lock").open("a+b")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise PrepError("KP_SINGLE_WRITER_LOCK_CONFLICT") from exc
        try:
            path = self.out / "STATE.json"
            if path.exists():
                state = json.loads(path.read_bytes())
                saved_hash = state.pop("state_sha256", None)
                if saved_hash != paper.digest(state) or state.get("schema") != STATE_SCHEMA or state.get("config_sha256") != paper.digest(self.config):
                    raise PrepError("CHECKPOINT_HASH_OR_CONFIGURATION_DRIFT")
                if state["attempt_status"] in ("STARTED", "INTERRUPTED", "FAILED"):
                    if not recover:
                        raise PrepError("EXPLICIT_RECOVERY_REQUIRED_NO_AUTOMATIC_RETRY")
                    state["history"].append({"kind": "EXPLICIT_RECOVERY", "prior_status": state["attempt_status"]})
                    state["attempt_status"] = "STARTED"
                self.state = state
            else:
                if recover:
                    raise PrepError("RECOVERY_CHECKPOINT_MISSING")
                self.state = {"schema": STATE_SCHEMA, "config_sha256": paper.digest(self.config),
                              "attempt_status": "STARTED", "attempt_count": 1, "consumed_full_credit": 0,
                              "paper_state": paper.empty_state(paper.digest(self.config)),
                              "processed_events": {}, "signal_bindings": {}, "history": [{"kind": "PREPARATION_STARTED"}],
                              "observations": []}
            self.save()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> PrepCheckpoint:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if exc_type is not None:
                try:
                    self.interrupt(str(exc), failed=not issubclass(exc_type, KeyboardInterrupt))
                except BaseException as save_error:
                    # The body exception remains primary even if its failure
                    # receipt cannot be persisted. Returning leaves its object
                    # and traceback intact; the note exposes the second error.
                    exc.add_note(f"CHECKPOINT_INTERRUPT_SAVE_FAILED: {type(save_error).__name__}: {save_error}")
        finally:
            try:
                self.close()
            except BaseException as close_error:
                if exc is None:
                    raise
                exc.add_note(f"CHECKPOINT_CLOSE_FAILED: {type(close_error).__name__}: {close_error}")

    def save(self) -> None:
        payload = copy.deepcopy(self.state)
        payload["state_sha256"] = paper.digest(payload)
        atomic_json(self.out / "STATE.json", payload)

    def close(self) -> None:
        if not self.lock.closed:
            try:
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
            finally:
                self.lock.close()

    def interrupt(self, reason: str, *, failed: bool = False) -> None:
        self.state["attempt_status"] = "FAILED" if failed else "INTERRUPTED"
        self.state["history"].append({"kind": self.state["attempt_status"], "reason": reason})
        self.save()

    def apply_synthetic(
        self, event_id: str, *, now_ms: int, quotes: Mapping[str, Any], frames: Mapping[int, Any],
        wrapper: Mapping[str, Any] | None = None, observe: bool = True,
    ) -> dict[str, Any]:
        if self.state["attempt_status"] != "STARTED" or self.lock.closed:
            raise PrepError("STARTED_SINGLE_WRITER_REQUIRED")
        if not isinstance(event_id, str) or not event_id:
            raise PrepError("EVENT_ID_REQUIRED")
        event_hash = paper.digest({"event_id": event_id, "now_ms": now_ms, "quotes": quotes,
                                  "wrapper": wrapper, "frames": {str(tf): {s: df.to_dict("records") for s, df in names.items()} for tf, names in frames.items()}})
        old = self.state["processed_events"].get(event_id)
        if old is not None:
            if old != event_hash:
                raise PrepError("DUPLICATE_EVENT_PAYLOAD_CHANGED")
            return self.snapshot()
        now = _time(now_ms, "processing")
        draft = copy.deepcopy(self.state)
        machine = paper.ObservedPaper(draft["paper_state"], self.config,
                                      self.config["reference_costs_bps"], {CANDIDATE: parent})
        if wrapper is not None:
            validate_signal_clock(wrapper, now)
            signal = wrapper["signal"]
            if (signal["symbol"] not in self.config["reference_costs_bps"]
                    or _number(signal["meta"]["frozen_cost_bps"], "signal_frozen_cost", positive=True)
                    != self.config["reference_costs_bps"][signal["symbol"]]):
                raise PrepError("FROZEN_SIGNAL_REFERENCE_COST_BINDING")
            signal_key = paper.digest({"runtime_identity": self.config["runtime_identity"],
                "symbol": signal["symbol"], "side": signal["side"],
                "signal_close_ms": wrapper["decision_bar_close_ms"]})
            signal_hash = paper.digest(dict(wrapper))
            prior = draft["signal_bindings"].get(signal_key)
            if prior is not None and prior != signal_hash:
                raise PrepError("DUPLICATE_SIGNAL_PAYLOAD_OR_RECEIPT_CHANGED")
            draft["signal_bindings"][signal_key] = signal_hash
            if now >= self.config["window_end_ms"]:
                raise PrepError("NEW_SIGNAL_AFTER_HARD_WINDOW_END")
            machine.admit(wrapper, now)
        held_pending = None
        if now >= self.config["window_end_ms"]:
            # Preserve pending attempts without allowing a new post-window fill.
            held_pending = machine.state["pending"]
            machine.state["pending"] = {}
        supplied_frames = {tf: {symbol: frame.copy(deep=True) for symbol, frame in names.items()}
                           for tf, names in frames.items()}
        machine.step(copy.deepcopy(quotes), supplied_frames, now)
        if held_pending is not None:
            machine.state["pending"] = held_pending
        for trade in machine.state["trades"]:
            # Correct storage provenance only; strategy/price/decision stay intact.
            trade["evidence_kind"] = "SYNTHETIC_PREPARATION_ONLY"
        if now >= self.config["window_end_ms"] and (machine.state["positions"] or machine.state["pending"]):
            draft["history"].append({"kind": "WINDOW_END_INCOMPLETE_PRESERVED", "processed_ms": now})
        if observe:
            prior_positions = self.state["paper_state"]["positions"]
            for position in machine.state["positions"].values():
                old = next((value for value in prior_positions.values()
                            if value["key"] == position["key"]), None)
                moved = old is not None and old["stop_price"] != position["stop_price"]
                draft["observations"].append({"trade_key": position["key"], "processed_ms": now,
                    "observation_kind": "STOP_ACTIVATED" if moved else "POSITION_SNAPSHOT",
                    "stop_before": None if old is None else old["stop_price"],
                    "reason_code": "FROZEN_PARENT_STOP_ACTIVATION" if moved else "PASSIVE_OBSERVATION",
                    "stop_price": position["stop_price"], "initial_risk": position["initial_risk"],
                    "mfe_r_so_far": position["mfe_R"], "mae_r_so_far": position["mae_R"],
                    "remaining_original_fraction": position["remaining"],
                    "pending_partial": copy.deepcopy(position["pending_partial"]),
                    "pending_exit": copy.deepcopy(position["pending_exit"]),
                    "known_reference_cost_bps": position["cost_bps"],
                    "feature_used_for_decision": False})
            new_events = machine.state["events"][len(self.state["paper_state"]["events"]):]
            for event in new_events:
                draft["observations"].append({"observation_kind": "PRESERVED_CORE_EVENT",
                    "processed_ms": now, "core_event": copy.deepcopy(event),
                    "core_event_sha256": paper.digest(event), "feature_used_for_decision": False})
        draft["processed_events"][event_id] = event_hash
        draft["history"].append({"kind": "SYNTHETIC_EVENT_COMMITTED", "event_id": event_id, "sha256": event_hash})
        payload = copy.deepcopy(draft)
        payload["state_sha256"] = paper.digest(payload)
        atomic_json(self.out / "STATE.json", payload)
        self.state = draft
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        state = self.state["paper_state"]
        return {"candidate": CANDIDATE, "attempt_status": self.state["attempt_status"],
                "attempt_count": self.state["attempt_count"], "consumed_full_credit": 0,
                "decision_state_sha256": paper.digest(state),
                "open_positions": len(state["positions"]), "pending_signals": len(state["pending"]),
                "closed_synthetic_trades": len(state["trades"]),
                "synthetic_only": True, "genuine_fresh_credit": 0, "g5b_terminal": False,
                "execution_ready": False, "proposed_semantics": SEMANTICS}
