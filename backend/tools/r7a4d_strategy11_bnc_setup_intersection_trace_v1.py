from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_bnc_prior_box_repair_v1 as bnc_repair
from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair
prior = replay.prior

STRATEGY_ID = "break_and_continue"
VERSION = "R7A4D_STRATEGY11_BNC_SETUP_INTERSECTION_TRACE_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def trace(
    strategy: Any,
    symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], Any],
    warmup_bars: int,
    history_bars: int,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    per_window: defaultdict[str, Counter[str]] = defaultdict(Counter)
    per_symbol: defaultdict[str, Counter[str]] = defaultdict(Counter)
    samples: list[dict[str, Any]] = []
    calls = 0

    def add(name: str, window_id: str, symbol: str) -> None:
        counts[name] += 1
        per_window[window_id][name] += 1
        per_symbol[symbol][name] += 1

    def classify_side(side: str, indicators: Mapping[str, Any], window_id: str, symbol: str) -> None:
        prefix = "long" if side == "long" else "short"
        historical_break = bool(indicators.get("up_break" if side == "long" else "down_break"))
        if not historical_break:
            return
        add(prefix + "_historical_break", window_id, symbol)
        tight = bool(indicators.get("tight_box"))
        breakout_now = bool(indicators.get("long_breakout_now" if side == "long" else "short_breakout_now"))
        reclaim = bool(indicators.get("long_reclaim" if side == "long" else "short_reclaim"))
        trend = bool(indicators.get("trend_long" if side == "long" else "trend_short"))
        late = bool(indicators.get("late_chase_block"))
        setup = bool(indicators.get("long_setup" if side == "long" else "short_setup"))

        if not tight:
            first = "tight_box_block"
        elif not breakout_now:
            first = "breakout_now_block"
        elif not reclaim:
            first = "reclaim_block"
        elif not trend:
            first = "trend_block"
        elif not setup:
            first = "setup_contract_mismatch"
        elif late:
            first = "late_chase_block"
        else:
            first = "entry_eligible"
        add(prefix + "_" + first, window_id, symbol)

        if len(samples) < 40:
            samples.append({
                "window_id": window_id,
                "symbol": symbol,
                "side": side,
                "first_blocker": first,
                "tight_box": tight,
                "breakout_now": breakout_now,
                "reclaim": reclaim,
                "trend": trend,
                "setup": setup,
                "late_chase_block": late,
                "breakout_strength_atr": indicators.get("breakout_strength_atr"),
                "box_height_atr": indicators.get("box_height_atr"),
                "dist_from_fast_atr": indicators.get("dist_from_fast_atr"),
            })

    for window_id in repair.FRESH_ROLES:
        for symbol in symbols:
            frame = frames[(window_id, symbol)]
            for index in range(warmup_bars, len(frame) - 1):
                history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
                result = exact._call_strategy(
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
                classify_side("long", indicators, window_id, symbol)
                classify_side("short", indicators, window_id, symbol)
                if str(result.get("action") or "hold").lower() == "enter":
                    add("actual_enter", window_id, symbol)

    long_total = counts["long_historical_break"]
    short_total = counts["short_historical_break"]
    categories = (
        "tight_box_block", "breakout_now_block", "reclaim_block", "trend_block",
        "setup_contract_mismatch", "late_chase_block", "entry_eligible",
    )
    long_accounted = sum(counts["long_" + name] for name in categories)
    short_accounted = sum(counts["short_" + name] for name in categories)
    total_breaks = long_total + short_total
    aggregate_blockers = {
        name: counts["long_" + name] + counts["short_" + name]
        for name in categories
    }
    dominant = max(aggregate_blockers, key=aggregate_blockers.get) if total_breaks else "NO_BREAK_EVENT"
    dominant_count = aggregate_blockers.get(dominant, 0)
    if total_breaks == 0:
        state = "NO_HISTORICAL_BREAK_EVIDENCE"
        next_action = "WAIT_NEW_EVIDENCE"
    elif dominant == "tight_box_block" and dominant_count / total_breaks >= 0.75:
        state = "TIGHT_BOX_DOMINATES_BREAK_EVENTS"
        next_action = "VERIFY_BREAKOUT_WINDOW_AND_BOX_WINDOW_SEMANTIC_COMPATIBILITY"
    elif aggregate_blockers["entry_eligible"] > 0:
        state = "ENTRY_ELIGIBLE_EVENTS_PRESENT"
        next_action = "TRACE_ROUTER_OR_REPLAY_CLOSURE"
    else:
        state = "MULTI_BLOCKER_INTERSECTION_DECOMPOSED"
        next_action = "WAIT_W1_OR_SINGLE_SUPPORTED_AXIS"

    return {
        "state": state,
        "next_action": next_action,
        "call_count": calls,
        "counts": dict(sorted(counts.items())),
        "long_historical_break_count": long_total,
        "short_historical_break_count": short_total,
        "total_historical_break_count": total_breaks,
        "long_accounting_identity_pass": long_total == long_accounted,
        "short_accounting_identity_pass": short_total == short_accounted,
        "aggregate_first_blockers": aggregate_blockers,
        "dominant_first_blocker": dominant,
        "dominant_first_blocker_count": dominant_count,
        "dominant_first_blocker_share": dominant_count / max(1, total_breaks),
        "actual_enter_count": counts["actual_enter"],
        "per_window": {key: dict(sorted(value.items())) for key, value in sorted(per_window.items())},
        "per_symbol": {key: dict(sorted(value.items())) for key, value in sorted(per_symbol.items())},
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    baseline_path = prior.find_summary(args.evidence_root.resolve(), STRATEGY_ID)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    symbols = tuple(str(value) for value in baseline.get("symbols", []))
    if not symbols:
        raise RuntimeError("BASELINE_SYMBOLS_EMPTY")
    frames, _, _, manifest = p.load_fresh_data(args.fresh_root.resolve())
    registry = base._load_registry(root)
    registry_row = registry[STRATEGY_ID]
    source_sha = str(registry_row["canonical_engine"]["source_sha256"])
    strategy, repair_manifest = bnc_repair.load_patched_strategy(root, source_sha)
    result_trace = trace(strategy, symbols, frames, int(manifest["warmup_bars"]), 220)

    result = {
        "schema_version": "strategy11.bnc_setup_intersection_trace.v1",
        "version": VERSION,
        "state": "PASS_BNC_SETUP_INTERSECTION_TRACE",
        "strategy_id": STRATEGY_ID,
        "source_run_id": str(args.source_run_id),
        "source_head_sha": str(args.source_head_sha),
        "baseline_summary_sha": stable_sha(baseline),
        "symbols": list(symbols),
        "repair": repair_manifest,
        "trace": result_trace,
        "canonical_source_modified": False,
        "registry_modified": False,
        "thresholds_modified": False,
        "ai_review_state": "WAIT_GROQ_QUOTA",
        "w1_confirmation_required": True,
        "new_sealed_required": True,
        **SAFETY,
    }
    result["diagnostic_sha"] = stable_sha(result)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "final.json", result)
    print(result["state"], result_trace["state"], result_trace["total_historical_break_count"], result_trace["dominant_first_blocker"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
