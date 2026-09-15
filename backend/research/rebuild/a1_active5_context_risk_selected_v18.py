from __future__ import annotations
import json
from pathlib import Path
from statistics import mean
from backend.research.rebuild import a1_active5_market_context_diag_v13 as ctx
from backend.research.rebuild import a1_active5_lifecycle_overlay_v2 as life
from backend.research.rebuild import a1_active5_market_state_scan_v1 as ms

MODE = "strict_core_plus_strong050_other"
RISK = 0.50


def q(xs, p):
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
    threshold = q([float(x["ctx"]["disp24"]) for x in rows[:cut]], 0.50)
    for x in rows:
        x["risk_mult"] = RISK if float(x["ctx"]["disp24"]) > threshold else 1.0
        x["scaled"] = float(x["net"]) * x["risk_mult"]

    def met(xs):
        return life.metric([float(x["scaled"]) for x in xs])

    n = len(rows)
    c = (0, n // 3, 2 * n // 3, n)
    res = {
        "schema": "zel.a1.active5.context_risk_selected.v18",
        "research_only": True,
        "selection_provenance": "selected_by_train_only_in_v14_before_holdout_read",
        "feature": "six_symbol_24h_return_dispersion",
        "threshold": threshold,
        "risk_multiplier_above_threshold": RISK,
        "avg_risk_multiplier": mean(float(x["risk_mult"]) for x in rows),
        "full": met(rows),
        "train60": met(rows[:cut]),
        "holdout40": met(rows[cut:]),
        "thirds": {},
        "cost_stress": {},
        "leave_one_symbol_out": {},
        "authority": {
            "selection": False,
            "promotion": False,
            "execution": "NONE",
            "order": "BLOCKED",
            "live": "BLOCKED",
        },
    }
    for i in range(3):
        res["thirds"][str(i + 1)] = met(rows[c[i] : c[i + 1]])
    for extra in (2.0, 5.0, 10.0):
        res["cost_stress"][f"plus_{int(extra)}bps_per_T"] = life.metric(
            [float(x["scaled"]) - extra * float(x["risk_mult"]) for x in rows]
        )
    for sym in sorted({x["symbol"] for x in rows}):
        res["leave_one_symbol_out"][sym] = met([x for x in rows if x["symbol"] != sym])
    out = Path("/home/z/z/runtime/active5_context_risk_selected_v18/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(res, indent=2, sort_keys=True) + "\n"
    )
    print("ACTIVE5_V18=" + json.dumps(res, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
