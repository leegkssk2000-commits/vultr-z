#!/usr/bin/env python3
"""Validate the parameter-free EAF_PSA_V1 Stage3 contract.

No signals, pair selection, numerical calibration, promotion, execution or orders.
The validator proves all 10 pair lanes are aligned and that each pair has a
complete sourced two-leg fee/slippage/funding envelope for every observed
notional bucket.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import eaf_stage3_pairs_replay as pair_adapter


def fail(msg: str) -> None:
    raise SystemExit(msg)


def slippage_map(cost: dict[str, Any], symbol: str) -> dict[float, dict[str, Any]]:
    rows = cost["slippage_floor_bps_by_symbol_and_notional"].get(symbol)
    if not isinstance(rows, list) or not rows:
        fail(f"HOLD_MISSING_SYMBOL_SLIPPAGE:{symbol}")
    out: dict[float, dict[str, Any]] = {}
    for row in rows:
        b = float(row["max_notional_usdt"])
        if b in out:
            fail(f"HOLD_DUPLICATE_NOTIONAL_BUCKET:{symbol}:{b}")
        out[b] = row
    return out


def validate_contract(contract: dict[str, Any]) -> None:
    assert contract["state"] == "PASS_PSA_PARAMETER_FREE_CONTRACT_HOLD_CALIBRATION"
    assert contract["research_only"] is True
    assert contract["execution_authority"] == "NONE"
    assert contract["order_authority"] == "BLOCKED"
    assert contract["selection_authority"] is False
    assert contract["promotion_authority"] is False
    assert contract["signal_generation_enabled"] is False
    assert contract["parameter_selection_allowed"] is False
    assert contract["baseline_engine_mutation_allowed"] is False
    assert contract["strategy_id"] == "EAF_PSA_V1"
    assert contract["universe"]["pair_selection_performed"] is False
    assert contract["two_leg_cost_contract"]["notional_bucket_selection_performed"] is False
    assert contract["two_leg_cost_contract"]["all_observed_notional_buckets_required"] is True
    assert contract["survivor_gate"]["survivor_selection_performed"] is False
    unresolved = contract["base_relationship_contract"]
    for key in (
        "cointegration_test_definition",
        "cointegration_significance_threshold",
        "formation_window",
        "trading_window",
        "spread_normalizer",
        "entry_extreme",
        "exit_neutral",
        "spread_stop",
        "half_life_limit",
    ):
        if "UNRESOLVED" not in str(unresolved[key]):
            fail(f"HOLD_UNSOURCED_NUMERIC_OR_METHOD_BOUND:{key}:{unresolved[key]}")


def validate_cost(cost: dict[str, Any], contract: dict[str, Any]) -> None:
    assert cost["state"] == "PASS_BINGX_REAL_OBSERVATION_COLLECTED_STRESS_PENDING"
    assert cost["calibration_mode"] == "real"
    assert cost["source_tier"] == "official"
    assert cost["execution_authority"] == "NONE"
    assert cost["order_authority"] == "BLOCKED"
    assert cost["promotion_authority"] is False
    assert cost["protected_mutations"] == 0
    mapping = contract["two_leg_cost_contract"]["symbol_mapping"]
    required = set(mapping.values())
    if set(cost["funding_p95_abs_pct_8h_by_symbol"]) != required:
        fail("HOLD_FUNDING_SYMBOL_COVERAGE")
    if set(cost["slippage_floor_bps_by_symbol_and_notional"]) != required:
        fail("HOLD_SLIPPAGE_SYMBOL_COVERAGE")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--contract", required=True, type=Path)
    ap.add_argument("--cost-model", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ns = ap.parse_args()

    contract = json.loads(ns.contract.read_text())
    cost = json.loads(ns.cost_model.read_text())
    validate_contract(contract)
    validate_cost(cost, contract)

    symbols = contract["universe"]["symbols"]
    pairs = contract["universe"]["unordered_pairs"]
    expected_pair_count = len(symbols) * (len(symbols) - 1) // 2
    canonical = {tuple(sorted(x)) for x in pairs}
    if len(pairs) != expected_pair_count or len(canonical) != expected_pair_count:
        fail(f"HOLD_PAIR_UNIVERSE_NOT_COMPLETE:{len(pairs)}:{len(canonical)}:{expected_pair_count}")

    mapping = contract["two_leg_cost_contract"]["symbol_mapping"]
    taker_pct = float(cost["taker_fee_pct"])
    pair_rows = []
    adapter_rows = []

    for left, right in pairs:
        if left not in symbols or right not in symbols or left == right:
            fail(f"HOLD_BAD_PAIR:{left}:{right}")
        adapter = pair_adapter.validate_two_leg(ns.data_dir / f"{left}.csv", ns.data_dir / f"{right}.csv")
        if adapter["state"] != "PASS_TWO_LEG_ADAPTER_CONTRACT" or adapter["gap_count"] != 0:
            fail(f"HOLD_PAIR_ADAPTER:{left}:{right}:{adapter['state']}:{adapter['gap_count']}")
        adapter_rows.append({
            "pair": [left, right],
            "state": adapter["state"],
            "aligned_rows": adapter["aligned_rows"],
            "gap_count": adapter["gap_count"],
            "left_sha256": adapter["left"]["sha256"],
            "right_sha256": adapter["right"]["sha256"],
        })

        bl, br = mapping[left], mapping[right]
        lm, rm = slippage_map(cost, bl), slippage_map(cost, br)
        buckets = sorted(set(lm) & set(rm))
        if set(lm) != set(rm) or not buckets:
            fail(f"HOLD_PAIR_BUCKET_MISMATCH:{left}:{right}")
        lf = float(cost["funding_p95_abs_pct_8h_by_symbol"][bl]["funding_p95_abs_pct_8h"])
        rf = float(cost["funding_p95_abs_pct_8h_by_symbol"][br]["funding_p95_abs_pct_8h"])
        envelopes = []
        for bucket in buckets:
            ls = float(lm[bucket]["slippage_bps_one_way"])
            rs = float(rm[bucket]["slippage_bps_one_way"])
            fee_rt_pct = 4.0 * taker_pct
            slippage_rt_pct = 2.0 * (ls + rs) / 100.0
            envelopes.append({
                "notional_bucket_usdt_per_leg": bucket,
                "taker_fee_pct_per_side_per_leg": taker_pct,
                "round_trip_two_leg_fee_pct": fee_rt_pct,
                "left_slippage_bps_one_way_p95": ls,
                "right_slippage_bps_one_way_p95": rs,
                "round_trip_two_leg_slippage_pct": slippage_rt_pct,
                "round_trip_fee_plus_slippage_pct_ex_funding": fee_rt_pct + slippage_rt_pct,
                "pair_abs_p95_funding_pct_per_8h": lf + rf,
                "funding_application": "pair_abs_p95_prorated_by_hold_duration_when_a_future_source_bound_signal_ledger_exists",
            })
        pair_rows.append({
            "pair": [left, right],
            "bingx_symbols": [bl, br],
            "pair_selection_performed": False,
            "bucket_selection_performed": False,
            "cost_envelopes": envelopes,
        })

    receipt = {
        "schema_version": "zel.eaf.stage3.psa_contract_validation.v1",
        "state": "PASS_PSA_ALL_PAIRS_ALIGNED_AND_COST_BOUND_HOLD_SIGNAL_CALIBRATION",
        "research_only": True,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "selection_authority": False,
        "promotion_authority": False,
        "signal_generation_enabled": False,
        "parameter_selection_allowed": False,
        "pair_selection_performed": False,
        "bucket_selection_performed": False,
        "pair_count": len(pair_rows),
        "notional_bucket_count": len(pair_rows[0]["cost_envelopes"]) if pair_rows else 0,
        "cost_receipt_sha256": cost["receipt_sha256"],
        "cost_observed_at": cost["observed_at"],
        "adapters": adapter_rows,
        "pair_cost_envelopes": pair_rows,
        "unresolved_blockers": contract["current_blockers"],
        "next": "source-bind formation/relationship/entry-exit-horizon semantics without numerical guessing; keep EAF_PSA_V1 signal generation disabled",
    }
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "state": receipt["state"],
        "pair_count": receipt["pair_count"],
        "notional_bucket_count": receipt["notional_bucket_count"],
        "cost_receipt_sha256": receipt["cost_receipt_sha256"],
        "signal_generation_enabled": receipt["signal_generation_enabled"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
