from __future__ import annotations
import gzip
import json
from pathlib import Path
from typing import Any

PARENT = Path("/home/z/z/runtime/benchmark6_transfer_v1")
CACHE = Path("/home/z/z/runtime/three_lane_5m_180d_v2/data")
MICRO = Path("/home/z/z/runtime/benchmark6_micro_5m_v1.jsonl.gz")
SIDS = ("liquidity_sweep", "scalp_snap", "vol_spike_fade")
SYMS = ("BTC-USDT", "ETH-USDT")


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


def load() -> (
    tuple[dict[str, list[dict[str, Any]]], dict[tuple[str, int], dict[str, Any]]]
):
    bars = {}
    for s in SYMS:
        rows = []
        with gzip.open(
            CACHE / f"{s.replace('-','')}_5m.jsonl.gz", "rt", encoding="utf-8"
        ) as f:
            for line in f:
                x = json.loads(line)
                rows.append(
                    {
                        "ts": int(x["timestamp_ms"]),
                        "open": float(x["open"]),
                        "high": float(x["high"]),
                        "low": float(x["low"]),
                        "close": float(x["close"]),
                    }
                )
        bars[s] = rows
    micro = {}
    with gzip.open(MICRO, "rt", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            micro[(x["symbol"], int(x["ts_ms"]))] = x
    return bars, micro


def supportive(sid: str, side: int, x: dict[str, Any], thr: float) -> bool:
    ti = x.get("trade_imbalance")
    imd = x.get("imbalance_delta")
    bid = x.get("bid_change")
    ask = x.get("ask_change")
    if (
        ti is None
        or imd is None
        or int(x.get("trade_messages") or 0) <= 0
        or int(x.get("depth_messages") or 0) <= 0
    ):
        return False
    sf = side * float(ti)
    si = side * float(imd)
    support = (
        (float(bid) if side == 1 else float(ask))
        if (bid if side == 1 else ask) is not None
        else 0.0
    )
    if sid == "liquidity_sweep":
        return sf >= thr and (si > 0 or support > 0)
    if sid == "scalp_snap":
        return sf >= thr and si > 0 and support > 0
    return sf >= -thr / 2 and si > 0


def simulate(
    sid: str,
    t: dict[str, Any],
    bars: list[dict[str, Any]],
    micro: dict[tuple[str, int], dict[str, Any]],
    window: int,
    thr: float,
) -> float | None:
    idx = {b["ts"]: i for i, b in enumerate(bars)}
    i0 = idx.get(int(t["entry_ts"]))
    i1 = idx.get(int(t["exit_ts"]))
    if i0 is None or i1 is None:
        return None
    side = 1 if t["side"] == "long" else -1
    orig = float(t["entry"])
    sl = (t.get("intent_geometry") or {}).get("sl")
    if sl is None:
        return None
    rpx = abs(orig - float(sl))
    confirm = None
    for k in range(i0, min(i1, i0 + window - 1) + 1):
        x = micro.get((str(t["symbol"]), bars[k]["ts"]))
        if x is not None and supportive(sid, side, x, thr):
            confirm = k
            break
    if confirm is None:
        return None
    ent_i = confirm + 1
    if ent_i > i1:
        return None
    entry = float(bars[ent_i]["open"])
    stop = entry - side * rpx
    px = None
    for j in range(ent_i, i1 + 1):
        lo = float(bars[j]["low"])
        hi = float(bars[j]["high"])
        if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
            px = stop
            break
    if px is None:
        px = float(bars[i1]["close"])
    return side * (px - entry) / entry * 10000 - float(t.get("realized_cost_bps") or 0)


def split(vals: list[float]) -> dict[str, Any]:
    c = int(len(vals) * 0.6)
    return {
        "full": metric(vals),
        "train60": metric(vals[:c]),
        "holdout40": metric(vals[c:]),
    }


def main() -> int:
    bars, micro = load()
    res = {
        "schema": "zel.a1.benchmark6.delayed_confirmation.v3",
        "research_only": True,
        "strategies": {},
    }
    for sid in SIDS:
        d = json.loads((PARENT / sid / "parent.json").read_text())
        tr = sorted(
            d.get("trades") or [], key=lambda x: (int(x["exit_ts"]), str(x["symbol"]))
        )
        item = {"parent": split([float(t["net_bps"]) for t in tr]), "variants": {}}
        for window, thr in ((1, 0.15), (2, 0.15), (2, 0.25), (3, 0.15)):
            vals = []
            kept = []
            for t in tr:
                v = simulate(sid, t, bars[str(t["symbol"])], micro, window, thr)
                if v is not None:
                    vals.append(v)
                    kept.append(t)
            name = f"w{window}_thr{thr:.2f}"
            m = split(vals)
            m["retention"] = len(vals) / len(tr) if tr else 0
            m["kept_T"] = len(vals)
            item["variants"][name] = m
            print("DELAY_ROW", sid, name, json.dumps(m, sort_keys=True), flush=True)
        res["strategies"][sid] = item
    out = Path("/home/z/z/runtime/benchmark6_delayed_confirmation_v3/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
