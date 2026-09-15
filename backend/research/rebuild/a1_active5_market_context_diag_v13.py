from __future__ import annotations
import json
from pathlib import Path
from statistics import mean, pstdev
from backend.research.rebuild import a1_active5_lifecycle_overlay_v2 as life
from backend.research.rebuild import a1_active5_market_state_scan_v1 as ms
from backend.research.rebuild.policy_kernel_v1 import ema

MODE = "strict_core_plus_strong050_other"


def market_map(bars):
    syms = list(bars)
    by = {s: {int(x["ts_ms"]): i for i, x in enumerate(v)} for s, v in bars.items()}
    btc = bars["BTC-USDT"]
    out = {}
    for i, b in enumerate(btc):
        if i < 72:
            continue
        t = int(b["ts_ms"])
        r1 = []
        r24 = []
        trend = []
        rets = []
        ok = True
        for s in syms:
            j = by[s].get(t)
            if j is None or j < 72:
                ok = False
                break
            v = bars[s]
            cl = [float(x["close"]) for x in v[j - 72 : j + 1]]
            rr = [cl[k] / cl[k - 1] - 1 for k in range(1, len(cl))]
            r1.append(rr[-1])
            r24.append(cl[-1] / cl[-25] - 1)
            e = ema(cl, 50)
            trend.append(
                1
                if cl[-1] > e[-1] and e[-1] > e[-2]
                else (-1 if cl[-1] < e[-1] and e[-1] < e[-2] else 0)
            )
            rets.append(rr[-24:])
        if not ok:
            continue
        bc = [float(x["close"]) for x in btc[i - 72 : i + 1]]
        br = [bc[k] / bc[k - 1] - 1 for k in range(1, len(bc))]
        rv12 = (sum(x * x for x in br[-12:]) / 12) ** 0.5
        rv72 = (sum(x * x for x in br[-72:]) / 72) ** 0.5
        signs = [1 if x > 0 else -1 if x < 0 else 0 for x in br[-12:]]
        flips = sum(1 for a, c in zip(signs[:-1], signs[1:]) if a * c < 0) / 11
        er12 = abs(sum(br[-12:])) / max(sum(abs(x) for x in br[-12:]), 1e-12)
        er24 = abs(sum(br[-24:])) / max(sum(abs(x) for x in br[-24:]), 1e-12)
        # mean pairwise corr of six 24h return streams
        cors = []
        for a in range(len(rets)):
            for c in range(a + 1, len(rets)):
                xa, xb = rets[a], rets[c]
                ma, mb = mean(xa), mean(xb)
                sa, sb = pstdev(xa), pstdev(xb)
                if sa > 1e-12 and sb > 1e-12:
                    cors.append(
                        sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
                        / len(xa)
                        / sa
                        / sb
                    )
        out[t] = {
            "rv_ratio": rv12 / max(rv72, 1e-12),
            "flip12": flips,
            "er12": er12,
            "er24": er24,
            "corr24": mean(cors) if cors else 0.0,
            "disp24": pstdev(r24),
            "breadth_abs": abs(sum(trend)),
            "breadth_dir": sum(trend),
        }
    return out


def nearest(m, t):
    k = max((x for x in m if x <= t), default=None)
    return m.get(k) if k is not None else None


def q(xs, p):
    if not xs:
        return None
    a = sorted(xs)
    return a[min(len(a) - 1, max(0, int(round((len(a) - 1) * p))))]


def main():
    bars = life.bars6()
    btcgate = ms.btc_feature(bars["BTC-USDT"])
    mm = market_map(bars)
    rows = []
    for sid, path in life.SOURCES.items():
        d = json.loads(path.read_text())
        for t in d.get("trades") or []:
            if not ms.allow(t, btcgate, MODE, sid):
                continue
            f = nearest(mm, int(t["signal_ts"]))
            if not f:
                continue
            x = dict(t)
            x["strategy_id"] = sid
            x["v8_net"] = life.simulate(
                t,
                bars[str(t["symbol"])],
                life.BASE_RULE[sid],
                (
                    {
                        "late_mult": 1.0,
                        "late_exit": True,
                        "late_mfe_r": float(
                            life.BASE_RULE[sid].get("stale_mfe_r", 0.5)
                        ),
                        "late_max_close_r": 0.0,
                    }
                    if life.BASE_RULE[sid].get("stale_bars")
                    else life.CANDIDATES["late_scratch"]
                ),
            )
            x["ctx"] = f
            rows.append(x)
    rows = sorted(
        rows, key=lambda x: (int(x["exit_ts"]), str(x["symbol"]), x["strategy_id"])
    )
    n = len(rows)
    cuts = (0, n // 3, 2 * n // 3, n)
    features = list(next(iter(mm.values())).keys())
    res = {
        "schema": "zel.a1.active5.market_context_diag.v13",
        "thirds": {},
        "feature_bins": {},
    }
    for j in range(3):
        xs = rows[cuts[j] : cuts[j + 1]]
        item = {
            "metrics": life.metric([float(x["v8_net"]) for x in xs]),
            "features": {},
        }
        for f in features:
            a = [float(x["ctx"][f]) for x in xs]
            item["features"][f] = {
                "mean": mean(a),
                "q25": q(a, 0.25),
                "q50": q(a, 0.5),
                "q75": q(a, 0.75),
            }
        res["thirds"][str(j + 1)] = item
    # fixed quantile bins from chronological first 60% only, then read economics in all data
    train = rows[: int(n * 0.6)]
    for f in features:
        vals = [float(x["ctx"][f]) for x in train]
        cutsf = [q(vals, p) for p in (0.25, 0.5, 0.75)]
        bins = []
        lo = -1e99
        for hi in cutsf + [1e99]:
            xs = [x for x in rows if lo < float(x["ctx"][f]) <= hi]
            bins.append(
                {
                    "lo": None if lo < -1e90 else lo,
                    "hi": None if hi > 1e90 else hi,
                    "metrics": life.metric([float(x["v8_net"]) for x in xs]),
                }
            )
            lo = hi
        res["feature_bins"][f] = bins
    out = Path("/home/z/z/runtime/active5_market_context_diag_v13.json")
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(res, indent=2, sort_keys=True) + "\n"
    )
    print("CTX13_THIRDS=" + json.dumps(res["thirds"], sort_keys=True))
    print("CTX13_BINS=" + json.dumps(res["feature_bins"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
