#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_trendrider_primary_loss_tail_path_replay_v1 as v1


def _normalize_bars(payload: Any) -> list[dict[str, float | int]]:
    rows = payload.get("data", payload if isinstance(payload, list) else [])
    out: list[dict[str, float | int]] = []
    for row in rows:
        if isinstance(row, dict):
            ts = int(row.get("time") or row.get("openTime") or row.get("timestamp"))
            vol = row.get("volume", row.get("vol", row.get("baseVolume", 0)))
            out.append({"ts_ms": ts, "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]), "volume": float(vol or 0)})
        else:
            vol = row[5] if len(row) > 5 else 0
            out.append({"ts_ms": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(vol or 0)})
    return sorted({int(x["ts_ms"]): x for x in out}.values(), key=lambda x: int(x["ts_ms"]))


def _frozen_end_by_symbol(source: Mapping[str, Any]) -> dict[str, int]:
    rows = ((source.get("source") or {}).get("symbols") or []) if isinstance(source.get("source"), Mapping) else []
    result: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "")
        end = int(row.get("last_post_boundary_ts") or 0)
        if symbol and end > 0:
            result[symbol] = end
    if not result:
        raise RuntimeError("FROZEN_SOURCE_WINDOW_MISSING")
    return result


def _fetch_frozen_bars(symbol: str, end_ms: int) -> list[dict[str, float | int]]:
    payload = ev.request_json(ev.KLINE_API, {"symbol": symbol, "interval": "1h", "limit": 1000, "endTime": int(end_ms)})
    bars = _normalize_bars(payload)
    if len(bars) != 1000:
        raise RuntimeError(f"FROZEN_BAR_COUNT_DRIFT:{symbol}:{len(bars)}")
    if int(bars[-1]["ts_ms"]) != int(end_ms):
        raise RuntimeError(f"FROZEN_BAR_END_DRIFT:{symbol}:{bars[-1]['ts_ms']}:{end_ms}")
    return bars


def _bind_geometry(source: Mapping[str, Any], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    module, _ = v1._load_historical_policy(source)
    cfg = ev.config_instance(module)
    compute, build = ev.policy_functions(module, "trend_rider")
    policy_sha = str(source.get("policy_sha") or "")
    snaps = source.get("execution_snapshots") or {}
    end_by_symbol = _frozen_end_by_symbol(source)
    bars_by: dict[str, list[dict[str, Any]]] = {}
    for symbol in sorted({str(x["symbol"]) for x in rows}):
        if symbol not in end_by_symbol:
            raise RuntimeError(f"FROZEN_SYMBOL_WINDOW_MISSING:{symbol}")
        bars_by[symbol] = _fetch_frozen_bars(symbol, end_by_symbol[symbol])
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row["symbol"])
        bars = bars_by[symbol]
        idx = next((i for i, b in enumerate(bars) if int(b["ts_ms"]) == int(row["signal_ts"])), None)
        if idx is None:
            raise RuntimeError(f"SIGNAL_BAR_MISSING:{symbol}:{row['signal_ts']}")
        feature = compute(bars[: idx + 1], symbol=symbol, now_ts_ms=int(row["signal_ts"]), config=cfg)
        snap = snaps.get(symbol) if isinstance(snaps, Mapping) else None
        if not isinstance(snap, Mapping):
            raise RuntimeError(f"EXECUTION_SNAPSHOT_MISSING:{symbol}")
        intent = build(feature, policy_source_sha=policy_sha, verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]), config=cfg)
        got = ev.intent_sha(intent)
        expected = str(row["intent_sha"])
        if got != expected:
            raise RuntimeError(f"FROZEN_INTENT_GEOMETRY_DRIFT:{symbol}:{row['signal_ts']}:{got}:{expected}")
        sl = getattr(intent, "sl", None)
        if sl is None:
            raise RuntimeError(f"FROZEN_SL_MISSING:{symbol}:{row['signal_ts']}")
        enriched = dict(row)
        enriched["intent_geometry"] = {"sl": float(sl)}
        out.append(enriched)
    return out, bars_by


def run(source_path: Path, out_path: Path) -> dict[str, Any]:
    old = v1._bind_geometry
    v1._bind_geometry = _bind_geometry
    try:
        result = v1.run(source_path, out_path)
    finally:
        v1._bind_geometry = old
    result["historical_bar_window_contract"] = "SOURCE_LAST_POST_BOUNDARY_ENDTIME_1000"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    r = run(Path(a.source), Path(a.out))
    b = r.get("best_candidate")
    if b:
        m = b["metrics"]
        print("PASS_TRENDRIDER_PRIMARY_LOSS_TAIL_CANDIDATE_V2", b["candidate_id"], f"T={m['completed_trades']}", f"WR={m['win_rate']:.6f}", f"PNL_BPS={m['net_pnl_bps']:.6f}", f"PF={m['profit_factor']:.6f}", f"PAYOFF={m['realized_payoff']:.6f}", f"DD_BPS={m['max_drawdown_bps']:.6f}")
    else:
        print("KEEP_TRENDRIDER_PRIMARY_NO_VALID_LOSS_TAIL_CANDIDATE_V2")


if __name__ == "__main__":
    main()
