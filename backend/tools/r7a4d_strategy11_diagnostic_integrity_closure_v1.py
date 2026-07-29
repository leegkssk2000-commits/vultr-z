from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay
from backend.tools import r7a4d_strategy11_rbreaker_signal_boundary_distance_v1 as rbreaker_v1
from backend.tools import r7a4d_strategy11_rbreaker_signal_boundary_distance_v2 as rbreaker_v2
from backend.tools import r7a4d_strategy11_rbreaker_source_causal_trace_v1 as rbreaker_blocker
from backend.tools import r7a4d_strategy11_session_bias_prior_range_repair_v1 as session_bias
from backend.tools import r7a4d_strategy11_sr_levels_prior_range_repair_v1 as sr_levels

VERSION = "R7A4D_STRATEGY11_DIAGNOSTIC_INTEGRITY_CLOSURE_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}

_ORIGINAL_EVALUATE = replay.evaluate


def _source_bound_evaluate(**kwargs: Any) -> dict[str, Any]:
    config = kwargs.get("config")
    if isinstance(config, Mapping):
        repair = config.get("repair")
        if isinstance(repair, Mapping):
            patched_source_sha = str(repair.get("patched_source_sha") or "")
            if len(patched_source_sha) == 64:
                kwargs["strategy_source_sha"] = patched_source_sha
    return _ORIGINAL_EVALUATE(**kwargs)


def _install_exact_window_floor(module: Any) -> None:
    original = module.compare

    def compare(candidate: Mapping[str, Any], control: Mapping[str, Any]) -> dict[str, Any]:
        result = original(candidate, control)
        checks = dict(result.get("checks") or {})
        positive = int(candidate.get("positive_fresh_windows") or 0)
        total = len(replay.repair.FRESH_ROLES)
        exact_two_thirds = positive * 3 >= total * 2
        checks["positive_windows_pct"] = exact_two_thirds
        checks["positive_windows_two_thirds_exact"] = exact_two_thirds
        result["checks"] = checks
        result["positive_window_count"] = positive
        result["positive_window_total"] = total
        result["state"] = "PASS_DIAGNOSTIC_REPAIR" if all(checks.values()) else "PARTIAL_REPAIR_ONLY"
        return result

    module.compare = compare


def _corrected_rbreaker_trace(
    strategy: Any,
    symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], Any],
    warmup_bars: int,
    history_bars: int,
) -> dict[str, Any]:
    cfg = rbreaker_blocker.RBreakerLikeConfig()
    counts: Counter[str] = Counter()
    per_window: defaultdict[str, Counter[str]] = defaultdict(Counter)
    per_symbol: defaultdict[str, Counter[str]] = defaultdict(Counter)
    samples: list[dict[str, Any]] = []
    calls = 0

    def add(name: str, window_id: str, symbol: str) -> None:
        counts[name] += 1
        per_window[window_id][name] += 1
        per_symbol[symbol][name] += 1

    for window_id in replay.repair.FRESH_ROLES:
        for symbol in symbols:
            frame = frames[(window_id, symbol)]
            for index in range(warmup_bars, len(frame) - 1):
                history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
                result = replay.exact._call_strategy(
                    strategy,
                    history,
                    {
                        "position_side": "",
                        "position_qty": 0.0,
                        "avg_entry": 0.0,
                        "add_count": 0,
                        "last_add_price": 0.0,
                    },
                )
                calls += 1
                indicators = result.get("indicators")
                if not isinstance(indicators, Mapping):
                    continue

                price = float(indicators["price"])
                atr_now = float(indicators["atr"])
                mid = float(indicators["mid"])
                breakout_buy = float(indicators["breakout_buy"])
                breakout_sell = float(indicators["breakout_sell"])
                rev_buy = float(indicators["rev_buy"])
                rev_sell = float(indicators["rev_sell"])
                prev = history.iloc[-2]
                prev_close = float(prev["close"])
                prev_high = float(prev["high"])
                prev_low = float(prev["low"])

                components = {
                    "long_break_price": price > breakout_buy + atr_now * cfg.breakout_buffer_atr,
                    "long_break_prev": prev_close <= breakout_buy,
                    "short_break_price": price < breakout_sell - atr_now * cfg.breakout_buffer_atr,
                    "short_break_prev": prev_close >= breakout_sell,
                    "long_reversal_touch": prev_low <= rev_buy,
                    "long_reversal_reclaim": price > mid + atr_now * cfg.reversal_reclaim_atr,
                    "short_reversal_touch": prev_high >= rev_sell,
                    "short_reversal_reclaim": price < mid - atr_now * cfg.reversal_reclaim_atr,
                }
                for key, value in components.items():
                    if value:
                        add(f"{key}_true", window_id, symbol)

                signals = {
                    "long_break": bool(indicators.get("long_break")),
                    "short_break": bool(indicators.get("short_break")),
                    "long_reversal": bool(indicators.get("long_reversal")),
                    "short_reversal": bool(indicators.get("short_reversal")),
                }
                active_signals = [name for name, active in signals.items() if active]
                why = str(result.get("why") or "")
                if why == "rbr_volatility_out_of_range":
                    first_blocker = "volatility_gate_block"
                elif why == "rbr_late_chase_block":
                    first_blocker = "late_chase_block"
                else:
                    first_blocker = "entry_eligible"

                if active_signals and first_blocker == "entry_eligible":
                    add("entry_eligible_call", window_id, symbol)

                for signal in active_signals:
                    add(f"{signal}_true", window_id, symbol)
                    add(f"{signal}_{first_blocker}", window_id, symbol)
                    if len(samples) < 30:
                        distance_name = (
                            "dist_beyond_signal_atr"
                            if indicators.get("dist_beyond_signal_atr") is not None
                            else "dist_from_fast_atr"
                        )
                        samples.append({
                            "window_id": window_id,
                            "symbol": symbol,
                            "signal": signal,
                            "first_blocker": first_blocker,
                            "gate_result_source": "strategy_why",
                            "atr_pct_reported": indicators.get("atr_pct"),
                            "distance_metric": distance_name,
                            "dist_beyond_signal_atr": indicators.get("dist_beyond_signal_atr"),
                            "dist_from_fast_atr": indicators.get("dist_from_fast_atr"),
                            "active_signal_boundary": indicators.get("active_signal_boundary"),
                            "price": price,
                            "mid": mid,
                            "breakout_buy": breakout_buy,
                            "breakout_sell": breakout_sell,
                            "rev_buy": rev_buy,
                            "rev_sell": rev_sell,
                        })

                if str(result.get("action") or "hold").lower() == "enter":
                    add("actual_enter", window_id, symbol)

    signal_names = ("long_break", "short_break", "long_reversal", "short_reversal")
    blocker_names = ("volatility_gate_block", "late_chase_block", "entry_eligible")
    identities = {
        signal: counts[f"{signal}_true"]
        == sum(counts[f"{signal}_{blocker}"] for blocker in blocker_names)
        for signal in signal_names
    }
    total_signals = sum(counts[f"{signal}_true"] for signal in signal_names)
    eligible_calls = counts["entry_eligible_call"]
    actual = counts["actual_enter"]

    long_touch = counts["long_reversal_touch_true"]
    long_reclaim = counts["long_reversal_reclaim_true"]
    long_joint = counts["long_reversal_true"]
    short_touch = counts["short_reversal_touch_true"]
    short_reclaim = counts["short_reversal_reclaim_true"]
    short_joint = counts["short_reversal_true"]

    if eligible_calls != actual:
        state = "ROUTING_CONTRACT_MISMATCH"
        next_action = "TRACE_ENTRY_ROUTER_PAYLOAD"
    elif total_signals > 0 and eligible_calls == 0:
        state = "PRE_ENTRY_GATES_BLOCK_ALL_SIGNALS"
        next_action = "DECOMPOSE_VOLATILITY_VS_DISTANCE_DEFINITION"
    elif long_joint == 0 and short_joint == 0 and min(long_touch, long_reclaim, short_touch, short_reclaim) > 0:
        state = "REVERSAL_COMPONENTS_NEVER_INTERSECT"
        next_action = "WAIT_W1_OR_VERIFY_FORMULA_GEOMETRY"
    elif total_signals < 5:
        state = "LOW_FREQUENCY_RBREAKER_SIGNAL_HOLD"
        next_action = "WAIT_W1_NEW_NONOVERLAP"
    else:
        state = "RBREAKER_CAUSAL_COMPONENTS_DECOMPOSED"
        next_action = "SOURCE_CAUSAL_REVIEW"

    return {
        "state": state,
        "next_action": next_action,
        "call_count": calls,
        "counts": dict(sorted(counts.items())),
        "total_signal_count": total_signals,
        "entry_eligible_count": eligible_calls,
        "actual_enter_count": actual,
        "eligible_equals_actual_enter": eligible_calls == actual,
        "eligibility_counting_scope": "UNIQUE_STRATEGY_CALL",
        "volatility_blocker_source": "STRATEGY_WHY_UNROUNDED_GATE_RESULT",
        "signal_accounting_identity_pass": all(identities.values()),
        "signal_accounting": identities,
        "reversal_component_summary": {
            "long_touch": long_touch,
            "long_reclaim": long_reclaim,
            "long_joint": long_joint,
            "short_touch": short_touch,
            "short_reclaim": short_reclaim,
            "short_joint": short_joint,
        },
        "per_window": {key: dict(sorted(value.items())) for key, value in sorted(per_window.items())},
        "per_symbol": {key: dict(sorted(value.items())) for key, value in sorted(per_symbol.items())},
        "samples": samples,
    }


def _run_module(module: Any, forwarded: list[str]) -> int:
    previous = list(sys.argv)
    sys.argv = [str(getattr(module, "__file__", "strategy11-diagnostic")), *forwarded]
    try:
        return int(module.main())
    finally:
        sys.argv = previous


def _load_ledger(out: Path, strategy_id: str, candidate_id: str) -> list[dict[str, Any]]:
    path = out / strategy_id / candidate_id / "replay-A.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("trades")
    if not isinstance(rows, list):
        raise RuntimeError(f"TRADE_LEDGER_SHAPE:{path}")
    return [dict(row) for row in rows]


def _finalize(out: Path, strategy_id: str, candidate_id: str) -> None:
    final_path = out / "final.json"
    final = json.loads(final_path.read_text(encoding="utf-8"))
    repair = final.get("repair") or {}
    patched_sha = str(repair.get("patched_source_sha") or "")
    canonical_sha = str(repair.get("canonical_source_sha") or final.get("strategy_source_sha") or "")
    if len(patched_sha) != 64 or len(canonical_sha) != 64:
        raise RuntimeError("REPAIR_SOURCE_SHA_MISSING")
    ledger = _load_ledger(out, strategy_id, candidate_id)
    lineage_shas = sorted({str(row.get("strategy_source_sha") or "") for row in ledger})
    if lineage_shas != [patched_sha]:
        raise RuntimeError(f"PATCHED_SOURCE_LINEAGE_MISMATCH:{lineage_shas}:{patched_sha}")

    relation = ((final.get("candidate") or {}).get("relation") or {})
    checks = relation.get("checks") or {}
    if strategy_id in {"session_bias", "sr_levels"} and checks.get("positive_windows_two_thirds_exact") is not True:
        raise RuntimeError("EXACT_TWO_THIRDS_WINDOW_GATE_NOT_APPLIED")

    if strategy_id == "rbreaker_like":
        trace = final.get("after_trace") or {}
        if trace.get("eligible_equals_actual_enter") is not True:
            raise RuntimeError("RBREAKER_CALL_LEVEL_ELIGIBILITY_MISMATCH")
        if trace.get("signal_accounting_identity_pass") is not True:
            raise RuntimeError("RBREAKER_SIGNAL_ACCOUNTING_MISMATCH")
        samples = trace.get("samples") or []
        if samples and not any(sample.get("distance_metric") == "dist_beyond_signal_atr" for sample in samples):
            raise RuntimeError("RBREAKER_CORRECTED_DISTANCE_NOT_TRACED")

    old_diagnostic_sha = final.get("diagnostic_sha")
    final["integrity_state"] = "PASS_DIAGNOSTIC_INTEGRITY_CLOSURE"
    final["integrity_version"] = VERSION
    final["canonical_strategy_source_sha"] = canonical_sha
    final["candidate_strategy_source_sha"] = patched_sha
    final["candidate_trade_lineage_source_shas"] = lineage_shas
    final["candidate_trade_lineage_count"] = len(ledger)
    final["supersedes_diagnostic_sha"] = old_diagnostic_sha
    final.update(SAFETY)
    final["diagnostic_sha"] = replay.stable_sha(final)
    replay.atomic_json(final_path, final)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("session_bias", "sr_levels", "rbreaker_like"), required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    replay.evaluate = _source_bound_evaluate
    forwarded = [
        "--root", str(args.root),
        "--fresh-root", str(args.fresh_root),
        "--evidence-root", str(args.evidence_root),
        "--policy", str(args.policy),
        "--source-run-id", str(args.source_run_id),
        "--source-head-sha", str(args.source_head_sha),
        "--out", str(args.out),
    ]

    if args.mode == "session_bias":
        _install_exact_window_floor(session_bias)
        rc = _run_module(session_bias, forwarded)
        _finalize(args.out.resolve(), "session_bias", "PRIOR_SESSION_RANGE")
    elif args.mode == "sr_levels":
        _install_exact_window_floor(sr_levels)
        rc = _run_module(sr_levels, forwarded)
        _finalize(args.out.resolve(), "sr_levels", "PRIOR_SR_RANGE")
    else:
        _install_exact_window_floor(rbreaker_v1)
        rbreaker_blocker.trace = _corrected_rbreaker_trace
        rbreaker_v1.load_patched_strategy = rbreaker_v2.load_patched_strategy
        rbreaker_v1.VERSION = VERSION
        rc = _run_module(rbreaker_v1, forwarded)
        _finalize(args.out.resolve(), "rbreaker_like", "ACTIVE_SIGNAL_BOUNDARY_DISTANCE")

    print("PASS_DIAGNOSTIC_INTEGRITY_CLOSURE", args.mode)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
