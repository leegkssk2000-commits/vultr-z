#!/usr/bin/env python3
"""Cost adapter for the isolated EAF Stage3 BASE replay.

This module does not change BASE signals or execution timing. It reuses the
Stage3 structural signal functions, reconstructs the same trade ledger, then
applies a sourced read-only BingX cost observation across every observed
notional bucket. No bucket is selected and no survivor/promotion authority is
granted here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

import eaf_stage3_micro_replay as base


def trade_ledger(rows: list[dict], strategy: str) -> list[dict]:
    hb, hidx = base.hour_bars(rows)
    ctx = {"hour_bars": hb, "hour_idx": hidx}
    fn: Callable = {
        "EAF_TM_V1": base.tm_signal,
        "EAF_VB_V1": base.vb_signal,
        "EAF_RMR_V1": base.rmr_signal,
    }[strategy]
    pos: base.Position | None = None
    pending_entry: dict | None = None
    pending_exit = False
    trades: list[dict] = []

    for i, bar in enumerate(rows):
        if pending_exit and pos is not None:
            ret = bar["open"] / pos.entry_price - 1.0
            trades.append({
                "entry_ts": pos.entry_ts,
                "exit_ts": bar["timestamp_ms"],
                "entry": pos.entry_price,
                "exit": bar["open"],
                "gross_return": ret,
                "bars_held": i - pos.entry_i,
            })
            pos = None
            pending_exit = False
        if pending_entry is not None and pos is None:
            pos = base.Position(i, bar["timestamp_ms"], bar["open"], pending_entry)
            pending_entry = None

        enter, exit_, meta = fn(rows, i, ctx)
        if strategy == "EAF_RMR_V1" and pos is not None:
            exit_ = bar["close"] >= pos.meta["range_reference"] or bar["close"] < pos.meta["lower_boundary"]
        if pos is not None and exit_ and i + 1 < len(rows):
            pending_exit = True
        elif pos is None and enter and i + 1 < len(rows):
            pending_entry = meta
    return trades


def metrics(rets: list[float]) -> dict:
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gp = sum(wins)
    gl = -sum(losses)
    pf = (gp / gl) if gl > 0 else (None if not gp else "INF")
    equity = 1.0
    peak = 1.0
    dd = 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        dd = max(dd, 1.0 - equity / peak)
    return {
        "trade_count": len(rets),
        "win_rate": (len(wins) / len(rets)) if rets else None,
        "compound_return": equity - 1.0 if rets else 0.0,
        "expectancy_per_trade": (sum(rets) / len(rets)) if rets else None,
        "profit_factor": pf,
        "max_drawdown": dd,
    }


def require_cost_model(d: dict) -> None:
    assert d.get("state", "").startswith("PASS_BINGX_REAL_OBSERVATION_COLLECTED"), d.get("state")
    assert d.get("calibration_mode") == "real"
    assert d.get("source_tier") == "official"
    assert d.get("execution_authority") == "NONE" and d.get("order_authority") == "BLOCKED"
    assert d.get("protected_mutations") == 0
    for k in ("maker_fee_pct", "taker_fee_pct", "funding_p95_abs_pct_8h", "slippage_floor_bps_by_notional", "receipt_sha256"):
        if d.get(k) is None:
            raise SystemExit(f"HOLD_MISSING_COST_FIELD:{k}")
    if not d["slippage_floor_bps_by_notional"]:
        raise SystemExit("HOLD_EMPTY_SLIPPAGE_BUCKETS")


def covered_symbols(cost: dict) -> set[str]:
    out = set()
    for e in cost.get("endpoints", []):
        if isinstance(e, dict) and e.get("path") == "depth" and e.get("symbol"):
            out.add(str(e["symbol"]).replace("-", ""))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--cost-model", required=True, type=Path)
    ap.add_argument("--minimum-effective-sample", type=int, default=0)
    ap.add_argument("--out", required=True, type=Path)
    ns = ap.parse_args()

    manifest = json.loads(ns.manifest.read_text())
    cost = json.loads(ns.cost_model.read_text())
    require_cost_model(cost)
    expected = {x["symbol"]: x for x in manifest["symbols"]}
    cost_covered = covered_symbols(cost)
    if not cost_covered:
        raise SystemExit("HOLD_NO_SYMBOL_COST_COVERAGE")
    results = []
    integrity = {}
    uncovered = []

    for symbol in sorted(expected):
        path = ns.data_dir / f"{symbol}.csv"
        rows, integ = base.load_csv(path)
        exp = expected[symbol]
        integ["manifest_rows_match"] = len(rows) == exp["rows"]
        integ["manifest_sha_match"] = integ["sha256"] == exp["market_sha256"]
        integ["manifest_range_match"] = rows[0]["timestamp_ms"] == exp["first_timestamp_ms"] and rows[-1]["timestamp_ms"] == exp["last_timestamp_ms"]
        if not (integ["state"] == "PASS" and integ["manifest_rows_match"] and integ["manifest_sha_match"] and integ["manifest_range_match"]):
            raise SystemExit(f"DATA_INTEGRITY_HOLD:{symbol}:{json.dumps(integ, sort_keys=True)}")
        integrity[symbol] = integ
        if symbol not in cost_covered:
            uncovered.append(symbol)
            continue

        for strategy in base.STRATEGIES:
            gross = base.replay(rows, strategy)
            ledger = trade_ledger(rows, strategy)
            gross_from_ledger = metrics([t["gross_return"] for t in ledger])
            if gross_from_ledger["trade_count"] != gross["closed_trades"]:
                raise SystemExit(f"BASE_PARITY_TRADE_COUNT:{symbol}:{strategy}")
            if abs(gross_from_ledger["compound_return"] - gross["gross_compound_return"]) > 1e-12:
                raise SystemExit(f"BASE_PARITY_RETURN:{symbol}:{strategy}")

            for floor in cost["slippage_floor_bps_by_notional"]:
                notional = float(floor["max_notional_usdt"])
                slip_bps = float(floor["slippage_bps_one_way"])
                taker_pct = float(cost["taker_fee_pct"])
                funding_pct_8h = float(cost["funding_p95_abs_pct_8h"])
                fee_rt_pct = 2.0 * taker_pct
                slip_rt_pct = 2.0 * slip_bps / 100.0
                net_rets = []
                funding_costs = []
                for t in ledger:
                    hours = float(t["bars_held"]) * 0.25
                    funding_pct = funding_pct_8h * (hours / 8.0)
                    funding_costs.append(funding_pct)
                    total_cost_decimal = (fee_rt_pct + slip_rt_pct + funding_pct) / 100.0
                    net_rets.append(float(t["gross_return"]) - total_cost_decimal)
                nm = metrics(net_rets)
                enough_sample = ns.minimum_effective_sample > 0 and len(ledger) >= ns.minimum_effective_sample
                results.append({
                    "symbol": symbol,
                    "strategy": strategy,
                    "notional_bucket_usdt": notional,
                    "gross": {
                        "trade_count": gross["closed_trades"],
                        "win_rate": gross["gross_win_rate"],
                        "compound_return": gross["gross_compound_return"],
                        "expectancy_per_trade": gross["gross_expectancy_per_trade"],
                        "profit_factor": gross["gross_profit_factor"],
                        "max_drawdown": gross["realized_max_drawdown"],
                    },
                    "cost": {
                        "fee_round_trip_pct": fee_rt_pct,
                        "slippage_bps_one_way_p95": slip_bps,
                        "slippage_round_trip_pct": slip_rt_pct,
                        "funding_p95_abs_pct_8h": funding_pct_8h,
                        "funding_application": "conservative_abs_p95_prorated_by_15m_bars_held",
                        "mean_funding_cost_pct_per_trade": (sum(funding_costs) / len(funding_costs)) if funding_costs else None,
                    },
                    "net": nm,
                    "economic_metrics_valid": True,
                    "minimum_effective_sample": ns.minimum_effective_sample or None,
                    "minimum_sample_gate_pass": enough_sample if ns.minimum_effective_sample > 0 else None,
                    "survivor_eligible": False,
                    "survivor_reason": "SELECTION_AUTHORITY_BLOCKED" if enough_sample else ("MISSING_MIN_EFFECTIVE_SAMPLE_SSOT" if ns.minimum_effective_sample <= 0 else "INSUFFICIENT_SAMPLE"),
                })

    receipt = {
        "schema_version": "zel.eaf.stage3.costed_replay.v1",
        "state": "PASS_STAGE3_NET_METRICS_HOLD_SURVIVOR_SELECTION",
        "research_only": True,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "selection_authority": False,
        "promotion_authority": False,
        "stage3_unlocked": False,
        "baseline_engine_mutated": False,
        "base_semantics_mutated": False,
        "bucket_selection_performed": False,
        "cost_symbol_coverage": sorted(cost_covered),
        "uncovered_symbols": sorted(uncovered),
        "cost_source": {
            "source_tier": cost["source_tier"],
            "source_identifier": cost["source_identifier"],
            "observed_at": cost["observed_at"],
            "receipt_sha256": cost["receipt_sha256"],
            "maker_fee_pct": cost["maker_fee_pct"],
            "taker_fee_pct": cost["taker_fee_pct"],
            "funding_p95_abs_pct_8h": cost["funding_p95_abs_pct_8h"],
            "slippage_floor_bps_by_notional": cost["slippage_floor_bps_by_notional"],
        },
        "minimum_effective_sample": ns.minimum_effective_sample or None,
        "integrity": integrity,
        "results": results,
        "survivor_selection_performed": False,
        "next": "resolve minimum effective sample from SSOT and acquire direct cost coverage for uncovered symbols; then apply the frozen gate without choosing a notional bucket or changing BASE rules",
    }
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": receipt["state"], "rows": len(results), "cost_receipt": receipt["cost_source"]["receipt_sha256"], "minimum_effective_sample": receipt["minimum_effective_sample"], "uncovered_symbols": receipt["uncovered_symbols"]}, sort_keys=True))


if __name__ == "__main__":
    main()
