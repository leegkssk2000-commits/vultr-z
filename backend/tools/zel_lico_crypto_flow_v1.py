from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_LICO_CRYPTO_FLOW_V1"
SCHEMA = "zel.lico.crypto_flow.effectiveness.receipt.v1"
INTERVAL_MS = 3_600_000
CHUNK_LIMIT = 1000
SAFE_CHUNK_BARS = 999
UNKNOWN_EXIT_VALUES = {"", "unknown", "none", "null"}
R_FIELDS = (
    "realized_R_including_funding_estimate",
    "pnl_r",
    "realized_R",
    "realized_r",
    "net_R",
    "net_r",
)
ENTRY_TS_FIELDS = ("entry_ts", "entry_time", "entry_timestamp", "opened_at", "open_ts")
SIDE_FIELDS = ("side", "position_side", "direction")
WINDOW_FIELDS = ("window_id", "window", "split", "partition")
IDENTITY_FIELDS = ("event_id", "position_id", "trade_id")
COST_FIELDS = ("fee", "slippage", "funding_pnl_estimate_usdt", "realized_R_including_funding_estimate")
FLOW_STATES = {
    "RISK_ON",
    "RISK_OFF",
    "ROTATION",
    "CROWDED_LONG",
    "CROWDED_SHORT",
    "NEUTRAL",
    "HOLD_DATA_GAP",
}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_utc(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def floor_hour(timestamp_ms: int) -> int:
    return timestamp_ms - timestamp_ms % INTERVAL_MS


def parse_timestamp_ms(value: Any) -> int:
    if value is None or value == "":
        raise ValueError("TIMESTAMP_MISSING")
    if isinstance(value, bool):
        raise ValueError("TIMESTAMP_BOOLEAN")
    if isinstance(value, (int, float, Decimal)):
        number = float(value)
        if number < 10_000_000_000:
            number *= 1000
        return int(number)
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    if number < 10_000_000_000:
        number *= 1000
    return int(number)


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def nested_value(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    for container in ("entry_features", "market_context", "execution_evidence", "risk_context", "result"):
        nested = row.get(container)
        if isinstance(nested, Mapping):
            for key in keys:
                if nested.get(key) not in (None, ""):
                    return nested.get(key)
    return None


def normalize_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "bull", "1"}:
        return "long"
    if text in {"short", "sell", "bear", "-1"}:
        return "short"
    return "unknown"


def normalize_window(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "W1": "W1",
        "1M_W1": "W1",
        "TRAIN": "W1",
        "RESEARCH": "W1",
        "W2": "W2",
        "1M_W2": "W2",
        "FORWARD": "W2",
        "VALIDATION": "W2",
        "W3": "W3",
        "1M_W3": "W3",
        "DURABILITY": "W3",
        "TEST": "W3",
    }
    return aliases.get(text, "UNKNOWN")


def normalized_exit_reason(row: Mapping[str, Any]) -> str:
    for key in ("exit_reason", "reason", "close_reason"):
        value = nested_value(row, (key,))
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    return "unknown"


def load_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("CONTRACT_OBJECT_REQUIRED")
    required = ("source", "features", "research_thresholds", "candidate_filters", "evaluation", "authority")
    if any(key not in value for key in required):
        raise RuntimeError("CONTRACT_SECTION_MISSING")
    if value["authority"].get("execution_authority") != "NONE" or value["authority"].get("order_authority") != "BLOCKED":
        raise RuntimeError("CONTRACT_AUTHORITY_INVALID")
    return value


def load_trades(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    identities: list[str] = []
    missing_identity = 0
    missing_cost_lineage = 0
    unknown_exit = 0
    parse_errors = 0
    unknown_side = 0
    unknown_window = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            if not isinstance(row, dict):
                parse_errors += 1
                continue
            identity = str(nested_value(row, IDENTITY_FIELDS) or "").strip()
            if identity:
                identities.append(identity)
            else:
                missing_identity += 1
            r_value = decimal_value(nested_value(row, R_FIELDS))
            try:
                entry_ms = parse_timestamp_ms(nested_value(row, ENTRY_TS_FIELDS))
            except (ValueError, TypeError):
                entry_ms = -1
                parse_errors += 1
            side = normalize_side(nested_value(row, SIDE_FIELDS))
            if side == "unknown":
                unknown_side += 1
            window = normalize_window(nested_value(row, WINDOW_FIELDS))
            if window == "UNKNOWN":
                unknown_window += 1
            if normalized_exit_reason(row) in UNKNOWN_EXIT_VALUES:
                unknown_exit += 1
            if any(decimal_value(nested_value(row, (field,))) is None for field in COST_FIELDS):
                missing_cost_lineage += 1
            if r_value is None:
                parse_errors += 1
                continue
            rows.append({
                "identity": identity,
                "strategy_id": str(row.get("strategy_id") or row.get("strategy") or "unknown"),
                "symbol": str(row.get("symbol") or nested_value(row, ("symbol",)) or "").upper().replace("_", "-").replace("/", "-"),
                "entry_ms": entry_ms,
                "side": side,
                "window": window,
                "r": float(r_value),
            })
    integrity = {
        "trade_count": len(rows),
        "identity_count": len(identities),
        "missing_identity_count": missing_identity,
        "duplicate_count": len(identities) - len(set(identities)),
        "parse_error_count": parse_errors,
        "unknown_side_count": unknown_side,
        "unknown_window_count": unknown_window,
        "unknown_exit_count": unknown_exit,
        "missing_cost_lineage_count": missing_cost_lineage,
        "censored_open_count": 0,
    }
    return rows, integrity


def extract_rows(payload: Mapping[str, Any], keys: Sequence[str]) -> list[Any]:
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"BINGX_CODE:{payload.get('code')}:{payload.get('msg')}")
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for key in keys:
            child = data.get(key)
            if isinstance(child, list):
                return child
    raise RuntimeError("BINGX_ROWS_MISSING")


def request_json(url: str, *, attempts: int = 5) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": VERSION, "X-SOURCE-KEY": "bingx:public:usdtm"},
    )
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = json.loads(response.read())
            if not isinstance(payload, Mapping):
                raise RuntimeError("BINGX_PAYLOAD_NOT_OBJECT")
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}:{exc}"
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"BINGX_REQUEST_FAILED:{last_error}")


def normalize_kline(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        timestamp = raw.get("openTime", raw.get("time", raw.get("timestamp")))
        close = raw.get("close")
        volume = raw.get("volume", raw.get("vol", 0))
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) and len(raw) >= 6:
        timestamp, close, volume = raw[0], raw[4], raw[5]
    else:
        raise RuntimeError("KLINE_SCHEMA_INVALID")
    ts = int(float(timestamp))
    price = decimal_value(close)
    vol = decimal_value(volume)
    if price is None or price <= 0 or vol is None or vol < 0:
        raise RuntimeError("KLINE_NUMERIC_INVALID")
    return {"timestamp_ms": ts, "close": float(price), "volume": float(vol)}


def collect_klines(
    *,
    base_url: str,
    endpoint: str,
    symbol: str,
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cursor = floor_hour(start_ms)
    end_exclusive_ms = floor_hour(end_exclusive_ms + INTERVAL_MS - 1)
    by_ts: dict[int, dict[str, Any]] = {}
    request_count = 0
    while cursor < end_exclusive_ms:
        chunk_end = min(cursor + SAFE_CHUNK_BARS * INTERVAL_MS, end_exclusive_ms)
        params = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": "1h",
            "startTime": cursor,
            "endTime": chunk_end,
            "limit": CHUNK_LIMIT,
        })
        payload = request_json(f"{base_url}{endpoint}?{params}")
        for raw in extract_rows(payload, ("data", "rows", "items", "list", "klines")):
            row = normalize_kline(raw)
            ts = int(row["timestamp_ms"])
            if cursor <= ts < chunk_end:
                prior = by_ts.get(ts)
                if prior is not None and prior != row:
                    raise RuntimeError(f"KLINE_CONFLICTING_DUPLICATE:{symbol}:{ts}")
                by_ts[ts] = row
        cursor = chunk_end
        request_count += 1
        time.sleep(0.13)
    expected = list(range(floor_hour(start_ms), end_exclusive_ms, INTERVAL_MS))
    rows = [by_ts[ts] for ts in expected if ts in by_ts]
    missing = len(expected) - len(rows)
    return rows, {
        "symbol": symbol,
        "expected_count": len(expected),
        "row_count": len(rows),
        "missing_count": missing,
        "coverage_pct": (len(rows) / len(expected) * 100.0) if expected else 0.0,
        "request_count": request_count,
        "first_timestamp_ms": rows[0]["timestamp_ms"] if rows else None,
        "last_timestamp_ms": rows[-1]["timestamp_ms"] if rows else None,
    }


def normalize_funding(raw: Any) -> tuple[int, float]:
    if not isinstance(raw, Mapping):
        raise RuntimeError("FUNDING_SCHEMA_INVALID")
    timestamp = raw.get("fundingTime", raw.get("time", raw.get("timestamp")))
    rate = raw.get("fundingRate", raw.get("rate"))
    ts = int(float(timestamp))
    parsed = decimal_value(rate)
    if parsed is None:
        raise RuntimeError("FUNDING_NUMERIC_INVALID")
    return ts, float(parsed * Decimal("100"))


def collect_funding_optional(
    *,
    base_url: str,
    endpoint: str,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> tuple[list[tuple[int, float]], dict[str, Any]]:
    params = urllib.parse.urlencode({"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": 1000})
    try:
        payload = request_json(f"{base_url}{endpoint}?{params}", attempts=3)
        rows = [normalize_funding(row) for row in extract_rows(payload, ("data", "rows", "items", "list", "fundingRates"))]
        rows = sorted(set(rows))
        return rows, {"symbol": symbol, "available": bool(rows), "row_count": len(rows), "error": None}
    except Exception as exc:  # optional evidence remains explicit
        return [], {"symbol": symbol, "available": False, "row_count": 0, "error": f"{type(exc).__name__}:{exc}"}


def pct_return(rows: Sequence[Mapping[str, Any]], index: int, hours: int) -> float | None:
    if index < hours:
        return None
    start = float(rows[index - hours]["close"])
    end = float(rows[index]["close"])
    return (end / start - 1.0) * 100.0 if start > 0 else None


def funding_asof(rows: Sequence[tuple[int, float]], timestamp_ms: int) -> float | None:
    if not rows:
        return None
    timestamps = [row[0] for row in rows]
    index = bisect_right(timestamps, timestamp_ms) - 1
    return rows[index][1] if index >= 0 else None


def build_snapshots(
    market: Mapping[str, Sequence[Mapping[str, Any]]],
    funding: Mapping[str, Sequence[tuple[int, float]]],
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    symbols = list(contract["source"]["symbols"])
    by_symbol = {symbol: {int(row["timestamp_ms"]): row for row in market.get(symbol, [])} for symbol in symbols}
    common = sorted(set.intersection(*(set(rows) for rows in by_symbol.values()))) if by_symbol else []
    thresholds = contract["research_thresholds"]
    snapshots: list[dict[str, Any]] = []
    ordered = {symbol: [by_symbol[symbol][ts] for ts in common] for symbol in symbols}
    for index, timestamp_ms in enumerate(common):
        returns_4h = {symbol: pct_return(ordered[symbol], index, 4) for symbol in symbols}
        returns_24h = {symbol: pct_return(ordered[symbol], index, 24) for symbol in symbols}
        if any(value is None for value in (*returns_4h.values(), *returns_24h.values())):
            continue
        btc4 = float(returns_4h["BTC-USDT"])
        btc24 = float(returns_24h["BTC-USDT"])
        breadth = sum(1 for value in returns_4h.values() if float(value) > 0) / len(symbols)
        alt_relative = statistics.median(float(returns_24h[symbol]) for symbol in symbols if symbol != "BTC-USDT") - btc24
        funding_values = [
            value for symbol in symbols if (value := funding_asof(funding.get(symbol, []), timestamp_ms)) is not None
        ]
        funding_median = statistics.median(funding_values) if funding_values else None
        state = "NEUTRAL"
        reasons: list[str] = []
        if funding_median is not None and funding_median >= float(thresholds["crowded_long_funding_median_gte_pct"]):
            state = "CROWDED_LONG"
            reasons.append("FUNDING_CROWDED_LONG")
        elif funding_median is not None and funding_median <= float(thresholds["crowded_short_funding_median_lte_pct"]):
            state = "CROWDED_SHORT"
            reasons.append("FUNDING_CROWDED_SHORT")
        elif btc4 <= float(thresholds["risk_off_btc_4h_lte_pct"]) or (
            breadth <= float(thresholds["risk_off_breadth_lte"]) and btc24 < 0
        ):
            state = "RISK_OFF"
            reasons.append("BTC_OR_BREADTH_RISK_OFF")
        elif btc4 >= float(thresholds["risk_on_btc_4h_gte_pct"]) and breadth >= float(thresholds["risk_on_breadth_gte"]):
            state = "RISK_ON"
            reasons.append("BTC_AND_BREADTH_RISK_ON")
        elif alt_relative >= float(thresholds["rotation_alt_relative_24h_gte_pct"]) and breadth >= float(thresholds["rotation_breadth_gte"]):
            state = "ROTATION"
            reasons.append("ALT_RELATIVE_ROTATION")
        else:
            reasons.append("NO_EXTREME_FLOW_STATE")
        snapshots.append({
            "timestamp_ms": timestamp_ms,
            "state": state,
            "reasons": reasons,
            "btc_return_4h_pct": btc4,
            "btc_return_24h_pct": btc24,
            "breadth_4h": breadth,
            "alt_relative_24h_pct": alt_relative,
            "funding_median_8h_pct": funding_median,
            "funding_symbol_count": len(funding_values),
        })
    return snapshots


def bind_trades(trades: Sequence[Mapping[str, Any]], snapshots: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timestamps = [int(row["timestamp_ms"]) for row in snapshots]
    max_age = int(contract["research_thresholds"]["maximum_snapshot_age_ms"])
    bound: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    missing = 0
    future_leak = 0
    for trade in trades:
        entry_ms = int(trade["entry_ms"])
        index = bisect_right(timestamps, entry_ms) - 1
        state = "HOLD_DATA_GAP"
        snapshot_ts = None
        age = None
        if index >= 0:
            snapshot = snapshots[index]
            snapshot_ts = int(snapshot["timestamp_ms"])
            age = entry_ms - snapshot_ts
            if snapshot_ts > entry_ms:
                future_leak += 1
            elif 0 <= age <= max_age:
                state = str(snapshot["state"])
        if state == "HOLD_DATA_GAP":
            missing += 1
        state_counts[state] += 1
        bound.append({**dict(trade), "flow_state": state, "flow_snapshot_ms": snapshot_ts, "flow_age_ms": age})
    coverage = ((len(bound) - missing) / len(bound) * 100.0) if bound else 0.0
    return bound, {
        "trade_count": len(bound),
        "bound_trade_count": len(bound) - missing,
        "unbound_trade_count": missing,
        "binding_coverage_pct": coverage,
        "future_snapshot_leak_count": future_leak,
        "state_counts": dict(sorted(state_counts.items())),
    }


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(row["r"]) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    payoff = avg_win / avg_loss if avg_loss > 0 else (999.0 if avg_win > 0 else 0.0)
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return {
        "trade_count": len(values),
        "net_R": sum(values),
        "profit_factor": pf,
        "expectancy_R": sum(values) / len(values) if values else 0.0,
        "payoff_ratio": payoff,
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0,
        "max_drawdown_R": max_dd,
    }


def keep_trade(row: Mapping[str, Any], config_id: str) -> bool:
    state = str(row["flow_state"])
    side = str(row["side"])
    if state == "HOLD_DATA_GAP":
        return True
    if config_id == "BLOCK_LONG_RISK_OFF":
        return not (side == "long" and state == "RISK_OFF")
    if config_id == "BLOCK_SHORT_RISK_ON":
        return not (side == "short" and state == "RISK_ON")
    if config_id == "BLOCK_CROWDED_SAME_SIDE":
        return not ((side == "long" and state == "CROWDED_LONG") or (side == "short" and state == "CROWDED_SHORT"))
    if config_id == "BLOCK_DIRECTIONAL_CONFLICT":
        return not ((side == "long" and state == "RISK_OFF") or (side == "short" and state == "RISK_ON"))
    raise RuntimeError(f"UNKNOWN_CONFIG:{config_id}")


def evaluate(bound: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]) -> dict[str, Any]:
    baseline = {window: metrics([row for row in bound if row["window"] == window]) for window in ("W1", "W2", "W3")}
    baseline["ALL"] = metrics(bound)
    minimum_retention = float(contract["evaluation"]["minimum_retention_pct"])
    candidates: list[dict[str, Any]] = []
    for config in contract["candidate_filters"]:
        config_id = str(config["config_id"])
        kept = [row for row in bound if keep_trade(row, config_id)]
        windows: dict[str, Any] = {}
        for window in ("W1", "W2", "W3"):
            base_rows = [row for row in bound if row["window"] == window]
            candidate_rows = [row for row in kept if row["window"] == window]
            candidate_metrics = metrics(candidate_rows)
            base_metrics = baseline[window]
            retention = (len(candidate_rows) / len(base_rows) * 100.0) if base_rows else 0.0
            windows[window] = {
                **candidate_metrics,
                "retention_pct": retention,
                "delta_net_R": candidate_metrics["net_R"] - base_metrics["net_R"],
                "delta_profit_factor": candidate_metrics["profit_factor"] - base_metrics["profit_factor"],
                "delta_max_drawdown_R": candidate_metrics["max_drawdown_R"] - base_metrics["max_drawdown_R"],
            }
        all_metrics = metrics(kept)
        all_retention = len(kept) / len(bound) * 100.0 if bound else 0.0
        w1 = windows["W1"]
        w1_eligible = (
            w1["retention_pct"] >= minimum_retention
            and w1["trade_count"] >= int(contract["evaluation"]["minimum_confirmation_trade_count"])
            and w1["delta_net_R"] > 0
            and w1["profit_factor"] >= baseline["W1"]["profit_factor"]
            and w1["max_drawdown_R"] <= baseline["W1"]["max_drawdown_R"]
        )
        candidates.append({
            "config_id": config_id,
            "description": config["description"],
            "w1_eligible": w1_eligible,
            "windows": windows,
            "all": {
                **all_metrics,
                "retention_pct": all_retention,
                "delta_net_R": all_metrics["net_R"] - baseline["ALL"]["net_R"],
                "delta_profit_factor": all_metrics["profit_factor"] - baseline["ALL"]["profit_factor"],
                "delta_max_drawdown_R": all_metrics["max_drawdown_R"] - baseline["ALL"]["max_drawdown_R"],
            },
        })
    eligible = [row for row in candidates if row["w1_eligible"]]
    selected = max(
        eligible,
        key=lambda row: (
            row["windows"]["W1"]["net_R"],
            row["windows"]["W1"]["profit_factor"],
            -row["windows"]["W1"]["max_drawdown_R"],
            row["windows"]["W1"]["retention_pct"],
        ),
        default=None,
    )
    survivor = False
    blockers: list[str] = []
    if selected is None:
        blockers.append("NO_W1_ELIGIBLE_FLOW_FILTER")
    else:
        for window in ("W1", "W2", "W3"):
            row = selected["windows"][window]
            if row["retention_pct"] < minimum_retention:
                blockers.append(f"{window}_RETENTION_BELOW_MIN")
            if row["trade_count"] < int(contract["evaluation"]["minimum_confirmation_trade_count"]):
                blockers.append(f"{window}_SAMPLE_BELOW_MIN")
            if row["net_R"] <= float(contract["evaluation"]["net_R_gt"]):
                blockers.append(f"{window}_NET_R_NOT_POSITIVE")
            if row["profit_factor"] < float(contract["evaluation"]["profit_factor_gte"]):
                blockers.append(f"{window}_PF_BELOW_GATE")
            if row["expectancy_R"] <= float(contract["evaluation"]["expectancy_R_gt"]):
                blockers.append(f"{window}_EXPECTANCY_NOT_POSITIVE")
            if row["payoff_ratio"] < float(contract["evaluation"]["payoff_ratio_gte"]):
                blockers.append(f"{window}_PAYOFF_BELOW_GATE")
        survivor = not blockers
    diagnostic = max(
        candidates,
        key=lambda row: (
            row["all"]["delta_net_R"] if row["all"]["retention_pct"] >= minimum_retention else -math.inf,
            row["all"]["delta_profit_factor"],
            -row["all"]["delta_max_drawdown_R"],
        ),
        default=None,
    )
    return {
        "baseline": baseline,
        "candidates": candidates,
        "selected_config_id": selected["config_id"] if selected else None,
        "selected_frozen_w2_w3": selected is not None,
        "selected": selected,
        "survivor": survivor,
        "survivor_blockers": sorted(set(blockers)),
        "diagnostic_incumbent_config_id": diagnostic["config_id"] if diagnostic else None,
        "diagnostic_incumbent": diagnostic,
    }


def aggregate_binding(bound: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_strategy_state: dict[str, Counter[str]] = defaultdict(Counter)
    by_window_state: dict[str, Counter[str]] = defaultdict(Counter)
    for row in bound:
        by_strategy_state[str(row["strategy_id"])][str(row["flow_state"])] += 1
        by_window_state[str(row["window"])][str(row["flow_state"])] += 1
    return {
        "strategy_state_counts": {key: dict(sorted(value.items())) for key, value in sorted(by_strategy_state.items())},
        "window_state_counts": {key: dict(sorted(value.items())) for key, value in sorted(by_window_state.items())},
    }


def run(contract_path: Path, trades_path: Path, out_path: Path) -> dict[str, Any]:
    contract = load_contract(contract_path)
    trades, integrity = load_trades(trades_path)
    expected_count = int(contract["evaluation"]["expected_terminal_trade_count"])
    integrity_checks = {
        "trade_count_exact": integrity["trade_count"] == expected_count,
        "missing_identity_zero": integrity["missing_identity_count"] == 0,
        "duplicate_zero": integrity["duplicate_count"] == 0,
        "parse_errors_zero": integrity["parse_error_count"] == 0,
        "unknown_side_zero": integrity["unknown_side_count"] == 0,
        "unknown_window_zero": integrity["unknown_window_count"] == 0,
        "unknown_exit_zero": integrity["unknown_exit_count"] == 0,
        "cost_lineage_complete": integrity["missing_cost_lineage_count"] == 0,
        "censored_open_zero": integrity["censored_open_count"] == 0,
    }
    if not all(integrity_checks.values()):
        receipt = {
            "schema_version": SCHEMA,
            "version": VERSION,
            "generated_at": now_iso(),
            "state": "HOLD_LICO_CRYPTO_TERMINAL_INTEGRITY",
            "integrity": integrity,
            "integrity_checks": integrity_checks,
            "protected_mutations": 0,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
        receipt["receipt_sha256"] = stable_sha(receipt)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return receipt

    minimum_entry = min(int(row["entry_ms"]) for row in trades)
    maximum_entry = max(int(row["entry_ms"]) for row in trades)
    lookback_ms = int(contract["features"]["lookback_hours"]) * INTERVAL_MS
    start_ms = floor_hour(minimum_entry - lookback_ms)
    end_ms = floor_hour(maximum_entry + 2 * INTERVAL_MS)
    source = contract["source"]
    market: dict[str, list[dict[str, Any]]] = {}
    funding: dict[str, list[tuple[int, float]]] = {}
    market_receipts: list[dict[str, Any]] = []
    funding_receipts: list[dict[str, Any]] = []
    for symbol in source["symbols"]:
        rows, market_receipt = collect_klines(
            base_url=str(source["base_url"]),
            endpoint=str(source["kline_endpoint"]),
            symbol=str(symbol),
            start_ms=start_ms,
            end_exclusive_ms=end_ms,
        )
        market[str(symbol)] = rows
        market_receipts.append(market_receipt)
        funding_rows, funding_receipt = collect_funding_optional(
            base_url=str(source["base_url"]),
            endpoint=str(source["funding_endpoint"]),
            symbol=str(symbol),
            start_ms=start_ms,
            end_ms=end_ms,
        )
        funding[str(symbol)] = funding_rows
        funding_receipts.append(funding_receipt)

    minimum_market_coverage = float(contract["research_thresholds"]["minimum_market_coverage_pct"])
    market_coverage_pass = all(float(row["coverage_pct"]) >= minimum_market_coverage for row in market_receipts)
    snapshots = build_snapshots(market, funding, contract) if market_coverage_pass else []
    bound, binding = bind_trades(trades, snapshots, contract)
    minimum_binding_coverage = float(contract["research_thresholds"]["minimum_binding_coverage_pct"])
    binding_pass = (
        binding["binding_coverage_pct"] >= minimum_binding_coverage
        and binding["future_snapshot_leak_count"] == 0
    )
    effectiveness = evaluate(bound, contract) if binding_pass else None
    dataset_material = {
        "market": [
            {
                "symbol": symbol,
                "count": len(rows),
                "first": rows[0]["timestamp_ms"] if rows else None,
                "last": rows[-1]["timestamp_ms"] if rows else None,
                "sha256": stable_sha(rows),
            }
            for symbol, rows in sorted(market.items())
        ],
        "funding": [
            {"symbol": symbol, "count": len(rows), "sha256": stable_sha(rows)}
            for symbol, rows in sorted(funding.items())
        ],
    }
    if not market_coverage_pass:
        state = "HOLD_LICO_CRYPTO_MARKET_COVERAGE"
    elif not binding_pass:
        state = "HOLD_LICO_CRYPTO_BINDING_COVERAGE"
    elif effectiveness and effectiveness["survivor"]:
        state = "PASS_LICO_CRYPTO_FLOW_VALIDATED_SURVIVOR"
    else:
        state = "PASS_LICO_CRYPTO_FLOW_BOUND_NO_VALID_SURVIVOR"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "contract_sha256": file_sha(contract_path),
        "terminal_trade_file_sha256": file_sha(trades_path),
        "terminal_trade_count": len(trades),
        "terminal_range": {
            "first_entry_ms": minimum_entry,
            "first_entry_utc": iso_utc(minimum_entry),
            "last_entry_ms": maximum_entry,
            "last_entry_utc": iso_utc(maximum_entry),
        },
        "integrity": integrity,
        "integrity_checks": integrity_checks,
        "source": {
            "venue": source["venue"],
            "source_key": source["source_key"],
            "symbols": source["symbols"],
            "interval": source["interval"],
            "market_receipts": market_receipts,
            "funding_receipts": funding_receipts,
            "funding_available_symbol_count": sum(1 for row in funding_receipts if row["available"]),
            "dataset_sha256": stable_sha(dataset_material),
            "interpolation_used": False,
            "synthetic_candles_used": False,
        },
        "flow_snapshot_count": len(snapshots),
        "binding": binding,
        "binding_aggregates": aggregate_binding(bound),
        "effectiveness": effectiveness,
        "future_mfe_mae_used": False,
        "entry_time_asof_only": True,
        "raw_trade_rows_published": False,
        "strategy_rules_mutated": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_mutated": False,
        "paper_mutated": False,
        "live_mutated": False,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "PRESERVE_VALID_FLOW_AXIS_FOR_SELECTED_INTERACTIONS" if effectiveness and effectiveness["survivor"] else "PRESERVE_DIAGNOSTIC_AND_TEST_NEXT_DISTINCT_FLOW_AXIS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def self_test() -> int:
    contract = {
        "source": {"symbols": ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT"]},
        "research_thresholds": {
            "risk_off_btc_4h_lte_pct": -2.0,
            "risk_off_breadth_lte": 0.2,
            "risk_on_btc_4h_gte_pct": 2.0,
            "risk_on_breadth_gte": 0.8,
            "rotation_alt_relative_24h_gte_pct": 2.0,
            "rotation_breadth_gte": 0.6,
            "crowded_long_funding_median_gte_pct": 0.03,
            "crowded_short_funding_median_lte_pct": -0.03,
            "maximum_snapshot_age_ms": 7_200_000,
        },
        "candidate_filters": [
            {"config_id": "BLOCK_LONG_RISK_OFF", "description": "x"},
            {"config_id": "BLOCK_SHORT_RISK_ON", "description": "x"},
            {"config_id": "BLOCK_CROWDED_SAME_SIDE", "description": "x"},
            {"config_id": "BLOCK_DIRECTIONAL_CONFLICT", "description": "x"},
        ],
        "evaluation": {
            "minimum_retention_pct": 60.0,
            "minimum_confirmation_trade_count": 2,
            "net_R_gt": 0.0,
            "profit_factor_gte": 1.0,
            "expectancy_R_gt": 0.0,
            "payoff_ratio_gte": 1.0,
        },
    }
    symbols = contract["source"]["symbols"]
    market: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        rows = []
        price = 100.0
        for hour in range(80):
            if hour >= 40:
                price *= 0.992 if symbol == "BTC-USDT" else 0.996
            rows.append({"timestamp_ms": hour * INTERVAL_MS, "close": price, "volume": 1.0})
        market[symbol] = rows
    snapshots = build_snapshots(market, {symbol: [] for symbol in symbols}, contract)
    assert snapshots and snapshots[-1]["state"] == "RISK_OFF", snapshots[-1]
    trades: list[dict[str, Any]] = []
    for window_index, window in enumerate(("W1", "W2", "W3")):
        for index in range(4):
            trades.append({
                "identity": f"{window}-{index}",
                "strategy_id": "s",
                "symbol": "BTC-USDT",
                "entry_ms": (45 + window_index * 8 + index) * INTERVAL_MS + 1,
                "side": "long" if index < 2 else "short",
                "window": window,
                "r": -1.0 if index < 2 else 2.0,
            })
    bound, binding = bind_trades(trades, snapshots, contract)
    assert binding["future_snapshot_leak_count"] == 0, binding
    assert binding["binding_coverage_pct"] == 100.0, binding
    result = evaluate(bound, contract)
    assert result["selected_config_id"] in {"BLOCK_LONG_RISK_OFF", "BLOCK_DIRECTIONAL_CONFLICT"}, result
    assert result["survivor"] is True, result
    assert normalize_side("BUY") == "long"
    assert normalize_window("1m_w3") == "W3"
    assert parse_timestamp_ms("2026-01-01T00:00:00Z") > 0
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not all((args.contract, args.trades, args.out)):
        parser.error("contract, trades and out are required")
    receipt = run(args.contract.resolve(), args.trades.resolve(), args.out.resolve())
    print(json.dumps({
        "state": receipt["state"],
        "terminal_trade_count": receipt.get("terminal_trade_count"),
        "binding_coverage_pct": (receipt.get("binding") or {}).get("binding_coverage_pct"),
        "survivor": ((receipt.get("effectiveness") or {}).get("survivor")),
        "selected_config_id": ((receipt.get("effectiveness") or {}).get("selected_config_id")),
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0 if str(receipt["state"]).startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
