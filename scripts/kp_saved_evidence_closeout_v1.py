"""Saved-only K.P amount reconciliation. No market loader, strategy import or replay.

A fixed 2R/10% model permits amount reconstruction from saved MFE and entry
geometry. This does NOT recover the original partial execution timestamp, raw
market path, individual settlement costs or a continuous account NAV.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

CANDIDATE = "scalp7_keltner_hg_parent_utc30m_v2"
IDENTITY = "389550fddc888266eaf336cdec83a63b05f0e5da198fe21d07a2cf171e4f5710"
BASE = "research/campaigns/scalp7_20260915/broad_rebuild_v2/"
LEDGER = BASE + "results/" + CANDIDATE + ".trades.json.gz"
RESULT = BASE + "results/" + CANDIDATE + ".json"
FREEZE = BASE + "POSITIVE_LANES_FREEZE_V2.json"
PINS = {
    LEDGER: "8863caa8231282fbd7dfd5660811b74e007c018c9cdafdaa52c24830cddfd989",
    RESULT: "7dbbae73964f94db9a7835f9bb57e75ea0e49c709ff0e18a33563e7e0c8d3626",
    FREEZE: "070b5b8db12ba317c11139d3703f0549e6ccc57216bd297dba30cf8a7b3ee4ee",
    "backend/research/rebuild/scalp7_positive_lanes_v2.py": "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2",
    "backend/research/rebuild/scalp7_execution_v2.py": "d1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1",
}
TOL_BPS = 1e-7  # Arithmetic tolerance only; never an economic acceptance gate.


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def finite(value: Any) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), "NUMERIC_REQUIRED")
    result = float(value)
    require(math.isfinite(result), "NONFINITE_VALUE")
    return result


def strict_load(raw: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            require(key not in out, "DUPLICATE_JSON_KEY")
            out[key] = value
        return out

    def bad(value: str) -> None:
        raise ValueError("NONFINITE_JSON:" + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def pinned(root: Path, path: str) -> bytes:
    full = (root / path).resolve(strict=True)
    require(full.is_relative_to(root.resolve()), "PATH_OUTSIDE_REPO")
    raw = full.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == PINS[path], "SOURCE_HASH_CHANGED:" + path)
    return raw


def reconstruct_amount(row: dict[str, Any]) -> dict[str, Any]:
    """Infer model amounts without reading saved gross/net as an input to them.

    For a COMPLETED trade of these pinned functions, recorded MFE >=2 means
    the stop-first loop survived a bar touching the sole frozen 2R partial.
    That callback fills exactly 10% once at the declared price. The final MFE
    does not encode *which* bar first touched it. Do not manufacture that time.
    """
    signal = row["signal"]
    require(row["identity"] == signal["identity"] == CANDIDATE, "WRONG_CANDIDATE")
    require(row["timeframe_min"] == signal["timeframe_min"] == 30, "WRONG_TIMEFRAME")
    require(row["execution_profile"] == "UTC_NEXT_OPEN_STOP_FIRST_GAPS_UNRESOLVED_V2", "WRONG_ENGINE_PROFILE")
    require(row["mfe_mae_semantics"] == "AFTER_STOP_CHECK_CONSERVATIVE_NO_INTRABAR_PATH", "WRONG_MFE_SEMANTICS")
    require(row["order_authority"] == "BLOCKED" and not row.get("legs"), "WRONG_AUTHORITY_OR_PRODUCT")
    symbol = row["symbol"]
    require(symbol == signal["symbol"] and set(row["entry_prices"]) == set(row["exit_prices"]) == {symbol}, "WRONG_LEGS")
    side = row["side"]
    require(side in (-1, 1) and not isinstance(side, bool) and side == signal["side"], "WRONG_SIDE")
    require(row["partition"] in ("validation", "rolling"), "WRONG_PARTITION")
    for key in ("entry_ts_ms", "exit_ts_ms", "outcome_available_ts_ms", "signal_ts_ms"):
        require(isinstance(row[key], int) and not isinstance(row[key], bool), "INTEGER_TIME_REQUIRED")
    require(row["signal_ts_ms"] <= row["entry_ts_ms"] <= row["exit_ts_ms"] <= row["outcome_available_ts_ms"], "WRONG_CHRONOLOGY")
    require(signal["take_profit_r"] is None and signal["partial_take_profit_r"] == 2.0
            and signal["partial_fraction"] == 0.10 and signal["max_hold_bars"] == 25, "FROZEN_LIFECYCLE_CHANGED")
    entry = finite(row["entry_prices"][symbol])
    terminal = finite(row["exit_prices"][symbol])
    stop = finite(signal["stop_price"])
    meta = signal["meta"]
    atr = finite(meta["entry_cost_gate"]["atr_price"])
    cost = finite(row["cost_bps"])
    mfe = finite(row["mfe_R"])
    require(min(entry, terminal, atr, cost) > 0 and mfe >= 0, "INVALID_PRICE_COST_OR_MFE")
    require(meta["fallback_stop_atr_mult"] == 1.2 and meta["be_arm_r"] == 1.0
            and meta["entry_cost_gate"]["min_ratio"] == 4.5, "FROZEN_GEOMETRY_CHANGED")
    require(math.isclose(cost, finite(meta["frozen_cost_bps"]), rel_tol=0, abs_tol=TOL_BPS), "COST_BINDING_CHANGED")
    require(atr / entry * 10000 / cost >= 4.5, "SAVED_ENTRY_GATE_FAILED")
    fallback_used = side * (entry - stop) <= 0
    if fallback_used:
        stop = entry - side * 1.2 * atr
    risk = side * (entry - stop)
    require(stop > 0 and risk > 0, "NONADVERSE_INITIAL_STOP")
    partial = mfe >= 2.0
    fraction = 0.1 if partial else 0.0
    partial_price = entry + side * 2.0 * risk if partial else None
    part_bps = fraction * side * (partial_price / entry - 1) * 10000 if partial_price is not None else 0.0
    final_bps = (1 - fraction) * side * (terminal / entry - 1) * 10000
    reconstructed = part_bps + final_bps
    saved_gross = finite(row["gross_bps"])
    saved_net = finite(row["net_bps"])
    require(abs(reconstructed - saved_gross) <= TOL_BPS, "GROSS_AMOUNT_MISMATCH")
    require(abs(saved_gross - cost - saved_net) <= TOL_BPS, "NET_COST_MISMATCH")
    return {
        "trade_key": [row["window_label"], symbol, side, row["signal_ts_ms"], row["entry_ts_ms"], row["exit_ts_ms"]],
        "partition": row["partition"], "reason": row["reason"],
        "partial_inferred_from_saved_model_state": partial,
        "partial_original_event_recovered": False,
        "partial_timestamp_ms": None,
        "partial_fraction_model_derived": fraction,
        "partial_price_model_derived": partial_price,
        "partial_gross_bps_model_derived": part_bps,
        "terminal_gross_bps_model_derived": final_bps,
        "gross_bps_model_derived": reconstructed,
        "gross_residual_bps": reconstructed - saved_gross,
        "entry_fallback_applied": fallback_used,
        "net_1x_bps": saved_net,
        "net_2x_bps": saved_gross - 2 * cost,
        "cost_multiplier_is_leverage": False,
        "net_positive_1x_to_nonpositive_2x": saved_net > 0 and saved_gross - 2 * cost <= 0,
        "fee_be_plus2_price_match": (not partial and row["reason"] == "STOP_FIRST"
              and abs(side * (terminal / entry - 1) * 10000 - cost - 2.0) <= TOL_BPS),
    }


def metrics(rows: list[dict[str, Any]], multiplier: float) -> dict[str, Any]:
    require(multiplier in (1.0, 2.0), "ONLY_FROZEN_COST_SCENARIOS")
    nets = [finite(x["gross_bps"]) - multiplier * finite(x["cost_bps"]) for x in rows]
    gains = math.fsum(n for n in nets if n > 0)
    losses = -math.fsum(n for n in nets if n < 0)
    return {"T": len(rows), "wins": sum(n > 0 for n in nets),
            "WR_pct": 100 * sum(n > 0 for n in nets) / len(rows) if rows else None,
            "Gross_bps": math.fsum(finite(x["gross_bps"]) for x in rows),
            "Cost_bps": math.fsum(multiplier * finite(x["cost_bps"]) for x in rows),
            "Net_bps": math.fsum(nets), "PF": gains / losses if losses else None}


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks = [reconstruct_amount(row) for row in rows]
    keys = [tuple(x["trade_key"]) for x in checks]
    require(len(set(keys)) == len(keys), "DUPLICATE_TRADE")
    rolling = [r for r in rows if r["partition"] == "rolling"]
    rolling_checks = [r for r in checks if r["partition"] == "rolling"]
    flips = [c for c in rolling_checks if c["net_positive_1x_to_nonpositive_2x"]]
    cohorts: dict[str, Any] = {}
    for partial in (False, True):
        selected = [r for r, c in zip(rows, checks) if r["partition"] == "rolling"
                    and c["partial_inferred_from_saved_model_state"] == partial]
        cohorts["reached_2R_partial" if partial else "did_not_reach_2R_partial"] = {
            "1x": metrics(selected, 1.0), "2x": metrics(selected, 2.0),
            "selection_is_post_outcome": True, "entry_filter_authorized": False}
    reasons = {reason: {"1x": metrics([r for r in rolling if r["reason"] == reason], 1),
                        "2x": metrics([r for r in rolling if r["reason"] == reason], 2)}
               for reason in sorted({r["reason"] for r in rolling})}
    return {
        "schema": "kp.saved_amount_closeout.v1", "candidate": CANDIDATE, "identity_key": IDENTITY,
        "evidence_mode": "MODEL_DERIVED_AMOUNTS_FROM_SAVED_STATE_NOT_RAW_CASHFLOW",
        "arithmetic_status": "PASS", "saved_rows": len(rows), "rolling_rows": len(rolling),
        "partial_amount_rows_all": sum(c["partial_inferred_from_saved_model_state"] for c in checks),
        "partial_amount_rows_rolling": sum(c["partial_inferred_from_saved_model_state"] for c in rolling_checks),
        "raw_partial_event_rows_recovered": 0,
        "max_abs_gross_residual_bps": max((abs(c["gross_residual_bps"]) for c in checks), default=0),
        "rolling1x": metrics(rolling, 1), "rolling2x": metrics(rolling, 2),
        "cost_flip": {"T": len(flips), "reason_counts": dict(Counter(c["reason"] for c in flips)),
                      "fee_be_plus2_matches": sum(c["fee_be_plus2_price_match"] for c in flips),
                      "net1x_bps": math.fsum(c["net_1x_bps"] for c in flips),
                      "net2x_bps": math.fsum(c["net_2x_bps"] for c in flips)},
        "post_outcome_cohorts": cohorts, "exit_reason_groups": reasons, "trade_amount_checks": checks,
        "new_market_full_runs": 0, "signal_generation_calls": 0, "strategy_rule_changes": 0,
        "g4_formal_pass": None, "g5_eligibility": None, "g5_execution_started": False,
        "g4_g5_blocker": "EXACT_CURRENT_KP_ADMISSION_CONTRACT_NOT_BOUND",
        "account_nav": None, "account_dd": None, "leverage": None,
        "historical_funding_settlements": "NOT_RECONSTRUCTED_REFERENCE_RESERVE_PRESERVED",
        "original_execution_credit": "UNCHANGED_COMPLETED_ONCE",
        "authority": {"order": "BLOCKED", "live": "BLOCKED", "promotion": False},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve(strict=True)
    sources = {name: pinned(root, name) for name in PINS}
    original = strict_load(sources[RESULT])
    require(original["identity_key"] == IDENTITY and original["promotion"] is False, "WRONG_RESULT")
    data = strict_load(gzip.decompress(sources[LEDGER]))
    require(data["unresolved"] == [], "UNRESOLVED_INPUT_UNSUPPORTED")
    report = analyze(data["trades"])
    for label in ("rolling1x", "rolling2x"):
        for key in ("T", "WR_pct", "Gross_bps", "Cost_bps", "Net_bps", "PF"):
            require(abs(report[label][key] - original[label][key]) <= TOL_BPS, "PUBLISHED_METRIC_MISMATCH:" + label + ":" + key)
    require(report["saved_rows"] == 119 and report["partial_amount_rows_all"] == 32, "FROZEN_ROW_COUNT_CHANGED")
    report["pinned_sources"] = PINS
    report["code_last_changed_before_original_run"] = "scalp7_execution_v2.py:95af7914a01b24e9077ffcb28bd8f2233bca5541;2026-09-15T19:15:15Z"
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "KP_AMOUNT_AND_COST_DIAGNOSIS.json"
    require(not target.exists(), "OUTPUT_EXISTS")
    target.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("trade_amount_checks", "pinned_sources", "exit_reason_groups", "post_outcome_cohorts")}, indent=2))


if __name__ == "__main__":
    main()
