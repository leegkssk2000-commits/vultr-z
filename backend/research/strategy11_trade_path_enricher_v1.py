from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "strategy11.trade_path_evidence.v1"
INDEX_SCHEMA = "strategy11.trade_path_evidence.index.v1"
VERSION = "STRATEGY11_TRADE_PATH_ENRICHER_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
POLICY = {
    "entry_observation_bars": 3,
    "post_exit_horizon_bars": 12,
    "post_exit_min_observation_bars": 3,
    "pre_entry_reference": "SIGNAL_BAR_CLOSE_TO_ENTRY_BAR_OPEN",
    "post_exit_reference": "FIRST_BAR_AFTER_EXIT_BAR",
    "same_bar_post_exit_excluded": True,
}


class TradePathError(ValueError):
    pass


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TradePathError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def number(value: Any, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TradePathError(f"NUMBER_REQUIRED:{name}")
    result = float(value)
    if not math.isfinite(result):
        raise TradePathError(f"NUMBER_NOT_FINITE:{name}")
    if minimum is not None and result < minimum:
        raise TradePathError(f"NUMBER_BELOW_MIN:{name}")
    return result


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TradePathError(f"STRING_REQUIRED:{name}")
    return value.strip()


def timestamp_ms(value: Any, name: str) -> int:
    raw = text(value, name).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TradePathError(f"TIMESTAMP_INVALID:{name}:{value}") from exc
    if parsed.tzinfo is None:
        raise TradePathError(f"TIMESTAMP_TZ_REQUIRED:{name}")
    return int(parsed.timestamp() * 1000)


@dataclass(frozen=True)
class Candle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float


def load_market(path: Path) -> list[Candle]:
    rows: list[Candle] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp_ms", "open", "high", "low", "close"}
        if not required.issubset(reader.fieldnames or []):
            raise TradePathError(f"MARKET_COLUMNS_MISSING:{path}")
        for index, row in enumerate(reader):
            candle = Candle(
                timestamp_ms=int(row["timestamp_ms"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            )
            if not all(math.isfinite(value) for value in (candle.open, candle.high, candle.low, candle.close)):
                raise TradePathError(f"MARKET_NONFINITE:{path}:{index}")
            if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close) or candle.high < candle.low:
                raise TradePathError(f"MARKET_OHLC_INVALID:{path}:{index}")
            rows.append(candle)
    if not rows:
        raise TradePathError(f"MARKET_EMPTY:{path}")
    if len({row.timestamp_ms for row in rows}) != len(rows):
        raise TradePathError(f"MARKET_TIMESTAMP_DUPLICATE:{path}")
    if any(left.timestamp_ms >= right.timestamp_ms for left, right in zip(rows, rows[1:])):
        raise TradePathError(f"MARKET_TIMESTAMP_NOT_ASCENDING:{path}")
    return rows


def locate(rows: list[Candle], ts_ms: int, name: str) -> int:
    matches = [index for index, row in enumerate(rows) if row.timestamp_ms == ts_ms]
    if len(matches) != 1:
        raise TradePathError(f"TIMESTAMP_NOT_UNIQUE:{name}:{ts_ms}:{len(matches)}")
    return matches[0]


def favorable(side: str, reference: float, highs: Iterable[float], lows: Iterable[float]) -> float:
    highs_list, lows_list = list(highs), list(lows)
    if not highs_list or not lows_list:
        return 0.0
    return max(0.0, max(highs_list) - reference) if side == "LONG" else max(0.0, reference - min(lows_list))


def adverse(side: str, reference: float, highs: Iterable[float], lows: Iterable[float]) -> float:
    highs_list, lows_list = list(highs), list(lows)
    if not highs_list or not lows_list:
        return 0.0
    return max(0.0, reference - min(lows_list)) if side == "LONG" else max(0.0, max(highs_list) - reference)


def regime_label(features: Mapping[str, Any]) -> str:
    atr_percentile = float(features.get("atr_percentile") or 50.0)
    trend = bool(features.get("htf_trend_up") or features.get("trend_ema20_50") or features.get("trend_ema20_50_200"))
    if atr_percentile >= 70.0:
        vol = "HIGH_VOL"
    elif atr_percentile <= 30.0:
        vol = "LOW_VOL"
    else:
        vol = "MID_VOL"
    return f"{vol}_{'TREND' if trend else 'RANGE'}"


def market_path(fresh_root: Path, window_id: str, symbol: str) -> Path:
    path = fresh_root / "market" / f"{window_id}-{symbol}.csv"
    if not path.exists():
        raise TradePathError(f"MARKET_FILE_MISSING:{path}")
    return path


def enrich_trade(
    trade: Mapping[str, Any],
    *,
    strategy_id: str,
    variant_id: str,
    source_sha: str,
    rows: list[Candle],
    market_sha: str,
    policy_sha: str,
) -> dict[str, Any]:
    trade_id = text(trade.get("trade_id"), "trade_id")
    if trade.get("path_ambiguous") is True:
        raise TradePathError(f"PATH_AMBIGUOUS:{trade_id}")
    entry_price = number(trade.get("entry_price"), "entry_price", 0.0)
    exit_price = number(trade.get("exit_price"), "exit_price", 0.0)
    initial_sl = number(trade.get("initial_sl"), "initial_sl", 0.0)
    risk_price = number(trade.get("risk_price"), "risk_price", 1e-12)
    features = trade.get("features")
    if not isinstance(features, Mapping):
        raise TradePathError(f"FEATURES_REQUIRED:{trade_id}")
    atr = number(features.get("atr14"), "features.atr14", 1e-12)
    side = "LONG" if initial_sl < entry_price else "SHORT"
    signal_index = locate(rows, timestamp_ms(trade.get("signal_ts"), "signal_ts"), "signal_ts")
    entry_index = locate(rows, timestamp_ms(trade.get("entry_ts"), "entry_ts"), "entry_ts")
    exit_index = locate(rows, timestamp_ms(trade.get("exit_ts"), "exit_ts"), "exit_ts")
    if not signal_index < entry_index <= exit_index:
        raise TradePathError(f"TRADE_TIME_ORDER_INVALID:{trade_id}:{signal_index}:{entry_index}:{exit_index}")
    if abs(rows[entry_index].open - entry_price) > max(1e-9, abs(entry_price) * 1e-8):
        raise TradePathError(f"ENTRY_OPEN_PARITY_FAIL:{trade_id}:{rows[entry_index].open}:{entry_price}")

    signal_reference = rows[signal_index].close
    intermediate = rows[signal_index + 1:entry_index]
    pre_highs = [row.high for row in intermediate] + [rows[entry_index].open]
    pre_lows = [row.low for row in intermediate] + [rows[entry_index].open]
    pre_entry_mfe_r = favorable(side, signal_reference, pre_highs, pre_lows) / risk_price
    pre_entry_mae_r = adverse(side, signal_reference, pre_highs, pre_lows) / risk_price

    first_rows = rows[entry_index:min(len(rows), entry_index + int(POLICY["entry_observation_bars"]))]
    first3_mfe_r = favorable(side, entry_price, (row.high for row in first_rows), (row.low for row in first_rows)) / risk_price
    first3_mae_r = adverse(side, entry_price, (row.high for row in first_rows), (row.low for row in first_rows)) / risk_price

    post_rows = rows[exit_index + 1:min(len(rows), exit_index + 1 + int(POLICY["post_exit_horizon_bars"]))]
    post_exit_mfe_r = favorable(side, exit_price, (row.high for row in post_rows), (row.low for row in post_rows)) / risk_price
    exit_reason = text(trade.get("exit_reason"), "exit_reason").upper()
    post_stop_mfe_r = post_exit_mfe_r if exit_reason in {"SL", "STOP", "STOP_LOSS"} else 0.0

    path_descriptor = {
        "trade_id": trade_id,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "market_sha": market_sha,
        "signal_index": signal_index,
        "entry_index": entry_index,
        "exit_index": exit_index,
        "post_exit_end_index": exit_index + len(post_rows),
        "policy_sha": policy_sha,
    }
    feature_lineage = {
        "candidate_config_sha": trade.get("candidate_config_sha"),
        "strategy_source_sha": trade.get("strategy_source_sha"),
        "market_file_sha256": market_sha,
        "features": dict(features),
        "path_descriptor": path_descriptor,
    }
    event = {
        "event_id": canonical_sha({"trade_id": trade_id, "path_descriptor": path_descriptor}),
        "event_ts": text(trade.get("exit_ts"), "exit_ts"),
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "symbol": text(trade.get("symbol"), "symbol").upper(),
        "regime": regime_label(features),
        "window_id": text(trade.get("window_id"), "window_id").upper(),
        "side": side,
        "pnl_r": number(trade.get("net_loss_r"), "net_loss_r"),
        "mfe_r": number(trade.get("mfe_r"), "mfe_r", 0.0),
        "mae_r": number(trade.get("mae_r"), "mae_r", 0.0),
        "pre_entry_mfe_r": pre_entry_mfe_r,
        "pre_entry_mae_r": pre_entry_mae_r,
        "first3_mfe_r": first3_mfe_r,
        "first3_mae_r": first3_mae_r,
        "first3_observation_bars": len(first_rows),
        "entry_delay_bars": entry_index - signal_index,
        "stop_distance_atr": abs(entry_price - initial_sl) / atr,
        "post_stop_mfe_r": post_stop_mfe_r,
        "post_exit_mfe_r": post_exit_mfe_r,
        "post_exit_observation_bars": len(post_rows),
        "bars_to_mfe_peak": int(trade.get("bars_to_mfe") or 0),
        "bars_to_mae_peak": int(trade.get("bars_to_mae") or 0),
        "bars_held": int(trade.get("bars_held") or 0),
        "exit_reason": exit_reason,
        "signal_skill": str(trade.get("signal_skill") or "UNKNOWN"),
        "signal_why": str(trade.get("signal_why") or "UNKNOWN"),
        "source_sha": source_sha,
        "feature_lineage_sha": canonical_sha(feature_lineage),
        "path_segment_sha": canonical_sha(path_descriptor),
    }
    return event


def replay_files(replay_root: Path) -> list[Path]:
    return sorted(path for path in replay_root.rglob("replay-A.json") if path.parent.name and path.parent.parent.name)


def build_bundle(replay_path: Path, fresh_root: Path, output_path: Path, market_cache: dict[tuple[str, str], tuple[list[Candle], str]]) -> dict[str, Any]:
    payload = read_json(replay_path)
    trades = payload.get("trades")
    if not isinstance(trades, list):
        raise TradePathError(f"TRADES_ARRAY_REQUIRED:{replay_path}")
    variant_id = str(payload.get("variant_id") or replay_path.parent.name)
    strategy_id = replay_path.parent.parent.name
    replay_sha = file_sha(replay_path)
    manifest_path = fresh_root / "manifest.json"
    manifest = read_json(manifest_path)
    manifest_sha = file_sha(manifest_path)
    policy_sha = canonical_sha(POLICY)
    market_inventory = sorted({
        (text(trade.get("window_id"), "window_id").upper(), text(trade.get("symbol"), "symbol").upper(), text(trade.get("market_file_sha256"), "market_file_sha256"))
        for trade in trades
    })
    source_descriptor = {
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "replay_sha": replay_sha,
        "fresh_manifest_file_sha": manifest_sha,
        "fresh_authority_data_set_sha": manifest.get("authority_data_set_sha256"),
        "fresh_authority_manifest_sha": manifest.get("authority_manifest_sha256"),
        "market_inventory": market_inventory,
        "policy_sha": policy_sha,
    }
    source_sha = canonical_sha(source_descriptor)
    blockers: list[str] = []
    events: list[dict[str, Any]] = []
    for trade in trades:
        window_id = text(trade.get("window_id"), "window_id").upper()
        symbol = text(trade.get("symbol"), "symbol").upper()
        key = (window_id, symbol)
        if key not in market_cache:
            path = market_path(fresh_root, window_id, symbol)
            actual_sha = file_sha(path)
            market_cache[key] = (load_market(path), actual_sha)
        rows, actual_market_sha = market_cache[key]
        expected_market_sha = text(trade.get("market_file_sha256"), "market_file_sha256")
        if actual_market_sha != expected_market_sha:
            blockers.append(f"MARKET_SHA_MISMATCH:{window_id}:{symbol}")
            continue
        try:
            events.append(enrich_trade(
                trade,
                strategy_id=strategy_id,
                variant_id=variant_id,
                source_sha=source_sha,
                rows=rows,
                market_sha=actual_market_sha,
                policy_sha=policy_sha,
            ))
        except TradePathError as exc:
            blockers.append(str(exc))
    duplicate_count = len(events) - len({row["event_id"] for row in events})
    if duplicate_count:
        blockers.append(f"DUPLICATE_EVENT_ID:{duplicate_count}")
    state = "PASS_TRADE_PATH_EVIDENCE" if not blockers and events else "WAIT_NO_TRADES" if not blockers else "HOLD_TRADE_PATH_EVIDENCE"
    result = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": state,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "source_sha": source_sha,
        "source_descriptor": source_descriptor,
        "source_descriptor_sha": canonical_sha(source_descriptor),
        "replay_path": str(replay_path),
        "replay_sha": replay_sha,
        "event_count": len(events),
        "duplicate_event_count": duplicate_count,
        "blocker_codes": sorted(set(blockers)),
        "policy": POLICY,
        "policy_sha": policy_sha,
        "events": events,
        **SAFETY,
    }
    result["bundle_sha"] = canonical_sha(result)
    write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    files = replay_files(args.replay_root)
    if not files:
        raise SystemExit("REPLAY_A_FILES_MISSING")
    market_cache: dict[tuple[str, str], tuple[list[Candle], str]] = {}
    rows = []
    for replay_path in files:
        strategy_id = replay_path.parent.parent.name
        variant_id = replay_path.parent.name
        output_path = args.out / strategy_id / variant_id / "path_evidence.json"
        bundle = build_bundle(replay_path, args.fresh_root, output_path, market_cache)
        rows.append({
            "strategy_id": strategy_id,
            "variant_id": variant_id,
            "state": bundle["state"],
            "event_count": bundle["event_count"],
            "source_sha": bundle["source_sha"],
            "bundle_sha": bundle["bundle_sha"],
            "path": str(output_path),
            "blocker_codes": bundle["blocker_codes"],
        })
    blockers = [row for row in rows if row["state"] == "HOLD_TRADE_PATH_EVIDENCE"]
    index = {
        "schema_version": INDEX_SCHEMA,
        "version": VERSION,
        "state": "PASS_TRADE_PATH_EVIDENCE_INDEX" if not blockers else "HOLD_TRADE_PATH_EVIDENCE_INDEX",
        "bundle_count": len(rows),
        "pass_bundle_count": sum(row["state"] == "PASS_TRADE_PATH_EVIDENCE" for row in rows),
        "empty_bundle_count": sum(row["state"] == "WAIT_NO_TRADES" for row in rows),
        "hold_bundle_count": len(blockers),
        "rows": rows,
        "policy_sha": canonical_sha(POLICY),
        **SAFETY,
    }
    index["index_sha"] = canonical_sha(index)
    write_json(args.out / "index.json", index)
    print(index["state"], "bundles=", len(rows), "pass=", index["pass_bundle_count"], "empty=", index["empty_bundle_count"])
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
