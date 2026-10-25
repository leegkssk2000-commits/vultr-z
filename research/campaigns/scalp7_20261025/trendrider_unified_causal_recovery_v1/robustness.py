#!/usr/bin/env python3
"""Auditable post-result stress and ablation, NO parameter retune."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import fuse_and_recover as model

P = Path(__file__).resolve().parent


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def clone_with_extra_roundtrip(
    parent: dict, instrument_bps_per_leg: float, shorts_only: bool = False
) -> dict:
    r = copy.deepcopy(parent)
    for x in r["admitted"]:
        for leg in x["legs"]:
            if shorts_only and leg["side"] != "short":
                continue
            # One extra instrument round-trip stress debit, per held 1/3-size
            # leg. Existing stressed 2x native costs remain INTACT.
            leg["Net2_bps"] -= instrument_bps_per_leg * model.SCALE
        x["Net2_bps"] = sum(y["Net2_bps"] for y in x["legs"])
    return r


def obs(market_foo):
    # Protect exactly one historical immutable snapshot, NO API calls.
    old = model.old_module()
    _, bars = old.source(model.SOURCE)
    maps, ema = old.index_bars(bars)
    old_inputs = old.original_inputs(
        model.SOURCE, json.loads((model.SOURCE / "FREEZE.json").read_text())
    )
    candidates, _ = model.build_candidates(old_inputs, old, bars, maps)
    latest = max(int(x["ts_ms"]) for x in bars["BTC-USDT"])
    return old, bars, maps, ema, candidates, latest


def run():
    frozen = (P / "FREEZE.json").read_bytes()
    saved = (P / "RESULT.json").read_bytes()
    ref = json.loads(saved)
    if sha(frozen) != ref["freeze_sha256"]:
        raise RuntimeError("FREEZE_CHANGED_AFTER_RESULT")
    old, bars, maps, ema, candidates, latest = obs(None)
    base = model.run_stage(candidates, bars, maps, ema, old, 0, latest)
    final = model.run_stage(candidates, bars, maps, ema, old, 4, latest)
    m0 = model.metrics_stage(base)
    m4 = model.metrics_stage(final)
    assert (
        abs(
            m0["Net2_sum_trade_bps"]
            - ref["stage_economics"]["S0"]["Net2_sum_trade_bps"]
        )
        < 1e-5
    )
    assert (
        abs(
            m4["Net2_sum_trade_bps"]
            - ref["stage_economics"]["S4"]["Net2_sum_trade_bps"]
        )
        < 1e-5
    )
    ablations = {}

    # Remove short reversals (same fused parent + trail, stop bailout + circuit);
    # negative-control attribution only, not selecting a replacement model.
    original = model.new_short_leg
    try:
        model.new_short_leg = lambda **kwargs: None
        a = model.run_stage(candidates, bars, maps, ema, old, 4, latest)
        ablations["S4_NO_SHORT"] = {
            "metrics": model.metrics_stage(a),
            "stats": a["stats"],
        }
    finally:
        model.new_short_leg = original

    early_original = model.bailout_close_candidate
    try:
        model.bailout_close_candidate = lambda *args, **kwargs: None
        a = model.run_stage(candidates, bars, maps, ema, old, 4, latest)
        ablations["S4_NO_EARLY_BAILOUT"] = {
            "metrics": model.metrics_stage(a),
            "stats": a["stats"],
        }
    finally:
        model.bailout_close_candidate = early_original

    try:

        def lagged_short(**kwargs):
            item = dict(kwargs)
            item["trigger_j"] = item["trigger_j"] + 1
            return original(**item)

        model.new_short_leg = lagged_short
        a = model.run_stage(candidates, bars, maps, ema, old, 4, latest)
        ablations["S4_SHORT_EXTRA_1H_LATENCY"] = {
            "metrics": model.metrics_stage(a),
            "stats": a["stats"],
            "description": "trigger at existing causal close j but short entry delayed by one extra completely closed bar, short ATR and stop built only from data available then; no new short source.",
        }
    finally:
        model.new_short_leg = original

    fee = {}
    for bps in (20.0, 40.0):
        for short_only in (True, False):
            label = f"EXTRA_{int(bps)}_INSTRUMENT_BPS_" + (
                "SHORT_ONLY" if short_only else "ALL_LONG_AND_SHORT_LEGS"
            )
            stress = clone_with_extra_roundtrip(final, bps, short_only)
            fee[label] = model.metrics_stage(stress)

    leave_one = {}
    for symbol in sorted({x["symbol"] for x in candidates}):
        sliced = [x for x in candidates if x["symbol"] != symbol]
        s0 = model.run_stage(sliced, bars, maps, ema, old, 0, latest)
        s4 = model.run_stage(sliced, bars, maps, ema, old, 4, latest)
        mm0 = model.metrics_stage(s0)
        mm4 = model.metrics_stage(s4)
        leave_one[symbol] = {
            "baseline_T": mm0["accepted_opportunities"],
            "baseline_net2": mm0["Net2_sum_trade_bps"],
            "fused_recovery_T": mm4["accepted_opportunities"],
            "fused_recovery_net2": mm4["Net2_sum_trade_bps"],
            "fused_recovery_PF2": mm4["PF2_opportunity"],
            "fused_recovery_DD2": mm4["DD2_realized_exit_leg_bps"],
            "fused_recovery_max_streak": mm4["max_loss_streak_opportunity"],
            "improvement_delta": mm4["Net2_sum_trade_bps"] - mm0["Net2_sum_trade_bps"],
        }
    final_bykey = {x["key"]: x for x in final["admitted"]}
    raw_losses = [x for x in base["admitted"] if x["Net2_bps"] < 0]
    large_losses = [x for x in raw_losses if x["Net2_bps"] <= -x["initial_long_r_bps"]]
    flipped = [
        (x, final_bykey[x["key"]])
        for x in large_losses
        if x["key"] in final_bykey and final_bykey[x["key"]]["Net2_bps"] > 0
    ]
    badr = sorted(
        [
            {
                "key": x["key"],
                "initial_risk_price_normalized_bps": x["initial_long_r_bps"],
                "Net2_bps": x["Net2_bps"],
                "Net2_initial_R": x["Net2_bps"] / x["initial_long_r_bps"],
            }
            for x in final["admitted"]
        ],
        key=lambda x: x["Net2_initial_R"],
    )
    audit = {
        "schema": "zel.trendrider.unified_rescue.robustness.v1",
        "source_freeze_sha256": sha(frozen),
        "source_result_sha256": sha(saved),
        "evaluation_is_retrospective_used_dev": True,
        "fully_new_unseen_OOS": False,
        "negative_control_attribution_not_parameter_selection": True,
        "baseline_metrics": m0,
        "full_metrics": m4,
        "fixed_fee_stress": fee,
        "fixed_ablation_controls": ablations,
        "leave_one_symbol_out_full_replay": leave_one,
        "positive_from_original_big_loss": len(flipped),
        "positive_ge1R_from_original_big_loss": sum(
            y["Net2_bps"] >= y["initial_long_r_bps"] for _, y in flipped
        ),
        "initial_risk_geometry_tail": {
            "worst_net2_original_r": badr[:5],
            "Net2_below_minus3R": sum(x["Net2_initial_R"] < -3 for x in badr),
            "Net2_below_minus10R": sum(x["Net2_initial_R"] < -10 for x in badr),
            "raw_original_R_is_not_executable_account_capital_at_risk": True,
        },
        "promote_to_G4_G5_Paper_Live": False,
        "realized_broker_fee_funding": False,
        "orders": 0,
    }
    raw = (json.dumps(audit, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with (P / "ROBUSTNESS.json").open("xb") as out:
        out.write(raw)
    print(
        "FROZEN_STRESS",
        json.dumps(
            {
                "baseline": m0["Net2_sum_trade_bps"],
                "final": m4["Net2_sum_trade_bps"],
                "full_excl_top2": m4["Net2_excluding_top2_bps"],
                "fee": {k: round(v["Net2_sum_trade_bps"], 2) for k, v in fee.items()},
                "ablation": {
                    k: round(v["metrics"]["Net2_sum_trade_bps"], 2)
                    for k, v in ablations.items()
                },
                "leave_one": {
                    k: round(v["fused_recovery_net2"], 2) for k, v in leave_one.items()
                },
                "big_loss_to_profit": len(flipped),
                "below_minus10_R": audit["initial_risk_geometry_tail"][
                    "Net2_below_minus10R"
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    print("ROBUSTNESS_SHA256", sha(raw), flush=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=P)
    P = parser.parse_args().root
    run()
