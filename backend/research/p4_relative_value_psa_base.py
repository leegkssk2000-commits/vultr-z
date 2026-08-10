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
PAIR = ("BTCUSDT", "ETHUSDT")
COST_SYMBOL = {"BTCUSDT": "BTC-USDT", "ETHUSDT": "ETH-USDT"}


def canonical_sha(v: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> tuple[list[dict[str, float]], dict[str, Any]]:
    rows: list[dict[str, float]] = []
    last: int | None = None
    gaps = 0
    with path.open(newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        if tuple(r.fieldnames or ()) != REQ:
            raise SystemExit(f"HOLD_BAD_SCHEMA:{path}:{r.fieldnames}")
        for line, x in enumerate(r, 2):
            if any(x.get(k, "") == "" for k in REQ):
                raise SystemExit(f"HOLD_MISSING_FIELD:{path}:{line}")
            ts = int(x["timestamp_ms"])
            o, h, l, c, v = (float(x[k]) for k in REQ[1:])
            if not all(math.isfinite(z) for z in (o, h, l, c, v)):
                raise SystemExit(f"HOLD_NONFINITE:{path}:{line}")
            if not (h >= max(o, c, l) and l <= min(o, c, h) and o > 0 and c > 0 and v >= 0):
                raise SystemExit(f"HOLD_BAD_OHLCV:{path}:{line}")
            if last is not None:
                if ts <= last:
                    raise SystemExit(f"HOLD_NON_MONOTONIC:{path}:{line}")
                if ts - last != BAR_MS:
                    gaps += 1
            last = ts
            rows.append({"timestamp_ms": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
    if not rows:
        raise SystemExit(f"HOLD_EMPTY:{path}")
    return rows, {
        "rows": len(rows),
        "first_timestamp_ms": int(rows[0]["timestamp_ms"]),
        "last_timestamp_ms": int(rows[-1]["timestamp_ms"]),
        "gap_count": gaps,
        "sha256": file_sha(path),
        "state": "PASS" if gaps == 0 else "HOLD",
    }


def manifest_row(manifest: dict[str, Any], window: str, symbol: str) -> dict[str, Any]:
    hits = [x for x in manifest.get("files", []) if x.get("kind") == "market" and x.get("interval") == "15m" and x.get("window_id") == window and x.get("symbol") == symbol]
    if len(hits) != 1:
        raise SystemExit(f"HOLD_MANIFEST_ROW:{window}:{symbol}:{len(hits)}")
    return hits[0]


def locate(root: Path, m: dict[str, Any]) -> Path:
    for p in (root / str(m["path"]), root / "zel_historical_oos_v1" / str(m["path"])):
        if p.is_file():
            return p
    raise SystemExit(f"HOLD_DATA_MISSING:{m['path']}")


def load_manifest(path: Path) -> dict[str, Any]:
    m = json.loads(path.read_text())
    if not str(m.get("state", "")).startswith("PASS_") or int(m.get("forward_overlap_count", -1)) != 0:
        raise SystemExit("HOLD_MANIFEST_STATE")
    return m


def load_pair(root: Path, manifest: dict[str, Any], window: str) -> tuple[list[dict[str, float]], list[dict[str, float]], dict[str, Any]]:
    loaded: dict[str, tuple[list[dict[str, float]], dict[str, Any]]] = {}
    for symbol in PAIR:
        m = manifest_row(manifest, window, symbol)
        rows, integ = load_csv(locate(root, m))
        integ.update({
            "manifest_rows_match": len(rows) == int(m["rows"]),
            "manifest_sha_match": integ["sha256"] == m["sha256"],
            "manifest_range_match": integ["first_timestamp_ms"] == int(m["start_ms"]) and integ["last_timestamp_ms"] == int(m["end_ms"]),
        })
        if not (integ["state"] == "PASS" and integ["manifest_rows_match"] and integ["manifest_sha_match"] and integ["manifest_range_match"]):
            raise SystemExit(f"HOLD_PAIR_LEG_INTEGRITY:{window}:{symbol}:{json.dumps(integ,sort_keys=True)}")
        loaded[symbol] = (rows, integ)
    btc, bi = loaded["BTCUSDT"]
    eth, ei = loaded["ETHUSDT"]
    bts = [int(x["timestamp_ms"]) for x in btc]
    ets = [int(x["timestamp_ms"]) for x in eth]
    if len(btc) != len(eth) or bts != ets:
        mismatch = next((i for i, (a, b) in enumerate(zip(bts, ets)) if a != b), None)
        raise SystemExit(f"HOLD_PAIR_TIMESTAMP_PARITY:{window}:rows={len(btc)}/{len(eth)}:first_mismatch={mismatch}")
    return btc, eth, {
        "window": window,
        "row_parity": True,
        "timestamp_parity": True,
        "rows": len(btc),
        "first_timestamp_ms": bts[0],
        "last_timestamp_ms": bts[-1],
        "legs": {"BTCUSDT": bi, "ETHUSDT": ei},
    }


@dataclass
class PairPos:
    direction: int  # +1 long BTC/short ETH, -1 short BTC/long ETH
    entry_i: int
    entry_ts: int
    btc_entry: float
    eth_entry: float
    entry_z: float


def metrics(rets: list[float]) -> dict[str, Any]:
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gp, gl = sum(wins), -sum(losses)
    pf: float | str | None = gp / gl if gl > 0 else ("INF" if gp > 0 else None)
    eq = peak = 1.0
    dd = 0.0
    for r in rets:
        eq *= 1.0 + r
        peak = max(peak, eq)
        dd = max(dd, 1.0 - eq / peak)
    return {
        "trade_count": len(rets),
        "win_rate": len(wins) / len(rets) if rets else None,
        "compound_return": eq - 1.0 if rets else 0.0,
        "expectancy_per_trade": sum(rets) / len(rets) if rets else None,
        "profit_factor": pf,
        "max_drawdown": dd,
        "best_trade": max(rets) if rets else None,
        "worst_trade": min(rets) if rets else None,
    }


def replay(btc: list[dict[str, float]], eth: list[dict[str, float]], window: int, entry_abs_z: float) -> dict[str, Any]:
    spread = [math.log(float(b["close"])) - math.log(float(e["close"])) for b, e in zip(btc, eth)]
    pos: PairPos | None = None
    pending_entry: tuple[int, float] | None = None
    pending_exit = False
    trades: list[dict[str, Any]] = []
    entry_signals = 0
    exit_signals = 0
    exposure_bars = 0
    sum_x = sum(spread[:window])
    sum_x2 = sum(x * x for x in spread[:window])

    for i in range(window, len(spread)):
        if pending_exit and pos is not None:
            btc_exit = float(btc[i]["open"])
            eth_exit = float(eth[i]["open"])
            btc_leg = pos.direction * (btc_exit / pos.btc_entry - 1.0)
            eth_leg = -pos.direction * (eth_exit / pos.eth_entry - 1.0)
            pair_ret = 0.5 * (btc_leg + eth_leg)
            trades.append({
                "direction": "LONG_BTC_SHORT_ETH" if pos.direction == 1 else "SHORT_BTC_LONG_ETH",
                "entry_ts": pos.entry_ts,
                "exit_ts": int(btc[i]["timestamp_ms"]),
                "entry_z": pos.entry_z,
                "btc_entry": pos.btc_entry,
                "eth_entry": pos.eth_entry,
                "btc_exit": btc_exit,
                "eth_exit": eth_exit,
                "bars_held": i - pos.entry_i,
                "gross_return": pair_ret,
            })
            pos = None
            pending_exit = False
        if pending_entry is not None and pos is None:
            direction, z = pending_entry
            pos = PairPos(direction, i, int(btc[i]["timestamp_ms"]), float(btc[i]["open"]), float(eth[i]["open"]), z)
            pending_entry = None
        if pos is not None:
            exposure_bars += 1

        n = float(window)
        mean = sum_x / n
        var = max(sum_x2 / n - mean * mean, 0.0)
        std = math.sqrt(var)
        z = (spread[i] - mean) / std if std > 1e-12 else 0.0

        if i + 1 < len(spread):
            if pos is None and pending_entry is None:
                if z >= entry_abs_z:
                    pending_entry = (-1, z)
                    entry_signals += 1
                elif z <= -entry_abs_z:
                    pending_entry = (1, z)
                    entry_signals += 1
            elif pos is not None and not pending_exit:
                if (pos.direction == 1 and z >= 0.0) or (pos.direction == -1 and z <= 0.0):
                    pending_exit = True
                    exit_signals += 1

        old = spread[i - window]
        new = spread[i]
        sum_x += new - old
        sum_x2 += new * new - old * old

    direction_counts = {
        "LONG_BTC_SHORT_ETH": sum(1 for t in trades if t["direction"] == "LONG_BTC_SHORT_ETH"),
        "SHORT_BTC_LONG_ETH": sum(1 for t in trades if t["direction"] == "SHORT_BTC_LONG_ETH"),
    }
    return {
        "entry_signal_count": entry_signals,
        "exit_signal_count": exit_signals,
        "closed_pair_trades": len(trades),
        "direction_counts": direction_counts,
        "open_position_at_end": pos is not None or pending_entry is not None,
        "exposure_fraction": exposure_bars / len(spread),
        "trades": trades,
    }


def validate_contract(c: dict[str, Any]) -> None:
    if c.get("state") != "FROZEN_BEFORE_REPLAY" or c.get("family") != "relative_value_psa":
        raise SystemExit("HOLD_CONTRACT_STATE")
    if c.get("candidate_id") != "RV_PSA_BASE_BTC_ETH_LOGRATIO_7D_Z2_V1" or c.get("pair") != list(PAIR):
        raise SystemExit("HOLD_CONTRACT_PAIR")
    a, s = c.get("adapter", {}), c.get("signal", {})
    if int(a.get("rolling_window_bars", -1)) != 672 or float(s.get("entry_abs_z", -1)) != 2.0:
        raise SystemExit("HOLD_CONTRACT_PARAMETER_DRIFT")
    if a.get("fill") != "both_legs_next_bar_open" or a.get("same_bar_fill") is not False:
        raise SystemExit("HOLD_FILL_DRIFT")
    if any(s.get(k) is not None for k in ("stop_loss", "take_profit", "max_holding_bars", "trailing_overlay")):
        raise SystemExit("HOLD_EXIT_OVERLAY")
    if s.get("parameter_selection_performed") is not False or s.get("exit_optimization_performed") is not False:
        raise SystemExit("HOLD_OPTIMIZATION_DRIFT")
    if c.get("execution_authority") != "NONE" or c.get("order_authority") != "BLOCKED":
        raise SystemExit("HOLD_AUTHORITY")


def require_cost(r: dict[str, Any]) -> None:
    if not str(r.get("state", "")).startswith("PASS_BINGX_REAL_OBSERVATION_COLLECTED"):
        raise SystemExit(f"HOLD_COST_STATE:{r.get('state')}")
    if r.get("source_tier") != "official" or r.get("calibration_mode") != "real":
        raise SystemExit("HOLD_COST_SOURCE")
    if r.get("execution_authority") != "NONE" or r.get("order_authority") != "BLOCKED":
        raise SystemExit("HOLD_COST_AUTHORITY")
    for key in ("taker_fee_pct", "funding_p95_abs_pct_8h_by_symbol", "slippage_floor_bps_by_symbol_and_notional", "receipt_sha256"):
        if r.get(key) is None:
            raise SystemExit(f"HOLD_COST_FIELD:{key}")


def cost_envelope(r: dict[str, Any]) -> dict[str, float]:
    out = {"taker_fee_pct": float(r["taker_fee_pct"])}
    for symbol in PAIR:
        cs = COST_SYMBOL[symbol]
        frow = r["funding_p95_abs_pct_8h_by_symbol"].get(cs)
        srows = r["slippage_floor_bps_by_symbol_and_notional"].get(cs)
        if not isinstance(frow, dict) or not isinstance(srows, list) or not srows:
            raise SystemExit(f"HOLD_SYMBOL_COST:{cs}")
        out[f"{symbol}_funding_p95_abs_pct_8h"] = float(frow["funding_p95_abs_pct_8h"])
        out[f"{symbol}_slippage_bps_one_way"] = max(float(x["slippage_bps_one_way"]) for x in srows)
    return out


def apply_cost(trades: list[dict[str, Any]], c: dict[str, float]) -> tuple[list[float], dict[str, Any]]:
    fee_pair_pct = 2.0 * c["taker_fee_pct"]
    slip_pair_pct = (c["BTCUSDT_slippage_bps_one_way"] + c["ETHUSDT_slippage_bps_one_way"]) / 100.0
    net: list[float] = []
    funding_costs: list[float] = []
    for t in trades:
        hours = float(t["bars_held"]) * 0.25
        funding_pair_pct = 0.5 * (
            c["BTCUSDT_funding_p95_abs_pct_8h"] + c["ETHUSDT_funding_p95_abs_pct_8h"]
        ) * (hours / 8.0)
        funding_costs.append(funding_pair_pct)
        total_pct = fee_pair_pct + slip_pair_pct + funding_pair_pct
        net.append(float(t["gross_return"]) - total_pct / 100.0)
    return net, {
        "fee_pair_round_trip_pct": fee_pair_pct,
        "slippage_pair_round_trip_pct_equal_weighted": slip_pair_pct,
        "mean_funding_pair_cost_pct": sum(funding_costs) / len(funding_costs) if funding_costs else 0.0,
        "max_funding_pair_cost_pct": max(funding_costs) if funding_costs else 0.0,
        "envelope": c,
    }


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
    window = contract["data"]["development_window"] if ns.mode == "w1_gross" else contract["data"]["oos_window"]

    if ns.mode == "w1_gross":
        if ns.cost_model is not None:
            raise SystemExit("HOLD_W1_COST_FORBIDDEN")
    else:
        if ns.w1_receipt is None or not ns.w1_receipt.is_file():
            raise SystemExit("HOLD_W1_RECEIPT_REQUIRED")
        w1 = json.loads(ns.w1_receipt.read_text())
        if w1.get("state") != "PASS_P4_W1_GROSS_PAIR_EDGE":
            raise SystemExit(f"HOLD_W1_NOT_PASS:{w1.get('state')}")
        if ns.cost_model is None or not ns.cost_model.is_file():
            raise SystemExit("HOLD_COST_REQUIRED")

    btc, eth, parity = load_pair(ns.data_root, manifest, window)
    rr = replay(btc, eth, int(contract["adapter"]["rolling_window_bars"]), float(contract["signal"]["entry_abs_z"]))
    gross = metrics([float(t["gross_return"]) for t in rr["trades"]])

    receipt: dict[str, Any] = {
        "schema_version": "zel.p4.relative_value_psa_base.replay.v1",
        "mode": ns.mode,
        "family": contract["family"],
        "candidate_id": contract["candidate_id"],
        "window": window,
        "pair_source_parity": parity,
        "closed_pair_trades": rr["closed_pair_trades"],
        "direction_counts": rr["direction_counts"],
        "entry_signal_count": rr["entry_signal_count"],
        "exit_signal_count": rr["exit_signal_count"],
        "open_position_at_end": rr["open_position_at_end"],
        "exposure_fraction": rr["exposure_fraction"],
        "aggregate_gross": gross,
        "contract_frozen_before_replay": True,
        "parameter_selection_performed": False,
        "exit_optimization_performed": False,
        "W3_untouched": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }

    if ns.mode == "w1_gross":
        g = contract["w1_gross_gate"]
        passed = bool(gross["trade_count"] >= int(g["minimum_closed_pair_trades"]) and gross["compound_return"] > 0 and (gross["expectancy_per_trade"] or 0.0) > 0)
        receipt.update({
            "state": "PASS_P4_W1_GROSS_PAIR_EDGE" if passed else "FAIL_P4_W1_GROSS_PAIR_EDGE",
            "gate_pass": passed,
            "cost_model_accessed": False,
            "W2_access_authorized": passed,
            "DD_gate_resolved": False,
            "action": "hold" if passed else "route_change",
        })
    else:
        cost_raw = json.loads(ns.cost_model.read_text())
        require_cost(cost_raw)
        env = cost_envelope(cost_raw)
        net_rets, applied = apply_cost(rr["trades"], env)
        net = metrics(net_rets)
        g = contract["w2_cost_gate"]
        passed = bool(net["trade_count"] >= int(g["minimum_closed_pair_trades"]) and net["compound_return"] > 0 and (net["expectancy_per_trade"] or 0.0) > 0)
        receipt.update({
            "state": "PASS_P4_W2_NET_PAIR_EDGE_HOLD_DD_SSOT" if passed else "FAIL_P4_W2_NET_PAIR_EDGE",
            "aggregate_net": net,
            "gate_pass": passed,
            "cost_source": {
                "receipt_sha256": cost_raw["receipt_sha256"],
                "observed_at": cost_raw.get("observed_at"),
                "source_tier": cost_raw["source_tier"],
                "calibration_mode": cost_raw["calibration_mode"],
                "applied": applied,
            },
            "DD_gate_required_next": passed,
            "DD_gate_resolved": False,
            "action": "hold" if passed else "route_change",
        })

    receipt["receipt_sha256"] = canonical_sha(receipt)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt["state"])
    print(json.dumps({
        "mode": ns.mode,
        "trades": gross["trade_count"],
        "directions": rr["direction_counts"],
        "gross_compound": gross["compound_return"],
        "gross_expectancy": gross["expectancy_per_trade"],
        "gross_pf": gross["profit_factor"],
        "gross_wr": gross["win_rate"],
        "gross_dd": gross["max_drawdown"],
        "net_compound": receipt.get("aggregate_net", {}).get("compound_return"),
        "net_expectancy": receipt.get("aggregate_net", {}).get("expectancy_per_trade"),
        "gate_pass": receipt["gate_pass"],
        "W3_untouched": True,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
