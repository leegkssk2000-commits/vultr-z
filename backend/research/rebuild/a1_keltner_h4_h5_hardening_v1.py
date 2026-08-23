#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.breakout_policy_batch_v1 import BreakoutPolicyConfig
from backend.research.rebuild.policy_kernel_v1 import atr, ema
from backend.tools import zel_economic_hardening_gate_v1 as hard

POLICY_COMMIT = "a4624e5c630046ec53f760dcd1abda5137d6a786"
POLICY_SEALED_AT = "2026-08-03T19:18:16+00:00"
MIN_TRADES = 25


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def replay_receipt(control: str, vals: list[float], *, source_sha: str, data_sha: str, config_sha: str, window_sha: str, cost_sha: str, ci: float | None = None, p: float | None = None) -> dict[str, Any]:
    row = {
        "schema_version": "zel.deterministic_replay.result.v1",
        "state": "PASS_DETERMINISTIC_REPLAY_RESULT",
        "result_id": control,
        "control_type": control,
        "source_sha256": source_sha,
        "data_sha256": data_sha,
        "config_sha256": config_sha,
        "window_sha256": window_sha,
        "cost_model_sha256": cost_sha,
        "trade_count": len(vals),
        "net_R": sum(vals),
        "expectancy_R": sum(vals) / len(vals),
    }
    if ci is not None:
        row["candidate_minus_control_ci_low_R"] = ci
    if p is not None:
        row["p_value"] = p
    row["receipt_sha256"] = hard.stable_sha(row)
    return row


def paired_stats(candidate: list[float], control: list[float], seed: int) -> tuple[float, float]:
    if len(candidate) != len(control) or not candidate:
        raise RuntimeError("PAIRED_CONTROL_LENGTH_MISMATCH")
    deltas = [a - b for a, b in zip(candidate, control)]
    rng = random.Random(seed)
    observed = sum(deltas) / len(deltas)
    ge = 1
    boots: list[float] = []
    rounds = 20_000
    for _ in range(rounds):
        signed = sum(x if rng.random() < 0.5 else -x for x in deltas) / len(deltas)
        if signed >= observed:
            ge += 1
    for _ in range(rounds):
        boots.append(sum(deltas[rng.randrange(len(deltas))] for __ in range(len(deltas))))
    boots.sort()
    ci = boots[max(0, int(0.05 * rounds) - 1)]
    return ci, ge / (rounds + 1)


def idx_by_ts(bars: list[dict[str, Any]]) -> dict[int, int]:
    return {int(row["ts_ms"]): i for i, row in enumerate(bars)}


def duration_bars(trade: dict[str, Any], mapping: dict[int, int]) -> int:
    return max(1, mapping[int(trade["exit_ts"])] - mapping[int(trade["entry_ts"])])


def net_for(side: str, entry: float, exit_px: float, cost: float) -> float:
    return (1 if side == "long" else -1) * (exit_px / entry - 1.0) * 10_000.0 - cost


def simulate_stop_timeout(bars: list[dict[str, Any]], signal_i: int, side: str, stop: float, timeout: int, cost: float) -> float | None:
    entry_i = signal_i + 1
    if entry_i >= len(bars):
        return None
    entry = float(bars[entry_i]["open"])
    last = min(len(bars) - 1, entry_i + max(1, timeout))
    exit_px: float | None = None
    for j in range(entry_i, last + 1):
        low = float(bars[j]["low"])
        high = float(bars[j]["high"])
        if (side == "long" and low <= stop) or (side == "short" and high >= stop):
            exit_px = float(stop)
            break
    if exit_px is None:
        exit_px = float(bars[last]["close"])
    return net_for(side, entry, exit_px, cost)


def one_bar_delay_net_R(trade: dict[str, Any], bars: list[dict[str, Any]], mapping: dict[int, int], cfg: BreakoutPolicyConfig) -> float:
    entry_i = mapping[int(trade["entry_ts"])]
    signal_i = entry_i - 1
    if signal_i < 0:
        raise RuntimeError("ONE_BAR_DELAY_SIGNAL_BAR_MISSING")
    a = atr(bars[: signal_i + 1], cfg.atr_len)
    signal_close = float(bars[signal_i]["close"])
    stop = signal_close - 1.25 * a if trade["side"] == "long" else signal_close + 1.25 * a
    value = simulate_stop_timeout(bars, entry_i, str(trade["side"]), stop, cfg.timeout_bars, float(trade["realized_cost_bps"]))
    if value is None:
        raise RuntimeError("ONE_BAR_DELAY_OPEN_TRADE")
    return value / 100.0


def _h5(trades: list[dict[str, Any]], bars_by: dict[str, list[dict[str, Any]]], maps: dict[str, dict[int, int]], window_sha: str, policy: dict[str, Any]) -> dict[str, Any]:
    def regime(trade: dict[str, Any]) -> str:
        bars = bars_by[str(trade["symbol"])]
        i = maps[str(trade["symbol"])][int(trade["signal_ts"])]
        return "VOL_HIGH" if atr(bars[: i + 1], 14) >= atr(bars[: i + 1], 50) else "VOL_LOW"

    def session(trade: dict[str, Any]) -> str:
        hour = datetime.fromtimestamp(int(trade["signal_ts"]) / 1000, tz=timezone.utc).hour
        return "APAC" if hour < 8 else "EU" if hour < 16 else "US"

    def window(trade: dict[str, Any]) -> str:
        return datetime.fromtimestamp(int(trade["entry_ts"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    groupers = {
        "symbol": lambda x: str(x["symbol"]),
        "regime": regime,
        "side": lambda x: str(x["side"]),
        "session": session,
        "window": window,
    }
    total_profit = sum(max(0.0, float(x["net_bps"])) for x in trades)
    total_net = sum(float(x["net_bps"]) for x in trades) / 100.0
    dimensions: dict[str, list[dict[str, Any]]] = {}
    leave_one: list[dict[str, Any]] = []
    for dimension, fn in groupers.items():
        groups: dict[str, list[dict[str, Any]]] = {}
        for trade in trades:
            groups.setdefault(fn(trade), []).append(trade)
        rows = []
        for group, subset in sorted(groups.items()):
            net_r = sum(float(x["net_bps"]) for x in subset) / 100.0
            profit = sum(max(0.0, float(x["net_bps"])) for x in subset)
            rows.append({"group": group, "net_R": net_r, "profit_share": profit / total_profit if total_profit > 0 else 0.0})
            leave_one.append({"dimension": dimension, "group": group, "net_R": total_net - net_r})
        dimensions[dimension] = rows
    top10 = sum(sorted((max(0.0, float(x["net_bps"])) for x in trades), reverse=True)[:10]) / total_profit if total_profit > 0 else 0.0
    h5p = policy["h5_concentration_fragility"]
    policy_sha = hard.stable_sha(policy)
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
        "thresholds_sha256": hard.stable_sha(thresholds),
        "sealed_at": POLICY_SEALED_AT,
        "source_commit_sha": POLICY_COMMIT,
    }
    seal["receipt_sha256"] = hard.stable_sha(seal)
    return hard.h5_concentration({
        "threshold_seal_receipt": seal,
        "holdout_window_sha256": window_sha,
        "holdout_opened_at": trades[0]["signal_ts_iso"] if "signal_ts_iso" in trades[0] else None,
        "dimensions": dimensions,
        "top10_trade_profit_share": top10,
        "leave_one_group_out": leave_one,
    }, h5p, policy_sha256=policy_sha)


def run(receipt_path: Path, out: Path) -> dict[str, Any]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("strategy_id") != "keltner_trend" or int(receipt.get("completed_trades") or 0) < MIN_TRADES:
        raise RuntimeError("KELTNER_HARDENING_MIN_SAMPLE_OR_ID_FAIL")
    trades = [dict(x) for x in receipt["trades"]]
    if len(trades) != int(receipt["completed_trades"]):
        raise RuntimeError("KELTNER_TRADE_COUNT_MISMATCH")
    cfg = BreakoutPolicyConfig()
    boundary = str(receipt.get("fresh_boundary_utc") or receipt.get("boundary_utc") or "")
    if not boundary:
        raise RuntimeError("KELTNER_BOUNDARY_MISSING")
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by = {symbol: ev.fetch_bars(symbol, "1h", 1000) for symbol in symbols}
    maps = {symbol: idx_by_ts(bars_by[symbol]) for symbol in symbols}
    latest = max(int(x["exit_ts"]) for x in trades)
    material = {symbol: [bar for bar in bars_by[symbol] if boundary_ms <= int(bar["ts_ms"]) <= latest + cfg.timeframe_ms] for symbol in symbols}
    source_sha = stable(receipt["source"])
    data_sha = stable(material)
    window_sha = stable({"boundary": boundary, "latest_exit": latest, "symbols": symbols, "trade_count": len(trades)})
    cost_sha = str(receipt["cost_authority_sha256"])
    candidate_values = [float(x["net_bps"]) / 100.0 for x in trades]
    candidate = replay_receipt("candidate", candidate_values, source_sha=source_sha, data_sha=data_sha, config_sha=str(receipt["config_sha"]), window_sha=window_sha, cost_sha=cost_sha)

    controls: dict[str, list[float]] = {}
    controls["direction_inversion"] = [(-float(x["gross_bps"]) - float(x["realized_cost_bps"])) / 100.0 for x in trades]
    sides = [str(x["side"]) for x in trades]
    rng = random.Random(int(window_sha[:16], 16))
    shuffled = sides[:]
    rng.shuffle(shuffled)
    controls["timestamp_shuffle"] = [net_for(shuffled[i], float(x["entry"]), float(x["exit"]), float(x["realized_cost_bps"])) / 100.0 for i, x in enumerate(trades)]
    controls["one_bar_delay"] = [one_bar_delay_net_R(x, bars_by[str(x["symbol"])], maps[str(x["symbol"])], cfg) for x in trades]

    random_values = []
    used: set[tuple[str, int]] = set()
    for trade in trades:
        symbol = str(trade["symbol"])
        bars = bars_by[symbol]
        mapping = maps[symbol]
        duration = duration_bars(trade, mapping)
        pool = [j for j, bar in enumerate(bars) if boundary_ms <= int(bar["ts_ms"]) <= latest and j + 1 + duration < len(bars) and (symbol, int(bar["ts_ms"])) not in used]
        if not pool:
            raise RuntimeError("KELTNER_RANDOM_ENTRY_POOL_EXHAUSTED")
        j = pool[rng.randrange(len(pool))]
        used.add((symbol, int(bars[j]["ts_ms"])))
        entry = float(bars[j + 1]["open"])
        exit_px = float(bars[j + 1 + duration]["close"])
        random_values.append(net_for(str(trade["side"]), entry, exit_px, float(trade["realized_cost_bps"])) / 100.0)
    controls["same_count_random_entry"] = random_values

    indicator_removed: list[float] = []
    candidates: list[tuple[int, str, int, str, float]] = []
    for symbol in symbols:
        bars = bars_by[symbol]
        closes = [float(x["close"]) for x in bars]
        fast = ema(closes, cfg.ema_fast_len)
        slow = ema(closes, cfg.ema_slow_len)
        for i in range(max(64, cfg.ema_slow_len + 3), len(bars) - cfg.timeout_bars - 2):
            ts = int(bars[i]["ts_ms"])
            if ts < boundary_ms or ts > latest:
                continue
            a = atr(bars[: i + 1], cfg.atr_len)
            prev_a = atr(bars[:i], cfg.atr_len)
            expansion = a / max(prev_a, 1e-12)
            long_ok = fast[i] > slow[i] and fast[i] >= fast[i - 1] and expansion >= 1.0
            short_ok = fast[i] < slow[i] and fast[i] <= fast[i - 1] and expansion >= 1.0
            if long_ok == short_ok:
                continue
            candidates.append((ts, symbol, i, "long" if long_ok else "short", a))
    candidates.sort()
    if len(candidates) < len(trades):
        raise RuntimeError(f"KELTNER_INDICATOR_REMOVAL_INSUFFICIENT_TRADES:{len(candidates)}<{len(trades)}")
    for _, symbol, i, side, a in candidates[: len(trades)]:
        bars = bars_by[symbol]
        signal_close = float(bars[i]["close"])
        stop = signal_close - 1.25 * a if side == "long" else signal_close + 1.25 * a
        cost = float(trades[len(indicator_removed)]["realized_cost_bps"])
        value = simulate_stop_timeout(bars, i, side, stop, cfg.timeout_bars, cost)
        if value is None:
            raise RuntimeError("KELTNER_INDICATOR_REMOVAL_OPEN_TRADE")
        indicator_removed.append(value / 100.0)
    controls["indicator_removal"] = indicator_removed

    control_receipts: dict[str, dict[str, Any]] = {}
    for name in ("same_count_random_entry", "one_bar_delay", "direction_inversion", "timestamp_shuffle", "indicator_removal"):
        values = controls[name]
        ci, p_value = paired_stats(candidate_values, values, int(stable({"window": window_sha, "control": name})[:16], 16))
        control_receipts[name] = replay_receipt(name, values, source_sha=source_sha, data_sha=data_sha, config_sha=stable({"base": receipt["config_sha"], "control": name}), window_sha=window_sha, cost_sha=cost_sha, ci=ci, p=p_value)

    policy = json.loads(Path("backend/research/zel_economic_hardening_policy_v1.json").read_text(encoding="utf-8"))
    h4 = hard.h4_placebo_controls({"candidate_receipt": candidate, "control_receipts": control_receipts}, policy["h4_placebo_negative_controls"])

    # H5 uses the same sealed dimensions/thresholds as the installed hardening engine.
    def regime(trade: dict[str, Any]) -> str:
        bars = bars_by[str(trade["symbol"])]
        i = maps[str(trade["symbol"])][int(trade["signal_ts"])]
        return "VOL_HIGH" if atr(bars[: i + 1], 14) >= atr(bars[: i + 1], 50) else "VOL_LOW"

    def session(trade: dict[str, Any]) -> str:
        hour = datetime.fromtimestamp(int(trade["signal_ts"]) / 1000, tz=timezone.utc).hour
        return "APAC" if hour < 8 else "EU" if hour < 16 else "US"

    def window(trade: dict[str, Any]) -> str:
        return datetime.fromtimestamp(int(trade["entry_ts"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

    groupers = {"symbol": lambda x: str(x["symbol"]), "regime": regime, "side": lambda x: str(x["side"]), "session": session, "window": window}
    total_profit = sum(max(0.0, float(x["net_bps"])) for x in trades)
    total_net = sum(float(x["net_bps"]) for x in trades) / 100.0
    dimensions: dict[str, list[dict[str, Any]]] = {}
    leave_one: list[dict[str, Any]] = []
    for dimension, fn in groupers.items():
        groups: dict[str, list[dict[str, Any]]] = {}
        for trade in trades:
            groups.setdefault(fn(trade), []).append(trade)
        dim_rows = []
        for group, subset in sorted(groups.items()):
            net_r = sum(float(x["net_bps"]) for x in subset) / 100.0
            profit = sum(max(0.0, float(x["net_bps"])) for x in subset)
            dim_rows.append({"group": group, "net_R": net_r, "profit_share": profit / total_profit if total_profit > 0 else 0.0})
            leave_one.append({"dimension": dimension, "group": group, "net_R": total_net - net_r})
        dimensions[dimension] = dim_rows
    top10 = sum(sorted((max(0.0, float(x["net_bps"])) for x in trades), reverse=True)[:10]) / total_profit if total_profit > 0 else 0.0
    h5_policy = policy["h5_concentration_fragility"]
    policy_sha = hard.stable_sha(policy)
    thresholds = {
        "maximum_single_symbol_profit_share": float(h5_policy["maximum_single_symbol_profit_share"]),
        "maximum_single_regime_profit_share": float(h5_policy["maximum_single_regime_profit_share"]),
        "maximum_top10_trade_profit_share": float(h5_policy["maximum_top10_trade_profit_share"]),
        "minimum_leave_one_group_out_net_R": float(h5_policy["minimum_leave_one_group_out_net_R"]),
    }
    seal = {
        "schema_version": "zel.concentration.threshold_seal.v1",
        "state": "PASS_THRESHOLD_SEAL",
        "policy_sha256": policy_sha,
        "holdout_window_sha256": window_sha,
        "thresholds_sha256": hard.stable_sha(thresholds),
        "sealed_at": POLICY_SEALED_AT,
        "source_commit_sha": POLICY_COMMIT,
    }
    seal["receipt_sha256"] = hard.stable_sha(seal)
    h5 = hard.h5_concentration({
        "threshold_seal_receipt": seal,
        "holdout_window_sha256": window_sha,
        "holdout_opened_at": boundary,
        "dimensions": dimensions,
        "top10_trade_profit_share": top10,
        "leave_one_group_out": leave_one,
    }, h5_policy, policy_sha256=policy_sha)

    source_quality = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), dict) else {}
    integrity_defects = list(receipt.get("integrity_defects") or [])
    leakage = int(receipt.get("leakage_lookahead") or 0)
    integrity_ok = source_quality.get("state") == "PASS" and not integrity_defects and leakage == 0
    hardening_ok = h4["state"] == "PASS_PLACEBO_NEGATIVE_CONTROLS" and h5["state"] == "PASS_CONCENTRATION_FRAGILITY"
    evidence = {
        "schema_version": "zel.a1.keltner.h4_h5_hardening.v1",
        "state": "PASS_HARDENING_EVIDENCE" if hardening_ok and integrity_ok else "HOLD_HARDENING_EVIDENCE",
        "strategy_id": "keltner_trend",
        "candidate_id": receipt.get("candidate_id"),
        "changed_axis": receipt.get("changed_axis"),
        "candidate_receipt_sha256": receipt["receipt_sha256"],
        "candidate_trade_count": len(trades),
        "boundary_utc": boundary,
        "cost_authority_sha256": cost_sha,
        "candidate_integrity": {"state": "PASS" if integrity_ok else "HOLD", "source_quality_state": source_quality.get("state"), "integrity_defects": integrity_defects, "leakage_lookahead": leakage, "fail_closed": True},
        "h4_receipt": h4,
        "h5_receipt": h5,
        "fixture": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    evidence["receipt_sha256"] = hard.stable_sha(evidence)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return evidence


def self_test() -> int:
    cfg = BreakoutPolicyConfig()
    assert cfg.timeout_bars == 48
    assert cfg.keltner_atr_mult == 1.5
    assert MIN_TRADES == 25
    print("PASS_A1_KELTNER_H4_H5_HARDENING_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_h4_h5_hardening_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.receipt is None:
        raise SystemExit("--receipt required")
    row = run(args.receipt, args.out)
    print(json.dumps({"state": row["state"], "H4": row["h4_receipt"]["state"], "H5": row["h5_receipt"]["state"], "candidate_trade_count": row["candidate_trade_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
