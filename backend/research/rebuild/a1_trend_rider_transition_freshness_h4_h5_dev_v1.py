#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact
from backend.research.rebuild import a1_trend_rider_h4_h5_hardening_v1 as mh
from backend.research.rebuild import a1_trend_rider_transition_freshness_frozen_w123_ab_v1 as ab
from backend.research.rebuild import a1_trend_rider_fresh_w123_audit_v1 as w123
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig
from backend.research.rebuild.policy_kernel_v1 import atr, ema

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
SCHEMA = "zel.a1_trend_rider_transition_freshness_h4_h5_dev.v1"
MIN_MATURE_TRADES = 25
EXPECTED_DEV_TRADES = 14


def _candidate_receipt(work: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    original_fetch = exact.v1.fetch_execution_snapshot

    def cached_fetch(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
        if symbol not in cache:
            cache[symbol] = copy.deepcopy(original_fetch(symbol, authority))
        return copy.deepcopy(cache[symbol])

    old_fetch = exact.v1.fetch_execution_snapshot
    try:
        exact.v1.fetch_execution_snapshot = cached_fetch
        parent_current = ab._run_exact(work / "parent_current.json", child=False)
        child_current = ab._run_exact(work / "child_current.json", child=True)
    finally:
        exact.v1.fetch_execution_snapshot = old_fetch

    parent_frozen = ab.template._freeze_parent(parent_current)
    child_frozen = ab.template._freeze_child(parent_frozen, child_current)
    parent_audit = w123.run(parent_frozen)
    child_audit = w123.run(child_frozen)
    if not ab.template._matches_expected(parent_audit["aggregate"]):
        raise RuntimeError("FROZEN_PARENT_AUTHORITY_MISMATCH")
    if int(child_audit["aggregate"]["trades"]) != EXPECTED_DEV_TRADES:
        raise RuntimeError(f"TRANSITION_CHILD_TRADE_COUNT_DRIFT:{child_audit['aggregate']['trades']}!={EXPECTED_DEV_TRADES}")
    if not child_audit.get("economics_gate_pass"):
        raise RuntimeError("TRANSITION_CHILD_ECONOMICS_NOT_PASS")
    return child_frozen, child_audit


def evaluate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trend_rider_transition_hardening_") as td:
        work = Path(td)
        r, child_audit = _candidate_receipt(work)

        trades = list(r.get("trades") or [])
        if len(trades) != EXPECTED_DEV_TRADES:
            raise RuntimeError("DEVELOPMENT_TRADE_BUDGET_DRIFT")
        cfg = TrendPolicyConfig()
        boundary_ms = int(datetime.fromisoformat(str(r["boundary_utc"]).replace("Z", "+00:00")).timestamp() * 1000)
        symbols = sorted({str(x["symbol"]) for x in trades})
        bars_by: dict[str, list[dict[str, Any]]] = {}
        maps: dict[str, dict[int, int]] = {}
        for sym in symbols:
            bs = mh.ev.fetch_bars(sym, "1h", 1000)
            bars_by[sym] = bs
            maps[sym] = mh.idx_by_ts(bs)

        latest = max(int(x["exit_ts"]) for x in trades)
        material = {
            s: [b for b in bars_by[s] if boundary_ms <= int(b["ts_ms"]) <= latest + cfg.timeframe_ms]
            for s in symbols
        }
        source_sha = mh.stable(r["source"])
        data_sha = mh.stable(material)
        window_sha = mh.stable({
            "boundary": r["boundary_utc"], "latest_exit": latest, "symbols": symbols,
            "trade_count": len(trades), "axis": ab.AXIS,
        })
        cost_sha = str(r["cost_authority_sha256"])
        cand = [float(x["net_bps"]) / 100.0 for x in trades]
        candidate = mh.replay_receipt(
            "candidate", cand, source_sha=source_sha, data_sha=data_sha,
            config_sha=str(r["config_sha"]), window_sha=window_sha, cost_sha=cost_sha,
        )

        controls: dict[str, list[float]] = {}
        controls["direction_inversion"] = [
            (-float(x["gross_bps"]) - float(x["realized_cost_bps"])) / 100.0 for x in trades
        ]
        sides = [str(x["side"]) for x in trades]
        rng = random.Random(int(window_sha[:16], 16))
        shuffled = sides[:]
        rng.shuffle(shuffled)
        controls["timestamp_shuffle"] = [
            mh.net_for(shuffled[i], float(x["entry"]), float(x["exit"]), float(x["realized_cost_bps"])) / 100.0
            for i, x in enumerate(trades)
        ]
        controls["one_bar_delay"] = [
            mh.one_bar_delay_net_R(x, bars_by[str(x["symbol"])], maps[str(x["symbol"])], cfg)
            for x in trades
        ]

        random_vals: list[float] = []
        used: set[tuple[str, int]] = set()
        for x in trades:
            sym = str(x["symbol"])
            bs = bars_by[sym]
            mp = maps[sym]
            dur = mh.duration_bars(x, mp)
            pool = [
                j for j, b in enumerate(bs)
                if boundary_ms <= int(b["ts_ms"]) <= latest
                and j + 1 + dur < len(bs)
                and (sym, int(b["ts_ms"])) not in used
            ]
            if not pool:
                raise RuntimeError("RANDOM_ENTRY_POOL_EXHAUSTED")
            j = pool[rng.randrange(len(pool))]
            used.add((sym, int(bs[j]["ts_ms"])))
            ep = float(bs[j + 1]["open"])
            xp = float(bs[j + 1 + dur]["close"])
            random_vals.append(mh.net_for(str(x["side"]), ep, xp, float(x["realized_cost_bps"])) / 100.0)
        controls["same_count_random_entry"] = random_vals

        ir: list[float] = []
        candidates: list[tuple[int, str, int, str, float]] = []
        for sym in symbols:
            bs = bars_by[sym]
            closes = [float(b["close"]) for b in bs]
            e = ema(closes, cfg.ema_trend_len)
            for i in range(max(64, cfg.ema_trend_len + 2), len(bs) - cfg.timeout_bars - 2):
                if int(bs[i]["ts_ms"]) < boundary_ms or int(bs[i]["ts_ms"]) > latest:
                    continue
                a = atr(bs[: i + 1], cfg.atr_len)
                close = closes[i]
                prev = bs[i - 1]
                long_ok = close > e[i] and e[i] > e[i - 1] and float(prev["close"]) >= float(prev["open"]) and abs(close - e[i]) / max(a, 1e-12) <= 2.0
                short_ok = close < e[i] and e[i] < e[i - 1] and float(prev["close"]) <= float(prev["open"]) and abs(close - e[i]) / max(a, 1e-12) <= 2.0
                if long_ok == short_ok:
                    continue
                candidates.append((int(bs[i]["ts_ms"]), sym, i, "long" if long_ok else "short", a))
        candidates.sort()
        if len(candidates) < len(trades):
            raise RuntimeError(f"INDICATOR_REMOVAL_INSUFFICIENT_TRADES:{len(candidates)}<{len(trades)}")
        for _, sym, i, side, a in candidates[: len(trades)]:
            bs = bars_by[sym]
            entry = float(bs[i]["close"])
            stop = entry - 1.5 * a if side == "long" else entry + 1.5 * a
            cost = float(trades[len(ir)]["realized_cost_bps"])
            value = mh.simulate_stop_timeout(bs, i, side, stop, cfg.timeout_bars, cost)
            if value is None:
                raise RuntimeError("INDICATOR_REMOVAL_OPEN_TRADE")
            ir.append(value / 100.0)
        controls["indicator_removal"] = ir

        control_receipts: dict[str, dict[str, Any]] = {}
        for name in ("same_count_random_entry", "one_bar_delay", "direction_inversion", "timestamp_shuffle", "indicator_removal"):
            vals = controls[name]
            ci, p = mh.paired_stats(cand, vals, int(mh.stable({"window": window_sha, "control": name})[:16], 16))
            control_receipts[name] = mh.replay_receipt(
                name, vals, source_sha=source_sha, data_sha=data_sha,
                config_sha=mh.stable({"base": r["config_sha"], "control": name}),
                window_sha=window_sha, cost_sha=cost_sha, ci=ci, p=p,
            )

        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        h4 = mh.hard.h4_placebo_controls(
            {"candidate_receipt": candidate, "control_receipts": control_receipts},
            policy["h4_placebo_negative_controls"],
        )

        def regime(x: dict[str, Any]) -> str:
            sym = str(x["symbol"])
            i = maps[sym][int(x["signal_ts"])]
            a14 = atr(bars_by[sym][: i + 1], 14)
            a50 = atr(bars_by[sym][: i + 1], 50)
            return "VOL_HIGH" if a14 >= a50 else "VOL_LOW"

        def session(x: dict[str, Any]) -> str:
            hour = datetime.fromtimestamp(int(x["signal_ts"]) / 1000, tz=timezone.utc).hour
            return "APAC" if hour < 8 else "EU" if hour < 16 else "US"

        def window(x: dict[str, Any]) -> str:
            return datetime.fromtimestamp(int(x["entry_ts"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        groupers = {
            "symbol": lambda x: str(x["symbol"]),
            "regime": regime,
            "side": lambda x: str(x["side"]),
            "session": session,
            "window": window,
        }
        total_profit = sum(max(0.0, float(x["net_bps"])) for x in trades)
        total_net_R = sum(float(x["net_bps"]) for x in trades) / 100.0
        dims: dict[str, list[dict[str, Any]]] = {}
        loo: list[dict[str, Any]] = []
        for dim, fn in groupers.items():
            groups: dict[str, list[dict[str, Any]]] = {}
            for x in trades:
                groups.setdefault(fn(x), []).append(x)
            rows: list[dict[str, Any]] = []
            for group, xs in sorted(groups.items()):
                net_R = sum(float(x["net_bps"]) for x in xs) / 100.0
                profit = sum(max(0.0, float(x["net_bps"])) for x in xs)
                rows.append({"group": group, "net_R": net_R, "profit_share": profit / total_profit if total_profit > 0 else 0.0})
                loo.append({"dimension": dim, "group": group, "net_R": total_net_R - net_R})
            dims[dim] = rows

        top10 = sum(sorted((max(0.0, float(x["net_bps"])) for x in trades), reverse=True)[:10]) / total_profit if total_profit > 0 else 0.0
        h5p = policy["h5_concentration_fragility"]
        policy_sha = mh.hard.stable_sha(policy)
        thresholds = {
            "maximum_single_symbol_profit_share": float(h5p["maximum_single_symbol_profit_share"]),
            "maximum_single_regime_profit_share": float(h5p["maximum_single_regime_profit_share"]),
            "maximum_top10_trade_profit_share": float(h5p["maximum_top10_trade_profit_share"]),
            "minimum_leave_one_group_out_net_R": float(h5p["minimum_leave_one_group_out_net_R"]),
        }
        seal = {
            "schema_version": "zel.concentration.threshold_seal.v1",
            "state": "PASS_THRESHOLD_SEAL",
            "policy_sha256": policy_sha,
            "holdout_window_sha256": window_sha,
            "thresholds_sha256": mh.hard.stable_sha(thresholds),
            "sealed_at": mh.POLICY_SEALED_AT,
            "source_commit_sha": mh.POLICY_COMMIT,
        }
        seal["receipt_sha256"] = mh.hard.stable_sha(seal)
        h5 = mh.hard.h5_concentration(
            {
                "threshold_seal_receipt": seal,
                "holdout_window_sha256": window_sha,
                "holdout_opened_at": r["boundary_utc"],
                "dimensions": dims,
                "top10_trade_profit_share": top10,
                "leave_one_group_out": loo,
            },
            h5p,
            policy_sha256=policy_sha,
        )

        h4_pass = h4.get("state") == "PASS_PLACEBO_NEGATIVE_CONTROLS"
        h5_pass = h5.get("state") == "PASS_CONCENTRATION_FRAGILITY"
        mature_budget_ready = len(trades) >= MIN_MATURE_TRADES
        if h4_pass and h5_pass and mature_budget_ready:
            state = "PASS_TRANSITION_FRESHNESS_MATURE_H4_H5"
        elif h4_pass and h5_pass:
            state = "PASS_TRANSITION_FRESHNESS_DEV_H4_H5_NEEDS_FRESH_25PLUS"
        else:
            state = "HOLD_TRANSITION_FRESHNESS_DEV_H4_H5_NEEDS_FRESH_ATTRIBUTION"

        result = {
            "schema_version": SCHEMA,
            "state": state,
            "strategy_id": "trend_rider",
            "candidate_axis": ab.AXIS,
            "baseline_identity": ab.BASELINE_IDENTITY,
            "development_trade_count": len(trades),
            "mature_minimum_trade_count": MIN_MATURE_TRADES,
            "mature_budget_ready": mature_budget_ready,
            "child_w123": child_audit,
            "h4": h4,
            "h5": h5,
            "h4_pass": h4_pass,
            "h5_pass": h5_pass,
            "top10_trade_profit_share": top10,
            "dimensions": dims,
            "leave_one_group_out": loo,
            "diagnostic_only": True,
            "survivor_improvement_claim_allowed": False,
            "next_if_dev_h4_h5_pass": "A2_COST_REVALIDATION_THEN_A3_FRESH_DURABILITY_AND_MATURE_H4_H5_AT_25PLUS",
            "next_if_dev_h4_h5_hold": "ATTRIBUTE_H4_H5_FAILURE_WITHOUT_RETUNING_THEN_A2_COST_DIAGNOSTIC_AND_A3_FRESH_COLLECTION_IF_ECONOMICS_REMAIN_POSITIVE",
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "protected_mutations": 0,
        }
        result["receipt_sha256"] = mh.hard.stable_sha(result)
        return result


def self_test() -> int:
    assert EXPECTED_DEV_TRADES == 14
    assert MIN_MATURE_TRADES == 25
    assert ab.AXIS == "TRANSITION_FRESHNESS_REENTRY_SUPPRESSION_ONLY"
    assert ab.EXPECTED_PARENT["trades"] == 22
    print("PASS_A1_TREND_RIDER_TRANSITION_FRESHNESS_H4_H5_DEV_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_transition_freshness_h4_h5_dev_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = evaluate()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "trades": result["development_trade_count"],
        "H4": result["h4"].get("state"),
        "H5": result["h5"].get("state"),
        "top10": result["top10_trade_profit_share"],
        "mature_budget_ready": result["mature_budget_ready"],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
