from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd  # type: ignore[import-untyped]

v2: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark25_donor_state_machine_replay_v2"
)
sm: Any = importlib.import_module(
    "backend.research.rebuild.benchmark25_donor_state_machine_v2"
)
web6: Any = importlib.import_module(
    "backend.research.rebuild.a1_benchmark_web_gmma_holygrail_v6"
)

TF = 1_800_000
COST_GATE = 5.8


def rearm_signal(
    state: Any, i: int, x: pd.DataFrame, spec: Mapping[str, Any], cost_bps: float
) -> Any | None:
    row, prev = x.iloc[i], x.iloc[i - 1]
    side = web6.gmma_long_side(row, prev)
    strong = side != "flat" and float(row["adx14"]) >= 30.0
    slope = float(row["g20"]) - float(prev["g20"])
    strong = strong and (
        (side == "long" and slope > 0) or (side == "short" and slope < 0)
    )
    if not strong:
        if float(row["adx14"]) < 25.0 or side == "flat":
            state.reset_all()
        return None
    if state.regime_side != side:
        state.reset_all()
        state.regime_side = side
    if state.episode_traded:
        renewed = (
            float(row["high"]) > float(row["hi20"])
            if side == "long"
            else float(row["low"]) < float(row["lo20"])
        )
        if renewed:
            state.episode_traded = False
            state.reset_event()
        return None
    if state.stage == 0:
        touched = (
            float(row["low"]) <= float(row["g20"])
            if side == "long"
            else float(row["high"]) >= float(row["g20"])
        )
        if touched:
            state.stage = 1
            state.pull_low = float(row["low"])
            state.pull_high = float(row["high"])
        return None
    state.pull_low = min(float(state.pull_low), float(row["low"]))
    state.pull_high = max(float(state.pull_high), float(row["high"]))
    turn = (
        float(row["close"]) > float(prev["high"])
        and float(row["close"]) > float(row["g20"])
        if side == "long"
        else float(row["close"]) < float(prev["low"])
        and float(row["close"]) < float(row["g20"])
    )
    entry = float(x.iloc[i + 1]["open"])
    if turn and web6.atr_cost(row, entry, cost_bps) >= COST_GATE:
        state.episode_traded = True
        invalid = float(state.pull_low if side == "long" else state.pull_high)
        return web6.make_signal(
            "keltner_trend",
            spec,
            side,
            i,
            row,
            invalid,
            invalid,
            (
                "ADX_GT_30",
                "GMMA_LONG_GROUP_AGREEMENT",
                "FRESH_MOMENTUM_EPISODE",
                "PULLBACK_20EMA",
                "TURN_TRIGGER",
                "ATR_COST_5P8",
            ),
        )
    return None


def replay(
    frames: Mapping[str, pd.DataFrame],
    costs: Mapping[str, float],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    signals = 0
    for sym in v2.SYMS6:
        x = web6.enrich_web(frames[sym])
        state = web6.WebState()
        i = 121
        while i < len(x) - 1:
            sig = rearm_signal(state, i, x, spec, float(costs[sym]))
            if sig is None:
                i += 1
                continue
            signals += 1
            trade, exit_j = v2.simulate_trade(
                "keltner_trend", sig, x, float(costs[sym]), spec
            )
            if trade is not None:
                trade["symbol"] = sym
                trade["entry_source"] = "WEB_DONOR_HOLYGRAIL_REARM_V9"
                trades.append(trade)
            i = max(i + 1, exit_j + 1)
    return {
        "signals": signals,
        "metrics": v2.metrics(trades),
        "split": v2.split_metrics(trades),
        "trades": trades,
    }


def main() -> int:
    all_spec = sm.load_spec()
    spec_all = web6.build_case_spec(all_spec, "keltner_trend", TF)
    frames_by_tf, _ = v2.prepare_frames(spec_all)
    spec = spec_all["children"]["keltner_trend"]
    authority = v2.read_json(v2.COST_PATH)
    costs: dict[str, float] = {}
    for sym in v2.SYMS6:
        snap = v2.cost_ev.fetch_execution_snapshot(sym, authority)
        costs[sym] = float(snap["pretrade_verified_cost_bps"])
    result = replay(frames_by_tf[TF], costs, spec)
    m = result["metrics"]
    h = result["split"]["holdout40"]
    compact = {
        "T": m["T"],
        "WR": m["WR"],
        "GrossExp_bps_T": m["GrossExp_bps_T"],
        "NetExp_bps_T": m["Exp_bps_T"],
        "PF": m["PF"],
        "HoldT": h["T"],
        "HoldGrossExp_bps_T": h["GrossExp_bps_T"],
        "HoldNetExp_bps_T": h["Exp_bps_T"],
        "HoldPF": h["PF"],
    }
    print("HOLYGRAIL_REARM_V9=" + json.dumps(compact, sort_keys=True), flush=True)
    out = {
        "schema": "zel.a1.benchmark_web.holygrail_rearm.v9",
        "state": "DEV_REPLAY_COMPLETE",
        "source_ids": ["RASCHKE_PRIMARY_INTERVIEW", "GUPPY_OFFICIAL"],
        "rule": "same 30m web-donor v6; allow a new first-pullback cycle only after a fresh 20-bar momentum extreme while ADX>30",
        "frozen_cost_gate": COST_GATE,
        "research_only": True,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "result": result,
    }
    Path("/home/z/z/runtime/benchmark_web_holygrail_rearm_v9.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
