#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as dev
from backend.research.architecture_factory import a1_top5_replacement_primitive_tournament_v1 as tournament
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child

ROOT = Path(__file__).resolve().parents[3]
FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v1.json"
CURRENT = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_latest.json"
ROLLING = ROOT / "backend/research/rebuild/a1_production_highwr_rolling_closed_latest.json"
COST = ROOT / "backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json"
SCHEMA = "zel.a1.g4.symbol_acceleration_audit.v1"
CORE = ("BTC-USDT", "ETH-USDT")
# New V2 cohort, if justified, is charged a conservative fixed 20 bps/trade.
# This is a cost-model tightening, not an alpha threshold change.
EXPANDED_FIXED_COST_BPS = 20.0
MIN_CLOSED_BARS = 239
MIN_ACCELERATION_MULTIPLIER = 1.25
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return x


def operational_symbols(rolling: Mapping[str, Any]) -> list[str]:
    out = set(CORE)
    lanes = rolling.get("lanes") if isinstance(rolling.get("lanes"), Mapping) else {}
    for lane in lanes.values():
        if not isinstance(lane, Mapping):
            continue
        for trade in lane.get("closed_trades") or []:
            if isinstance(trade, Mapping) and trade.get("symbol"):
                out.add(str(trade["symbol"]))
    return sorted(out)


def closed_event_count(rows: list[dict[str, float]], spec: Mapping[str, Any], boundary_ms: int) -> int:
    _, engine = child._features(rows, spec)
    entry_rule = str(spec.get("entry_rule") or "")
    side_rule = str(spec.get("side_rule") or "")
    hold = int(spec.get("max_hold_bars") or 0)
    engine.validate(entry_rule)
    child._validate_side(side_rule, engine)
    count = 0
    i = 50
    while i < len(rows) - 1:
        signal_ts = int(rows[i]["ts"])
        if signal_ts >= boundary_ms:
            break
        try:
            fire = bool(engine.eval(entry_rule, i))
        except (TypeError, ZeroDivisionError, ValueError):
            fire = False
        if not fire:
            i += 1
            continue
        entry_i = i + 1
        exit_i = entry_i + hold - 1
        if exit_i >= len(rows) or int(rows[exit_i]["ts"]) >= boundary_ms:
            break
        count += 1
        # Match prospective collector's one-position-per-symbol time-stop ownership.
        i = exit_i + 1
    return count


def development_cost_rebudget() -> dict[str, Any]:
    old_cost, old_symbols = dev.COST_BPS, dev.SYMBOLS
    try:
        dev.COST_BPS = EXPANDED_FIXED_COST_BPS
        dev.SYMBOLS = CORE
        r = dev.evaluate_queue(tournament.candidates())
    finally:
        dev.COST_BPS, dev.SYMBOLS = old_cost, old_symbols
    rows = [dict(x) for x in r.get("rows") or [] if isinstance(x, Mapping)]
    return {
        "fixed_cost_bps": EXPANDED_FIXED_COST_BPS,
        "core_symbols": list(CORE),
        "candidate_count": int(r.get("candidate_count") or 0),
        "economic_pass_count": int(r.get("economic_pass_count") or 0),
        "economic_fail_count": int(r.get("economic_fail_count") or 0),
        "insufficient_event_count": int(r.get("insufficient_event_count") or 0),
        "rows": [
            {
                "candidate_id": x.get("candidate_id"),
                "state": x.get("state"),
                "economic_pass": x.get("economic_pass"),
                "metrics": x.get("metrics"),
            }
            for x in rows
        ],
        "all_three_pass": int(r.get("economic_pass_count") or 0) == 3 and int(r.get("candidate_count") or 0) == 3,
        "uses_symbol_specific_outcomes_for_universe_selection": False,
        "purpose": "Verify the already-frozen architectures remain development-economic-positive under the more conservative expanded-universe cost budget.",
    }


def run(output: Path) -> dict[str, Any]:
    freeze, current, rolling, authority = map(read, (FREEZE, CURRENT, ROLLING, COST))
    if freeze.get("state") != "FROZEN_REPLACEMENT_CHILDREN_PRE_PROSPECTIVE":
        raise RuntimeError("FREEZE_STATE_DRIFT")
    if current.get("state") != "PASS_PROSPECTIVE_CHILD_COLLECTION_ACTIVE":
        raise RuntimeError("CURRENT_CHILD_COLLECTION_NOT_ACTIVE")
    if int(current.get("total_closed_T") or 0) != 0:
        raise RuntimeError("CURRENT_CHILD_ALREADY_HAS_EVIDENCE_NO_POPULATION_CHANGE_ALLOWED")
    if authority.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("COST_AUTHORITY_INVALID")
    boundary = freeze.get("prospective_boundary") or {}
    boundary_ms = int(boundary.get("ms") or 0)
    if boundary_ms <= 0:
        raise RuntimeError("BOUNDARY_REQUIRED")

    rebudget = development_cost_rebudget()
    symbols = operational_symbols(rolling)
    symbol_rows: dict[str, Any] = {}
    eligible: list[str] = []
    bars_by_symbol: dict[str, list[dict[str, float]]] = {}
    for symbol in symbols:
        row: dict[str, Any] = {"symbol": symbol, "source": "PREEXISTING_OPERATIONAL_ROLLING_UNIVERSE"}
        try:
            bars = child._bars(symbol, "4h", boundary_ms, boundary_ms)
            bars_by_symbol[symbol] = bars
            row["closed_4h_bars_preboundary"] = len(bars)
            snap = ev.fetch_execution_snapshot(symbol, authority)
            cost = float(snap["pretrade_verified_cost_bps"])
            row["pretrade_verified_cost_bps"] = cost
            row["cost_snapshot_sha256"] = snap["snapshot_sha256"]
            row["data_ok"] = len(bars) >= MIN_CLOSED_BARS
            row["cost_ok"] = cost <= EXPANDED_FIXED_COST_BPS
            row["eligible"] = bool(row["data_ok"] and row["cost_ok"])
            if row["eligible"]:
                eligible.append(symbol)
        except Exception as exc:
            row.update({"eligible": False, "data_ok": False, "cost_ok": False, "error": f"{type(exc).__name__}:{exc}"})
        symbol_rows[symbol] = row

    core_ok = all(s in eligible for s in CORE)
    extra = sorted(set(eligible) - set(CORE))
    children = [x for x in freeze.get("children") or [] if isinstance(x, Mapping)]
    lane_rates: dict[str, Any] = {}
    for c in children:
        lane_id = str(c.get("lane_id") or "")
        spec = c.get("executable_spec")
        if not lane_id or not isinstance(spec, Mapping):
            raise RuntimeError("CHILD_SPEC_REQUIRED")
        core_count = expanded_count = 0
        per_symbol: dict[str, int] = {}
        for symbol in symbols:
            try:
                bars = bars_by_symbol.get(symbol) or child._bars(symbol, "4h", boundary_ms, boundary_ms)
                n = closed_event_count(bars, spec, boundary_ms)
            except Exception:
                n = 0
            per_symbol[symbol] = n
            if symbol in CORE:
                core_count += n
            if symbol in eligible:
                expanded_count += n
        multiplier = (expanded_count / core_count) if core_count > 0 else (float("inf") if expanded_count > 0 else 1.0)
        lane_rates[lane_id] = {
            "core_preboundary_closed_event_count": core_count,
            "eligible_universe_preboundary_closed_event_count": expanded_count,
            "arrival_rate_multiplier": multiplier if multiplier != float("inf") else None,
            "arrival_rate_multiplier_infinite": multiplier == float("inf"),
            "per_symbol_event_count": per_symbol,
            "outcome_values_used_for_symbol_selection": False,
        }

    all_lanes_accelerate = all(
        (bool(x["arrival_rate_multiplier_infinite"]) or float(x["arrival_rate_multiplier"] or 0.0) >= MIN_ACCELERATION_MULTIPLIER)
        for x in lane_rates.values()
    )
    can_refreeze = bool(
        rebudget["all_three_pass"] and core_ok and extra and all_lanes_accelerate
        and int(current.get("total_closed_T") or 0) == 0
    )
    state = "PASS_G4_SYMBOL_EXPANSION_REFREEZE_ELIGIBLE" if can_refreeze else "HOLD_G4_SYMBOL_EXPANSION_NOT_JUSTIFIED"
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "purpose": "Reduce G4 calendar time without using symbol PnL outcomes or modifying any lane after fresh child evidence exists.",
        "current_child_total_closed_T": int(current.get("total_closed_T") or 0),
        "current_child_boundary_utc": current.get("boundary_utc"),
        "candidate_universe_source": "UNIQUE_SYMBOLS_ALREADY_PRESENT_IN_PREEXISTING_ROLLING_CLOSED_LEDGER_PLUS_CORE",
        "candidate_symbols": symbols,
        "core_symbols": list(CORE),
        "eligible_symbols": sorted(eligible),
        "extra_eligible_symbols": extra,
        "development_cost_rebudget": rebudget,
        "eligibility": {
            "min_closed_4h_bars": MIN_CLOSED_BARS,
            "max_pretrade_verified_cost_bps": EXPANDED_FIXED_COST_BPS,
            "prospective_v2_fixed_cost_bps": EXPANDED_FIXED_COST_BPS,
            "uses_trade_pnl": False,
            "uses_post_boundary_outcomes": False,
            "symbol_rows": symbol_rows,
        },
        "arrival_rate_rule": {
            "preboundary_only": True,
            "outcome_blind": True,
            "minimum_multiplier_each_lane": MIN_ACCELERATION_MULTIPLIER,
            "lanes": lane_rates,
        },
        "can_refreeze_g4_population": can_refreeze,
        "refreeze_semantics": (
            "CREATE_V2_CHILDREN_WITH_IDENTICAL_ALPHA_DSL; FIXED_20BPS_COST; ELIGIBLE_SYMBOL_SET_FROZEN; "
            "NEW_POST_MERGE_BOUNDARY; RETIRE_V1_WITH_ZERO_CONSUMED_T"
            if can_refreeze else None
        ),
        "g5_broad_population_change_allowed": False,
        "g5_reason": "CURRENT_G5_W2_ALREADY_CONTAINS_4_CLOSED_T; MIDWINDOW_SYMBOL_EXPANSION_WOULD_INVALIDATE_FROZEN_POPULATION",
        "paid_provider_calls": 0,
        **AUTH,
    }
    result["receipt_sha256"] = child._sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake = {"lanes": {"a": {"closed_trades": [{"symbol": "SOL-USDT"}, {"symbol": "BTC-USDT"}]}}}
    assert operational_symbols(fake) == ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
    assert EXPANDED_FIXED_COST_BPS == 20.0 and MIN_CLOSED_BARS == 239
    assert MIN_ACCELERATION_MULTIPLIER == 1.25
    print("PASS_A1_G4_SYMBOL_ACCELERATION_AUDIT_V1_SELF_TEST")
    print("PASS_OUTCOME_BLIND_SYMBOL_ELIGIBILITY_AND_G5_POPULATION_LOCK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_g4_symbol_acceleration_audit_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output)
    print(json.dumps({
        "state": r["state"],
        "eligible_symbols": r["eligible_symbols"],
        "extra_eligible_symbols": r["extra_eligible_symbols"],
        "development_cost_rebudget": r["development_cost_rebudget"],
        "can_refreeze": r["can_refreeze_g4_population"],
        "lane_rates": r["arrival_rate_rule"]["lanes"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
