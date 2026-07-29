from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair

VERSION = "R7A4D_STRATEGY11_CANONICAL_TRIGGER_TRACE_V1"
TARGETS = (
    "bb_revert",
    "break_and_continue",
    "fvg_revert",
    "keltner_trend",
    "mfi_rsi_div",
    "range_fade",
    "rbreaker_like",
    "session_bias",
    "sr_levels",
    "supertrend_pullback",
    "trend_rider",
)
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}
ENTRY_HINTS = (
    "long", "buy", "bull", "up", "reclaim", "setup", "trigger", "signal",
    "break", "cross", "trend", "volume", "vol_ok", "momentum", "support",
    "sweep", "fvg", "pullback", "bounce", "oversold", "rsi", "mfi", "adx",
)
EXCLUDE_HINTS = (
    "short", "sell", "bear", "down", "position", "in_long", "in_short",
    "failed", "exit", "reduce", "add", "late", "block", "nan", "valid",
)


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def indicator_mapping(result: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("indicators", "indicator", "features", "diagnostics", "debug"):
        value = result.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def candidate_predicate_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ENTRY_HINTS) and not any(token in lowered for token in EXCLUDE_HINTS)


def trace_strategy(
    *, strategy_id: str, strategy: Any, symbols: tuple[str, ...], frames: Mapping[tuple[str, str], Any],
    warmup_bars: int, history_bars: int,
) -> dict[str, Any]:
    action_counts: Counter[str] = Counter()
    side_counts: Counter[str] = Counter()
    why_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    bool_true: Counter[str] = Counter()
    bool_false: Counter[str] = Counter()
    numeric_values: defaultdict[str, list[float]] = defaultdict(list)
    result_shapes: Counter[str] = Counter()
    long_events: list[dict[str, Any]] = []
    calls = 0

    for window_id in repair.FRESH_ROLES:
        for symbol in symbols:
            frame = frames[(window_id, symbol)]
            for index in range(warmup_bars, len(frame) - 1):
                history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
                state = {
                    "position_side": "",
                    "position_qty": 0.0,
                    "avg_entry": 0.0,
                    "add_count": 0,
                    "last_add_price": 0.0,
                }
                result = exact._call_strategy(strategy, history, state)
                calls += 1
                action = str(result.get("action") or "hold").lower()
                side = str(result.get("side") or "").lower()
                why = str(result.get("why") or result.get("reason") or "UNSPECIFIED")
                action_counts[action] += 1
                side_counts[side or "none"] += 1
                why_counts[why] += 1
                tags = result.get("tags")
                if isinstance(tags, list):
                    for tag in tags:
                        tag_counts[str(tag)] += 1
                indicators = indicator_mapping(result)
                result_shapes[stable_sha(sorted(indicators))] += 1
                for key, value in indicators.items():
                    if isinstance(value, bool):
                        (bool_true if value else bool_false)[str(key)] += 1
                    elif finite(value):
                        numeric_values[str(key)].append(float(value))
                if action == "enter" and side == "long" and len(long_events) < 30:
                    long_events.append({
                        "window_id": window_id,
                        "symbol": symbol,
                        "event_ts": str(frame["timestamp"].iloc[index]),
                        "why": why,
                        "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
                        "indicator_sha": stable_sha(indicators),
                    })

    boolean_rows = []
    for key in sorted(set(bool_true) | set(bool_false)):
        true_count = int(bool_true[key])
        false_count = int(bool_false[key])
        observed = true_count + false_count
        boolean_rows.append({
            "predicate": key,
            "true_count": true_count,
            "false_count": false_count,
            "observed_count": observed,
            "true_rate_pct": true_count / max(1, observed) * 100.0,
            "entry_candidate": candidate_predicate_key(key),
        })
    boolean_rows.sort(key=lambda row: (
        not row["entry_candidate"],
        row["true_rate_pct"],
        -row["observed_count"],
        row["predicate"],
    ))
    numeric_rows = []
    for key, values in sorted(numeric_values.items()):
        numeric_rows.append({
            "indicator": key,
            "sample_count": len(values),
            "min": min(values),
            "p10": quantile(values, 0.10),
            "median": quantile(values, 0.50),
            "p90": quantile(values, 0.90),
            "max": max(values),
        })

    entry_predicates = [row for row in boolean_rows if row["entry_candidate"]]
    always_false = [row for row in entry_predicates if row["true_count"] == 0]
    rare = [row for row in entry_predicates if 0 < row["true_rate_pct"] < 1.0]
    dominant = always_false[0]["predicate"] if len(always_false) == 1 else None
    if action_counts.get("enter", 0) > 0:
        state = "CANONICAL_ENTER_ACTIVE"
        next_action = "NO_TRIGGER_REPAIR"
    elif len(always_false) == 1:
        state = "SINGLE_ALWAYS_FALSE_ENTRY_PREDICATE"
        next_action = "ONE_PREDICATE_ABLATION_REPLAY"
    elif len(always_false) > 1:
        state = "MULTIPLE_ALWAYS_FALSE_ENTRY_PREDICATES"
        next_action = "SOURCE_CAUSAL_DECOMPOSITION_REQUIRED"
    elif rare:
        state = "RARE_ENTRY_PREDICATE_INTERSECTION"
        next_action = "PAIRWISE_INTERSECTION_TRACE"
    else:
        state = "NO_EXPOSED_BOOLEAN_TRIGGER"
        next_action = "SOURCE_AST_AND_NUMERIC_THRESHOLD_TRACE"

    return {
        "strategy_id": strategy_id,
        "state": state,
        "next_action": next_action,
        "call_count": calls,
        "action_counts": dict(sorted(action_counts.items())),
        "side_counts": dict(sorted(side_counts.items())),
        "why_counts": dict(why_counts.most_common()),
        "tag_counts": dict(tag_counts.most_common()),
        "boolean_predicates": boolean_rows,
        "always_false_entry_predicates": [row["predicate"] for row in always_false],
        "rare_entry_predicates": [row["predicate"] for row in rare],
        "single_dominant_predicate": dominant,
        "numeric_indicators": numeric_rows,
        "result_indicator_shape_count": len(result_shapes),
        "long_event_sample": long_events,
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

    frames, _, _, manifest = p.load_fresh_data(args.fresh_root.resolve())
    registry = base._load_registry(args.root.resolve())
    warmup_bars = int(manifest["warmup_bars"])
    rows = []
    for strategy_id in TARGETS:
        baseline_summary = json.loads(
            replay.prior.find_summary(args.evidence_root.resolve(), strategy_id).read_text(encoding="utf-8")
        )
        candidate = baseline_summary["candidate"]
        gate = exact._gate_from(candidate)
        surgery = p.surgery_from(baseline_summary.get("surgery"))
        if gate.required or gate.forbidden or surgery is not None:
            raise RuntimeError(f"TARGET_NOT_BASE_NO_SURGERY:{strategy_id}")
        symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))
        strategy = base._load_canonical_strategy(args.root.resolve(), strategy_id, registry[strategy_id])
        row = trace_strategy(
            strategy_id=strategy_id,
            strategy=strategy,
            symbols=symbols,
            frames=frames,
            warmup_bars=warmup_bars,
            history_bars=220,
        )
        row["source_sha"] = str(registry[strategy_id]["canonical_engine"]["source_sha256"])
        row["symbols"] = list(symbols)
        rows.append(row)

    state_counts = Counter(row["state"] for row in rows)
    repairable = [
        {
            "strategy_id": row["strategy_id"],
            "predicate": row["single_dominant_predicate"],
            "change_budget": 1,
            "next_action": row["next_action"],
        }
        for row in rows if row["single_dominant_predicate"]
    ]
    result = {
        "schema_version": "strategy11.canonical_trigger_trace.v1",
        "version": VERSION,
        "state": "PASS_CANONICAL_TRIGGER_TRACE",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "strategy_count": len(rows),
        "state_counts": dict(sorted(state_counts.items())),
        "single_predicate_repair_queue": repairable,
        "rows": rows,
        "repair_policy": {
            "source_unchanged": True,
            "single_predicate_ablation_only": True,
            "diagnostic_replay_before_code_change": True,
            "no_threshold_sweep": True,
            "ai_review_required": True,
            "w1_and_new_sealed_required": True,
        },
        **SAFETY,
    }
    result["trace_sha"] = stable_sha(result)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "canonical_trigger_trace.json", result)
    print(result["state"], result["state_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
