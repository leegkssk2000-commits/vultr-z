#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BAR_MS = 15 * 60 * 1000
REQ = ("timestamp_ms", "open", "high", "low", "close", "volume")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> tuple[list[dict[str, float]], dict[str, Any]]:
    rows: list[dict[str, float]] = []
    duplicate = 0
    gaps = 0
    seen: set[int] = set()
    last: int | None = None
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != REQ:
            raise SystemExit(f"BAD_SCHEMA:{path}:{reader.fieldnames}")
        for line, x in enumerate(reader, 2):
            if any(x.get(k, "") == "" for k in REQ):
                raise SystemExit(f"MISSING_FIELD:{path}:{line}")
            ts = int(x["timestamp_ms"])
            o, h, l, c, v = (float(x[k]) for k in REQ[1:])
            if not all(math.isfinite(z) for z in (o, h, l, c, v)):
                raise SystemExit(f"NONFINITE:{path}:{line}")
            if not (h >= max(o, c, l) and l <= min(o, c, h) and v >= 0):
                raise SystemExit(f"BAD_OHLCV:{path}:{line}")
            if ts in seen:
                duplicate += 1
            if last is not None:
                if ts <= last:
                    raise SystemExit(f"NON_MONOTONIC:{path}:{line}")
                if ts - last != BAR_MS:
                    gaps += 1
            seen.add(ts)
            last = ts
            rows.append({"timestamp_ms": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
    if not rows:
        raise SystemExit(f"EMPTY:{path}")
    return rows, {
        "rows": len(rows),
        "first_timestamp_ms": int(rows[0]["timestamp_ms"]),
        "last_timestamp_ms": int(rows[-1]["timestamp_ms"]),
        "duplicate_timestamps": duplicate,
        "gap_count": gaps,
        "sha256": sha256_file(path),
        "state": "PASS" if duplicate == 0 and gaps == 0 else "HOLD",
    }


@dataclass
class Position:
    entry_i: int
    entry_ts: int
    entry_price: float


def replay(rows: list[dict[str, float]], lookback: int) -> dict[str, Any]:
    pos: Position | None = None
    pending_entry = False
    pending_exit = False
    trades: list[dict[str, Any]] = []
    signals = 0
    exposure_bars = 0

    for i, bar in enumerate(rows):
        if pending_exit and pos is not None:
            trades.append({
                "entry_ts": pos.entry_ts,
                "exit_ts": int(bar["timestamp_ms"]),
                "entry": pos.entry_price,
                "exit": float(bar["open"]),
                "gross_return": float(bar["open"]) / pos.entry_price - 1.0,
                "bars_held": i - pos.entry_i,
            })
            pos = None
            pending_exit = False
        if pending_entry and pos is None:
            pos = Position(i, int(bar["timestamp_ms"]), float(bar["open"]))
            pending_entry = False
        if pos is not None:
            exposure_bars += 1

        if i < lookback or i + 1 >= len(rows):
            continue
        prior = rows[i - lookback:i]
        prior_high = max(float(x["high"]) for x in prior)
        prior_low = min(float(x["low"]) for x in prior)
        close = float(bar["close"])
        if pos is None and close > prior_high:
            pending_entry = True
            signals += 1
        elif pos is not None and close < prior_low:
            pending_exit = True

    return {
        "signal_count": signals,
        "closed_trades": len(trades),
        "open_position_at_end": pos is not None or pending_entry,
        "exposure_fraction": exposure_bars / len(rows),
        "trades": trades,
    }


def metrics(rets: list[float]) -> dict[str, Any]:
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    pf: float | str | None = None
    if gross_loss > 0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pf = "INF"
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / peak)
    return {
        "trade_count": len(rets),
        "win_rate": len(wins) / len(rets) if rets else None,
        "compound_return": equity - 1.0 if rets else 0.0,
        "expectancy_per_trade": sum(rets) / len(rets) if rets else None,
        "profit_factor": pf,
        "max_drawdown": max_dd,
    }


def require_cost(cost: dict[str, Any]) -> None:
    if not str(cost.get("state", "")).startswith("PASS_BINGX_REAL_OBSERVATION_COLLECTED"):
        raise SystemExit(f"HOLD_COST_STATE:{cost.get('state')}")
    if cost.get("source_tier") != "official" or cost.get("calibration_mode") != "real":
        raise SystemExit("HOLD_COST_NOT_OFFICIAL_REAL")
    if cost.get("execution_authority") != "NONE" or cost.get("order_authority") != "BLOCKED":
        raise SystemExit("HOLD_COST_AUTHORITY")
    for key in ("taker_fee_pct", "funding_p95_abs_pct_8h", "slippage_floor_bps_by_notional", "receipt_sha256"):
        if cost.get(key) is None:
            raise SystemExit(f"HOLD_COST_FIELD:{key}")
    if not cost["slippage_floor_bps_by_notional"]:
        raise SystemExit("HOLD_EMPTY_SLIPPAGE")


def worst_cost(cost: dict[str, Any]) -> dict[str, float]:
    worst_slip = max(float(x["slippage_bps_one_way"]) for x in cost["slippage_floor_bps_by_notional"])
    return {
        "taker_fee_pct_one_way": float(cost["taker_fee_pct"]),
        "slippage_bps_one_way": worst_slip,
        "funding_p95_abs_pct_8h": float(cost["funding_p95_abs_pct_8h"]),
    }


def net_returns(trades: list[dict[str, Any]], c: dict[str, float]) -> tuple[list[float], dict[str, float]]:
    fee_rt_pct = 2.0 * c["taker_fee_pct_one_way"]
    slip_rt_pct = 2.0 * c["slippage_bps_one_way"] / 100.0
    rets: list[float] = []
    funding_sum = 0.0
    for t in trades:
        hours = float(t["bars_held"]) * 0.25
        funding_pct = c["funding_p95_abs_pct_8h"] * (hours / 8.0)
        funding_sum += funding_pct
        total_cost_decimal = (fee_rt_pct + slip_rt_pct + funding_pct) / 100.0
        rets.append(float(t["gross_return"]) - total_cost_decimal)
    return rets, {
        "fee_round_trip_pct": fee_rt_pct,
        "slippage_round_trip_pct": slip_rt_pct,
        "funding_p95_abs_pct_8h": c["funding_p95_abs_pct_8h"],
        "mean_funding_cost_pct_per_trade": funding_sum / len(trades) if trades else 0.0,
    }


def manifest_row(manifest: dict[str, Any], window: str, symbol: str) -> dict[str, Any]:
    hits = [x for x in manifest.get("files", []) if x.get("kind") == "market" and x.get("interval") == "15m" and x.get("window_id") == window and x.get("symbol") == symbol]
    if len(hits) != 1:
        raise SystemExit(f"HOLD_MANIFEST_ROW:{window}:{symbol}:{len(hits)}")
    return hits[0]


def evaluate_window(data_root: Path, manifest: dict[str, Any], window: str, symbol: str, lookback: int, c: dict[str, float], dd_limit_pct: float | None) -> dict[str, Any]:
    m = manifest_row(manifest, window, symbol)
    path = data_root / m["path"]
    rows, integ = load_csv(path)
    integ.update({
        "manifest_rows_match": len(rows) == int(m["rows"]),
        "manifest_sha_match": integ["sha256"] == m["sha256"],
        "manifest_range_match": integ["first_timestamp_ms"] == int(m["start_ms"]) and integ["last_timestamp_ms"] == int(m["end_ms"]),
    })
    integrity_ok = integ["state"] == "PASS" and integ["manifest_rows_match"] and integ["manifest_sha_match"] and integ["manifest_range_match"]
    if not integrity_ok:
        raise SystemExit(f"HOLD_DATA_INTEGRITY:{window}:{symbol}:{json.dumps(integ,sort_keys=True)}")
    r = replay(rows, lookback)
    gross = metrics([float(t["gross_return"]) for t in r["trades"]])
    net_rets, cost_applied = net_returns(r["trades"], c)
    net = metrics(net_rets)
    dd_within = None if dd_limit_pct is None else net["max_drawdown"] * 100.0 <= dd_limit_pct
    edge_pass = bool(net["trade_count"] > 0 and net["compound_return"] > 0 and (net["expectancy_per_trade"] or 0.0) > 0)
    return {
        "window": window,
        "symbol": symbol,
        "integrity_ok": integrity_ok,
        "integrity": integ,
        "signal_count": r["signal_count"],
        "closed_trades": r["closed_trades"],
        "open_position_at_end": r["open_position_at_end"],
        "exposure_fraction": r["exposure_fraction"],
        "gross": gross,
        "cost": cost_applied,
        "net": net,
        "base_edge_pass": edge_pass,
        "dd_limit_pct_ssot": dd_limit_pct,
        "dd_within_ssot": dd_within,
        "survivor_eligible": bool(edge_pass and dd_within is True),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--cost-model", type=Path, required=True)
    ap.add_argument("--dd-limit-pct", type=float, default=0.0)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    contract = json.loads(ns.contract.read_text())
    manifest = json.loads(ns.manifest.read_text())
    cost = json.loads(ns.cost_model.read_text())
    require_cost(cost)
    if contract.get("state") != "FROZEN_BEFORE_REPLAY":
        raise SystemExit("HOLD_CONTRACT_NOT_FROZEN")
    if not str(manifest.get("state", "")).startswith("PASS_") or int(manifest.get("forward_overlap_count", -1)) != 0:
        raise SystemExit("HOLD_HISTORICAL_MANIFEST")
    lookback = int(contract["signal"]["lookback_bars"])
    if lookback != 16 or contract["timeframe"] != "15m" or contract["signal"]["same_bar_fill"] is not False:
        raise SystemExit("HOLD_BASE_CONTRACT_DRIFT")
    dd_limit = ns.dd_limit_pct if ns.dd_limit_pct > 0 else None
    c = worst_cost(cost)

    results: list[dict[str, Any]] = []
    for window in (contract["data"]["development_window"], contract["data"]["oos_window"]):
        for symbol in contract["symbols"]:
            results.append(evaluate_window(ns.data_root, manifest, window, symbol, lookback, c, dd_limit))

    oos = [x for x in results if x["window"] == contract["data"]["oos_window"]]
    base_edge_pass_symbols = [x["symbol"] for x in oos if x["base_edge_pass"]]
    base_edge_fail_symbols = [x["symbol"] for x in oos if not x["base_edge_pass"]]
    all_oos_edge_pass = len(base_edge_pass_symbols) == len(oos) and bool(oos)
    any_oos_edge_pass = bool(base_edge_pass_symbols)
    dd_resolved = dd_limit is not None
    survivor_symbols = [x["symbol"] for x in oos if x["survivor_eligible"]]

    if any_oos_edge_pass:
        state = "PASS_P2_BASE_EDGE_EXISTS_HOLD_SURVIVOR_GATE" if not dd_resolved else ("PASS_P2_BASE_SURVIVOR_CANDIDATE" if survivor_symbols else "HOLD_P2_DD_GATE")
    else:
        state = "FAIL_P2_TREND_MOMENTUM_BASE_EDGE"

    receipt = {
        "schema_version": "zel.p2.trend_momentum_base.replay.v1",
        "state": state,
        "family": "trend_momentum",
        "candidate_id": contract["candidate_id"],
        "research_only": True,
        "contract_frozen_before_replay": True,
        "parameter_selection_performed": False,
        "exit_optimization_performed": False,
        "symbols": contract["symbols"],
        "timeframe": "15m",
        "lookback_bars": lookback,
        "lookback_clock_hours": 4,
        "fill_model": "closed_bar_signal_then_next_bar_open",
        "same_bar_fill": False,
        "data": {
            "branch": contract["data"]["source_branch"],
            "development_window": contract["data"]["development_window"],
            "oos_window": contract["data"]["oos_window"],
            "untouched_window": contract["data"]["untouched_window"],
            "untouched_window_accessed": False,
            "forward_overlap_count": manifest.get("forward_overlap_count"),
        },
        "cost_source": {
            "receipt_sha256": cost["receipt_sha256"],
            "source_tier": cost["source_tier"],
            "observed_at": cost.get("observed_at"),
            "worst_available_cost_envelope": c,
            "notional_bucket_selection_performed": False,
        },
        "dd_ssot": {
            "resolved": dd_resolved,
            "limit_pct": dd_limit,
            "state": "PASS_RESOLVED" if dd_resolved else "HOLD_Z_POLICY_V3_DD_LIMIT_NOT_RESOLVED",
        },
        "results": results,
        "oos_base_edge_pass_symbols": base_edge_pass_symbols,
        "oos_base_edge_fail_symbols": base_edge_fail_symbols,
        "any_oos_base_edge_pass": any_oos_edge_pass,
        "all_oos_base_edge_pass": all_oos_edge_pass,
        "survivor_symbols": survivor_symbols,
        "win_rate_is_pass_gate": False,
        "untouched_w3_accessed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "resolve DD SSOT then durability gate without changing BASE" if any_oos_edge_pass
            else "do not optimize exit; evaluate at most two predeclared Trend/Momentum variants under the same W1/W2 costed gate"
        ),
    }
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "state": state,
        "oos_pass": base_edge_pass_symbols,
        "oos_fail": base_edge_fail_symbols,
        "dd_ssot": receipt["dd_ssot"]["state"],
        "untouched_w3_accessed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
