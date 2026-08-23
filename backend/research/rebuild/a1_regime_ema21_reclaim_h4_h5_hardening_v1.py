#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_keltner_h4_h5_hardening_v1 as kh
from backend.research.rebuild.breakout_policy_batch_v1 import BreakoutPolicyConfig
from backend.research.rebuild.policy_kernel_v1 import atr, ema
from backend.tools import zel_economic_hardening_gate_v1 as hard

MIN_TRADES = 25
IDENTITY = "regime_ema21_reclaim_v1"
INDICATOR_REMOVAL_SEMANTICS = "REMOVE_EMA21_TOUCH_RECLAIM_KEEP_VOL_HIGH_AND_EMA21_55_DIRECTION"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def run(receipt_path: Path, out: Path) -> dict[str, Any]:
    receipt = _read(receipt_path)
    if receipt.get("candidate_identity") != IDENTITY:
        raise RuntimeError("EMA21_RECLAIM_IDENTITY_MISMATCH")
    if int(receipt.get("completed_trades") or 0) < MIN_TRADES:
        raise RuntimeError("EMA21_RECLAIM_HARDENING_MIN_SAMPLE_FAIL")
    if receipt.get("existing_keltner_h4_h5_reuse_for_promotion") is not False:
        raise RuntimeError("EMA21_RECLAIM_KELTNER_HARDENING_REUSE_FORBIDDEN")

    trades = [dict(x) for x in receipt.get("trades") or []]
    if len(trades) != int(receipt["completed_trades"]):
        raise RuntimeError("EMA21_RECLAIM_TRADE_COUNT_MISMATCH")
    boundary = str(receipt.get("fresh_boundary_utc") or receipt.get("boundary_utc") or "")
    if not boundary:
        raise RuntimeError("EMA21_RECLAIM_BOUNDARY_MISSING")
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)

    cfg = BreakoutPolicyConfig()
    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by = {symbol: ev.fetch_bars(symbol, "1h", 1000) for symbol in symbols}
    maps = {symbol: kh.idx_by_ts(bars_by[symbol]) for symbol in symbols}
    latest = max(int(x["exit_ts"]) for x in trades)
    material = {
        symbol: [bar for bar in bars_by[symbol] if boundary_ms <= int(bar["ts_ms"]) <= latest + cfg.timeframe_ms]
        for symbol in symbols
    }
    source_sha = kh.stable(receipt["source"])
    data_sha = kh.stable(material)
    window_sha = kh.stable({"identity": IDENTITY, "boundary": boundary, "latest_exit": latest, "symbols": symbols, "trade_count": len(trades)})
    cost_sha = str(receipt["cost_authority_sha256"])
    config_sha = str(receipt["config_sha"])
    candidate_values = [float(x["net_bps"]) / 100.0 for x in trades]
    candidate = kh.replay_receipt(
        "candidate", candidate_values, source_sha=source_sha, data_sha=data_sha,
        config_sha=config_sha, window_sha=window_sha, cost_sha=cost_sha,
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
        kh.net_for(shuffled[i], float(x["entry"]), float(x["exit"]), float(x["realized_cost_bps"])) / 100.0
        for i, x in enumerate(trades)
    ]
    controls["one_bar_delay"] = [
        kh.one_bar_delay_net_R(x, bars_by[str(x["symbol"])], maps[str(x["symbol"])], cfg)
        for x in trades
    ]

    random_values: list[float] = []
    used: set[tuple[str, int]] = set()
    for trade in trades:
        symbol = str(trade["symbol"])
        bars = bars_by[symbol]
        mapping = maps[symbol]
        duration = kh.duration_bars(trade, mapping)
        pool = [
            j for j, bar in enumerate(bars)
            if boundary_ms <= int(bar["ts_ms"]) <= latest
            and j + 1 + duration < len(bars)
            and (symbol, int(bar["ts_ms"])) not in used
        ]
        if not pool:
            raise RuntimeError("EMA21_RECLAIM_RANDOM_ENTRY_POOL_EXHAUSTED")
        j = pool[rng.randrange(len(pool))]
        used.add((symbol, int(bars[j]["ts_ms"])))
        entry = float(bars[j + 1]["open"])
        exit_px = float(bars[j + 1 + duration]["close"])
        random_values.append(
            kh.net_for(str(trade["side"]), entry, exit_px, float(trade["realized_cost_bps"])) / 100.0
        )
    controls["same_count_random_entry"] = random_values

    # Identity-specific indicator removal: preserve the VOL_HIGH trend regime and
    # EMA21/55 direction, but remove the defining prior-touch/current-reclaim event.
    indicator_removed: list[float] = []
    candidates: list[tuple[int, str, int, str, float]] = []
    for symbol in symbols:
        bars = bars_by[symbol]
        closes = [float(x["close"]) for x in bars]
        fast = ema(closes, cfg.ema_fast_len)
        slow = ema(closes, cfg.ema_slow_len)
        start = max(64, cfg.ema_slow_len + 3)
        for i in range(start, len(bars) - cfg.timeout_bars - 2):
            ts_ms = int(bars[i]["ts_ms"])
            if ts_ms < boundary_ms or ts_ms > latest:
                continue
            a14 = atr(bars[: i + 1], 14)
            a50 = atr(bars[: i + 1], 50)
            vol_high = a14 >= a50
            long_ok = bool(vol_high and fast[i] > slow[i])
            short_ok = bool(vol_high and fast[i] < slow[i])
            if long_ok == short_ok:
                continue
            candidates.append((ts_ms, symbol, i, "long" if long_ok else "short", a14))
    candidates.sort()
    if len(candidates) < len(trades):
        raise RuntimeError(f"EMA21_RECLAIM_INDICATOR_REMOVAL_INSUFFICIENT:{len(candidates)}<{len(trades)}")
    for _, symbol, i, side, a14 in candidates[: len(trades)]:
        bars = bars_by[symbol]
        signal_close = float(bars[i]["close"])
        stop = signal_close - 1.25 * a14 if side == "long" else signal_close + 1.25 * a14
        cost = float(trades[len(indicator_removed)]["realized_cost_bps"])
        value = kh.simulate_stop_timeout(bars, i, side, stop, cfg.timeout_bars, cost)
        if value is None:
            raise RuntimeError("EMA21_RECLAIM_INDICATOR_REMOVAL_OPEN_TRADE")
        indicator_removed.append(value / 100.0)
    controls["indicator_removal"] = indicator_removed

    control_receipts: dict[str, dict[str, Any]] = {}
    for name in ("same_count_random_entry", "one_bar_delay", "direction_inversion", "timestamp_shuffle", "indicator_removal"):
        values = controls[name]
        ci, p_value = kh.paired_stats(candidate_values, values, int(kh.stable({"identity": IDENTITY, "window": window_sha, "control": name})[:16], 16))
        control_receipts[name] = kh.replay_receipt(
            name, values, source_sha=source_sha, data_sha=data_sha,
            config_sha=kh.stable({"base": config_sha, "identity": IDENTITY, "control": name}),
            window_sha=window_sha, cost_sha=cost_sha, ci=ci, p=p_value,
        )

    policy = _read(Path("backend/research/zel_economic_hardening_policy_v1.json"))
    h4 = hard.h4_placebo_controls(
        {"candidate_receipt": candidate, "control_receipts": control_receipts},
        policy["h4_placebo_negative_controls"],
    )
    h5 = kh._h5(trades, bars_by, maps, window_sha, policy)

    source_quality = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), dict) else {}
    defects = list(receipt.get("integrity_defects") or [])
    lookahead = int(receipt.get("leakage_lookahead") or 0)
    integrity_ok = source_quality.get("state") == "PASS" and not defects and lookahead == 0
    hardening_ok = h4.get("state") == "PASS_PLACEBO_NEGATIVE_CONTROLS" and h5.get("state") == "PASS_CONCENTRATION_FRAGILITY"
    state = "PASS_EMA21_RECLAIM_IDENTITY_HARDENING" if integrity_ok and hardening_ok else "HOLD_EMA21_RECLAIM_IDENTITY_HARDENING"
    result = {
        "schema_version": "zel.a1.regime_ema21_reclaim.hardening.v1",
        "state": state,
        "candidate_identity": IDENTITY,
        "identity_specific_controls": True,
        "indicator_removal_semantics": INDICATOR_REMOVAL_SEMANTICS,
        "candidate_trade_count": len(trades),
        "fresh_boundary_utc": boundary,
        "candidate_receipt_sha256": receipt.get("receipt_sha256"),
        "source_quality_state": source_quality.get("state"),
        "integrity_defects": defects,
        "leakage_lookahead": lookahead,
        "h4_receipt": h4,
        "h5_receipt": h5,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": "SURVIVOR_CANDIDATE_PASS_THEN_A2_A3" if state.startswith("PASS_") else "PRESERVE_EVIDENCE_AND_ROUTE_NEXT_DISTINCT_AXIS",
    }
    result["receipt_sha256"] = hard.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert IDENTITY == "regime_ema21_reclaim_v1"
    assert "REMOVE_EMA21_TOUCH_RECLAIM" in INDICATOR_REMOVAL_SEMANTICS
    assert "KEEP_VOL_HIGH" in INDICATOR_REMOVAL_SEMANTICS
    print("PASS_A1_REGIME_EMA21_RECLAIM_H4_H5_HARDENING_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_regime_ema21_reclaim_h4_h5_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.receipt is None:
        raise SystemExit("--receipt required")
    result = run(args.receipt, args.out)
    print(json.dumps({
        "state": result["state"],
        "candidate_trade_count": result["candidate_trade_count"],
        "H4": (result["h4_receipt"] or {}).get("state"),
        "H5": (result["h5_receipt"] or {}).get("state"),
        "next": result["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
