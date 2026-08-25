#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "backend/research/rebuild/a1_exact25_disposition_ledger_v1.json"
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
BOX_CHILD = ROOT / "backend/research/rebuild/break_and_continue_box_break_child_policy_v1.py"
CONTRACT = ROOT / "backend/research/contracts/a1_iterative_repair_named_channel_gemini_v1.json"
STRATEGY_ID = "break_and_continue"
SCHEMA = "zel.a1.break_box_iterative_dd_repair.v1"

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "protected_mutations": 0,
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _trade_id(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("symbol") or ""), str(row.get("side") or ""),
        int(row.get("signal_ts") or 0), int(row.get("entry_ts") or 0),
    )


def _ordered(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(x) for x in rows), key=lambda x: (int(x.get("exit_ts") or 0), int(x.get("entry_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")))


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    trades = _ordered(rows)
    vals = [float(x.get("net_bps") or 0.0) for x in trades]
    wins = [x for x in vals if x > 0]
    losses = [x for x in vals if x < 0]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    dd_start = 0
    peak_index = -1
    worst_range = (0, -1)
    for i, v in enumerate(vals):
        equity += v
        if equity > peak:
            peak = equity
            peak_index = i
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            dd_start = peak_index + 1
            worst_range = (dd_start, i)
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = math.inf if gross_loss <= 0 and gross_win > 0 else (gross_win / gross_loss if gross_loss > 0 else 0.0)
    streak = 0
    max_streak = 0
    for v in vals:
        if v < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {
        "trades": len(vals),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(vals) if vals else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else None,
        "profit_factor": pf,
        "drawdown_bps": max_dd,
        "max_consecutive_losses": max_streak,
        "worst_drawdown_trade_range": list(worst_range),
    }


def _session(ts_ms: int) -> str:
    hour = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).hour
    if 0 <= hour < 7:
        return "ASIA_00_07_UTC"
    if 7 <= hour < 13:
        return "EUROPE_07_13_UTC"
    if 13 <= hour < 21:
        return "US_13_21_UTC"
    return "LATE_21_24_UTC"


def _dd_episode(rows: Sequence[Mapping[str, Any]], m: Mapping[str, Any]) -> list[dict[str, Any]]:
    ordered = _ordered(rows)
    a, b = list(m.get("worst_drawdown_trade_range") or [0, -1])
    if b < a or a < 0:
        return []
    return ordered[int(a): int(b) + 1]


def _breakdown(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [dict(x) for x in rows]
    by_symbol: dict[str, float] = defaultdict(float)
    by_side: dict[str, float] = defaultdict(float)
    by_session: dict[str, float] = defaultdict(float)
    by_reason: dict[str, float] = defaultdict(float)
    signal_groups: Counter[int] = Counter()
    for x in vals:
        net = float(x.get("net_bps") or 0.0)
        by_symbol[str(x.get("symbol") or "UNKNOWN")] += net
        by_side[str(x.get("side") or "UNKNOWN")] += net
        by_session[_session(int(x.get("signal_ts") or x.get("entry_ts") or 0))] += net
        by_reason[str(x.get("reason") or "UNKNOWN")] += net
        signal_groups[int(x.get("signal_ts") or 0)] += 1
    return {
        "net_bps_by_symbol": dict(sorted(by_symbol.items(), key=lambda kv: kv[1])),
        "net_bps_by_side": dict(sorted(by_side.items(), key=lambda kv: kv[1])),
        "net_bps_by_session": dict(sorted(by_session.items(), key=lambda kv: kv[1])),
        "net_bps_by_exit_reason": dict(sorted(by_reason.items(), key=lambda kv: kv[1])),
        "same_signal_timestamp_group_sizes": dict(Counter(signal_groups.values())),
        "max_same_signal_timestamp_count": max(signal_groups.values(), default=0),
    }


def _same_symbol_overlap_filter(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted((dict(x) for x in rows), key=lambda x: (int(x.get("signal_ts") or 0), str(x.get("symbol") or ""), str(x.get("side") or "")))
    active_until: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for x in ordered:
        symbol = str(x.get("symbol") or "")
        signal = int(x.get("signal_ts") or 0)
        if signal < int(active_until.get(symbol, -1)):
            continue
        out.append(x)
        active_until[symbol] = int(x.get("exit_ts") or signal)
    return out


def _same_timestamp_burst_filter(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for x in rows:
        groups[int(x.get("signal_ts") or 0)].append(dict(x))
    out: list[dict[str, Any]] = []
    for ts in sorted(groups):
        g = groups[ts]
        if len(g) == 1:
            out.extend(g)
    return out


def _avoid_value(rows: Sequence[Mapping[str, Any]], axis: str, value: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for x in rows:
        if axis == "SIDE":
            current = str(x.get("side") or "")
        elif axis == "SESSION":
            current = _session(int(x.get("signal_ts") or x.get("entry_ts") or 0))
        elif axis == "SYMBOL":
            current = str(x.get("symbol") or "")
        else:
            raise RuntimeError(f"UNKNOWN_AXIS:{axis}")
        if current != value:
            out.append(dict(x))
    return out


def _candidate(name: str, axis: str, variant: str, child_rows: Sequence[Mapping[str, Any]], baseline_m: Mapping[str, Any], notes: Sequence[str]) -> dict[str, Any]:
    m = _metrics(child_rows)
    base_pf = float(baseline_m.get("profit_factor") or 0.0)
    pf = float(m.get("profit_factor") or 0.0)
    gate = bool(
        m["trades"] >= max(8, math.ceil(int(baseline_m["trades"]) * 0.60))
        and float(m.get("net_pnl_bps") or -1e18) >= float(baseline_m.get("net_pnl_bps") or -1e18)
        and float(m.get("net_expectancy_bps") or -1e18) >= float(baseline_m.get("net_expectancy_bps") or -1e18)
        and pf >= base_pf
        and float(m.get("drawdown_bps") or 1e18) < float(baseline_m.get("drawdown_bps") or 1e18)
    )
    row = {
        "candidate_id": name,
        "generation": "R3",
        "changed_axis": axis,
        "changed_variant": variant,
        "changed_axis_count": 1,
        "metrics": m,
        "trade_retention_pct": 100.0 * int(m["trades"]) / max(1, int(baseline_m["trades"])),
        "development_upgrade_gate_pass": gate,
        "development_hypothesis_only": True,
        "fresh_oos_required": True,
        "post_outcome_feature_selection_disclosed": axis in {"SIDE_REGIME_OWNER_ONLY", "SESSION_REGIME_OWNER_ONLY", "SYMBOL_REGIME_DIAGNOSTIC_ONLY"},
        "runtime_feature_is_preentry_causal": True,
        "notes": list(notes),
        **AUTH,
    }
    row["candidate_sha256"] = _sha(row)
    return row


def evaluate(parent: Mapping[str, Any], box: Mapping[str, Any], boundary: str) -> dict[str, Any]:
    parent_rows = [dict(x) for x in (parent.get("trades") or [])]
    box_rows = [dict(x) for x in (box.get("trades") or [])]
    parent_ids = {_trade_id(x) for x in parent_rows}
    added = [x for x in box_rows if _trade_id(x) not in parent_ids]
    base = _metrics(box_rows)
    episode = _dd_episode(box_rows, base)
    attribution = {
        "box_child_metrics": base,
        "parent_metrics_same_trade_path_definition": _metrics(parent_rows),
        "added_trade_count": len(added),
        "added_trade_metrics": _metrics(added),
        "added_trade_breakdown": _breakdown(added),
        "worst_drawdown_episode_trade_count": len(episode),
        "worst_drawdown_episode_net_bps": sum(float(x.get("net_bps") or 0.0) for x in episode),
        "worst_drawdown_episode_breakdown": _breakdown(episode),
        "worst_drawdown_episode_trades": [
            {k: x.get(k) for k in ("symbol", "side", "signal_ts", "entry_ts", "exit_ts", "reason", "net_bps")}
            for x in episode
        ],
    }

    losses = [x for x in episode if float(x.get("net_bps") or 0.0) < 0.0] or [x for x in box_rows if float(x.get("net_bps") or 0.0) < 0.0]
    side_loss = Counter(str(x.get("side") or "") for x in losses)
    session_loss = Counter(_session(int(x.get("signal_ts") or x.get("entry_ts") or 0)) for x in losses)
    symbol_loss = Counter(str(x.get("symbol") or "") for x in losses)
    dominant_side = side_loss.most_common(1)[0][0] if side_loss else None
    dominant_session = session_loss.most_common(1)[0][0] if session_loss else None
    dominant_symbol = symbol_loss.most_common(1)[0][0] if symbol_loss else None
    attribution["dominant_loss_context"] = {
        "side": dominant_side,
        "session": dominant_session,
        "symbol": dominant_symbol,
        "selection_scope": "DEVELOPMENT_DD_EPISODE_ONLY; MUST_FREEZE_AND_PROVE_FRESH",
    }

    candidates: list[dict[str, Any]] = []
    candidates.append(_candidate(
        "break_box_r3_same_symbol_overlap_v1", "SAME_SYMBOL_OVERLAP_CONTEXT_ONLY", "ONE_ACTIVE_PER_SYMBOL",
        _same_symbol_overlap_filter(box_rows), base,
        ["causal at signal time", "prevents overlapping same-symbol risk concentration", "no numeric threshold sweep"],
    ))
    candidates.append(_candidate(
        "break_box_r3_common_timestamp_burst_v1", "COMMON_MODE_EXPOSURE_CONTEXT_ONLY", "AVOID_MULTI_SYMBOL_SAME_SIGNAL_TIMESTAMP_BURST",
        _same_timestamp_burst_filter(box_rows), base,
        ["causal same-timestamp common-mode context", "development test only", "fresh proof required"],
    ))
    if dominant_session:
        candidates.append(_candidate(
            "break_box_r3_session_avoid_v1", "SESSION_REGIME_OWNER_ONLY", f"AVOID_{dominant_session}",
            _avoid_value(box_rows, "SESSION", dominant_session), base,
            ["session selected from R2 development DD attribution", "fixed UTC session definition", "fresh proof mandatory"],
        ))
    if dominant_side:
        candidates.append(_candidate(
            "break_box_r3_side_avoid_v1", "SIDE_REGIME_OWNER_ONLY", f"AVOID_{dominant_side.upper()}",
            _avoid_value(box_rows, "SIDE", dominant_side), base,
            ["side selected from R2 development DD attribution", "preentry causal side", "fresh proof mandatory"],
        ))
    if dominant_symbol:
        candidates.append(_candidate(
            "break_box_r3_symbol_diagnostic_v1", "SYMBOL_REGIME_DIAGNOSTIC_ONLY", f"AVOID_{dominant_symbol}",
            _avoid_value(box_rows, "SYMBOL", dominant_symbol), base,
            ["diagnostic only; symbol exclusion is not preferred final architecture", "use only to establish concentration cause", "fresh promotion forbidden from this diagnostic alone"],
        ))

    candidates.sort(key=lambda x: (
        not bool(x["development_upgrade_gate_pass"]),
        float(x["metrics"].get("drawdown_bps") or 1e18),
        -float(x["metrics"].get("net_pnl_bps") or -1e18),
        -float(x["metrics"].get("net_expectancy_bps") or -1e18),
        -float(x["trade_retention_pct"]),
    ))
    ready = [x for x in candidates if x["development_upgrade_gate_pass"]]
    if ready:
        state = "PASS_R3_DD_REPAIR_DEVELOPMENT_CANDIDATE_READY"
        next_step = "FREEZE_SELECTED_ONE_AXIS_CHILD_AND_START_INDEPENDENT_FRESH_OOS; DO_NOT_REPLACE_INCUMBENT_YET"
    else:
        state = "HOLD_R3_DD_REPAIR_NEXT_DISTINCT_AXIS_REQUIRED"
        next_step = "PRESERVE_BOX_PARTIAL_SUCCESS; CONTINUE_R4_DISTINCT_AXIS_REPAIR_WITHOUT_RESET"
    out = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY_ID,
        "comparison_boundary_utc": boundary,
        "best_partial_success_child": "break_and_continue_box_break_child_v1",
        "R2_dd_root_cause_attribution": attribution,
        "R3_candidates": candidates,
        "R3_ready_count": len(ready),
        "R3_best_candidate": ready[0] if ready else None,
        "next": next_step,
        "policy": {
            "preserve_partial_success": True,
            "restart_from_zero_forbidden": True,
            "one_primary_axis_per_child": True,
            "numeric_threshold_sweep": False,
            "post_outcome_runtime_feature_use": False,
            "development_selection_disclosed": True,
            "fresh_oos_required": True,
            "continue_R4_RN_if_dd_only_tradeoff_remains": True,
            "stop_after_two_consecutive_distinct_axis_economic_failures": True,
        },
        **AUTH,
    }
    out["receipt_sha256"] = _sha(out)
    return out


def run(out: Path) -> dict[str, Any]:
    contract = _read(CONTRACT)
    if not bool(((contract.get("iterative_pareto_repair") or {}).get("enabled"))):
        raise RuntimeError("ITERATIVE_REPAIR_CONTRACT_DISABLED")
    ledger = _read(LEDGER)
    inventory = _read(INVENTORY)
    row = (ledger.get("strategies") or {}).get(STRATEGY_ID)
    if not isinstance(row, Mapping):
        raise RuntimeError("BREAK_STRATEGY_MISSING")
    boundary = str(row.get("prospective_boundary_utc") or "")
    if not boundary:
        raise RuntimeError("BREAK_BOUNDARY_MISSING")
    parent_policy = ROOT / str(inventory["strategies"][STRATEGY_ID]["policy_owner"])
    with tempfile.TemporaryDirectory(prefix="break_box_iterative_dd_") as td:
        p = Path(td)
        parent, _ = run_terminal_shadow(strategy_id=STRATEGY_ID, policy_path=parent_policy, fresh_boundary_utc=boundary, out=p / "parent.json")
        box, _ = run_terminal_shadow(strategy_id=STRATEGY_ID, policy_path=BOX_CHILD, fresh_boundary_utc=boundary, out=p / "box.json")
    result = evaluate(parent, box, boundary)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake_parent = {
        "trades": [
            {"symbol":"BTC-USDT","side":"long","signal_ts":1_000,"entry_ts":2_000,"exit_ts":3_000,"reason":"TP","net_bps":100.0},
            {"symbol":"ETH-USDT","side":"long","signal_ts":4_000,"entry_ts":5_000,"exit_ts":6_000,"reason":"SL","net_bps":-20.0},
        ]
    }
    fake_box = {
        "trades": fake_parent["trades"] + [
            {"symbol":"ETH-USDT","side":"long","signal_ts":7_000,"entry_ts":8_000,"exit_ts":9_000,"reason":"TP","net_bps":200.0},
            {"symbol":"BTC-USDT","side":"short","signal_ts":10_000,"entry_ts":11_000,"exit_ts":12_000,"reason":"SL","net_bps":-40.0},
        ]
    }
    r = evaluate(fake_parent, fake_box, "2026-01-01T00:00:00Z")
    assert r["strategy_id"] == STRATEGY_ID
    assert r["R2_dd_root_cause_attribution"]["added_trade_count"] == 2
    assert r["policy"]["restart_from_zero_forbidden"] is True
    assert r["selection_authority"] is False and r["execution_authority"] == "NONE"
    print("PASS_A1_BREAK_BOX_ITERATIVE_DD_REPAIR_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_box_iterative_dd_repair_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    best = r.get("R3_best_candidate") or {}
    print(json.dumps({
        "state": r["state"], "ready": r["R3_ready_count"],
        "best": best.get("candidate_id"), "best_dd": (best.get("metrics") or {}).get("drawdown_bps"),
        "next": r["next"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
