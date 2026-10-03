#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_a4_distinct_child_repair_batch_v1 as base
from backend.research.rebuild import a1_production_compression_gate_v1 as production

ROOT = Path(__file__).resolve().parents[3]
HARDENING_POLICY = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
SCHEMA = "zel.a1.a4.distinct_child_repair_batch.production.v1"
_ORIGINAL_CANDIDATE = base._candidate


def _production_candidate(**kwargs: Any) -> dict[str, Any]:
    row = _ORIGINAL_CANDIDATE(**kwargs)
    hard: Mapping[str, Any] = kwargs["hard"]
    parent_metrics = base.metrics(kwargs["parent_trades"])
    child_metrics = base.metrics(kwargs["child_trades"])
    gate = production.evaluate_child(parent_metrics, child_metrics, hard)
    row["production_gate"] = gate
    row["production_gate_pass"] = bool(gate["production_ready"])
    row["development_candidate_ready_pre_production_gate"] = bool(row["development_candidate_ready"])
    row["development_candidate_ready"] = bool(row["development_candidate_ready"] and gate["production_ready"])
    row["candidate_sha256"] = base.stable(row)
    return row


def _with_production_gate(fn, *args, **kwargs):
    prior = base._candidate
    base._candidate = _production_candidate
    try:
        return fn(*args, **kwargs)
    finally:
        base._candidate = prior


def evaluate(strategy_id: str, parent: Mapping[str, Any], hard: Mapping[str, Any]) -> dict[str, Any]:
    row = _with_production_gate(base.evaluate, strategy_id, parent, hard)
    row["schema_version"] = SCHEMA
    row["production_compression_gate_enforced"] = True
    return row


def run(parent_paths: Mapping[str, Path], output: Path) -> dict[str, Any]:
    result = _with_production_gate(base.run, parent_paths, output)
    result["schema_version"] = SCHEMA
    result["production_compression_gate_enforced"] = True
    result["policy"]["incumbent_collector_always_on"] = True
    result["policy"]["challenger_parallel_only"] = True
    result["policy"]["strict25_background_certification_only"] = True
    result["receipt_sha256"] = base.stable(result)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    hard = base.read(HARDENING_POLICY)
    parent = {"trades": 9, "net_pnl_bps": 3713.563248004183, "net_expectancy_bps": 412.61813866713146,
              "profit_factor": 7.57329610968171, "payoff": 2.0, "drawdown_bps": 223.13453260982578}
    child = {"trades": 7, "net_pnl_bps": 2146.833589174235, "net_expectancy_bps": 306.6905127391764,
             "profit_factor": 7.59991523339377, "payoff": 2.0, "drawdown_bps": 170.51152272604122}
    out = production.evaluate_child(parent, child, hard)
    assert out["production_ready"] is False
    assert "PARENT_RELATIVE_PNL_AND_EXPECTANCY_REGRESSION" in out["blockers"]
    print("PASS_A1_A4_PRODUCTION_COMPRESSION_WRAPPER_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--break-parent", type=Path)
    ap.add_argument("--supertrend-parent", type=Path)
    ap.add_argument("--keltner-parent", type=Path)
    ap.add_argument("--macd-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_a4_distinct_child_repair_batch_production_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    paths = {
        "break_and_continue": args.break_parent,
        "supertrend_pullback": args.supertrend_parent,
        "keltner_trend": args.keltner_parent,
        "trend_ma_macd": args.macd_parent,
    }
    if any(v is None for v in paths.values()):
        raise SystemExit("all four exact parent receipts required")
    result = run({k: v for k, v in paths.items() if v is not None}, args.out)
    print("A1_A4_PRODUCTION_COMPRESSION=" + json.dumps({
        "state": result["state"],
        "ready": result["development_ready_count"],
        "next": (result.get("next_distinct_child_candidate") or {}).get("candidate_id"),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
