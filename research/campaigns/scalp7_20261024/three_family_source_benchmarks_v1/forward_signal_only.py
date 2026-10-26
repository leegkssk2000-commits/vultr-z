"""GMMA + TSMOM: existing frozen 4h rule, real received-at, zero-order signal watch.

Uses ONE existing BingX public 1m source, never a new collector.
Existing economic outcomes are used historical DEV; no trade fills or G5 credit.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import hashlib
import io
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

import benchmark as native
import forward_asof_quote as book

SOURCE = Path("/home/z/z/runtime/scalp7_broad_v2_20260915/fresh_1m_verified")
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT")
FAMILIES = (native.TREND, native.MOM)
FOUR = 4 * 3_600_000
MINUTE = 60_000
WARMUP = 240
IDENTITY_SHA = "a5c2d7d6888b1cbf5e5c851c66b11127736fda94fd58f0484e19381c7e1efca9"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def guarded_path(root: Path, relative: str) -> Path:
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()):
        raise RuntimeError("SOURCE_PATH_ESCAPE")
    return p


def load_period(
    source: Path, start: int, end: int, observed_ms: int
) -> dict[str, pd.DataFrame]:
    """Point-in-time verified OHLC from already-saved immutable one-minute receipts."""
    if end <= start or start % FOUR or end % FOUR or observed_ms < end:
        raise RuntimeError("SOURCE_CLOCK_WRONG")
    identity_raw = (source / "IDENTITY.json").read_bytes()
    identity = json.loads(identity_raw)
    if (
        digest(identity_raw) != IDENTITY_SHA
        or identity.get("interval") != "1m"
        or identity.get("volume_units") != "UNKNOWN"
        or identity.get("synthetic_fill") is not False
        or not set(SYMBOLS).issubset(set(identity.get("symbols", [])))
    ):
        raise RuntimeError("SOURCE_IDENTITY_MISMATCH")
    cursor_raw = (source / "CURSOR.json").read_bytes()
    cursor = json.loads(cursor_raw)
    if cursor["identity_sha256"] != IDENTITY_SHA:
        raise RuntimeError("SOURCE_CURSOR_IDENTITY_MISMATCH")
    result = {}
    for symbol in SYMBOLS:
        observed: dict[int, tuple[tuple[float, ...], int]] = {}
        for pointer in reversed(cursor["symbols"][symbol]):
            p = guarded_path(source, pointer["path"])
            receipt_raw = p.read_bytes()
            if digest(receipt_raw) != pointer["sha256"]:
                raise RuntimeError("SOURCE_RECEIPT_HASH_CHANGED:" + symbol)
            r = json.loads(receipt_raw)
            if int(r["end_exclusive_ms"]) <= start:
                break
            if int(r["start_ms"]) >= end:
                continue
            if (
                r["symbol"] != symbol
                or r["http_status"] != 200
                or r["synthetic_fill"] is not False
            ):
                raise RuntimeError("SOURCE_RECEIPT_INVALID:" + symbol)
            received = int(r["received_at_ms"])
            if received > observed_ms:
                continue
            blob = guarded_path(source, r["normalized_path"]).read_bytes()
            if digest(blob) != r["normalized_sha256"]:
                raise RuntimeError("SOURCE_PAYLOAD_HASH_CHANGED:" + symbol)
            for row in csv.DictReader(io.StringIO(gzip.decompress(blob).decode())):
                t = int(row["timestamp_ms"])
                if not start <= t < end:
                    continue
                val = tuple(
                    float(row[col])
                    for col in ("open", "high", "low", "close", "volume")
                )
                op, hi, lo, close, vol = val
                if (
                    t % MINUTE
                    or not all(math.isfinite(v) for v in val)
                    or min(op, hi, lo, close) <= 0
                    or vol < 0
                    or hi < max(op, lo, close)
                    or lo > min(op, hi, close)
                ):
                    raise RuntimeError("SOURCE_BAD_MINUTE:" + symbol)
                if t in observed and observed[t][0] != val:
                    raise RuntimeError("SOURCE_MINUTE_REWRITTEN:" + symbol)
                if t not in observed or received < observed[t][1]:
                    observed[t] = (val, received)
        bars = []
        for opening in range(start, end, FOUR):
            minutes = [observed.get(opening + j * MINUTE) for j in range(240)]
            if any(x is None for x in minutes):
                raise RuntimeError("SOURCE_4H_MINUTE_GAP:" + symbol)
            price = [x[0] for x in minutes if x is not None]
            latest = max(x[1] for x in minutes if x is not None)
            if latest > observed_ms or latest < opening + FOUR:
                raise RuntimeError("SOURCE_4H_EARLY_OR_UNAVAILABLE:" + symbol)
            bars.append(
                {
                    "open_ts_ms": opening,
                    "close_ts_ms": opening + FOUR,
                    "open": price[0][0],
                    "high": max(x[1] for x in price),
                    "low": min(x[2] for x in price),
                    "close": price[-1][3],
                    "volume": sum(x[4] for x in price),
                    "observed_source_last_received_ms": latest,
                }
            )
        result[symbol] = pd.DataFrame(bars)
    return result


def classify(family: str, enriched: pd.DataFrame) -> bool:
    rows = enriched.to_dict("records")
    if len(rows) <= WARMUP:
        raise RuntimeError("NATIVE_240_WARMUP_NOT_COMPLETE")
    return native.signal_for(family, rows, len(rows) - 1)


def frame_digest(frame: pd.DataFrame) -> str:
    """Commit the verified OHLC prefix, not an indicator's NaN warmup rows."""
    return digest(frame.to_json(orient="records", double_precision=15).encode())


def decision_event(family: str, symbol: str, history: pd.DataFrame,
                   context: pd.DataFrame) -> dict[str, Any]:
    """Native predicates only; the quote consumer owns all virtual positions."""
    is_signal = classify(family, context)
    row = history.iloc[-1]
    enriched = context.iloc[-1]
    multiple, bars = native.safety(family)
    distance = float(enriched["atr14"]) * multiple
    exit_on_close = bool(native.take_exit_on_close(family, enriched))
    bar = {key: int(row[key]) for key in
           ("open_ts_ms", "close_ts_ms", "observed_source_last_received_ms")}
    bar.update({key: float(row[key]) for key in ("open", "high", "low", "close")})
    if not math.isfinite(distance) or distance <= 0:
        raise RuntimeError("NATIVE_STOP_DISTANCE_INVALID")
    event = {
        "rule_id": family, "symbol": symbol,
        "closed_native_4h_ts_ms": int(row.close_ts_ms),
        "first_actual_source_received_ms": int(row.observed_source_last_received_ms),
        "state": "SIGNAL_ONLY_NO_ORDER_NO_FILL" if is_signal else "NO_SIGNAL",
        "native_exit_on_close": exit_on_close,
        "native_safety_max_hold_bars": bars,
        "native_safety_stop_distance_price": distance,
        "native_stop_distance_reference_bps": 10000 * distance / float(row["close"]),
        "native_signal_close_reference_price": float(row["close"]),
        "native_exit_input": {"bar": bar, "source_bar_sha256": digest(
            json.dumps(bar, sort_keys=True, separators=(",", ":")).encode())},
        "native_exit_status": "INPUT_ONLY_NO_POSITION_STATE",
        "context_first_open_ms": int(history.iloc[0].open_ts_ms),
        "context_source_sha256": frame_digest(history),
        "source_identity_sha256": IDENTITY_SHA,
        "order_calls": 0, "virtual_fills": 0,
        "native_next_open_fill_verified": False,
    }
    # Stamp after the native computation and evidence digests have completed.
    event["decision_ts_ms"] = int(time.time() * 1000)
    if event["decision_ts_ms"] < max(event["first_actual_source_received_ms"],
                                       event["closed_native_4h_ts_ms"]):
        raise RuntimeError("NATIVE_DECISION_BEFORE_SOURCE")
    return event


def resume_plan(status: dict[str, Any], now_ms: int) -> tuple[int, int, int]:
    """Restore the original EMA seed and cursor; never emit old decisions again."""
    expected = {
        "schema": "zel.existing_gmma_tsmom.4h.orderless_forward.v1",
        "source_identity_sha256": IDENTITY_SHA,
        "native_frozen_source_sha256": digest(Path(__file__).with_name("benchmark.py").read_bytes()),
        "native_freeze_sha256": digest(Path(__file__).with_name("FREEZE.json").read_bytes()),
        "orders": 0, "order_calls": 0, "virtual_fills": 0, "formal_shadow": False,
    }
    if any(status.get(key) != val for key, val in expected.items()):
        raise RuntimeError("RESUME_AUTHORITY_OR_SOURCE_CHANGED")
    if list(status.get("action_symbols", [])) != list(SYMBOLS) or list(status.get("rule_ids", [])) != list(FAMILIES):
        raise RuntimeError("RESUME_RULE_OR_SYMBOL_CHANGED")
    initial_close = int(status["started_ms"]) // FOUR * FOUR
    start = int(status.get("context_first_open_ms", initial_close - WARMUP * FOUR))
    next_close = int(status["next_expected_bar_close_ms"])
    last_close = int(status.get("last_complete_native_4h_close_ms", initial_close))
    if (start != initial_close - WARMUP * FOUR or start % FOUR or
            last_close % FOUR or next_close != last_close + FOUR or
            last_close < initial_close or now_ms < last_close or
            now_ms >= next_close + FOUR):
        raise RuntimeError("RESUME_CONTEXT_OR_CURSOR_GAP_NO_BACKFILL")
    return start, last_close, next_close


def atomic_status(out: Path, status: dict[str, Any]) -> None:
    status["pid"] = os.getpid()
    status["updated_at_ms"] = int(time.time() * 1000)
    if (
        status.get("orders") != 0
        or status.get("order_calls") != 0
        or status.get("virtual_fills") != 0
        or status.get("formal_shadow") is not False
    ):
        raise RuntimeError("ZERO_ORDER_SHADOW_AUTHORITY_BROKEN")
    raw = (
        json.dumps(status, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    p = out / "STATUS.tmp"
    p.write_bytes(raw)
    os.replace(p, out / "STATUS.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enable-signal-only", action="store_true")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--source", type=Path, default=SOURCE)
    ap.add_argument("--max-seconds", type=int, default=86400)
    ap.add_argument("--poll-seconds", type=int, default=180)
    ap.add_argument("--resume-existing", action="store_true")
    a = ap.parse_args()
    if not a.enable_signal_only:
        print("DEFAULT_OFF")
        return 0
    if not (60 <= a.max_seconds <= 604800 and 60 <= a.poll_seconds <= 300):
        raise SystemExit("BOUNDED_ORDERLESS_ONLY")
    safe_env = {
        key: value
        for key, value in os.environ.items()
        if key in ("PATH", "LANG", "LC_ALL", "TZ")
    }
    os.environ.clear()
    os.environ.update(safe_env)
    a.out.mkdir(parents=True, exist_ok=a.resume_existing)
    lock = (a.out / "writer.lock").open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def forbid(event: str, args: tuple[Any, ...]) -> None:
        if event in (
            "socket.connect",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
        ):
            raise RuntimeError("NETWORK_OR_ORDER_BLOCKED")

    sys.addaudithook(forbid)
    started = int(time.time() * 1000)
    last_close = started // FOUR * FOUR
    next_close = last_close + FOUR
    status: dict[str, Any] = {
        "schema": "zel.existing_gmma_tsmom.4h.orderless_forward.v1",
        "phase": "INIT_240_NATIVE_4H_CONTEXT",
        "started_ms": started,
        "native_frozen_source_sha256": digest(
            (Path(__file__).with_name("benchmark.py")).read_bytes()
        ),
        "native_freeze_sha256": digest(
            (Path(__file__).with_name("FREEZE.json")).read_bytes()
        ),
        "source_identity_sha256": IDENTITY_SHA,
        "action_symbols": SYMBOLS,
        "rule_ids": FAMILIES,
        "next_expected_bar_close_ms": next_close,
        "orders": 0,
        "order_calls": 0,
        "virtual_fills": 0,
        "formal_shadow": False,
        "fresh_trades": 0,
        "market_api_calls": 0,
        "account_net_pf_dd": "NOT_VERIFIED",
        "real_next_open_fills": 0,
        "signals": [],
        "decisions": [],
    }
    context_start = last_close - WARMUP * FOUR
    if a.resume_existing:
        old = json.loads((a.out / "STATUS.json").read_bytes())
        context_start, last_close, next_close = resume_plan(old, started)
        status = old
        status["resumed_at_ms"] = started
        status["stopped"] = False
        status["phase"] = "RESTORE_ORIGINAL_CONTEXT_NO_SIGNAL_REISSUE"
    status["context_first_open_ms"] = context_start
    status["native_exit_contract"] = "FROZEN_NATIVE_COMPLETED_BAR_CONDITIONS_V1"
    status["producer_poll_seconds"] = a.poll_seconds
    atomic_status(a.out, status)
    try:
        # One time warmup on real older source; no old signal is future-credited.
        source_frames = load_period(
            a.source, context_start, last_close, started
        )
        if any(len(f) != (last_close - context_start) // FOUR for f in source_frames.values()):
            raise RuntimeError("SOURCE_CONTEXT_TOO_SHORT")
        prior_hashes = status.get("context_source_sha256_by_symbol", {})
        restored_hashes = {sym: frame_digest(df) for sym, df in source_frames.items()}
        if prior_hashes and prior_hashes != restored_hashes:
            raise RuntimeError("RESUME_CONTEXT_SOURCE_CHANGED")
        status["context_source_sha256_by_symbol"] = restored_hashes
        status["context_source_closed_4h_by_symbol"] = {
            sym: len(df) for sym, df in source_frames.items()
        }
        status["phase"] = "ACTIVE_WAIT_NEXT_NEW_CLOSED_4H_SIGNAL_ONLY"
        atomic_status(a.out, status)
        print(
            json.dumps(
                {
                    "phase": status["phase"],
                    "warmup": WARMUP,
                    "symbols": len(SYMBOLS),
                    "orders": 0,
                }
            ),
            flush=True,
        )
        deadline = time.monotonic() + a.max_seconds
        while time.monotonic() < deadline:
            now = int(time.time() * 1000)
            if now < next_close:
                atomic_status(a.out, status)
                time.sleep(a.poll_seconds)
                continue
            if now >= next_close + FOUR:
                status["phase"] = "HOLD_EXPIRED_BAR_NO_BACKFILL"
                atomic_status(a.out, status)
                break
            try:
                new_frames = load_period(a.source, next_close - FOUR, next_close, now)
                decisions = []
                next_histories = {}
                for sym in SYMBOLS:
                    history = pd.concat(
                        [source_frames[sym], new_frames[sym]], ignore_index=True
                    )
                    context = native.enrich(history)
                    for family in FAMILIES:
                        event = decision_event(family, sym, history, context)
                        decisions.append(event)
                        if event["state"] == "SIGNAL_ONLY_NO_ORDER_NO_FILL":
                            # Quote is a new post-decision mark, never retroactive
                            # to the theoretical native next 4h OPEN.
                            event["quote_evidence"] = book.observe(
                                sym,
                                decision_ts_ms=event["decision_ts_ms"],
                                read_at_ms=int(time.time() * 1000),
                            )
                    same_symbol = [
                        event
                        for event in decisions
                        if event["symbol"] == sym
                        and event["state"] == "SIGNAL_ONLY_NO_ORDER_NO_FILL"
                    ]
                    if len(same_symbol) > 1:
                        for event in same_symbol:
                            event["overlap_same_symbol_both_strategies"] = True
                            event["independent_position_credit"] = False
                    next_histories[sym] = history
                source_frames = next_histories
                status["signals"].extend(event for event in decisions
                                         if event["state"] == "SIGNAL_ONLY_NO_ORDER_NO_FILL")
                status["decisions"].extend(decisions)
                status["context_source_sha256_by_symbol"] = {
                    sym: frame_digest(df) for sym, df in source_frames.items()}
                status["last_complete_native_4h_close_ms"] = next_close
                next_close += FOUR
                status["next_expected_bar_close_ms"] = next_close
                status["phase"] = "ACTIVE_WAIT_NEXT_NEW_CLOSED_4H_SIGNAL_ONLY"
                status.pop("source_hold_reason", None)
                atomic_status(a.out, status)
                print(
                    json.dumps(
                        {
                            "new_decisions": len(decisions),
                            "signals": len(status["signals"]),
                            "close": status["last_complete_native_4h_close_ms"],
                            "orders": 0,
                        }
                    ),
                    flush=True,
                )
            except (OSError, RuntimeError, KeyError, ValueError) as e:
                status["phase"] = "WAIT_ACTUAL_SOURCE"
                status["source_hold_reason"] = str(e)
                atomic_status(a.out, status)
            time.sleep(a.poll_seconds)
    except Exception as e:
        status["phase"] = "HOLD_SOURCE_PRECHECK"
        status["source_hold_reason"] = type(e).__name__ + ":" + str(e)
        atomic_status(a.out, status)
        raise
    finally:
        status["stopped"] = True
        status["terminal_phase"] = status["phase"]
        atomic_status(a.out, status)
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
