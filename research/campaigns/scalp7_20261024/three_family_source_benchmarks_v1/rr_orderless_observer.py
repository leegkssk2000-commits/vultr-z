"""K117 + GMMA + TSMOM prospective, BBO-only R observation; default OFF.

Source-frozen original strategies retain ALL authority. This separate
counterfactual RR runner does NOT simulate exact broker fills, intrabar path,
native strategy exits, funding, account NAV, orders, Paper, Live or G5 credit.
Only causal post-signal BTC/ETH WS quotes are observational price marks.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

from forward_asof_quote import observe

GMMA = "TREND_GUPPY_GMMA_LONG_4H_V1"
TSMOM = "MOMENTUM_MOP_TSMOM_LONG_4H_V1"
K117 = "K117_PRICE_ONLY_30M_NATIVE"
RULES = (TSMOM, GMMA, K117)
FOUR = 14_400_000
HALF_HOUR = 1_800_000
SIGNAL_4H = Path("/home/z/z/runtime/gmma_tsmom_orderless_quote_20261026_v2/STATUS.json")
SIGNAL_K117 = Path(
    "/home/z/z/runtime/k117_priceonly_orderless_20261025_extended_v1/STATUS.json"
)
SHADOW = "zel.three_existing_survivors.rr_observer.v1"


def digest(v: Any) -> str:
    return hashlib.sha256(
        json.dumps(v, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def native_events(
    gmma_status: dict[str, Any], k117_status: dict[str, Any]
) -> list[dict[str, Any]]:
    """No lookahead; K117 decision timestamp is its matching latest checkpoint."""
    out = []
    if (
        gmma_status.get("order_calls") != 0
        or gmma_status.get("virtual_fills") != 0
        or gmma_status.get("formal_shadow") is not False
        or k117_status.get("order_calls") != 0
        or k117_status.get("virtual_fills") != 0
    ):
        raise RuntimeError("SOURCE_OBSERVER_AUTHORITY_CHANGED")
    for row in gmma_status.get("signals", []):
        if row.get("state") != "SIGNAL_ONLY_NO_ORDER_NO_FILL":
            continue
        if row.get("rule_id") not in (GMMA, TSMOM):
            continue
        out.append(
            {
                "rule_id": row["rule_id"],
                "symbol": row["symbol"],
                "decision_ms": int(row["decision_ts_ms"]),
                "risk_bps": float(row.get("native_stop_distance_reference_bps") or 0),
                "max_hold_ms": FOUR * (24 if row["rule_id"] == TSMOM else 48),
                "original_signal_digest": digest(row),
            }
        )
    last_bar = k117_status.get("last_complete_30m_close_ms")
    decision = k117_status.get("last_native_decision_ms")
    for row in k117_status.get("signals", []):
        if row.get("status") != "SIGNAL":
            continue
        if row.get("close_ts_ms") != last_bar or decision is None:
            # A prior K117 event has no provable stored per-event decision clock.
            continue
        sig = row.get("signal") or {}
        if sig.get("side") not in (1, "long", "LONG"):
            continue
        out.append(
            {
                "rule_id": K117,
                "symbol": row.get("symbol"),
                "decision_ms": int(decision),
                "signal_stop_px": float(sig.get("stop_price") or 0),
                "max_hold_ms": HALF_HOUR * 50,
                "original_signal_digest": digest(row),
            }
        )
    return sorted(
        out,
        key=lambda x: (x["decision_ms"], RULES.index(x["rule_id"]), str(x["symbol"])),
    )


def quote_entry(event: dict[str, Any], q: dict[str, Any]) -> dict[str, Any] | None:
    if q.get("state") != "OBSERVED_REAL_POST_DECISION_BOOK_ONLY_NO_FILL":
        return None
    px = float(q["best_ask"])
    if px <= 0 or not math.isfinite(px):
        return None
    if event["rule_id"] == K117:
        # The native stop belongs to the native next-open, NOT this delayed quote.
        stop = float(event["signal_stop_px"])
    else:
        r_bps = float(event.get("risk_bps") or 0)
        if not math.isfinite(r_bps) or not 0 < r_bps < 10000:
            return None
        stop = px * (1 - r_bps / 10000)
    risk = px - stop
    if not math.isfinite(risk) or not 0 < risk < px:
        return None
    ts = int(q["source_quote_ts_ms"])
    if ts < event["decision_ms"]:
        return None
    return {
        "rule_id": event["rule_id"],
        "symbol": event["symbol"],
        "original_signal_digest": event["original_signal_digest"],
        "entry_quote_ts_ms": ts,
        "entry_ask_price": px,
        "native_or_reference_stop_price": stop,
        "initial_risk_price": risk,
        "last_quote_ts_ms": ts,
        "max_hold_ms": event["max_hold_ms"],
        "base_stop_price": stop,
        "active_floor_stop_price": stop,
        "floor_pending_after_ts_ms": None,
        "best_observed_R": -100.0,
        "last_observed_R": -100.0,
        "cost_assumption_roundtrip_bps": 40,
        "quote_entry_sha256": q["source_quote_sha256"],
        "real_broker_fill": False,
        "original_next_open_fill_verified": False,
        "formal_shadow": False,
    }


def sample_position(
    position: dict[str, Any], q: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """2R observation arms +0.5R floor for NEXT quote; big winners uncapped."""
    if q.get("state") != "OBSERVED_REAL_POST_DECISION_BOOK_ONLY_NO_FILL":
        return position, None
    ts = int(q["source_quote_ts_ms"])
    if ts <= position["last_quote_ts_ms"]:
        return position, None
    p = dict(position)
    entry = float(p["entry_ask_price"])
    risk = float(p["initial_risk_price"])
    bid = float(q["best_bid"])
    if not 0 < bid or not 0 < risk:
        return position, None
    p["last_quote_ts_ms"] = ts
    measured_R = (bid - entry) / risk
    p["best_observed_R"] = max(float(p["best_observed_R"]), measured_R)
    p["last_observed_R"] = measured_R
    # Apply the already-armed floor, only when the quote is STRICTLY newer.
    if p["floor_pending_after_ts_ms"] is not None:
        if ts > p["floor_pending_after_ts_ms"]:
            p["active_floor_stop_price"] = max(
                p["active_floor_stop_price"], entry + 0.5 * risk
            )
            p["floor_pending_after_ts_ms"] = None
    terminal = (
        "OBSERVED_BID_TOUCH_STOP"
        if bid <= p["active_floor_stop_price"]
        else (
            "OBSERVED_TIME_CAP"
            if ts >= p["entry_quote_ts_ms"] + p["max_hold_ms"]
            else None
        )
    )
    if terminal:
        pnl_bps = 10000 * (bid / entry - 1) - p["cost_assumption_roundtrip_bps"]
        return p, {
            "type": "QUOTE_MARK_TERMINAL_NOT_BROKER_FILL",
            "symbol": p["symbol"],
            "rule_id": p["rule_id"],
            "terminal_quote_ts_ms": ts,
            "terminal_bid_price": bid,
            "observational_net_bps_at_40bp": pnl_bps,
            "observational_net_R": measured_R
            - (p["cost_assumption_roundtrip_bps"] / (10000 * risk / entry)),
            "reason": terminal,
            "intrabar_stop_witness_complete": False,
            "native_exit_rule_parity": False,
            "real_trade": False,
            "order_calls": 0,
            "source_quote_sha256": q["source_quote_sha256"],
        }
    if (
        measured_R >= 2
        and p["floor_pending_after_ts_ms"] is None
        and p["active_floor_stop_price"] < entry
    ):
        p["floor_pending_after_ts_ms"] = ts
    return p, None


def persist(out: Path, state: dict[str, Any]) -> None:
    if (
        state.get("order_calls") != 0
        or state.get("real_broker_fills") != 0
        or state.get("formal_shadow") is not False
    ):
        raise RuntimeError("RR_ORDERLESS_AUTHORITY_CHANGED")
    tmp = out / "STATUS.tmp"
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, out / "STATUS.json")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--enable-observational-rr-only", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--max-seconds", type=int, default=604800)
    p.add_argument("--poll-seconds", type=int, default=5)
    p.add_argument("--resume-existing", action="store_true")
    a = p.parse_args()
    if not a.enable_observational_rr_only:
        print("DEFAULT_OFF:NO_ORDER_RR_SHADOW")
        return 0
    if not (60 <= a.max_seconds <= 604800 and 3 <= a.poll_seconds <= 60):
        raise SystemExit("BOUNDED_RR_ONLY")
    a.out.mkdir(parents=True, exist_ok=a.resume_existing)
    lock = (a.out / "writer.lock").open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event in (
            "socket.connect",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
        ):
            raise RuntimeError("NETWORK_ORDER_SUBPROCESS_BLOCKED")

    sys.addaudithook(audit)
    started = int(time.time() * 1000)
    state: dict[str, Any] = {
        "schema": SHADOW,
        "state": "ACTIVE_WAIT_FIRST_FUTURE_SOURCE_SIGNAL",
        "started_at_ms": started,
        "rules": list(RULES),
        "quote_symbols": ["BTC-USDT", "ETH-USDT"],
        "runner_idea": "OBSERVE_2R_ARM_NEXT_QUOTE_PLUS_0P5R_FLOOR_NO_HARD_TP",
        "same_symbol_max_positions": 1,
        "model_cost_bps": 40,
        "real_broker_fills": 0,
        "virtual_fill_claims": 0,
        "order_calls": 0,
        "formal_shadow": False,
        "native_strategy_changed": False,
        "g5_credit": 0,
        "account_NAV": None,
        "closed_quote_marks": [],
        "positions": {},
        "seen_signals": [],
        "pending": {},
        "blocked": [],
    }
    existing = a.out / "STATUS.json"
    if a.resume_existing and existing.exists():
        old_state = json.loads(existing.read_bytes())
        if (
            old_state.get("schema") != SHADOW
            or old_state.get("order_calls") != 0
            or old_state.get("real_broker_fills") != 0
            or old_state.get("formal_shadow") is not False
            or old_state.get("runner_idea")
            != "OBSERVE_2R_ARM_NEXT_QUOTE_PLUS_0P5R_FLOOR_NO_HARD_TP"
            or old_state.get("rules") != list(RULES)
        ):
            raise RuntimeError("RR_CHECKPOINT_AUTHORITY_OR_FREEZE_CHANGED")
        state = old_state
        if started - int(state.get("updated_at_ms", 0)) > 30000:
            state.setdefault("censored_quote_positions", []).extend(
                {
                    "symbol": symbol,
                    "rule_id": position["rule_id"],
                    "reason": "UNOBSERVED_QUOTE_PATH_ON_RESTART_NO_RETRO_CLOSE",
                }
                for symbol, position in state["positions"].items()
            )
            state["positions"] = {}
        state["stopped"] = False
        state["state"] = "RESUMED_PROSPECTIVE_OBSERVATION_NO_ORDER"
        state["restarted_at_ms"] = started
    persist(a.out, state)
    until = time.monotonic() + a.max_seconds
    try:
        while time.monotonic() < until:
            now = int(time.time() * 1000)
            try:
                source4 = json.loads(SIGNAL_4H.read_bytes())
                source117 = json.loads(SIGNAL_K117.read_bytes())
                signals = native_events(source4, source117)
                seen = set(state["seen_signals"])
                for signal in signals:
                    uid = signal["original_signal_digest"]
                    if uid in seen or uid in state["pending"]:
                        continue
                    if signal["decision_ms"] < started:
                        continue  # Never use any earlier signal as fresh.
                    state["pending"][uid] = signal
                for uid, sig in list(state["pending"].items()):
                    if now - sig["decision_ms"] > 120000:
                        state["blocked"].append(
                            {
                                "uid": uid,
                                "reason": "NO_TIMELY_POST_SIGNAL_QUOTE",
                            }
                        )
                        state["seen_signals"].append(uid)
                        del state["pending"][uid]
                        continue
                    sym = sig["symbol"]
                    if sym not in ("BTC-USDT", "ETH-USDT"):
                        state["blocked"].append(
                            {
                                "uid": uid,
                                "reason": "NO_APPROVED_ORDERLESS_BBO_FOR_SYMBOL",
                            }
                        )
                        state["seen_signals"].append(uid)
                        del state["pending"][uid]
                        continue
                    if sym in state["positions"]:
                        state["blocked"].append(
                            {
                                "uid": uid,
                                "reason": "SAME_SYMBOL_POSITION_ALREADY_OCCUPIED",
                            }
                        )
                        state["seen_signals"].append(uid)
                        del state["pending"][uid]
                        continue
                    mark = observe(
                        sym, decision_ts_ms=sig["decision_ms"], read_at_ms=now
                    )
                    new_position = quote_entry(sig, mark)
                    if new_position is not None:
                        state["positions"][sym] = new_position
                        state["seen_signals"].append(uid)
                        del state["pending"][uid]
                        state["state"] = "OBSERVED_QUOTE_MARKED_POSITION_NOT_REAL_FILL"
                for sym, pos in list(state["positions"].items()):
                    mark = observe(
                        sym,
                        decision_ts_ms=pos["last_quote_ts_ms"] + 1,
                        read_at_ms=now,
                    )
                    updated, terminal = sample_position(pos, mark)
                    state["positions"][sym] = updated
                    if terminal:
                        state["closed_quote_marks"].append(terminal)
                        del state["positions"][sym]
                state.pop("last_source_error", None)
            except (OSError, RuntimeError, TypeError, KeyError, ValueError) as e:
                state["last_source_error"] = type(e).__name__ + ":" + str(e)
                state["state"] = "HOLD_SOURCE_CLOCK_OR_AUTHORITY"
            state["updated_at_ms"] = now
            persist(a.out, state)
            time.sleep(a.poll_seconds)
    finally:
        state["stopped"] = True
        persist(a.out, state)
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
