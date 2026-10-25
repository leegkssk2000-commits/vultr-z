"""One pre-frozen, source-only stop-risk economic feasibility axis, no sweep."""

from __future__ import annotations
import json
import hashlib
from pathlib import Path
import fuse_and_recover as m

P = Path(__file__).resolve().parent


def run():
    frozen = (P / "MECHANISM_FIX_FREEZE.json").read_bytes()
    spec = json.loads(frozen)
    assert spec["schema"] == "zel.trendrider.unified_one_axisscreen.v1"
    assert (
        hashlib.sha256((P / "RESULT.json").read_bytes()).hexdigest()
        == spec["base_result_sha256"]
    )
    assert (
        hashlib.sha256((P / "ROBUSTNESS.json").read_bytes()).hexdigest()
        == spec["base_robustness_sha256"]
    )
    old = m.old_module()
    _, bars = old.source(m.SOURCE)
    maps, ema = old.index_bars(bars)
    inp = old.original_inputs(
        m.SOURCE, json.loads((m.SOURCE / "FREEZE.json").read_text())
    )
    candidates, _ = m.build_candidates(inp, old, bars, maps)
    latest = max(int(x["ts_ms"]) for x in bars["BTC-USDT"])
    original = m.run_stage(candidates, bars, maps, ema, old, 4, latest)
    original_metrics = m.metrics_stage(original)
    valid = []
    denied = []
    diagnoses = []
    for x in candidates:
        price_r = (
            10000
            * (float(x["entry"]) - float(x["intent_geometry"]["sl"]))
            / float(x["entry"])
        )
        source_c = float(x["instrument_source_cost_bps"])
        entry_j = maps[x["symbol"]][int(x["entry_ts"])]
        atr = m.atr_14(bars[x["symbol"]], entry_j - 1)
        normalized_r = (float(x["entry"]) - float(x["intent_geometry"]["sl"])) / atr
        # Preliminary source feasibility only, no future outcomes.
        if price_r < 2 * source_c:
            denied.append(x)
        else:
            valid.append(x)
        diagnoses.append(
            {
                "key": x["canonical_key"],
                "native_R_instrument_bps": price_r,
                "source_cost_instrument_bps": source_c,
                "R_div_cost": price_r / source_c if source_c else None,
                "R_div_prior_ATR14": normalized_r,
                "excluded_cost_floor": price_r < 2 * source_c,
            }
        )
    out = m.run_stage(valid, bars, maps, ema, old, 4, latest)
    metrics = m.metrics_stage(out)
    # Rejected input must be counted relative to ALL source candidates.
    denykey = {x["canonical_key"] for x in denied}
    originally_accepted = [x for x in original["admitted"] if x["key"] in denykey]
    left = {}
    for symbol in sorted({x["symbol"] for x in valid}):
        sub = [x for x in valid if x["symbol"] != symbol]
        v = m.metrics_stage(m.run_stage(sub, bars, maps, ema, old, 4, latest))
        left[symbol] = {
            "net2": v["Net2_sum_trade_bps"],
            "PF2": v["PF2_opportunity"],
            "DD2": v["DD2_realized_exit_leg_bps"],
        }
    data = {
        "schema": "zel.trendrider.unified.stop_cost_screen_result.v1",
        "pre_result_rule_sha256": hashlib.sha256(frozen).hexdigest(),
        "base_S4": original_metrics,
        "one_axis_S4": metrics,
        "input_source_T": len(candidates),
        "cost_stop_preentry_rejected_T": len(denied),
        "original_S4_acceptances_removed_by_filter_T": len(originally_accepted),
        "removed_prior_winners_T": sum(x["Net2_bps"] > 0 for x in originally_accepted),
        "removed_prior_winner_net2": sum(
            max(0, x["Net2_bps"]) for x in originally_accepted
        ),
        "source_diagnostics": diagnoses,
        "by_symbol_leave_one": left,
        "actual_fee_unknown": True,
        "fresh_prospective": False,
        "promote": False,
        "orders": 0,
    }
    raw = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    (P / "MECHANISM_FIX_RESULT.json").write_bytes(raw)
    print(
        "ONE_AXIS_RESULTS",
        json.dumps(
            {
                "base_T": original_metrics["accepted_opportunities"],
                "base_net": original_metrics["Net2_sum_trade_bps"],
                "base_PF": original_metrics["PF2_opportunity"],
                "child_T": metrics["accepted_opportunities"],
                "child_net": metrics["Net2_sum_trade_bps"],
                "child_PF": metrics["PF2_opportunity"],
                "child_DD": metrics["DD2_realized_exit_leg_bps"],
                "child_maxstreak": metrics["max_loss_streak_opportunity"],
                "rejected": len(denied),
                "lost_winners": data["removed_prior_winners_T"],
                "October": metrics["by_month_Net2"].get("2026-10"),
                "leave_1000PEPE": left.get("1000PEPE-USDT"),
            }
        ),
        flush=True,
    )
    print("FIX_RECEIPT_SHA", hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    run()
