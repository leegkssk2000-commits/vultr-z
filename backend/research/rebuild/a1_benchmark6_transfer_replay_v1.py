from __future__ import annotations
import argparse
import contextlib
import gzip
import io
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any
from backend.research.rebuild import a1_exact25_generic_evaluator_three_lane_v1 as ev
from backend.research.rebuild.a1_strategy19_5m_replay_v1 import (
    load_cache,
    BASELINE_LEDGER,
)
from backend.research.rebuild.policy_kernel_v1 import ema

ROOT = Path(__file__).resolve().parents[3]
CACHE = Path("/home/z/z/runtime/three_lane_5m_180d_v2")
MICRO = Path("/home/z/z/runtime/benchmark6_micro_5m_v1.jsonl.gz")
B6 = (
    "liquidity_sweep",
    "scalp_snap",
    "vol_spike_fade",
    "ema_ribbon_scalp",
    "session_bias",
    "sr_levels",
)
MICRO3 = {"liquidity_sweep", "scalp_snap", "vol_spike_fade"}
SYMS6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")


def metrics(d: dict[str, Any]) -> dict[str, Any]:
    m = d.get("metrics") or {}
    return {
        "T": int(d.get("completed_trades") or 0),
        "WR": m.get("win_rate"),
        "Net_bps": m.get("net_pnl_bps"),
        "Exp_bps_T": m.get("net_expectancy_bps"),
        "PF": m.get("net_profit_factor"),
        "DD_bps": m.get("max_drawdown_bps"),
    }


def split(d: dict[str, Any]) -> dict[str, Any]:
    tr = sorted(
        d.get("trades") or [], key=lambda x: (int(x["exit_ts"]), str(x["symbol"]))
    )
    cut = int(len(tr) * 0.6)

    def mm(xs):
        vals = [float(x["net_bps"]) for x in xs]
        w = [x for x in vals if x > 0]
        losses = [-x for x in vals if x < 0]
        eq = pk = dd = 0.0
        for x in vals:
            eq += x
            pk = max(pk, eq)
            dd = max(dd, pk - eq)
        return {
            "T": len(vals),
            "WR": len(w) / len(vals) if vals else None,
            "Net_bps": sum(vals),
            "PF": sum(w) / sum(losses) if losses else None,
            "DD_bps": dd,
        }

    return {"train60": mm(tr[:cut]), "holdout40": mm(tr[cut:])}


def load_micro() -> dict[tuple[str, int], dict[str, Any]]:
    out = {}
    with gzip.open(MICRO, "rt", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            out[(str(x["symbol"]), int(x["ts_ms"]))] = x
    return out


def micro_ok(sid: str, side: str, x: dict[str, Any]) -> bool:
    ti = x.get("trade_imbalance")
    bd = x.get("bid_change")
    ad = x.get("ask_change")
    imd = x.get("imbalance_delta")
    if ti is None or bd is None or ad is None or imd is None:
        return False
    if int(x.get("depth_messages") or 0) <= 0 or int(x.get("trade_messages") or 0) <= 0:
        return False
    ti = float(ti)
    bd = float(bd)
    ad = float(ad)
    imd = float(imd)
    if sid == "liquidity_sweep":
        return (
            (ti > 0 and (bd > 0 or imd > 0))
            if side == "long"
            else (ti < 0 and (ad > 0 or imd < 0))
        )
    if sid == "scalp_snap":
        return (
            (ti > 0 and bd > 0 and imd > 0)
            if side == "long"
            else (ti < 0 and ad > 0 and imd < 0)
        )
    # Exhaustion fade: continuation flow must have stopped and book imbalance must recover toward fade direction.
    return (ti >= 0 and imd > 0) if side == "long" else (ti <= 0 and imd < 0)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy-id", choices=B6, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    sid = args.strategy_id
    args.out_dir.mkdir(parents=True, exist_ok=True)
    bars = load_cache(CACHE)
    micro = load_micro() if sid in MICRO3 else {}
    if sid in MICRO3:
        first = min(t for (s, t) in micro)
        last = max(t for (s, t) in micro)
        # Keep warmup before first observable L2 bucket, but no economics outside observed microstructure coverage.
        for s in ("BTC-USDT", "ETH-USDT"):
            bars[s] = [
                b
                for b in bars[s]
                if int(b["ts_ms"]) >= first - 36_000_000
                and int(b["ts_ms"]) <= last + 300_000
            ]
        symbols = ("BTC-USDT", "ETH-USDT")
    else:
        symbols = SYMS6
        # Fast A/B screen on the same post-boundary month as the observable microstructure lane.
        cutoff = 1786719300000 - 36_000_000
        for s in symbols:
            bars[s] = [b for b in bars[s] if int(b["ts_ms"]) >= cutoff]
    ledger = json.loads(BASELINE_LEDGER.read_text())
    ledger["strategies"][sid]["status"] = "ACTIVE"
    meta = {}
    orig_pf = ev.policy_functions
    orig_b = ev.fetch_bars
    orig_s = ev.fetch_execution_snapshot
    orig_l = ev.LEDGER_PATH
    snap = {}

    def local_b(symbol, interval, limit=1000):
        if interval != "5m":
            raise RuntimeError("BENCHMARK6_REQUIRES_5M")
        return bars[symbol]

    def cached_s(symbol, authority):
        if symbol not in snap:
            snap[symbol] = orig_s(symbol, authority)
        return snap[symbol]

    mode = {"name": "parent"}

    def wrapped_pf(module, strategy_id):
        compute, build = orig_pf(module, strategy_id)

        def cw(bs, *, symbol, now_ts_ms, config):
            f = compute(bs, symbol=symbol, now_ts_ms=now_ts_ms, config=config)
            key = (symbol, int(getattr(f, "signal_ts")))
            v = getattr(f, "values", {}) or {}
            a = float(getattr(f, "atr", 0) or 0)
            m = {}
            if sid == "ema_ribbon_scalp" and a > 0:
                closes = [float(b["close"]) for b in bs]
                e8 = ema(closes, 8)[-1]
                e21 = ema(closes, 21)[-1]
                e55 = ema(closes, 55)[-1]
                m = {
                    "separation_atr": (abs(e8 - e21) + abs(e21 - e55)) / a,
                    "dist_e21_atr": float(v.get("dist_e21_atr") or 0),
                }
            elif sid == "session_bias" and a > 0:
                vv = [float(b.get("volume") or 0) for b in bs[-51:-1]]
                vm = sum(vv) / len(vv) if vv else 0
                last = bs[-1]
                m = {
                    "volume_ratio": float(last.get("volume") or 0) / max(vm, 1e-12),
                    "range_atr": (float(last["high"]) - float(last["low"])) / a,
                }
            elif sid == "sr_levels" and a > 0:
                side = str(getattr(f, "side", "flat"))
                level = float(
                    v.get("prior_hi")
                    if side == "long"
                    else v.get("prior_lo") if side == "short" else getattr(f, "close")
                )
                m = {
                    "level_distance_atr": abs(float(getattr(f, "close")) - level) / a,
                    "relative_volume": float(v.get("relative_volume") or 0),
                }
            meta[key] = m
            return f

        def bw(feature, **kw):
            intent = build(feature, **kw)
            if bool(getattr(intent, "no_trade")):
                return intent
            key = (str(getattr(feature, "symbol")), int(getattr(feature, "signal_ts")))
            ok = True
            reason = ""
            if sid in MICRO3:
                x = micro.get(key)
                avail = bool(
                    x
                    and int(x.get("depth_messages") or 0) > 0
                    and int(x.get("trade_messages") or 0) > 0
                )
                if not avail:
                    ok = False
                    reason = "MICROSTRUCTURE_OBSERVATION_REQUIRED"
                elif mode["name"] == "child" and not micro_ok(
                    sid, str(getattr(intent, "side")), x
                ):
                    ok = False
                    reason = "BENCHMARK_FLOW_DEPTH_CONFIRMATION_FAIL"
            elif mode["name"] == "child":
                m = meta.get(key, {})
                if sid == "ema_ribbon_scalp":
                    ok = bool(
                        m.get("separation_atr", 0) >= 0.25
                        and m.get("dist_e21_atr", 99) <= 0.80
                    )
                    reason = "BENCHMARK_RIBBON_STRUCTURE_CHASE_FAIL"
                elif sid == "session_bias":
                    ok = bool(
                        m.get("volume_ratio", 0) >= 1.0
                        and m.get("range_atr", 0) >= 0.80
                    )
                    reason = "BENCHMARK_LIQUIDITY_VOLATILITY_REGIME_FAIL"
                elif sid == "sr_levels":
                    ok = bool(m.get("level_distance_atr", 99) <= 0.80)
                    reason = "BENCHMARK_LEVEL_EXTENSION_FAIL"
            if ok:
                return intent
            return replace(
                intent,
                no_trade=True,
                regime=str(getattr(intent, "regime")) + "_BENCHMARK_REJECT",
                reason_codes=tuple(getattr(intent, "reason_codes", ())) + (reason,),
            )

        return cw, bw

    ev.policy_functions = wrapped_pf
    ev.fetch_bars = local_b
    ev.fetch_execution_snapshot = cached_s
    try:
        with tempfile.TemporaryDirectory(prefix="bench6_") as td:
            lp = Path(td) / "ledger.json"
            lp.write_text(json.dumps(ledger))
            ev.LEDGER_PATH = lp
            receipts = {}
            for name in ("parent", "child"):
                mode["name"] = name
                out = args.out_dir / f"{name}.json"
                prior = list(sys.argv)
                sys.argv = [
                    "bench6",
                    "--strategy-id",
                    sid,
                    "--symbols",
                    ",".join(symbols),
                    "--out",
                    str(out),
                    "--timeframe-ms",
                    "300000",
                ]
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        ev.main()
                finally:
                    sys.argv = prior
                receipts[name] = json.loads(out.read_text())
    finally:
        ev.policy_functions = orig_pf
        ev.fetch_bars = orig_b
        ev.fetch_execution_snapshot = orig_s
        ev.LEDGER_PATH = orig_l
    p0, c0 = receipts["parent"], receipts["child"]
    pm, cm = metrics(p0), metrics(c0)
    ps, cs = split(p0), split(c0)
    report = {
        "schema": "zel.a1.benchmark6.transfer.replay.v1",
        "strategy_id": sid,
        "benchmark_transfer": {
            "liquidity_sweep": "L2 flow sign + bid/ask depth or imbalance recovery after sweep/reclaim",
            "scalp_snap": "aggressive-flow reversal + opposite depth recovery after failed impulse",
            "vol_spike_fade": "trade-flow continuation failure + book-imbalance recovery before fade",
            "ema_ribbon_scalp": "EMA order+separation state, pullback/reclaim retained, extended-ribbon chase veto",
            "session_bias": "session remains context only; require observed liquidity+volatility expansion, not directional clock bias",
            "sr_levels": "prior level+volume confirmation retained; reject overextended break away from reference level",
        }[sid],
        "parent": pm,
        "child": cm,
        "parent_split": ps,
        "child_split": cs,
        "symbols": list(symbols),
        "microstructure_observed_only": sid in MICRO3,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    (args.out_dir / "REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print("BENCH6_RESULT=" + json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
