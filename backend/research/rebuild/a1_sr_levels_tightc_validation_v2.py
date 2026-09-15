from __future__ import annotations
import json
from pathlib import Path
from backend.research.rebuild import a1_benchmark6_architecture_v2 as base
from backend.research.rebuild import a1_benchmark6_architecture_v3 as fast
from backend.research.rebuild import a1_sr_levels_reclaim_focus_v1 as focus


def main():
    data = {s: base.load(s) for s in base.SYMS}
    tr = []
    for s, d in data.items():
        long, short, sm, rr, to = focus.reclaim(d, 1.6, 0.40, 0.20, 2.4)
        tr += fast.sim(s, d, long, short, sm, rr, to)
    tr = sorted(tr, key=lambda x: (int(x["exit_ts"]), str(x["symbol"])))
    m = base.split(tr)
    res = {
        "schema": "zel.a1.sr_levels.tightc.validation.v2",
        "research_only": True,
        "parent_identity": "sr_levels",
        "child": "tight_break_reclaim_C",
        "full": m["full"],
        "train60": m["train60"],
        "holdout40": m["holdout40"],
        "cost_stress": {},
        "thirds": {},
        "leave_one_symbol_out": {},
        "trades": tr,
        "authority": {
            "selection": False,
            "promotion": False,
            "execution": "NONE",
            "order": "BLOCKED",
            "live": "BLOCKED",
        },
    }
    for extra in (2.0, 5.0, 10.0):
        res["cost_stress"][f"plus_{int(extra)}bps_per_T"] = base.metrics(
            [{**x, "net": float(x["net"]) - extra} for x in tr]
        )
    n = len(tr)
    c = (0, n // 3, 2 * n // 3, n)
    for i in range(3):
        res["thirds"][str(i + 1)] = base.metrics(tr[c[i] : c[i + 1]])
    for sym in sorted({x["symbol"] for x in tr}):
        res["leave_one_symbol_out"][sym] = base.metrics(
            [x for x in tr if x["symbol"] != sym]
        )
    out = Path("/home/z/z/runtime/sr_levels_tightc_validation_v2/REPORT.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(
            {k: v for k, v in res.items() if k != "trades"}, indent=2, sort_keys=True
        )
        + "\n"
    )
    print(
        "SR_TIGHTC_V2="
        + json.dumps({k: v for k, v in res.items() if k != "trades"}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
