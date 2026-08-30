#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_parallel_prospective_v1 as base

ROOT = Path(__file__).resolve().parents[3]
V1_FREEZE_AUDIT = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v1.json"
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
V2_CHILD_LATEST = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
LATEST = ROOT / "backend/research/rebuild/a1_top5_parallel_prospective_latest.json"
EXPECTED_BOUNDARY_MS = 1788048000000
EXPECTED_BOUNDARY_UTC = "2026-08-30T00:00:00Z"
EXPECTED_SYMBOLS = [
    "1000PEPE-USDT",
    "BCH-USDT",
    "BTC-USDT",
    "ETH-USDT",
    "HYPE-USDT",
    "LINK-USDT",
    "SOL-USDT",
]
EXPECTED_COST_BPS = 20.0


def _v1_burned_rows() -> dict[str, dict[str, Any]]:
    old = base._read(V1_FREEZE_AUDIT)
    if old.get("schema_version") != "zel.a1.top5.replacement_child_freeze.v1":
        raise RuntimeError("V1_BURN_AUDIT_SCHEMA_DRIFT")
    if old.get("state") != "FROZEN_REPLACEMENT_CHILDREN_PRE_PROSPECTIVE":
        raise RuntimeError("V1_BURN_AUDIT_STATE_DRIFT")
    base._assert_blocked(old, "V1_BURN_AUDIT")
    rows = {
        str(x.get("lane_id")): dict(x)
        for x in old.get("children") or []
        if isinstance(x, Mapping) and x.get("lane_id")
    }
    if set(rows) != set(base.REPLACEMENT_LANES):
        raise RuntimeError("V1_BURN_AUDIT_LANE_SET_DRIFT")
    return rows


def _freeze_rows_v2(freeze: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(freeze, Mapping):
        return {}
    if freeze.get("schema_version") != "zel.a1.top5.replacement_child_freeze.v2":
        raise RuntimeError("V2_REPLACEMENT_FREEZE_SCHEMA_DRIFT")
    if freeze.get("state") != "FROZEN_REPLACEMENT_CHILDREN_V2_PRE_PROSPECTIVE":
        raise RuntimeError("V2_REPLACEMENT_FREEZE_STATE_DRIFT")
    base._assert_blocked(freeze, "V2_REPLACEMENT_FREEZE")
    boundary = freeze.get("prospective_boundary") or {}
    if int(boundary.get("ms") or 0) != EXPECTED_BOUNDARY_MS or str(boundary.get("utc") or "") != EXPECTED_BOUNDARY_UTC:
        raise RuntimeError("V2_REPLACEMENT_BOUNDARY_DRIFT")
    if list(freeze.get("frozen_symbol_universe") or []) != EXPECTED_SYMBOLS:
        raise RuntimeError("V2_REPLACEMENT_SYMBOL_UNIVERSE_DRIFT")
    if abs(float((freeze.get("cost_model") or {}).get("cost_bps_per_trade") or 0.0) - EXPECTED_COST_BPS) > 1e-12:
        raise RuntimeError("V2_REPLACEMENT_COST_DRIFT")
    retirement = freeze.get("v1_retirement") or {}
    if retirement.get("state") != "RETIRED_ZERO_EVIDENCE_SUPERSEDED_BY_V2":
        raise RuntimeError("V1_RETIREMENT_NOT_PROVEN")
    if int(retirement.get("total_consumed_T") or 0) != 0 or retirement.get("economic_evidence_lost") is not False:
        raise RuntimeError("V1_RETIREMENT_EVIDENCE_DRIFT")

    active = {
        str(x.get("lane_id")): dict(x)
        for x in freeze.get("children") or []
        if isinstance(x, Mapping) and x.get("lane_id")
    }
    if set(active) != set(base.REPLACEMENT_LANES):
        raise RuntimeError("V2_REPLACEMENT_FREEZE_LANE_SET_DRIFT")
    old = _v1_burned_rows()
    out: dict[str, dict[str, Any]] = {}
    for lane_id in base.REPLACEMENT_LANES:
        now = active[lane_id]
        prior = old[lane_id]
        burned_ids = [str(x) for x in prior.get("burned_parent_raw_observer_closed_trade_ids") or [] if str(x)]
        burned_t = int(prior.get("burned_parent_raw_observer_T") or 0)
        if len(burned_ids) != burned_t or len(burned_ids) != len(set(burned_ids)):
            raise RuntimeError(f"V1_BURN_IDENTITY_DRIFT:{lane_id}")
        if int(now.get("burned_parent_raw_observer_T") or 0) != burned_t:
            raise RuntimeError(f"V2_BURN_COUNT_DRIFT:{lane_id}")
        if int(now.get("predecessor_v1_consumed_T") or 0) != 0:
            raise RuntimeError(f"V2_PREDECESSOR_CONSUMPTION_DRIFT:{lane_id}")
        if now.get("alpha_dsl_identical_to_v1") is not True:
            raise RuntimeError(f"V2_ALPHA_DSL_DRIFT:{lane_id}")
        out[lane_id] = {
            **now,
            "burned_parent_raw_observer_closed_trade_ids": burned_ids,
            "burned_parent_raw_observer_T": burned_t,
        }
    return out


def _child_rows_v2(child_latest: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(child_latest, Mapping):
        return {}
    if child_latest.get("schema_version") != "zel.a1.top5.replacement_child.prospective.receipt.v2":
        raise RuntimeError("V2_REPLACEMENT_CHILD_RECEIPT_SCHEMA_DRIFT")
    if child_latest.get("state") != "PASS_PROSPECTIVE_V2_CHILD_COLLECTION_ACTIVE":
        raise RuntimeError("V2_REPLACEMENT_CHILD_RECEIPT_NOT_ACTIVE")
    base._assert_blocked(child_latest, "V2_REPLACEMENT_CHILD_RECEIPT")
    if int(child_latest.get("boundary_ms") or 0) != EXPECTED_BOUNDARY_MS:
        raise RuntimeError("V2_CHILD_BOUNDARY_DRIFT")
    if list(child_latest.get("frozen_symbol_universe") or []) != EXPECTED_SYMBOLS:
        raise RuntimeError("V2_CHILD_SYMBOL_UNIVERSE_DRIFT")
    if abs(float(child_latest.get("fixed_cost_bps_per_trade") or 0.0) - EXPECTED_COST_BPS) > 1e-12:
        raise RuntimeError("V2_CHILD_COST_DRIFT")
    if child_latest.get("predecessor_v1_retired") is not True or int(child_latest.get("predecessor_v1_total_closed_T") or 0) != 0:
        raise RuntimeError("V2_CHILD_PREDECESSOR_RETIREMENT_DRIFT")
    if child_latest.get("g5_broad_population_mutated") is not False:
        raise RuntimeError("G5_POPULATION_MUTATION_FORBIDDEN")
    rows = child_latest.get("lanes")
    if not isinstance(rows, Mapping) or set(rows) != set(base.REPLACEMENT_LANES):
        raise RuntimeError("V2_REPLACEMENT_CHILD_LANES_DRIFT")
    return {str(k): dict(v) for k, v in rows.items() if isinstance(v, Mapping)}


def _install_v2_owner() -> None:
    base.REPLACEMENT_FREEZE = V2_FREEZE
    base.REPLACEMENT_CHILD_LATEST = V2_CHILD_LATEST
    base._freeze_rows = _freeze_rows_v2
    base._child_rows = _child_rows_v2


def run(output: Path, previous_path: Path | None = None, rolling_path: Path = base.ROLLING) -> dict[str, Any]:
    _install_v2_owner()
    result = base.run(output, previous_path, rolling_path)
    result["replacement_owner_generation"] = "V2_EXPANDED_FROZEN_SYMBOL_UNIVERSE"
    result["replacement_predecessor_v1_retired_zero_evidence"] = True
    result["replacement_frozen_symbol_universe"] = EXPECTED_SYMBOLS
    result["replacement_fixed_cost_bps_per_trade"] = EXPECTED_COST_BPS
    result["replacement_boundary_ms"] = EXPECTED_BOUNDARY_MS
    result["replacement_boundary_utc"] = EXPECTED_BOUNDARY_UTC
    result["g5_broad_population_mutated"] = False
    result["paid_provider_calls"] = 0
    for lane_id in base.REPLACEMENT_LANES:
        lane = result["lanes"][lane_id]
        lane["fresh_evidence_owner_generation"] = "V2"
        lane["frozen_symbol_universe"] = EXPECTED_SYMBOLS
        lane["fixed_cost_bps_per_trade"] = EXPECTED_COST_BPS
        lane["predecessor_v1_consumed_T"] = 0
        lane["next"] = "FRESH_REPLACEMENT_CHILD_V2_PROSPECTIVE_COLLECTOR_OWNS_COLLECTION"
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = base._sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    _install_v2_owner()
    freeze = base._read(V2_FREEZE)
    child = base._read(V2_CHILD_LATEST)
    rows = _freeze_rows_v2(freeze)
    child_rows = _child_rows_v2(child)
    assert set(rows) == set(base.REPLACEMENT_LANES)
    assert set(child_rows) == set(base.REPLACEMENT_LANES)
    assert all(len(x["burned_parent_raw_observer_closed_trade_ids"]) == int(x["burned_parent_raw_observer_T"]) for x in rows.values())
    assert all(int(x.get("predecessor_v1_consumed_T") or 0) == 0 for x in child_rows.values())
    assert EXPECTED_COST_BPS == 20.0 and len(EXPECTED_SYMBOLS) == 7
    print("PASS_A1_TOP5_PARALLEL_PROSPECTIVE_V2_BRIDGE_SELF_TEST")
    print("PASS_V1_BURN_IDENTITIES_RETAINED_V2_CHILD_OWNS_FRESH_EVIDENCE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rolling", type=Path, default=base.ROLLING)
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_parallel_prospective_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out, args.previous, args.rolling)
    print(json.dumps({
        "state": r["state"],
        "owner_generation": r["replacement_owner_generation"],
        "replacement_lane_T": {k: r["lanes"][k]["replacement_child_closed_T"] for k in base.REPLACEMENT_LANES},
        "primary_g4_T": r["lanes"]["trend_rider_primary_wr8125"]["g4_consumable_T"],
        "broad_g5_T": r["lanes"]["trend_rider_broad_wr7000"]["g5_postlock_closed_T"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
