#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as ev2
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import metrics, stable

SCHEMA = "zel.a1.trend_rider.long_only_exact_parent_economics.v1"
EXPECTED_PARENT = "trend_rider_one_bar_delayed_fill_v1"
EXPECTED_CHILD = "trend_rider_delayed_fill_long_only_v1"
EXPECTED_AXIS = "LONG_SHORT_ASYMMETRY_LONG_ONLY"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


def trade_identity(trade: Mapping[str, Any]) -> str:
    return stable({
        "symbol": trade.get("symbol"),
        "signal_ts": trade.get("signal_ts"),
        "entry_ts": trade.get("entry_ts"),
        "exit_ts": trade.get("exit_ts"),
        "side": trade.get("side"),
        "intent_sha": trade.get("intent_sha"),
    })


def validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("state") != "FROZEN_PROSPECTIVE_CHALLENGER_CONTRACT":
        raise RuntimeError("LONG_ONLY_CONTRACT_NOT_FROZEN")
    if contract.get("challenger_id") != EXPECTED_CHILD:
        raise RuntimeError("LONG_ONLY_CHILD_IDENTITY_MISMATCH")
    if contract.get("parent_challenger_id") != EXPECTED_PARENT:
        raise RuntimeError("LONG_ONLY_PARENT_CONTRACT_MISMATCH")
    if contract.get("changed_axis") != EXPECTED_AXIS:
        raise RuntimeError("LONG_ONLY_AXIS_MISMATCH")
    rules = contract.get("frozen_rules") if isinstance(contract.get("frozen_rules"), Mapping) else {}
    required_false = (
        "new_trade_admission", "signal_policy_changed", "entry_delay_bars_changed",
        "stop_geometry_changed", "timeout_bars_changed", "cost_model_changed",
        "parameter_sweep", "h4_h5_thresholds_changed", "post_outcome_trade_deletion",
    )
    if rules.get("parent_trade_identity_subset_only") is not True:
        raise RuntimeError("LONG_ONLY_PARENT_SUBSET_LOCK_MISSING")
    for key in required_false:
        if rules.get(key) is not False:
            raise RuntimeError(f"LONG_ONLY_FROZEN_FALSE_REQUIRED:{key}")
    if rules.get("side_rule") != "long_only_from_parent_identity":
        raise RuntimeError("LONG_ONLY_SIDE_RULE_MISMATCH")


def validate_parent(parent: Mapping[str, Any]) -> None:
    if parent.get("parent_strategy_id") != "trend_rider":
        raise RuntimeError("LONG_ONLY_PARENT_STRATEGY_MISMATCH")
    if parent.get("challenger_id") != EXPECTED_PARENT:
        raise RuntimeError("LONG_ONLY_EXACT_PARENT_REQUIRED")
    if parent.get("parameter_sweep") is not False:
        raise RuntimeError("LONG_ONLY_PARENT_PARAMETER_SWEEP_NOT_FALSE")
    if parent.get("execution_authority") != "NONE":
        raise RuntimeError("LONG_ONLY_PARENT_EXECUTION_AUTHORITY_NOT_BLOCKED")
    if parent.get("order_authority") != "BLOCKED" or parent.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("LONG_ONLY_PARENT_ORDER_LIVE_NOT_BLOCKED")
    if int(parent.get("completed_trades") or 0) != len(parent.get("trades") or []):
        raise RuntimeError("LONG_ONLY_PARENT_TRADE_COUNT_MISMATCH")


def source_symbols(parent: Mapping[str, Any]) -> list[str]:
    source = parent.get("source") if isinstance(parent.get("source"), Mapping) else {}
    rows = source.get("symbols") if isinstance(source.get("symbols"), list) else []
    names = [str(x.get("symbol")) for x in rows if isinstance(x, Mapping) and x.get("symbol")]
    if names:
        return sorted(set(names))
    return sorted({str(x["symbol"]) for x in parent.get("trades") or []})


def rebase_source_to_boundary(parent: Mapping[str, Any], boundary_utc: str) -> tuple[dict[str, Any], dict[str, Any]]:
    source = dict(parent.get("source") or {})
    interval = str(source.get("interval") or "1h")
    if interval != "1h":
        raise RuntimeError(f"LONG_ONLY_SOURCE_INTERVAL_NOT_1H:{interval}")
    boundary_ms = utc_ms(boundary_utc)
    rows: list[dict[str, Any]] = []
    for symbol in source_symbols(parent):
        bars = ev.fetch_bars(symbol, interval, 1000)
        post = [x for x in bars if int(x["ts_ms"]) >= boundary_ms]
        rows.append({
            "symbol": symbol,
            "bars_post_boundary": len(post),
            "first_post_boundary_ts": int(post[0]["ts_ms"]) if post else None,
            "last_post_boundary_ts": int(post[-1]["ts_ms"]) if post else None,
        })
    source["interval"] = interval
    source["symbols"] = rows
    probe = dict(parent)
    probe["source"] = source
    probe["boundary_utc"] = boundary_utc
    return source, ev2.source_quality_gate(probe)


def transform(parent: Mapping[str, Any], contract: Mapping[str, Any], mode: str) -> dict[str, Any]:
    validate_contract(contract)
    validate_parent(parent)
    boundary = str(contract["frozen_at_utc"])
    boundary_ms = utc_ms(boundary)
    parent_trades = [dict(x) for x in parent.get("trades") or []]
    parent_ids = {trade_identity(x) for x in parent_trades}

    if mode == "development":
        chosen = [x for x in parent_trades if str(x.get("side")) == "long"]
        child_boundary = parent.get("boundary_utc")
        source = dict(parent.get("source") or {})
        source_quality = dict(parent.get("source_quality_gate") or {})
    elif mode == "prospective":
        chosen = [
            x for x in parent_trades
            if str(x.get("side")) == "long" and int(x.get("entry_ts") or 0) >= boundary_ms
        ]
        child_boundary = boundary
        source, source_quality = rebase_source_to_boundary(parent, boundary)
    else:
        raise RuntimeError(f"LONG_ONLY_UNKNOWN_MODE:{mode}")

    child_ids = {trade_identity(x) for x in chosen}
    if not child_ids.issubset(parent_ids):
        raise RuntimeError("LONG_ONLY_CHILD_TRADE_IDENTITY_NOT_PARENT_SUBSET")
    if any(str(x.get("side")) != "long" for x in chosen):
        raise RuntimeError("LONG_ONLY_SIDE_LEAK")

    receipt = dict(parent)
    receipt.update({
        "schema_version": SCHEMA,
        "strategy_id": "trend_rider",
        "challenger_id": EXPECTED_CHILD,
        "parent_challenger_id": EXPECTED_PARENT,
        "changed_axis": EXPECTED_AXIS,
        "evaluation_mode": mode,
        "boundary_utc": child_boundary,
        "prospective_boundary_utc": boundary if mode == "prospective" else None,
        "contract_sha256": stable(contract),
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "parent_completed_trades": len(parent_trades),
        "trades": chosen,
        "completed_trades": len(chosen),
        "intent_count": len(chosen),
        "metrics": metrics(chosen),
        "source": source,
        "source_quality_gate": source_quality,
        "exact_parent_integrity": {
            "state": "PASS",
            "parent_trade_count": len(parent_trades),
            "child_trade_count": len(chosen),
            "parent_trade_identity_subset_only": True,
            "new_trade_admission": False,
            "all_child_sides_long": True,
            "signal_policy_changed": False,
            "entry_delay_bars_changed": False,
            "stop_geometry_changed": False,
            "timeout_bars_changed": False,
            "cost_model_changed": False,
            "parameter_sweep": False,
            "post_outcome_trade_deletion": False,
            "parent_trade_identity_sha256": stable(sorted(parent_ids)),
            "child_trade_identity_sha256": stable(sorted(child_ids)),
            "fail_closed": True,
        },
        "state": "A1_REBUILT_ECONOMICS_ACTIVE" if chosen else "WAIT_FRESH_PROSPECTIVE_DATA",
        "parameter_sweep": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    })
    receipt["receipt_sha256"] = stable({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    return receipt


def self_test(contract_path: Path) -> int:
    contract = read(contract_path)
    validate_contract(contract)
    parent = {
        "parent_strategy_id": "trend_rider",
        "challenger_id": EXPECTED_PARENT,
        "parameter_sweep": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "completed_trades": 2,
        "trades": [
            {"symbol": "BTC-USDT", "signal_ts": 1, "entry_ts": 2, "exit_ts": 3, "side": "long", "intent_sha": "a", "net_bps": 10.0, "gross_bps": 24.0},
            {"symbol": "BTC-USDT", "signal_ts": 4, "entry_ts": 5, "exit_ts": 6, "side": "short", "intent_sha": "b", "net_bps": -10.0, "gross_bps": 4.0},
        ],
        "boundary_utc": "2026-08-01T00:00:00Z",
        "source": {"interval": "1h", "symbols": []},
        "source_quality_gate": {"state": "PASS", "defects": []},
    }
    out = transform(parent, contract, "development")
    assert out["completed_trades"] == 1
    assert out["trades"][0]["side"] == "long"
    assert out["exact_parent_integrity"]["parent_trade_identity_subset_only"] is True
    assert out["execution_authority"] == "NONE" and out["order_authority"] == "BLOCKED"
    print("PASS_A1_TREND_RIDER_LONG_ONLY_EXACT_PARENT_EVALUATOR_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--mode", choices=("development", "prospective"))
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_long_only_exact_parent_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test(args.contract)
    if args.parent is None or args.mode is None:
        raise SystemExit("--parent and --mode are required")
    receipt = transform(read(args.parent), read(args.contract), args.mode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print("A1_TREND_RIDER_LONG_ONLY=" + json.dumps({
        "mode": args.mode,
        "state": receipt["state"],
        "completed_trades": receipt["completed_trades"],
        "metrics": receipt["metrics"],
        "source_quality_state": (receipt.get("source_quality_gate") or {}).get("state"),
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
