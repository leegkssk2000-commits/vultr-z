#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import _side, _validate_side
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
PREDECESSOR = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_latest.json"
LATEST = ROOT / "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
SCHEMA = "zel.a1.top5.replacement_child.prospective.receipt.v2"
EXPECTED_BOUNDARY_MS = 1788048000000
EXPECTED_BOUNDARY_UTC = "2026-08-30T00:00:00Z"
EXPECTED_COST_BPS = 20.0
EXPECTED_SYMBOLS = (
    "1000PEPE-USDT",
    "BCH-USDT",
    "BTC-USDT",
    "ETH-USDT",
    "HYPE-USDT",
    "LINK-USDT",
    "SOL-USDT",
)
AUTH = dict(v1.AUTH)


def _read(path: Path) -> dict[str, Any]:
    return v1._read(path)


def _previous_ids(previous: Mapping[str, Any] | None, lane_id: str) -> set[str]:
    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return set()
    lane = (previous.get("lanes") or {}).get(lane_id)
    if not isinstance(lane, Mapping):
        return set()
    return {
        str(x.get("closed_trade_id"))
        for x in lane.get("closed_trades") or []
        if isinstance(x, Mapping) and x.get("closed_trade_id")
    }


def _metrics(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    net = [float(x["net_bps"]) for x in trades]
    gp = sum(x for x in net if x > 0)
    gl = -sum(x for x in net if x < 0)
    eq = peak = dd = 0.0
    for value in net:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "closed_T": len(net),
        "win_rate": (sum(1 for x in net if x > 0) / len(net)) if net else None,
        "net_expectancy_bps": (sum(net) / len(net)) if net else None,
        "net_pnl_bps": sum(net),
        "profit_factor": (gp / gl) if gl > 0 else None,
        "drawdown_bps": dd,
        "cost_bps_per_trade": EXPECTED_COST_BPS,
    }


def _closed_trades(child: Mapping[str, Any], boundary_ms: int, now_ms: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    child_id = str(child.get("child_id") or "")
    spec = child.get("executable_spec")
    if not child_id or not isinstance(spec, Mapping):
        raise RuntimeError("CHILD_SPEC_REQUIRED")
    interval = str(spec.get("bar_interval") or "")
    if interval not in v1.INTERVAL_MS:
        raise RuntimeError(f"UNSUPPORTED_INTERVAL:{interval}")
    hold = int(spec.get("max_hold_bars") or 0)
    if hold <= 0:
        raise RuntimeError("HOLD_REQUIRED")
    entry_rule = str(spec.get("entry_rule") or "")
    side_rule = str(spec.get("side_rule") or "")
    cost_bps = float(spec.get("cost_bps_per_trade") or 0.0)
    if abs(cost_bps - EXPECTED_COST_BPS) > 1e-12:
        raise RuntimeError("V2_COST_DRIFT")

    trades: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    for symbol in EXPECTED_SYMBOLS:
        rows = v1._bars(symbol, interval, boundary_ms, now_ms)
        source[symbol] = {
            "closed_bars": len(rows),
            "first_bar_ts": int(rows[0]["ts"]) if rows else None,
            "last_bar_ts": int(rows[-1]["ts"]) if rows else None,
        }
        if len(rows) < 60:
            continue
        _, engine = v1._features(rows, spec)
        engine.validate(entry_rule)
        _validate_side(side_rule, engine)
        i = 50
        while i < len(rows) - 1:
            signal_ts = int(rows[i]["ts"])
            if signal_ts < boundary_ms:
                i += 1
                continue
            try:
                fire = bool(engine.eval(entry_rule, i))
            except (TypeError, ZeroDivisionError, ValueError):
                fire = False
            if not fire:
                i += 1
                continue
            side = _side(side_rule, engine, i)
            if side not in {"long", "short"}:
                raise RuntimeError("SIDE_RULE_UNSUPPORTED")
            entry_i = i + 1
            exit_i = entry_i + hold - 1
            if exit_i >= len(rows):
                break
            entry_px = float(rows[entry_i]["open"])
            exit_px = float(rows[exit_i]["close"])
            gross = (exit_px / entry_px - 1.0) * 10000.0 * (1.0 if side == "long" else -1.0)
            net = gross - cost_bps
            payload = {
                "child_id": child_id,
                "symbol": symbol,
                "side": side,
                "signal_ts": signal_ts,
                "entry_ts": int(rows[entry_i]["ts"]),
                "exit_ts": int(rows[exit_i]["ts"]),
            }
            trades.append({
                "closed_trade_id": v1._sha(payload),
                **payload,
                "entry_px": entry_px,
                "exit_px": exit_px,
                "gross_bps": gross,
                "net_bps": net,
                "cost_bps": cost_bps,
            })
            i = exit_i + 1
    trades.sort(key=lambda x: (x["exit_ts"], x["signal_ts"], x["symbol"], x["closed_trade_id"]))
    ids = [x["closed_trade_id"] for x in trades]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"DUPLICATE_V2_CHILD_TRADE_ID:{child_id}")
    return trades, source


def _assert_contract(contract: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if contract.get("schema_version") != "zel.a1.top5.replacement_child_freeze.v2":
        raise RuntimeError("V2_FREEZE_SCHEMA_DRIFT")
    if contract.get("state") != "FROZEN_REPLACEMENT_CHILDREN_V2_PRE_PROSPECTIVE":
        raise RuntimeError("V2_FREEZE_STATE_DRIFT")
    boundary = contract.get("prospective_boundary") or {}
    if int(boundary.get("ms") or 0) != EXPECTED_BOUNDARY_MS or boundary.get("utc") != EXPECTED_BOUNDARY_UTC:
        raise RuntimeError("V2_BOUNDARY_DRIFT")
    symbols = tuple(contract.get("frozen_symbol_universe") or [])
    if symbols != EXPECTED_SYMBOLS:
        raise RuntimeError(f"V2_SYMBOL_UNIVERSE_DRIFT:{symbols}")
    cost = contract.get("cost_model") or {}
    if abs(float(cost.get("cost_bps_per_trade") or 0.0) - EXPECTED_COST_BPS) > 1e-12:
        raise RuntimeError("V2_COST_MODEL_DRIFT")
    rules = contract.get("global_rules") or {}
    if rules.get("alpha_dsl_changed_from_v1") is not False:
        raise RuntimeError("V2_ALPHA_MUTATION_FORBIDDEN")
    for key in ("old_history_union", "post_result_retune", "threshold_sweep", "g5_broad_population_mutation"):
        if rules.get(key) is not False:
            raise RuntimeError(f"V2_CONTAMINATION_RULE_DRIFT:{key}")
    if rules.get("symbol_universe_frozen_after_v2_boundary") is not True or rules.get("cost_model_frozen_after_v2_boundary") is not True:
        raise RuntimeError("V2_POPULATION_OR_COST_NOT_FROZEN")
    children = [x for x in contract.get("children") or [] if isinstance(x, Mapping)]
    if len(children) != 3:
        raise RuntimeError("V2_EXACT_THREE_CHILDREN_REQUIRED")
    if any(x.get("alpha_dsl_identical_to_v1") is not True for x in children):
        raise RuntimeError("V2_ALPHA_DSL_NOT_IDENTICAL")
    if any(int(x.get("predecessor_v1_consumed_T") or 0) != 0 for x in children):
        raise RuntimeError("V1_EVIDENCE_CONSUMED")
    if any(int(x.get("prospective_child_T_at_freeze", -1)) != 0 for x in children):
        raise RuntimeError("V2_CHILD_NOT_ZERO_AT_FREEZE")
    return children


def run(output: Path, previous_path: Path | None = None, now_ms: int | None = None) -> dict[str, Any]:
    contract = _read(CONTRACT)
    children = _assert_contract(contract)
    predecessor = _read(PREDECESSOR)
    if predecessor.get("schema_version") != "zel.a1.top5.replacement_child.prospective.receipt.v1":
        raise RuntimeError("V1_PREDECESSOR_SCHEMA_DRIFT")
    if int(predecessor.get("total_closed_T") or 0) != 0:
        raise RuntimeError("V1_PREDECESSOR_ACCUMULATED_EVIDENCE_ABORT_V2")
    if predecessor.get("receipt_sha256") != (contract.get("evidence") or {}).get("v1_last_receipt_sha256"):
        raise RuntimeError("V1_PREDECESSOR_RECEIPT_DRIFT")

    boundary = contract.get("prospective_boundary") or {}
    boundary_ms = int(boundary["ms"])
    current_ms = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    previous = _read(previous_path) if previous_path and previous_path.is_file() else (_read(LATEST) if LATEST.is_file() else None)
    lanes: dict[str, Any] = {}
    total_new = 0
    for c in children:
        lane_id = str(c.get("lane_id") or "")
        trades, source = _closed_trades(c, boundary_ms, current_ms) if current_ms >= boundary_ms else ([], {})
        if any(int(x["signal_ts"]) < boundary_ms for x in trades):
            raise RuntimeError(f"V2_PREBOUNDARY_CHILD_TRADE:{lane_id}")
        if any(str(x["symbol"]) not in EXPECTED_SYMBOLS for x in trades):
            raise RuntimeError(f"V2_UNFROZEN_SYMBOL_TRADE:{lane_id}")
        prior = _previous_ids(previous, lane_id)
        current_ids = {str(x["closed_trade_id"]) for x in trades}
        if not prior.issubset(current_ids):
            raise RuntimeError(f"V2_APPEND_ONLY_REGRESSION:{lane_id}")
        new_ids = sorted(current_ids - prior)
        total_new += len(new_ids)
        lanes[lane_id] = {
            "parent_strategy_id": c.get("parent_strategy_id"),
            "predecessor_child_id": c.get("predecessor_child_id"),
            "child_id": c.get("child_id"),
            "architecture_family": c.get("architecture_family"),
            "boundary_ms": boundary_ms,
            "boundary_utc": boundary.get("utc"),
            "replacement_child_frozen": True,
            "alpha_dsl_identical_to_v1": True,
            "frozen_symbol_universe": list(EXPECTED_SYMBOLS),
            "predecessor_v1_consumed_T": 0,
            "old_parent_raw_observer_burned_T": int(c.get("burned_parent_raw_observer_T") or 0),
            "old_parent_raw_observer_consumed_T": 0,
            "closed_trades": trades,
            "closed_T": len(trades),
            "new_closed_trade_ids": new_ids,
            "new_closed_T": len(new_ids),
            "metrics": _metrics(trades),
            "source_summary": source,
            "next": "ACCUMULATE_FRESH_PROSPECTIVE_V2_CHILD_T_ONLY",
        }

    result = {
        "schema_version": SCHEMA,
        "state": "WAIT_PROSPECTIVE_V2_BOUNDARY" if current_ms < boundary_ms else "PASS_PROSPECTIVE_V2_CHILD_COLLECTION_ACTIVE",
        "observed_at_utc": datetime.fromtimestamp(current_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "predecessor_v1_receipt_sha256": predecessor.get("receipt_sha256"),
        "predecessor_v1_total_closed_T": 0,
        "predecessor_v1_retired": True,
        "boundary_ms": boundary_ms,
        "boundary_utc": boundary.get("utc"),
        "boundary_reached": current_ms >= boundary_ms,
        "frozen_symbol_universe": list(EXPECTED_SYMBOLS),
        "frozen_symbol_count": len(EXPECTED_SYMBOLS),
        "fixed_cost_bps_per_trade": EXPECTED_COST_BPS,
        "lane_count": 3,
        "total_closed_T": sum(int(x["closed_T"]) for x in lanes.values()),
        "total_new_closed_T": total_new,
        "old_history_union": False,
        "post_result_retune": False,
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "g5_broad_population_mutated": False,
        "lanes": lanes,
        **AUTH,
    }
    result["receipt_sha256"] = v1._sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = _read(CONTRACT)
    children = _assert_contract(c)
    assert len(children) == 3
    assert EXPECTED_BOUNDARY_MS == 1788048000000
    assert EXPECTED_COST_BPS == 20.0
    assert len(EXPECTED_SYMBOLS) == 7
    assert AUTH["execution_authority"] == "NONE" and AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_REPLACEMENT_CHILD_PROSPECTIVE_V2_SELF_TEST")
    print("PASS_V1_ZERO_EVIDENCE_RETIREMENT_AND_EXPANDED_FROZEN_UNIVERSE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_top5_replacement_child_prospective_v2_latest.json"))
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--now-ms", type=int)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output, args.previous, args.now_ms)
    print(json.dumps({
        "state": r["state"],
        "boundary_reached": r["boundary_reached"],
        "symbols": r["frozen_symbol_universe"],
        "lane_T": {k: v["closed_T"] for k, v in r["lanes"].items()},
        "total_closed_T": r["total_closed_T"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
