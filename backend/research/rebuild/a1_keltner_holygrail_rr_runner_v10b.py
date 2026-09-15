import importlib
import json

rr = importlib.import_module("backend.research.rebuild.a1_keltner_holygrail_rr_opt_v10")
v2 = rr.v2
sm = rr.sm
web6 = rr.web6
vars = {
    "P10_2R_TR3_G125": dict(
        buf=0.10,
        tp=None,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=(2.0, 0.10),
        trail=(3.0, 1.25),
    ),
    "P15_2R_TR3_G125": dict(
        buf=0.10,
        tp=None,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=(2.0, 0.15),
        trail=(3.0, 1.25),
    ),
    "P20_2R_TR3_G125": dict(
        buf=0.10,
        tp=None,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=(2.0, 0.20),
        trail=(3.0, 1.25),
    ),
    "P15_2R_TR3_G150": dict(
        buf=0.10,
        tp=None,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=(2.0, 0.15),
        trail=(3.0, 1.50),
    ),
    "P15_25R_TR3_G125": dict(
        buf=0.10,
        tp=None,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=(2.5, 0.15),
        trail=(3.0, 1.25),
    ),
    "NOP_TR25_G125": dict(
        buf=0.10,
        tp=None,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=None,
        trail=(2.5, 1.25),
    ),
    "NOP_TR3_G150": dict(
        buf=0.10,
        tp=None,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=None,
        trail=(3.0, 1.50),
    ),
}
allspec = sm.load_spec()
spall = web6.build_case_spec(allspec, "keltner_trend", rr.TF)
frames, _ = v2.prepare_frames(spall)
spec = spall["children"]["keltner_trend"]
costs = {
    "BTC-USDT": 14.0,
    "ETH-USDT": 14.0,
    "SOL-USDT": 14.0,
    "XRP-USDT": 15.058813437188807,
    "LINK-USDT": 15.561366061899777,
    "DOGE-USDT": 15.363228169680506,
}
rows = {}
for n, v in vars.items():
    tr, m, train, hold = rr.replay(v, frames[rr.TF], costs, spec)
    rows[n] = {"full": m, "train60": train, "holdout40": hold}
    print(
        n,
        "T",
        m["T"],
        "WR",
        round(m["WR"] * 100, 1),
        "Net/T",
        round(m["Exp_bps_T"], 2),
        "PF",
        round(m["PF"], 3),
        "Payoff",
        round(m["Payoff"], 2),
        "H",
        hold["T"],
        round(hold["Exp_bps_T"], 2),
        round(hold["PF"], 3),
        round(hold["Payoff"], 2),
        flush=True,
    )
open("/home/z/z/runtime/keltner_rr_runner_bracket_v10b.json", "w").write(
    json.dumps(
        {
            "schema": "zel.keltner.rr.runner_bracket.v10b",
            "entry_gate": 4.5,
            "frozen_costs": costs,
            "rows": rows,
            "research_only": True,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
