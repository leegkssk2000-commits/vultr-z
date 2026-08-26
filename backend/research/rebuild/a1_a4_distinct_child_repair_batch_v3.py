#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_a4_distinct_child_repair_batch_v2 as v2

SCHEMA = "zel.a1.a4.distinct_child_repair_batch.v3"
POLICY = v2.PRODUCTION_POLICY


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _break_main(policy: Mapping[str, Any]) -> dict[str, Any]:
    raw = ((policy.get("strategies") or {}).get("break_and_continue") or {}).get("production_main") or {}
    metrics = dict(raw.get("metrics") or {})
    required = ("trades", "win_rate", "net_pnl_bps", "net_expectancy_bps", "profit_factor", "drawdown_bps")
    if raw.get("identity") != "break_and_continue" or raw.get("role") != "MAIN" or raw.get("frozen") is not True:
        raise RuntimeError("BREAK_PRODUCTION_MAIN_NOT_FROZEN")
    if any(k not in metrics for k in required):
        raise RuntimeError("BREAK_PRODUCTION_MAIN_METRICS_INCOMPLETE")
    return {
        "identity": "break_and_continue",
        "role": "MAIN",
        "frozen": True,
        "source_path": raw.get("source_path"),
        "source_lineage_axis": raw.get("source_lineage_axis"),
        "metrics": metrics,
        "concentration_blocker_count": int(raw.get("concentration_blocker_count") or 0),
    }


def _break_main_blockers(main: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    m = candidate.get("metrics") or {}
    base_m = main.get("metrics") or {}
    blockers: list[str] = []

    if int(m.get("trades") or 0) < int(base_m.get("trades") or 0):
        blockers.append("TRADE_COUNT_BELOW_FROZEN_MAIN")
    if _num(m.get("win_rate"), -1.0) + 1e-12 < _num(base_m.get("win_rate"), 1.0):
        blockers.append("WIN_RATE_BELOW_FROZEN_MAIN")
    if _num(m.get("net_pnl_bps"), float("-inf")) + 1e-9 < _num(base_m.get("net_pnl_bps"), float("inf")):
        blockers.append("NET_PNL_BELOW_FROZEN_MAIN")
    if _num(m.get("net_expectancy_bps"), float("-inf")) + 1e-9 < _num(base_m.get("net_expectancy_bps"), float("inf")):
        blockers.append("NET_EXPECTANCY_BELOW_FROZEN_MAIN")
    if _num(m.get("profit_factor"), float("-inf")) + 1e-9 < _num(base_m.get("profit_factor"), float("inf")):
        blockers.append("PROFIT_FACTOR_BELOW_FROZEN_MAIN")
    if _num(m.get("drawdown_bps"), float("inf")) > _num(base_m.get("drawdown_bps"), 0.0) + 1e-9:
        blockers.append("DRAWDOWN_ABOVE_FROZEN_MAIN")

    child_h5 = int((candidate.get("concentration") or {}).get("blocker_count") or 0)
    if child_h5 >= int(main.get("concentration_blocker_count") or 0):
        blockers.append("CONCENTRATION_NOT_BETTER_THAN_FROZEN_MAIN")
    if not bool(candidate.get("economic_gate_pass")):
        blockers.append("ECONOMIC_GATE_FAIL")
    return blockers


def _apply_break_main_gate(row: dict[str, Any], main: Mapping[str, Any]) -> dict[str, Any]:
    row["candidate_generation_parent_metrics"] = dict(row.get("parent_metrics") or {})
    row["production_main"] = dict(main)
    candidates: list[dict[str, Any]] = []
    for raw in row.get("candidates") or []:
        candidate = dict(raw)
        candidate["candidate_generation_gate"] = dict(candidate.get("production_gate") or {})
        blockers = _break_main_blockers(main, candidate)
        candidate["production_gate"] = {
            "reference": "FROZEN_BREAK_MAIN",
            "passed": not blockers,
            "blockers": blockers,
            "trade_count_non_decrease_required": True,
            "win_rate_non_decrease_required": True,
            "net_pnl_non_decrease_required": True,
            "net_expectancy_non_decrease_required": True,
            "profit_factor_non_decrease_required": True,
            "drawdown_non_increase_required": True,
            "concentration_improvement_required": True,
        }
        candidate["development_candidate_ready"] = not blockers
        candidate["disposition"] = "CHALLENGER_READY_FOR_FRESH_OOS" if not blockers else (
            "PARTS_ONLY" if bool(candidate.get("economic_gate_pass")) else "REJECT"
        )
        candidate.pop("candidate_sha256", None)
        candidate["candidate_sha256"] = v2.base.stable(candidate)
        candidates.append(candidate)

    candidates.sort(key=lambda x: (
        not bool(x.get("development_candidate_ready")),
        len((x.get("production_gate") or {}).get("blockers") or []),
        -_num((x.get("metrics") or {}).get("win_rate"), -1.0),
        -_num((x.get("metrics") or {}).get("net_expectancy_bps"), -1e18),
        -_num((x.get("metrics") or {}).get("profit_factor"), -1e18),
        _num((x.get("metrics") or {}).get("drawdown_bps"), 1e18),
        str(x.get("candidate_id") or ""),
    ))
    ready = [x for x in candidates if x.get("development_candidate_ready")]
    row["candidates"] = candidates
    row["development_ready_count"] = len(ready)
    row["next_distinct_child_candidate"] = ready[0] if ready else None
    row["parent_metrics"] = dict(main.get("metrics") or {})
    row["parent_role"] = "FROZEN_PRODUCTION_MAIN"
    row["main_preserved"] = True
    return row


def run(parent_paths: Mapping[str, Path], output: Path) -> dict[str, Any]:
    policy = v2.read(POLICY)
    main = _break_main(policy)
    base_result = v2.run(parent_paths, output)
    strategies = {str(k): dict(v) for k, v in (base_result.get("strategies") or {}).items()}
    strategies["break_and_continue"] = _apply_break_main_gate(strategies["break_and_continue"], main)

    ready: list[dict[str, Any]] = []
    for sid, row in strategies.items():
        ready.extend([dict(x) for x in row.get("candidates") or [] if x.get("development_candidate_ready")])
    ready.sort(key=lambda x: (
        len((x.get("production_gate") or {}).get("blockers") or []),
        -_num((x.get("metrics") or {}).get("win_rate"), -1.0),
        -_num((x.get("metrics") or {}).get("net_expectancy_bps"), -1e18),
        str(x.get("candidate_id") or ""),
    ))

    result = dict(base_result)
    result["schema_version"] = SCHEMA
    result["strategies"] = strategies
    result["development_ready_count"] = len(ready)
    result["next_distinct_child_candidate"] = ready[0] if ready else None
    result["state"] = "PASS_A4_DISTINCT_CHILD_REPAIR_READY" if ready else "HOLD_A4_NEXT_DISTINCT_CHILD_REQUIRED"
    result["break_main"] = main
    result["break_main_preserved"] = True
    result["break_weak_challenger_cannot_replace_main"] = True
    result["policy"] = dict(result.get("policy") or {})
    result["policy"].update({
        "break_reference_is_frozen_main": True,
        "win_rate_non_decrease_required": True,
        "drawdown_non_increase_required": True,
        "parts_only_on_economic_pass_but_main_fail": True,
    })
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v2.base.stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    policy = v2.read(POLICY)
    main = _break_main(policy)
    m = main["metrics"]
    assert int(m["trades"]) == 9
    assert abs(float(m["win_rate"]) - 5.0 / 9.0) < 1e-12
    assert float(m["net_pnl_bps"]) > 9000.0
    assert float(m["profit_factor"]) > 16.0

    same = {
        "metrics": dict(m),
        "concentration": {"blocker_count": 1},
        "economic_gate_pass": True,
    }
    assert _break_main_blockers(main, same) == []

    weak = json.loads(json.dumps(same))
    weak["metrics"]["win_rate"] = 0.25
    weak["metrics"]["net_expectancy_bps"] = 376.9
    weak["metrics"]["profit_factor"] = 4.34
    weak["metrics"]["drawdown_bps"] = 1282.0
    blockers = _break_main_blockers(main, weak)
    assert "WIN_RATE_BELOW_FROZEN_MAIN" in blockers
    assert "NET_EXPECTANCY_BELOW_FROZEN_MAIN" in blockers
    assert "PROFIT_FACTOR_BELOW_FROZEN_MAIN" in blockers
    assert "DRAWDOWN_ABOVE_FROZEN_MAIN" in blockers

    print("PASS_A1_A4_DISTINCT_CHILD_REPAIR_BATCH_V3_BREAK_MAIN_LOCK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--break-parent", type=Path)
    ap.add_argument("--supertrend-parent", type=Path)
    ap.add_argument("--keltner-parent", type=Path)
    ap.add_argument("--macd-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_a4_distinct_child_repair_batch_v3.json"))
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
        raise SystemExit("all four candidate-generation parent receipts required")
    result = run({k: v for k, v in paths.items() if v is not None}, args.out)
    print("A1_A4_DISTINCT_CHILD_REPAIR_V3=" + json.dumps({
        "state": result["state"],
        "ready": result["development_ready_count"],
        "next": (result.get("next_distinct_child_candidate") or {}).get("candidate_id"),
        "break_main_wr": result["break_main"]["metrics"]["win_rate"],
        "break_main_trades": result["break_main"]["metrics"]["trades"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
