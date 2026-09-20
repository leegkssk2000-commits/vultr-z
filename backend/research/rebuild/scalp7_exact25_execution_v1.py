"""Small per-order detail adapter; model witnesses never become observed fills.

No data loader, signal search, FULL runner, order API, or portfolio allocator.
The old execution_v2 profile remains unchanged. Prices below are fill prices:
slippage is not separately deducted. Account equity uses actual base quantity.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from backend.research.rebuild.scalp7_implementation_contract_v1 import (
    AUTHORITY,
    _decimal,
    _required_text,
    _timestamp,
    inspect_entry_bar,
    value_account_snapshots,
)

SCHEMA = "zel.scalp7.exact25_execution_adapter.v1"
MODEL = "DECLARED_OHLC_MARKET_V1"
RECEIPT_ONLY = "RECEIPT_ONLY"
MINUTE = 60_000


def _float(value: Any, name: str, *, positive: bool = False) -> float:
    result = float(_decimal(value, name, positive=positive))
    if not math.isfinite(result):
        raise ValueError("FLOAT_RANGE:" + name)
    return result


class DetailExecutionAdapter:
    """One order/episode, contiguous minutes, explicit fill model and costs.

    Historical market candidates fill the remaining quantity under an explicit
    all-remaining market assumption. This is NOT an observed queue/size model.
    LIMIT touch never fills. Receipt-only mode accepts actual partial receipts;
    absent receipts, an OHLC stop crossing remains unresolved. No assumed TP.
    Callbacks run only on validated complete 15m/30m decision bars; their new
    stop/market exit can affect subsequent detail bars only.
    """

    def __init__(
        self,
        order: Mapping[str, Any],
        *,
        fill_model: str,
        fee_rate: Any,
        entry_update: Callable[..., dict[str, Any]] | None = None,
        exit_update: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        if fill_model not in {MODEL, RECEIPT_ONLY}:
            raise ValueError("EXPLICIT_FILL_MODEL_REQUIRED")
        self.order = copy.deepcopy(dict(order))
        for key in ("identity", "symbol", "rule_digest", "timing_basis"):
            _required_text(order, key)
        for key in (
            "decision_tf_min",
            "feature_available_ts_ms",
            "order_submit_ts_ms",
            "order_active_ts_ms",
            "expires_ts_ms",
        ):
            _timestamp(order.get(key), key)
        if order["decision_tf_min"] not in (15, 30):
            raise ValueError("SCALP7_TIMEFRAME_REQUIRED")
        if not (
            order["feature_available_ts_ms"]
            <= order["order_submit_ts_ms"]
            <= order["order_active_ts_ms"]
            < order["expires_ts_ms"]
        ):
            raise ValueError("ORDER_CLOCK_NOT_CAUSAL")
        if order.get("side") not in (-1, 1) or isinstance(order.get("side"), bool):
            raise ValueError("INVALID_SIDE")
        if order.get("order_kind") not in {"NEXT_OPEN", "STOP_MARKET", "LIMIT"}:
            raise ValueError("INVALID_ORDER_KIND")
        if order["timing_basis"] not in {"HISTORICAL_MODEL", "OBSERVED_ORDER"}:
            raise ValueError("INVALID_TIMING_BASIS")
        if fill_model == MODEL and order["timing_basis"] != "HISTORICAL_MODEL":
            raise ValueError("MODEL_CANNOT_CLAIM_OBSERVED_ORDER")
        self.fee_rate = _decimal(fee_rate, "fee_rate")
        if self.fee_rate < 0:
            raise ValueError("NEGATIVE_FEE_RATE")
        self.requested = _decimal(order.get("qty_base"), "qty_base", positive=True)
        self.remaining = self.requested
        self.stop = _float(
            order.get("protective_stop"), "protective_stop", positive=True
        )
        self.fill_model = fill_model
        self.entry_update, self.exit_update = entry_update, exit_update
        self.state, self.order_state = "PENDING", "PENDING"
        self.position: dict[str, Any] | None = None
        self.ledger: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.details: list[dict[str, Any]] = []
        self.last_available = int(order["feature_available_ts_ms"])
        self.last_decision = -1
        self.pending_update: dict[str, Any] | None = None
        self.receipt_ids: set[str] = set()
        self.episode_id = str(
            order.get(
                "position_episode_id",
                order["identity"] + ":" + str(order["order_active_ts_ms"]),
            )
        )

    def _event(self, status: str, **extra: Any) -> dict[str, Any]:
        event = {
            "status": status,
            **extra,
            "authority": dict(AUTHORITY),
            "economic_credit": False,
            "execution_profile": SCHEMA,
            "fill_model": self.fill_model,
        }
        self.events.append(event)
        return event

    def _unresolved(self, reason: str) -> dict[str, Any]:
        self.state = "UNRESOLVED"
        return self._event(reason, remaining_qty_base=str(self.remaining))

    def cancel(self, ts_ms: int, reason: str = "CAUSAL_CANCEL") -> dict[str, Any]:
        stamp = _timestamp(ts_ms, "cancel_ts_ms")
        if stamp < self.last_available or stamp < self.order["order_submit_ts_ms"]:
            raise ValueError("RETROACTIVE_CANCEL")
        if self.state == "UNRESOLVED":
            raise ValueError("UNRESOLVED_OWNERSHIP_RETAINED")
        self.order_state = "CANCELLED"
        self.last_available = stamp
        self.state = "ACTIVE" if self.position is not None else "CANCELLED"
        return self._event(reason, cancelled_remaining_qty_base=str(self.remaining))

    def record_fill(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        """Append an explicit fill receipt; no price-touch to maker conversion."""
        if self.state in {"UNRESOLVED", "CLOSED"}:
            raise ValueError("TERMINAL_EPISODE")
        row = copy.deepcopy(dict(receipt))
        fill_id = _required_text(row, "fill_id")
        if fill_id in self.receipt_ids:
            raise ValueError("DUPLICATE_FILL_ID")
        _required_text(row, "source_ref")
        stamp = _timestamp(row.get("ts_ms"), "fill_ts_ms")
        known = _timestamp(row.get("available_ts_ms"), "fill_available_ts_ms")
        if known < stamp or known < self.last_available:
            raise ValueError("FILL_AVAILABILITY_NOT_CAUSAL")
        if self.ledger and stamp < self.ledger[-1]["ts_ms"]:
            raise ValueError("FILL_TIME_NOT_CHRONOLOGICAL")
        if row.get("symbol") != self.order["symbol"]:
            raise ValueError("SYMBOL_MISMATCH")
        for key, expected_binding in (
            ("side", self.order["side"]),
            ("identity", self.order["identity"]),
            ("position_episode_id", self.episode_id),
        ):
            if key in row and (
                row[key] != expected_binding or isinstance(row[key], bool)
            ):
                raise ValueError("FILL_BINDING_MISMATCH:" + key)
        evidence = row.get("execution_evidence")
        expected = (
            "MODEL_NOT_OBSERVED"
            if self.fill_model == MODEL
            else "OBSERVED_FILL_RECEIPT"
        )
        if evidence != expected:
            raise ValueError("FILL_EVIDENCE_MISMATCH")
        if row.get("maker_taker") not in {"MAKER", "TAKER", "UNKNOWN"}:
            raise ValueError("MAKER_TAKER_REQUIRED")
        qty = _decimal(row.get("qty_base"), "qty_base", positive=True)
        price = _decimal(row.get("fill_price"), "fill_price", positive=True)
        _float(price, "fill_price", positive=True)
        fee = _decimal(row.get("fee_usdt"), "fee_usdt")
        if fee < 0 or "slippage_usdt" in row or "leverage" in row:
            raise ValueError("COST_OR_SIZE_REAPPLICATION_FORBIDDEN")
        effect = row.get("effect")
        if effect == "OPEN":
            if self.order_state not in {"PENDING", "PARTIAL"}:
                raise ValueError("ORDER_NOT_FILLABLE")
            if (
                not self.order["order_active_ts_ms"]
                <= stamp
                < self.order["expires_ts_ms"]
            ):
                raise ValueError("FILL_OUTSIDE_ACTIVATION_WINDOW")
            if qty > self.remaining:
                raise ValueError("OVERFILL")
            new_stop = self.stop
            if self.entry_update is not None:
                update = self.entry_update(
                    copy.deepcopy(self.order.get("signal", self.order)), float(price)
                )
                if update.get("reject"):
                    raise ValueError("ENTRY_CALLBACK_REJECTED")
                new_stop = _float(
                    update.get("stop_price", self.stop), "stop_price", positive=True
                )
            if self.order["side"] * (float(price) - new_stop) <= 0:
                raise ValueError("ENTRY_INVALIDATES_STOP")
            old_qty = (
                Decimal(0)
                if self.position is None
                else _decimal(self.position["remaining_qty_base"], "remaining_qty_base")
            )
            old_entry = (
                Decimal(0)
                if self.position is None
                else _decimal(self.position["entry_price"], "entry_price")
            )
            total = old_qty + qty
            entry = (old_qty * old_entry + qty * price) / total
            self.stop = (
                max(self.stop, new_stop)
                if self.order["side"] == 1
                else min(self.stop, new_stop)
            )
            if self.position is None:
                self.position = {
                    "signal": copy.deepcopy(self.order.get("signal", self.order)),
                    "side": self.order["side"],
                    "entry_ts_ms": stamp,
                    "initial_stop": self.stop,
                    "initial_risk": abs(float(price) - self.stop),
                    "hold_bars": 0,
                    "mfe_R": 0.0,
                    "mae_R": 0.0,
                    "realized_parts_bps": 0.0,
                }
            self.position.update(
                entry_price=float(entry),
                entry_prices={self.order["symbol"]: float(entry)},
                remaining_qty_base=str(total),
                remaining=float(total / self.requested),
                stop_price=self.stop,
            )
            self.remaining -= qty
            self.order_state = "FILLED" if not self.remaining else "PARTIAL"
            self.state = "ACTIVE"
        elif effect == "CLOSE":
            if self.position is None:
                raise ValueError("CLOSE_WITHOUT_POSITION")
            held = _decimal(self.position["remaining_qty_base"], "remaining_qty_base")
            if qty > held:
                raise ValueError("OVERCLOSE")
            left = held - qty
            if left:
                self.position["remaining_qty_base"] = str(left)
                self.position["remaining"] = float(left / self.requested)
            else:
                self.position = None
                self.order_state = "CANCELLED" if self.remaining else "FILLED"
                self.state = "CLOSED"
        else:
            raise ValueError("FILL_EFFECT_REQUIRED")
        self.receipt_ids.add(fill_id)
        self.last_available = known
        self.ledger.append(
            {
                **row,
                "type": "FILL",
                "side": self.order["side"],
                "position_episode_id": self.episode_id,
                "identity": self.order["identity"],
                "qty_base": str(qty),
                "fill_price": str(price),
                "fee_usdt": str(fee),
                "authority": dict(AUTHORITY),
            }
        )
        return self._event(
            "FILL_RECORDED", fill_id=fill_id, execution_evidence=evidence
        )

    def _model_fill(
        self, effect: str, price: float, interval: list[int], known: int
    ) -> None:
        qty = self.remaining if effect == "OPEN" else _decimal(self.position["remaining_qty_base"], "qty")  # type: ignore[index]
        stamp = interval[0] if interval[0] == interval[1] else interval[1]
        self.record_fill(
            {
                "fill_id": f"model:{self.episode_id}:{len(self.ledger)}",
                "ts_ms": stamp,
                "available_ts_ms": known,
                "symbol": self.order["symbol"],
                "effect": effect,
                "qty_base": str(qty),
                "fill_price": price,
                "fee_usdt": str(qty * Decimal(str(price)) * self.fee_rate),
                "maker_taker": "TAKER",
                "source_ref": MODEL,
                "execution_evidence": "MODEL_NOT_OBSERVED",
                "event_interval_ms": interval,
                "time_precision": (
                    "OPEN" if interval[0] == interval[1] else "MINUTE_INTERVAL"
                ),
                "queue_model": "NONE",
                "size_model": "ALL_REMAINING_MARKET_ASSUMPTION",
            }
        )

    def process_detail_bar(self, bar: Mapping[str, Any]) -> dict[str, Any]:
        if self.state in {"UNRESOLVED", "CLOSED", "CANCELLED", "EXPIRED"}:
            return self._event("TERMINAL_NO_REPLAY")
        witness = inspect_entry_bar(self.order, bar)
        bar = {
            **bar,
            **{
                k: _float(bar[k], k, positive=True)
                for k in ("open", "high", "low", "close")
            },
        }
        opened, closed, known = [
            int(bar[k]) for k in ("open_ts_ms", "close_ts_ms", "available_ts_ms")
        ]
        if closed - opened != MINUTE or opened % MINUTE:
            raise ValueError("ONE_MINUTE_DETAIL_REQUIRED")
        if self.details:
            prior = self.details[-1]
            if (
                opened != prior["close_ts_ms"]
                or bar["segment_id"] != prior["segment_id"]
            ):
                return self._unresolved("DETAIL_GAP_NO_SYNTHETIC_FILL")
        elif opened > self.order["order_active_ts_ms"]:
            return self._unresolved("MISSING_ACTIVATION_DETAIL")
        if known < self.last_available:
            raise ValueError("DETAIL_AVAILABILITY_NOT_CAUSAL")
        self.details.append(dict(bar))
        self.last_available = known
        if closed <= self.order["order_active_ts_ms"]:
            return self._event("BEFORE_ACTIVATION")
        if self.pending_update is not None:
            if opened < self.pending_update["effective_ts_ms"]:
                return self._unresolved("UPDATE_ACTIVE_INSIDE_DETAIL_BAR")
            update, self.pending_update = self.pending_update, None
            self.stop = update.get("next_stop", self.stop)
            if self.position is not None:
                self.position["stop_price"] = self.stop
            if update.get("exit_next_open") and self.position is not None:
                if self.fill_model == RECEIPT_ONLY:
                    return self._unresolved("EXIT_RECEIPT_REQUIRED")
                self._model_fill("CLOSE", float(bar["open"]), [opened, opened], known)
                return self._event("MODEL_CALLBACK_EXIT")
        entering_interval = False
        if self.order_state in {"PENDING", "PARTIAL"}:
            status = witness["status"]
            if status == "EXPIRED":
                self.order_state = "EXPIRED"
                if self.position is None:
                    self.state = "EXPIRED"
                    return self._event("EXPIRED")
            elif status.startswith("UNRESOLVED") or (
                status == "MISSED_ACTIVATION_OPEN" and self.order_state != "PARTIAL"
            ):
                return self._unresolved(status)
            elif status == "ENTRY_INVALIDATES_STOP":
                self.order_state = "CANCELLED"
                if self.position is None:
                    self.state = "CANCELLED"
                    return self._event(status)
            elif status.startswith("MODEL_") and self.fill_model == MODEL:
                interval = witness["event_interval_ms"]
                entering_interval = interval[0] != interval[1]
                if entering_interval and interval[1] >= self.order["expires_ts_ms"]:
                    return self._unresolved("ENTRY_TIME_INTERVAL_OVERLAPS_EXPIRY")
                self._model_fill("OPEN", witness["candidate_price"], interval, known)
        if self.position is not None:
            side = self.order["side"]
            touched = bar["low"] <= self.stop if side == 1 else bar["high"] >= self.stop
            if touched:
                if entering_interval or opened < self.position["entry_ts_ms"] < closed:
                    return self._unresolved("ENTRY_UPDATED_STOP_ORDER_AMBIGUOUS")
                if self.fill_model == RECEIPT_ONLY:
                    return self._unresolved("STOP_RECEIPT_REQUIRED")
                gap = side * (float(bar["open"]) - self.stop) < 0
                price = float(bar["open"]) if gap else self.stop
                self._model_fill(
                    "CLOSE", price, [opened, opened] if gap else [opened, closed], known
                )
                return self._event("MODEL_PROTECTIVE_EXIT")
            if not entering_interval and opened >= self.position["entry_ts_ms"]:
                entry, risk = (
                    self.position["entry_price"],
                    self.position["initial_risk"],
                )
                favorable = (
                    (float(bar["high"]) - entry) / risk
                    if side == 1
                    else (entry - float(bar["low"])) / risk
                )
                adverse = (
                    (entry - float(bar["low"])) / risk
                    if side == 1
                    else (float(bar["high"]) - entry) / risk
                )
                self.position["mfe_R"] = max(self.position["mfe_R"], favorable)
                self.position["mae_R"] = max(self.position["mae_R"], adverse)
        return self._event(witness["status"], remaining_qty_base=str(self.remaining))

    def process_decision_bar(
        self, bar: Mapping[str, Any], history: Any
    ) -> dict[str, Any]:
        """Use existing callback convention, but never apply its stop to its bar."""
        if bar.get("symbol") != self.order["symbol"]:
            raise ValueError("SYMBOL_MISMATCH")
        tf_ms = int(self.order["decision_tf_min"]) * MINUTE
        opened, closed, known = [
            _timestamp(bar.get(k), k)
            for k in ("open_ts_ms", "close_ts_ms", "available_ts_ms")
        ]
        if opened % tf_ms or closed != opened + tf_ms or known < closed:
            raise ValueError("DECISION_CLOCK_INVALID")
        if known != self.last_available or closed <= self.last_decision:
            raise ValueError("DECISION_NOT_CURRENT_OR_DUPLICATE")
        parts = [r for r in self.details if opened <= r["open_ts_ms"] < closed]
        if len(parts) != tf_ms // MINUTE or parts[-1]["close_ts_ms"] != closed:
            raise ValueError("DECISION_DETAIL_COVERAGE_MISSING")
        if any(r["segment_id"] != bar.get("segment_id") for r in parts):
            raise ValueError("DECISION_DETAIL_SEGMENT_MISMATCH")
        expected = [
            parts[0]["open"],
            max(r["high"] for r in parts),
            min(r["low"] for r in parts),
            parts[-1]["close"],
        ]
        if any(
            _decimal(bar.get(k), k) != _decimal(v, k)
            for k, v in zip(("open", "high", "low", "close"), expected)
        ):
            raise ValueError("DECISION_DETAIL_OHLC_MISMATCH")
        rows = (
            history.to_dict("records") if hasattr(history, "to_dict") else list(history)
        )
        if any(
            _timestamp(r.get("available_ts_ms"), "available_ts_ms") > known
            or _timestamp(r.get("close_ts_ms"), "close_ts_ms") > closed
            for r in rows
        ):
            raise ValueError("CALLBACK_HISTORY_CONTAINS_FUTURE")
        if any("symbol" in r and r["symbol"] != self.order["symbol"] for r in rows):
            raise ValueError("CALLBACK_HISTORY_SYMBOL_MISMATCH")
        if self.state != "ACTIVE" or self.position is None or self.exit_update is None:
            self.last_decision = closed
            return self._event("DECISION_NO_ACTIVE_CALLBACK")
        if opened < self.position["entry_ts_ms"]:
            self.last_decision = closed
            return self._event("SKIP_ENTRY_STRADDLING_DECISION_BAR")
        callback_position = copy.deepcopy(self.position)
        callback_position["hold_bars"] += 1
        update = self.exit_update(
            callback_position,
            copy.deepcopy(dict(bar)),
            copy.deepcopy(history),
        )
        if not isinstance(update, Mapping):
            raise ValueError("CALLBACK_MAPPING_REQUIRED")
        if "exit_next_open" in update and not isinstance(
            update["exit_next_open"], bool
        ):
            raise ValueError("CALLBACK_EXIT_FLAG_MUST_BE_BOOL")
        if update.get("partial_fraction"):
            raise ValueError("PARTIAL_CALLBACK_REQUIRES_EXPLICIT_FILL_RECEIPT")
        permitted = {"next_stop", "exit_next_open", "reason"}
        if set(update) - permitted:
            raise ValueError("UNSUPPORTED_EXIT_CALLBACK_FIELDS")
        pending = {**update, "effective_ts_ms": known}
        if pending.get("next_stop") is None:
            pending.pop("next_stop", None)
        if update.get("next_stop") is not None:
            new_stop = _float(update["next_stop"], "next_stop", positive=True)
            pending["next_stop"] = (
                max(self.stop, new_stop)
                if self.order["side"] == 1
                else min(self.stop, new_stop)
            )
        self.position["hold_bars"] += 1
        self.last_decision = closed
        self.pending_update = pending
        return self._event("DECISION_UPDATE_SCHEDULED", effective_ts_ms=known)

    def finish(self) -> dict[str, Any]:
        if self.state in {"PENDING", "ACTIVE"}:
            self._unresolved("END_OF_DETAIL_UNRESOLVED")
        return {
            "schema": SCHEMA,
            "state": self.state,
            "order_state": self.order_state,
            "remaining_order_qty_base": str(self.remaining),
            "position": copy.deepcopy(self.position),
            "ledger": copy.deepcopy(self.ledger),
            "events": copy.deepcopy(self.events),
            "fill_model": self.fill_model,
            "authority": dict(AUTHORITY),
            "economic_execution_performed": False,
            "order": copy.deepcopy(self.order),
            "observed_fill_receipts_supplied": bool(self.ledger)
            and self.fill_model == RECEIPT_ONLY,
            "receipt_authenticity_verified": False,
            "limitations": [
                "ONE_ORDER_NOT_PORTFOLIO",
                "NO_QUEUE_MODEL",
                "NO_LIQUIDATION_SIMULATION",
            ],
        }


def account_snapshots_from_ledger(
    ledger: Sequence[Mapping[str, Any]],
    price_snapshots: Sequence[Mapping[str, Any]],
    *,
    initial_cash_usdt: Any,
    start_ts_ms: Any,
    price_basis: str,
) -> dict[str, Any]:
    """Adapt actual/model fill and cash ledgers to synchronized valuation.

    Input rows: FILL(effect OPEN/CLOSE, qty_base, fill_price, fee_usdt, side,
    position_episode_id,symbol,fill_id); FEE(amount_usdt); FUNDING(signed
    amount_usdt, symbol, settlement_ts_ms); each has ts_ms,event_id/source_ref.
    Rows must already be in actual event sequence; same-ms sequence is retained.
    No HLC substitution, leverage multiplication, or slippage double deduction.
    """
    start = _timestamp(start_ts_ms, "start_ts_ms")
    events = [dict(r) for r in ledger]
    previous = start - 1
    seen: set[str] = set()
    for row in events:
        ts = _timestamp(row.get("ts_ms"), "ledger_ts_ms")
        if ts < start or ts < previous:
            raise ValueError("LEDGER_NOT_CHRONOLOGICAL")
        previous = ts
        if (
            "available_ts_ms" in row
            and _timestamp(row["available_ts_ms"], "available_ts_ms") < ts
        ):
            raise ValueError("LEDGER_AVAILABLE_BEFORE_EVENT")
        for unit_key, expected_unit in (
            ("quantity_unit", "BASE"),
            ("cash_unit", "USDT"),
        ):
            if unit_key in row and row[unit_key] != expected_unit:
                raise ValueError("LEDGER_UNIT_MISMATCH:" + unit_key)
        _required_text(row, "source_ref")
        key = _required_text(
            row, "fill_id" if row.get("type") == "FILL" else "event_id"
        )
        if key in seen:
            raise ValueError("DUPLICATE_LEDGER_EVENT")
        seen.add(key)
        if "leverage" in row or "slippage_usdt" in row:
            raise ValueError("COST_OR_SIZE_REAPPLICATION_FORBIDDEN")
        if row.get("type") not in {"FILL", "FEE", "FUNDING"}:
            raise ValueError("UNSUPPORTED_LEDGER_EVENT_OR_EXTERNAL_FLOW")
    positions: dict[str, dict[str, Any]] = {}
    closed: set[str] = set()
    realized = fees = funding = Decimal(0)
    pointer = 0
    snapshots = []
    last_snapshot = start - 1
    for sample in price_snapshots:
        stamp = _timestamp(sample.get("ts_ms"), "snapshot_ts_ms")
        if _decimal(sample.get("external_flow_usdt", 0), "external_flow_usdt") != 0:
            raise ValueError("EXTERNAL_FLOW_REQUIRES_UNITIZATION")
        if stamp <= last_snapshot or stamp < start:
            raise ValueError("SNAPSHOT_NOT_CHRONOLOGICAL")
        last_snapshot = stamp
        while pointer < len(events) and events[pointer]["ts_ms"] <= stamp:
            row = events[pointer]
            pointer += 1
            kind = row["type"]
            if kind == "FEE":
                amount = _decimal(row.get("amount_usdt"), "amount_usdt")
                if amount < 0:
                    raise ValueError("NEGATIVE_FEE")
                fees += amount
            elif kind == "FUNDING":
                symbol = _required_text(row, "symbol")
                if (
                    _timestamp(row.get("settlement_ts_ms"), "settlement_ts_ms")
                    != row["ts_ms"]
                ):
                    raise ValueError("FUNDING_SETTLEMENT_CLOCK_MISMATCH")
                if not any(p["symbol"] == symbol for p in positions.values()):
                    raise ValueError("FUNDING_WITHOUT_HELD_POSITION")
                funding += _decimal(row.get("amount_usdt"), "amount_usdt")
            else:
                episode = _required_text(row, "position_episode_id")
                symbol = _required_text(row, "symbol")
                side = row.get("side")
                if isinstance(side, bool) or side not in (-1, 1):
                    raise ValueError("INVALID_SIDE")
                qty = _decimal(row.get("qty_base"), "qty_base", positive=True)
                price = _decimal(row.get("fill_price"), "fill_price", positive=True)
                fee = _decimal(row.get("fee_usdt"), "fee_usdt")
                if fee < 0:
                    raise ValueError("NEGATIVE_FEE")
                fees += fee
                if row.get("effect") == "OPEN":
                    if episode in closed:
                        raise ValueError("CLOSED_EPISODE_CANNOT_REOPEN")
                    position = positions.get(episode)
                    if position is None:
                        positions[episode] = {
                            "position_episode_id": episode,
                            "symbol": symbol,
                            "side": side,
                            "remaining_qty_base": qty,
                            "avg_entry_price": price,
                        }
                    else:
                        if position["symbol"] != symbol or position["side"] != side:
                            raise ValueError("POSITION_BINDING_CHANGED")
                        old = position["remaining_qty_base"]
                        position["avg_entry_price"] = (
                            old * position["avg_entry_price"] + qty * price
                        ) / (old + qty)
                        position["remaining_qty_base"] += qty
                elif row.get("effect") == "CLOSE":
                    position = positions.get(episode)
                    if (
                        position is None
                        or position["symbol"] != symbol
                        or position["side"] != side
                    ):
                        raise ValueError("CLOSE_POSITION_BINDING_MISSING")
                    if qty > position["remaining_qty_base"]:
                        raise ValueError("OVERCLOSE")
                    realized += side * qty * (price - position["avg_entry_price"])
                    position["remaining_qty_base"] -= qty
                    if not position["remaining_qty_base"]:
                        del positions[episode]
                        closed.add(episode)
                else:
                    raise ValueError("FILL_EFFECT_REQUIRED")
        snapshots.append(
            {
                "ts_ms": stamp,
                "realized_gross_cum_usdt": str(realized),
                "fees_cum_usdt": str(fees),
                "funding_received_cum_usdt": str(funding),
                "positions": [
                    {k: str(v) if isinstance(v, Decimal) else v for k, v in p.items()}
                    for p in positions.values()
                ],
                "prices": copy.deepcopy(sample.get("prices")),
                "external_flow_usdt": 0,
            }
        )
    if pointer != len(events):
        raise ValueError("LEDGER_EXTENDS_AFTER_LAST_SNAPSHOT")
    value = value_account_snapshots(
        snapshots,
        initial_cash_usdt=initial_cash_usdt,
        start_ts_ms=start,
        price_basis=price_basis,
    )
    return {
        "schema": SCHEMA,
        "snapshots": snapshots,
        "valuation": value,
        "authority": dict(AUTHORITY),
        "economics_claim": "VALUATION_ONLY_NOT_STRATEGY_BENCHMARK",
        "clock_semantics": "RETROSPECTIVE_EVENT_TIME_NOT_ASOF_CAUSAL_FEATURE",
        "input_execution_evidence": sorted(
            {
                str(r.get("execution_evidence", "UNSPECIFIED_INPUT_EVIDENCE"))
                for r in events
                if r["type"] == "FILL"
            }
        ),
        "unclosed_position_episodes": sorted(positions),
        "closed_position_episodes": sorted(closed),
    }
