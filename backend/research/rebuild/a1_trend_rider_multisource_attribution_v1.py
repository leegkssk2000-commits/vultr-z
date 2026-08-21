#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.policy_kernel_v1 import atr


def stable(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def profit_factor(values: list[float]) -> float | None:
    wins = sum(x for x in values if x > 0)
    losses = -sum(x for x in values if x < 0)
    if losses <= 0:
        return None
    value = wins / losses
    return value if math.isfinite(value) else None


def group_stats(rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    result = []
    for name, items in sorted(groups.items()):
        values = [float(x["net_bps"]) for x in items]
        result.append({
            "group": name,
            "trade_count": len(items),
            "net_bps": sum(values),
            "expectancy_bps": sum(values) / len(values),
            "profit_factor": profit_factor(values),
            "win_rate": sum(x > 0 for x in values) / len(values),
        })
    return result


def latest_funding(rows: list[dict[str, float | int]], entry_ts: int) -> float:
    eligible = [float(x["rate"]) for x in rows if int(x["ts_ms"]) <= entry_ts]
    return eligible[-1] if eligible else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    receipt = json.loads(Path(args.receipt).read_text())
    contract = json.loads(Path(args.contract).read_text())
    if receipt.get("strategy_id") != "trend_rider":
        raise RuntimeError("TREND_RIDER_RECEIPT_REQUIRED")
    if contract.get("state") != "FROZEN_PROSPECTIVE_DIAGNOSTIC_CONTRACT":
        raise RuntimeError("FROZEN_ATTRIBUTION_CONTRACT_REQUIRED")
    symbols = list((contract.get("universe_selection") or {}).get("symbols") or [])
    if sorted(symbols) != sorted({str(x["symbol"]) for x in receipt.get("trades") or []}):
        raise RuntimeError("RECEIPT_UNIVERSE_DOES_NOT_MATCH_FROZEN_CONTRACT")

    bars_by: dict[str, list[dict[str, float | int]]] = {}
    maps: dict[str, dict[int, int]] = {}
    funding_by: dict[str, list[dict[str, float | int]]] = {}
    authority = json.loads(ev.COST_PATH.read_text())
    for symbol in symbols:
        bars = ev.fetch_bars(symbol, "1h", 1000)
        bars_by[symbol] = bars
        maps[symbol] = {int(x["ts_ms"]): i for i, x in enumerate(bars)}
        funding_by[symbol] = list(ev.fetch_execution_snapshot(symbol, authority)["funding_rows"])

    enriched = []
    for trade in receipt.get("trades") or []:
        symbol = str(trade["symbol"])
        signal_ts = int(trade["signal_ts"])
        index = maps[symbol].get(signal_ts)
        if index is None or index < 50:
            raise RuntimeError(f"SIGNAL_BAR_NOT_AVAILABLE:{symbol}:{signal_ts}")
        bars = bars_by[symbol]
        current_volume = float(bars[index].get("volume") or 0.0)
        prior_volumes = [float(x.get("volume") or 0.0) for x in bars[index - 24:index]]
        volume_ratio = current_volume / max(median(prior_volumes), 1e-12)
        atr_ratio = atr(bars[: index + 1], 14) / max(atr(bars[: index + 1], 50), 1e-12)
        funding_rate = latest_funding(funding_by[symbol], int(trade["entry_ts"]))
        hour = datetime.fromtimestamp(signal_ts / 1000, tz=timezone.utc).hour
        side = str(trade["side"])
        aligned = (side == "long" and funding_rate > 0) or (side == "short" and funding_rate < 0)
        enriched.append({
            **trade,
            "volume_ratio_24h_median": volume_ratio,
            "atr14_over_atr50": atr_ratio,
            "funding_rate": funding_rate,
            "volume_participation": "ABOVE_PRIOR_24H_MEDIAN" if volume_ratio >= 1.0 else "BELOW_PRIOR_24H_MEDIAN",
            "atr_regime": "ATR_EXPANDING" if atr_ratio >= 1.0 else "ATR_CONTRACTING",
            "funding_alignment": "ALIGNED_CROWDING" if aligned else "CONTRA_OR_ZERO",
            "session": "APAC" if hour < 8 else "EU" if hour < 16 else "US",
        })

    groupers: dict[str, Callable[[dict[str, Any]], str]] = {
        "symbol": lambda x: str(x["symbol"]),
        "side": lambda x: str(x["side"]),
        "session": lambda x: str(x["session"]),
        "volume_participation": lambda x: str(x["volume_participation"]),
        "atr_regime": lambda x: str(x["atr_regime"]),
        "funding_alignment": lambda x: str(x["funding_alignment"]),
    }
    output = {
        "schema_version": "zel.a1.trend_rider.multisource_attribution.v1",
        "state": "PASS_DIAGNOSTIC_ATTRIBUTION",
        "strategy_id": "trend_rider",
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "contract_sha256": stable(contract),
        "trade_count": len(enriched),
        "dimensions": {name: group_stats(enriched, key) for name, key in groupers.items()},
        "feature_definitions": {
            "volume_participation": "signal_bar_volume / median(previous_24_closed_bar_volumes), fixed split at 1.0",
            "atr_regime": "ATR14 / ATR50 at signal close, fixed split at 1.0",
            "funding_alignment": "latest entry-observable funding sign agrees with position side",
            "session": "fixed UTC APAC[00,08), EU[08,16), US[16,24)"
        },
        "parameter_sweep": False,
        "thresholds_changed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "next_use": "hypothesis generation only; any repair requires a new post-freeze prospective boundary"
    }
    output["receipt_sha256"] = stable(output)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print("A1_TREND_RIDER_MULTISOURCE_ATTRIBUTION=" + json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
