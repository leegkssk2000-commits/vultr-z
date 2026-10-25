"""Read-only holdout diagnostics for frozen TrendRider stage results."""

import json
from datetime import datetime, timezone
from pathlib import Path

from stages import (
    make_stage1,
    index_bars,
    metrics,
    original_inputs,
    original_rows,
    source,
    stage2_soft_risk,
    terminal_source_parity,
    sha,
)

ROOT = Path(__file__).resolve().parent


def run():
    result_raw = (ROOT / "RESULT.json").read_bytes()
    result = json.loads(result_raw)
    freeze = json.loads((ROOT / "FREEZE.json").read_text())
    market, bars = source(ROOT)
    originals = original_inputs(ROOT, freeze)
    maps, ema = index_bars(bars)
    now = datetime.fromisoformat(market["utc_retrieved_at"])
    evidence = {
        "schema": "zel.trendrider.causal_two_axes_robustness.v1",
        "frozen_sha256": result["frozen_sha256"],
        "parent_result_sha256": sha(result_raw),
        "classification": "SAVED_USED_HISTORY_DIAGNOSTIC_NOT_OOS",
        "lanes": {},
        "orders": 0,
        "promotion": False,
    }
    for lane, trades in originals.items():
        terminal_source_parity(trades, bars, maps)
        bad = [
            x for x in trades if float(x["entry"]) <= float(x["intent_geometry"]["sl"])
        ]
        admitted = [x for x in trades if x not in bad]
        # Correct stop geometry must be enforced before causal Stage 2.
        source_rows = admitted if bad else trades
        base = original_rows(source_rows)
        ext, metadata = make_stage1(source_rows, bars, maps, ema, now)
        reduced, reduced_meta = stage2_soft_risk(source_rows)
        combined = None
        combined_metadata = None
        if (
            not bad
            and result["results"][lane]["metrics"]["stage1_winner_extension"][
                "economic_improvement_pass"
            ]
        ):
            combined, combined_metadata = stage2_soft_risk(ext)

        original_keys = {(x["symbol"], x["signal_ts"]) for x in base}
        ext_keys = {(x["symbol"], x["signal_ts"]) for x in ext}
        if len(original_keys) != len(base) or len(ext_keys) != len(ext):
            raise RuntimeError("DUPLICATE_TRADE_OR_NO_SOURCE_PARITY")
        if ext_keys - original_keys:
            raise RuntimeError("STAGE1_FABRICATED_NEW_TRADE")
        if len(original_keys - ext_keys) != metadata.get(
            "saved_opportunities_blocked_by_new_exit", 0
        ):
            raise RuntimeError("STAGE1_COOLDOWN_ACCOUNTING_MISMATCH")
        if any(x.get("modeled_incremental_carry_bps", 0) < 0 for x in ext):
            raise RuntimeError("NEGATIVE_MODELED_CARRY")
        if any(x.get("stage2_risk_factor") not in (1.0, 0.75) for x in reduced):
            raise RuntimeError("RISK_RULE_NOT_FROZEN")
        if len(reduced) != len(base):
            raise RuntimeError("STAGE2_MUST_NOT_REJECT_ANY_WINNER_OR_LOSER")

        bound = [("baseline", base), ("stage1", ext), ("stage2", reduced)]
        if combined is not None:
            bound.append(("stage1_plus_stage2", combined))
        partitions = {}
        for m in ("2026-09", "2026-10"):
            subs = {}
            for name, rows in bound:
                s = [
                    t
                    for t in rows
                    if datetime.fromtimestamp(
                        int(t["signal_ts"]) / 1000, timezone.utc
                    ).strftime("%Y-%m")
                    == m
                ]
                score = metrics(s)
                subs[name] = {
                    "T": score["T"],
                    "Net2_bps": score["Net2_sum_trade_bps"],
                    "PF2": score["Net2_profit_factor"],
                    "DD2_bps": score["Net2_exit_cohort_DD_trade_bps"],
                }
            partitions[m] = subs
        leave_one = {}
        for sym in sorted({t["symbol"] for t in base}):
            d = {}
            for name, rows in bound:
                score = metrics([x for x in rows if x["symbol"] != sym])
                d[name] = {
                    "T": score["T"],
                    "Net2_bps": score["Net2_sum_trade_bps"],
                    "PF2": score["Net2_profit_factor"],
                    "DD2_bps": score["Net2_exit_cohort_DD_trade_bps"],
                }
            leave_one[sym] = d

        orig_map = {(x["symbol"], x["signal_ts"]): x for x in base}
        deltas = [
            {
                "symbol": x["symbol"],
                "signal_ts": x["signal_ts"],
                "Net2_delta_bps": float(x["net2_bps"])
                - float(orig_map[(x["symbol"], x["signal_ts"])]["net2_bps"]),
                "old_Net2_bps": float(
                    orig_map[(x["symbol"], x["signal_ts"])]["net2_bps"]
                ),
                "new_Net2_bps": float(x["net2_bps"]),
                "extra_hours": (int(x["exit_ts"]) - int(x["old_exit_ts"])) // 3600000,
                "exit_reason": x["reason"],
            }
            for x in ext
            if x["exit_ts"] != x["old_exit_ts"]
        ]
        deltas.sort(key=lambda x: x["Net2_delta_bps"], reverse=True)
        orig_excluded = [
            x for x in base if (x["symbol"], x["signal_ts"]) not in ext_keys
        ]
        stat = {name: metrics(rows) for name, rows in bound}
        evidence["lanes"][lane] = {
            "source_input_T": len(trades),
            "preentry_stop_geometry_invalid_T": len(bad),
            "valid_cohort_T": len(source_rows),
            "stages": stat,
            "monthly": partitions,
            "leave_one_symbol_out": leave_one,
            "stage1_eligible_delta_top5": deltas[:5],
            "stage1_eligible_delta_bottom5": deltas[-5:],
            "stage1_source_removed_T": len(orig_excluded),
            "stage1_source_removed_profit_bps": sum(
                x["net2_bps"] for x in orig_excluded if x["net2_bps"] > 0
            ),
            "stage1_source_removed_loss_bps": sum(
                x["net2_bps"] for x in orig_excluded if x["net2_bps"] < 0
            ),
            "stage1_model_limitation": "FROZEN_ACCEPTED_OPPORTUNITY_SET_ONLY_NO_REGENERATED_SIGNALS",
            "stages_runtime_diagnostics": {
                "stage1": metadata,
                "stage2": reduced_meta,
                "combined": combined_metadata,
            },
            "promotion": (
                "HOLD_FORMAL_G5_AND_H4" if not bad else "HOLD_STOP_GEOMETRY_DEFECT_4"
            ),
        }
        print(
            "ROBUSTNESS",
            lane,
            "T",
            len(source_rows),
            "bad",
            len(bad),
            "months",
            json.dumps(
                {
                    m: {n: round(v["Net2_bps"], 2) for n, v in z.items()}
                    for m, z in partitions.items()
                }
            ),
            "combined",
            stat.get("stage1_plus_stage2", {}),
            flush=True,
        )
    body = (
        json.dumps(
            evidence, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode()
    with (ROOT / "ROBUSTNESS.json").open("xb") as f:
        f.write(body)
    print(
        "ROBUSTNESS_SHA",
        sha(body),
        "RESULT_REF",
        evidence["parent_result_sha256"],
        flush=True,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    ROOT = args.root
    run()
