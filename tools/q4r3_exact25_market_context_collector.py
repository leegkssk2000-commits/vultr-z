from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def parse_symbols(payload: Mapping[str, Any], required_core: Sequence[str]) -> list[str]:
    raw = payload.get("symbols")
    symbols = [str(item).upper() for item in raw] if isinstance(raw, list) else []
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise RuntimeError("SYMBOLS_MISSING")
    missing = sorted(set(str(item).upper() for item in required_core) - set(symbols))
    if missing:
        raise RuntimeError(f"CORE_SYMBOLS_MISSING:{','.join(missing)}")
    return symbols


def build_exchange() -> Any:
    try:
        import ccxt  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"CCXT_IMPORT_FAILED:{type(exc).__name__}:{exc}") from exc
    exchange = ccxt.bingx({
        "enableRateLimit": True,
        "timeout": 20_000,
        "options": {"defaultType": "swap"},
    })
    if getattr(exchange, "apiKey", None) or getattr(exchange, "secret", None):
        raise RuntimeError("PRIVATE_CREDENTIALS_FORBIDDEN")
    return exchange


def resolve_symbol(exchange: Any, token: str) -> str:
    compact = token.upper().replace("/", "").replace(":", "")
    base = compact[:-4] if compact.endswith("USDT") else compact
    markets = exchange.markets or exchange.load_markets()
    for candidate in (token, f"{base}/USDT:USDT", f"{base}/USDT"):
        if candidate in markets:
            return candidate
    for symbol, market in markets.items():
        market_id = str(market.get("id") or "").upper().replace("-", "").replace("_", "")
        if market_id == compact and str(market.get("quote") or "").upper() == "USDT":
            return str(symbol)
    raise RuntimeError(f"MARKET_NOT_FOUND:{token}")


def closed_frame(rows: Any, minimum: int = 60) -> pd.DataFrame:
    if not isinstance(rows, list) or len(rows) < minimum:
        raise RuntimeError(f"OHLCV_INSUFFICIENT:{len(rows) if isinstance(rows, list) else -1}")
    frame = pd.DataFrame(rows, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp_ms").drop_duplicates("timestamp_ms")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if len(frame) and int(frame.iloc[-1]["timestamp_ms"]) + 60_000 > now_ms - 2_000:
        frame = frame.iloc[:-1]
    if len(frame) < minimum:
        raise RuntimeError(f"CLOSED_OHLCV_INSUFFICIENT:{len(frame)}")
    return frame.reset_index(drop=True)


def nested_number(payload: Mapping[str, Any] | None, keys: Sequence[str]) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        value = finite(payload.get(key))
        if value is not None:
            return value
    info = payload.get("info")
    if isinstance(info, Mapping):
        for key in keys:
            value = finite(info.get(key))
            if value is not None:
                return value
    return None


def compute_context(
    token: str,
    frame: pd.DataFrame,
    ticker: Mapping[str, Any] | None,
    funding: Mapping[str, Any] | None,
    open_interest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    prior_close = close.shift(1)
    true_range = pd.concat([(high - low), (high - prior_close).abs(), (low - prior_close).abs()], axis=1).max(axis=1)
    atr = float(true_range.rolling(14, min_periods=14).mean().iloc[-1])
    price = float(close.iloc[-1])
    returns = close.pct_change().dropna().tail(60)
    realized_volatility = float(returns.std(ddof=0) * math.sqrt(max(len(returns), 1))) if len(returns) else 0.0
    ema_fast = close.ewm(span=20, adjust=False).mean()
    ema_slow = close.ewm(span=100, adjust=False).mean()
    trend_strength = abs(float(ema_fast.iloc[-1] - ema_slow.iloc[-1])) / max(atr, 1e-12)
    trend_direction = "long" if ema_fast.iloc[-1] > ema_slow.iloc[-1] else "short" if ema_fast.iloc[-1] < ema_slow.iloc[-1] else "neutral"
    vol_mean = float(volume.tail(60).mean())
    vol_std = float(volume.tail(60).std(ddof=0))
    volume_zscore = (float(volume.iloc[-1]) - vol_mean) / vol_std if vol_std > 0 else 0.0

    bid = nested_number(ticker, ("bid", "bidPrice"))
    ask = nested_number(ticker, ("ask", "askPrice"))
    spread_bps = (ask - bid) / ((ask + bid) / 2.0) * 10_000.0 if bid and ask and ask >= bid else None
    funding_rate = nested_number(funding, ("fundingRate", "funding_rate", "lastFundingRate"))
    mark = nested_number(ticker, ("mark", "markPrice")) or nested_number(funding, ("markPrice", "mark"))
    index = nested_number(ticker, ("index", "indexPrice")) or nested_number(funding, ("indexPrice", "index"))
    basis_bps = (mark - index) / index * 10_000.0 if mark is not None and index not in (None, 0.0) else None
    oi = nested_number(open_interest, ("openInterestAmount", "openInterest", "open_interest", "amount"))
    bar_ts_ms = int(frame.iloc[-1]["timestamp_ms"])
    bar_ts = datetime.fromtimestamp(bar_ts_ms / 1000.0, tz=timezone.utc).isoformat()
    snapshot_id = hashlib.sha256(f"EXACT25_EDGE_V1|{token}|{bar_ts_ms}".encode()).hexdigest()[:32]
    return {
        "schema": "q4r3_exact25_market_context_snapshot_v1",
        "snapshot_id": snapshot_id,
        "epoch_id": "EXACT25_EDGE_V1",
        "measurement_namespace": "EXACT25_EDGE_V1",
        "symbol": token,
        "bar_ts": bar_ts,
        "bar_epoch": bar_ts_ms / 1000.0,
        "price": price,
        "atr_pct": atr / max(price, 1e-12) * 100.0,
        "realized_volatility_pct": realized_volatility * 100.0,
        "trend_strength": trend_strength,
        "trend_direction": trend_direction,
        "volume_zscore": volume_zscore,
        "spread_bps": spread_bps,
        "funding_8h_pct": funding_rate * 100.0 if funding_rate is not None else None,
        "open_interest": oi,
        "basis_bps": basis_bps,
        "observer_only": True,
        "private_credentials_used": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "captured_at": now_iso(),
    }


def append_once(path: Path, row: Mapping[str, Any], retention_rows: int) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        lines = handle.read().splitlines()
        event_id = str(row.get("snapshot_id") or "")
        for line in lines[-2000:]:
            try:
                prior = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(prior, dict) and str(prior.get("snapshot_id") or "") == event_id:
                return False
        lines.append(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
        if retention_rows > 0 and len(lines) > retention_rows:
            lines = lines[-retention_rows:]
        handle.seek(0)
        handle.truncate(0)
        handle.write("\n".join(lines) + ("\n" if lines else ""))
        handle.flush()
        os.fsync(handle.fileno())
        return True


def collect(exchange: Any, token: str, market_symbol: str, timeframe: str, candle_limit: int) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    frame = closed_frame(exchange.fetch_ohlcv(market_symbol, timeframe=timeframe, limit=candle_limit))
    try:
        ticker = exchange.fetch_ticker(market_symbol)
    except Exception as exc:
        ticker = {}
        errors.append(f"ticker:{type(exc).__name__}")
    try:
        funding = exchange.fetch_funding_rate(market_symbol) if exchange.has.get("fetchFundingRate") else {}
    except Exception as exc:
        funding = {}
        errors.append(f"funding:{type(exc).__name__}")
    try:
        open_interest = exchange.fetch_open_interest(market_symbol) if exchange.has.get("fetchOpenInterest") else {}
    except Exception as exc:
        open_interest = {}
        errors.append(f"open_interest:{type(exc).__name__}")
    return compute_context(token, frame, ticker, funding, open_interest), errors


def run(args: argparse.Namespace) -> int:
    ssot = load_json(args.ssot.resolve())
    producer = load_json(args.producer_status.resolve())
    safety = ssot.get("safety") if isinstance(ssot.get("safety"), dict) else {}
    if safety.get("observer_only") is not True:
        raise RuntimeError("OBSERVER_ONLY_SSOT_REQUIRED")
    for key in ("paper_enabled", "live_enabled", "order_enabled"):
        if producer.get(key) not in (False, None):
            raise RuntimeError(f"UNSAFE_PRODUCER_FLAG:{key}")
    symbols = parse_symbols(producer, ssot.get("required_core_symbols", []))
    cfg = ssot.get("market_context") if isinstance(ssot.get("market_context"), dict) else {}
    exchange = build_exchange()
    exchange.load_markets()
    appended = 0
    errors: dict[str, list[str]] = {}
    snapshots: list[dict[str, Any]] = []
    for token in symbols:
        try:
            market_symbol = resolve_symbol(exchange, token)
            row, row_errors = collect(
                exchange,
                token,
                market_symbol,
                str(cfg.get("timeframe") or "1m"),
                int(cfg.get("candle_limit") or 240),
            )
            snapshots.append(row)
            if append_once(args.ledger.resolve(), row, int(cfg.get("snapshot_retention_rows") or 50000)):
                appended += 1
            if row_errors:
                errors[token] = row_errors
        except Exception as exc:
            errors[token] = [f"{type(exc).__name__}:{exc}"]
    status = {
        "schema": "q4r3_exact25_market_context_collector_status_v1",
        "state": "RUNNING" if snapshots else "DEGRADED",
        "updated_at": now_iso(),
        "epoch_id": ssot.get("expected_epoch"),
        "symbols": symbols,
        "snapshot_count": len(snapshots),
        "appended_count": appended,
        "error_count": len(errors),
        "errors": errors,
        "ledger_path": str(args.ledger.resolve()),
        "observer_only": True,
        "private_credentials_used": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "historical_backfill_allowed": False,
        "action": "hold",
    }
    atomic_json(args.status.resolve(), status)
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0 if snapshots else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer-status", type=Path, required=True)
    parser.add_argument("--ssot", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
