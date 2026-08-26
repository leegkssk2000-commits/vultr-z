#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7 as v7
from backend.research.architecture_factory import a1_top5_evolutionary_synthesis_v7_2 as v72
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil

ROOT = Path(__file__).resolve().parents[3]
SSOT = ROOT / "backend/research/rebuild/a1_production_highwr_top5_ssot_v1.json"
LATEST = ROOT / "backend/research/architecture_factory/a1_top5_evolutionary_synthesis_latest.json"
SCHEMA = "zel.a1_top5_evolutionary_synthesis.v7_3_highwr_lane_ssot"
EXPECTED_BREAK_AXIS = "DONOR__VOL_SPIKE_FADE__VOLATILITY_EXHAUSTION__ONLY"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _production_lanes(ssot: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(x) for x in (ssot.get("production_top5") or []) if isinstance(x, Mapping)]
    if len(rows) != 5:
        raise RuntimeError(f"HIGHWR_EXACT5_LANES_REQUIRED:{len(rows)}")
    lane_ids = [str(x.get("lane_id") or "") for x in rows]
    if any(not x for x in lane_ids) or len(set(lane_ids)) != 5:
        raise RuntimeError(f"HIGHWR_UNIQUE_LANE_IDS_REQUIRED:{lane_ids}")
    if bool(ssot.get("low_wr_fallback_allowed")):
        raise RuntimeError("LOW_WR_FALLBACK_MUST_REMAIN_DISABLED")
    return rows


def _strategy_lane_counts(lanes: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in lanes:
        sid = str(row.get("strategy_id") or "")
        out[sid] = out.get(sid, 0) + 1
    return out


def _eligible_host_strategies(lanes: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    counts = _strategy_lane_counts(lanes)
    hosts: list[str] = []
    blocked: dict[str, str] = {}
    for row in lanes:
        lane_id = str(row.get("lane_id") or "")
        sid = str(row.get("strategy_id") or "")
        if counts.get(sid, 0) > 1:
            blocked[lane_id] = "BLOCKED_LANE_COLLISION_REQUIRES_LANE_AWARE_EXECUTOR"
            continue
        if row.get("challenger_parent_eligible") is not True:
            blocked[lane_id] = "BLOCKED_DISPLAY_ONLY_NOT_CHALLENGER_PARENT"
            continue
        if sid not in hosts:
            hosts.append(sid)
    return hosts, blocked


def _protected_strategy_ids(lanes: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(x.get("strategy_id") or "") for x in lanes if x.get("strategy_id")))


def _sanitize_side_rule(rule: str) -> tuple[str, bool]:
    text = str(rule or "").strip()
    # Preserve nested ternary truth table while translating it to the frozen two-side grammar.
    # long if A else short if B else long  == long if (A) or not (B) else short
    if text.startswith("long if ") and " else short if " in text and text.endswith(" else long"):
        left = text[len("long if "):]
        a, tail = left.split(" else short if ", 1)
        b = tail[: -len(" else long")]
        return f"long if ({a.strip()}) or not ({b.strip()}) else short", True
    # short if A else long if B else short == short if (A) or not (B) else long
    if text.startswith("short if ") and " else long if " in text and text.endswith(" else short"):
        left = text[len("short if "):]
        a, tail = left.split(" else long if ", 1)
        b = tail[: -len(" else short")]
        return f"short if ({a.strip()}) or not ({b.strip()}) else long", True
    return text, False


def _sanitize_attempt(original):
    def wrapped(provider, prompt, source_ids, axes, readiness):
        rows, meta = original(provider, prompt, source_ids, axes, readiness)
        fixed = 0
        out: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            spec = row.get("executable_spec")
            if isinstance(spec, Mapping):
                spec2 = dict(spec)
                new_rule, changed = _sanitize_side_rule(str(spec2.get("side_rule") or ""))
                if changed:
                    spec2["side_rule"] = new_rule
                    row["executable_spec"] = spec2
                    row["side_rule_grammar_repair"] = "NESTED_TERNARY_TO_EQUIVALENT_BINARY"
                    fixed += 1
            out.append(row)
        meta2 = dict(meta)
        meta2["side_rule_grammar_repair_count"] = fixed
        return out, meta2
    return wrapped


def run(output: Path) -> dict[str, Any]:
    ssot = _read(SSOT)
    lanes = _production_lanes(ssot)
    eligible_hosts, blocked = _eligible_host_strategies(lanes)
    # Current strategy-id evaluator cannot distinguish the two TrendRider lanes and
    # Keltner/Supertrend are display-only parents. Break is therefore the only safe host.
    if eligible_hosts != ["break_and_continue"]:
        raise RuntimeError(f"EXPECTED_ONLY_BREAK_ACTIONABLE:{eligible_hosts}")

    protected = _protected_strategy_ids(lanes)
    original_order = v7._host_order
    original_pool = v7._donor_pool
    original_attempt = v7.v3._attempt

    def highwr_host_order(_league: Mapping[str, Any]) -> list[str]:
        return list(eligible_hosts)

    def protected_pool(league: Mapping[str, Any], _hosts: list[str]) -> list[dict[str, Any]]:
        # Never recycle any current high-WR production strategy as a donor merely
        # because only Break is executable in the legacy strategy-id evaluator.
        return original_pool(league, protected)

    try:
        v7._host_order = highwr_host_order
        v7._donor_pool = protected_pool
        v7.v3._attempt = _sanitize_attempt(original_attempt)
        result = dict(v72.run(output))
    finally:
        v7._host_order = original_order
        v7._donor_pool = original_pool
        v7.v3._attempt = original_attempt

    plans = result.get("host_plans") or {}
    break_plan = plans.get("break_and_continue") if isinstance(plans, Mapping) else None
    axis = str((break_plan or {}).get("next_axis") or "") if isinstance(break_plan, Mapping) else ""
    if axis != EXPECTED_BREAK_AXIS:
        raise RuntimeError(f"OFFICIAL_REMAINING_AXIS_MISMATCH:{axis}")

    technical_states: list[str] = []
    for key in ("initial_development_economics", "spec_repair_development_economics", "second_step_development_economics"):
        block = result.get(key)
        if not isinstance(block, Mapping):
            continue
        for raw in block.get("rows") or []:
            if isinstance(raw, Mapping):
                technical_states.append(str(raw.get("state") or ""))
    side_rule_reject_present = any(x == "REJECT_UNEXECUTABLE_SPEC" for x in technical_states)

    result["schema_version"] = SCHEMA
    result["production_top5_source"] = str(SSOT.relative_to(ROOT))
    result["production_top5_lane_ids"] = [str(x.get("lane_id") or "") for x in lanes]
    result["production_top5_lanes"] = lanes
    result["legacy_strategy_id_synthesis_hosts"] = list(eligible_hosts)
    result["blocked_lane_routes"] = blocked
    result["protected_current_strategy_ids"] = protected
    result["official_remaining_axis_count"] = 1
    result["official_remaining_axis"] = {
        "lane_id": "break_and_continue_main",
        "strategy_id": "break_and_continue",
        "axis": axis,
        "policy": "EXECUTE_ONLY_THIS_AXIS_NO_TOP5_RESET",
    }
    result["trend_rider_lane_collision_blocked"] = True
    result["keltner_supertrend_display_only_parent_blocked"] = True
    result["trend_ma_top5_eligible"] = False
    result["low_wr_fallback_allowed"] = False
    result["nested_side_rule_grammar_guard"] = True
    result["side_rule_reject_present_after_guard"] = side_rule_reject_present
    result["selection_authority"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = "NONE"
    result["order_authority"] = "BLOCKED"
    result["live_trade_authority"] = "BLOCKED"
    result["exchange_order_submitted"] = False
    result["protected_mutations"] = 0
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    sample = {
        "low_wr_fallback_allowed": False,
        "production_top5": [
            {"lane_id": "tr1", "strategy_id": "trend_rider", "challenger_parent_eligible": True},
            {"lane_id": "tr2", "strategy_id": "trend_rider", "challenger_parent_eligible": True},
            {"lane_id": "br", "strategy_id": "break_and_continue", "challenger_parent_eligible": True},
            {"lane_id": "ke", "strategy_id": "keltner_trend", "challenger_parent_eligible": False},
            {"lane_id": "st", "strategy_id": "supertrend_pullback", "challenger_parent_eligible": False},
        ],
    }
    lanes = _production_lanes(sample)
    hosts, blocked = _eligible_host_strategies(lanes)
    assert hosts == ["break_and_continue"]
    assert blocked["tr1"].startswith("BLOCKED_LANE_COLLISION")
    assert blocked["ke"] == "BLOCKED_DISPLAY_ONLY_NOT_CHALLENGER_PARENT"
    rule, changed = _sanitize_side_rule("long if close > highest(close,20) else short if close < lowest(close,20) else long")
    assert changed and rule == "long if (close > highest(close,20)) or not (close < lowest(close,20)) else short"
    assert EXPECTED_BREAK_AXIS.endswith("__ONLY")
    assert v7.v3.AUTH["execution_authority"] == "NONE" and v7.v3.AUTH["order_authority"] == "BLOCKED"
    print("PASS_A1_TOP5_EVOLUTIONARY_SYNTHESIS_V7_3_HIGHWR_SSOT_SELF_TEST")
    print("PASS_ONLY_BREAK_CURRENT_LANE_ACTIONABLE_AND_NESTED_SIDE_RULE_GUARD")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=LATEST)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({
        "state": result.get("state"),
        "lanes": result.get("production_top5_lane_ids"),
        "active_hosts": result.get("legacy_strategy_id_synthesis_hosts"),
        "remaining_axis": result.get("official_remaining_axis"),
        "development_pass": result.get("development_economic_pass_count"),
        "side_rule_reject": result.get("side_rule_reject_present_after_guard"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
