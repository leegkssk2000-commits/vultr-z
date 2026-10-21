"""Join already-published K126 evidence; no source replay, orders or rule selection.

This is an outcome-censored diagnostic, never a decision-time feature producer.
It adds origin coverage and units linkage; it does not rerun analyze.py or any
native strategy, calculate a new return series, or generate candidate signals.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path


PINS = {
    "diagnosis/ANATOMY.json": "2583c08dfa0e50885d5552358e7b35419d430bdad152eecfd4305408d22b5dbd",
    "diagnosis/INPUT_MANIFEST.json": "fadf94fae0685f746a26848c15327595e1c6d17cdf46bf746e53db99f8487028",
    "diagnosis/ENTRY_GEOMETRY_ALL126.json": "ed98e2ee712cdb57339d61fa7c823d46e39b20fd839c0b048985e38ec337e388",
    "diagnosis/RAW_PATHS_ALL126.json.gz": "68fda12ccefab90d2d6529cd6883ab4ec9fb34a954c790ce3d26db57cb6d929f",
    "completion/ROWS.json.gz": "5f45180aa762dc091c16e8fa2d208dcf027c16f795d9533911d2c11d73a30c77",
    "completion/PAIRED_ALL126.json.gz": "3bf6a370dae9e93d674ee49fc6d7fd1fdd8836e5bfd39de603d58629a7c20c9d",
    "completion/SUMMARY.json": "a69e1cce4b5dffe004d49820ced626962795952f2e7b06226eb71ad77b8f7812",
    "prepared/FREEZE.json": "f17647a26cc39abb1100a4e26b129ff7e1b1ef9e016c648723361b0a4bae14f7",
}
REFS = {
    "diagnosis": "4a5985e362959f8460726fb56780fc10eab04a8b",
    "completion": "81a12c422ee9329996d2f6b983267d2def490d4b",
    "prepared": "b692aa8b4a6ab955afa11ee4a7a07e56a96a9c36",
    "original_control": "308bd2deb7acaaacf1adb582206e78262d72c9d1",
}


def load_inputs(root: Path) -> dict:
    result = {}
    for name, expected in PINS.items():
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("INPUT_SHA_MISMATCH:" + name)
        result[name] = json.loads(gzip.decompress(raw) if name.endswith(".gz") else raw)
    return result


def keyed(rows: list, field: str) -> dict:
    out = {tuple(row[field]): row for row in rows}
    if len(out) != len(rows):
        raise ValueError("DUPLICATE_TRADE_KEY:" + field)
    return out


def build(root: Path) -> dict:
    data = load_inputs(root)
    geometry = keyed(data["diagnosis/ENTRY_GEOMETRY_ALL126.json"], "key")
    paths = keyed(data["diagnosis/RAW_PATHS_ALL126.json.gz"], "trade_key")
    pairs = keyed(data["completion/PAIRED_ALL126.json.gz"]["paired"], "key")
    trades = data["completion/ROWS.json.gz"]["trades"]
    rows = {(t["symbol"], int(t["side"]), int(t["signal_ts_ms"])): t for t in trades}
    if len(rows) != 126 or not (geometry.keys() == paths.keys() == pairs.keys() == rows.keys()):
        raise ValueError("ALL126_KEY_COVERAGE_MISMATCH")
    output = []
    for key, g in geometry.items():
        t, pair = rows[key], pairs[key]
        signal = t["signal"]
        entry, risk, atr, side = g["entry_price"], g["initial_risk_price"], g["frozen_ATR_price"], g["side"]
        if not math.isclose(risk, side * (entry - g["initial_stop"]), rel_tol=1e-12):
            raise ValueError("INITIAL_RISK_MISMATCH")
        if not math.isclose(risk / atr, g["initial_risk_ATR"], rel_tol=1e-12):
            raise ValueError("ATR_NORMALIZATION_MISMATCH")
        # Same-time completed previous close precedes the next actual open. A
        # stop-hit terminal bar is excluded wholesale: its intrabar order is
        # unknown and native stop-first never credits its favorable extremum.
        complete = [b for b in paths[key]["bars"]
                    if t["entry_ts_ms"] <= b["open_ts_ms"] < t["exit_ts_ms"]
                    and b["available_ts_ms"] <= t["exit_ts_ms"]]
        if t["reason"] == "STOP_FIRST":
            complete = [b for b in complete if b["available_ts_ms"] < t["outcome_available_ts_ms"]]
        if any(b["available_ts_ms"] < b["close_ts_ms"] for b in complete):
            raise ValueError("BAR_BEFORE_CLOSE")
        progress = []
        mfe_price = 0.0
        for b in complete:
            favorable = b["high"] - entry if side == 1 else entry - b["low"]
            mfe_price = max(mfe_price, favorable)
            progress.append({
                "available_ts_ms": b["available_ts_ms"],
                "close_price": b["close"],
                "directional_close_price": side * (b["close"] - entry),
                "directional_close_R": side * (b["close"] - entry) / risk,
                "cumulative_completed_bar_mfe_price": mfe_price,
                "cumulative_completed_bar_mfe_R": mfe_price / risk,
                "cumulative_completed_bar_mfe_signal_ATR": mfe_price / atr,
            })
        # Validate units/censoring against the already-saved observation, not a
        # new strategy result. Raw export has finite JSON rounding precision.
        if not math.isclose(mfe_price / risk, t["mfe_R"], rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError("SAVED_MFE_UNITS_LINKAGE_MISMATCH:" + str(key))
        first_adverse = next((i for i, p in enumerate(progress) if p["directional_close_price"] < 0), None)
        recovered = (next((p["available_ts_ms"] for p in progress[first_adverse + 1:]
                           if p["directional_close_price"] > 0), None)
                     if first_adverse is not None else None)
        output.append({
            "key": list(key),
            "signal_open_ts_ms": signal["signal_open_ts_ms"],
            "signal_available_ts_ms": signal["signal_ts_ms"],
            "feature_available_ts_ms": signal["meta"]["feature_available_ts_ms"],
            "entry_ts_ms": t["entry_ts_ms"],
            "origin_coverage": {
                "native_touch_open_ts_ms": None,
                "native_touch_available_ts_ms": None,
                "native_reference_assignment_open_ts_ms": None,
                "native_reference_assignment_available_ts_ms": None,
                "status": "UNKNOWN_NATIVE_LIFECYCLE_TRACE_NOT_IN_SAVED_INPUTS",
                "latest_raw_matching_extreme_available_ts_ms": g["latest_matching_extreme_available_ts_ms"],
                "raw_match_is_native_assignment": False,
            },
            "entry_frozen": {
                "entry_price": entry,
                "native_invalidation_price": g["invalidation_price"],
                "initial_stop": g["initial_stop"],
                "initial_risk_price": risk,
                "signal_ATR_price": atr,
                "initial_risk_signal_ATR": risk / atr,
                "existing_scratch_hurdle_price": 0.40 * risk,
                "existing_scratch_hurdle_signal_ATR": 0.40 * risk / atr,
            },
            "saved_alive_path_DIAGNOSTIC_NOT_POLICY": {
                "complete_bar_count_before_terminal_check": len(complete),
                "first_five_completed_closes": progress[:5],
                "first_adverse_close_available_ts_ms": progress[first_adverse]["available_ts_ms"] if first_adverse is not None else None,
                "later_favorable_close_after_adverse_ts_ms": recovered,
                "first_close_adverse": bool(progress and progress[0]["directional_close_price"] < 0),
                "saved_exit_used_only_to_censor_path": True,
                "terminal_stop_bar_extrema_included": False,
            },
            "outcome_labels_NOT_FEATURES": {
                **g["outcome_labels_NOT_FEATURES"],
                "recorded_final_mfe_price": t["mfe_R"] * risk,
                "recorded_final_mfe_signal_ATR": t["mfe_R"] * risk / atr,
                "previous_whole_structure_rule_first_failure": pair["first_failure"],
            },
        })
    winners = [r for r in output if r["outcome_labels_NOT_FEATURES"]["net1x"] > 0]
    widest = max(winners, key=lambda r: r["entry_frozen"]["initial_risk_signal_ATR"])
    initial_recovery = [r for r in winners if r["saved_alive_path_DIAGNOSTIC_NOT_POLICY"]["first_close_adverse"]
                        and r["saved_alive_path_DIAGNOSTIC_NOT_POLICY"]["later_favorable_close_after_adverse_ts_ms"] is not None]
    summary = data["completion/SUMMARY.json"]
    return {
        "schema": "zel.k126.saved_origin_risk_linkage.v1",
        "scope_key": "K126_WORST8_STATE_AND_LOSS_REPAIR_C_V1",
        "classification": "SAVED_INPUT_ORIGIN_COVERAGE_AND_UNITS_LINKAGE_ONLY",
        "new_native_price_replays": 0,
        "new_economic_comparisons": 0,
        "original_anatomy_recomputed": False,
        "input_refs": REFS,
        "input_sha256": PINS,
        "all126_joined": len(output),
        "all126_saved_mfe_unit_and_terminal_censoring_matches": len(output),
        "missing_single_artifact": "Per-step native lifecycle trace linking each accepted signal to touch/reference assignment, raw before/after state, wrapper admission decision and reset/rearm events with available timestamps.",
        "missing_origin_count": len(output),
        "interpretation": [
            "Raw paths begin at signal open. They lack the prior enriched EMA/GMMA/ADX sequence and wrapper decisions needed to identify native state origins.",
            "A raw equal-price timestamp is not proof the state assigned that price then; equal extrema need not replace the earliest contributing origin.",
            "Initial risk is frozen from actual entry and initial stop. Later tightening changes live stop, not MFE_R denominator.",
            "The existing 0.40R scratch hurdle is 0.40 * initial_risk/ATR in signal-ATR units; conversion does not propose an ATR threshold.",
            "Scratch means insufficient normalized excursion, not necessarily negative PnL. The widest winning trade itself scratches profitably after adverse closes recover.",
            "Neither stale-state causation nor harmlessness can be established from these saved paths. Source-state observer execution remains for A.",
        ],
        "previous_economics_QUOTED_NOT_RECOMPUTED": {
            "source_sha256": PINS["completion/SUMMARY.json"],
            "candidate": summary["candidate"],
            "net1x": summary["child"]["cost1x"]["Net_bps"],
            "net2x": summary["child"]["cost2x"]["Net_bps"],
            "used_DEV_only": True,
        },
        "counterexamples_DIAGNOSTIC_ONLY": {
            "widest_risk_winner_key": widest["key"],
            "first_completed_close_adverse_then_recovered_winner_count": len(initial_recovery),
            "first_completed_close_adverse_then_recovered_winner_keys": [r["key"] for r in initial_recovery],
            "selection_is_retrospective_documentation_not_execution_condition": True,
        },
        "all126": output,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.input_root)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({"all126_joined": result["all126_joined"], "missing_origin_count": result["missing_origin_count"],
                      "new_native_price_replays": 0, "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
