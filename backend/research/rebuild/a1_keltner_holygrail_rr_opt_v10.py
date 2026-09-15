import importlib
import json
from pathlib import Path
from typing import Any

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
sm: Any = importlib.import_module(
    "backend.research.rebuild.benchmark25_donor_state_machine_v2"
)
web6: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_gmma_holygrail_v6"
)
v9: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_holygrail_rearm_v9"
)
TF = 1800000
v9.COST_GATE = 4.5
VARIANTS = {
    "BASE_020_TP2": dict(
        buf=0.20,
        tp=2.0,
        scratch_b=6,
        scratch_mfe=0.45,
        be=None,
        partial=None,
        trail=None,
    ),
    "B015_TP25": dict(
        buf=0.15,
        tp=2.5,
        scratch_b=6,
        scratch_mfe=0.45,
        be=None,
        partial=None,
        trail=None,
    ),
    "B010_TP25": dict(
        buf=0.10,
        tp=2.5,
        scratch_b=5,
        scratch_mfe=0.40,
        be=None,
        partial=None,
        trail=None,
    ),
    "B010_TP30": dict(
        buf=0.10,
        tp=3.0,
        scratch_b=5,
        scratch_mfe=0.40,
        be=None,
        partial=None,
        trail=None,
    ),
    "B005_TP25": dict(
        buf=0.05,
        tp=2.5,
        scratch_b=5,
        scratch_mfe=0.35,
        be=None,
        partial=None,
        trail=None,
    ),
    "B005_TP30": dict(
        buf=0.05,
        tp=3.0,
        scratch_b=5,
        scratch_mfe=0.35,
        be=None,
        partial=None,
        trail=None,
    ),
    "B010_BE1_TP30": dict(
        buf=0.10,
        tp=3.0,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=None,
        trail=None,
    ),
    "B015_BE1_TP30": dict(
        buf=0.15,
        tp=3.0,
        scratch_b=6,
        scratch_mfe=0.45,
        be=1.0,
        partial=None,
        trail=None,
    ),
    "B010_P20_2R_RUN": dict(
        buf=0.10,
        tp=None,
        scratch_b=5,
        scratch_mfe=0.40,
        be=1.0,
        partial=(2.0, 0.20),
        trail=(2.5, 1.0),
    ),
    "B015_P20_2R_RUN": dict(
        buf=0.15,
        tp=None,
        scratch_b=6,
        scratch_mfe=0.45,
        be=1.0,
        partial=(2.0, 0.20),
        trail=(2.5, 1.0),
    ),
}


def metrics(ts):
    m = v2.metrics(ts)
    vals = [float(t["net_bps"]) for t in ts]
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    m["AvgWin_bps"] = sum(wins) / len(wins) if wins else None
    m["AvgLoss_bps"] = sum(losses) / len(losses) if losses else None
    m["Payoff"] = (
        m["AvgWin_bps"] / m["AvgLoss_bps"]
        if m["AvgWin_bps"] and m["AvgLoss_bps"]
        else None
    )
    return m


def sim(sig, x, cost, var):
    i = sig.index
    if i + 1 >= len(x):
        return None, i
    side = 1 if sig.side == "long" else -1
    entry = float(x.iloc[i + 1]["open"])
    atr = max(float(x.iloc[i]["atr"]), 1e-12)
    ref = float(sig.invalidation_ref)
    stop = ref - side * var["buf"] * atr
    if (side == 1 and stop >= entry) or (side == -1 and stop <= entry):
        stop = entry - side * 1.2 * atr
    risk = abs(entry - stop)
    tp = entry + side * var["tp"] * risk if var["tp"] else None
    last = min(len(x) - 1, i + 1 + 24)
    peak = entry
    mfe = 0.0
    rem = 1.0
    parts = []
    partial_done = False
    be_armed = False
    trail = None
    exit_j = last
    reason = "TIMEOUT"
    final = float(x.iloc[last]["close"])
    for j in range(i + 1, last + 1):
        r = x.iloc[j]
        hi = float(r["high"])
        lo = float(r["low"])
        close = float(r["close"])
        active_stop = entry if be_armed else stop
        # adverse first is conservative on ambiguous bars
        if (side == 1 and lo <= active_stop) or (side == -1 and hi >= active_stop):
            final = active_stop
            exit_j = j
            reason = "BE_STOP" if be_armed else "HARD_STOP"
            break
        if trail is not None and (
            (side == 1 and lo <= trail) or (side == -1 and hi >= trail)
        ):
            final = trail
            exit_j = j
            reason = "TRAIL"
            break
        if tp is not None and ((side == 1 and hi >= tp) or (side == -1 and lo <= tp)):
            final = tp
            exit_j = j
            reason = "TARGET"
            break
        fav = (hi - entry) / risk if side == 1 else (entry - lo) / risk
        mfe = max(mfe, fav)
        peak = max(peak, hi) if side == 1 else min(peak, lo)
        if var["be"] and mfe >= var["be"]:
            be_armed = True
        if var["partial"] and not partial_done and mfe >= var["partial"][0]:
            rr, frac = var["partial"]
            px = entry + side * rr * risk
            parts.append(frac * side * (px - entry) / entry * 10000)
            rem -= frac
            partial_done = True
        if var["trail"] and mfe >= var["trail"][0]:
            _, gapr = var["trail"]
            cand = peak - side * gapr * risk
            trail = (
                max(trail if trail is not None else -1e99, cand)
                if side == 1
                else min(trail if trail is not None else 1e99, cand)
            )
        if j - (i + 1) + 1 >= var["scratch_b"] and mfe < var["scratch_mfe"]:
            final = close
            exit_j = j
            reason = "SCRATCH"
            break
    parts.append(rem * side * (final - entry) / entry * 10000)
    gross = sum(parts)
    net = gross - cost
    return {
        "symbol": "",
        "signal_ts": sig.signal_ts,
        "entry_ts": int(x.iloc[i + 1]["ts_ms"]),
        "exit_ts": int(x.iloc[exit_j]["ts_ms"]),
        "side": sig.side,
        "entry": entry,
        "exit": final,
        "gross_bps": gross,
        "cost_bps": cost,
        "net_bps": net,
        "reason": reason,
    }, exit_j


def replay(var, frames, costs, spec):
    trades = []
    for sym in v2.SYMS6:
        x = web6.enrich_web(frames[sym])
        state = web6.WebState()
        i = 121
        while i < len(x) - 1:
            sig = v9.rearm_signal(state, i, x, spec, float(costs[sym]))
            if sig is None:
                i += 1
                continue
            t, ej = sim(sig, x, float(costs[sym]), var)
            if t:
                t["symbol"] = sym
                trades.append(t)
            i = max(i + 1, ej + 1)
    trades = sorted(trades, key=lambda t: (int(t["exit_ts"]), t["symbol"]))
    cut = int(len(trades) * 0.60)
    return trades, metrics(trades), metrics(trades[:cut]), metrics(trades[cut:])


def main():
    allspec = sm.load_spec()
    spall = web6.build_case_spec(allspec, "keltner_trend", TF)
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
    for name, var in VARIANTS.items():
        tr, m, train, hold = replay(var, frames[TF], costs, spec)
        rows[name] = {
            "full": m,
            "train60": train,
            "holdout40": hold,
            "exit_reasons": dict(
                __import__("collections").Counter(t["reason"] for t in tr)
            ),
        }
        print(
            name,
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
    base = rows["BASE_020_TP2"]["full"]
    baseT = int(base["T"])
    eligible = []
    for n, r in rows.items():
        full = r["full"]
        if (
            int(full["T"]) >= int(0.90 * baseT)
            and float(full["Exp_bps_T"] or -1e9) >= float(base["Exp_bps_T"] or -1e9)
            and float(full["PF"] or 0.0) >= float(base["PF"] or 0.0)
            and float(full["Payoff"] or 0.0) > float(base["Payoff"] or 0.0)
        ):
            eligible.append(
                (float(full["Payoff"]), float(full["Exp_bps_T"]), int(full["T"]), n)
            )
    chosen = max(eligible)[-1] if eligible else "BASE_020_TP2"
    out = {
        "schema": "zel.keltner.holygrail.gmma.rr_opt.v10",
        "state": "DEV_RR_OPT_COMPLETE_CONTAMINATED_HISTORY_NOT_OOS",
        "entry_gate": 4.5,
        "selection": "DEV_FULL_HISTORY_RR_IMPROVEMENT_WITH_T_RETENTION_GE_90PCT_AND_NET_PF_NONDEGRADATION",
        "baseline_T": baseT,
        "chosen": chosen,
        "variants": rows,
        "research_only": True,
        "live": "BLOCKED",
    }
    Path("/home/z/z/runtime/keltner_holygrail_rr_opt_v10.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n"
    )
    print("CHOSEN", chosen, json.dumps(rows[chosen], sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
