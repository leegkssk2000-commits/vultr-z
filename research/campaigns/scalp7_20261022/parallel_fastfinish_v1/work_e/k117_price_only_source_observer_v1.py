"""Single-writer, bounded K117 PRICE-ONLY development observer of existing public 1m receipts.

Default OFF; no additional collector, order API or historical prospective credit.
Does NOT override formal PREAUTO/G4/G5 or unknown future broker funding.
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

import importlib

k = importlib.import_module("k117_adapter")
journal = importlib.import_module("k117_shadow_noorder_journal_v1")
quotes = importlib.import_module("k117_existing_ws_quote_mark_v1")

HALF_HOUR = 1_800_000
MINUTE = 60_000
BARS = 136
SOURCE_ROOT = Path("/home/z/z/runtime/scalp7_broad_v2_20260915/fresh_1m_verified")
FROZEN_ROOT = k.ROOT
SCHEMA = "k117.price_only.orderless_forward_development.v1"


def file_sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def source_snapshot(
    path: Path, now_ms: int, expected_close_ms: int, first_context_open_ms: int
) -> dict[str, pd.DataFrame]:
    contract = json.loads(k.PRICE_ONLY_CONTRACT.read_bytes())
    identity_raw = (path / "IDENTITY.json").read_bytes()
    identity = json.loads(identity_raw)
    identity_sha = file_sha(identity_raw)
    if (
        identity_sha != contract["source_identity_sha256"]
        or identity.get("schema") != contract["source_schema"]
        or identity.get("volume_units") != "UNKNOWN"
        or identity.get("synthetic_fill") is not False
        or sorted(identity.get("symbols", [])) != contract["required_context_symbols"]
        or identity.get("interval") != "1m"
    ):
        raise RuntimeError("SOURCE_IDENTITY_OR_SIX_SYMBOL_CONTRACT_MISMATCH")
    before = (path / "CURSOR.json").read_bytes()
    cursor = json.loads(before)
    if cursor["identity_sha256"] != identity_sha:
        raise RuntimeError("SOURCE_CURSOR_IDENTITY_MISMATCH")
    if expected_close_ms > (now_ms // HALF_HOUR) * HALF_HOUR:
        raise RuntimeError("INCOMPLETE_EXPECTED_NEXT_30M")
    latest_start = expected_close_ms - HALF_HOUR
    first_start = first_context_open_ms
    if first_start > latest_start - (BARS - 1) * HALF_HOUR:
        raise RuntimeError("FROZEN_WARMUP_CONTEXT_TOO_SHORT")
    end_exclusive = latest_start + HALF_HOUR
    frames = {}
    for symbol in contract["required_context_symbols"]:
        minutes: dict[int, tuple[tuple[float, ...], int]] = {}
        for item in reversed(cursor["symbols"][symbol]):
            receipt_raw = (path / item["path"]).read_bytes()
            if file_sha(receipt_raw) != item["sha256"]:
                raise RuntimeError("SOURCE_RECEIPT_SHA_MISMATCH")
            receipt = json.loads(receipt_raw)
            if receipt["end_exclusive_ms"] <= first_start:
                break
            if receipt["start_ms"] >= end_exclusive:
                continue
            if (
                receipt["symbol"] != symbol
                or receipt["http_status"] != 200
                or receipt["synthetic_fill"] is not False
                or receipt["received_at_ms"] > now_ms
            ):
                raise RuntimeError("SOURCE_RECEIPT_CLOCK_OR_SYMBOL_INVALID")
            packed = (path / receipt["normalized_path"]).read_bytes()
            if file_sha(packed) != receipt["normalized_sha256"]:
                raise RuntimeError("SOURCE_NORMALIZED_SHA_MISMATCH")
            for candle in csv.DictReader(io.StringIO(gzip.decompress(packed).decode())):
                minute = int(candle["timestamp_ms"])
                if minute < first_start or minute >= end_exclusive:
                    continue
                vals = tuple(float(candle[c]) for c in ("open", "high", "low", "close"))
                if minute in minutes and minutes[minute][0] != vals:
                    raise RuntimeError("SOURCE_MINUTE_REVISION_MISMATCH")
                if (
                    minute not in minutes
                    or receipt["received_at_ms"] < minutes[minute][1]
                ):
                    minutes[minute] = (vals, int(receipt["received_at_ms"]))
        out = []
        for stamp in range(first_start, end_exclusive, HALF_HOUR):
            section = [minutes.get(stamp + i * MINUTE) for i in range(30)]
            if any(x is None for x in section):
                raise RuntimeError("SIX_CONTEXT_30M_MISSING_MINUTE:" + symbol)
            prices = [x[0] for x in section if x is not None]
            latest_available = max(int(x[1]) for x in section if x is not None)
            values: dict[str, Any] = {
                "open_ts_ms": stamp,
                "close_ts_ms": stamp + HALF_HOUR,
                "available_ts_ms": max(latest_available, stamp + HALF_HOUR),
                "segment_id": "EXACT_BINGX_1M_PRICE_ONLY_CONTIG",
                "open": prices[0][0],
                "high": max(x[1] for x in prices),
                "low": min(x[2] for x in prices),
                "close": prices[-1][3],
            }
            if int(values["available_ts_ms"]) > now_ms:
                raise RuntimeError("SIX_CONTEXT_BAR_NOT_AVAILABLE")
            out.append(values)
        frames[symbol] = pd.DataFrame(out)
    after = (path / "CURSOR.json").read_bytes()
    if before != after:
        raise RuntimeError("SOURCE_CURSOR_CHANGED_DURING_SNAPSHOT")
    return frames


def safe_status(out: Path, body: dict[str, Any]) -> None:
    p = out / "STATUS.json"
    tmp = out / "STATUS.tmp"
    tmp.write_text(json.dumps(body, sort_keys=True, indent=2) + "\n")
    os.replace(tmp, p)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-development-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-seconds", type=int, default=1500)
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()
    if not args.enable_development_only:
        print("DEFAULT_OFF:EXPLICIT_DEVELOPMENT_ONLY_REQUIRED")
        return 0
    if not (1 <= args.max_seconds <= 604800 and 30 <= args.poll_seconds <= 300):
        raise SystemExit("BOUNDED_WATCH_REQUIRED")
    # Original no-order isolation: scrub env before any K117 native dependencies.
    safe_env = {"PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT"}
    cleaned = {key: value for key, value in os.environ.items() if key in safe_env}
    os.environ.clear()
    os.environ.update(cleaned)
    # One and only one observer; does NOT claim original B4 producer.
    args.out.mkdir(parents=True, exist_ok=args.resume)
    lock = (args.out / "writer.lock").open("a+b")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    started = int(time.time() * 1000)
    observer_source_sha = file_sha(Path(__file__).read_bytes())
    contract_raw = k.PRICE_ONLY_CONTRACT.read_bytes()
    contract = json.loads(contract_raw)
    expected_sha = file_sha(contract_raw)
    fit_path = (
        FROZEN_ROOT
        / "research/campaigns/scalp7_20260915/broad_rebuild_v2/FRESH_FORWARD_CONFIG_V2.json"
    )
    fit = json.loads(fit_path.read_text())["regime_fit"]
    if fit["sha256"] != contract["immutable_fit_sha256"]:
        raise RuntimeError("FROZEN_CONTEXT_FIT_HASH_MISMATCH")
    cost_path = (
        FROZEN_ROOT
        / "research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
    )
    raw_costs = cost_path.read_bytes()
    cost_data = json.loads(raw_costs)
    costs = cost_data["costs_bps"]
    d = k.dependencies()
    saved_checkpoint = None
    if args.resume:
        saved_checkpoint = journal.read_checkpoint(
            args.out, expected_sha, observer_source_sha
        )
        started = int(saved_checkpoint["status"]["started_at_ms"])
    observer = k.Adapter(
        enabled=True,
        fixture=False,
        development=True,
        started_at_ms=started,
        state=None if saved_checkpoint is None else saved_checkpoint["adapter"],
    )
    guard = {
        "volume_units": "UNKNOWN",
        "source_schema": contract["source_schema"],
        "identity_sha256": contract["source_identity_sha256"],
        "price_only_contract_sha256": expected_sha,
        "native_price_only_six_context_verified": True,
        "no_trade_volume_used": True,
        "synthetic_fill": False,
        "higher_timeframe_complete": True,
        "stale_authority": "K117_PRICE_ONLY_30M_COMPLETE_RECEIPT_V1",
        "stale_ms": HALF_HOUR,
    }
    k.native_price_only_source_guard(guard)

    # Block all exchange/order/client network or arbitrary subprocess calls.
    def audit(event: str, arguments: tuple[Any, ...]) -> None:
        if event in (
            "socket.connect",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.posix_spawn",
        ):
            raise RuntimeError("ORDER_AND_SOURCE_NETWORK_CALL_BLOCKED")
        if event == "open" and arguments and isinstance(arguments[0], (str, bytes)):
            if Path(os.fsdecode(arguments[0])).name in (
                "credentials",
                "credentials.json",
                "id_rsa",
                "id_ed25519",
            ):
                raise RuntimeError("CREDENTIAL_FILE_BLOCKED")

    sys.meta_path.insert(0, k.NoOrderImports())
    sys.addaudithook(audit)
    labels = contract["orderless_action_symbols"]
    next_close = (started // HALF_HOUR + 1) * HALF_HOUR
    first_context_open = next_close - BARS * HALF_HOUR
    status: dict[str, Any] = {
        "schema": SCHEMA,
        "phase": "WAIT_FIRST_PROSPECTIVE_CLOSED_30M",
        "started_at_ms": started,
        "first_context_open_ms": first_context_open,
        "next_expected_complete_close_ms": next_close,
        "identity": k.IDENTITY,
        "contract_sha256": expected_sha,
        "source_identity_sha256": guard["identity_sha256"],
        "six_market_context_required": True,
        "price_only_volume_units": "UNKNOWN",
        "action_symbols": labels,
        "formal_shadow_active": False,
        "formal_fresh_credit": False,
        "full_funding_verified": False,
        "cost_is_reference_model": True,
        "reference_cost_snapshot_sha256": file_sha(raw_costs),
        "reference_cost_components": {
            sym: cost_data["snapshots"][sym] for sym in labels
        },
        "virtual_fills": 0,
        "order_calls": 0,
        "signals": [],
        "decisions": [],
        "next_open_entry_holds": [],
        "reason": "DEVELOPMENT_ONLY_NO_FORMAL_PREAUTO",
    }
    if saved_checkpoint is not None:
        status = saved_checkpoint["status"]
        next_close = int(status["next_expected_complete_close_ms"])
        first_context_open = int(status["first_context_open_ms"])
        if status.get("next_open_entry_holds"):
            raise ValueError("UNRESOLVED_PREVIOUS_NEXT_OPEN_HOLD_CANNOT_RESUME")
        status["phase"] = "RESUMED_DEVELOPMENT_OBSERVATION_NO_ORDER"
    state_sha = journal.commit_checkpoint(
        args.out, status, observer.state, expected_sha, observer_source_sha
    )
    safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
    deadline = time.monotonic() + args.max_seconds
    try:
        while time.monotonic() < deadline:
            now = int(time.time() * 1000)
            target_close = next_close
            if target_close > (now // HALF_HOUR) * HALF_HOUR:
                time.sleep(args.poll_seconds)
                continue
            # A stale or interrupted observer is not permitted to label
            # historical bars as a fresh executable 30m signal on restart.
            if now - target_close >= HALF_HOUR:
                status["phase"] = "HOLD_EXPIRED_SOURCE_CLOSED_BAR"
                status["reason"] = "NEXT_OPEN_WITNESS_EXPIRED_NO_RETRO_EVALUATION"
                seal = journal.commit_checkpoint(
                    args.out, status, observer.state, expected_sha, observer_source_sha
                )
                safe_status(args.out, {**status, "checkpoint_sha256": seal})
                break
            try:
                frames = source_snapshot(
                    args.source, now, target_close, first_context_open
                )
                bound = d.helpers["bind_causal_context"](frames, fit)
                if any(
                    len(bound[s]) < 122 for s in contract["required_context_symbols"]
                ):
                    raise RuntimeError("NATIVE_WARMUP_121_NOT_AVAILABLE")
                common_last = {int(bound[s].iloc[-1].close_ts_ms) for s in bound}
                if len(common_last) != 1 or target_close not in common_last:
                    raise RuntimeError("SIX_CONTEXT_LAST_COMPLETE_MISMATCH")
                results = []
                for sym in labels:
                    item = observer.on_bar(
                        symbol=sym,
                        frame=bound[sym],
                        asof_ms=now,
                        source=guard,
                        fit=fit,
                        frozen_cost_bps=costs[sym],
                    )
                    timing = journal.next_open_eligibility(
                        expected_open_ms=target_close,
                        decision_ts_ms=now,
                        price_received_at_ms=int(bound[sym].iloc[-1].available_ts_ms),
                    )
                    quote = (
                        quotes.observe(
                            sym, decision_ts_ms=now, read_at_ms=int(time.time() * 1000)
                        )
                        if item["status"] == "SIGNAL"
                        else None
                    )
                    results.append(
                        {
                            "symbol": sym,
                            "close_ts_ms": target_close,
                            "next_open_eligibility": timing,
                            "post_decision_existing_ws_quote": quote,
                            "available_ts_ms": int(bound[sym].iloc[-1].available_ts_ms),
                            "status": item["status"],
                            "reason": item.get("reason"),
                            "signal": item.get("signal"),
                        }
                    )
                next_close += HALF_HOUR
                status["next_expected_complete_close_ms"] = next_close
                status["decisions"].extend(results)
                status["signals"].extend(x for x in results if x["status"] == "SIGNAL")
                for item in results:
                    if item["status"] == "SIGNAL":
                        status["next_open_entry_holds"].append(
                            {
                                "symbol": item["symbol"],
                                "close_ts_ms": target_close,
                                "reason": item["next_open_eligibility"],
                                "signal_sha256": k.digest(item["signal"]),
                                "actual_order_calls": 0,
                                "virtual_fill": False,
                            }
                        )
                status["phase"] = (
                    "HOLD_SIGNAL_NEXT_OPEN_UNVERIFIED"
                    if status["next_open_entry_holds"]
                    else "ACTIVE_DEVELOPMENT_OBSERVATION_NO_ORDER"
                )
                status["last_complete_30m_close_ms"] = target_close
                status["last_native_decision_ms"] = now
                status["source_six_context_bars"] = len(
                    bound[contract["required_context_symbols"][0]]
                )
                status["source_cursor_atomic_verified"] = True
                status["adapter_event_hash"] = k.digest(observer.state["events"])
                status["reason"] = "REAL_POST_START_COMPLETED_30M_OBSERVED_NO_ORDER"
                state_sha = journal.commit_checkpoint(
                    args.out, status, observer.state, expected_sha, observer_source_sha
                )
                safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
                print(
                    json.dumps(
                        {
                            "state": status["phase"],
                            "fresh_30m_close": target_close,
                            "native_4_decisions": len(results),
                            "signals": len(status["signals"]),
                            "orders": 0,
                            "formal": False,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                if status["next_open_entry_holds"]:
                    break  # Fail closed: do NOT backfill this unresolved entry.
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                status["reason"] = type(exc).__name__ + ":" + str(exc)
                status["phase"] = "WAIT_SOURCE_OR_NATIVE_GUARD"
                state_sha = journal.commit_checkpoint(
                    args.out, status, observer.state, expected_sha, observer_source_sha
                )
                safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
                print(
                    json.dumps({"state": status["phase"], "reason": status["reason"]}),
                    flush=True,
                )
            time.sleep(args.poll_seconds)
    finally:
        status["phase"] = "BOUNDED_DEVELOPMENT_OBSERVATION_STOPPED"
        state_sha = journal.commit_checkpoint(
            args.out, status, observer.state, expected_sha, observer_source_sha
        )
        safe_status(args.out, {**status, "checkpoint_sha256": state_sha})
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
