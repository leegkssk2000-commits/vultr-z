from __future__ import annotations

import importlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore[import-not-found]

sp: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic7_improvement_sprint_v1"
)
ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "causal_strategy_failover_router_v1.json"
REPO_OUT = Path(__file__).with_name("causal_strategy_failover_router_v1_results.json")
BOOST_CAPS = (0.25, 0.50, 1.00)


def month(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m")


def metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda x: (int(x["exit_ts"]), str(x["lane"])))
    vals = [float(x[key]) for x in ordered]
    wins, losses = [v for v in vals if v > 0], [-v for v in vals if v < 0]
    eq = peak = dd = 0.0
    streak = max_streak = 0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if value < 0 else 0
        max_streak = max(max_streak, streak)
    return {
        "T": len(vals),
        "Net_bps": sum(vals),
        "Exp_bps_T": sum(vals) / len(vals) if vals else None,
        "PF": sum(wins) / sum(losses) if losses else None,
        "DD_bps": dd,
        "MaxLossStreak": max_streak,
    }


def monthly(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for row in rows:
        out[month(int(row["exit_ts"]))] += float(row[key])
    return dict(sorted(out.items()))


def build_lane_rows() -> (
    tuple[Any, int, dict[str, float], dict[str, list[dict[str, Any]]], dict[str, Any]]
):
    feat, cutoff, q, strategies, ledger, bars = sp.build_inputs()
    k_lane, k_rows = sp.keltner_lane(strategies, cutoff)
    r_lane, r_rows = sp.rider_lane(strategies, ledger, bars, cutoff)
    s_lane, s_rows = sp.squeeze_lane(strategies, cutoff)
    m_lane, m_rows = sp.mean_reversion_lane(cutoff)
    b_lane = sp.break_lane(strategies, ledger, bars, cutoff)
    st_lane = sp.supertrend_lane(strategies, cutoff)
    micro_lane = sp.micro_lane()
    lanes = {
        "KELTNER": k_rows,
        "RIDER": r_rows,
        "SQUEEZE": s_rows,
        "MR": m_rows,
    }
    standby = {
        "BREAK": b_lane,
        "SUPERTREND": st_lane,
        "MICRO": micro_lane,
    }
    return feat, cutoff, q, lanes, standby


def attach_state(
    feat: Any,
    q: dict[str, float],
    lanes: dict[str, list[dict[str, Any]]],
) -> None:
    ts = feat.ts_ms.to_numpy(dtype=np.int64)
    for lane, rows in lanes.items():
        for row in rows:
            pos = int(np.searchsorted(ts, int(row["signal_ts"]), side="right") - 1)
            if pos < 0:
                raise RuntimeError(
                    f"NO_CAUSAL_FEATURE_CONTEXT:{lane}:{row['signal_ts']}"
                )
            f = feat.iloc[pos]
            row["lane"] = lane
            row["regime"] = str(row.get("regime") or sp.mx.regime(f, q))
            row["vol_state"] = (
                "LOW"
                if float(f.vol_ratio) <= q["vol_q25"]
                else ("HIGH" if float(f.vol_ratio) >= q["vol_q67"] else "MID")
            )
            breadth = abs(float(f.breadth))
            row["breadth_state"] = (
                "B6" if breadth >= 6 else ("B4" if breadth >= 4 else "MIXED")
            )
            row["disp_state"] = (
                "HIGH" if float(f.dispersion24) >= q["disp_q67"] else "LOW"
            )


def simple_metrics(rows: list[dict[str, Any]]) -> tuple[int, float, float | None]:
    vals = [float(x["adjusted_bps"]) for x in rows]
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    return (
        len(vals),
        sum(vals) / len(vals) if vals else 0.0,
        sum(wins) / sum(losses) if losses else None,
    )


def build_state_maps(
    lanes: dict[str, list[dict[str, Any]]], cutoff: int
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    levels = (
        ("regime", "vol_state", "breadth_state"),
        ("regime", "vol_state"),
        ("regime",),
    )
    for lane, rows in lanes.items():
        train = [x for x in rows if int(x["signal_ts"]) <= cutoff]
        min_n = max(4, int(math.ceil(len(train) * 0.08)))
        level_rows = []
        for columns in levels:
            groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
            for row in train:
                groups[tuple(str(row[c]) for c in columns)].append(row)
            states: dict[str, Any] = {}
            for key, xs in groups.items():
                n, exp, pf = simple_metrics(xs)
                if n < min_n:
                    continue
                if exp > 0 and (pf is None or pf > 1.0):
                    risk = 1.0
                    label = "GREEN"
                elif exp < 0 and float(pf or 0.0) < 1.0:
                    risk = 0.25
                    label = "RED"
                else:
                    risk = 0.50
                    label = "AMBER"
                states["|".join(key)] = {
                    "T": n,
                    "Exp_bps_T": exp,
                    "PF": pf,
                    "risk": risk,
                    "label": label,
                }
            level_rows.append({"columns": list(columns), "states": states})
        result[lane] = {"min_train_T": min_n, "levels": level_rows}
    return result


def state_risk(row: dict[str, Any], state_map: dict[str, Any]) -> tuple[float, str]:
    for level in state_map["levels"]:
        key = "|".join(str(row[c]) for c in level["columns"])
        item = level["states"].get(key)
        if item is not None:
            return float(item["risk"]), str(item["label"])
    return 0.50, "AMBER_INSUFFICIENT_EXACT_STATE"


def apply_state_gate(
    rows: list[dict[str, Any]], maps: dict[str, Any]
) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        risk, label = state_risk(row, maps[str(row["lane"])])
        item = dict(row)
        item["state_risk"] = risk
        item["state_label"] = label
        item["routed_bps"] = risk * float(row["adjusted_bps"])
        out.append(item)
    return out


def apply_same_hour_failover(
    rows: list[dict[str, Any]], boost_cap: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["signal_ts"]) // 3_600_000, str(row["lane"]))].append(row)
    by_hour: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for (hour, lane), xs in grouped.items():
        by_hour[hour][lane] = xs
    out: list[dict[str, Any]] = []
    boosted_hours = 0
    receiver_counts: dict[str, int] = defaultdict(int)
    released_total = 0.0
    reallocated_total = 0.0
    for hour, lane_map in by_hour.items():
        lane_risk = {
            lane: min(float(x["state_risk"]) for x in xs)
            for lane, xs in lane_map.items()
        }
        released = sum(max(0.0, 1.0 - risk) for risk in lane_risk.values())
        receivers = [lane for lane, risk in lane_risk.items() if risk >= 0.999]
        extra = {lane: 0.0 for lane in lane_map}
        remaining = released
        for _ in range(4):
            active = [lane for lane in receivers if extra[lane] < boost_cap - 1e-12]
            if not active or remaining <= 1e-12:
                break
            share = remaining / len(active)
            used = 0.0
            for lane in active:
                add = min(share, boost_cap - extra[lane])
                extra[lane] += add
                used += add
            remaining -= used
        allocated = sum(extra.values())
        if allocated > 0:
            boosted_hours += 1
            for lane, value in extra.items():
                if value > 0:
                    receiver_counts[lane] += 1
        released_total += released
        reallocated_total += allocated
        for lane, xs in lane_map.items():
            multiplier = 1.0 + extra[lane]
            for row in xs:
                item = dict(row)
                item["failover_boost"] = multiplier
                item["final_bps"] = float(row["routed_bps"]) * multiplier
                out.append(item)
    return sorted(out, key=lambda x: (int(x["signal_ts"]), str(x["lane"]))), {
        "boosted_hours": boosted_hours,
        "receiver_hour_counts": dict(sorted(receiver_counts.items())),
        "released_lane_risk_units": released_total,
        "reallocated_lane_risk_units": reallocated_total,
    }


def summarize(rows: list[dict[str, Any]], cutoff: int, key: str) -> dict[str, Any]:
    train = [x for x in rows if int(x["signal_ts"]) <= cutoff]
    hold = [x for x in rows if int(x["signal_ts"]) > cutoff]
    return {
        "full": metrics(rows, key),
        "train": metrics(train, key),
        "holdout_diagnostic": metrics(hold, key),
        "months_full": monthly(rows, key),
        "months_train": monthly(train, key),
        "worst_train_month_bps": min(monthly(train, key).values()) if train else None,
    }


def main() -> int:
    feat, cutoff, q, lanes, standby = build_lane_rows()
    attach_state(feat, q, lanes)
    maps = build_state_maps(lanes, cutoff)
    base = sorted(
        [
            dict(x, base_bps=float(x["adjusted_bps"]))
            for xs in lanes.values()
            for x in xs
        ],
        key=lambda x: (int(x["signal_ts"]), str(x["lane"])),
    )
    candidates: dict[str, Any] = {
        "BASE": {"summary": summarize(base, cutoff, "base_bps")}
    }
    gated = apply_state_gate(base, maps)
    candidates["STATE_GATE"] = {"summary": summarize(gated, cutoff, "routed_bps")}
    routed_cache: dict[str, list[dict[str, Any]]] = {}
    for cap in BOOST_CAPS:
        rows, receipt = apply_same_hour_failover(gated, cap)
        name = f"STATE_GATE_FAILOVER_{cap:.2f}"
        routed_cache[name] = rows
        candidates[name] = {
            "summary": summarize(rows, cutoff, "final_bps"),
            "failover_receipt": receipt,
        }
    base_train = candidates["BASE"]["summary"]["train"]
    base_worst = float(candidates["BASE"]["summary"]["worst_train_month_bps"])
    eligible = []
    for name, item in candidates.items():
        if name == "BASE":
            continue
        tr = item["summary"]["train"]
        worst = float(item["summary"]["worst_train_month_bps"])
        if (
            float(tr["Net_bps"]) >= float(base_train["Net_bps"])
            and float(tr["PF"] or 0.0) >= float(base_train["PF"] or 0.0)
            and float(tr["DD_bps"]) <= float(base_train["DD_bps"])
            and worst >= base_worst
        ):
            eligible.append((name, item))
    chosen = max(
        eligible,
        key=lambda pair: (
            float(pair[1]["summary"]["worst_train_month_bps"]),
            float(pair[1]["summary"]["train"]["PF"] or 0.0),
            float(pair[1]["summary"]["train"]["Net_bps"]),
        ),
        default=("BASE", candidates["BASE"]),
    )[0]
    chosen_rows = routed_cache.get(chosen, gated if chosen == "STATE_GATE" else base)
    span_days = max(
        (max(int(x["exit_ts"]) for x in base) - min(int(x["signal_ts"]) for x in base))
        / 86_400_000.0,
        1e-9,
    )
    out = {
        "schema": "zel.causal_strategy_failover_router.v1",
        "state": "DEV_TRAIN_SELECTED_CAUSAL_ROUTER_NOT_LIVE",
        "objective": "block or throttle strategy-specific negative payer states and reallocate only to already-valid concurrent independent signals",
        "cutoff_ts": cutoff,
        "causal_features": ["regime", "vol_state", "breadth_state"],
        "state_map_policy": "first 60% only; hierarchical state cells; minimum T=max(4,8% of lane train T); GREEN=1x, AMBER=0.5x, RED=0.25x",
        "failover_policy": "no replacement signal is manufactured; released lane risk may boost only another GREEN lane that already fired in the same hour",
        "state_maps": maps,
        "candidates": candidates,
        "selection_rule": "train only: Net>=BASE, PF>=BASE, DD<=BASE, worst train month>=BASE; then maximize worst month, PF, Net",
        "chosen": chosen,
        "chosen_summary": candidates[chosen]["summary"],
        "chosen_T_per_day": len(chosen_rows) / span_days,
        "standby_7_lane_status": {
            "BREAK": "WATCH_NOT_ROUTER_RECEIVER_UNTIL_ROBUST_CHILD",
            "SUPERTREND": "WATCH_NOT_ROUTER_RECEIVER_UNTIL_ROBUST_CHILD",
            "MICRO": "FRESH_FORWARD_T0_NOT_ROUTER_RECEIVER",
            "details": standby,
        },
        "holdout_note": "already-inspected history; holdout is diagnostic only, not fresh OOS",
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    for path in (OUT, REPO_OUT):
        path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        "CAUSAL_FAILOVER="
        + json.dumps(
            {
                "chosen": chosen,
                "base": candidates["BASE"]["summary"],
                "chosen_summary": out["chosen_summary"],
                "T_per_day": out["chosen_T_per_day"],
                "failover": candidates[chosen].get("failover_receipt"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
