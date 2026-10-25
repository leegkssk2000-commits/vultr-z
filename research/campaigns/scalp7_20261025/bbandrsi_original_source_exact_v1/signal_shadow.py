"""One bounded source-exact BbandRsi SIGNAL ONLY prospective read.

Original STOP=-25% is NOT futures risk-admissible. No virtual fills/PNL,
Paper, Live, signed funding claims, extra market collector, or network calls.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import gzip
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from evaluate import HOUR, indicators

ROOT = Path(__file__).resolve().parent
SOURCE = Path("/home/z/z/runtime/scalp7_broad_v2_20260915/fresh_1m_verified")
HIST_HOURS = 120
MINUTE = 60_000
SCHEMA = "zel.bbandrsi.original.signal_only.forward_obs.v1"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def under(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("SOURCE_PATH_TRAVERSAL")
    return path


def price_frame(
    source: Path,
    close_ms: int,
    observed_ms: int,
    symbol: str,
    *,
    limit: int = HIST_HOURS,
) -> pd.DataFrame:
    contract = json.loads((ROOT / "SIGNAL_ONLY_CONTRACT.json").read_bytes())
    identity_raw = (source / "IDENTITY.json").read_bytes()
    ident = json.loads(identity_raw)
    id_sha = sha(identity_raw)
    if (
        id_sha != contract["source_blob_sha256"]
        or ident.get("volume_units") != "UNKNOWN"
        or ident.get("synthetic_fill") is not False
        or symbol not in contract["signal_only_target_symbols"]
        or ident.get("interval") != "1m"
    ):
        raise RuntimeError("SOURCE_IDENTITY_OR_PRICE_ONLY_SYMBOL_CHANGED")
    if not (observed_ms >= close_ms > 0 and limit >= 50):
        raise RuntimeError("FUTURE_OR_INSUFFICIENT_CONTEXT")
    cursor_raw = (source / "CURSOR.json").read_bytes()
    cursor = json.loads(cursor_raw)
    if cursor["identity_sha256"] != id_sha:
        raise RuntimeError("SOURCE_CURSOR_IDENTITY_CHANGED")
    start_ms = close_ms - limit * HOUR
    observed: dict[int, tuple[tuple[float, ...], int]] = {}
    for pointer in reversed(cursor["symbols"][symbol]):
        p = under(source, pointer["path"])
        receipt_raw = p.read_bytes()
        if sha(receipt_raw) != pointer["sha256"]:
            raise RuntimeError("SOURCE_RECEIPT_SHA_INVALID")
        receipt = json.loads(receipt_raw)
        if int(receipt["end_exclusive_ms"]) <= start_ms:
            break
        if int(receipt["start_ms"]) >= close_ms:
            continue
        if (
            receipt["symbol"] != symbol
            or receipt["http_status"] != 200
            or receipt["synthetic_fill"] is not False
            or receipt["received_at_ms"] > observed_ms
        ):
            raise RuntimeError("SOURCE_RECEIPT_ASOF_INVALID")
        compressed = under(source, receipt["normalized_path"]).read_bytes()
        if sha(compressed) != receipt["normalized_sha256"]:
            raise RuntimeError("SOURCE_NORMALIZED_SHA_INVALID")
        for row in csv.DictReader(io.StringIO(gzip.decompress(compressed).decode())):
            ts = int(row["timestamp_ms"])
            if not start_ms <= ts < close_ms:
                continue
            values = tuple(float(row[col]) for col in ("open", "high", "low", "close"))
            if ts in observed and observed[ts][0] != values:
                raise RuntimeError("SOURCE_MINUTE_REVISION_CHANGED")
            if ts not in observed or receipt["received_at_ms"] < observed[ts][1]:
                observed[ts] = (values, int(receipt["received_at_ms"]))
    if cursor_raw != (source / "CURSOR.json").read_bytes():
        raise RuntimeError("SOURCE_CURSOR_CHANGED_DURING_READ")
    rows = []
    for open_ms in range(start_ms, close_ms, HOUR):
        minutes = [observed.get(open_ms + i * MINUTE) for i in range(60)]
        if any(m is None for m in minutes):
            raise RuntimeError("SOURCE_1H_MINUTE_GAP:" + symbol)
        candles = [m[0] for m in minutes if m is not None]
        latest_received = max(m[1] for m in minutes if m is not None)
        if latest_received > observed_ms or latest_received < open_ms + HOUR:
            raise RuntimeError("SOURCE_1H_BAR_NOT_FULLY_AVAILABLE")
        rows.append(
            {
                "ts_ms": open_ms,
                "open": candles[0][0],
                "high": max(c[1] for c in candles),
                "low": min(c[2] for c in candles),
                "close": candles[-1][3],
                "received_at_ms": latest_received,
            }
        )
    return pd.DataFrame(rows)


def append_status(out: Path, data: dict[str, Any]) -> None:
    if (
        data.get("order_calls") != 0
        or data.get("virtual_fills") != 0
        or data.get("formal_shadow") is not False
    ):
        raise RuntimeError("FORBIDDEN_EXECUTION_AUTHORITY")
    raw = (json.dumps(data, sort_keys=True, allow_nan=False, indent=2) + "\n").encode()
    temp = out / "STATUS.tmp"
    temp.write_bytes(raw)
    os.replace(temp, out / "STATUS.json")


def emit_signals(
    frames: dict[str, pd.DataFrame], *, actual_decision_ms: int, close_ms: int
) -> list[dict[str, Any]]:
    result = []
    for symbol in sorted(frames):
        bar = indicators(frames[symbol]).iloc[-1]
        if int(bar["ts_ms"]) + HOUR != close_ms:
            raise RuntimeError("SIGNAL_SOURCE_CLOCK_WRONG")
        if int(bar["received_at_ms"]) > actual_decision_ms:
            raise RuntimeError("SIGNAL_SOURCE_NOT_OBSERVED")
        entry = bool(bar["signal_long"])
        exit_sig = bool(bar["signal_exit"])
        rsi = float(bar["rsi14"])
        lower = float(bar["boll_lower"])
        if not pd.notna(rsi) or not pd.notna(lower):
            raise RuntimeError("INCOMPLETE_NATIVE_SOURCE_INDICATOR")
        # 120-hour RSI initial seeding is an approximation to an unbounded
        # TA-Lib history. Near a threshold the source is held ambiguous.
        near_boundary = (
            abs(rsi - 30) < 0.2
            or abs(float(bar["close"]) - lower) / float(bar["close"]) < 0.0002
        )
        result.append(
            {
                "symbol": symbol,
                "source_bar_close_ts_ms": close_ms,
                "actual_source_received_at_ms": int(bar["received_at_ms"]),
                "actual_decision_ms": actual_decision_ms,
                "rsi14": rsi,
                "boll_lower": lower,
                "source_close_price": float(bar["close"]),
                "raw_enter_long": entry,
                "raw_exit_long": exit_sig,
                "decision": (
                    "HOLD_SIGNAL_NEAR_SOURCE_THRESHOLD"
                    if near_boundary
                    else (
                        "SIGNAL_INTENT_ONLY_NO_FILL"
                        if entry
                        else "EXIT_INTENT_ONLY_NO_FILL" if exit_sig else "NO_SIGNAL"
                    )
                ),
                "next_open_fill_authorized": False,
                "next_open_past_ts_ms": close_ms,
                "virtual_executions": 0,
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-signal-only", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--max-seconds", type=int, default=5400)
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()
    if not args.enable_signal_only:
        print("DEFAULT_OFF")
        return 0
    if not (30 <= args.poll_seconds <= 300 and 60 <= args.max_seconds <= 7200):
        raise SystemExit("BOUNDED_ONLY")
    allowed = {"PATH", "LANG", "LC_ALL", "TZ"}
    cleaned = {k: v for k, v in os.environ.items() if k in allowed}
    os.environ.clear()
    os.environ.update(cleaned)
    args.out.mkdir(parents=True, exist_ok=False)
    lock = (args.out / "writer.lock").open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def no_external_calls(event: str, arguments: tuple[Any, ...]) -> None:
        if event in (
            "socket.connect",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
        ):
            raise RuntimeError("NETWORK_ORDER_API_BLOCKED")
        if event == "open" and arguments and isinstance(arguments[0], (bytes, str)):
            if Path(os.fsdecode(arguments[0])).name in (
                "credentials",
                "credentials.json",
                "id_rsa",
                "id_ed25519",
            ):
                raise RuntimeError("CREDENTIAL_ACCESS_BLOCKED")

    sys.addaudithook(no_external_calls)
    started = int(time.time() * 1000)
    next_close = (started // HOUR + 1) * HOUR
    contract = json.loads((ROOT / "SIGNAL_ONLY_CONTRACT.json").read_bytes())
    status = {
        "schema": SCHEMA,
        "mode": "READONLY_ORIGINAL_PUBLIC_BANDRSI_PRICE_SIGNAL",
        "started_ms": started,
        "next_expected_closed_hour_ms": next_close,
        "source_sha256": contract["source_blob_sha256"],
        "contract_sha256": sha((ROOT / "SIGNAL_ONLY_CONTRACT.json").read_bytes()),
        "signal_symbols": contract["signal_only_target_symbols"],
        "source_1h_warmup_hours": HIST_HOURS,
        "orders": 0,
        "order_calls": 0,
        "virtual_fills": 0,
        "formal_shadow": False,
        "spot_original_stoploss": -0.25,
        "leveraged_execution": "BLOCKED",
        "source_received_at_unverified_historical": True,
        "phase": "WAIT_FIRST_NEW_CLOSED_HOUR",
        "signals": [],
        "decisions": [],
    }
    append_status(args.out, status)
    deadline = time.monotonic() + args.max_seconds
    try:
        while time.monotonic() < deadline:
            now = int(time.time() * 1000)
            if now < next_close:
                time.sleep(args.poll_seconds)
                continue
            if now - next_close >= HOUR:
                status["phase"] = "HOLD_SOURCE_HOUR_EXPIRED"
                append_status(args.out, status)
                break
            try:
                frames = {
                    symbol: price_frame(args.source, next_close, now, symbol)
                    for symbol in contract["signal_only_target_symbols"]
                }
                recorded = emit_signals(
                    frames, actual_decision_ms=now, close_ms=next_close
                )
                status["phase"] = "ONE_REAL_PROSPECTIVE_HOUR_SIGNAL_ONLY_RECORDED"
                status["decisions"] = recorded
                status["signals"] = [x for x in recorded if x["raw_enter_long"]]
                status["actual_received_at_ms"] = now
                append_status(args.out, status)
                print(
                    json.dumps(
                        {
                            "phase": status["phase"],
                            "decision_count": len(recorded),
                            "signal_count": len(status["signals"]),
                            "order_calls": 0,
                            "next_open_fill_authorized": False,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                break
            except (ValueError, RuntimeError, OSError, KeyError) as e:
                status["phase"] = "WAIT_SOURCE_INTEGRITY"
                status["source_hold_reason"] = type(e).__name__ + ":" + str(e)
                append_status(args.out, status)
                print(status["source_hold_reason"], flush=True)
                time.sleep(args.poll_seconds)
    finally:
        status["terminal_phase"] = status["phase"]
        status["observer_stopped"] = True
        append_status(args.out, status)
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
