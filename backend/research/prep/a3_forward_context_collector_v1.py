from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild.policy_kernel_v1 import atr, ema

KLINE_API = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"
DEPTH_API = "https://open-api.bingx.com/openApi/swap/v2/quote/depth"
FUNDING_API = "https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate"
OI_API = "https://open-api.bingx.com/openApi/swap/v2/quote/openInterest"
SYMBOLS = ("BTC-USDT", "ETH-USDT")
HOUR_MS = 3_600_000
HISTORY_CAP = 480

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "action": "hold",
}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def request_json(url: str, params: dict[str, Any]) -> Any:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "zel-a3-research/1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.loads(response.read().decode())
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise RuntimeError(f"BINGX_API_ERROR:{payload.get('code')}:{payload.get('msg')}")
    return payload


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    return []


def fetch_bars(symbol: str, limit: int = 120) -> list[dict[str, float | int]]:
    payload = request_json(KLINE_API, {"symbol": symbol, "interval": "1h", "limit": limit})
    out: list[dict[str, float | int]] = []
    for row in _rows(payload):
        if isinstance(row, dict):
            t = row.get("time") or row.get("openTime") or row.get("timestamp")
            if t is None:
                continue
            out.append({
                "ts_ms": int(t), "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]),
                "volume": float(row.get("volume") or row.get("vol") or row.get("baseVolume") or 0.0),
            })
        elif isinstance(row, list) and len(row) >= 5:
            out.append({"ts_ms": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5] if len(row) > 5 else 0.0)})
    return sorted({int(x["ts_ms"]): x for x in out}.values(), key=lambda x: int(x["ts_ms"]))


def fetch_depth(symbol: str) -> tuple[float, float]:
    payload = request_json(DEPTH_API, {"symbol": symbol, "limit": 50})
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    bids, asks = data.get("bids") or [], data.get("asks") or []
    if not bids or not asks:
        raise RuntimeError("DEPTH_EMPTY")
    bid = float(bids[0][0]); ask = float(asks[0][0])
    if bid <= 0 or ask <= bid:
        raise RuntimeError("DEPTH_TOP_INVALID")
    mid = (bid + ask) / 2.0
    spread_bps = (ask - bid) / mid * 10_000.0
    bid_depth = sum(float(x[0]) * float(x[1]) for x in bids if len(x) >= 2)
    ask_depth = sum(float(x[0]) * float(x[1]) for x in asks if len(x) >= 2)
    return spread_bps, min(bid_depth, ask_depth)


def fetch_funding_pct(symbol: str) -> float:
    payload = request_json(FUNDING_API, {"symbol": symbol, "limit": 10})
    rows = _rows(payload)
    vals: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("fundingRate") if row.get("fundingRate") is not None else row.get("rate")
        if raw is None:
            continue
        ts = int(row.get("fundingTime") or row.get("time") or row.get("timestamp") or 0)
        vals.append((ts, float(raw)))
    if not vals:
        raise RuntimeError("FUNDING_RATE_MISSING")
    vals.sort(key=lambda x: x[0])
    return vals[-1][1] * 100.0


def _find_numeric(node: Any, keys: tuple[str, ...]) -> float | None:
    if isinstance(node, dict):
        for key in keys:
            if node.get(key) is not None:
                try:
                    return float(node[key])
                except (TypeError, ValueError):
                    pass
        for value in node.values():
            found = _find_numeric(value, keys)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_numeric(value, keys)
            if found is not None:
                return found
    return None


def fetch_open_interest(symbol: str) -> float:
    payload = request_json(OI_API, {"symbol": symbol})
    value = _find_numeric(payload, ("openInterest", "openInterestValue", "open_interest", "oi", "value"))
    if value is None or not math.isfinite(value) or value <= 0:
        raise RuntimeError("OPEN_INTEREST_MISSING_OR_INVALID")
    return value


def iso_ms(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def previous_oi(prior_rows: list[dict[str, Any]], symbol: str, closed_bar_ts: str) -> float | None:
    eligible = [x for x in prior_rows if x.get("symbol") == symbol and str(x.get("closed_bar_ts_utc") or "") < closed_bar_ts and x.get("open_interest") is not None]
    if not eligible:
        return None
    eligible.sort(key=lambda x: str(x.get("closed_bar_ts_utc") or ""))
    try:
        return float(eligible[-1]["open_interest"])
    except Exception:
        return None


def collect_symbol(symbol: str, prior_rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    bars = fetch_bars(symbol)
    latest_closed_open_ms = (int(now.timestamp() * 1000) // HOUR_MS) * HOUR_MS - HOUR_MS
    closed = [x for x in bars if int(x["ts_ms"]) <= latest_closed_open_ms]
    if len(closed) < 55:
        raise RuntimeError(f"INSUFFICIENT_CLOSED_BARS:{symbol}:{len(closed)}")
    closed = closed[-100:]
    closes = [float(x["close"]) for x in closed]
    e50 = ema(closes, 50)
    a14 = atr(closed, 14)
    trend_strength = (float(e50[-1]) - float(e50[-4])) / max(float(a14), 1e-12)
    log_returns = [math.log(closes[i] / closes[i-1]) for i in range(max(1, len(closes)-24), len(closes))]
    if len(log_returns) < 12:
        raise RuntimeError("REALIZED_VOL_WARMUP")
    realized_vol_pct = statistics.pstdev(log_returns) * 100.0
    spread_bps, depth_usdt = fetch_depth(symbol)
    funding_pct = fetch_funding_pct(symbol)
    oi = fetch_open_interest(symbol)
    closed_ts = iso_ms(int(closed[-1]["ts_ms"]))
    prev = previous_oi(prior_rows, symbol, closed_ts)
    oi_change = None if prev in (None, 0.0) else 100.0 * (oi / prev - 1.0)
    event_ts = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    valid = oi_change is not None and all(math.isfinite(float(x)) for x in (trend_strength, realized_vol_pct, spread_bps, depth_usdt, funding_pct, oi_change))
    return {
        "ts_utc": event_ts,
        "closed_bar_ts_utc": closed_ts,
        "symbol": symbol,
        "trend_strength": trend_strength,
        "realized_vol_pct": realized_vol_pct,
        "spread_bps": spread_bps,
        "depth_usdt": depth_usdt,
        "funding_8h_pct": funding_pct,
        "oi_change_pct": oi_change,
        "open_interest": oi,
        "session_utc_hour": datetime.fromisoformat(closed_ts.replace("Z", "+00:00")).hour,
        "valid_for_a3": valid,
        "invalid_reason": None if valid else "OI_CHANGE_WARMUP_FIRST_OBSERVATION",
        "outcome_fields_used": [],
    }


def evaluate(prior: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    prior_rows = [x for x in (prior.get("rows") or []) if isinstance(x, dict)]
    new_rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for symbol in SYMBOLS:
        try:
            new_rows.append(collect_symbol(symbol, prior_rows + new_rows, current))
        except Exception as exc:
            blockers.append(f"{symbol}:{type(exc).__name__}:{exc}")
    merged = prior_rows[:]
    by_key = {(str(x.get("symbol")), str(x.get("closed_bar_ts_utc"))): x for x in merged}
    for row in new_rows:
        by_key[(str(row.get("symbol")), str(row.get("closed_bar_ts_utc")))] = row
    merged = sorted(by_key.values(), key=lambda x: (str(x.get("closed_bar_ts_utc")), str(x.get("symbol"))))[-HISTORY_CAP:]
    valid_count = sum(1 for x in merged if x.get("valid_for_a3") is True)
    current_valid = sum(1 for x in new_rows if x.get("valid_for_a3") is True)
    if blockers:
        state = "HOLD_A3_FORWARD_CONTEXT_SOURCE"
    elif len(new_rows) != len(SYMBOLS):
        state = "HOLD_A3_FORWARD_CONTEXT_INCOMPLETE"
    elif current_valid < len(SYMBOLS):
        state = "HOLD_A3_FORWARD_CONTEXT_OI_WARMUP"
    else:
        state = "PASS_A3_FORWARD_CONTEXT_CAPTURE"
    result = {
        "schema_version": "zel.a3.forward_context.v1",
        "state": state,
        "captured_at_utc": current.isoformat().replace("+00:00", "Z"),
        "symbols": list(SYMBOLS),
        "new_rows": new_rows,
        "rows": merged,
        "row_count": len(merged),
        "valid_row_count": valid_count,
        "current_valid_count": current_valid,
        "blockers": blockers,
        "source_endpoints": {"kline": KLINE_API, "depth": DEPTH_API, "funding": FUNDING_API, "open_interest": OI_API},
        "strategy_mutated": False,
        "outcome_fields_used": False,
        **AUTH,
    }
    result["receipt_sha256"] = stable_sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prior", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a3_forward_context_v1.json"))
    args = ap.parse_args()
    prior = {}
    if args.prior and args.prior.exists():
        prior = json.loads(args.prior.read_text(encoding="utf-8"))
    result = evaluate(prior)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "row_count": result["row_count"], "valid_row_count": result["valid_row_count"], "current_valid_count": result["current_valid_count"], "blockers": result["blockers"], "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
