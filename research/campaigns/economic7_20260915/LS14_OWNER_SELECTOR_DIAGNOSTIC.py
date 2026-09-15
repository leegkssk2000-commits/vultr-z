import importlib
from collections import defaultdict
from typing import Any

import pandas as pd
import numpy as np

v1 = importlib.import_module(
    "backend.research.rebuild.a1_causal_strategy_failover_router_v1"
)
v2 = importlib.import_module(
    "backend.research.rebuild.a1_strategy_specific_failover_router_v2"
)
feat, cutoff, q, lanes, ledger, bars = v2.build_inputs()
state_maps = v1.build_state_maps(lanes, cutoff)
frames = {}
for sym, raw in bars.items():
    d = pd.DataFrame(raw).sort_values("ts_ms").reset_index(drop=True)
    c = d["close"].astype(float)
    d["mom24"] = c / c.shift(24) - 1.0
    frames[sym] = d.set_index("ts_ms")


def quality(row):
    d = frames[str(row["symbol"])]
    idx = d.index[d.index <= int(row["signal_ts"])]
    v = float(d.loc[int(idx[-1]), "mom24"])
    side = 1.0 if str(row.get("side")) == "long" else -1.0
    return side * v if np.isfinite(v) else -1e99


rider = list(lanes["RIDER"])
groups = defaultdict(list)
for row in rider:
    groups[(int(row["signal_ts"]) // 3600000, str(row.get("side")))].append(row)
owner = []
removed = 0
for xs in groups.values():
    if len(xs) == 1:
        owner.append(dict(xs[0]))
        continue
    chosen = max(xs, key=lambda r: (quality(r), str(r["symbol"])))
    item = dict(chosen)
    item["adjusted_bps"] = float(item["net_bps"]) * float(item["current_risk"])
    item["owner_selector"] = "HIGHEST_SIDE_ALIGNED_24H_MOMENTUM"
    item["owner_group_size"] = len(xs)
    owner.append(item)
    removed += len(xs) - 1
new_lanes = {k: (owner if k == "RIDER" else list(v)) for k, v in lanes.items()}
base = []
for rows in new_lanes.values():
    for row in rows:
        item = dict(row)
        item["base_bps"] = float(item["adjusted_bps"])
        base.append(item)
base.sort(key=lambda x: (int(x["signal_ts"]), str(x["lane"])))
trend = v2.rider_trend_alignment([x for x in base if x["lane"] == "RIDER"], bars)
vol = v2.feature_vol_delta3(feat)
gated = v2.apply_strategy_specific_gate(base, state_maps, trend, vol)
out, _ = v1.apply_same_hour_failover(gated, 1.0)
summary = v1.summarize(out, cutoff, "final_bps")
print("owner_rows", len(owner), "removed", removed, "portfolio_T", len(out))
print("full", summary["full"])
print("train", summary["train"])
print("hold", summary["holdout_diagnostic"])
print("months", summary["months_full"])
# longest individual loss streak
ordered = sorted(
    out, key=lambda r: (int(r["exit_ts"]), str(r.get("lane")), str(r.get("symbol")))
)
best: list[dict[str, Any]] = []
cur: list[dict[str, Any]] = []
for row in ordered:
    if float(row["final_bps"]) < 0:
        cur = cur + [row]
        if len(cur) > len(best):
            best = list(cur)
    else:
        cur = []
print(
    "raw_longest",
    len(best),
    "first_exit",
    best[0]["exit_ts"],
    "last_exit",
    best[-1]["exit_ts"],
)
print(
    "raw_longest_lanes",
    [(x["lane"], x.get("symbol"), round(float(x["final_bps"]), 2)) for x in best],
)
print("raw_longest_details")
for row in best:
    print(
        {
            k: row.get(k)
            for k in (
                "lane",
                "strategy",
                "symbol",
                "side",
                "signal_ts",
                "exit_ts",
                "final_bps",
                "regime",
                "vol_state",
                "breadth_state",
                "state_risk",
                "strategy_state_reason",
            )
        }
    )
sq_train = [
    x for x in gated if x["lane"] == "SQUEEZE" and int(x["signal_ts"]) <= cutoff
]
print("squeeze_train_vol_groups")
for label, pred in [
    (
        "HIGH_RISING",
        lambda x: x["vol_state"] == "HIGH" and float(x.get("market_vol_delta3", 0)) > 0,
    ),
    (
        "OTHER",
        lambda x: not (
            x["vol_state"] == "HIGH" and float(x.get("market_vol_delta3", 0)) > 0
        ),
    ),
]:
    xs = [x for x in sq_train if pred(x)]
    vals = [float(x["adjusted_bps"]) for x in xs]
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    print(
        label,
        "T",
        len(xs),
        "net",
        sum(vals),
        "exp",
        sum(vals) / len(xs) if xs else None,
        "PF",
        sum(wins) / sum(losses) if losses else None,
    )
gated_sq = [
    x
    for x in gated
    if not (
        x["lane"] == "SQUEEZE"
        and not (x["vol_state"] == "HIGH" and float(x.get("market_vol_delta3", 0)) > 0)
    )
]
out_sq, _ = v1.apply_same_hour_failover(gated_sq, 1.0)
sq_summary = v1.summarize(out_sq, cutoff, "final_bps")
print("owner_plus_squeeze_high_rising_only")
print("full", sq_summary["full"])
print("train", sq_summary["train"])
print("hold", sq_summary["holdout_diagnostic"])
print("months", sq_summary["months_full"])
print("squeeze_train_by_vol_state")
for state in ("LOW", "MID", "HIGH"):
    xs = [x for x in sq_train if x["vol_state"] == state]
    vals = [float(x["adjusted_bps"]) for x in xs]
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    print(
        state,
        "T",
        len(xs),
        "net",
        sum(vals),
        "exp",
        sum(vals) / len(xs) if xs else None,
        "PF",
        sum(wins) / sum(losses) if losses else None,
    )
gated_sq_high = [
    x for x in gated if not (x["lane"] == "SQUEEZE" and x["vol_state"] != "HIGH")
]
out_sq_high, _ = v1.apply_same_hour_failover(gated_sq_high, 1.0)
sq_high_summary = v1.summarize(out_sq_high, cutoff, "final_bps")
print("owner_plus_squeeze_high_only")
print("full", sq_high_summary["full"])
print("train", sq_high_summary["train"])
print("hold", sq_high_summary["holdout_diagnostic"])
print("months", sq_high_summary["months_full"])
ordered2 = sorted(
    out_sq_high,
    key=lambda r: (int(r["exit_ts"]), str(r.get("lane")), str(r.get("symbol"))),
)
best2: list[dict[str, Any]] = []
cur2: list[dict[str, Any]] = []
for row in ordered2:
    if float(row["final_bps"]) < 0:
        cur2 = cur2 + [row]
        if len(cur2) > len(best2):
            best2 = list(cur2)
    else:
        cur2 = []
print("high_only_longest_details", len(best2))
for row in best2:
    print(
        {
            k: row.get(k)
            for k in (
                "lane",
                "strategy",
                "symbol",
                "side",
                "signal_ts",
                "exit_ts",
                "final_bps",
                "regime",
                "vol_state",
                "breadth_state",
                "state_risk",
                "strategy_state_reason",
            )
        }
    )


def apply_rider_open_exposure_cap(rows, cap=1.0):
    active = {"long": [], "short": []}
    result = []
    for row in sorted(
        rows,
        key=lambda r: (
            int(r["signal_ts"]),
            int(r["exit_ts"]),
            str(r.get("lane")),
            str(r.get("symbol")),
        ),
    ):
        item = dict(row)
        if item["lane"] == "RIDER" and item.get("side") in active:
            side = str(item["side"])
            ts = int(item["signal_ts"])
            active[side] = [(e, w) for e, w in active[side] if e > ts]
            used = sum(w for _, w in active[side])
            raw_net = float(item["net_bps"])
            requested = abs(float(item["final_bps"]) / raw_net) if raw_net else 0.0
            allowed = min(requested, max(0.0, cap - used))
            item["open_exposure_requested"] = requested
            item["open_exposure_allowed"] = allowed
            item["final_bps"] = raw_net * allowed
            if allowed > 0:
                active[side].append((int(item["exit_ts"]), allowed))
        result.append(item)
    return result


cap_rows = apply_rider_open_exposure_cap(out_sq_high, 1.0)
cap_exec = [x for x in cap_rows if abs(float(x["final_bps"])) > 1e-12]
cap_summary = v1.summarize(cap_exec, cutoff, "final_bps")
print("owner_squeeze_high_plus_rider_open_cap1")
print("signalT", len(cap_rows), "executedT", len(cap_exec))
print("full", cap_summary["full"])
print("train", cap_summary["train"])
print("hold", cap_summary["holdout_diagnostic"])
print("months", cap_summary["months_full"])
ordered3 = sorted(
    cap_exec,
    key=lambda r: (int(r["exit_ts"]), str(r.get("lane")), str(r.get("symbol"))),
)
best3: list[dict[str, Any]] = []
cur3: list[dict[str, Any]] = []
for row in ordered3:
    if float(row["final_bps"]) < 0:
        cur3 = cur3 + [row]
        if len(cur3) > len(best3):
            best3 = list(cur3)
    else:
        cur3 = []
print(
    "cap_longest",
    len(best3),
    [(x["lane"], x.get("symbol"), round(float(x["final_bps"]), 2)) for x in best3],
)
orig_base = sorted(
    [dict(x, base_bps=float(x["adjusted_bps"])) for rs in lanes.values() for x in rs],
    key=lambda x: (int(x["signal_ts"]), str(x["lane"])),
)
orig_trend = v2.rider_trend_alignment(
    [x for x in orig_base if x["lane"] == "RIDER"], bars
)
orig_vol = v2.feature_vol_delta3(feat)
orig_gated = v2.apply_strategy_specific_gate(
    orig_base, state_maps, orig_trend, orig_vol
)
orig_high = [
    x for x in orig_gated if not (x["lane"] == "SQUEEZE" and x["vol_state"] != "HIGH")
]
orig_high_out, _ = v1.apply_same_hour_failover(orig_high, 1.0)
orig_high_summary = v1.summarize(orig_high_out, cutoff, "final_bps")
print("squeeze_high_only_without_owner")
print("full", orig_high_summary["full"])
print("train", orig_high_summary["train"])
print("hold", orig_high_summary["holdout_diagnostic"])
