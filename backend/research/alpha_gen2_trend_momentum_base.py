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


def canonical_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> tuple[list[dict[str, float]], dict[str, Any]]:
    rows: list[dict[str, float]] = []
    seen: set[int] = set()
    duplicate = 0
    gaps = 0
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


def ema_series(values: list[float], period: int) -> list[float]:
    if period <= 1:
        raise SystemExit("BAD_EMA_PERIOD")
    alpha = 2.0 / (period + 1.0)
    out: list[float] = []
    cur: float | None = None
    for v in values:
        cur = v if cur is None else alpha * v + (1.0 - alpha) * cur
        out.append(cur)
    return out


@dataclass
class Position:
    entry_i: int
    entry_ts: int
    entry_price: float


def replay(rows: list[dict[str, float]], fast_n: int, slow_n: int, slope_lag: int) -> dict[str, Any]:
    closes = [float(x["close"]) for x in rows]
    fast = ema_series(closes, fast_n)
    slow = ema_series(closes, slow_n)
    pos: Position | None = None
    pending_entry = False
    pending_exit = False
    trades: list[dict[str, Any]] = []
    entry_signals = 0
    exit_signals = 0
    exposure_bars = 0
    warmup = slow_n + slope_lag

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

        if i < warmup or i + 1 >= len(rows):
            continue

        close = closes[i]
        prev_close = closes[i - 1]
        slow_rising = slow[i] > slow[i - slope_lag]
        trend_regime = fast[i] > slow[i] and close > slow[i] and slow_rising
        pullback_resume = prev_close <= fast[i - 1] and close > fast[i] and close > prev_close

        if pos is None and not pending_entry and trend_regime and pullback_resume:
            pending_entry = True
            entry_signals += 1
        elif pos is not None and not pending_exit:
            trend_broken = close < slow[i] or fast[i] < slow[i] or not slow_rising
            if trend_broken:
                pending_exit = True
                exit_signals += 1

    return {
        "entry_signal_count": entry_signals,
        "exit_signal_count": exit_signals,
        "closed_trades": len(trades),
        "open_position_at_end": pos is not None or pending_entry,
        "exposure_fraction": exposure_bars / len(rows),
        "trades": trades,
    }


def metrics(rets: list[float]) -> dict[str, Any]:
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gp = sum(wins)
    gl = -sum(losses)
    if gl > 0:
        pf: float | str | None = gp / gl
    elif gp > 0:
        pf = "INF"
    else:
        pf = None
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
        "worst_trade": min(rets) if rets else None,
        "best_trade": max(rets) if rets else None,
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
    return {
        "taker_fee_pct_one_way": float(cost["taker_fee_pct"]),
        "slippage_bps_one_way": max(float(x["slippage_bps_one_way"]) for x in cost["slippage_floor_bps_by_notional"]),
        "funding_p95_abs_pct_8h": float(cost["funding_p95_abs_pct_8h"]),
    }


def apply_cost(trades: list[dict[str, Any]], c: dict[str, float]) -> tuple[list[float], dict[str, float]]:
    fee_rt_pct = 2.0 * c["taker_fee_pct_one_way"]
    slip_rt_pct = 2.0 * c["slippage_bps_one_way"] / 100.0
    out: list[float] = []
    funding_sum = 0.0
    for t in trades:
        hours = float(t["bars_held"]) * 0.25
        funding_pct = c["funding_p95_abs_pct_8h"] * (hours / 8.0)
        funding_sum += funding_pct
        total_cost_decimal = (fee_rt_pct + slip_rt_pct + funding_pct) / 100.0
        out.append(float(t["gross_return"]) - total_cost_decimal)
    return out, {
        "fee_round_trip_pct": fee_rt_pct,
        "slippage_round_trip_pct": slip_rt_pct,
        "funding_p95_abs_pct_8h": c["funding_p95_abs_pct_8h"],
        "mean_funding_cost_pct_per_trade": funding_sum / len(trades) if trades else 0.0,
    }


def manifest_row(manifest: dict[str, Any], window: str, symbol: str) -> dict[str, Any]:
    hits = [
        x for x in manifest.get("files", [])
        if x.get("kind") == "market" and x.get("interval") == "15m" and x.get("window_id") == window and x.get("symbol") == symbol
    ]
    if len(hits) != 1:
        raise SystemExit(f"HOLD_MANIFEST_ROW:{window}:{symbol}:{len(hits)}")
    return hits[0]


def locate_file(data_root: Path, m: dict[str, Any]) -> Path:
    p = data_root / str(m["path"])
    if p.is_file():
        return p
    p2 = data_root / "zel_historical_oos_v1" / str(m["path"])
    if p2.is_file():
        return p2
    raise SystemExit(f"HOLD_DATA_FILE_MISSING:{m['path']}")


def evaluate_symbol(data_root: Path, manifest: dict[str, Any], window: str, symbol: str, contract: dict[str, Any]) -> dict[str, Any]:
    m = manifest_row(manifest, window, symbol)
    path = locate_file(data_root, m)
    rows, integ = load_csv(path)
    integ.update({
        "manifest_rows_match": len(rows) == int(m["rows"]),
        "manifest_sha_match": integ["sha256"] == m["sha256"],
        "manifest_range_match": integ["first_timestamp_ms"] == int(m["start_ms"]) and integ["last_timestamp_ms"] == int(m["end_ms"]),
    })
    integrity_ok = bool(integ["state"] == "PASS" and integ["manifest_rows_match"] and integ["manifest_sha_match"] and integ["manifest_range_match"])
    if not integrity_ok:
        raise SystemExit(f"HOLD_DATA_INTEGRITY:{window}:{symbol}:{json.dumps(integ,sort_keys=True)}")
    s = contract["signal"]
    r = replay(rows, int(s["fast_ema_bars"]), int(s["slow_ema_bars"]), int(s["slow_slope_lag_bars"]))
    gross_rets = [float(t["gross_return"]) for t in r["trades"]]
    return {
        "window": window,
        "symbol": symbol,
        "integrity_ok": True,
        "integrity": integ,
        "entry_signal_count": r["entry_signal_count"],
        "exit_signal_count": r["exit_signal_count"],
        "closed_trades": r["closed_trades"],
        "open_position_at_end": r["open_position_at_end"],
        "exposure_fraction": r["exposure_fraction"],
        "gross": metrics(gross_rets),
        "trades": r["trades"],
    }


def validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("state") != "FROZEN_BEFORE_REPLAY" or contract.get("family") != "trend_momentum":
        raise SystemExit("HOLD_CONTRACT_STATE")
    if contract.get("candidate_id") != "TM_GEN2_BASE_4H_24H_PULLBACK_RESUME_LONG_V1":
        raise SystemExit("HOLD_CANDIDATE_ID")
    if contract.get("timeframe") != "15m" or contract.get("symbols") != ["BTCUSDT", "ETHUSDT"]:
        raise SystemExit("HOLD_CONTRACT_UNIVERSE")
    s = contract.get("signal", {})
    expected = (int(s.get("fast_ema_bars", -1)), int(s.get("slow_ema_bars", -1)), int(s.get("slow_slope_lag_bars", -1)))
    if expected != (16, 96, 16):
        raise SystemExit("HOLD_CONTRACT_HORIZON_DRIFT")
    if s.get("same_bar_fill") is not False or s.get("fill") != "next_bar_open":
        raise SystemExit("HOLD_FILL_DRIFT")
    if any(s.get(k) is not None for k in ("stop_loss", "take_profit", "trailing_overlay", "volume_filter")):
        raise SystemExit("HOLD_PREMATURE_OVERLAY")
    if s.get("parameter_selection_performed") is not False or s.get("exit_optimization_performed") is not False:
        raise SystemExit("HOLD_OPTIMIZATION_DRIFT")
    if contract.get("execution_authority") != "NONE" or contract.get("order_authority") != "BLOCKED":
        raise SystemExit("HOLD_AUTHORITY_DRIFT")


def load_manifest(path: Path) -> dict[str, Any]:
    m = json.loads(path.read_text())
    if not str(m.get("state", "")).startswith("PASS_") or int(m.get("forward_overlap_count", -1)) != 0:
        raise SystemExit("HOLD_HISTORICAL_MANIFEST")
    return m


def public_result(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "trades"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("w1_gross", "w2_cost"), required=True)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--w1-receipt", type=Path)
    ap.add_argument("--cost-model", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    contract = json.loads(ns.contract.read_text())
    validate_contract(contract)
    manifest = load_manifest(ns.manifest)
    data = contract["data"]
    window = data["development_window"] if ns.mode == "w1_gross" else data["oos_window"]

    if ns.mode == "w2_cost":
        if ns.w1_receipt is None or not ns.w1_receipt.is_file():
            raise SystemExit("HOLD_W1_RECEIPT_REQUIRED")
        w1 = json.loads(ns.w1_receipt.read_text())
        if w1.get("state") != "PASS_GEN2_W1_GROSS_EDGE":
            raise SystemExit(f"HOLD_W1_NOT_PASS:{w1.get('state')}")
        if ns.cost_model is None or not ns.cost_model.is_file():
            raise SystemExit("HOLD_COST_REQUIRED")
    else:
        if ns.cost_model is not None:
            raise SystemExit("HOLD_W1_MUST_NOT_ACCESS_COST")

    rows = [evaluate_symbol(ns.data_root, manifest, window, symbol, contract) for symbol in contract["symbols"]]
    all_trades = [t for r in rows for t in r["trades"]]
    gross_rets = [float(t["gross_return"]) for t in all_trades]
    gross = metrics(gross_rets)
    symbols_with_closed_trade = sum(1 for r in rows if r["closed_trades"] > 0)

    if ns.mode == "w1_gross":
        gate = contract["w1_gross_gate"]
        gate_pass = bool(
            gross["trade_count"] >= int(gate["minimum_closed_trades_total"])
            and symbols_with_closed_trade >= int(gate["minimum_symbols_with_closed_trade"])
            and gross["compound_return"] > 0
            and (gross["expectancy_per_trade"] or 0.0) > 0
        )
        state = "PASS_GEN2_W1_GROSS_EDGE" if gate_pass else "FAIL_GEN2_W1_GROSS_EDGE"
        receipt: dict[str, Any] = {
            "schema_version": "zel.alpha_gen2.trend_momentum_base.replay.v1",
            "state": state,
            "mode": ns.mode,
            "family": contract["family"],
            "candidate_id": contract["candidate_id"],
            "research_only": True,
            "contract_frozen_before_replay": True,
            "parameter_selection_performed": False,
            "exit_optimization_performed": False,
            "donchian_logic_reused": False,
            "window": window,
            "symbols": contract["symbols"],
            "results": [public_result(r) for r in rows],
            "aggregate_gross": gross,
            "symbols_with_closed_trade": symbols_with_closed_trade,
            "gate_pass": gate_pass,
            "cost_model_accessed": False,
            "W2_access_authorized": gate_pass,
            "W3_untouched": True,
            "dd_ssot_accessed": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold" if gate_pass else "route_change"
        }
    else:
        cost = json.loads(ns.cost_model.read_text())
        require_cost(cost)
        c = worst_cost(cost)
        net_rets, cost_applied = apply_cost(all_trades, c)
        net = metrics(net_rets)
        gate = contract["w2_cost_gate"]
        gate_pass = bool(
            net["trade_count"] >= int(gate["minimum_closed_trades_total"])
            and symbols_with_closed_trade >= int(gate["minimum_symbols_with_closed_trade"])
            and net["compound_return"] > 0
            and (net["expectancy_per_trade"] or 0.0) > 0
        )
        state = "PASS_GEN2_W2_NET_EDGE_HOLD_DD_SSOT" if gate_pass else "FAIL_GEN2_W2_NET_EDGE"
        receipt = {
            "schema_version": "zel.alpha_gen2.trend_momentum_base.replay.v1",
            "state": state,
            "mode": ns.mode,
            "family": contract["family"],
            "candidate_id": contract["candidate_id"],
            "research_only": True,
            "contract_frozen_before_replay": True,
            "parameter_selection_performed": False,
            "exit_optimization_performed": False,
            "donchian_logic_reused": False,
            "window": window,
            "symbols": contract["symbols"],
            "results": [public_result(r) for r in rows],
            "aggregate_gross": gross,
            "aggregate_net": net,
            "symbols_with_closed_trade": symbols_with_closed_trade,
            "cost_source": {
                "receipt_sha256": cost["receipt_sha256"],
                "source_tier": cost["source_tier"],
                "calibration_mode": cost["calibration_mode"],
                "observed_at": cost.get("observed_at"),
                "worst_available_cost_envelope": c,
                "applied": cost_applied
            },
            "gate_pass": gate_pass,
            "DD_gate_required_next": gate_pass,
            "DD_gate_resolved": False,
            "W3_untouched": True,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold" if gate_pass else "route_change"
        }

    material = dict(receipt)
    receipt["receipt_sha256"] = canonical_sha(material)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(state)
    print(json.dumps({
        "mode": ns.mode,
        "candidate_id": contract["candidate_id"],
        "trades": gross["trade_count"],
        "gross_compound": gross["compound_return"],
        "gross_expectancy": gross["expectancy_per_trade"],
        "net_compound": receipt.get("aggregate_net", {}).get("compound_return"),
        "net_expectancy": receipt.get("aggregate_net", {}).get("expectancy_per_trade"),
        "symbols_with_closed_trade": symbols_with_closed_trade,
        "gate_pass": gate_pass,
        "W3_untouched": True
    }, sort_keys=True))


if __name__ == "__main__":
    main()
