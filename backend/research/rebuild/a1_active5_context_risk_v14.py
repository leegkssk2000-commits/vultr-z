from __future__ import annotations
import json
from pathlib import Path
from statistics import mean
from backend.research.rebuild import a1_active5_market_context_diag_v13 as ctx
from backend.research.rebuild import a1_active5_lifecycle_overlay_v2 as life
from backend.research.rebuild import a1_active5_market_state_scan_v1 as ms

MODE = "strict_core_plus_strong050_other"


def quant(xs, p):
    a = sorted(xs)
    return a[min(len(a) - 1, max(0, int(round((len(a) - 1) * p))))]


def main():
    bars = life.bars6()
    btc = ms.btc_feature(bars["BTC-USDT"])
    mm = ctx.market_map(bars)
    rows = []
    for sid, path in life.SOURCES.items():
        d = json.loads(path.read_text())
        for t in d.get("trades") or []:
            if not ms.allow(t, btc, MODE, sid):
                continue
            f = ctx.nearest(mm, int(t["signal_ts"]))
            if not f:
                continue
            b = life.BASE_RULE[sid]
            e = life.CANDIDATES["late_scratch"].copy()
            if b.get("stale_bars"):
                e = {
                    "late_mult": 1.0,
                    "late_exit": True,
                    "late_mfe_r": float(b.get("stale_mfe_r", 0.5)),
                    "late_max_close_r": 0.0,
                }
            x = dict(t)
            x["strategy_id"] = sid
            x["net"] = life.simulate(t, bars[str(t["symbol"])], b, e)
            x["ctx"] = f
            rows.append(x)
    rows = sorted(
        rows, key=lambda x: (int(x["exit_ts"]), str(x["symbol"]), x["strategy_id"])
    )
    cut = int(len(rows) * 0.60)
    train = rows[:cut]
    cq50 = quant([float(x["ctx"]["corr24"]) for x in train], 0.50)
    cq75 = quant([float(x["ctx"]["corr24"]) for x in train], 0.75)
    dq50 = quant([float(x["ctx"]["disp24"]) for x in train], 0.50)
    rules = {
        "base": {},
        "corrmid50": {"corr": 0.50},
        "corrmid25": {"corr": 0.25},
        "disphi50": {"disp": 0.50},
        "combo50": {"corr": 0.50, "disp": 0.50},
        "combo25_50": {"corr": 0.25, "disp": 0.50},
    }

    def mult(x, rule):
        m = 1.0
        c = float(x["ctx"]["corr24"])
        d = float(x["ctx"]["disp24"])
        if "corr" in rule and cq50 < c <= cq75:
            m = min(m, float(rule["corr"]))
        if "disp" in rule and d > dq50:
            m = min(m, float(rule["disp"]))
        return m

    def metrics_for(xs):
        return life.metric([float(x["net"]) * float(x["mult"]) for x in xs])

    res = {
        "schema": "zel.a1.active5.context_risk.v14",
        "research_only": True,
        "threshold_source": "first_60pct_only",
        "thresholds": {"corr_q50": cq50, "corr_q75": cq75, "disp_q50": dq50},
        "variants": {},
    }
    for name, rule in rules.items():
        xs = []
        for x in rows:
            y = dict(x)
            y["mult"] = mult(y, rule)
            xs.append(y)
        tr = xs[:cut]
        ho = xs[cut:]
        m = {
            "train60": metrics_for(tr),
            "holdout40": metrics_for(ho),
            "full": metrics_for(xs),
            "avg_multiplier": mean(float(x["mult"]) for x in xs),
            "train_avg_multiplier": mean(float(x["mult"]) for x in tr),
            "holdout_avg_multiplier": mean(float(x["mult"]) for x in ho),
        }
        res["variants"][name] = m
        print("CTX_RISK14", name, json.dumps(m, sort_keys=True), flush=True)
    # Selection is frozen from train only: require >=75% average risk and maximize train PF, tie-break Net.
    eligible = [
        (m["train60"]["PF"] or 0, m["train60"]["Net_bps"], n)
        for n, m in res["variants"].items()
        if m["train_avg_multiplier"] >= 0.75
    ]
    selected = max(eligible)[2]
    res["selected_by_train_only"] = selected
    print(
        "CTX_RISK14_SELECTED",
        selected,
        json.dumps(res["variants"][selected], sort_keys=True),
    )
    out = Path("/home/z/z/runtime/active5_context_risk_v14.json")
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(res, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
