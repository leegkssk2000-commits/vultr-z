#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.research.architecture_factory import a1_trendrider_lane_aware_synthesis_v1 as lane
from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as exact_v1

PRIMARY_SOURCE_JOB_ID = 97195981802
PRIMARY_SOURCE_RUN_ID = 32640190665
PRIMARY_SOURCE_COMPLETED = 25
PRIMARY_SOURCE_POLICY = "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py"
BROAD_SOURCE_RUN_ID = 32482936710
BROAD_SOURCE_RECEIPT_SHA256 = "b9a7cc4c930952e9fae3a4b65012ceb393f0e084ee3c9decbd2854858a4fedd9"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _stats_preserve_receipt_order(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = [dict(x) for x in rows]
    values = [float(x.get("net_bps") or 0.0) for x in ordered]
    wins = [x for x in values if x > 0.0]
    losses = [-x for x in values if x < 0.0]
    gp, gl = sum(wins), sum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = gl / len(losses) if losses else None
    return {
        "completed_trades": len(values),
        "wins": len(wins),
        "win_rate": len(wins) / len(values) if values else None,
        "net_pnl_bps": sum(values),
        "net_expectancy_bps": sum(values) / len(values) if values else None,
        "max_drawdown_bps": exact_v1.max_drawdown(values),
        "profit_factor": exact_v1.profit_factor(gp, gl),
        "payoff": avg_win / avg_loss if avg_win is not None and avg_loss not in (None, 0) else None,
    }


def _validate_primary_source(receipt: Mapping[str, Any]) -> None:
    trades = receipt.get("trades")
    checks = {
        "strategy_id": str(receipt.get("strategy_id")) == "trend_rider",
        "completed_trades": int(receipt.get("completed_trades") or 0) == PRIMARY_SOURCE_COMPLETED,
        "trade_count": isinstance(trades, list) and len(trades) == PRIMARY_SOURCE_COMPLETED,
        "policy_path": str(receipt.get("policy_path")) == PRIMARY_SOURCE_POLICY,
        "leakage_lookahead": int(receipt.get("leakage_lookahead") or 0) == 0,
        "duplicate_count": int(receipt.get("duplicate_count") or 0) == 0,
        "execution_authority": str(receipt.get("execution_authority")) == "NONE",
        "order_authority": str(receipt.get("order_authority")) == "BLOCKED",
        "live_trade_authority": str(receipt.get("live_trade_authority")) == "BLOCKED",
    }
    failed = [k for k, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError("PRIMARY_HISTORICAL_SOURCE_INTEGRITY:" + ",".join(failed))


def _validate_broad_artifact(artifact_dir: Path) -> None:
    matches: list[dict[str, Any]] = []
    for receipt in lane._broad_receipts(artifact_dir):
        if (
            int(receipt.get("completed_trades") or 0) == 30
            and str(receipt.get("receipt_sha256") or "") == BROAD_SOURCE_RECEIPT_SHA256
        ):
            matches.append(receipt)
    if len(matches) != 1:
        raise RuntimeError(f"BROAD_HISTORICAL_RECEIPT_REQUIRED:{len(matches)}")
    receipt = matches[0]
    if str(receipt.get("execution_authority")) != "NONE":
        raise RuntimeError("BROAD_EXECUTION_AUTHORITY_DRIFT")
    if str(receipt.get("order_authority")) != "BLOCKED":
        raise RuntimeError("BROAD_ORDER_AUTHORITY_DRIFT")
    if str(receipt.get("live_trade_authority")) != "BLOCKED":
        raise RuntimeError("BROAD_LIVE_AUTHORITY_DRIFT")


def run(primary_source: Path, artifact_dir: Path, output: Path) -> dict[str, Any]:
    receipt = _read(primary_source)
    _validate_primary_source(receipt)
    _validate_broad_artifact(artifact_dir)

    old_run_receipt = lane.diag._run_receipt
    old_stats = lane._stats_from_trades

    def historical_primary(strategy_id: str, out: Path) -> dict[str, Any]:
        if strategy_id != "trend_rider":
            return old_run_receipt(strategy_id, out)
        frozen = copy.deepcopy(receipt)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(frozen, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return frozen

    try:
        lane.diag._run_receipt = historical_primary
        lane._stats_from_trades = _stats_preserve_receipt_order
        result = lane.run(output, artifact_dir)
    finally:
        lane.diag._run_receipt = old_run_receipt
        lane._stats_from_trades = old_stats

    result["historical_parent_binding"] = {
        "primary_source_run_id": PRIMARY_SOURCE_RUN_ID,
        "primary_source_job_id": PRIMARY_SOURCE_JOB_ID,
        "primary_source_completed_trades": PRIMARY_SOURCE_COMPLETED,
        "broad_source_run_id": BROAD_SOURCE_RUN_ID,
        "broad_source_receipt_sha256": BROAD_SOURCE_RECEIPT_SHA256,
        "receipt_order_preserved_for_path_dependent_drawdown": True,
        "thresholds_changed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    result["receipt_sha256"] = lane.hashutil.sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    sample = [
        {"net_bps": 100.0},
        {"net_bps": -40.0},
        {"net_bps": 60.0},
        {"net_bps": -10.0},
    ]
    stats = _stats_preserve_receipt_order(sample)
    assert stats["completed_trades"] == 4
    assert stats["wins"] == 2
    assert abs(float(stats["net_pnl_bps"]) - 110.0) < 1e-12
    assert abs(float(stats["max_drawdown_bps"]) - 40.0) < 1e-12
    assert lane.AUTH["execution_authority"] == "NONE"
    assert lane.AUTH["order_authority"] == "BLOCKED"
    assert lane.AUTH["live_trade_authority"] == "BLOCKED"
    print("PASS_A1_TRENDRIDER_HISTORICAL_PARENT_BIND_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary-source", type=Path)
    ap.add_argument("--exact25-artifact-dir", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_trendrider_lane_aware_synthesis_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.primary_source is None or args.exact25_artifact_dir is None:
        raise SystemExit("PRIMARY_SOURCE_AND_EXACT25_ARTIFACT_REQUIRED")
    result = run(args.primary_source, args.exact25_artifact_dir, args.output)
    print(json.dumps({
        "state": result["state"],
        "parent_states": {x["lane_id"]: x["state"] for x in result["parent_adapters"]},
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
