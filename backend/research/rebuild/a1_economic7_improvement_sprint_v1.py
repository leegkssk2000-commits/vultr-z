from __future__ import annotations

import importlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

mx: Any = importlib.import_module(
    "backend.research.rebuild.a1_strategy_regime_alpha_matrix_v1"
)
p1: Any = importlib.import_module(
    "backend.research.rebuild.a1_priority_economic_program_v1"
)
cc: Any = importlib.import_module(
    "backend.research.rebuild.a1_economic_core_crowding_allocator_v5"
)

ROOT = Path("/home/z/z/runtime")
OUT = ROOT / "economic7_improvement_sprint_v1.json"
REPO_OUT = Path(__file__).with_name("economic7_improvement_sprint_v1_results.json")


def split_metrics(
    rows: list[dict[str, Any]], cutoff: int, key: str = "net_bps"
) -> dict[str, Any]:
    train = [x for x in rows if int(x["signal_ts"]) <= cutoff]
    hold = [x for x in rows if int(x["signal_ts"]) > cutoff]
    return {
        "full": mx.metrics(rows, key),
        "train": mx.metrics(train, key),
        "hold": mx.metrics(hold, key),
    }


def normalize(rows: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["strategy"] = name
        item["adjusted_bps"] = float(item.get("adjusted_bps", item["net_bps"]))
        out.append(item)
    return out


def monthly(rows: list[dict[str, Any]], key: str = "adjusted_bps") -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for row in rows:
        m = datetime.fromtimestamp(
            int(row["exit_ts"]) / 1000, tz=timezone.utc
        ).strftime("%Y-%m")
        out[m] += float(row[key])
    return dict(sorted(out.items()))


def build_inputs() -> tuple[
    Any,
    int,
    dict[str, float],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    feat, cutoff, q = mx.build_features()
    strategies = mx.load_strategies()
    mx.attach_regimes(strategies, feat, q)
    ledger = json.load(open(ROOT / "active5_v6_180d_ledger_v2.json"))["trades"]
    bars = p1.v6.v5.local_1h_bars()
    return feat, cutoff, q, strategies, ledger, bars


def build_regmap(
    strategies: dict[str, list[dict[str, Any]]]
) -> dict[tuple[str, str, int], str]:
    return {
        (str(row["strategy"]), str(row["symbol"]), int(row["signal_ts"])): str(
            row["regime"]
        )
        for rows in strategies.values()
        for row in rows
    }


def keltner_lane(
    strategies: dict[str, list[dict[str, Any]]], cutoff: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = strategies["keltner_holygrail_30m"]
    base_regs = {"PANIC_DISPERSION"}
    additions: list[str] = []
    diagnostics: dict[str, Any] = {}
    for reg in sorted({str(x["regime"]) for x in rows} - base_regs):
        xs = [x for x in rows if x["regime"] == reg]
        sm = split_metrics(xs, cutoff)
        diagnostics[reg] = sm
        tr = sm["train"]
        if tr["T"] >= 15 and (tr["Exp_bps_T"] or -1e9) > 0 and (tr["PF"] or 0) > 1.2:
            additions.append(reg)
    selected_regs = base_regs | set(additions)
    selected = normalize(
        [x for x in rows if x["regime"] in selected_regs], "keltner_hg_expanded"
    )
    return {
        "selected_regimes": sorted(selected_regs),
        "metrics": split_metrics(selected, cutoff, "adjusted_bps"),
        "diagnostics": diagnostics,
    }, selected


def rider_lane(
    strategies: dict[str, list[dict[str, Any]]],
    ledger: list[dict[str, Any]],
    bars: dict[str, Any],
    cutoff: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    regmap = build_regmap(strategies)
    regime_diag: dict[str, Any] = {}
    for reg in sorted({str(x["regime"]) for x in strategies["trend_rider_active5"]}):
        xs = p1.improved_active(
            ledger, regmap, bars, "trend_rider", reg, 12, 0.50, f"trend_rider_{reg}"
        )
        regime_diag[reg] = split_metrics(xs, cutoff)
    rows, _, _, _, _ = cc.build_rows()
    capped = cc.apply_cap(rows, 1.0)
    rider = [
        dict(x, strategy="trend_rider_coherent_capped")
        for x in capped
        if str(x.get("strategy")) == "trend_rider_coherent_v2"
    ]
    return {
        "selected_regime": "TREND_COHERENT",
        "same_hour_same_side_cap": 1.0,
        "metrics": split_metrics(rider, cutoff, "adjusted_bps"),
        "regime_diagnostics": regime_diag,
    }, rider


def break_lane(
    strategies: dict[str, list[dict[str, Any]]],
    ledger: list[dict[str, Any]],
    bars: dict[str, Any],
    cutoff: int,
) -> dict[str, Any]:
    regmap = build_regmap(strategies)
    rows = p1.improved_active(
        ledger,
        regmap,
        bars,
        "break_and_continue",
        "TREND_DISPERSED",
        6,
        0.75,
        "break_td",
    )
    side_map = {
        (str(t["symbol"]), int(t["signal_ts"])): str(t["side"])
        for t in ledger
        if t["strategy_id"] == "break_and_continue"
    }
    for row in rows:
        row["side"] = side_map[(str(row["symbol"]), int(row["signal_ts"]))]
    side_diag = {
        side: split_metrics([x for x in rows if x["side"] == side], cutoff)
        for side in ("long", "short")
    }
    selected = [
        side
        for side, sm in side_diag.items()
        if sm["train"]["T"] >= 12
        and (sm["train"]["Exp_bps_T"] or -1e9) > 0
        and (sm["train"]["PF"] or 0) > 1.2
    ]
    confirmed = [
        side
        for side in selected
        if (side_diag[side]["hold"]["Exp_bps_T"] or -1e9) > 0
        and (side_diag[side]["hold"]["PF"] or 0) > 1.0
    ]
    return {
        "base": split_metrics(rows, cutoff),
        "train_selected_sides": selected,
        "holdout_confirmed_sides": confirmed,
        "side_diagnostics": side_diag,
        "decision": "KEEP_WATCH_NO_SIDE_AXIS" if not confirmed else "DEV_SIDE_CHILD",
    }


def supertrend_lane(
    strategies: dict[str, list[dict[str, Any]]], cutoff: int
) -> dict[str, Any]:
    rows = strategies["supertrend_pullback_active5"]
    diag: dict[str, Any] = {}
    selected: list[str] = []
    confirmed: list[str] = []
    for reg in sorted({str(x["regime"]) for x in rows}):
        xs = [x for x in rows if x["regime"] == reg]
        sm = split_metrics(xs, cutoff)
        diag[reg] = sm
        tr = sm["train"]
        if tr["T"] >= 20 and (tr["Exp_bps_T"] or -1e9) > 0 and (tr["PF"] or 0) > 1.05:
            selected.append(reg)
            ho = sm["hold"]
            if (ho["Exp_bps_T"] or -1e9) > 0 and (ho["PF"] or 0) > 1.0:
                confirmed.append(reg)
    return {
        "train_selected_regimes": selected,
        "holdout_confirmed_regimes": confirmed,
        "diagnostics": diag,
        "decision": (
            "WATCH_ONLY_NO_ROBUST_REGIME_CHILD" if not confirmed else "DEV_REGIME_CHILD"
        ),
    }


def squeeze_lane(
    strategies: dict[str, list[dict[str, Any]]], cutoff: int
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    panic = [
        x for x in strategies["squeeze_native_30m"] if x["regime"] == "PANIC_DISPERSION"
    ]
    side_diag = {
        side: split_metrics([x for x in panic if x["side"] == side], cutoff)
        for side in ("long", "short")
    }
    eligible = [
        side
        for side, sm in side_diag.items()
        if sm["train"]["T"] >= 12
        and (sm["train"]["Exp_bps_T"] or -1e9) > 0
        and (sm["train"]["PF"] or 0) > 1.2
    ]
    confirmed = [
        side
        for side in eligible
        if (side_diag[side]["hold"]["Exp_bps_T"] or -1e9) > 0
        and (side_diag[side]["hold"]["PF"] or 0) > 1.0
    ]
    chosen = confirmed[0] if len(confirmed) == 1 else None
    rows = (
        normalize(
            [x for x in panic if chosen is not None and x["side"] == chosen],
            "squeeze_panic_long",
        )
        if chosen
        else []
    )
    return {
        "base_panic": split_metrics(panic, cutoff),
        "side_diagnostics": side_diag,
        "chosen_side": chosen,
        "metrics": split_metrics(rows, cutoff, "adjusted_bps") if rows else None,
        "decision": "DEV_LONG_PANIC_CHILD" if chosen else "KEEP_WATCH",
    }, rows


def mean_reversion_lane(cutoff: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = json.load(
        open(Path(__file__).with_name("cross_sectional_mean_reversion_v1_results.json"))
    )
    trades = source["trades"]
    diag: dict[str, Any] = {}
    for reg in sorted({str(x["regime"]) for x in trades}):
        rows = [
            {
                "strategy": "mr_v1",
                "signal_ts": int(x["signal_ts"]),
                "exit_ts": int(x["exit_ts"]),
                "net_bps": float(x["net_bps"]),
            }
            for x in trades
            if x["regime"] == reg
        ]
        diag[reg] = split_metrics(rows, cutoff)
    rows = [
        {
            "strategy": "mr_v1",
            "signal_ts": int(x["signal_ts"]),
            "exit_ts": int(x["exit_ts"]),
            "adjusted_bps": float(x["net_bps"]),
        }
        for x in trades
    ]
    return {
        "metrics": split_metrics(rows, cutoff, "adjusted_bps"),
        "regime_diagnostics": diag,
        "decision": "KEEP_V1_NO_NEW_AXIS; V2_V3_REJECTED",
        "T_per_day": float(source["T_per_day"]),
    }, rows


def micro_lane() -> dict[str, Any]:
    dev = json.load(
        open(Path(__file__).with_name("micro_exhaustion_sleeve_v1_results.json"))
    )
    fresh = json.load(
        open(Path(__file__).with_name("micro_exhaustion_fresh_forward_v2_results.json"))
    )
    return {
        "development": dev["candidates"]["EDGE"],
        "fresh": fresh,
        "decision": "KEEP_FROZEN_EDGE_NO_RETUNE_UNTIL_FRESH_T_GT_0",
    }


def portfolio(rows_by_lane: list[list[dict[str, Any]]], cutoff: int) -> dict[str, Any]:
    rows = sorted(
        [x for lane in rows_by_lane for x in lane],
        key=lambda x: (int(x["exit_ts"]), str(x["strategy"])),
    )
    train = [x for x in rows if int(x["signal_ts"]) <= cutoff]
    hold = [x for x in rows if int(x["signal_ts"]) > cutoff]
    span = max(
        (max(int(x["exit_ts"]) for x in rows) - min(int(x["signal_ts"]) for x in rows))
        / 86_400_000.0,
        1e-9,
    )
    return {
        "full": cc.a2.metric(rows, "adjusted_bps"),
        "train": cc.a2.metric(train, "adjusted_bps"),
        "hold": cc.a2.metric(hold, "adjusted_bps"),
        "months": monthly(rows),
        "T_per_day": len(rows) / span,
    }


def main() -> int:
    _, cutoff, _, strategies, ledger, bars = build_inputs()
    keltner, keltner_rows = keltner_lane(strategies, cutoff)
    rider, rider_rows = rider_lane(strategies, ledger, bars, cutoff)
    brk = break_lane(strategies, ledger, bars, cutoff)
    supertrend = supertrend_lane(strategies, cutoff)
    squeeze, squeeze_rows = squeeze_lane(strategies, cutoff)
    mr, mr_rows = mean_reversion_lane(cutoff)
    micro = micro_lane()
    dev_portfolio = portfolio([keltner_rows, rider_rows, squeeze_rows, mr_rows], cutoff)
    out = {
        "schema": "zel.economic7.improvement_sprint.v1",
        "state": "DEV_7_LANE_SPRINT_COMPLETE_NOT_LIVE",
        "cutoff_ts": cutoff,
        "selection_policy": "bounded one-axis train-only selection; holdout only confirms/rejects; no live authority",
        "lanes": {
            "keltner_holygrail_30m": keltner,
            "trend_rider_coherent_stale_scratch": rider,
            "break_trend_dispered": brk,
            "supertrend_regime": supertrend,
            "squeeze_break": squeeze,
            "cross_sectional_mean_reversion_v1": mr,
            "micro_exhaustion_edge": micro,
        },
        "development_portfolio_excluding_watch_and_unconfirmed_micro": dev_portfolio,
        "decisions": {
            "accepted_dev_changes": [
                "keltner: add TREND_DISPERSED to PANIC_DISPERSION sleeve",
                "squeeze: PANIC_DISPERSION long-only child",
                "trend_rider: preserve coherent child plus train-selected same-hour same-side crowding cap",
            ],
            "no_change": [
                "break: train-selected short side failed holdout",
                "supertrend: no regime passed train+hold confirmation",
                "mean_reversion: preserve V1; V2/V3 expansion failed",
                "micro: frozen EDGE; fresh forward has no new trade yet",
            ],
        },
        "authority": {
            "selection": False,
            "promotion": False,
            "execution": "NONE",
            "order": "BLOCKED",
            "live": "BLOCKED",
        },
    }
    payload = json.dumps(out, indent=2, sort_keys=True) + "\n"
    OUT.write_text(payload)
    REPO_OUT.write_text(payload)
    print(
        "ECONOMIC7_SPRINT="
        + json.dumps(
            {"portfolio": dev_portfolio, "decisions": out["decisions"]}, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
