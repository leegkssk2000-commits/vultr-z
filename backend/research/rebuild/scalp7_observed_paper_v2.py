"""Observed-quote Scalp7 paper execution. No exchange order interface.

Signals enter at the first new bid/ask observation after the actual decision.
Stop/target/lifecycle triggers fill only on a later request, never past OHLC.
Sparse quote observations are not complete tick paths or exchange fills.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import time
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from backend.research.rebuild.economic7_canonical_history_v1 import (
    atomic_json,
    immutable_bytes,
    json_bytes,
    public_fetch,
)
from backend.research.rebuild.scalp7_source_data_v2 import SYMBOLS, sha_file
from backend.research.rebuild.economic7_bingx_raw_capture_v1 import (
    digest as micro_digest,
)

QUOTE_URL = "https://open-api.bingx.com/openApi/swap/v2/quote/depth"
PROFILE = "POST_DECISION_OBSERVED_QUOTE_TRIGGER_THEN_LATER_QUOTE_V2"
MAX_STATE_BYTES = 64 * 1024 * 1024


class PaperError(RuntimeError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def _num(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PaperError("NONNUMERIC") from exc
    if not math.isfinite(result):
        raise PaperError("NONFINITE")
    return result


def _ms(value: Any) -> int:
    result = _num(value)
    if result != math.floor(result) or result < 0:
        raise PaperError("NONINTEGER_OR_NEGATIVE_TIME")
    return int(result)


def _legs(signal: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = signal.get("legs")
    if raw:
        legs = [dict(x) for x in raw]
    else:
        legs = [{"symbol": signal["symbol"], "side": signal["side"], "weight": 1.0}]
    if any(x["symbol"] not in SYMBOLS or x["side"] not in (-1, 1) for x in legs):
        raise PaperError("LEG_IDENTITY_OR_SIDE")
    if len({x["symbol"] for x in legs}) != len(legs):
        raise PaperError("DUPLICATE_LEG")
    if (
        any(_num(x["weight"]) <= 0 for x in legs)
        or abs(sum(_num(x["weight"]) for x in legs) - 1) > 1e-9
    ):
        raise PaperError("GROSS_ONE_LEG_WEIGHTS")
    return legs


def _owner(signal: Mapping[str, Any]) -> str:
    return (
        str(signal["identity"])
        + ":"
        + ("PAIR_GLOBAL" if signal.get("legs") else str(signal["symbol"]))
    )


def normalize_quote(
    raw: bytes, symbol: str, requested: int, received: int
) -> dict[str, Any]:
    """Only best nonzero displayed prices; no volume-unit or capacity inference."""
    requested, received = _ms(requested), _ms(received)
    if symbol not in SYMBOLS or received < requested:
        raise PaperError("QUOTE_IDENTITY_OR_CLOCK")
    payload = json.loads(raw)
    if (
        not isinstance(payload, dict)
        or str(payload.get("code")) != "0"
        or not isinstance(payload.get("data"), dict)
    ):
        raise PaperError("QUOTE_RESPONSE_SCHEMA")
    data = payload["data"]
    if data.get("symbol", symbol) != symbol:
        raise PaperError("QUOTE_SYMBOL_MISMATCH")
    prices: dict[str, list[float]] = {}
    for name in ("bids", "asks"):
        levels = data.get(name)
        if not isinstance(levels, list) or not levels:
            raise PaperError("QUOTE_EMPTY_BOOK")
        values = []
        for level in levels:
            if not isinstance(level, list) or len(level) < 2:
                raise PaperError("QUOTE_LEVEL_SCHEMA")
            price, quantity = _num(level[0]), _num(level[1])
            if price <= 0 or quantity < 0:
                raise PaperError("QUOTE_LEVEL_RANGE")
            if quantity > 0:
                values.append(price)
        if not values:
            raise PaperError("QUOTE_EMPTY_NONZERO_BOOK")
        prices[name] = values
    bid, ask = max(prices["bids"]), min(prices["asks"])
    if bid >= ask:
        raise PaperError("QUOTE_CROSSED_BOOK")
    source_times = [_ms(data[k]) for k in ("T", "timestamp", "time") if k in data]
    if source_times and (len(set(source_times)) != 1 or source_times[0] > received):
        raise PaperError("QUOTE_SOURCE_TIME_INVALID")
    quote = {
        "symbol": symbol,
        "bid": bid,
        "ask": ask,
        "requested_at_ms": requested,
        "received_at_ms": received,
        "source_ts_ms": source_times[0] if source_times else None,
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "source": QUOTE_URL,
        "quantity_unit_used": False,
        "capacity_proven": False,
    }
    quote["quote_id"] = digest(quote)
    return quote


def quote_request(
    out: Path, symbol: str, fetch: Callable[[str], tuple[int, bytes]] = public_fetch
) -> dict[str, Any]:
    requested = int(time.time() * 1000)
    query = {"symbol": symbol, "limit": 5, "timestamp": requested}
    url = QUOTE_URL + "?" + urllib.parse.urlencode(query)
    status, raw = fetch(url)
    received = int(time.time() * 1000)
    stem = out / "quotes" / symbol / str(time.time_ns())
    body = stem.with_suffix(".body")
    immutable_bytes(body, raw)
    receipt = {
        "source": QUOTE_URL,
        "query": query,
        "url": url,
        "requested_at_ms": requested,
        "received_at_ms": received,
        "http_status": status,
        "body_path": str(body),
        "body_sha256": hashlib.sha256(raw).hexdigest(),
    }
    receipt_path = stem.with_suffix(".receipt.json")
    immutable_bytes(receipt_path, json_bytes(receipt))
    if status != 200:
        raise PaperError("QUOTE_HTTP:" + str(status))
    quote = normalize_quote(raw, symbol, requested, received)
    quote.update(receipt_path=str(receipt_path), receipt_sha256=sha_file(receipt_path))
    return quote


def empty_state(freeze_sha: str) -> dict[str, Any]:
    return {
        "schema": "scalp7.observed_paper.state.v2",
        "freeze_sha256": freeze_sha,
        "pending": {},
        "positions": {},
        "seen": {},
        "trades": [],
        "events": [],
        "signal_cursors": {},
        "last_poll_ms": 0,
    }


class ObservedPaper:
    """Deterministic state transitions, supplied actual observations only."""

    def __init__(
        self,
        state: dict[str, Any],
        config: Mapping[str, Any],
        costs: Mapping[str, float],
        modules: Mapping[str, Any],
    ):
        self.state, self.config, self.costs, self.modules = (
            state,
            config,
            costs,
            modules,
        )
        for key in (
            "fresh_start_ms",
            "max_quote_request_ms",
            "max_pair_skew_ms",
            "max_quote_gap_ms",
        ):
            if _ms(config[key]) <= 0:
                raise PaperError("PAPER_CLOCK_POLICY_REQUIRED:" + key)
        if any(_num(value) <= 0 for value in costs.values()):
            raise PaperError("POSITIVE_FROZEN_RESERVE_REQUIRED")

    def _event(self, kind: str, now: int, **data: Any) -> None:
        self.state["events"].append({"kind": kind, "observed_at_ms": now, **data})

    def admit(self, wrapper: Mapping[str, Any], now_ms: int) -> None:
        signal = copy.deepcopy(wrapper["signal"])
        identity = str(signal["identity"])
        key = str(
            wrapper.get("opportunity_key") or signal.get("setup_id") or digest(signal)
        )
        if key in self.state["seen"]:
            return
        self.state["seen"][key] = "OBSERVED"
        tf = _ms(signal["timeframe_min"])
        observed = max(
            _ms(signal["signal_ts_ms"]),
            _ms(
                wrapper.get(
                    "observed_at_ms",
                    wrapper.get(
                        "strategy_observed_at_ms", wrapper.get("recorded_at_ms", 0)
                    ),
                )
            ),
        )
        if identity not in self.modules or tf not in (15, 30):
            raise PaperError("FROZEN_IDENTITY_OR_SCALP_TIMEFRAME")
        if observed > now_ms:
            raise PaperError("FUTURE_SIGNAL_RECEIPT")
        if observed < int(self.config["fresh_start_ms"]):
            self.state["seen"][key] = "PRE_PAPER_FREEZE_NO_CREDIT"
            return
        eligibility = wrapper.get("execution_eligibility")
        if eligibility == "MISSED_SUPERSEDED_DECISION_OBSERVATION_ONLY":
            self.state["seen"][key] = eligibility
            self._event("REJECT_SUPERSEDED_DECISION", now_ms, key=key)
            return
        if eligibility not in (None, "CURRENT_DECISION_BAR_REQUIRES_NEW_QUOTE"):
            raise PaperError("UNKNOWN_SIGNAL_EXECUTION_ELIGIBILITY")
        _legs(signal)
        if not signal.get("legs") and _num(signal["stop_price"]) <= 0:
            raise PaperError("INITIAL_STOP_INVALID")
        for field in ("take_profit_r", "partial_take_profit_r"):
            if signal.get(field) is not None and _num(signal[field]) <= 0:
                raise PaperError("TARGET_R_INVALID")
        if (
            signal.get("partial_take_profit_r") is not None
            and not 0 < _num(signal.get("partial_fraction")) < 1
        ):
            raise PaperError("PARTIAL_FRACTION_INVALID")
        if _ms(signal["max_hold_bars"]) < 1:
            raise PaperError("MAX_HOLD_INVALID")
        owner = _owner(signal)
        if owner in self.state["positions"] or owner in self.state["pending"]:
            self.state["seen"][key] = "POSITION_ALREADY_OWNED"
            self._event("REJECT", now_ms, key=key, reason="POSITION_ALREADY_OWNED")
            return
        interval = tf * 60_000
        due = observed + 1
        decision_close = _ms(
            wrapper.get(
                "decision_bar_close_ms", _ms(signal["signal_open_ts_ms"]) + interval
            )
        )
        if decision_close > observed:
            raise PaperError("UNAVAILABLE_DECISION_BAR")
        self.state["pending"][owner] = {
            "key": key,
            "signal": signal,
            "observed_at_ms": observed,
            "due_ms": due,
            "decision_bar_close_ms": decision_close,
            "signal_receipt_sha256": wrapper["record_sha256"],
        }
        self._event("WAIT_NEW_POST_DECISION_QUOTE", now_ms, key=key, due_ms=due)

    def _quotes(
        self, signal: Mapping[str, Any], quotes: Mapping[str, Any], now: int, after: int
    ) -> dict[str, Any] | None:
        names = [x["symbol"] for x in _legs(signal)]
        if any(name not in quotes for name in names):
            return None
        chosen = {name: quotes[name] for name in names}
        for name, quote in chosen.items():
            if quote["symbol"] != name:
                raise PaperError("QUOTE_SYMBOL_KEY_MISMATCH")
            requested, received = _ms(quote["requested_at_ms"]), _ms(
                quote["received_at_ms"]
            )
            if requested <= after or received > now or received < requested:
                return None
            if received - requested > int(self.config["max_quote_request_ms"]):
                return None
            if now - received > int(self.config["max_quote_request_ms"]):
                return None
            source = quote.get("source_ts_ms")
            if source is not None and (
                int(source) > received
                or received - int(source) > int(self.config["max_quote_request_ms"])
            ):
                return None
            if not 0 < _num(quote["bid"]) < _num(quote["ask"]):
                raise PaperError("QUOTE_PRICE_RANGE")
        stamps = [int(q["received_at_ms"]) for q in chosen.values()]
        if max(stamps) - min(stamps) > int(self.config["max_pair_skew_ms"]):
            return None
        return chosen

    @staticmethod
    def _prices(
        signal: Mapping[str, Any], quotes: Mapping[str, Any], entry: bool
    ) -> dict[str, float]:
        return {
            leg["symbol"]: float(
                quotes[leg["symbol"]]["ask" if (leg["side"] == 1) == entry else "bid"]
            )
            for leg in _legs(signal)
        }

    def _enter(
        self, owner: str, waiting: dict[str, Any], quotes: dict[str, Any], now: int
    ) -> None:
        signal = waiting["signal"]
        prices = self._prices(signal, quotes, True)
        entry_ts = max(int(q["received_at_ms"]) for q in quotes.values())
        mod = self.modules[signal["identity"]]
        stop, risk, entry = None, None, None
        if not signal.get("legs"):
            entry = prices[signal["symbol"]]
            stop = _num(signal["stop_price"])
            if hasattr(mod, "entry_update"):
                update = mod.entry_update(signal, entry)
                if update.get("reject"):
                    self._event(
                        "ENTRY_REJECT",
                        now,
                        key=waiting["key"],
                        reason=str(update.get("reason", update["reject"])),
                    )
                    del self.state["pending"][owner]
                    return
                stop = _num(update.get("stop_price", stop))
            risk = int(signal["side"]) * (entry - stop)
            if stop <= 0 or risk <= 0:
                self._event(
                    "ENTRY_REJECT",
                    now,
                    key=waiting["key"],
                    reason="OBSERVED_FILL_INVALIDATES_STOP",
                )
                del self.state["pending"][owner]
                return
        cost = sum(
            float(x["weight"]) * float(self.costs[x["symbol"]]) for x in _legs(signal)
        )
        interval = int(signal["timeframe_min"]) * 60_000
        position = {
            "key": waiting["key"],
            "signal": signal,
            "entry_price": entry,
            "entry_prices": prices,
            "side": signal.get("side", 0),
            "entry_ts_ms": entry_ts,
            "entry_quote_receipts": quotes,
            "entry_quote_ts_by_leg": {
                s: q["received_at_ms"] for s, q in quotes.items()
            },
            "initial_stop": stop,
            "stop_price": stop,
            "initial_risk": risk,
            "hold_bars": 0,
            "mfe_R": None if signal.get("legs") else 0.0,
            "mae_R": None if signal.get("legs") else 0.0,
            "remaining": 1.0,
            "realized_parts_bps": 0.0,
            "partials": [],
            "cost_bps": cost,
            "pending_exit": None,
            "pending_partial": None,
            "last_quote_ms": entry_ts,
            "last_quote_ids": {s: q["quote_id"] for s, q in quotes.items()},
            "next_lifecycle_open_ms": ((entry_ts + interval - 1) // interval)
            * interval,
            "max_hold_due_ms": entry_ts + interval * int(signal["max_hold_bars"]),
            "status": "OPEN_OBSERVED_PAPER",
            "signal_receipt_sha256": waiting["signal_receipt_sha256"],
            "actual_entry_delay_ms": entry_ts - int(signal["signal_ts_ms"]),
            "execution_profile": PROFILE,
        }
        self.state["positions"][owner] = position
        del self.state["pending"][owner]
        self._event(
            "PAPER_ENTRY",
            now,
            key=position["key"],
            entry_ts_ms=entry_ts,
            entry_prices=prices,
            quote_ids=position["last_quote_ids"],
        )

    def _gross(self, position: Mapping[str, Any], prices: Mapping[str, float]) -> float:
        return sum(
            float(x["weight"])
            * int(x["side"])
            * (prices[x["symbol"]] / position["entry_prices"][x["symbol"]] - 1)
            * 10_000
            for x in _legs(position["signal"])
        )

    def _close(
        self, owner: str, position: dict[str, Any], quotes: dict[str, Any], now: int
    ) -> None:
        prices = self._prices(position["signal"], quotes, False)
        gross = float(position["realized_parts_bps"]) + float(
            position["remaining"]
        ) * self._gross(position, prices)
        stamp = max(int(q["received_at_ms"]) for q in quotes.values())
        cost = float(position["cost_bps"])
        signal = position["signal"]
        position["hold_bars"] = max(
            int(position["hold_bars"]),
            (stamp - int(position["entry_ts_ms"]))
            // (int(signal["timeframe_min"]) * 60_000),
        )
        if not signal.get("legs"):
            move = (
                int(position["side"])
                * (prices[signal["symbol"]] - float(position["entry_price"]))
                / float(position["initial_risk"])
            )
            position["mfe_R"] = max(float(position["mfe_R"]), move)
            position["mae_R"] = max(float(position["mae_R"]), -move)
        row = {
            k: signal[k]
            for k in (
                "identity",
                "lane",
                "symbol",
                "timeframe_min",
                "signal_ts_ms",
                "signal_open_ts_ms",
            )
        }
        row.update(
            {
                "key": position["key"],
                "signal": signal,
                "side": signal.get("side", 0),
                "legs": signal.get("legs"),
                "entry_ts_ms": position["entry_ts_ms"],
                "exit_ts_ms": stamp,
                "outcome_available_ts_ms": now,
                "entry_prices": position["entry_prices"],
                "exit_prices": prices,
                "entry_quote_receipts": position["entry_quote_receipts"],
                "exit_quote_receipts": quotes,
                "exit_quote_ts_by_leg": {
                    s: q["received_at_ms"] for s, q in quotes.items()
                },
                "gross_bps": gross,
                "cost_bps": cost,
                "net_bps": gross - cost,
                "stress2x_cost_bps": 2 * cost,
                "stress2x_net_bps": gross - 2 * cost,
                "cost_semantics": "OBSERVED_BID_ASK_GROSS_MINUS_ADDITIONAL_FROZEN_REFERENCE_RESERVE_NOT_ACTUAL_FEES",
                "reason": position["pending_exit"]["reason"],
                "trigger": position["pending_exit"],
                "hold_bars": position["hold_bars"],
                "hold_minutes": (stamp - position["entry_ts_ms"]) / 60_000,
                "mfe_R": position["mfe_R"],
                "mae_R": position["mae_R"],
                "mfe_mae_semantics": "OBSERVED_POST_ENTRY_QUOTES_ONLY_SPARSE_PATH",
                "partials": position["partials"],
                "signal_receipt_sha256": position["signal_receipt_sha256"],
                "actual_entry_delay_ms": position["actual_entry_delay_ms"],
                "execution_profile": PROFILE,
                "evidence_kind": "GENUINE_FRESH_OBSERVED_QUOTE_PAPER",
                "account_or_exchange_fill": False,
                "capacity_or_slippage_proven": False,
                "promotion_authority": False,
                "order_authority": "BLOCKED",
                "live_authority": "BLOCKED",
            }
        )
        self.state["trades"].append(row)
        self._event("PAPER_CLOSE", now, key=position["key"], net_bps=row["net_bps"])
        del self.state["positions"][owner]

    def _trigger(self, position: dict[str, Any], reason: str, now: int) -> None:
        if position["pending_exit"] is None:
            position["pending_exit"] = {"reason": reason, "decision_ms": now}
            position["pending_partial"] = None
            self._event(
                "EXIT_TRIGGER_WAIT_LATER_QUOTE", now, key=position["key"], reason=reason
            )

    def _observe_open(
        self, owner: str, position: dict[str, Any], quotes: dict[str, Any], now: int
    ) -> None:
        stamp = max(int(q["received_at_ms"]) for q in quotes.values())
        if stamp - int(position["last_quote_ms"]) > int(
            self.config["max_quote_gap_ms"]
        ):
            position["status"] = "HOLD_UNRESOLVED_QUOTE_GAP"
            self._event(
                "HOLD", now, key=position["key"], reason="UNOBSERVED_QUOTE_PATH_GAP"
            )
            return
        if position["pending_exit"] is not None:
            if all(
                int(q["requested_at_ms"]) > int(position["pending_exit"]["decision_ms"])
                for q in quotes.values()
            ):
                self._close(owner, position, quotes, now)
            return
        prices = self._prices(position["signal"], quotes, False)
        partial = position["pending_partial"]
        if partial is not None and all(
            int(q["requested_at_ms"]) > int(partial["decision_ms"])
            for q in quotes.values()
        ):
            fraction = float(partial["fraction"])
            position["realized_parts_bps"] += fraction * self._gross(position, prices)
            position["remaining"] -= fraction
            position["partials"].append(
                {
                    "fraction": fraction,
                    "prices": prices,
                    "filled_at_ms": stamp,
                    "quote_receipts": quotes,
                    "trigger": partial,
                }
            )
            position["pending_partial"] = None
            position["partial_executed"] = True
        position["last_quote_ms"] = stamp
        position["last_quote_ids"] = {s: q["quote_id"] for s, q in quotes.items()}
        signal = position["signal"]
        if not signal.get("legs"):
            side = int(position["side"])
            px = prices[signal["symbol"]]
            move = (
                side
                * (px - float(position["entry_price"]))
                / float(position["initial_risk"])
            )
            position["mfe_R"] = max(float(position["mfe_R"]), move)
            position["mae_R"] = max(float(position["mae_R"]), -move)
            if side * (px - float(position["stop_price"])) <= 0:
                self._trigger(position, "OBSERVED_HARD_STOP", now)
            elif signal.get("take_profit_r") is not None and move >= float(
                signal["take_profit_r"]
            ):
                self._trigger(position, "OBSERVED_TAKE_PROFIT", now)
            elif (
                signal.get("partial_take_profit_r") is not None
                and move >= float(signal["partial_take_profit_r"])
                and not position.get("partial_executed")
                and position["pending_partial"] is None
            ):
                fraction = _num(signal["partial_fraction"])
                if not 0 < fraction < float(position["remaining"]):
                    raise PaperError("PARTIAL_FRACTION_INVALID")
                position["pending_partial"] = {
                    "fraction": fraction,
                    "decision_ms": now,
                    "reason": "OBSERVED_POST_ENTRY_PARTIAL_TARGET",
                }
        if now >= int(position["max_hold_due_ms"]):
            self._trigger(position, "OBSERVED_MAX_HOLD", now)

    def _parent_quote_update(
        self,
        mod: Any,
        position: dict[str, Any],
        bar: dict[str, Any],
        history: pd.DataFrame,
    ) -> dict[str, Any]:
        """Preserve closed-bar ATR/structure, bind path extrema to observed quotes."""
        signal = position["signal"]
        side = int(position["side"])
        interval = int(signal["timeframe_min"]) * 60_000
        opened = int(bar["open_ts_ms"])
        last = copy.deepcopy(position.get("_parent_control_state"))
        if last is None:
            last = {
                "atr": float(signal["meta"]["atr_at_signal"]),
                "close": float(signal["meta"]["close_at_signal"]),
                "open_ts_ms": int(signal["signal_open_ts_ms"]),
                "peak": float(position["entry_price"]),
                "trail": None,
                "segment_id": str(signal["segment_id"]),
            }
        quote_peak = float(position["entry_price"]) + side * float(
            position["mfe_R"]
        ) * float(position["initial_risk"])
        bridge = history.loc[
            (history.open_ts_ms > int(last["open_ts_ms"]))
            & (history.open_ts_ms < opened)
        ]
        for raw in bridge.to_dict("records"):
            row = mod._validate(pd.DataFrame([raw]), interval).iloc[0]
            if (
                int(row.open_ts_ms) >= int(position["entry_ts_ms"])
                or int(row.open_ts_ms) != int(last["open_ts_ms"]) + interval
                or str(row.segment_id) != last["segment_id"]
            ):
                raise PaperError("PARENT_PARTIAL_FEATURE_BRIDGE_GAP")
            tr = max(
                float(row.high - row.low),
                abs(float(row.high) - last["close"]),
                abs(float(row.low) - last["close"]),
            )
            last.update(
                atr=(13 * last["atr"] + tr) / 14,
                close=float(row.close),
                open_ts_ms=int(row.open_ts_ms),
                peak=quote_peak,
            )
            self._event(
                "PARTIAL_ENTRY_BAR_PARENT_FEATURE_ONLY",
                int(bar["available_ts_ms"]),
                key=position["key"],
                open_ts_ms=int(row.open_ts_ms),
            )
        position["_parent_control_state"] = last
        previous_trail = last["trail"]
        update = mod.exit_update(position, bar, history)
        current = position.get("_parent_control_state", {})
        if current.get("open_ts_ms") != opened:
            raise PaperError("PARENT_LIFECYCLE_STATE_NOT_ADVANCED")
        life = signal["meta"]["source_spec"]["lifecycle"]
        trail = previous_trail
        if not update.get("exit_next_open") and float(position["mfe_R"]) >= max(
            1.5, float(life["trail_activate_r"])
        ):
            candidate = quote_peak - side * float(life["trail_atr_mult"]) * float(
                current["atr"]
            )
            trail = (
                candidate
                if trail is None
                else max(trail, candidate) if side == 1 else min(trail, candidate)
            )
        update["next_stop"] = None
        if trail is not None and not update.get("exit_next_open"):
            update["next_stop"] = (
                max(float(position["stop_price"]), trail)
                if side == 1
                else min(float(position["stop_price"]), trail)
            )
        current.update(peak=quote_peak, trail=trail, result=dict(update))
        position["_parent_partial_done"] = bool(position.get("partial_executed"))
        return update

    def _lifecycle(
        self, position: dict[str, Any], by_symbol: Mapping[str, pd.DataFrame], now: int
    ) -> None:
        signal = position["signal"]
        mod = self.modules[signal["identity"]]
        if not hasattr(mod, "exit_update"):
            return
        names = [x["symbol"] for x in _legs(signal)]
        if any(name not in by_symbol for name in names):
            position["status"] = "HOLD_UNRESOLVED_CANDLE_SOURCE"
            return
        interval = int(signal["timeframe_min"]) * 60_000
        histories = {
            name: by_symbol[name]
            .loc[
                (by_symbol[name].available_ts_ms <= now)
                & (by_symbol[name].close_ts_ms <= now)
            ]
            .copy()
            for name in names
        }
        next_open = int(position["next_lifecycle_open_ms"])
        common = set.intersection(
            *(set(x.open_ts_ms.astype(int)) for x in histories.values())
        )
        future = sorted(t for t in common if t >= next_open)
        if future and future[0] != next_open:
            position["status"] = "HOLD_UNRESOLVED_CANDLE_GAP"
            self._event(
                "HOLD", now, key=position["key"], reason="MISSING_LIFECYCLE_CANDLE"
            )
            return
        for opened in future:
            if opened != int(position["next_lifecycle_open_ms"]):
                position["status"] = "HOLD_UNRESOLVED_CANDLE_GAP"
                return
            prefix = {
                name: x.loc[x.open_ts_ms <= opened].copy()
                for name, x in histories.items()
            }
            bars = {name: x.iloc[-1].to_dict() for name, x in prefix.items()}
            for name, history in prefix.items():
                continuity = history.loc[
                    history.open_ts_ms >= int(signal["signal_open_ts_ms"])
                ]
                if (
                    continuity.segment_id.nunique() != 1
                    or (continuity.open_ts_ms.diff().dropna() != interval).any()
                ):
                    position["status"] = "HOLD_UNRESOLVED_CANDLE_SEGMENT"
                    self._event(
                        "HOLD",
                        now,
                        key=position["key"],
                        reason="CANDLE_SEGMENT_CHANGED_OR_GAP",
                    )
                    return
            position["hold_bars"] = max(
                0, (opened + interval - int(position["entry_ts_ms"])) // interval
            )
            for bar in bars.values():
                bar["source_available_ts_ms"] = bar["available_ts_ms"]
                bar["available_ts_ms"] = now
            try:
                if signal.get("legs"):
                    update = mod.exit_update(position, bars, prefix)
                else:
                    name = names[0]
                    if hasattr(mod, "prepare_frames"):
                        prefix = mod.prepare_frames(prefix)
                    if (
                        signal["identity"]
                        == "scalp7_supertrend_native_impulse_pullback_30m_v2"
                    ):
                        saved = position.get(
                            "_scalp7_supertrend_state", signal["meta"]["native_state"]
                        )
                        native = mod.BandState(**{**saved, "seed": list(saved["seed"])})
                        bridge = prefix[name].loc[
                            (prefix[name].open_ts_ms > native.last_open_ts_ms)
                            & (prefix[name].open_ts_ms < opened)
                        ]
                        for raw in bridge.to_dict("records"):
                            feature_bar = mod._bar(raw)
                            if int(feature_bar["open_ts_ms"]) >= int(
                                position["entry_ts_ms"]
                            ) or not mod._contiguous(native, feature_bar):
                                raise PaperError(
                                    "SUPERTREND_PARTIAL_FEATURE_BRIDGE_GAP"
                                )
                            native = mod._step(native, feature_bar)
                            self._event(
                                "PARTIAL_ENTRY_BAR_NATIVE_FEATURE_ONLY",
                                now,
                                key=position["key"],
                                open_ts_ms=int(feature_bar["open_ts_ms"]),
                            )
                        position["_scalp7_supertrend_state"] = asdict(native)
                    if getattr(mod, "__name__", "").endswith(
                        ".scalp7_parent_controls_v2"
                    ):
                        update = self._parent_quote_update(
                            mod, position, bars[name], prefix[name]
                        )
                    else:
                        update = mod.exit_update(position, bars[name], prefix[name])
            except (ValueError, KeyError, TypeError, RuntimeError) as exc:
                position["status"] = "HOLD_UNRESOLVED_LIFECYCLE_BINDING"
                self._event("HOLD", now, key=position["key"], reason=str(exc))
                return
            if update.get("reason") == "DATA_GAP_HOLD":
                position["status"] = "HOLD_UNRESOLVED_NATIVE_STATE_GAP"
                self._event(
                    "HOLD", now, key=position["key"], reason="NATIVE_STATE_DATA_GAP"
                )
                return
            # Actual quote path alone can activate/fill partials. OHLC hints get no fill.
            if update.get("partial_fraction"):
                self._event(
                    "OHLC_PARTIAL_HINT_NO_FILL",
                    now,
                    key=position["key"],
                    observed_quote_partial_armed=position["pending_partial"]
                    is not None,
                )
            if update.get("next_stop") is not None:
                proposed = _num(update["next_stop"])
                if proposed <= 0:
                    raise PaperError("LIFECYCLE_STOP_INVALID")
                old = float(position["stop_price"])
                position["stop_price"] = (
                    max(old, proposed) if position["side"] == 1 else min(old, proposed)
                )
                self._event(
                    "STOP_ACTIVATED_AFTER_BAR_AVAILABILITY",
                    now,
                    key=position["key"],
                    stop_price=position["stop_price"],
                )
            position["next_lifecycle_open_ms"] = opened + interval
            if update.get("exit_next_open"):
                self._trigger(
                    position, str(update.get("reason", "OBSERVED_LIFECYCLE")), now
                )
                return
            if position["pending_exit"] is not None:
                return

    def step(
        self,
        quotes: Mapping[str, Any],
        frames: Mapping[int, Mapping[str, pd.DataFrame]],
        now_ms: int,
        observed_frames: Mapping[int, Mapping[str, pd.DataFrame]] | None = None,
    ) -> None:
        now = _ms(now_ms)
        if now < int(self.state["last_poll_ms"]):
            raise PaperError("PAPER_CLOCK_REVERSED")
        for owner, position in list(self.state["positions"].items()):
            if position["status"] != "OPEN_OBSERVED_PAPER":
                continue
            selected = self._quotes(
                position["signal"], quotes, now, int(position["last_quote_ms"])
            )
            if selected is None:
                if now - int(position["last_quote_ms"]) > int(
                    self.config["max_quote_gap_ms"]
                ):
                    position["status"] = "HOLD_UNRESOLVED_QUOTE_GAP"
                continue
            self._observe_open(owner, position, selected, now)
            if (
                owner in self.state["positions"]
                and position["status"] == "OPEN_OBSERVED_PAPER"
                and position["pending_exit"] is None
            ):
                self._lifecycle(
                    position,
                    frames.get(int(position["signal"]["timeframe_min"]), {}),
                    now,
                )
        for owner, waiting in list(self.state["pending"].items()):
            source = (observed_frames if observed_frames is not None else frames).get(
                int(waiting["signal"]["timeframe_min"]), {}
            )
            closes = []
            for frame in source.values():
                available = frame.loc[
                    (frame.available_ts_ms <= now) & (frame.close_ts_ms <= now)
                ]
                if not available.empty:
                    closes.append(int(available.close_ts_ms.max()))
            if not closes:
                continue
            latest_common_close = min(closes)
            if latest_common_close > int(waiting["decision_bar_close_ms"]):
                self._event(
                    "ENTRY_SUPERSEDED_BY_OBSERVED_DECISION_BAR",
                    now,
                    key=waiting["key"],
                    latest_common_close_ms=latest_common_close,
                )
                del self.state["pending"][owner]
                continue
            if latest_common_close < int(waiting["decision_bar_close_ms"]):
                continue
            if now < int(waiting["due_ms"]):
                continue
            selected = self._quotes(
                waiting["signal"],
                quotes,
                now,
                max(int(waiting["due_ms"]) - 1, int(waiting["observed_at_ms"])),
            )
            if selected is not None:
                self._enter(owner, waiting, selected, now)
        self.state["last_poll_ms"] = now


def read_signal_projection(
    path: Path, cursor: Mapping[str, Any], kind: str = "FRESH_FORWARD"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Verify the prior byte prefix even if an atomic logical projection was replaced."""
    if kind not in ("FRESH_FORWARD", "MICRO"):
        raise PaperError("UNKNOWN_SIGNAL_HASH_PROFILE")
    source_digest = micro_digest if kind == "MICRO" else digest
    if cursor.get("hash_profile", kind) != kind:
        raise PaperError("SIGNAL_HASH_PROFILE_CHANGED")
    if not path.exists():
        return [], dict(cursor)
    raw = path.read_bytes()
    offset = int(cursor.get("offset", 0))
    if offset > len(raw) or hashlib.sha256(raw[:offset]).hexdigest() != cursor.get(
        "prefix_sha256", hashlib.sha256(b"").hexdigest()
    ):
        raise PaperError("SIGNAL_PROJECTION_PREFIX_CHANGED")
    complete = raw.rfind(b"\n") + 1
    if complete < offset:
        raise PaperError("SIGNAL_CURSOR_OUTSIDE_COMPLETE_PREFIX")
    previous = cursor.get("last_record_sha256", "0" * 64)
    new = []
    for line in raw[offset:complete].splitlines():
        row = json.loads(line)
        body = {k: v for k, v in row.items() if k != "record_sha256"}
        if row.get("previous_sha256") != previous or row.get(
            "record_sha256"
        ) != source_digest(body):
            raise PaperError("SIGNAL_PROJECTION_HASH_CHAIN")
        previous = row["record_sha256"]
        new.append(row)
    return new, {
        "offset": complete,
        "prefix_sha256": hashlib.sha256(raw[:complete]).hexdigest(),
        "last_record_sha256": previous,
        "hash_profile": kind,
    }


def _pin(item: Mapping[str, Any]) -> Path:
    path = Path(str(item["path"]))
    if not path.is_absolute():
        raise PaperError("ABSOLUTE_PAPER_PIN_REQUIRED")
    path = path.resolve()
    if sha_file(path) != item["sha256"]:
        raise PaperError("PAPER_PIN_CHANGED:" + str(path))
    return path


def runtime_config(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, float], dict[str, Any]]:
    config = json.loads(path.read_bytes())
    if (
        config.get("execution_profile") != PROFILE
        or config.get("order_authority") != "BLOCKED"
    ):
        raise PaperError("PAPER_PROFILE_OR_ORDER_AUTHORITY")
    for item in config["code_pins"]:
        _pin(item)
    if not any(
        Path(item["path"]).resolve() == Path(__file__).resolve()
        for item in config["code_pins"]
    ):
        raise PaperError("PAPER_SELF_CODE_PIN_REQUIRED")
    forward_path = _pin(config["fresh_config"])
    forward = importlib.import_module(
        "backend.research.rebuild.scalp7_fresh_forward_v2"
    )
    forward_config, contract, costs = forward.read_config(forward_path)
    modules = {
        x["identity"]: importlib.import_module(
            "backend.research.rebuild." + x["module"]
        )
        for x in contract["candidates"]
    }
    micro = importlib.import_module("backend.research.rebuild.scalp7_micro_decision_v2")
    modules[micro.IDENTITY] = micro
    if len({str(Path(x["path"]).resolve()) for x in config["signal_sources"]}) != len(
        config["signal_sources"]
    ):
        raise PaperError("DUPLICATE_PAPER_SIGNAL_SOURCE")
    for item in config["signal_sources"]:
        freeze_path = _pin(item["freeze"])
        freeze = json.loads(freeze_path.read_bytes())
        source_path = Path(item["path"])
        if (
            not source_path.is_absolute()
            or source_path.resolve().parent != freeze_path.parent
        ):
            raise PaperError("SIGNAL_LEDGER_FREEZE_DIRECTORY_MISMATCH")
        if item.get("kind") == "FRESH_FORWARD":
            if freeze.get("schema") != "scalp7.fresh_forward.freeze.v2" or freeze.get(
                "config_sha256"
            ) != sha_file(forward_path):
                raise PaperError("SIGNAL_FORWARD_FREEZE_CONFIG_MISMATCH")
            if source_path.name != "fresh_signals.jsonl":
                raise PaperError("SIGNAL_FORWARD_LEDGER_NAME")
        elif item.get("kind") == "MICRO":
            if (
                freeze.get("schema") != "scalp7.micro.fresh_producer.v2"
                or freeze.get("identity") != micro.IDENTITY
            ):
                raise PaperError("SIGNAL_MICRO_FREEZE_IDENTITY")
            if source_path.name != "signals.jsonl":
                raise PaperError("SIGNAL_MICRO_LEDGER_NAME")
            micro_pins = freeze.get("code_sha256", {})
            if (
                "scalp7_micro_decision_v2.py" not in micro_pins
                or "scalp7_micro_producer_v2.py" not in micro_pins
            ):
                raise PaperError("SIGNAL_MICRO_CODE_PINS_REQUIRED")
            for name, expected in micro_pins.items():
                if (
                    Path(name).name != name
                    or sha_file(Path(__file__).parent / name) != expected
                ):
                    raise PaperError("SIGNAL_MICRO_CODE_CHANGED")
        else:
            raise PaperError("PAPER_SIGNAL_SOURCE_KIND")
    if int(config["fresh_start_ms"]) < int(forward_config["fresh_start_ms"]):
        raise PaperError("PAPER_PRECEDES_COMMON_RULE_FREEZE")
    return config, forward_config, costs, modules


def _load_state(out: Path, freeze_sha: str) -> dict[str, Any]:
    path = out / "STATE.json"
    if not path.exists():
        return empty_state(freeze_sha)
    state = json.loads(path.read_bytes())
    saved = state.pop("state_sha256")
    if saved != digest(state) or state["freeze_sha256"] != freeze_sha:
        raise PaperError("PAPER_STATE_HASH_OR_FREEZE")
    return state


def initialize(out: Path, config_path: Path, now_ms: int) -> dict[str, Any]:
    config, _, _, _ = runtime_config(config_path)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "FREEZE.json"
    if path.exists():
        result = json.loads(path.read_bytes())
        if result["config_sha256"] != sha_file(config_path):
            raise PaperError("PAPER_CONFIG_CHANGED")
        return result
    if now_ms > int(config["fresh_start_ms"]):
        raise PaperError("PAPER_INITIALIZE_BEFORE_START")
    result = {
        "schema": "scalp7.observed_paper.freeze.v2",
        "config_sha256": sha_file(config_path),
        "initialized_at_ms": now_ms,
        "fresh_start_ms": config["fresh_start_ms"],
        "execution_profile": PROFILE,
        "sizing": "UNIT_GROSS_RESEARCH_NOTIONAL_NOT_ACCOUNT_POSITION",
        "costs": "OBSERVED_QUOTE_GROSS_MINUS_ADDITIONAL_FROZEN_RESERVE_1X_2X",
        "capacity": "UNPROVEN_NO_QUANTITY_UNIT_ASSUMPTION",
        "quote_path": "SPARSE_OBSERVED_NOT_COMPLETE",
        "first_partial_entry_bar": "QUOTE_STOP_TARGET_MFE_PARTIALS_ACTIVE; CALLBACKS_START_FIRST_FULL_POST_ENTRY_BAR; ST_AND_PARENT_NATIVE_FEATURE_STATE_BRIDGE_PARTIAL_CLOSED_BAR_WITHOUT_FILLS; PARENT_PEAK_TRAIL_USES_QUOTE_MFE",
        "entry": "FIRST_NEW_REQUEST_AFTER_ACTUAL_DECISION_IF_DECISION_BAR_NOT_SUPERSEDED",
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    immutable_bytes(path, json_bytes(result))
    return result


def poll(
    out: Path,
    config_path: Path,
    *,
    now_ms: int | None = None,
    fetch: Callable[[str], tuple[int, bytes]] = public_fetch,
) -> dict[str, Any]:
    now = int(time.time() * 1000) if now_ms is None else now_ms
    config, forward_config, costs, modules = runtime_config(config_path)
    initialize(out, config_path, now)
    state = _load_state(out, sha_file(out / "FREEZE.json"))
    machine = ObservedPaper(state, config, costs, modules)
    if now < int(config["fresh_start_ms"]):
        return {
            "state": "WAIT_COMMON_PAPER_START",
            "fresh_closed_trades": len(state["trades"]),
        }
    for source in config["signal_sources"]:
        name = str(Path(source["path"]).resolve())
        new, cursor = read_signal_projection(
            Path(name), state["signal_cursors"].get(name, {}), source["kind"]
        )
        for wrapper in new:
            if (
                source["kind"] == "FRESH_FORWARD"
                and wrapper.get("freeze_sha256") != source["freeze"]["sha256"]
            ):
                raise PaperError("SIGNAL_WRAPPER_FREEZE_MISMATCH")
            admission_now = int(time.time() * 1000) if now_ms is None else now
            machine.admit(wrapper, admission_now)
        state["signal_cursors"][name] = cursor
    forward = importlib.import_module(
        "backend.research.rebuild.scalp7_fresh_forward_v2"
    )
    frames, _, source_receipt = forward.build_current_frames(forward_config, now)
    names = sorted(
        {
            leg["symbol"]
            for x in list(state["pending"].values()) + list(state["positions"].values())
            for leg in _legs(x["signal"])
        }
    )
    quotes = {}
    for symbol in names:
        quotes[symbol] = quote_request(out, symbol, fetch)
    observed = (
        int(time.time() * 1000)
        if now_ms is None
        else max([now] + [int(q["received_at_ms"]) for q in quotes.values()])
    )
    _, observed_bars, refreshed_receipt = forward.build_current_frames(
        forward_config, observed, bind=False
    )
    machine.step(quotes, frames, observed, observed_bars)
    source_receipt["entry_recheck_source_receipt"] = refreshed_receipt
    state["context_source_receipt"] = source_receipt
    state["state_sha256"] = digest(state)
    if len(json_bytes(state)) > MAX_STATE_BYTES:
        raise PaperError("PAPER_LEDGER_BUDGET_HOLD_NO_DELETION")
    atomic_json(out / "STATE.json", state)
    # Repairable projections; authoritative atomic state prevents duplicate closes after a crash.
    for filename, rows in (
        ("paper_trades.jsonl", state["trades"]),
        ("paper_events.jsonl", state["events"]),
    ):
        previous = "0" * 64
        lines = []
        for row in rows:
            item = {"previous_sha256": previous, "payload": row}
            item["record_sha256"] = digest(item)
            previous = item["record_sha256"]
            lines.append(json_bytes(item))
        target = out / filename
        temporary = out / (filename + ".tmp")
        temporary.write_bytes(b"".join(lines))
        temporary.replace(target)
    result = {
        "state": "OBSERVED_QUOTE_PAPER_ACTIVE",
        "fresh_closed_trades": len(state["trades"]),
        "open_positions": len(state["positions"]),
        "pending_entries": len(state["pending"]),
        "unresolved_positions": sum(
            x["status"] != "OPEN_OBSERVED_PAPER" for x in state["positions"].values()
        ),
        "observed_at_ms": observed,
        "execution_profile": PROFILE,
        "account_or_exchange_fills": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    atomic_json(out / "STATUS.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "paper.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                result = poll(args.out, args.config)
            except (
                PaperError,
                ValueError,
                KeyError,
                TypeError,
                OSError,
                RuntimeError,
            ) as exc:
                atomic_json(
                    args.out / "STATUS.json",
                    {
                        "state": "HOLD_OBSERVED_PAPER_INTEGRITY",
                        "reason": str(exc),
                        "observed_at_ms": int(time.time() * 1000),
                        "order_authority": "BLOCKED",
                    },
                )
                return 2
            print(json.dumps(result), flush=True)
            if args.once:
                return 0
            time.sleep(30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
