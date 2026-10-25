"""Read-only verified source-clock admission for frozen native Cluc 5m.

No market network requests, trades, collector changes or financial simulation.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any

SOURCE = Path("/home/z/z/runtime/scalp7_broad_v2_20260915/fresh_1m_verified")
OUT = Path(__file__).with_name("CLUC_FORWARD_CLOCK_AUDIT.json")
SYMBOLS = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT", "LINK-USDT")
START = dt.datetime(2026, 10, 25, 3, tzinfo=dt.timezone.utc)
END = dt.datetime(2026, 10, 25, 21, tzinfo=dt.timezone.utc)
MINUTE = 60_000
BAR = 5 * MINUTE
EXPECTED_IDENTITY_SHA = (
    "a5c2d7d6888b1cbf5e5c851c66b11127736fda94fd58f0484e19381c7e1efca9"
)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def inside(root: Path, relative: str) -> Path:
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError("SOURCE_PATH_TRAVERSAL")
    return p


def read_source() -> dict[str, Any]:
    identity_raw = (SOURCE / "IDENTITY.json").read_bytes()
    identity = json.loads(identity_raw)
    if (
        digest(identity_raw) != EXPECTED_IDENTITY_SHA
        or identity.get("interval") != "1m"
        or identity.get("volume_units") != "UNKNOWN"
        or identity.get("synthetic_fill") is not False
        or set(identity.get("symbols", [])) != set(SYMBOLS)
    ):
        raise RuntimeError("SOURCE_IDENTITY_CHANGED")

    cursor_raw = (SOURCE / "CURSOR.json").read_bytes()
    cursor = json.loads(cursor_raw)
    if cursor["identity_sha256"] != EXPECTED_IDENTITY_SHA:
        raise RuntimeError("SOURCE_CURSOR_IDENTITY_CHANGED")
    begin = int(START.timestamp() * 1000)
    end = int(END.timestamp() * 1000)
    rows_by_symbol: dict[str, dict] = {}
    receipts_by_symbol: dict[str, list[str]] = {}
    for symbol in SYMBOLS:
        observed: dict[int, tuple[tuple[float, ...], int]] = {}
        used = []
        for pointer in reversed(cursor["symbols"][symbol]):
            receipt_path = inside(SOURCE, pointer["path"])
            receipt_raw = receipt_path.read_bytes()
            if digest(receipt_raw) != pointer["sha256"]:
                raise RuntimeError("RECEIPT_SHA_CHANGED:" + symbol)
            receipt = json.loads(receipt_raw)
            if int(receipt["end_exclusive_ms"]) <= begin:
                break
            if int(receipt["start_ms"]) >= end:
                continue
            if (
                receipt["symbol"] != symbol
                or receipt["http_status"] != 200
                or receipt["synthetic_fill"] is not False
            ):
                raise RuntimeError("NON_NATIVE_RECEIPT:" + symbol)
            blob = inside(SOURCE, receipt["normalized_path"]).read_bytes()
            if digest(blob) != receipt["normalized_sha256"]:
                raise RuntimeError("NORMALIZED_SHA_CHANGED:" + symbol)
            rx_ms = int(receipt["received_at_ms"])
            used.append(
                pointer["path"]
                + ":"
                + pointer["sha256"]
                + ":"
                + receipt["normalized_sha256"]
            )
            for row in csv.DictReader(io.StringIO(gzip.decompress(blob).decode())):
                t = int(row["timestamp_ms"])
                if not begin <= t < end:
                    continue
                o, h, low, c, v = (
                    float(row[col])
                    for col in ("open", "high", "low", "close", "volume")
                )
                if (
                    t % MINUTE
                    or not all(math.isfinite(x) for x in (o, h, low, c, v))
                    or min(o, h, low, c) <= 0
                    or v < 0
                    or h < max(o, low, c)
                    or low > min(o, h, c)
                ):
                    raise RuntimeError("INVALID_NATIVE_MINUTE:" + symbol)
                value = (o, h, low, c, v)
                prior = observed.get(t)
                if prior and prior[0] != value:
                    raise RuntimeError("SOURCE_MINUTE_REVISION:" + symbol)
                if prior is None or rx_ms < prior[1]:
                    observed[t] = (value, rx_ms)

        gaps = [t for t in range(begin, end, MINUTE) if t not in observed]
        if gaps:
            raise RuntimeError(f"MISSING_NATIVE_MINUTES:{symbol}:{len(gaps)}")
        rows_by_symbol[symbol] = observed
        receipts_by_symbol[symbol] = used

    result: dict[str, Any] = {
        "schema": "zel.cluc.5m.readonly_forward_source_latency.v1",
        "strategy": "Freqtrade/ClucMay72018 native 5m; source original frozen in PR1475",
        "source": str(SOURCE),
        "source_identity_sha256": digest(identity_raw),
        "source_cursor_snapshot_sha256": digest(cursor_raw),
        "volume_units": "UNKNOWN (not relabeled)",
        "start_inclusive_utc": START.isoformat(),
        "end_exclusive_utc": END.isoformat(),
        "actual_complete_one_minute_source": True,
        "period_preselected": True,
        "source_api_calls": 0,
        "orders": 0,
        "virtual_fills": 0,
        "fresh_trades": 0,
        "not_future_performance_proof": True,
        "symbols": {},
    }
    total_bars = total_after_next_close = 0
    for symbol in SYMBOLS:
        mins = rows_by_symbol[symbol]
        latency = []
        for close in range(begin + BAR, end + 1, BAR):
            actual_first_asof = max(
                mins[t][1] for t in range(close - BAR, close, MINUTE)
            )
            latency_ms = actual_first_asof - close
            if latency_ms < 0:
                raise RuntimeError("BAR_AVAILABLE_BEFORE_CLOSED:" + symbol)
            latency.append(latency_ms / MINUTE)
        s = sorted(latency)
        late = sum(t >= 5 for t in latency)
        total_bars += len(latency)
        total_after_next_close += late
        result["symbols"][symbol] = {
            "minute_rows_verified": len(mins),
            "five_minute_bars_verified": len(latency),
            "first_available_after_source_bar_close": sum(t > 0 for t in latency),
            "available_only_at_or_after_next_5m_close": late,
            "latency_median_min": round(s[len(s) // 2], 3),
            "latency_p90_min": round(s[int(0.9 * (len(s) - 1))], 3),
            "latency_max_min": round(s[-1], 3),
            "receipt_count": len(receipts_by_symbol[symbol]),
            "receipt_chain_sha256": digest(
                "\n".join(sorted(receipts_by_symbol[symbol])).encode()
            ),
        }
    result["total_5m_bars"] = total_bars
    result["late_beyond_one_full_5m_bar"] = total_after_next_close
    result["late_beyond_one_full_5m_bar_pct"] = round(
        100 * total_after_next_close / total_bars, 3
    )
    result["original_next_open_fill_verified"] = 0
    result["execution_admission"] = (
        "HOLD_CURRENT_PUBLIC_COLLECTOR_CANNOT_PROVE_NATIVE_NEXT_OPEN"
    )
    return result


if __name__ == "__main__":
    r = read_source()
    raw = (json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    OUT.write_bytes(raw)
    print("AUDIT_SHA256", digest(raw))
    print(
        json.dumps(
            {
                k: v
                for k, v in r.items()
                if k
                in (
                    "start_inclusive_utc",
                    "end_exclusive_utc",
                    "total_5m_bars",
                    "late_beyond_one_full_5m_bar",
                    "late_beyond_one_full_5m_bar_pct",
                    "execution_admission",
                    "original_next_open_fill_verified",
                )
            },
            sort_keys=True,
        )
    )
    for k, v in r["symbols"].items():
        print(
            k,
            "p50_min",
            v["latency_median_min"],
            "p90_min",
            v["latency_p90_min"],
            "late",
            v["available_only_at_or_after_next_5m_close"],
        )
