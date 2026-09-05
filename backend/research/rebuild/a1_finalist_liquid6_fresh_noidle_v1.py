#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
HARDENING_POLICY = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
LATEST = ROOT / "backend/research/rebuild/a1_finalist_liquid6_fresh_latest.json"
LIQUID6 = ("BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "LINK-USDT", "DOGE-USDT")
TARGETS = ("supertrend_pullback", "trend_ma_macd")
MIN_TRADES = 25
STALL_LAST_TRADE_HOURS = 12.0
MIN_ELAPSED_HOURS_FOR_STALL = 24.0
PROJECTED_REMAINING_HOURS_ALERT = 168.0
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
    "exchange_order_submitted": False,
}


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def parse_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def next_full_hour_iso(ts_ms: int) -> str:
    hour = 3_600_000
    return datetime.fromtimestamp((((int(ts_ms) // hour) + 1) * hour) / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def source_frontier(receipt: Mapping[str, Any]) -> int | None:
    source = receipt.get("source") if isinstance(receipt.get("source"), Mapping) else {}
    rows = [x for x in (source.get("symbols") or []) if isinstance(x, Mapping)]
    return max((int(x["last_post_boundary_ts"]) for x in rows if x.get("last_post_boundary_ts") is not None), default=None)


def run_liquid6_shadow(*, strategy_id: str, boundary: str, out: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one canonical policy on fixed Liquid6 from a temporary fresh boundary.

    The canonical ledger and inventory are byte-for-byte guarded. Historical bars
    remain available only for indicator warmup; signals before `boundary` are not
    iterated/settled by the evaluator.
    """
    inventory = read(INVENTORY)
    ledger = read(LEDGER)
    if strategy_id not in (inventory.get("strategies") or {}):
        raise RuntimeError(f"INVENTORY_TARGET_MISSING:{strategy_id}")
    strategy = (ledger.get("strategies") or {}).get(strategy_id)
    if not isinstance(strategy, dict):
        raise RuntimeError(f"LEDGER_TARGET_MISSING:{strategy_id}")
    original_boundary = str(strategy.get("prospective_boundary_utc") or "")
    if not original_boundary:
        raise RuntimeError(f"CANONICAL_BOUNDARY_MISSING:{strategy_id}")

    real_ledger_sha = file_sha(LEDGER)
    real_inventory_sha = file_sha(INVENTORY)
    shadow_ledger = json.loads(json.dumps(ledger))
    shadow_ledger["strategies"][strategy_id]["prospective_boundary_utc"] = boundary

    with tempfile.TemporaryDirectory(prefix=f"{strategy_id}_liquid6_fresh_") as td:
        td_path = Path(td)
        ledger_path = td_path / "ledger.json"
        inventory_path = td_path / "inventory.json"
        ledger_path.write_text(json.dumps(shadow_ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        old_inventory = exact.v1.INVENTORY_PATH
        old_canonical = exact.CANONICAL_LEDGER_PATH
        old_argv = sys.argv[:]
        try:
            exact.v1.INVENTORY_PATH = inventory_path
            exact.CANONICAL_LEDGER_PATH = ledger_path
            sys.argv = [
                old_argv[0], "--strategy-id", strategy_id,
                "--symbols", ",".join(LIQUID6),
                "--out", str(out), "--terminal-replay",
            ]
            exact.main()
        finally:
            exact.v1.INVENTORY_PATH = old_inventory
            exact.CANONICAL_LEDGER_PATH = old_canonical
            sys.argv = old_argv

    if file_sha(LEDGER) != real_ledger_sha:
        raise RuntimeError("REAL_CANONICAL_LEDGER_MUTATED")
    if file_sha(INVENTORY) != real_inventory_sha:
        raise RuntimeError("REAL_CANONICAL_INVENTORY_MUTATED")
    receipt = read(out)
    if str(receipt.get("boundary_utc") or "") != boundary:
        raise RuntimeError(f"LIQUID6_BOUNDARY_NOT_APPLIED:{strategy_id}")
    if sorted(x.get("symbol") for x in ((receipt.get("source") or {}).get("symbols") or [])) != sorted(LIQUID6):
        raise RuntimeError(f"LIQUID6_UNIVERSE_MISMATCH:{strategy_id}")
    meta = {
        "original_canonical_boundary_utc": original_boundary,
        "shadow_evaluation_boundary_utc": boundary,
        "fixed_symbol_universe": list(LIQUID6),
        "real_canonical_ledger_sha256": real_ledger_sha,
        "real_canonical_inventory_sha256": real_inventory_sha,
        "real_canonical_ledger_mutated": False,
        "real_canonical_inventory_mutated": False,
        **AUTH,
    }
    return receipt, meta


def metric(receipt: Mapping[str, Any], key: str) -> float | None:
    metrics = receipt.get("metrics") if isinstance(receipt.get("metrics"), Mapping) else {}
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def max_loss_streak(trades: list[dict[str, Any]]) -> int:
    best = cur = 0
    for row in sorted(trades, key=lambda x: (int(x.get("exit_ts") or 0), int(x.get("entry_ts") or 0), str(x.get("symbol") or ""))):
        if float(row.get("net_bps") or 0.0) < 0.0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def concentration_precheck(receipt: Mapping[str, Any], h5: Mapping[str, Any]) -> dict[str, Any]:
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    total_net = sum(float(x.get("net_bps") or 0.0) for x in trades)
    total_profit = sum(max(0.0, float(x.get("net_bps") or 0.0)) for x in trades)
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in trades:
        by_symbol.setdefault(str(row.get("symbol") or "UNKNOWN"), []).append(row)
    rows = []
    for symbol in LIQUID6:
        xs = by_symbol.get(symbol, [])
        net = sum(float(x.get("net_bps") or 0.0) for x in xs)
        profit = sum(max(0.0, float(x.get("net_bps") or 0.0)) for x in xs)
        rows.append({
            "symbol": symbol,
            "trade_count": len(xs),
            "net_pnl_bps": net,
            "profit_share": profit / total_profit if total_profit > 0 else 0.0,
            "leave_one_symbol_out_net_bps": total_net - net,
        })
    top10 = sum(sorted((max(0.0, float(x.get("net_bps") or 0.0)) for x in trades), reverse=True)[:10]) / total_profit if total_profit > 0 else 0.0
    max_symbol_share = max((float(x["profit_share"]) for x in rows), default=0.0)
    min_loo_bps = min((float(x["leave_one_symbol_out_net_bps"]) for x in rows), default=0.0)
    thresholds = {
        "maximum_single_symbol_profit_share": float(h5["maximum_single_symbol_profit_share"]),
        "maximum_top10_trade_profit_share": float(h5["maximum_top10_trade_profit_share"]),
        "minimum_leave_one_group_out_net_R": float(h5["minimum_leave_one_group_out_net_R"]),
    }
    full_sample = len(trades) >= MIN_TRADES
    breaches = []
    if max_symbol_share > thresholds["maximum_single_symbol_profit_share"]:
        breaches.append("SINGLE_SYMBOL_PROFIT_SHARE")
    if top10 > thresholds["maximum_top10_trade_profit_share"]:
        breaches.append("TOP10_TRADE_PROFIT_SHARE")
    if min_loo_bps / 100.0 < thresholds["minimum_leave_one_group_out_net_R"]:
        breaches.append("LEAVE_ONE_SYMBOL_OUT_NET_R")
    return {
        "state": ("PENDING_FRESH25_H5_SUBSET" if not full_sample else ("PASS_H5_SYMBOL_TOP10_SUBSET" if not breaches else "HOLD_H5_SYMBOL_TOP10_SUBSET")),
        "note": "Subset precheck only. Full H5 still requires symbol/regime/side/session/window and sealed holdout evaluation.",
        "trade_count": len(trades),
        "symbols": rows,
        "maximum_single_symbol_profit_share": max_symbol_share,
        "top10_trade_profit_share": top10,
        "minimum_leave_one_symbol_out_net_bps": min_loo_bps,
        "thresholds_from_h5_ssot": thresholds,
        "breaches": breaches,
    }


def pace(receipt: Mapping[str, Any], boundary: str) -> dict[str, Any]:
    trades = [dict(x) for x in (receipt.get("trades") or []) if isinstance(x, Mapping)]
    frontier = source_frontier(receipt)
    boundary_ms = parse_ms(boundary)
    elapsed_h = max(0.0, ((frontier or boundary_ms) - boundary_ms) / 3_600_000.0)
    count = len(trades)
    rate = count / elapsed_h if elapsed_h > 0 else 0.0
    remaining = max(0, MIN_TRADES - count)
    projected = remaining / rate if rate > 0 else None
    latest_exit = max((int(x.get("exit_ts") or 0) for x in trades), default=None)
    last_age = ((frontier - latest_exit) / 3_600_000.0) if frontier is not None and latest_exit is not None else None
    stall = bool(
        count < MIN_TRADES and elapsed_h >= MIN_ELAPSED_HOURS_FOR_STALL and (
            (last_age is not None and last_age >= STALL_LAST_TRADE_HOURS)
            or (projected is None or projected > PROJECTED_REMAINING_HOURS_ALERT)
        )
    )
    return {
        "elapsed_hours": elapsed_h,
        "completed_trades": count,
        "completed_trades_per_hour": rate,
        "remaining_to_25": remaining,
        "projected_remaining_hours_to_25": projected,
        "last_completed_trade_age_hours": last_age,
        "sample_stall_triggered": stall,
        "monitor_sla_not_strategy_parameters": {
            "minimum_elapsed_hours_before_stall_check": MIN_ELAPSED_HOURS_FOR_STALL,
            "last_completed_trade_stall_hours": STALL_LAST_TRADE_HOURS,
            "projected_remaining_hours_alert": PROJECTED_REMAINING_HOURS_ALERT,
        },
    }


def economics_positive(receipt: Mapping[str, Any]) -> bool:
    pnl = metric(receipt, "net_pnl_bps")
    exp = metric(receipt, "net_expectancy_bps")
    pf = metric(receipt, "net_profit_factor")
    return bool(pnl is not None and pnl > 0.0 and exp is not None and exp > 0.0 and (pf is None or pf >= 1.0))


def integrity_ok(receipt: Mapping[str, Any]) -> bool:
    source = receipt.get("source_quality_gate") if isinstance(receipt.get("source_quality_gate"), Mapping) else {}
    return bool(source.get("state") in ("PASS", "PENDING") and not (receipt.get("integrity_defects") or []) and int(receipt.get("leakage_lookahead") or 0) == 0)


def run(out: Path) -> dict[str, Any]:
    ledger = read(LEDGER)
    policy = read(HARDENING_POLICY)
    h5 = policy["h5_concentration_fragility"]
    previous = read(LATEST) if LATEST.exists() else {}
    previous_targets = previous.get("targets") if isinstance(previous.get("targets"), Mapping) else {}
    rows: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="a1_finalist_liquid6_fresh_") as td:
        td_path = Path(td)
        for sid in TARGETS:
            canonical = (ledger.get("strategies") or {}).get(sid)
            if not isinstance(canonical, Mapping):
                raise RuntimeError(f"CANONICAL_TARGET_MISSING:{sid}")
            original_boundary = str(canonical.get("prospective_boundary_utc") or "")
            if not original_boundary:
                raise RuntimeError(f"ORIGINAL_BOUNDARY_MISSING:{sid}")

            retrospective, retrospective_meta = run_liquid6_shadow(
                strategy_id=sid,
                boundary=original_boundary,
                out=td_path / f"{sid}_retrospective_liquid6.json",
            )
            prior = previous_targets.get(sid) if isinstance(previous_targets, Mapping) else None
            frozen = str((prior or {}).get("frozen_liquid6_fresh_boundary_utc") or "") if isinstance(prior, Mapping) else ""
            if not frozen:
                frontier = source_frontier(retrospective)
                if frontier is None:
                    raise RuntimeError(f"SOURCE_FRONTIER_MISSING:{sid}")
                frozen = next_full_hour_iso(frontier)

            fresh, fresh_meta = run_liquid6_shadow(
                strategy_id=sid,
                boundary=frozen,
                out=td_path / f"{sid}_fresh_liquid6.json",
            )
            p = pace(fresh, frozen)
            c = concentration_precheck(fresh, h5)
            fresh_trades = [dict(x) for x in (fresh.get("trades") or []) if isinstance(x, Mapping)]
            if not integrity_ok(retrospective) or not economics_positive(retrospective):
                state = "HOLD_RETROSPECTIVE_LIQUID6_QUALIFIER_FAILED"
                nxt = "KEEP_BTCETH_PARENT; DO_NOT_EXPAND_UNIVERSE"
            elif not integrity_ok(fresh):
                state = "HOLD_LIQUID6_FRESH_INTEGRITY"
                nxt = "FAIL_CLOSED_DIAGNOSE_SOURCE_OR_LINEAGE"
            elif len(fresh_trades) >= MIN_TRADES:
                state = "READY_LIQUID6_FRESH25_FOR_FULL_H4_H5" if c["state"] == "PASS_H5_SYMBOL_TOP10_SUBSET" else "HOLD_LIQUID6_FRESH25_CONCENTRATION_PRECHECK"
                nxt = "RUN_FULL_H4_H5_SEALED_HOLDOUT" if state.startswith("READY") else "DIAGNOSE_SYMBOL_CONCENTRATION_BEFORE_ANY_PROMOTION"
            elif p["sample_stall_triggered"]:
                state = "HOLD_LIQUID6_FRESH_SAMPLE_STALL_ROUTE_NO_IDLE_DIAGNOSIS"
                nxt = "RUN_SYMBOL_FUNNEL_LOSS_CLUSTER_AND_DISTINCT_CAUSAL_CHILD; KEEP_FRESH_LANE_RUNNING"
            else:
                state = "COLLECTING_LIQUID6_FRESH_TO_25"
                nxt = "KEEP_PARENT_AND_LIQUID6_FRESH_IN_PARALLEL"

            rows[sid] = {
                "state": state,
                "next": nxt,
                "fixed_symbol_universe": list(LIQUID6),
                "original_canonical_boundary_utc": original_boundary,
                "frozen_liquid6_fresh_boundary_utc": frozen,
                "boundary_reused_from_previous_receipt": bool(isinstance(prior, Mapping) and prior.get("frozen_liquid6_fresh_boundary_utc")),
                "retrospective_liquid6_qualifier": {
                    "completed_trades": int(retrospective.get("completed_trades") or 0),
                    "win_rate": metric(retrospective, "win_rate"),
                    "net_pnl_bps": metric(retrospective, "net_pnl_bps"),
                    "net_expectancy_bps": metric(retrospective, "net_expectancy_bps"),
                    "profit_factor": metric(retrospective, "net_profit_factor"),
                    "max_drawdown_bps": metric(retrospective, "max_drawdown_bps"),
                    "economics_positive": economics_positive(retrospective),
                    "integrity_ok": integrity_ok(retrospective),
                    "shadow_meta": retrospective_meta,
                },
                "fresh": {
                    "completed_trades": len(fresh_trades),
                    "intent_count": int(fresh.get("intent_count") or 0),
                    "win_rate": metric(fresh, "win_rate"),
                    "net_pnl_bps": metric(fresh, "net_pnl_bps"),
                    "net_expectancy_bps": metric(fresh, "net_expectancy_bps"),
                    "profit_factor": metric(fresh, "net_profit_factor"),
                    "max_drawdown_bps": metric(fresh, "max_drawdown_bps"),
                    "max_consecutive_losses": max_loss_streak(fresh_trades),
                    "integrity_ok": integrity_ok(fresh),
                    "source_quality_state": ((fresh.get("source_quality_gate") or {}).get("state") if isinstance(fresh.get("source_quality_gate"), Mapping) else None),
                    "integrity_defects": list(fresh.get("integrity_defects") or []),
                    "leakage_lookahead": int(fresh.get("leakage_lookahead") or 0),
                    "shadow_meta": fresh_meta,
                },
                "pace": p,
                "h5_symbol_top10_subset_precheck": c,
                "full_h5_not_claimed": True,
                "strategy_parameters_changed": False,
                "thresholds_changed": False,
                "canonical_parent_collection_should_continue": True,
                **AUTH,
            }

    result = {
        "schema_version": "zel.a1.finalist.liquid6_fresh_noidle.v1",
        "state": "PASS_LIQUID6_FRESH_NO_IDLE_ROUTER_ACTIVE",
        "purpose": "Accelerate sparse finalist evidence without mutating alpha: keep BTC/ETH canonical parents, run fixed Liquid6 prospective shadow lanes, watch loss streak/DD/concentration, and route renewed sample stalls into diagnosis instead of passive waiting.",
        "fixed_liquid6": list(LIQUID6),
        "targets": rows,
        "h5_ssot_path": str(HARDENING_POLICY.relative_to(ROOT)),
        "h5_thresholds_reused_not_invented": True,
        "full_h5_not_claimed": True,
        "strategy_parameters_changed": False,
        "thresholds_changed": False,
        "canonical_ledger_mutation": False,
        "canonical_inventory_mutation": False,
        **AUTH,
    }
    result["receipt_sha256"] = stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    h5 = {
        "maximum_single_symbol_profit_share": 0.7,
        "maximum_top10_trade_profit_share": 0.8,
        "minimum_leave_one_group_out_net_R": 0.0,
    }
    fake = {
        "trades": [
            {"symbol": "BTC-USDT", "entry_ts": 1, "exit_ts": 2, "net_bps": 100.0},
            {"symbol": "ETH-USDT", "entry_ts": 3, "exit_ts": 4, "net_bps": -20.0},
            {"symbol": "SOL-USDT", "entry_ts": 5, "exit_ts": 6, "net_bps": 50.0},
        ],
        "metrics": {"net_pnl_bps": 130.0, "net_expectancy_bps": 43.333, "net_profit_factor": 7.5},
        "source": {"symbols": [{"symbol": s, "last_post_boundary_ts": 3_600_000} for s in LIQUID6]},
        "source_quality_gate": {"state": "PASS"},
        "integrity_defects": [], "leakage_lookahead": 0,
    }
    c = concentration_precheck(fake, h5)
    assert c["state"] == "PENDING_FRESH25_H5_SUBSET"
    assert max_loss_streak(fake["trades"]) == 1
    assert next_full_hour_iso(3_600_000) == "1970-01-01T02:00:00Z"
    assert economics_positive(fake) is True and integrity_ok(fake) is True
    print("PASS_A1_FINALIST_LIQUID6_FRESH_NOIDLE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_finalist_liquid6_fresh_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.out)
    print(json.dumps({
        "state": result["state"],
        "targets": {
            sid: {
                "state": row["state"],
                "boundary": row["frozen_liquid6_fresh_boundary_utc"],
                "retro_trades": row["retrospective_liquid6_qualifier"]["completed_trades"],
                "fresh_trades": row["fresh"]["completed_trades"],
                "fresh_dd_bps": row["fresh"]["max_drawdown_bps"],
                "fresh_max_loss_streak": row["fresh"]["max_consecutive_losses"],
                "h5_subset": row["h5_symbol_top10_subset_precheck"]["state"],
                "stall": row["pace"]["sample_stall_triggered"],
            }
            for sid, row in result["targets"].items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
