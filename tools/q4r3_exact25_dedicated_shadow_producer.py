from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

import pandas as pd

EPOCH_ID = "EXACT25_EDGE_V1"
NAMESPACE = "EXACT25_EDGE_V1"
EXPECTED_COUNT = 25
CORE_CANARY_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
_STOP = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fnum(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def parse_time(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return number if 1_500_000_000 <= number <= 2_100_000_000 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return parse_time(float(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    value = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def append_jsonl_once(path: Path, row: Mapping[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    event_id = str(row.get("event_id") or "")
    if not event_id:
        raise RuntimeError("EVENT_ID_REQUIRED")
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                prior = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(prior, dict) and str(prior.get("event_id") or "") == event_id:
                return False
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def require_environment() -> None:
    expected = {
        "Q4R3_SHADOW_ONLY": "1",
        "Q4R3_PAPER_ENABLED": "0",
        "Q4R3_LIVE_ENABLED": "0",
        "Q4R3_ORDER_ENABLED": "0",
        "Q4R3_HISTORICAL_BACKFILL_ALLOWED": "0",
        "Q4R3_EPOCH_ID": EPOCH_ID,
        "Q4R3_PRODUCER_STAGE": "FIRST_FORWARD_CANARY",
    }
    for key, value in expected.items():
        actual = os.environ.get(key)
        if actual != value:
            raise RuntimeError(f"ENVIRONMENT_GATE_MISMATCH:{key}:expected={value}:actual={actual}")


def request_stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def parse_symbols(raw: str | None) -> List[str]:
    tokens = [token.strip().upper() for token in str(raw or "").split(",") if token.strip()]
    if not tokens:
        tokens = list(CORE_CANARY_SYMBOLS)
    result: List[str] = []
    for token in tokens:
        compact = token.replace("/", "").replace(":", "")
        if not compact.endswith("USDT"):
            raise ValueError(f"ONLY_USDT_SYMBOLS_ALLOWED:{token}")
        if token not in result:
            result.append(token)
    return result


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
        raise RuntimeError("PRIVATE_EXCHANGE_CREDENTIALS_FORBIDDEN")
    return exchange


def resolve_market_symbol(exchange: Any, token: str) -> str:
    compact = token.upper().replace("/", "").replace(":", "")
    base = compact[:-4] if compact.endswith("USDT") else compact
    candidates = [token, f"{base}/USDT:USDT", f"{base}/USDT"]
    markets = exchange.markets or exchange.load_markets()
    for candidate in candidates:
        if candidate in markets:
            return candidate
    for symbol, market in markets.items():
        market_id = str(market.get("id") or "").upper().replace("-", "").replace("_", "")
        if market_id == compact and str(market.get("quote") or "").upper() == "USDT":
            return str(symbol)
    raise RuntimeError(f"BINGX_MARKET_NOT_FOUND:{token}")


def timeframe_seconds(timeframe: str) -> int:
    units = {"m": 60, "h": 3600}
    unit = timeframe[-1:]
    if unit not in units:
        raise ValueError(f"UNSUPPORTED_TIMEFRAME:{timeframe}")
    amount = int(timeframe[:-1])
    if amount <= 0:
        raise ValueError(f"UNSUPPORTED_TIMEFRAME:{timeframe}")
    return amount * units[unit]


def fetch_closed_frame(exchange: Any, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not isinstance(rows, list) or len(rows) < 180:
        raise RuntimeError(f"OHLCV_INSUFFICIENT:{symbol}:{len(rows) if isinstance(rows, list) else -1}")
    frame = pd.DataFrame(rows, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
    frame = frame.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp_ms").drop_duplicates("timestamp_ms")
    seconds = timeframe_seconds(timeframe)
    now_ms = int(time.time() * 1000)
    if len(frame) and int(frame.iloc[-1]["timestamp_ms"]) + seconds * 1000 > now_ms - 2000:
        frame = frame.iloc[:-1]
    if len(frame) < 170:
        raise RuntimeError(f"CLOSED_OHLCV_INSUFFICIENT:{symbol}:{len(frame)}")
    return frame.reset_index(drop=True)


def load_registry(root: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    loader_dir = root / "backend/engine"
    manifest_path = root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
    binding_path = root / "backend/config/q4r3_exact25_shadow_binding_v1.json"
    if not loader_dir.is_dir() or not manifest_path.is_file() or not binding_path.is_file():
        raise RuntimeError("EXACT25_ACTIVE_BINDING_INPUT_MISSING")
    sys.path.insert(0, str(loader_dir))
    try:
        from q4r3_exact25_shadow_manifest_loader import load_shadow_registry  # type: ignore
        registry = load_shadow_registry(root, manifest_path, binding_path)
    finally:
        if sys.path and sys.path[0] == str(loader_dir):
            sys.path.pop(0)
    binding = load_json(binding_path)
    if len(registry) != EXPECTED_COUNT:
        raise RuntimeError(f"REGISTRY_NOT_EXACT25:{len(registry)}")
    if binding.get("shadow_enabled") is not True:
        raise RuntimeError("SHADOW_BINDING_NOT_ENABLED")
    for key in ("paper_enabled", "live_enabled", "order_enabled", "write_enabled"):
        if binding.get(key) is not False:
            raise RuntimeError(f"UNSAFE_BINDING_FLAG:{key}")
    return binding, registry


def feature_snapshot(frame: pd.DataFrame) -> Dict[str, Any]:
    recent = frame.tail(240).copy()
    close = recent["close"].astype(float)
    fast = close.ewm(span=60, adjust=False).mean()
    slow = close.ewm(span=180, adjust=False).mean()
    price = float(close.iloc[-1])
    if float(fast.iloc[-1]) > float(slow.iloc[-1]) and float(fast.iloc[-1]) >= float(fast.iloc[-4]):
        bias = "long"
    elif float(fast.iloc[-1]) < float(slow.iloc[-1]) and float(fast.iloc[-1]) <= float(fast.iloc[-4]):
        bias = "short"
    else:
        bias = "neutral"

    swing = recent.tail(50)
    range_high = float(swing["high"].max())
    range_low = float(swing["low"].min())
    width = max(range_high - range_low, 1e-12)
    range_position = min(max((price - range_low) / width, 0.0), 1.0)
    premium_discount = "discount" if range_position < 0.5 else "premium"
    retracement_depth = None
    if bias == "long":
        retracement_depth = 1.0 - range_position
    elif bias == "short":
        retracement_depth = range_position
    ote = retracement_depth is not None and 0.5 <= retracement_depth <= 0.79

    highs = swing["high"].astype(float).tolist()
    lows = swing["low"].astype(float).tolist()
    local_highs = [highs[index] for index in range(1, len(highs) - 1) if highs[index] > highs[index - 1] and highs[index] >= highs[index + 1]]
    local_lows = [lows[index] for index in range(1, len(lows) - 1) if lows[index] < lows[index - 1] and lows[index] <= lows[index + 1]]
    if len(local_highs) >= 2 and len(local_lows) >= 2:
        if local_highs[-1] > local_highs[-2] and local_lows[-1] > local_lows[-2]:
            sequence = "HH_HL"
        elif local_highs[-1] < local_highs[-2] and local_lows[-1] < local_lows[-2]:
            sequence = "LH_LL"
        else:
            sequence = "MIXED"
    else:
        sequence = "UNRESOLVED"

    last = recent.iloc[-1]
    previous = recent.iloc[-2]
    if bias == "long":
        reversal = bool(float(last["close"]) > float(last["open"]) and float(last["close"]) > float(previous["close"]))
        invalidation = range_low
    elif bias == "short":
        reversal = bool(float(last["close"]) < float(last["open"]) and float(last["close"]) < float(previous["close"]))
        invalidation = range_high
    else:
        reversal = False
        invalidation = range_low if price - range_low <= range_high - price else range_high

    timestamp = pd.Timestamp(last["timestamp"])
    hour = int(timestamp.hour)
    if 0 <= hour < 7:
        session = "asia"
    elif 7 <= hour < 13:
        session = "london"
    elif 13 <= hour < 16:
        session = "london_newyork_overlap"
    elif 16 <= hour < 22:
        session = "newyork"
    else:
        session = "off_session"

    return {
        "observer_only": True,
        "htf_bias": bias,
        "swing_sequence": sequence,
        "dealing_range_position": round(range_position, 8),
        "premium_discount_side": premium_discount,
        "ote_depth": round(retracement_depth, 8) if retracement_depth is not None else None,
        "ote_0_5_0_79": bool(ote),
        "ltf_reversal_confirm": reversal,
        "session_window": session,
        "invalidation_swing_price": invalidation,
        "invalidation_swing_distance_pct": round(abs(price - invalidation) / max(price, 1e-12) * 100.0, 8),
    }


def blank_state() -> Dict[str, Any]:
    return {
        "schema": "q4r3_exact25_dedicated_shadow_producer_state_v1",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "epoch_id": EPOCH_ID,
        "last_processed": {},
        "positions": {},
        "cycle_count": 0,
        "signal_count": 0,
        "open_count": 0,
        "close_count": 0,
        "duplicate_close_count": 0,
    }


def position_key(strategy_id: str, symbol: str, timeframe: str) -> str:
    return f"{strategy_id}|{symbol}|{timeframe}"


def deterministic_position_id(strategy_id: str, symbol: str, timeframe: str, entry_ts: str) -> str:
    raw = f"{EPOCH_ID}|{strategy_id}|{symbol}|{timeframe}|{entry_ts}"
    return "exact25.shadow." + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:28]


def valid_entry(result: Mapping[str, Any], current_price: float) -> Tuple[str, float, float, float] | None:
    action = str(result.get("action") or "").lower()
    side = str(result.get("side") or "").lower()
    if action not in {"enter", "entry", "open", "buy", "sell"} or side not in {"long", "short"}:
        return None
    entry = fnum(result.get("entry"), current_price) or current_price
    stop = fnum(result.get("sl"))
    target = fnum(result.get("tp"))
    if stop is None or target is None or min(entry, stop, target) <= 0:
        return None
    if side == "long" and not (stop < entry < target):
        return None
    if side == "short" and not (target < entry < stop):
        return None
    return side, entry, stop, target


def make_position(
    strategy_id: str,
    owner_sha: str,
    symbol: str,
    timeframe: str,
    result: Mapping[str, Any],
    frame: pd.DataFrame,
    risk_usdt: float,
    fee_rate: float,
    slippage_bps: float,
) -> Dict[str, Any] | None:
    current_price = float(frame.iloc[-1]["close"])
    validated = valid_entry(result, current_price)
    if validated is None:
        return None
    side, entry, stop, target = validated
    distance = abs(entry - stop)
    if distance <= 0:
        return None
    qty = risk_usdt / distance
    entry_ts = pd.Timestamp(frame.iloc[-1]["timestamp"]).isoformat()
    position_id = deterministic_position_id(strategy_id, symbol, timeframe, entry_ts)
    entry_fee = entry * qty * fee_rate
    entry_slippage = entry * qty * slippage_bps / 10_000.0
    features = feature_snapshot(frame)
    return {
        "position_id": position_id,
        "event_id": position_id,
        "strategy_id": strategy_id,
        "owner_sha256": owner_sha,
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "entry_ts": entry_ts,
        "entry_epoch": parse_time(entry_ts),
        "entry_price": entry,
        "stop_price": stop,
        "take_profit_price": target,
        "qty": qty,
        "original_qty": qty,
        "initial_risk_usdt": risk_usdt,
        "gross_realized_partial": 0.0,
        "fee_accum": entry_fee,
        "slippage_accum": entry_slippage,
        "add_count": 0,
        "partial_count": 0,
        "max_favorable_usdt": 0.0,
        "max_adverse_usdt": 0.0,
        "entry_features": features,
        "entry_reason": str(result.get("why") or ""),
        "entry_skill": str(result.get("skill") or ""),
        "entry_confidence": fnum(result.get("confidence"), 0.0) or 0.0,
        "mode": "shadow",
        "shadow": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }


def mark_excursions(position: MutableMapping[str, Any], candle: Mapping[str, Any]) -> None:
    entry = float(position["entry_price"])
    qty = float(position["qty"])
    high = float(candle["high"])
    low = float(candle["low"])
    if position["side"] == "long":
        favorable = (high - entry) * qty
        adverse = (low - entry) * qty
    else:
        favorable = (entry - low) * qty
        adverse = (entry - high) * qty
    position["max_favorable_usdt"] = max(float(position.get("max_favorable_usdt") or 0.0), favorable)
    position["max_adverse_usdt"] = min(float(position.get("max_adverse_usdt") or 0.0), adverse)


def bar_exit(position: Mapping[str, Any], candle: Mapping[str, Any], now_epoch: float, max_hold_min: float) -> Tuple[float, str] | None:
    high = float(candle["high"])
    low = float(candle["low"])
    stop = float(position["stop_price"])
    target = float(position["take_profit_price"])
    side = str(position["side"])
    if side == "long":
        stop_hit = low <= stop
        target_hit = high >= target
    else:
        stop_hit = high >= stop
        target_hit = low <= target
    if stop_hit:
        return stop, "stop_loss" if not target_hit else "same_bar_stop_first"
    if target_hit:
        return target, "take_profit"
    entry_epoch = fnum(position.get("entry_epoch"))
    if entry_epoch is not None and now_epoch - entry_epoch >= max_hold_min * 60.0:
        return float(candle["close"]), "max_hold"
    return None


def apply_add(
    position: MutableMapping[str, Any],
    result: Mapping[str, Any],
    current_price: float,
    risk_unit_usdt: float,
    fee_rate: float,
    slippage_bps: float,
) -> bool:
    if str(result.get("action") or "").lower() != "add":
        return False
    if str(result.get("side") or "").lower() != str(position.get("side") or "").lower():
        return False
    entry = fnum(result.get("entry"), current_price) or current_price
    stop = fnum(result.get("sl"))
    target = fnum(result.get("tp"))
    if stop is None or target is None or min(entry, stop, target) <= 0:
        return False
    side = str(position["side"])
    if side == "long" and not (stop < entry < target):
        return False
    if side == "short" and not (target < entry < stop):
        return False
    requested = fnum(result.get("size"), 0.1) or 0.1
    add_risk = risk_unit_usdt * min(max(requested, 0.05), 1.0)
    add_qty = add_risk / abs(entry - stop)
    old_qty = float(position["qty"])
    new_qty = old_qty + add_qty
    position["entry_price"] = (float(position["entry_price"]) * old_qty + entry * add_qty) / new_qty
    position["qty"] = new_qty
    position["original_qty"] = float(position.get("original_qty") or old_qty) + add_qty
    position["initial_risk_usdt"] = float(position["initial_risk_usdt"]) + add_risk
    position["stop_price"] = max(float(position["stop_price"]), stop) if side == "long" else min(float(position["stop_price"]), stop)
    position["take_profit_price"] = target
    position["fee_accum"] = float(position.get("fee_accum") or 0.0) + entry * add_qty * fee_rate
    position["slippage_accum"] = float(position.get("slippage_accum") or 0.0) + entry * add_qty * slippage_bps / 10_000.0
    position["add_count"] = int(position.get("add_count") or 0) + 1
    return True


def apply_partial_reduce(
    position: MutableMapping[str, Any],
    result: Mapping[str, Any],
    exit_price: float,
    fee_rate: float,
    slippage_bps: float,
) -> bool:
    action = str(result.get("action") or "").lower()
    if action not in {"reduce", "partial", "partial30"}:
        return False
    fraction = min(max(fnum(result.get("size"), 0.3) or 0.3, 0.05), 0.95)
    qty = float(position["qty"])
    close_qty = qty * fraction
    entry = float(position["entry_price"])
    gross = (exit_price - entry) * close_qty if position["side"] == "long" else (entry - exit_price) * close_qty
    position["gross_realized_partial"] = float(position.get("gross_realized_partial") or 0.0) + gross
    position["fee_accum"] = float(position.get("fee_accum") or 0.0) + exit_price * close_qty * fee_rate
    position["slippage_accum"] = float(position.get("slippage_accum") or 0.0) + exit_price * close_qty * slippage_bps / 10_000.0
    position["qty"] = qty - close_qty
    position["partial_count"] = int(position.get("partial_count") or 0) + 1
    return True


def close_position(
    position: Mapping[str, Any],
    exit_price: float,
    exit_ts: str,
    reason: str,
    exit_features: Mapping[str, Any],
    fee_rate: float,
    slippage_bps: float,
) -> Dict[str, Any]:
    qty = float(position["qty"])
    entry = float(position["entry_price"])
    gross_open = (exit_price - entry) * qty if position["side"] == "long" else (entry - exit_price) * qty
    gross = float(position.get("gross_realized_partial") or 0.0) + gross_open
    fee = float(position.get("fee_accum") or 0.0) + exit_price * qty * fee_rate
    slippage = float(position.get("slippage_accum") or 0.0) + exit_price * qty * slippage_bps / 10_000.0
    net = gross - fee - slippage
    initial_risk = float(position["initial_risk_usdt"])
    exit_epoch = parse_time(exit_ts)
    entry_epoch = fnum(position.get("entry_epoch"))
    exposure = (exit_epoch - entry_epoch) / 60.0 if exit_epoch is not None and entry_epoch is not None and exit_epoch >= entry_epoch else None
    close_id = str(position["position_id"]) + ":close"
    return {
        "schema": "q4r3_exact25_dedicated_shadow_close_v1",
        "event_id": close_id,
        "position_id": position["position_id"],
        "event_type": "CLOSED",
        "status": "CLOSED",
        "state": "CLOSED",
        "closed": True,
        "mode": "shadow",
        "shadow": True,
        "source": "q4r3_exact25_dedicated_shadow_producer",
        "epoch_id": EPOCH_ID,
        "measurement_namespace": NAMESPACE,
        "strategy_id": position["strategy_id"],
        "owner_sha256": position["owner_sha256"],
        "symbol": position["symbol"],
        "timeframe": position["timeframe"],
        "side": position["side"],
        "regime": str(exit_features.get("htf_bias") or "unknown"),
        "entry_ts": position["entry_ts"],
        "exit_ts": exit_ts,
        "entry_price": entry,
        "stop_price": position["stop_price"],
        "take_profit_price": position["take_profit_price"],
        "exit_price": exit_price,
        "qty": qty,
        "initial_risk_usdt": initial_risk,
        "gross_pnl_usdt": gross,
        "realized_pnl_usdt": net,
        "realized_R": net / initial_risk,
        "fee": fee,
        "slippage": slippage,
        "latency_ms": 0.0,
        "MFE_R": float(position.get("max_favorable_usdt") or 0.0) / initial_risk,
        "MAE_R": float(position.get("max_adverse_usdt") or 0.0) / initial_risk,
        "time_exposure_min": exposure,
        "close_reason": reason,
        "add_count": int(position.get("add_count") or 0),
        "partial_count": int(position.get("partial_count") or 0),
        "entry_features": position.get("entry_features"),
        "exit_features": dict(exit_features),
        "feature_observer_only": True,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
        "captured_at": now_iso(),
    }


def publish_open_positions(path: Path, positions: Mapping[str, Any], symbols: Sequence[str], timeframe: str) -> None:
    atomic_json(path, {
        "schema": "q4r3_exact25_dedicated_shadow_open_positions_v1",
        "updated_at": now_iso(),
        "epoch_id": EPOCH_ID,
        "mode": "shadow",
        "symbols": list(symbols),
        "timeframe": timeframe,
        "open_count": len(positions),
        "positions": list(positions.values()),
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    })


def publish_close_surface(path: Path, row: Mapping[str, Any]) -> None:
    prior = load_json(path, {"rows": []})
    rows = prior.get("rows")
    if not isinstance(rows, list):
        rows = []
    event_id = str(row.get("event_id") or "")
    deduped = [item for item in rows if isinstance(item, dict) and str(item.get("event_id") or "") != event_id]
    deduped.append(dict(row))
    deduped = deduped[-500:]
    atomic_json(path, {
        "schema": "q4r3_exact25_dedicated_shadow_close_surface_v1",
        "updated_at": now_iso(),
        "status": "CLOSED",
        "state": "CLOSED",
        "mode": "shadow",
        "shadow": True,
        "epoch_id": EPOCH_ID,
        "latest_close": dict(row),
        "row_count": len(deduped),
        "rows": deduped,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    })


def run_probe(root: Path, symbols: Sequence[str], timeframe: str, candle_limit: int) -> Dict[str, Any]:
    require_environment()
    _binding, registry = load_registry(root)
    exchange = build_exchange()
    exchange.load_markets()
    token = symbols[0]
    market_symbol = resolve_market_symbol(exchange, token)
    frame = fetch_closed_frame(exchange, market_symbol, timeframe, candle_limit)
    failures: List[Dict[str, str]] = []
    for strategy_id, owner in sorted(registry.items()):
        try:
            result = owner.strategy(frame.copy(), state=None, risk_action="hold")
            if not isinstance(result, dict) or "action" not in result or "size" not in result:
                raise RuntimeError("STRATEGY_OUTPUT_CONTRACT_GAP")
        except Exception as exc:
            failures.append({"strategy_id": strategy_id, "error": f"{type(exc).__name__}:{exc}"})
    return {
        "schema": "q4r3_exact25_dedicated_shadow_producer_probe_v1",
        "status": "PASS" if not failures else "HOLD",
        "strategy_count": len(registry),
        "pass_count": len(registry) - len(failures),
        "failure_count": len(failures),
        "failures": failures,
        "symbol": token,
        "resolved_symbol": market_symbol,
        "timeframe": timeframe,
        "closed_candle_count": len(frame),
        "latest_closed_ts": pd.Timestamp(frame.iloc[-1]["timestamp"]).isoformat(),
        "feature_observer": feature_snapshot(frame),
        "private_credentials_used": False,
        "paper_enabled": False,
        "live_enabled": False,
        "order_enabled": False,
    }


def run_service(args: argparse.Namespace) -> int:
    require_environment()
    binding, registry = load_registry(args.root)
    exchange = build_exchange()
    exchange.load_markets()
    requested_symbols = parse_symbols(args.symbols)
    resolved = {token: resolve_market_symbol(exchange, token) for token in requested_symbols}
    state = load_json(args.state, blank_state())
    if state.get("epoch_id") not in (None, EPOCH_ID):
        raise RuntimeError("STATE_EPOCH_MISMATCH")
    state["epoch_id"] = EPOCH_ID
    consecutive_all_fail = 0
    started_at = now_iso()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    while not _STOP:
        cycle_errors: Dict[str, str] = {}
        processed_symbols = 0
        for token, market_symbol in resolved.items():
            try:
                frame = fetch_closed_frame(exchange, market_symbol, args.timeframe, args.candle_limit)
                last = frame.iloc[-1]
                last_ts_ms = int(last["timestamp_ms"])
                last_ts_iso = pd.Timestamp(last["timestamp"]).isoformat()
                prior_ts = int((state.get("last_processed") or {}).get(token) or 0)
                if prior_ts == 0:
                    state.setdefault("last_processed", {})[token] = last_ts_ms
                    processed_symbols += 1
                    continue
                if last_ts_ms <= prior_ts:
                    processed_symbols += 1
                    continue

                features = feature_snapshot(frame)
                current_price = float(last["close"])
                candle = {key: float(last[key]) for key in ("open", "high", "low", "close")}
                now_epoch = parse_time(last_ts_iso) or time.time()

                for strategy_id, owner in sorted(registry.items()):
                    key = position_key(strategy_id, token, args.timeframe)
                    position = (state.get("positions") or {}).get(key)
                    strategy_state = None
                    if isinstance(position, dict):
                        mark_excursions(position, candle)
                        price_exit = bar_exit(position, candle, now_epoch, args.max_hold_min)
                        if price_exit is not None:
                            exit_price, reason = price_exit
                            row = close_position(position, exit_price, last_ts_iso, reason, features, args.fee_rate, args.slippage_bps)
                            if append_jsonl_once(args.ledger, row):
                                publish_close_surface(args.close_latest, row)
                                state["close_count"] = int(state.get("close_count") or 0) + 1
                            else:
                                state["duplicate_close_count"] = int(state.get("duplicate_close_count") or 0) + 1
                            state.setdefault("positions", {}).pop(key, None)
                            position = None
                        else:
                            strategy_state = {
                                "position_side": position.get("side"),
                                "position_qty": position.get("qty"),
                                "avg_entry": position.get("entry_price"),
                                "add_count": position.get("add_count", 0),
                                "last_add_price": position.get("entry_price"),
                            }

                    result = owner.strategy(frame.copy(), state=strategy_state, risk_action="hold")
                    if not isinstance(result, dict):
                        raise RuntimeError(f"STRATEGY_RESULT_NOT_DICT:{strategy_id}")
                    action = str(result.get("action") or "hold").lower()
                    if action not in {"hold", "none", "flat"}:
                        state["signal_count"] = int(state.get("signal_count") or 0) + 1

                    position = (state.get("positions") or {}).get(key)
                    if isinstance(position, dict):
                        if action in {"reduce", "partial", "partial30"}:
                            apply_partial_reduce(position, result, current_price, args.fee_rate, args.slippage_bps)
                        elif action == "add":
                            apply_add(position, result, current_price, args.risk_unit_usdt, args.fee_rate, args.slippage_bps)
                        elif action in {"exit", "close", "stop"}:
                            row = close_position(position, current_price, last_ts_iso, f"strategy_{action}", features, args.fee_rate, args.slippage_bps)
                            if append_jsonl_once(args.ledger, row):
                                publish_close_surface(args.close_latest, row)
                                state["close_count"] = int(state.get("close_count") or 0) + 1
                            else:
                                state["duplicate_close_count"] = int(state.get("duplicate_close_count") or 0) + 1
                            state.setdefault("positions", {}).pop(key, None)
                    else:
                        owner_sha = str(getattr(owner, "owner_sha256", ""))
                        new_position = make_position(
                            strategy_id,
                            owner_sha,
                            token,
                            args.timeframe,
                            result,
                            frame,
                            args.risk_unit_usdt,
                            args.fee_rate,
                            args.slippage_bps,
                        )
                        if new_position is not None:
                            state.setdefault("positions", {})[key] = new_position
                            state["open_count"] = int(state.get("open_count") or 0) + 1

                state.setdefault("last_processed", {})[token] = last_ts_ms
                processed_symbols += 1
            except Exception as exc:
                cycle_errors[token] = f"{type(exc).__name__}:{exc}"

        state["cycle_count"] = int(state.get("cycle_count") or 0) + 1
        state["updated_at"] = now_iso()
        atomic_json(args.state, state)
        publish_open_positions(args.open_latest, state.get("positions") or {}, requested_symbols, args.timeframe)
        status = {
            "schema": "q4r3_exact25_dedicated_shadow_producer_status_v1",
            "state": "RUNNING" if processed_symbols else "DEGRADED",
            "updated_at": now_iso(),
            "started_at": started_at,
            "pid": os.getpid(),
            "epoch_id": EPOCH_ID,
            "measurement_namespace": NAMESPACE,
            "producer_mode": "FIRST_FORWARD_CANARY",
            "strategy_count": len(registry),
            "symbols": requested_symbols,
            "resolved_symbols": resolved,
            "timeframe": args.timeframe,
            "processed_symbol_count": processed_symbols,
            "cycle_count": state.get("cycle_count"),
            "signal_count": state.get("signal_count"),
            "open_event_count": state.get("open_count"),
            "close_event_count": state.get("close_count"),
            "open_position_count": len(state.get("positions") or {}),
            "duplicate_close_count": state.get("duplicate_close_count"),
            "close_surface": str(args.close_latest),
            "feature_observer_enabled": True,
            "feature_filter_enabled": False,
            "write_scope": "DEDICATED_SHADOW_CLOSE_SURFACE_ONLY",
            "measurement_writer_enabled": False,
            "private_credentials_used": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "historical_backfill_allowed": False,
            "cycle_errors": cycle_errors,
        }
        atomic_json(args.status, status)
        if processed_symbols == 0:
            consecutive_all_fail += 1
        else:
            consecutive_all_fail = 0
        if consecutive_all_fail >= 3:
            raise RuntimeError(f"ALL_SYMBOLS_FAILED_THREE_CYCLES:{cycle_errors}")
        if args.once:
            return 0
        time.sleep(max(args.poll_sec, 2.0))

    status = load_json(args.status, {})
    status.update({"state": "STOPPED", "updated_at": now_iso(), "pid": os.getpid()})
    atomic_json(args.status, status)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--symbols", default=",".join(CORE_CANARY_SYMBOLS))
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--candle-limit", type=int, default=420)
    parser.add_argument("--poll-sec", type=float, default=15.0)
    parser.add_argument("--max-hold-min", type=float, default=120.0)
    parser.add_argument("--risk-unit-usdt", type=float, default=1.0)
    parser.add_argument("--fee-rate", type=float, default=0.0005)
    parser.add_argument("--slippage-bps", type=float, default=1.0)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--open-latest", type=Path)
    parser.add_argument("--close-latest", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--probe-output", type=Path)
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    args.root = args.root.resolve()
    if args.probe_only:
        return args
    required = ("state", "status", "open_latest", "close_latest", "ledger")
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        parser.error("required for service mode: " + ",".join("--" + name.replace("_", "-") for name in missing))
    return args


def main() -> None:
    args = parse_args()
    symbols = parse_symbols(args.symbols)
    if args.probe_only:
        result = run_probe(args.root, symbols, args.timeframe, args.candle_limit)
        if args.probe_output:
            atomic_json(args.probe_output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        raise SystemExit(0 if result["failure_count"] == 0 else 2)
    raise SystemExit(run_service(args))


if __name__ == "__main__":
    main()
