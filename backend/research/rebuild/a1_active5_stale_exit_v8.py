from __future__ import annotations
import json
import copy
from pathlib import Path
from backend.research.rebuild import a1_active5_lifecycle_overlay_v2 as life
from backend.research.rebuild import a1_active5_market_state_scan_v1 as ms

MODE = "strict_core_plus_strong050_other"
VARIANTS = ("base", "stale50", "stale75", "stale_full0", "stale_full_n25")


def thirds(rows, vals):
    n = len(rows)
    c = (0, n // 3, 2 * n // 3, n)
    return {str(i + 1): life.metric(vals[c[i] : c[i + 1]]) for i in range(3)}


def rule_for(sid, name):
    b = copy.deepcopy(life.BASE_RULE[sid])
    extra = life.CANDIDATES["late_scratch"].copy()
    if name == "stale50" and b.get("stale_frac") is not None:
        b["stale_frac"] = 0.50
    if name == "stale75" and b.get("stale_frac") is not None:
        b["stale_frac"] = 0.75
    if name in ("stale_full0", "stale_full_n25") and b.get("stale_bars"):
        extra = {
            "late_mult": 1.0,
            "late_exit": True,
            "late_mfe_r": float(b.get("stale_mfe_r", 0.5)),
            "late_max_close_r": 0.0 if name == "stale_full0" else -0.25,
        }
    return b, extra


def main():
    bars = life.bars6()
    btc = ms.btc_feature(bars["BTC-USDT"])
    raw = []
    for sid, path in life.SOURCES.items():
        d = json.loads(path.read_text())
        for t in sorted(
            d.get("trades") or [], key=lambda x: (int(x["exit_ts"]), str(x["symbol"]))
        ):
            if ms.allow(t, btc, MODE, sid):
                x = dict(t)
                x["strategy_id"] = sid
                raw.append(x)
    raw = sorted(
        raw, key=lambda x: (int(x["exit_ts"]), str(x["symbol"]), x["strategy_id"])
    )
    res = {
        "schema": "zel.a1.active5.stale_exit.v8",
        "research_only": True,
        "variants": {},
    }
    for name in VARIANTS:
        vals = []
        for t in raw:
            b, e = rule_for(str(t["strategy_id"]), name)
            vals.append(life.simulate(t, bars[str(t["symbol"])], b, e))
        res["variants"][name] = {"full": life.metric(vals), "thirds": thirds(raw, vals)}
        print(
            "STALE8",
            name,
            json.dumps(res["variants"][name], sort_keys=True),
            flush=True,
        )
    out = Path("/home/z/z/runtime/active5_stale_exit_v8.json")
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(res, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
