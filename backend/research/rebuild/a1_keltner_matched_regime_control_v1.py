#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_keltner_h4_h5_hardening_v1 as hardk
from backend.research.rebuild.breakout_policy_batch_v1 import BreakoutPolicyConfig
from backend.research.rebuild.policy_kernel_v1 import atr, ema

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "zel.a1.keltner.matched_regime_control.v1"
MIN_TRADES = 25
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _read(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return row


def _session(ts_ms: int) -> str:
    h = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour
    return "APAC" if h < 8 else "EU" if h < 16 else "US"


def _regime(bars: list[dict[str, Any]], i: int) -> str:
    return "VOL_HIGH" if atr(bars[: i + 1], 14) >= atr(bars[: i + 1], 50) else "VOL_LOW"


def _aligned(side: str, fast: list[float], slow: list[float], i: int) -> bool:
    return fast[i] > slow[i] if side == "long" else fast[i] < slow[i]


def _passed(delta: float, ci: float, p: float) -> bool:
    return delta > 0 and ci > 0 and p <= 0.05


def run(out: Path) -> dict[str, Any]:
    cfg = BreakoutPolicyConfig()
    with tempfile.TemporaryDirectory(prefix="keltner-matched-regime-") as td:
        work = Path(td)
        candidate_path = work / "candidate.json"
        cp = subprocess.run([
            sys.executable, "-m", "backend.research.rebuild.a1_exact25_generic_evaluator_v2",
            "--strategy-id", "keltner_trend", "--out", str(candidate_path), "--terminal-replay",
        ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
        if cp.returncode != 0 or not candidate_path.is_file():
            raise RuntimeError("KELTNER_TERMINAL_REPLAY_FAILED:" + (cp.stderr or cp.stdout)[-1200:])
        receipt = _read(candidate_path)

    trades = [dict(x) for x in (receipt.get("trades") or [])]
    if len(trades) < MIN_TRADES:
        raise RuntimeError(f"KELTNER_MATCHED_REGIME_MIN_SAMPLE:{len(trades)}")
    if list(receipt.get("integrity_defects") or []) or int(receipt.get("leakage_lookahead") or 0) != 0:
        raise RuntimeError("KELTNER_MATCHED_REGIME_INTEGRITY_FAIL")
    boundary = str(receipt.get("prospective_boundary_utc") or receipt.get("boundary_utc") or "")
    if not boundary:
        raise RuntimeError("KELTNER_MATCHED_REGIME_BOUNDARY_MISSING")
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    latest = max(int(x["exit_ts"]) for x in trades)
    symbols = sorted({str(x["symbol"]) for x in trades})
    bars_by = {s: [dict(x) for x in ev.fetch_bars(s, "1h", 1000)] for s in symbols}
    maps = {s: {int(b["ts_ms"]): i for i, b in enumerate(bars_by[s])} for s in symbols}
    ema_by: dict[str, tuple[list[float], list[float]]] = {}
    for s in symbols:
        closes = [float(x["close"]) for x in bars_by[s]]
        ema_by[s] = (ema(closes, cfg.ema_fast_len), ema(closes, cfg.ema_slow_len))

    rng = random.Random(int(ev.stable_sha({"candidate": receipt.get("receipt_sha256"), "control": SCHEMA})[:16], 16))
    candidate_signal_keys = {(str(x["symbol"]), int(x["signal_ts"])) for x in trades}
    used: set[tuple[str, int]] = set()
    duration_values: list[float] = []
    policy_exit_values: list[float] = []
    matched_rows: list[dict[str, Any]] = []

    for trade in trades:
        symbol = str(trade["symbol"])
        side = str(trade["side"])
        bars = bars_by[symbol]
        mapping = maps[symbol]
        fast, slow = ema_by[symbol]
        signal_i = mapping[int(trade["signal_ts"])]
        entry_i = mapping[int(trade["entry_ts"])]
        exit_i = mapping[int(trade["exit_ts"])]
        duration = max(1, exit_i - entry_i)
        target_regime = _regime(bars, signal_i)
        target_session = _session(int(trade["signal_ts"]))
        pool: list[int] = []
        for j in range(64, len(bars) - cfg.timeout_bars - 2):
            ts_ms = int(bars[j]["ts_ms"])
            if ts_ms < boundary_ms or ts_ms > latest:
                continue
            key = (symbol, ts_ms)
            if key in used or key in candidate_signal_keys:
                continue
            if j + 1 + duration >= len(bars):
                continue
            if _session(ts_ms) != target_session or _regime(bars, j) != target_regime:
                continue
            if not _aligned(side, fast, slow, j):
                continue
            pool.append(j)
        if not pool:
            raise RuntimeError(f"MATCHED_REGIME_POOL_EXHAUSTED:{symbol}:{side}:{target_regime}:{target_session}")
        j = pool[rng.randrange(len(pool))]
        used.add((symbol, int(bars[j]["ts_ms"])))
        cost = float(trade["realized_cost_bps"])
        entry = float(bars[j + 1]["open"])
        exit_px = float(bars[j + 1 + duration]["close"])
        duration_net_r = hardk.net_for(side, entry, exit_px, cost) / 100.0
        a = atr(bars[: j + 1], cfg.atr_len)
        signal_close = float(bars[j]["close"])
        stop = signal_close - 1.25 * a if side == "long" else signal_close + 1.25 * a
        policy_net_bps = hardk.simulate_stop_timeout(bars, j, side, stop, cfg.timeout_bars, cost)
        if policy_net_bps is None:
            raise RuntimeError("MATCHED_REGIME_POLICY_EXIT_OPEN")
        policy_net_r = policy_net_bps / 100.0
        duration_values.append(duration_net_r)
        policy_exit_values.append(policy_net_r)
        matched_rows.append({
            "symbol": symbol,
            "side": side,
            "candidate_signal_ts": int(trade["signal_ts"]),
            "matched_signal_ts": int(bars[j]["ts_ms"]),
            "regime": target_regime,
            "session": target_session,
            "duration_bars": duration,
            "candidate_net_R": float(trade["net_bps"]) / 100.0,
            "duration_matched_random_net_R": duration_net_r,
            "policy_exit_matched_random_net_R": policy_net_r,
        })

    candidate_values = [float(x["net_bps"]) / 100.0 for x in trades]
    seed1 = int(ev.stable_sha({"receipt": receipt.get("receipt_sha256"), "kind": "duration"})[:16], 16)
    seed2 = int(ev.stable_sha({"receipt": receipt.get("receipt_sha256"), "kind": "policy_exit"})[:16], 16)
    ci1, p1 = hardk.paired_stats(candidate_values, duration_values, seed1)
    ci2, p2 = hardk.paired_stats(candidate_values, policy_exit_values, seed2)
    cand_net = sum(candidate_values)
    dur_net = sum(duration_values)
    pol_net = sum(policy_exit_values)
    dur_delta = cand_net - dur_net
    pol_delta = cand_net - pol_net
    dur_pass = _passed(dur_delta, ci1, p1)
    pol_pass = _passed(pol_delta, ci2, p2)

    if dur_pass and pol_pass:
        state = "ENTRY_TIMING_EDGE_SURVIVES_MATCHED_REGIME"
        nxt = "PRESERVE_KELTNER_ENTRY_AND_ADDRESS_H5_BREADTH_ONLY"
    elif (not dur_pass) and pol_pass:
        state = "H4_RANDOM_FAILURE_CONTROL_SPEC_SENSITIVE"
        nxt = "FIX_NEGATIVE_CONTROL_EXIT_PARITY_BEFORE_STRATEGY_REPAIR"
    elif not dur_pass and not pol_pass:
        state = "REGIME_PREMIUM_DOMINATES_KELTNER_ENTRY_TIMING"
        nxt = "DESIGN_REGIME_CORE_PLUS_TIMING_CHILD_WITHOUT_CUTTING_VOL_HIGH_LONG_WINNERS"
    else:
        state = "MATCHED_REGIME_CONTROL_MIXED"
        nxt = "HOLD_AND_DECOMPOSE_CONTROL_MISMATCH"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": "keltner_trend",
        "candidate_trade_count": len(trades),
        "candidate_net_R": cand_net,
        "candidate_net_pnl_bps": cand_net * 100.0,
        "prospective_boundary_utc": boundary,
        "matching_dimensions": ["symbol", "side", "VOL_HIGH_OR_LOW", "UTC_session", "EMA21_55_alignment"],
        "duration_matched_random": {
            "net_R": dur_net,
            "candidate_minus_control_net_R": dur_delta,
            "candidate_minus_control_ci_low_R": ci1,
            "p_value": p1,
            "pass": dur_pass,
        },
        "policy_exit_matched_random": {
            "exit_rule": "same_keltner_1.25ATR_stop_and_48bar_timeout",
            "net_R": pol_net,
            "candidate_minus_control_net_R": pol_delta,
            "candidate_minus_control_ci_low_R": ci2,
            "p_value": p2,
            "pass": pol_pass,
        },
        "matched_rows": matched_rows,
        "numeric_threshold_sweep": False,
        "candidate_policy_mutated": False,
        "canonical_ledger_mutation": False,
        "next": nxt,
        **AUTH,
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert _session(7 * 3600 * 1000) == "APAC"
    assert _session(8 * 3600 * 1000) == "EU"
    assert _session(16 * 3600 * 1000) == "US"
    assert _passed(1.0, 0.1, 0.05) is True
    assert _passed(1.0, -0.1, 0.01) is False
    print("PASS_A1_KELTNER_MATCHED_REGIME_CONTROL_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_matched_regime_control_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    print(json.dumps({"state": r["state"], "candidate_net_R": r["candidate_net_R"], "duration": r["duration_matched_random"], "policy_exit": r["policy_exit_matched_random"], "next": r["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
