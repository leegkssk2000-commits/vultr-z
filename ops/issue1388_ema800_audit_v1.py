"""Independent saved EMA800 order/price/funding certificate audit; no model replay.

Shares established BBand audit accounting/clock rules. Certifies earliest source
entries, prior-known trailing exits, omitted exits, and all saved arithmetic.
"""
from __future__ import annotations
import math
from typing import Any, Mapping

def audit_ema800_result(result: Mapping[str, Any], market: Mapping[str, Any]) -> None:
    from decimal import Decimal
    from ops.issue1388_alpha_screen_v1 import SYMBOLS, START_MS, END_MS, ScreenError
    from ops.issue1388_bband_rsi_v1 import bind_bband_decisions
    from ops.issue1388_alpha_screen_v1 import ema800_source_decisions
    from ops.issue1388_alpha_screen_v1 import (EMA800_ID, PROFILES, EMA800_CONTRACT_SHA256, EMA800_THESIS_SHA256,
                                             source_binding, six_funding_hashes, summarize, validate_ema800_contract)
    validate_ema800_contract()
    profile = PROFILES[EMA800_ID]
    required = {"schema": "zel.issue1388.cheap_screen_result.v1", "issue": 1388,
                "candidate_id": EMA800_ID, **source_binding(profile), "period_ms": [START_MS, END_MS],
                "timeframe_min": 60, "classification": "DEVELOPMENT_ONLY_NOT_FRESH_NOT_OOS",
                "signal_rules": profile["signal_rules"], "order_adapter": profile["order_adapter"],
                "source_replication": False, "donor_live_fill_equivalence": False,
                "donor_config_and_net_roi_engine_reproduced": False,
                "execution_contract_sha256": EMA800_CONTRACT_SHA256, "frozen_thesis_sha256": EMA800_THESIS_SHA256,
                "funding_hashes": six_funding_hashes(), "mark_account_NAV": None,
                "funding_actual_account_debit_certified": False, "full_consumed": 0,
                "order_authority": "BLOCKED", "exchange_order_submitted": False, "promotion": False}
    if any(result.get(k) != v for k, v in required.items()):
        raise ScreenError("EMA800_SAVED_IDENTITY_CONTRACT_SEMANTICS")
    accounting = result["symbol_accounting"]
    if set(accounting) != set(SYMBOLS):
        raise ScreenError("EMA800_SAVED_SYMBOL_COHORT")
    trades = sorted([t for x in accounting.values() for t in x["trades"]], key=lambda t: (t["exit_ts_ms"], t["symbol"]))
    if result["trades"] != trades:
        raise ScreenError("EMA800_SAVED_TRADE_BINDING")
    for symbol in SYMBOLS:
        saved = accounting[symbol]
        expected_meta = {"candidate_id": EMA800_ID, "symbol": symbol, "period_ms": [START_MS, END_MS],
                         "frozen_roi_ratio": 11.0, "frozen_stop_ratio": 0.85,
                         "trailing_update_policy": "PRIOR_COMPLETED_RECEIVED_HIGH_ONLY",
                         "source_profits_reproduced": False, "account_nav": None,
                         "source_signal_values_certified_by_helper": False, "funding_coverage_certified_by_helper": False,
                         "classification": "INTERNAL_CONSERVATIVE_CLASS_DEFAULT_ADAPTER_NOT_DONOR_CONFIG_REPRODUCTION"}
        if any(saved.get(k) != v for k,v in expected_meta.items()):
            raise ScreenError("EMA800_SAVED_SYMBOL_SEMANTICS")
        rows = market["frames"][symbol].to_dict("records")
        opens = {r["open_ts_ms"]: r for r in rows}
        closes = {r["close_ts_ms"]: r for r in rows}
        frame = market["frames"][symbol]
        entry, exits = ema800_source_decisions(frame)
        decisions = bind_bband_decisions(rows, entry.tolist(), exits.tolist())
        by_signal = {d["signal_open_ts_ms"]: d for d in decisions}
        cutoff = min((x.get("gap_ts_ms", x.get("bar_open_ts_ms", END_MS)) for x in
                      (saved["gap_quarantine"],saved["protective_touch_quarantine"]) if x is not None), default=END_MS)
        events = [d for d in decisions if d["entry"] and START_MS <= d["signal_open_ts_ms"]
                  and d["signal_close_ts_ms"] < END_MS and d["signal_open_ts_ms"] < cutoff]
        entries = [o for o in saved["orders"] if o["kind"] == "ENTRY"]
        admitted = {o["signal_open_ts_ms"] for o in entries}
        if saved["pending_entry"] is not None:
            admitted.add(saved["pending_entry"]["signal_open_ts_ms"])
        positions = saved["trades"] + ([saved["open_position"]] if saved["open_position"] else [])
        occupied_count = sum(any(t["entry_ts_ms"] <= d["signal_open_ts_ms"] and
                             (t.get("exit_ts_ms",END_MS) > d["signal_close_ts_ms"] if t.get("exit_reason", "").startswith("INTRABAR")
                              else t.get("exit_ts_ms",END_MS) > d["signal_open_ts_ms"]) for t in positions)
                             for d in events if d["signal_open_ts_ms"] not in admitted)
        pending_count = len(events) - len(admitted) - occupied_count
        if (saved["signals"] != len(events) or saved["occupied_rejections"] != occupied_count
                or saved["pending_entry_rejections"] != pending_count or pending_count < 0):
            raise ScreenError("EMA800_SAVED_INDEPENDENT_SIGNAL_CENSUS")
        clock_keys = ("signal_open_ts_ms", "signal_close_ts_ms", "signal_available_ts_ms")
        def verify_signal(order: Mapping[str, Any], flag: str, execution: int) -> Mapping[str, Any]:
            decision = by_signal.get(order.get("signal_open_ts_ms"))
            if (decision is None or not decision[flag]
                    or any(order.get(k) != decision[k] for k in clock_keys)
                    or not START_MS <= decision["signal_open_ts_ms"] < decision["signal_close_ts_ms"] < END_MS):
                raise ScreenError("EMA800_SAVED_SOURCE_SIGNAL_BINDING")
            eligible = next((r for r in rows if r["open_ts_ms"] >= decision["signal_available_ts_ms"]), None)
            if (eligible is None or eligible["open_ts_ms"] != execution
                    or eligible["segment_id"] != decision["segment_id"]):
                raise ScreenError("EMA800_SAVED_EARLIEST_CAUSAL_OPEN")
            return decision
        def first_flat_signal(previous: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
            return next((d for d in decisions if d["entry"] and START_MS <= d["signal_open_ts_ms"]
                         and d["signal_close_ts_ms"] < END_MS and (previous is None or
                         (d["signal_close_ts_ms"] >= previous["exit_ts_ms"] if previous["exit_reason"].startswith("INTRABAR")
                          else d["signal_open_ts_ms"] >= previous["exit_ts_ms"]))), None)
        unresolved_certificates = {}
        def first_exit_certificate(position: Mapping[str, Any]) -> tuple[int, float, str] | None:
            basis = Decimal(str(position["entry_price"]))
            stop, roi = float(basis * Decimal("0.85")), float(basis * Decimal("11"))
            pending_ema = next((d for d in decisions if d["exit"] and d["signal_open_ts_ms"] >= position["entry_ts_ms"]), None)
            prior = None
            received_highs = []
            for bar in rows:
                opened = bar["open_ts_ms"]
                if opened < position["entry_ts_ms"] or opened >= END_MS:
                    continue
                if prior is not None and (opened != prior["close_ts_ms"] or bar["segment_id"] != prior["segment_id"]):
                    unresolved_certificates[position["entry_identity"]] = {"kind":"GAP", "stamp":opened, "stop":stop}
                    return None  # Occupied gap cannot certify a later exit.
                prior = bar
                for receipt, high in received_highs:
                    if receipt <= opened:
                        stop = max(stop, float(Decimal(str(high)) * Decimal("0.85")))
                received_highs = [(receipt, high) for receipt, high in received_highs if receipt > opened]
                if opened > position["entry_ts_ms"]:
                    if float(bar["open"]) <= stop:
                        return opened, float(bar["open"]), "OPEN_STOP"
                    if float(bar["open"]) >= roi:
                        return opened, float(bar["open"]), "OPEN_ROI"
                    if pending_ema is not None and pending_ema["signal_available_ts_ms"] <= opened:
                        return opened, float(bar["open"]), "NEXT_AVAILABLE_OPEN_EMA_EXIT"
                reason = "INTRABAR_STOP_FIRST" if float(bar["low"]) <= stop else "INTRABAR_ROI" if float(bar["high"]) >= roi else None
                if reason:
                    if bar["close_ts_ms"] == END_MS or bar["available_ts_ms"] != bar["close_ts_ms"]:
                        unresolved_certificates[position["entry_identity"]] = {"kind":"TERMINAL" if bar["close_ts_ms"] == END_MS else "LATE_TOUCH", "bar":bar, "reason":reason, "price":stop if reason == "INTRABAR_STOP_FIRST" else roi, "stop":stop}
                        return None  # Terminal or late protective receipt remains unresolved.
                    return bar["close_ts_ms"], stop if reason == "INTRABAR_STOP_FIRST" else roi, reason
                received_highs.append((bar["available_ts_ms"], bar["high"]))
            unresolved_certificates[position["entry_identity"]] = {"kind":"OPEN", "stop":stop}
            return None
        one_way = float(market["costs"][symbol]) / 2
        position, trade_index, paid, last_stamp = None, 0, 0.0, -1
        def funding(entry: int, exit_: int, basis: float, closed: bool) -> tuple[float, int]:
            debit, count = 0.0, 0
            for row in market["six_funding"][symbol]:
                stamp = row["fundingTime"]
                if entry <= stamp <= exit_ and stamp < END_MS:
                    value = float(row["fundingRate"]) * float(row["markPrice"]) / basis * 10000
                    if stamp != entry and (not closed or stamp != exit_) or value > 0:
                        debit += value
                        count += 1
            return debit, count
        for order in saved["orders"]:
            stamp, price = order["execution_ts_ms"], order["price"]
            if (order["quantity"] != 1 or not START_MS <= stamp < END_MS
                    or not math.isclose(order["cost_bps"], one_way, abs_tol=1e-9)):
                raise ScreenError("EMA800_SAVED_ORDER_COST_CLOCK")
            if stamp < last_stamp:
                raise ScreenError("EMA800_SAVED_EXECUTION_CHRONOLOGY")
            last_stamp = stamp
            paid += one_way
            if order["kind"] == "ENTRY":
                if position is not None or stamp not in opens or price != float(opens[stamp]["open"]):
                    raise ScreenError("EMA800_SAVED_ENTRY_PRICE")
                decision = verify_signal(order, "entry", stamp)
                previous = saved["trades"][trade_index - 1] if trade_index else None
                if first_flat_signal(previous) != decision:
                    raise ScreenError("EMA800_SAVED_FIRST_ADMISSIBLE_ENTRY")
                identity = f"{symbol}:{stamp}:{order['signal_open_ts_ms']}"
                if order["entry_identity"] != identity:
                    raise ScreenError("EMA800_SAVED_ENTRY_SIGNAL_IDENTITY")
                position = {"identity": EMA800_ID, "symbol":symbol, "side":"LONG", "entry_cost_bps":one_way,
                            "entry_ts_ms": stamp, "entry_price": price, "entry_identity": identity,
                            **{k: order[k] for k in clock_keys}}
            elif order["kind"] == "EXIT":
                if position is None or order["entry_identity"] != position["entry_identity"] or trade_index >= len(saved["trades"]):
                    raise ScreenError("EMA800_SAVED_EXIT_BINDING")
                if stamp <= position["entry_ts_ms"]:
                    raise ScreenError("EMA800_SAVED_EXECUTION_CHRONOLOGY")
                trade = saved["trades"][trade_index]
                if order["reason"] == "NEXT_AVAILABLE_OPEN_EMA_EXIT":
                    decision = verify_signal(order, "exit", stamp)
                    first = next((d for d in decisions if d["exit"] and
                                  d["signal_open_ts_ms"] >= position["entry_ts_ms"]), None)
                    if (first != decision or any(trade.get("exit_" + k) != decision[k] for k in clock_keys)):
                        raise ScreenError("EMA800_SAVED_EXIT_FIRST_SIGNAL_BINDING")
                basis = position["entry_price"]
                stop, roi = float(Decimal(str(basis)) * Decimal("0.85")), float(Decimal(str(basis)) * Decimal("11"))
                reason = order["reason"]
                if first_exit_certificate(position) != (stamp, price, reason):
                    raise ScreenError("EMA800_SAVED_FIRST_EXIT_OR_SOURCE_GAP")
                valid = True  # certified first causal exit above
                gross = (price / basis - 1) * 10000
                debit, count = funding(position["entry_ts_ms"], stamp, basis, True)
                if (not valid or any(trade.get(k) != position[k] for k in position)
                        or trade["symbol"] != symbol or trade["exit_ts_ms"] != stamp or trade["exit_price"] != price
                        or trade["exit_reason"] != reason or not math.isclose(trade["gross_bps"], gross, abs_tol=1e-9)
                        or not math.isclose(trade["cost_bps"], 2 * one_way, abs_tol=1e-9)
                        or not math.isclose(trade["funding_bps"], debit, abs_tol=1e-9)
                        or trade["funding_settlements"] != count
                        or not math.isclose(trade["net_bps"], gross - 2 * one_way - debit, abs_tol=1e-9)):
                    raise ScreenError("EMA800_SAVED_EXIT_GROSS_FUNDING_AUDIT")
                trade_index += 1
                position = None
            else:
                raise ScreenError("EMA800_SAVED_ORDER_KIND")
        open_position = saved["open_position"]
        if position is None and saved["gap_quarantine"] is None and saved["protective_touch_quarantine"] is None:
            next_signal = first_flat_signal(saved["trades"][-1] if saved["trades"] else None)
            if next_signal is not None:
                expected_open = next((r for r in rows if r["open_ts_ms"] >= next_signal["signal_available_ts_ms"]), None)
                if expected_open is not None and expected_open["open_ts_ms"] < END_MS:
                    raise ScreenError("EMA800_SAVED_MISSING_ADMISSIBLE_ENTRY")
                if saved["pending_entry"] != next_signal:
                    raise ScreenError("EMA800_SAVED_PENDING_ENTRY_BINDING")
        if saved["pending_entry"] is not None:
            pending = saved["pending_entry"]
            expected_signal = first_flat_signal(saved["trades"][-1] if saved["trades"] else None)
            eligible = next((r for r in rows if r["open_ts_ms"] >= pending.get("signal_available_ts_ms",-1)),None)
            if (position is not None or pending != expected_signal or
                    eligible is not None and eligible["open_ts_ms"] < cutoff and eligible["open_ts_ms"] < END_MS):
                raise ScreenError("EMA800_SAVED_PENDING_ENTRY_FIRST_CAUSAL_OPEN")
            first_gap = next((r["open_ts_ms"] for i,r in enumerate(rows) if i>0 and
                              r["open_ts_ms"] >= pending["signal_close_ts_ms"] and r["open_ts_ms"] < END_MS and
                              (r["segment_id"] != rows[i-1]["segment_id"] or r["open_ts_ms"] != rows[i-1]["close_ts_ms"])),None)
            if saved["gap_quarantine"] is not None and first_gap != cutoff:
                raise ScreenError("EMA800_SAVED_PENDING_ENTRY_FIRST_GAP")
        if position is not None and first_exit_certificate(position) is not None:
            raise ScreenError("EMA800_SAVED_OMITTED_FIRST_EXIT")
        gap, late, terminal = saved["gap_quarantine"], saved["protective_touch_quarantine"], saved["terminal_protective_touch"]
        held = unresolved_certificates.get(position["entry_identity"]) if position is not None else None
        if gap is not None:
            if not isinstance(gap, dict) or set(gap) != {"gap_ts_ms","position","pending_entry","pending_exit"}:
                raise ScreenError("EMA800_SAVED_GAP_CERTIFICATE")
            stamp = gap["gap_ts_ms"]
            index = next((i for i,r in enumerate(rows) if r["open_ts_ms"] == stamp), None)
            if (index is None or index == 0 or stamp >= END_MS or
                    (rows[index]["segment_id"] == rows[index-1]["segment_id"] and stamp == rows[index-1]["close_ts_ms"]) or
                    position is None and saved["pending_entry"] is None or
                    position is not None and (held is None or held["kind"] != "GAP" or held["stamp"] != stamp) or
                    gap["pending_entry"] != saved["pending_entry"] or gap["pending_exit"] != saved["pending_exit"] or
                    (gap["position"] is None) != (position is None) or
                    position is not None and gap["position"] != position):
                raise ScreenError("EMA800_SAVED_GAP_CERTIFICATE")
        elif held is not None and held["kind"] == "GAP":
            raise ScreenError("EMA800_SAVED_OMITTED_GAP")
        for value, kind in ((late,"LATE_TOUCH"),(terminal,"TERMINAL")):
            if value is not None:
                if (not isinstance(value,dict) or held is None or held["kind"] != kind or
                        value.get("entry_identity", value.get("position",{}).get("entry_identity")) != position["entry_identity"] or
                        value.get("bar_open_ts_ms") != held["bar"]["open_ts_ms"] or
                        value.get("bar_close_ts_ms") != held["bar"]["close_ts_ms"] or
                        value.get("reason") != held["reason"] or value.get("threshold_price") != held["price"]):
                    raise ScreenError("EMA800_SAVED_TOUCH_CERTIFICATE")
                expected_touch = {"bar_open_ts_ms":held["bar"]["open_ts_ms"], "bar_close_ts_ms":held["bar"]["close_ts_ms"],
                                  "reason":held["reason"], "threshold_price":held["price"]}
                if kind == "TERMINAL":
                    expected_touch.update(entry_identity=position["entry_identity"],classification="UNRESOLVED_TOUCH_NO_END_ORDER")
                else:
                    expected_touch.update(available_ts_ms=held["bar"]["available_ts_ms"],position=position,
                                          pending_entry=saved["pending_entry"],pending_exit=saved["pending_exit"])
                if value != expected_touch:
                    raise ScreenError("EMA800_SAVED_EXACT_TOUCH_STATE")
            elif held is not None and held["kind"] == kind:
                raise ScreenError("EMA800_SAVED_OMITTED_TOUCH")
        if position is not None:
            if saved["open_stop_price"] != held["stop"]:
                raise ScreenError("EMA800_SAVED_OPEN_TRAILING_STOP")
            bound_exit = next((d for d in decisions if d["exit"] and d["signal_open_ts_ms"] >= position["entry_ts_ms"]
                              and d["signal_open_ts_ms"] < cutoff and d["signal_close_ts_ms"] < END_MS),None)
            expected_pending = {**bound_exit,"entry_identity":position["entry_identity"]} if bound_exit else None
            if saved["pending_exit"] != expected_pending:
                raise ScreenError("EMA800_SAVED_PENDING_EXIT")
            if held["kind"] == "OPEN" and open_position.get("funding_bps_to_end_exclusive") is None:
                raise ScreenError("EMA800_SAVED_OPEN_FUNDING_REQUIRED")
        elif saved["pending_exit"] is not None or saved["open_stop_price"] is not None:
            raise ScreenError("EMA800_SAVED_ORPHAN_EXIT_STOP")
        expected_unresolved = int(position is not None or saved["pending_entry"] is not None or saved["pending_exit"] is not None or gap is not None or late is not None)
        if (saved["unresolved_end"] != expected_unresolved or
                saved["closed_trading_cost_bps"] != sum(t["cost_bps"] for t in saved["trades"]) or
                saved["open_entry_cost_bps"] != (one_way if position is not None else 0)):
            raise ScreenError("EMA800_SAVED_UNRESOLVED_COST_BREAKDOWN")
        if ((position is None) != (open_position is None) or trade_index != len(saved["trades"])
                or position is not None and any(position[k] != open_position.get(k) for k in position)
                or not math.isclose(paid, saved["paid_trading_cost_bps"], abs_tol=1e-9)
                or not math.isclose(paid, sum(t["cost_bps"] for t in saved["trades"]) + (one_way if position else 0), abs_tol=1e-9)):
            raise ScreenError("EMA800_SAVED_OPEN_COUNT_PAID_COST_AUDIT")
        if position is not None and open_position["funding_bps_to_end_exclusive"] is not None:
            debit, count = funding(position["entry_ts_ms"], END_MS, position["entry_price"], False)
            if not math.isclose(open_position["funding_bps_to_end_exclusive"], debit, abs_tol=1e-9) or open_position["funding_settlements"] != count:
                raise ScreenError("EMA800_SAVED_OPEN_FUNDING_AUDIT")
    gaps = sum(int(x["gap_quarantine"] is not None or x["protective_touch_quarantine"] is not None) for x in accounting.values())
    unresolved = sum(int(x["open_position"] is not None or x["pending_entry"] is not None or x["pending_exit"] is not None or x["gap_quarantine"] is not None or x["protective_touch_quarantine"] is not None) for x in accounting.values())
    disposition = ("BLOCKED_INPUT_GAP_OR_PROTECTIVE_CLOCK" if gaps else "BLOCKED_TERMINAL_OUTCOME_UNRESOLVED" if unresolved else
                   "SCREEN_SURVIVOR_PENDING_FULL" if result["cost_1x"]["T"] > 0 and result["cost_1x"]["Net_bps"] > 0 and result["cost_2x"]["Net_bps"] > 0 else "REJECT_ECONOMIC_EARLY")
    expected_census = {"signals_or_attempts": sum(x["signals"] for x in accounting.values()), "completed": len(trades),
                       "occupied_rejections": sum(x["occupied_rejections"] for x in accounting.values()),
                       "pending_rejections": sum(x["pending_entry_rejections"] for x in accounting.values()),
                       "gap_quarantined": gaps, "missing_fill_evidence": gaps, "unresolved_end": unresolved}
    if (result["census"] != expected_census or result["disposition"] != disposition
            or result["cost_1x"] != summarize(trades,1) or result["cost_2x"] != summarize(trades,2)):
        raise ScreenError("EMA800_SAVED_DISPOSITION_AUDIT")


