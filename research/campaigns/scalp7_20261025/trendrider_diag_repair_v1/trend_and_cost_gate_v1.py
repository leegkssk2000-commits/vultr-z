"""Two independent PRE-FROZEN causal diagnostics on the existing unified owner.

H1: Wilder ADX14>=25 rising and DI- > DI+ for SHORT reversal. Only uses
    1h candles fully closed as of the short confirmation bar.
H2: published standard taker RT 0.05%+0.05%=10 instrument bp native
    LONG initial stop distance vs cost gate, before any position admission.

Not a fitted production bot, not fresh OOS; no API and no order calls.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Iterator

STAGE_OLD = "d256807c58a41d77606df1a844a2d13c2cfff945"
FREEZE_SCHEMA = "zel.trendrider.diag_trend_funding_nonoptimized.v1"
ROOT = Path(__file__).resolve().parent
PARENT = Path(
    os.environ.get(
        "ZEL_TRENDRIDER_UNIFIED_PARENT_ROOT",
        str(
            Path(__file__).resolve().parent.parent
            / "trendrider_unified_causal_recovery_v1"
        ),
    )
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def import_model(parent: Path) -> Any:
    f = parent / "fuse_and_recover.py"
    if not f.exists():
        raise RuntimeError("PINNED_UNIFIED_CODE_NOT_AVAILABLE")
    spec = importlib.util.spec_from_file_location("pinned_unified", f)
    assert spec and spec.loader
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    return model


def wilder_adx_di(
    bars: list[dict[str, Any]], lookback: int = 14
) -> dict[str, list[float | None]]:
    """Wilder RMA and 14-period DX->ADX, no future-bar references.

    Initial smoothed TR,+DM,-DM at index14 use bars 1..14.
    ADX seeds at index27 as mean(DX[14]..DX[27]).
    """
    n = len(bars)
    plus = [0.0] * n
    minus = [0.0] * n
    tr = [0.0] * n
    adx: list[float | None] = [None] * n
    pos_di: list[float | None] = [None] * n
    neg_di: list[float | None] = [None] * n
    if n < 2 * lookback + 1:
        return {"ADX": adx, "DI+": pos_di, "DI-": neg_di}
    for i in range(1, n):
        p, b = bars[i - 1], bars[i]
        up = float(b["high"]) - float(p["high"])
        down = float(p["low"]) - float(b["low"])
        plus[i] = up if up > down and up > 0 else 0.0
        minus[i] = down if down > up and down > 0 else 0.0
        prev_close = float(p["close"])
        tr[i] = max(
            float(b["high"]) - float(b["low"]),
            abs(float(b["high"]) - prev_close),
            abs(float(b["low"]) - prev_close),
        )
    sm_tr, sm_plus, sm_minus = (
        sum(tr[1 : lookback + 1]),
        sum(plus[1 : lookback + 1]),
        sum(minus[1 : lookback + 1]),
    )
    dx: list[float | None] = [None] * n
    for i in range(lookback, n):
        if i > lookback:
            sm_tr = sm_tr - sm_tr / lookback + tr[i]
            sm_plus = sm_plus - sm_plus / lookback + plus[i]
            sm_minus = sm_minus - sm_minus / lookback + minus[i]
        di_plus = 100 * sm_plus / sm_tr if sm_tr > 0 else 0.0
        di_minus = 100 * sm_minus / sm_tr if sm_tr > 0 else 0.0
        denom = di_plus + di_minus
        dx[i] = 100 * abs(di_plus - di_minus) / denom if denom > 0 else 0.0
        pos_di[i], neg_di[i] = di_plus, di_minus
        if i == 2 * lookback - 1:
            seeded_dx = dx[lookback : i + 1]
            if any(value is None for value in seeded_dx):
                raise RuntimeError("WILDER_ADX_SEED_MISSING")
            adx[i] = sum(value for value in seeded_dx if value is not None) / lookback
        elif i > 2 * lookback - 1:
            prior_adx = adx[i - 1]
            current_dx = dx[i]
            if prior_adx is None or current_dx is None:
                raise RuntimeError("WILDER_ADX_RECURSION_MISSING")
            adx[i] = (prior_adx * (lookback - 1) + current_dx) / lookback
    return {"ADX": adx, "DI+": pos_di, "DI-": neg_di}


def qualified_bearish_dmi(
    *, index: int, features: dict[str, list[float | None]]
) -> bool:
    if index < 28:
        return False
    current, previous = features["ADX"][index], features["ADX"][index - 1]
    di_bear, di_bull = features["DI-"][index], features["DI+"][index]
    if current is None or previous is None or di_bear is None or di_bull is None:
        return False
    return (
        float(current) >= 25.0
        and float(current) > float(previous)
        and float(di_bear) > float(di_bull)
    )


def valid_fee_stop_minimum(candidate: dict[str, Any]) -> bool:
    """Known market fee schedule minimum only; NO future cost/label read."""
    stop = float(candidate["intent_geometry"]["sl"])
    entry = float(candidate["entry"])
    if entry <= 0 or stop >= entry:
        return False
    stop_distance_instrument_bps = (entry - stop) / entry * 10000
    return stop_distance_instrument_bps >= 10.0


@contextlib.contextmanager
def short_dmi_gate(
    model: Any, market: dict[str, list[dict[str, Any]]]
) -> Iterator[dict[str, Any]]:
    old = model.short_confirmation
    keyed: dict[int, dict[str, list[float | None]]] = {}
    for _, bars in sorted(market.items()):
        keyed[id(bars)] = wilder_adx_di(bars)
    counts: dict[str, int] = collections.Counter()

    def gated(
        *, last_completed_idx: int, bars: list[dict[str, Any]], ema: list[float]
    ) -> bool:
        if not old(last_completed_idx=last_completed_idx, bars=bars, ema=ema):
            counts["original_ema_signal_false"] += 1
            return False
        indicators = keyed.get(id(bars))
        if indicators is None:
            raise RuntimeError("BAR_ARRAY_NOT_FROZEN")
        if qualified_bearish_dmi(index=last_completed_idx, features=indicators):
            counts["qualified_adx_di"] += 1
            return True
        counts["rejected_weak_or_wrong_direction"] += 1
        return False

    try:
        model.short_confirmation = gated
        yield counts
    finally:
        model.short_confirmation = old


def metrics_under_fee(model: Any, stage: dict[str, Any], instrument_bps: float) -> dict:
    # Additional conservative cost per actual long or short *leg*, never
    # credits this as actual funding/latency or exchange account NAV.
    copied = copy.deepcopy(stage)
    for opportunity in copied["admitted"]:
        for leg in opportunity["legs"]:
            leg["Net2_bps"] -= instrument_bps / 3.0
        opportunity["Net2_bps"] = sum(leg["Net2_bps"] for leg in opportunity["legs"])
    return model.metrics_stage(copied)


def run(out: Path, parent: Path) -> dict:
    prior = json.loads((out / "FREEZE.json").read_text())
    if prior["schema"] != FREEZE_SCHEMA or len(prior["new_fixed_hypotheses"]) != 2:
        raise RuntimeError("RULE_PRE_FREEZE_MISSING")
    if prior["parent"]["result_sha256"] != sha((parent / "RESULT.json").read_bytes()):
        raise RuntimeError("WRONG_FROZEN_PARENT_EPOCH")
    if prior["parent"]["source_sha256"] != sha((parent / "FREEZE.json").read_bytes()):
        raise RuntimeError("WRONG_FROZEN_PARENT_CONFIG")
    if prior["parent"]["traces_sha256"] != sha(
        (parent / "TRACES.json.gz").read_bytes()
    ):
        raise RuntimeError("WRONG_FROZEN_PARENT_TRACES")
    model = import_model(parent)
    old = model.old_module()
    src, market = old.source(model.SOURCE)
    maps, ema = old.index_bars(market)
    original = old.original_inputs(
        model.SOURCE, json.loads((model.SOURCE / "FREEZE.json").read_text())
    )
    candidates, _ = model.build_candidates(original, old, market, maps)
    last = max(int(bar["ts_ms"]) for bar in market["BTC-USDT"])
    assert last == max(int(bar[-1]["ts_ms"]) for bar in market.values())
    if len(candidates) != 267:
        raise RuntimeError("UNEXPECTED_PRE_FROZEN_UNION_SOURCE")
    original_stage = model.run_stage(candidates, market, maps, ema, old, 4, last)
    original_score = model.metrics_stage(original_stage)
    found = {}
    found["BASE_S4"] = (
        original_stage,
        {"source_T": len(candidates), "indicator_action": "NONE"},
    )
    # H1: only Short replacement confirmation stage changes; original long
    # exit/winner logic, capital rules and all published fees identical.
    with short_dmi_gate(model, market) as gate_counts:
        adx_stage = model.run_stage(candidates, market, maps, ema, old, 4, last)
        found["H1_DMI14_STRONG_NEGATIVE"] = (
            adx_stage,
            {
                "source_T": len(candidates),
                "indicator_action": "SHORT_ADX_DI",
                "gate_counts": dict(gate_counts),
            },
        )
    # H2 independent of H1: 10bp public standard fee-cost stop suitability
    # is knowable at actual entry and never reads an eventual win/loss.
    eligible = [c for c in candidates if valid_fee_stop_minimum(c)]
    rejected = [c for c in candidates if not valid_fee_stop_minimum(c)]
    stop_stage = model.run_stage(eligible, market, maps, ema, old, 4, last)
    found["H2_NATIVE_STOP_COST_FLOOR"] = (
        stop_stage,
        {
            "source_T": len(candidates),
            "entry_risk_eligible": len(eligible),
            "entry_risk_veto_T": len(rejected),
            "entry_risk_veto_unique_ids": [c["canonical_key"] for c in rejected],
        },
    )
    response = {
        "schema": "zel.trendrider.two_independent_causal_controls.v1",
        "freeze_sha256": sha((out / "FREEZE.json").read_bytes()),
        "source_sha256": prior["parent"]["result_sha256"],
        "input_source_symbol_count": len(market),
        "input_candidate_count": len(candidates),
        "C_owner": "existing C read-only only",
        "hypotheses": {},
        "final_executable_admission": False,
        "new_untouched_OOS": False,
        "funding_actual_signed": False,
        "new_market_requests": 0,
        "orders": 0,
    }
    base_ids = {x["key"]: x for x in original_stage["admitted"]}
    for key, (stage, meta) in found.items():
        score = model.metrics_stage(stage)
        pos = {x["key"]: x for x in stage["admitted"]}
        overlap = set(base_ids) & set(pos)
        common_delta = sum(
            pos[t]["Net2_bps"] - base_ids[t]["Net2_bps"] for t in sorted(overlap)
        )
        absent = set(base_ids) - set(pos)
        total_win_lost = sum(max(base_ids[t]["Net2_bps"], 0.0) for t in sorted(absent))
        stress20 = metrics_under_fee(model, stage, 20.0)
        stress40 = metrics_under_fee(model, stage, 40.0)
        late = None
        if key == "H1_DMI14_STRONG_NEGATIVE":
            orig_short = model.new_short_leg
            try:

                def late_short(**kwargs):
                    x = dict(kwargs)
                    x["trigger_j"] += 1
                    return orig_short(**x)

                model.new_short_leg = late_short
                with short_dmi_gate(model, market):
                    late = model.metrics_stage(
                        model.run_stage(candidates, market, maps, ema, old, 4, last)
                    )
            finally:
                model.new_short_leg = orig_short
        without_1000 = [
            c
            for c in (eligible if key == "H2_NATIVE_STOP_COST_FLOOR" else candidates)
            if c["symbol"] != "1000PEPE-USDT"
        ]
        if key == "H1_DMI14_STRONG_NEGATIVE":
            with short_dmi_gate(model, market):
                no_pepe = model.run_stage(without_1000, market, maps, ema, old, 4, last)
        else:
            no_pepe = model.run_stage(without_1000, market, maps, ema, old, 4, last)
        no_pepe_score = model.metrics_stage(no_pepe)
        response["hypotheses"][key] = {
            "measured": score,
            "diagnostics": meta,
            "extra20bp_all_legs": stress20,
            "extra40bp_all_legs": stress40,
            "plus1h_short_delay": late,
            "leave_1000PEPE_out_full_evaluator": no_pepe_score,
            "relative_to_baseline": {
                "Net2_delta": score["Net2_sum_trade_bps"]
                - original_score["Net2_sum_trade_bps"],
                "common_T": len(overlap),
                "common_net2_delta": common_delta,
                "old_candidates_displaced_T": len(absent),
                "old_displaced_positive_winner_profit": total_win_lost,
                "new_selected_original_source_candidate_T": len(
                    set(pos) - set(base_ids)
                ),
            },
            "passes_cost40_and_PEPE_holdout": stress40["Net2_sum_trade_bps"] > 0
            and no_pepe_score["Net2_sum_trade_bps"] > 0,
        }
        print(
            "STAGE_HYPOTHESIS",
            key,
            {
                "accepted": score["accepted_opportunities"],
                "shorts": score["reverse_short_legs"],
                "Net2": round(score["Net2_sum_trade_bps"], 2),
                "PF2": round(score["PF2_opportunity"] or 0, 4),
                "DD": round(score["DD2_realized_exit_leg_bps"], 2),
                "LOSS_STREAK": score["max_loss_streak_opportunity"],
                "extra20Net": round(stress20["Net2_sum_trade_bps"], 2),
                "extra40Net": round(stress40["Net2_sum_trade_bps"], 2),
                "NoPEPENet": round(no_pepe_score["Net2_sum_trade_bps"], 2),
                "relDelta": round(
                    score["Net2_sum_trade_bps"] - original_score["Net2_sum_trade_bps"],
                    2,
                ),
            },
            flush=True,
        )
    h1 = response["hypotheses"]["H1_DMI14_STRONG_NEGATIVE"]
    h2 = response["hypotheses"]["H2_NATIVE_STOP_COST_FLOOR"]

    def standalone_better(row):
        v = row["measured"]
        original_score = response["hypotheses"]["BASE_S4"]["measured"]
        return (
            v["Net2_sum_trade_bps"] > original_score["Net2_sum_trade_bps"]
            and v["DD2_realized_exit_leg_bps"]
            <= original_score["DD2_realized_exit_leg_bps"]
            and v["PF2_opportunity"] >= original_score["PF2_opportunity"]
        )

    response["compound_evaluated"] = False
    response["compound_gate"] = "NOT_ELIGIBLE_STOP_IF_EITHER_NO_PARETO"
    if standalone_better(h1) and standalone_better(h2):
        with short_dmi_gate(model, market):
            compound = model.run_stage(eligible, market, maps, ema, old, 4, last)
        response["compound_evaluated"] = True
        response["compound_gate"] = "INDEPENDENT_PARETO_BOTH_PASS"
        response["hypotheses"]["H1_AND_H2_PRESPEC_COMBINATION"] = {
            "measured": model.metrics_stage(compound),
            "other": "No economic promotion without fee40, symbol, delay, and future OOS.",
        }
    payload = (
        json.dumps(response, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    with (out / "RESULT.json").open("xb") as fd:
        fd.write(payload)
    print("DIAGNOSTIC_FREEZE_RESULT_SHA256", sha(payload), response["compound_gate"])
    return response


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--parent", type=Path, default=PARENT)
    args = ap.parse_args()
    run(args.root, args.parent)
