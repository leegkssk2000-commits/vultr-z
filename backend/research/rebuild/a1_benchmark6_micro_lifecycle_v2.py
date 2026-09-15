from __future__ import annotations
import gzip
import json
from pathlib import Path
from typing import Any
from backend.research.rebuild import a1_exact25_generic_evaluator_three_lane_v1 as ev

ROOT = Path("/home/z/z/runtime/benchmark6_transfer_v1")
MICRO = Path("/home/z/z/runtime/benchmark6_micro_5m_v1.jsonl.gz")
SIDS = ("liquidity_sweep", "scalp_snap", "vol_spike_fade")
VARIANTS = {
    "scratch2_strong": {
        "bars": 2,
        "flow": 0.25,
        "imb": 0.08,
        "mfe": 0.25,
        "mode": "scratch",
    },
    "reduce50_2_strong": {
        "bars": 2,
        "flow": 0.25,
        "imb": 0.08,
        "mfe": 0.25,
        "mode": "reduce",
        "frac": 0.50,
    },
    "scratch3_moderate": {
        "bars": 3,
        "flow": 0.15,
        "imb": 0.04,
        "mfe": 0.35,
        "mode": "scratch",
    },
    "reduce50_then_scratch3": {
        "bars": 3,
        "flow": 0.18,
        "imb": 0.05,
        "mfe": 0.30,
        "mode": "two_stage",
        "frac": 0.50,
    },
}


def metric(vals: list[float]) -> dict[str, Any]:
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
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": sum(w) / sum(losses) if losses else None,
        "DD_bps": dd,
    }


def load_micro() -> dict[tuple[str, int], dict[str, Any]]:
    out = {}
    with gzip.open(MICRO, "rt", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            out[(x["symbol"], int(x["ts_ms"]))] = x
    return out


def adverse(x: dict[str, Any], side: int, flow_thr: float, imb_thr: float) -> bool:
    ti = x.get("trade_imbalance")
    imd = x.get("imbalance_delta")
    if ti is None or imd is None:
        return False
    if int(x.get("trade_messages") or 0) <= 0 or int(x.get("depth_messages") or 0) <= 0:
        return False
    sf = side * float(ti)
    si = side * float(imd)
    bid = x.get("bid_change")
    ask = x.get("ask_change")
    support = (
        (float(bid) if side == 1 else float(ask))
        if (bid if side == 1 else ask) is not None
        else 0.0
    )
    oppose = (
        (float(ask) if side == 1 else float(bid))
        if (ask if side == 1 else bid) is not None
        else 0.0
    )
    return sf <= -flow_thr and (si <= -imb_thr or support < 0 or oppose > 0)


def simulate(
    t: dict[str, Any],
    bars: list[dict[str, Any]],
    micro: dict[tuple[str, int], dict[str, Any]],
    rule: dict[str, Any],
) -> tuple[float, bool]:
    entry = float(t["entry"])
    side = 1 if t["side"] == "long" else -1
    sl = (t.get("intent_geometry") or {}).get("sl")
    if sl is None:
        return float(t["net_bps"]), False
    rpx = abs(entry - float(sl))
    idx = {int(b["ts_ms"]): i for i, b in enumerate(bars)}
    i0 = idx.get(int(t["entry_ts"]))
    i1 = idx.get(int(t["exit_ts"]))
    if rpx <= 0 or i0 is None or i1 is None:
        return float(t["net_bps"]), False
    rem = 1.0
    parts = []
    mfe = 0.0
    triggered = False
    stage = 0
    for k in range(i0, min(i1, i0 + int(rule["bars"]) - 1) + 1):
        b = bars[k]
        hi = float(b["high"])
        lo = float(b["low"])
        cl = float(b["close"])
        fav = ((hi - entry) if side == 1 else (entry - lo)) / rpx
        mfe = max(mfe, fav)
        x = micro.get((str(t["symbol"]), int(b["ts_ms"])))
        if x is None or mfe >= float(rule["mfe"]):
            continue
        if not adverse(x, side, float(rule["flow"]), float(rule["imb"])):
            continue
        triggered = True
        if rule["mode"] == "scratch":
            parts.append(rem * side * (cl - entry) / entry * 10000)
            rem = 0
            break
        if rule["mode"] == "reduce" and stage == 0:
            f = min(rem, float(rule["frac"]) * rem)
            parts.append(f * side * (cl - entry) / entry * 10000)
            rem -= f
            stage = 1
        elif rule["mode"] == "two_stage":
            if stage == 0:
                f = min(rem, float(rule["frac"]) * rem)
                parts.append(f * side * (cl - entry) / entry * 10000)
                rem -= f
                stage = 1
            elif stage == 1:
                parts.append(rem * side * (cl - entry) / entry * 10000)
                rem = 0
                stage = 2
                break
    if rem > 0:
        parts.append(rem * side * (float(t["exit"]) - entry) / entry * 10000)
    return sum(parts) - float(t.get("realized_cost_bps") or 0), triggered


def split(rows: list[dict[str, Any]], vals: list[float]) -> dict[str, Any]:
    cut = int(len(rows) * 0.60)
    return {
        "full": metric(vals),
        "train60": metric(vals[:cut]),
        "holdout40": metric(vals[cut:]),
    }


def main() -> int:
    micro = load_micro()
    bars = {s: ev.fetch_bars(s, "5m", 1000) for s in ["BTC-USDT", "ETH-USDT"]}
    # Replace short API window with full shared-cache rows used by the parent replay.
    import gzip as _gz

    for s in bars:
        p = (
            Path("/home/z/z/runtime/three_lane_5m_180d_v2/data")
            / f"{s.replace('-','')}_5m.jsonl.gz"
        )
        rows = []
        with _gz.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                x = json.loads(line)
                rows.append(
                    {
                        "ts_ms": int(x["timestamp_ms"]),
                        "open": float(x["open"]),
                        "high": float(x["high"]),
                        "low": float(x["low"]),
                        "close": float(x["close"]),
                        "volume": float(x["volume"]),
                    }
                )
        bars[s] = rows
    res = {
        "schema": "zel.a1.benchmark6.micro_lifecycle.v2",
        "research_only": True,
        "strategies": {},
    }
    for sid in SIDS:
        d = json.loads((ROOT / sid / "parent.json").read_text())
        tr = sorted(
            d.get("trades") or [], key=lambda x: (int(x["exit_ts"]), str(x["symbol"]))
        )
        base = [float(t["net_bps"]) for t in tr]
        item = {"baseline": split(tr, base), "variants": {}}
        for name, rule in VARIANTS.items():
            vals = []
            n = 0
            for t in tr:
                v, hit = simulate(t, bars[str(t["symbol"])], micro, rule)
                vals.append(v)
                n += int(hit)
            m = split(tr, vals)
            b = item["baseline"]
            m["triggered"] = n
            m["pass"] = bool(
                m["full"]["Net_bps"] >= b["full"]["Net_bps"]
                and (m["full"]["PF"] or 0) >= (b["full"]["PF"] or 0)
                and m["full"]["DD_bps"] <= b["full"]["DD_bps"]
                and m["holdout40"]["Net_bps"] >= b["holdout40"]["Net_bps"]
            )
            item["variants"][name] = m
        res["strategies"][sid] = item
    out = Path("/home/z/z/runtime/benchmark6_micro_lifecycle_v2/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    for sid, x in res["strategies"].items():
        print("MICRO_LIFE_BASE", sid, json.dumps(x["baseline"], sort_keys=True))
        for n, m in x["variants"].items():
            print(
                "MICRO_LIFE_ROW",
                sid,
                n,
                json.dumps(
                    {
                        "full": m["full"],
                        "holdout40": m["holdout40"],
                        "triggered": m["triggered"],
                        "pass": m["pass"],
                    },
                    sort_keys=True,
                ),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
