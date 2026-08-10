#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BAR_MS = 15 * 60 * 1000
REQ = ("timestamp_ms", "open", "high", "low", "close", "volume")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
COST_SYMBOL = {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}


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
    gaps = 0
    last: int | None = None
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != REQ:
            raise SystemExit(f"HOLD_BAD_SCHEMA:{path}:{reader.fieldnames}")
        for line, row in enumerate(reader, 2):
            if any(row.get(k, "") == "" for k in REQ):
                raise SystemExit(f"HOLD_MISSING_FIELD:{path}:{line}")
            ts = int(row["timestamp_ms"])
            o, h, l, c, v = (float(row[k]) for k in REQ[1:])
            if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                raise SystemExit(f"HOLD_NONFINITE:{path}:{line}")
            if not (o > 0 and c > 0 and v >= 0 and h >= max(o, c, l) and l <= min(o, c, h)):
                raise SystemExit(f"HOLD_BAD_OHLCV:{path}:{line}")
            if ts in seen:
                raise SystemExit(f"HOLD_DUPLICATE_TIMESTAMP:{path}:{line}")
            if last is not None:
                if ts <= last:
                    raise SystemExit(f"HOLD_NON_MONOTONIC:{path}:{line}")
                if ts - last != BAR_MS:
                    gaps += 1
            seen.add(ts)
            last = ts
            rows.append({"timestamp_ms": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
    if not rows:
        raise SystemExit(f"HOLD_EMPTY:{path}")
    return rows, {
        "rows": len(rows),
        "first_timestamp_ms": int(rows[0]["timestamp_ms"]),
        "last_timestamp_ms": int(rows[-1]["timestamp_ms"]),
        "gap_count": gaps,
        "sha256": sha256_file(path),
        "state": "PASS" if gaps == 0 else "HOLD",
    }


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text())
    if not str(manifest.get("state", "")).startswith("PASS_"):
        raise SystemExit(f"HOLD_MANIFEST_STATE:{manifest.get('state')}")
    if int(manifest.get("forward_overlap_count", -1)) != 0:
        raise SystemExit(f"HOLD_MANIFEST_FORWARD_OVERLAP:{manifest.get('forward_overlap_count')}")
    return manifest


def manifest_row(manifest: dict[str, Any], window: str, symbol: str) -> dict[str, Any]:
    hits = [
        row for row in manifest.get("files", [])
        if row.get("kind") == "market"
        and row.get("interval") == "15m"
        and row.get("window_id") == window
        and row.get("symbol") == symbol
    ]
    if len(hits) != 1:
        raise SystemExit(f"HOLD_MANIFEST_ROW:{window}:{symbol}:{len(hits)}")
    return hits[0]


def historical_path(root: Path, mrow: dict[str, Any]) -> Path:
    candidates = (root / str(mrow["path"]), root / "zel_historical_oos_v1" / str(mrow["path"]))
    for path in candidates:
        if path.is_file():
            return path
    raise SystemExit(f"HOLD_HISTORICAL_FILE_MISSING:{mrow['path']}")


def load_historical_window(root: Path, manifest: dict[str, Any], window: str, symbol: str) -> tuple[list[dict[str, float]], dict[str, Any]]:
    mrow = manifest_row(manifest, window, symbol)
    rows, integ = load_csv(historical_path(root, mrow))
    integ.update({
        "manifest_rows_match": len(rows) == int(mrow["rows"]),
        "manifest_sha_match": integ["sha256"] == str(mrow["sha256"]),
        "manifest_range_match": integ["first_timestamp_ms"] == int(mrow["start_ms"]) and integ["last_timestamp_ms"] == int(mrow["end_ms"]),
        "manifest_source": mrow.get("source"),
    })
    ok = bool(integ["state"] == "PASS" and integ["manifest_rows_match"] and integ["manifest_sha_match"] and integ["manifest_range_match"])
    if not ok:
        raise SystemExit(f"HOLD_HISTORICAL_INTEGRITY:{window}:{symbol}:{json.dumps(integ,sort_keys=True)}")
    return rows, integ


def require_contiguous(a: list[dict[str, float]], b: list[dict[str, float]], label: str) -> None:
    if int(a[-1]["timestamp_ms"]) + BAR_MS != int(b[0]["timestamp_ms"]):
        raise SystemExit(f"HOLD_WINDOW_NOT_CONTIGUOUS:{label}:{int(a[-1]['timestamp_ms'])}:{int(b[0]['timestamp_ms'])}")


def validate_contract(contract: dict[str, Any], history: dict[str, Any]) -> None:
    if contract.get("state") != "FROZEN_BEFORE_FINAL_GENERATION_REPLAY":
        raise SystemExit("HOLD_CONTRACT_STATE")
    if contract.get("family") != "trend_momentum" or int(contract.get("generation", -1)) != 3:
        raise SystemExit("HOLD_CONTRACT_GENERATION")
    if contract.get("candidate_id") != "TM_GEN3_FINAL_RISK_ADJ_24H_MOM_7D_REGIME_LONG_V1":
        raise SystemExit("HOLD_CANDIDATE_ID")
    if contract.get("symbols") != list(SYMBOLS) or contract.get("timeframe") != "15m" or contract.get("side") != "LONG_ONLY":
        raise SystemExit("HOLD_UNIVERSE_DRIFT")
    signal = contract.get("signal", {})
    fixed = (
        int(signal.get("regime_lookback_bars", -1)),
        int(signal.get("momentum_lookback_bars", -1)),
        int(signal.get("volatility_reference_bars", -1)),
        float(signal.get("entry_threshold_sigma", -999)),
    )
    if fixed != (672, 96, 96, 1.0):
        raise SystemExit(f"HOLD_PARAMETER_DRIFT:{fixed}")
    if signal.get("fill") != "next_bar_open" or signal.get("same_bar_fill") is not False:
        raise SystemExit("HOLD_FILL_DRIFT")
    if any(signal.get(k) is not None for k in ("stop_loss", "take_profit", "max_holding_bars", "trailing_overlay", "volume_filter")):
        raise SystemExit("HOLD_OVERLAY_DRIFT")
    if signal.get("parameter_selection_performed") is not False or signal.get("exit_optimization_performed") is not False:
        raise SystemExit("HOLD_OPTIMIZATION_DRIFT")
    if int(contract.get("variants", {}).get("allowed_after_this_contract", -1)) != 0:
        raise SystemExit("HOLD_VARIANT_AUTHORITY_DRIFT")
    w4 = contract.get("W4_final_forward", {})
    if (
        int(w4.get("fresh_fetch_start_ms", -1)) != 1784536200000
        or int(w4.get("window_start_ms", -1)) != 1785141900000
        or int(w4.get("window_end_ms", -1)) != 1786350600000
        or int(w4.get("warmup_bars", -1)) != 673
        or int(w4.get("window_bars", -1)) != 1344
        or int(w4.get("fresh_fetch_total_rows_per_symbol", -1)) != 2017
    ):
        raise SystemExit("HOLD_W4_BOUNDARY_DRIFT")
    if history.get("state") != "TWO_FAILED_GENERATIONS_FINAL_REDEFINITION_ONLY":
        raise SystemExit("HOLD_GENERATION_HISTORY")
    if int(history.get("completed_generations", -1)) != 2 or int(history.get("remaining_generations", -1)) != 1:
        raise SystemExit("HOLD_GENERATION_BUDGET")
    if history.get("global_holdout_status", {}).get("W3_may_be_used_as_final_OOS") is not False:
        raise SystemExit("HOLD_W3_ROLE_DRIFT")
    if contract.get("execution_authority") != "NONE" or contract.get("order_authority") != "BLOCKED":
        raise SystemExit("HOLD_AUTHORITY_DRIFT")


def require_cost(cost: dict[str, Any]) -> None:
    if not str(cost.get("state", "")).startswith("PASS_BINGX_REAL_OBSERVATION_COLLECTED"):
        raise SystemExit(f"HOLD_COST_STATE:{cost.get('state')}")
    if cost.get("source_tier") != "official" or cost.get("calibration_mode") != "real":
        raise SystemExit("HOLD_COST_SOURCE")
    if cost.get("execution_authority") != "NONE" or cost.get("order_authority") != "BLOCKED":
        raise SystemExit("HOLD_COST_AUTHORITY")
    for key in ("taker_fee_pct", "funding_p95_abs_pct_8h_by_symbol", "slippage_floor_bps_by_symbol_and_notional", "receipt_sha256"):
        if cost.get(key) is None:
            raise SystemExit(f"HOLD_COST_FIELD:{key}")


def cost_envelope(cost: dict[str, Any]) -> dict[str, dict[str, float]]:
    fee = float(cost["taker_fee_pct"])
    out: dict[str, dict[str, float]] = {}
    for symbol in SYMBOLS:
        c_symbol = COST_SYMBOL[symbol]
        funding = cost["funding_p95_abs_pct_8h_by_symbol"].get(c_symbol)
        slippage = cost["slippage_floor_bps_by_symbol_and_notional"].get(c_symbol)
        if not isinstance(funding, dict) or not isinstance(slippage, list) or not slippage:
            raise SystemExit(f"HOLD_COST_SYMBOL:{c_symbol}")
        out[symbol] = {
            "taker_fee_pct_one_way": fee,
            "funding_p95_abs_pct_8h": float(funding["funding_p95_abs_pct_8h"]),
            "slippage_bps_one_way": max(float(x["slippage_bps_one_way"]) for x in slippage),
        }
    return out


@dataclass
class Position:
    entry_i: int
    entry_ts: int
    entry_price: float
    entry_z: float
    entry_regime: float


def feature_series(rows: list[dict[str, float]], regime_n: int, mom_n: int, vol_n: int) -> tuple[list[float | None], list[float | None]]:
    closes = [float(x["close"]) for x in rows]
    lr: list[float | None] = [None]
    for i in range(1, len(closes)):
        lr.append(math.log(closes[i] / closes[i - 1]))
    regimes: list[float | None] = [None] * len(rows)
    zscores: list[float | None] = [None] * len(rows)
    for i in range(len(rows)):
        if i < regime_n or i < mom_n or i < vol_n + 1:
            continue
        prior = [x for x in lr[i - vol_n:i] if x is not None]
        if len(prior) != vol_n:
            continue
        sd = statistics.stdev(prior)
        denom = sd * math.sqrt(float(mom_n))
        if not math.isfinite(denom) or denom <= 1e-15:
            continue
        regime = math.log(closes[i] / closes[i - regime_n])
        momentum = math.log(closes[i] / closes[i - mom_n])
        regimes[i] = regime
        zscores[i] = momentum / denom
    return regimes, zscores


def replay_symbol(
    rows: list[dict[str, float]],
    eval_start_ms: int,
    eval_end_ms: int,
    symbol: str,
    signal: dict[str, Any],
) -> dict[str, Any]:
    regime_n = int(signal["regime_lookback_bars"])
    mom_n = int(signal["momentum_lookback_bars"])
    vol_n = int(signal["volatility_reference_bars"])
    threshold = float(signal["entry_threshold_sigma"])
    regimes, zscores = feature_series(rows, regime_n, mom_n, vol_n)
    pos: Position | None = None
    pending_entry: tuple[float, float] | None = None
    pending_exit = False
    entry_signals = 0
    exit_signals = 0
    exposure_bars = 0
    trades: list[dict[str, Any]] = []

    for i, bar in enumerate(rows):
        ts = int(bar["timestamp_ms"])
        in_eval = eval_start_ms <= ts <= eval_end_ms

        if pending_exit and pos is not None:
            if not in_eval:
                raise SystemExit(f"HOLD_EXIT_FILL_OUTSIDE_EVAL:{symbol}:{ts}")
            exit_price = float(bar["open"])
            trades.append({
                "symbol": symbol,
                "entry_ts": pos.entry_ts,
                "exit_ts": ts,
                "entry": pos.entry_price,
                "exit": exit_price,
                "entry_z": pos.entry_z,
                "entry_regime": pos.entry_regime,
                "bars_held": i - pos.entry_i,
                "gross_return": exit_price / pos.entry_price - 1.0,
            })
            pos = None
            pending_exit = False

        if pending_entry is not None and pos is None:
            if not in_eval:
                raise SystemExit(f"HOLD_ENTRY_FILL_OUTSIDE_EVAL:{symbol}:{ts}")
            entry_z, entry_regime = pending_entry
            pos = Position(i, ts, float(bar["open"]), entry_z, entry_regime)
            pending_entry = None

        if in_eval and pos is not None:
            exposure_bars += 1

        if not in_eval or i == 0 or i + 1 >= len(rows):
            continue
        next_ts = int(rows[i + 1]["timestamp_ms"])
        if next_ts > eval_end_ms:
            continue
        z = zscores[i]
        prev_z = zscores[i - 1]
        regime = regimes[i]
        if z is None or prev_z is None or regime is None:
            continue

        if pos is None and pending_entry is None:
            if regime > 0.0 and prev_z <= threshold and z > threshold:
                pending_entry = (float(z), float(regime))
                entry_signals += 1
        elif pos is not None and not pending_exit:
            if z <= 0.0 or regime <= 0.0:
                pending_exit = True
                exit_signals += 1

    eval_bars = sum(1 for row in rows if eval_start_ms <= int(row["timestamp_ms"]) <= eval_end_ms)
    return {
        "symbol": symbol,
        "entry_signal_count": entry_signals,
        "exit_signal_count": exit_signals,
        "closed_trades": len(trades),
        "open_position_at_end": pos is not None or pending_entry is not None,
        "exposure_fraction": exposure_bars / eval_bars if eval_bars else 0.0,
        "trades": trades,
    }


def apply_cost(trades: list[dict[str, Any]], envelope: dict[str, dict[str, float]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    funding_costs: list[float] = []
    for trade in trades:
        symbol = str(trade["symbol"])
        c = envelope[symbol]
        fee_rt_pct = 2.0 * c["taker_fee_pct_one_way"]
        slippage_rt_pct = 2.0 * c["slippage_bps_one_way"] / 100.0
        hours = float(trade["bars_held"]) * 0.25
        funding_pct = c["funding_p95_abs_pct_8h"] * (hours / 8.0)
        total_cost_pct = fee_rt_pct + slippage_rt_pct + funding_pct
        funding_costs.append(funding_pct)
        row = dict(trade)
        row["fee_round_trip_pct"] = fee_rt_pct
        row["slippage_round_trip_pct"] = slippage_rt_pct
        row["funding_cost_pct"] = funding_pct
        row["net_return"] = float(trade["gross_return"]) - total_cost_pct / 100.0
        out.append(row)
    return out, {
        "mean_funding_cost_pct_per_trade": sum(funding_costs) / len(funding_costs) if funding_costs else 0.0,
        "max_funding_cost_pct_per_trade": max(funding_costs) if funding_costs else 0.0,
        "per_symbol_envelope": envelope,
    }


def metrics(values: list[float]) -> dict[str, Any]:
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    gp = sum(wins)
    gl = -sum(losses)
    pf: float | str | None = gp / gl if gl > 0 else ("INF" if gp > 0 else None)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_dd = max(max_dd, 1.0 - equity / peak)
    return {
        "trade_count": len(values),
        "win_rate": len(wins) / len(values) if values else None,
        "compound_return": equity - 1.0 if values else 0.0,
        "expectancy_per_trade": sum(values) / len(values) if values else None,
        "profit_factor": pf,
        "max_drawdown": max_dd,
        "best_trade": max(values) if values else None,
        "worst_trade": min(values) if values else None,
    }


def aggregate(symbol_rows: list[dict[str, Any]], envelope: dict[str, dict[str, float]]) -> dict[str, Any]:
    all_trades = sorted([t for row in symbol_rows for t in row["trades"]], key=lambda x: (int(x["exit_ts"]), str(x["symbol"]), int(x["entry_ts"])))
    net_trades, applied = apply_cost(all_trades, envelope)
    by_symbol: dict[str, Any] = {}
    for symbol in SYMBOLS:
        raw = [t for t in all_trades if t["symbol"] == symbol]
        net = [t for t in net_trades if t["symbol"] == symbol]
        by_symbol[symbol] = {
            "closed_trades": len(raw),
            "gross": metrics([float(t["gross_return"]) for t in raw]),
            "net": metrics([float(t["net_return"]) for t in net]),
        }
    return {
        "gross": metrics([float(t["gross_return"]) for t in all_trades]),
        "net": metrics([float(t["net_return"]) for t in net_trades]),
        "symbols_with_closed_trade": sum(1 for symbol in SYMBOLS if by_symbol[symbol]["closed_trades"] > 0),
        "by_symbol": by_symbol,
        "cost_applied": applied,
    }


def gate_pass(agg: dict[str, Any], gate: dict[str, Any]) -> bool:
    net = agg["net"]
    return bool(
        int(net["trade_count"]) >= int(gate["minimum_closed_trades_total"])
        and int(agg["symbols_with_closed_trade"]) >= int(gate["minimum_symbols_with_closed_trade"])
        and float(net["compound_return"]) > 0.0
        and float(net["expectancy_per_trade"] or 0.0) > 0.0
    )


def window_public(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k != "trades"}


def evaluate_historical(
    root: Path,
    manifest: dict[str, Any],
    window: str,
    warmup_window: str | None,
    contract: dict[str, Any],
    envelope: dict[str, dict[str, float]],
) -> dict[str, Any]:
    symbol_results: list[dict[str, Any]] = []
    integrity: dict[str, Any] = {}
    for symbol in SYMBOLS:
        eval_rows, eval_integ = load_historical_window(root, manifest, window, symbol)
        if warmup_window is None:
            combined = eval_rows
            warmup_integ = None
        else:
            warm_rows, warmup_integ = load_historical_window(root, manifest, warmup_window, symbol)
            require_contiguous(warm_rows, eval_rows, f"{warmup_window}->{window}:{symbol}")
            combined = warm_rows[-673:] + eval_rows
        eval_start = int(eval_rows[0]["timestamp_ms"])
        eval_end = int(eval_rows[-1]["timestamp_ms"])
        rr = replay_symbol(combined, eval_start, eval_end, symbol, contract["signal"])
        symbol_results.append(rr)
        integrity[symbol] = {"evaluation": eval_integ, "warmup": warmup_integ}
    agg = aggregate(symbol_results, envelope)
    return {
        "window": window,
        "warmup_window": warmup_window,
        "integrity": integrity,
        "symbol_results": [window_public(x) for x in symbol_results],
        "aggregate": agg,
    }


def evaluate_w4(
    root: Path,
    source_receipt: dict[str, Any],
    contract: dict[str, Any],
    envelope: dict[str, dict[str, float]],
) -> dict[str, Any]:
    w4 = contract["W4_final_forward"]
    symbol_results: list[dict[str, Any]] = []
    integrity: dict[str, Any] = {}
    timestamps_ref: list[int] | None = None
    for symbol in SYMBOLS:
        path = root / f"{symbol}.csv"
        rows, integ = load_csv(path)
        expected_rows = int(w4["fresh_fetch_total_rows_per_symbol"])
        expected_first = int(w4["fresh_fetch_start_ms"])
        expected_last = int(w4["window_end_ms"])
        if len(rows) != expected_rows or int(rows[0]["timestamp_ms"]) != expected_first or int(rows[-1]["timestamp_ms"]) != expected_last or integ["gap_count"] != 0:
            raise SystemExit(f"HOLD_W4_FETCH_INTEGRITY:{symbol}:{json.dumps(integ,sort_keys=True)}")
        ts = [int(x["timestamp_ms"]) for x in rows]
        if timestamps_ref is None:
            timestamps_ref = ts
        elif ts != timestamps_ref:
            raise SystemExit(f"HOLD_W4_TIMESTAMP_PARITY:{symbol}")
        source_row = source_receipt.get("symbols", {}).get(symbol)
        if not isinstance(source_row, dict):
            raise SystemExit(f"HOLD_W4_SOURCE_RECEIPT:{symbol}")
        if source_row.get("sha256") != integ["sha256"] or int(source_row.get("rows", -1)) != len(rows):
            raise SystemExit(f"HOLD_W4_SOURCE_SHA:{symbol}")
        if source_row.get("endpoint") not in w4["official_kline_preference"]:
            raise SystemExit(f"HOLD_W4_SOURCE_ENDPOINT:{symbol}:{source_row.get('endpoint')}")
        eval_start = int(w4["window_start_ms"])
        eval_end = int(w4["window_end_ms"])
        eval_rows = [x for x in rows if eval_start <= int(x["timestamp_ms"]) <= eval_end]
        if len(eval_rows) != int(w4["exact_rows_per_symbol"]):
            raise SystemExit(f"HOLD_W4_SCORE_ROWS:{symbol}:{len(eval_rows)}")
        rr = replay_symbol(rows, eval_start, eval_end, symbol, contract["signal"])
        symbol_results.append(rr)
        integrity[symbol] = integ
    agg = aggregate(symbol_results, envelope)
    return {
        "window": "W4_FINAL_FORWARD_14D",
        "source_receipt_sha256": source_receipt.get("receipt_sha256"),
        "integrity": integrity,
        "symbol_results": [window_public(x) for x in symbol_results],
        "aggregate": agg,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("development", "w3_validation", "w4_final"), required=True)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--history", type=Path, required=True)
    ap.add_argument("--cost-model", type=Path, required=True)
    ap.add_argument("--historical-root", type=Path)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--development-receipt", type=Path)
    ap.add_argument("--w3-receipt", type=Path)
    ap.add_argument("--w4-root", type=Path)
    ap.add_argument("--w4-source-receipt", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    contract = json.loads(ns.contract.read_text())
    history = json.loads(ns.history.read_text())
    validate_contract(contract, history)
    cost_raw = json.loads(ns.cost_model.read_text())
    require_cost(cost_raw)
    envelope = cost_envelope(cost_raw)

    common: dict[str, Any] = {
        "schema_version": "zel.alpha.trend_momentum.final_gen3.replay.v1",
        "family": contract["family"],
        "generation": contract["generation"],
        "candidate_id": contract["candidate_id"],
        "contract_frozen_before_replay": True,
        "variants_allowed_after_result": 0,
        "parameter_selection_performed": False,
        "exit_optimization_performed": False,
        "cost_source": {
            "receipt_sha256": cost_raw["receipt_sha256"],
            "observed_at": cost_raw.get("observed_at"),
            "source_tier": cost_raw["source_tier"],
            "calibration_mode": cost_raw["calibration_mode"],
            "envelope": envelope,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }

    if ns.mode == "development":
        if ns.historical_root is None or ns.manifest is None:
            raise SystemExit("HOLD_DEVELOPMENT_DATA_ARGS")
        manifest = load_manifest(ns.manifest)
        w1 = evaluate_historical(ns.historical_root, manifest, contract["historical_data"]["W1"], None, contract, envelope)
        w2 = evaluate_historical(ns.historical_root, manifest, contract["historical_data"]["W2"], contract["historical_data"]["W1"], contract, envelope)
        gate = contract["development_gate"]
        w1_pass = gate_pass(w1["aggregate"], gate)
        w2_pass = gate_pass(w2["aggregate"], gate)
        passed = w1_pass and w2_pass
        receipt = {
            **common,
            "mode": "development",
            "state": "PASS_TM_GEN3_DEVELOPMENT_NET_EDGE" if passed else "FAIL_TM_GEN3_DEVELOPMENT_NET_EDGE",
            "W1_role": "DEVELOPMENT",
            "W2_role": "DEVELOPMENT",
            "W1": w1,
            "W2": w2,
            "W1_gate_pass": w1_pass,
            "W2_gate_pass": w2_pass,
            "development_gate_pass": passed,
            "W3_access_authorized": passed,
            "W4_market_outcome_accessed": False,
            "DD_gate_resolved": False,
            "action": "hold" if passed else "route_change",
        }
    elif ns.mode == "w3_validation":
        if ns.development_receipt is None or not ns.development_receipt.is_file():
            raise SystemExit("HOLD_DEVELOPMENT_RECEIPT_REQUIRED")
        dev = json.loads(ns.development_receipt.read_text())
        if dev.get("state") != "PASS_TM_GEN3_DEVELOPMENT_NET_EDGE" or dev.get("W3_access_authorized") is not True:
            raise SystemExit(f"HOLD_W3_NOT_AUTHORIZED:{dev.get('state')}")
        if ns.historical_root is None or ns.manifest is None:
            raise SystemExit("HOLD_W3_DATA_ARGS")
        manifest = load_manifest(ns.manifest)
        w3 = evaluate_historical(ns.historical_root, manifest, contract["historical_data"]["W3"], contract["historical_data"]["W2"], contract, envelope)
        passed = gate_pass(w3["aggregate"], contract["W3_validation_gate"])
        receipt = {
            **common,
            "mode": "w3_validation",
            "state": "PASS_TM_GEN3_W3_REGIME_VALIDATION" if passed else "FAIL_TM_GEN3_W3_REGIME_VALIDATION",
            "W3_role": "REGIME_EXPOSED_VALIDATION_NOT_FINAL_OOS",
            "development_receipt_sha256": dev.get("receipt_sha256"),
            "W3": w3,
            "W3_gate_pass": passed,
            "W4_access_authorized": passed,
            "W4_market_outcome_accessed": False,
            "DD_gate_resolved": False,
            "action": "hold" if passed else "route_change",
        }
    else:
        if ns.w3_receipt is None or not ns.w3_receipt.is_file():
            raise SystemExit("HOLD_W3_RECEIPT_REQUIRED")
        w3r = json.loads(ns.w3_receipt.read_text())
        if w3r.get("state") != "PASS_TM_GEN3_W3_REGIME_VALIDATION" or w3r.get("W4_access_authorized") is not True:
            raise SystemExit(f"HOLD_W4_NOT_AUTHORIZED:{w3r.get('state')}")
        if ns.w4_root is None or ns.w4_source_receipt is None or not ns.w4_source_receipt.is_file():
            raise SystemExit("HOLD_W4_DATA_ARGS")
        source_receipt = json.loads(ns.w4_source_receipt.read_text())
        if source_receipt.get("state") != "PASS_TM_GEN3_W4_FRESH_OFFICIAL_FETCH":
            raise SystemExit(f"HOLD_W4_SOURCE_STATE:{source_receipt.get('state')}")
        w4 = evaluate_w4(ns.w4_root, source_receipt, contract, envelope)
        passed = gate_pass(w4["aggregate"], contract["W4_final_forward_gate"])
        receipt = {
            **common,
            "mode": "w4_final",
            "state": "PASS_TM_GEN3_W4_FINAL_FORWARD_EDGE_HOLD_DD_SSOT" if passed else "FAIL_TM_GEN3_W4_FINAL_FORWARD_EDGE",
            "W4_role": "NEW_FINAL_FORWARD",
            "W3_receipt_sha256": w3r.get("receipt_sha256"),
            "W4": w4,
            "W4_gate_pass": passed,
            "W4_market_outcome_accessed": True,
            "DD_gate_required_next": passed,
            "DD_gate_resolved": False,
            "survivor_declared": False,
            "action": "hold" if passed else "route_change",
        }

    material = dict(receipt)
    receipt["receipt_sha256"] = canonical_sha(material)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt["state"])
    if ns.mode == "development":
        for key in ("W1", "W2"):
            a = receipt[key]["aggregate"]
            print(json.dumps({
                "window": key,
                "trades": a["net"]["trade_count"],
                "symbols": a["symbols_with_closed_trade"],
                "gross_compound": a["gross"]["compound_return"],
                "net_compound": a["net"]["compound_return"],
                "net_expectancy": a["net"]["expectancy_per_trade"],
                "net_pf": a["net"]["profit_factor"],
                "net_wr": a["net"]["win_rate"],
                "net_dd": a["net"]["max_drawdown"],
                "gate_pass": receipt[f"{key}_gate_pass"],
            }, sort_keys=True))
    elif ns.mode == "w3_validation":
        a = receipt["W3"]["aggregate"]
        print(json.dumps({
            "window": "W3",
            "trades": a["net"]["trade_count"],
            "symbols": a["symbols_with_closed_trade"],
            "gross_compound": a["gross"]["compound_return"],
            "net_compound": a["net"]["compound_return"],
            "net_expectancy": a["net"]["expectancy_per_trade"],
            "net_pf": a["net"]["profit_factor"],
            "net_wr": a["net"]["win_rate"],
            "net_dd": a["net"]["max_drawdown"],
            "gate_pass": receipt["W3_gate_pass"],
            "W4_access_authorized": receipt["W4_access_authorized"],
        }, sort_keys=True))
    else:
        a = receipt["W4"]["aggregate"]
        print(json.dumps({
            "window": "W4_FINAL_FORWARD_14D",
            "trades": a["net"]["trade_count"],
            "symbols": a["symbols_with_closed_trade"],
            "gross_compound": a["gross"]["compound_return"],
            "net_compound": a["net"]["compound_return"],
            "net_expectancy": a["net"]["expectancy_per_trade"],
            "net_pf": a["net"]["profit_factor"],
            "net_wr": a["net"]["win_rate"],
            "net_dd": a["net"]["max_drawdown"],
            "gate_pass": receipt["W4_gate_pass"],
            "survivor_declared": False,
        }, sort_keys=True))


if __name__ == "__main__":
    main()
