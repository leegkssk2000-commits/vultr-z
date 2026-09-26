"""Complete configured Noise-Area research model; never an order service.

The selected source base uses opposite-band decisions at half-hour clocks.
Crypto UTC sessions, fractional base sizing and causal next-open execution are
explicit transfer hypotheses. Native SPY replication is not claimed.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pandas as pd

from backend.research.rebuild import scalp7_exact25_session_v1 as source
from backend.research.rebuild.scalp7_implementation_contract_v1 import (
    AUTHORITY,
    _decimal,
    _timestamp,
    validate_rules,
)

MINUTE = 60_000
DAY = 1440 * MINUTE
MODEL_ID = "NOISE_OPPOSITE_BAND_UTC30_RESEARCH_V1"
SOURCE_URL = source.SOURCES["S310"]


def noise_config(symbol: str) -> dict[str, Any]:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("SYMBOL_REQUIRED")
    return {
        "model_id": MODEL_ID,
        "strategy_id": "trend_rider",
        "aliases": ["session_bias"],
        "symbol": symbol,
        "timeframe_min": 30,
        "mode_id": "noise_area_paper14_v1",
        "noise_stop_mode": "OPPOSITE_BAND",
        "session_source": {
            "source_ref": "DECLARED_UTC_24H_SESSION_V1",
            "timezone": "UTC",
            "market": "CRYPTO_UTC_RESEARCH",
        },
        "clock_hypothesis_id": "NOISE_UTC24H_TRANSFER_V1",
        "qty_policy": "FRACTIONAL_BASE_SESSION_START_EQUITY_DIV_OPEN",
        "entry_fill_policy": "NEXT_MINUTE_OPEN_ALL_REMAINING_MARKET_MODEL",
        "reversal_policy": "CLOSE_ACK_THEN_OPEN_AT_NEXT_AVAILABLE_MINUTE",
        "eod_policy": "PREDECLARED_UTC_BOUNDARY_NEXT_OPEN",
        "funding_policy": "GENUINE_SETTLEMENT_RECEIPTS_REQUIRED_FOR_PERPETUAL",
        "volume_policy": "NOT_USED_PRICE_ONLY_BASE_MODEL",
    }


def _config(config: dict[str, Any]) -> dict[str, Any]:
    symbol = config.get("symbol")
    if not isinstance(symbol, str):
        raise ValueError("SYMBOL_REQUIRED")
    expected = noise_config(symbol)
    if config != expected:
        raise ValueError("FIXED_NOISE_MODEL_CONFIG_REQUIRED")
    return expected


def model_spec() -> dict[str, Any]:
    rules = [
        source._rule(
            "noise_opposite_band_source",
            "14 complete prior sessions, same-slot absolute open-to-close moves; "
            "gap-adjusted upper/lower boundaries; 30minute decisions; hold until "
            "opposite boundary then reverse; end-session flat",
            "session / price / minutes",
            "S310",
            "paper20250922_section3_opposite_band_base",
        ),
        source._rule(
            "noise_source_capital",
            "100percent session-start equity divided by session opening price; "
            "source equity implementation rounds down whole shares",
            "account equity / price",
            "S310",
            "paper20250922_section3_pp8_9_base_sizing",
        ),
        source._hypothesis(
            "noise_crypto_transfer",
            "UTC00:00-24:00 sessions, 30minute bars, fractional base quantity "
            "without exchange-lot claim; prior14 complete calendar days. "
            "No volume or VWAP use, no native-SPY replication claim",
            "NOISE_UTC24H_TRANSFER_V1",
        ),
        source._hypothesis(
            "noise_execution_completion",
            "Decisions use completed available bars; next minute open market "
            "model only. Reversal opens after close acknowledgment. EOD was "
            "scheduled before entry and executes at UTC boundary open. "
            "Missing minute while owned blocks ownership, no invented fill",
            "NOISE_ACKNOWLEDGED_NEXT_OPEN_V1",
        ),
        source._hypothesis(
            "noise_account_completion",
            "One symbol per standalone finite-equity sleeve. Session quantity "
            "is fixed until EOD; no reinvestment inside session; nonpositive "
            "cash blocks new sessions. Full-fill receipts only. Explicit "
            "fees and genuine perpetual funding affect next session equity",
            "NOISE_FINITE_SINGLE_SYMBOL_SLEEVE_V1",
        ),
    ]
    return {
        "model_id": MODEL_ID,
        "strategy_id": "trend_rider",
        "aliases": ["session_bias"],
        "complete_configured_model": True,
        "native_source_strategy_certified": False,
        "execution_mode": "DECISION_TARGET_NEXT_OPEN",
        "rules": rules,
        "rule_digest": validate_rules(rules),
        "source_version": "2025-09-22 paper, section3 opposite-band base",
        "source_locator": SOURCE_URL,
        "risk_policy": "SOURCE_OPPOSITE_BAND_ONLY_AT_30M_AND_SCHEDULED_EOD",
        "hard_intrabar_stop": None,
        "take_profit": None,
        "generic_max_hold": None,
        "new_full_runs": 0,
        "economics": "NOT_RUN",
        "authority": dict(AUTHORITY),
    }


def utc_sessions(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach declared calendar only; preserve every gap and original price."""
    if "price_type" in frame and not (frame.price_type == "last").all():
        raise ValueError("NOISE_LAST_PRICE_REQUIRED")
    x = source._frame(frame, 30)
    x = x.drop(columns=["_boundary"])
    if x.empty:
        return x
    starts = (x.open_ts_ms // DAY) * DAY
    if (x.close_ts_ms > starts + DAY).any():
        raise ValueError("BAR_STRADDLES_UTC_SESSION")
    x["session_open_ts_ms"] = starts
    x["session_close_ts_ms"] = starts + DAY
    x["session_known_ts_ms"] = starts
    x["session_index"] = starts // DAY
    x["session_id"] = starts.astype(str)
    return x


def noise_schedule(
    frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Actual price producer; no future equity or simulated exposure included."""
    cfg = _config(config)
    symbol = cfg["symbol"]
    if set(frames) != {symbol}:
        raise ValueError("ONE_SYMBOL_SLEEVE_REQUIRED")
    x = source._frame(utc_sessions(frames[symbol]), 30)
    if x.empty:
        return []
    sessions = source._session_rows(x, cfg)
    history: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for session_id, rows in sessions:
        first = rows[0]
        start, end = first["session_open_ts_ms"], first["session_close_ts_ms"]
        complete = first["open_ts_ms"] == start
        slots = {}
        for i, row in enumerate(rows):
            if i and (
                row["open_ts_ms"] != rows[i - 1]["close_ts_ms"]
                or row["segment_id"] != rows[i - 1]["segment_id"]
            ):
                complete = False
            slot = (row["close_ts_ms"] - start) // MINUTE
            slots[slot] = abs(row["close"] / first["open"] - 1)
            prior = history[-14:]
            eligible = (
                complete
                and len(prior) == 14
                and [p["index"] for p in prior]
                == list(range(first["session_index"] - 14, first["session_index"]))
                and all(
                    p["complete"] and slot in p["slots"] and p["known"] <= start
                    for p in prior
                )
            )
            sigma = sum(p["slots"][slot] for p in prior) / 14 if eligible else None
            upper = (
                max(first["open"], prior[-1]["close"]) * (1 + sigma)
                if sigma is not None
                else None
            )
            lower = (
                min(first["open"], prior[-1]["close"]) * (1 - sigma)
                if sigma is not None
                else None
            )
            decisions.append(
                {
                    "symbol": symbol,
                    "setup_ts_ms": int(row["close_ts_ms"]),
                    "feature_available_ts_ms": int(row["available_ts_ms"]),
                    "session_id": session_id,
                    "session_open_ts_ms": int(start),
                    "session_close_ts_ms": int(end),
                    "session_open_price": float(first["open"]),
                    "session_complete_prefix": complete,
                    "eligible": eligible,
                    "close": float(row["close"]),
                    "upper": upper,
                    "lower": lower,
                    "reference_session_count": len(prior),
                    "source_ref": SOURCE_URL,
                }
            )
        history.append(
            {
                "index": first["session_index"],
                "slots": slots,
                "close": rows[-1]["close"],
                "complete": complete and rows[-1]["close_ts_ms"] == end,
                "known": rows[-1]["available_ts_ms"],
            }
        )
    return decisions


class SessionTargetModel:
    """State advances from bound full-fill receipts, never virtual exposure."""

    def __init__(self, config: dict[str, Any], initial_cash_usdt: Any) -> None:
        self.config = _config(copy.deepcopy(config))
        self.symbol = self.config["symbol"]
        self.identity = MODEL_ID + ":" + self.symbol
        self.cash = _decimal(initial_cash_usdt, "initial_cash_usdt", positive=True)
        self.initial_cash = self.cash
        self.session: dict[str, Any] | None = None
        self.position: dict[str, Any] | None = None
        self.pending_orders: dict[str, dict[str, Any]] = {}
        self.ledger: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.seen_fills: set[str] = set()
        self.last_known = -1
        self.last_decision = -1
        self.sequence = 0
        self.reverse_target = 0
        self.max_entry_notional_equity_ratio = Decimal(0)
        self.state = "FLAT"

    def _event(self, reason: str, **fields: Any) -> None:
        self.events.append({"reason": reason, **fields})

    def mark_gap(self, reason: str = "MISSING_DETAIL_MINUTE") -> None:
        if self.position is not None or self.pending_orders:
            self.state = "UNRESOLVED"
            self._event(reason, ownership_retained=True)
        else:
            self._event(reason, ownership_retained=False)

    def _order(self, effect: str, side: int, known: int, reason: str) -> list[dict]:
        if self.session is None or self.state == "UNRESOLVED":
            return []
        self.sequence += 1
        active = ((known + MINUTE - 1) // MINUTE) * MINUTE
        end = self.session["end"]
        if effect == "OPEN":
            if active >= end or self.cash <= 0:
                return []
            qty = self.session["qty"]
            episode = self.identity + ":" + str(self.sequence)
        else:
            if self.position is None:
                return []
            qty = self.position["qty"]
            episode = self.position["episode"]
        if qty <= 0:
            return []
        order_id = self.identity + ":order:" + str(self.sequence)
        order = {
            "order_id": order_id,
            "identity": self.identity,
            "symbol": self.symbol,
            "side": side,
            "effect": effect,
            "qty_base": str(qty),
            "position_episode_id": episode,
            "order_kind": "NEXT_OPEN",
            "order_active_ts_ms": active,
            "expires_ts_ms": (
                min(active + MINUTE, end) if effect == "OPEN" else active + MINUTE
            ),
            "feature_available_ts_ms": known,
            "source_ref": SOURCE_URL,
            "reason": reason,
            "timing_basis": "HISTORICAL_MODEL",
        }
        self.pending_orders[order_id] = order
        return [copy.deepcopy(order)]

    def on_decision(self, decision: dict[str, Any]) -> list[dict]:
        if self.state == "UNRESOLVED":
            return []
        row = copy.deepcopy(decision)
        if row.get("symbol") != self.symbol:
            raise ValueError("DECISION_SYMBOL_MISMATCH")
        known = _timestamp(row.get("feature_available_ts_ms"), "decision_available")
        stamp = _timestamp(row.get("setup_ts_ms"), "decision_close")
        if known < stamp or stamp <= self.last_decision or known < self.last_known:
            raise ValueError("NONCAUSAL_OR_DUPLICATE_DECISION")
        start = _timestamp(row.get("session_open_ts_ms"), "session_start")
        end = _timestamp(row.get("session_close_ts_ms"), "session_end")
        if start % DAY or end != start + DAY or not start < stamp <= end:
            raise ValueError("FIXED_UTC_SESSION_REQUIRED")
        if stamp % (30 * MINUTE):
            raise ValueError("HALF_HOUR_DECISION_REQUIRED")
        if self.session is None or self.session["start"] != start:
            if self.position is not None or self.pending_orders:
                self.mark_gap("PREVIOUS_SESSION_OWNERSHIP_UNCLOSED")
                return []
            if not row.get("session_complete_prefix"):
                self._event("INCOMPLETE_SESSION_PREFIX")
                return []
            price = _decimal(
                row.get("session_open_price"), "session_open", positive=True
            )
            self.session = {
                "start": start,
                "end": end,
                "qty": max(self.cash, Decimal(0)) / price,
            }
            self.reverse_target = 0
        self.last_known, self.last_decision = known, stamp
        if known >= end or self.pending_orders:
            return []
        if not row.get("session_complete_prefix"):
            self.mark_gap("SOURCE_BAR_GAP")
            return []
        if not row.get("eligible"):
            return []
        upper = _decimal(row.get("upper"), "upper", positive=True)
        lower = _decimal(row.get("lower"), "lower")
        close = _decimal(row.get("close"), "close", positive=True)
        if lower > upper:
            raise ValueError("NOISE_BOUNDARY_ORDER_INVALID")
        side = 0 if self.position is None else self.position["side"]
        target = side
        if side == 0:
            target = 1 if close > upper else -1 if close < lower else 0
        elif side == 1 and close < lower:
            target = -1
        elif side == -1 and close > upper:
            target = 1
        if target == side:
            return []
        if side:
            self.reverse_target = target
            return self._order("CLOSE", side, known, "OPPOSITE_BAND")
        return self._order("OPEN", target, known, "NOISE_BREAKOUT")

    def on_clock(self, ts_ms: int) -> list[dict]:
        stamp = _timestamp(ts_ms, "clock")
        if self.state == "UNRESOLVED" or self.session is None:
            return []
        if stamp < self.session["end"]:
            return []
        if stamp > self.session["end"]:
            if self.position is not None or self.pending_orders:
                self.mark_gap("MISSED_SCHEDULED_EOD_BOUNDARY")
            return []
        self.reverse_target = 0
        for order_id, order in list(self.pending_orders.items()):
            if order["effect"] == "OPEN":
                del self.pending_orders[order_id]
                self._event("EOD_CANCEL_UNFILLED_ENTRY", order_id=order_id)
        if self.position is None or any(
            o["effect"] == "CLOSE" for o in self.pending_orders.values()
        ):
            return []
        return self._order("CLOSE", self.position["side"], stamp, "SCHEDULED_EOD")

    def record_fill(self, receipt: dict[str, Any]) -> list[dict]:
        if self.state == "UNRESOLVED":
            raise ValueError("UNRESOLVED_OWNERSHIP_RETAINED")
        row = copy.deepcopy(receipt)
        order_id = row.get("order_id")
        if order_id not in self.pending_orders:
            raise ValueError("UNKNOWN_OR_CANCELLED_ORDER")
        order = self.pending_orders[order_id]
        stamp = _timestamp(row.get("ts_ms"), "fill_ts")
        known = _timestamp(row.get("available_ts_ms"), "fill_available")
        if (
            known < stamp
            or known < self.last_known
            or (self.ledger and stamp < self.ledger[-1]["ts_ms"])
        ):
            raise ValueError("NONCAUSAL_FILL_RECEIPT")
        if not order["order_active_ts_ms"] <= stamp < order["expires_ts_ms"]:
            raise ValueError("FILL_OUTSIDE_ACTIVATION_WINDOW")
        for key in ("symbol", "effect", "position_episode_id", "side"):
            if row.get(key) != order[key] or (
                key == "side" and isinstance(row.get(key), bool)
            ):
                raise ValueError("FILL_BINDING_MISMATCH:" + key)
        fill_id = row.get("fill_id")
        if not isinstance(fill_id, str) or not fill_id or fill_id in self.seen_fills:
            raise ValueError("UNIQUE_FILL_ID_REQUIRED")
        if not row.get("source_ref") or row.get("execution_evidence") not in (
            "MODEL_NOT_OBSERVED",
            "OBSERVED_FILL_RECEIPT",
        ):
            raise ValueError("EXPLICIT_EXECUTION_EVIDENCE_REQUIRED")
        qty = _decimal(row.get("qty_base"), "qty", positive=True)
        price = _decimal(row.get("fill_price"), "fill_price", positive=True)
        fee = _decimal(row.get("fee_usdt"), "fee")
        if fee < 0 or qty != Decimal(order["qty_base"]):
            raise ValueError("BOUND_FULL_FILL_AND_NONNEGATIVE_FEE_REQUIRED")
        if "slippage_usdt" in row or "leverage" in row:
            raise ValueError("COST_OR_SIZE_REAPPLICATION_FORBIDDEN")
        if order["effect"] == "OPEN":
            if self.position is not None:
                raise ValueError("OPEN_WHILE_POSITION_OWNED")
            if self.cash <= 0:
                raise ValueError("NONPOSITIVE_EQUITY_BLOCKS_OPEN")
            notional = qty * price
            ratio = notional / self.cash
            self.max_entry_notional_equity_ratio = max(
                self.max_entry_notional_equity_ratio, ratio
            )
            row["entry_notional_usdt"] = str(notional)
            row["entry_notional_equity_ratio"] = str(ratio)
            self.position = {
                "episode": order["position_episode_id"],
                "qty": qty,
                "price": price,
                "side": order["side"],
            }
            self.state = "ACTIVE"
        else:
            if (
                self.position is None
                or self.position["episode"] != order["position_episode_id"]
            ):
                raise ValueError("CLOSE_WITHOUT_BOUND_POSITION")
            self.cash += order["side"] * qty * (price - self.position["price"])
            self.position = None
            self.state = "FLAT"
        self.cash -= fee
        self.seen_fills.add(fill_id)
        self.last_known = known
        del self.pending_orders[order_id]
        self.ledger.append(
            {
                **row,
                "type": "FILL",
                "identity": self.identity,
                "qty_base": str(qty),
                "fill_price": str(price),
                "fee_usdt": str(fee),
                "authority": dict(AUTHORITY),
            }
        )
        if order["effect"] == "CLOSE" and self.reverse_target:
            target, self.reverse_target = self.reverse_target, 0
            return self._order("OPEN", target, known, "ACKNOWLEDGED_REVERSAL")
        return []

    def record_cash_event(self, event: dict[str, Any]) -> None:
        row = copy.deepcopy(event)
        stamp = _timestamp(row.get("ts_ms"), "cash_event_ts")
        known = _timestamp(row.get("available_ts_ms"), "cash_event_available")
        event_id = row.get("event_id")
        if (
            row.get("type") != "FUNDING"
            or row.get("symbol") != self.symbol
            or row.get("settlement_ts_ms") != stamp
            or self.position is None
            or known < stamp
            or known < self.last_known
            or (self.ledger and stamp < self.ledger[-1]["ts_ms"])
            or self.state == "UNRESOLVED"
            or not isinstance(event_id, str)
            or not event_id
            or event_id in self.seen_fills
            or not row.get("source_ref")
        ):
            raise ValueError("CAUSAL_HELD_POSITION_FUNDING_RECEIPT_REQUIRED")
        amount = _decimal(row.get("amount_usdt"), "funding_amount")
        self.cash += amount
        self.last_known = known
        self.seen_fills.add(event_id)
        self.ledger.append({**row, "amount_usdt": str(amount)})

    def finish(self) -> dict[str, Any]:
        return {
            "model_id": MODEL_ID,
            "state": self.state,
            "ledger": copy.deepcopy(self.ledger),
            "events": copy.deepcopy(self.events),
            "cash_usdt": str(self.cash),
            "initial_cash_usdt": str(self.initial_cash),
            "pending_orders": copy.deepcopy(list(self.pending_orders.values())),
            "unclosed_position": (
                None
                if self.position is None
                else {
                    k: str(v) if isinstance(v, Decimal) else copy.deepcopy(v)
                    for k, v in self.position.items()
                }
            ),
            "max_entry_notional_equity_ratio": str(
                self.max_entry_notional_equity_ratio
            ),
            "capital_policy": "LINEAR_SLEEVE_FIXED_SESSION_QTY",
            "broker_margin_liquidation": "UNKNOWN_NOT_SIMULATED",
            "complete_configured_model": True,
            "native_source_strategy_certified": False,
            "economics_claim": "RECEIPT_ACCOUNT_STATE_NOT_BENCHMARK",
            "authority": dict(AUTHORITY),
        }


PORTFOLIO_MODEL_ID = MODEL_ID + "_FIXED_SLEEVES"
CANONICAL_SYMBOLS = (
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "XRP-USDT",
    "LINK-USDT",
    "DOGE-USDT",
)


def noise_portfolio_config(symbols: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Universe is explicit and frozen by caller; no ranking or selection."""
    names = list(symbols)
    if (
        not names
        or any(not isinstance(s, str) or not s.strip() for s in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("EXPLICIT_UNIQUE_SYMBOL_UNIVERSE_REQUIRED")
    names = sorted(names)
    return {
        "model_id": PORTFOLIO_MODEL_ID,
        "strategy_id": "trend_rider",
        "aliases": ["session_bias"],
        "symbols": names,
        "timeframe_min": 30,
        "allocation_policy": "EQUAL_INITIAL_INDEPENDENT_SLEEVES_NO_RENORMALIZATION",
        "symbol_configs": {s: noise_config(s) for s in names},
        "hypothesis_id": "NOISE_FIXED_EQUAL_SLEEVES_V1",
        "fusion_classification": "SAME_MODEL_MULTI_SYMBOL_NOT_B_BY_B",
    }


def portfolio_spec() -> dict[str, Any]:
    spec = model_spec()
    spec["model_id"] = PORTFOLIO_MODEL_ID
    spec["rules"].append(
        source._hypothesis(
            "noise_equal_independent_sleeves",
            "Split initial research capital equally over the entire frozen universe. "
            "Each symbol keeps its own realized equity and session-start quantity. "
            "No cross-symbol risk transfer, renormalization or symbol ranking. "
            "Aliases and symbols do not create independent material strategies.",
            "NOISE_FIXED_EQUAL_SLEEVES_V1",
        )
    )
    spec["rule_digest"] = validate_rules(spec["rules"])
    return spec


def _portfolio_config(config: dict[str, Any]) -> dict[str, Any]:
    expected = noise_portfolio_config(config.get("symbols", []))
    if config != expected:
        raise ValueError("FIXED_NOISE_PORTFOLIO_CONFIG_REQUIRED")
    return expected


def noise_portfolio_schedule(
    frames: dict[str, pd.DataFrame], config: dict[str, Any]
) -> list[dict[str, Any]]:
    cfg = _portfolio_config(config)
    if set(frames) != set(cfg["symbols"]):
        raise ValueError("ENTIRE_FROZEN_UNIVERSE_REQUIRED")
    decisions = []
    for symbol in cfg["symbols"]:
        decisions.extend(
            noise_schedule({symbol: frames[symbol]}, cfg["symbol_configs"][symbol])
        )
    return sorted(
        decisions,
        key=lambda r: (r["feature_available_ts_ms"], r["symbol"], r["setup_ts_ms"]),
    )


class NoisePortfolioTargetModel:
    """Same configured model across fixed independent symbol sleeves."""

    def __init__(self, config: dict[str, Any], initial_cash_usdt: Any) -> None:
        self.config = _portfolio_config(copy.deepcopy(config))
        self.initial_cash = _decimal(initial_cash_usdt, "initial_cash", positive=True)
        allocation = self.initial_cash / len(self.config["symbols"])
        self.models = {
            symbol: SessionTargetModel(cfg, allocation)
            for symbol, cfg in self.config["symbol_configs"].items()
        }
        self.identity = PORTFOLIO_MODEL_ID

    @property
    def pending_orders(self) -> dict[str, dict[str, Any]]:
        return {
            order_id: order
            for model in self.models.values()
            for order_id, order in model.pending_orders.items()
        }

    @property
    def cash(self) -> Decimal:
        return sum((m.cash for m in self.models.values()), Decimal(0))

    @property
    def state(self) -> str:
        if any(m.state == "UNRESOLVED" for m in self.models.values()):
            return "UNRESOLVED"
        if any(m.position is not None for m in self.models.values()):
            return "ACTIVE"
        return "PENDING" if self.pending_orders else "FLAT"

    def _model(self, symbol: Any) -> SessionTargetModel:
        if symbol not in self.models:
            raise ValueError("SYMBOL_OUTSIDE_FROZEN_UNIVERSE")
        return self.models[symbol]

    def on_decision(self, decision: dict[str, Any]) -> list[dict]:
        return self._model(decision.get("symbol")).on_decision(decision)

    def on_clock(self, ts_ms: int) -> list[dict]:
        return [
            order for model in self.models.values() for order in model.on_clock(ts_ms)
        ]

    def record_fill(self, receipt: dict[str, Any]) -> list[dict]:
        return self._model(receipt.get("symbol")).record_fill(receipt)

    def record_cash_event(self, event: dict[str, Any]) -> None:
        self._model(event.get("symbol")).record_cash_event(event)

    def mark_gap(
        self, reason: str = "MISSING_DETAIL_MINUTE", symbol: str | None = None
    ) -> None:
        if symbol is not None:
            self._model(symbol).mark_gap(reason)
        else:
            for model in self.models.values():
                model.mark_gap(reason)

    def finish(self) -> dict[str, Any]:
        sleeves = {s: m.finish() for s, m in self.models.items()}
        events = [
            {**event, "symbol": s}
            for s, report in sleeves.items()
            for event in report["events"]
        ]
        ledger = [row for report in sleeves.values() for row in report["ledger"]]
        ledger.sort(key=lambda r: (r["ts_ms"], r["symbol"], r["available_ts_ms"]))
        return {
            "model_id": PORTFOLIO_MODEL_ID,
            "state": self.state,
            "ledger": ledger,
            "events": events,
            "cash_usdt": str(self.cash),
            "initial_cash_usdt": str(self.initial_cash),
            "sleeves": sleeves,
            "pending_orders": list(self.pending_orders.values()),
            "unclosed_position": {
                s: r["unclosed_position"]
                for s, r in sleeves.items()
                if r["unclosed_position"] is not None
            },
            "capital_policy": "LINEAR_SLEEVE_FIXED_SESSION_QTY",
            "allocation_policy": self.config["allocation_policy"],
            "complete_configured_model": True,
            "native_source_strategy_certified": False,
            "broker_margin_liquidation": "UNKNOWN_NOT_SIMULATED",
            "economics_claim": "RECEIPT_ACCOUNT_STATE_NOT_BENCHMARK",
            "authority": dict(AUTHORITY),
        }
