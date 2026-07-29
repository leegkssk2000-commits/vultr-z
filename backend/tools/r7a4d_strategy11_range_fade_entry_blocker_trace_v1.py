from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

p = replay.p
exact = replay.exact
base = replay.base
repair = replay.repair
prior = replay.prior

STRATEGY_ID = "range_fade"
VERSION = "R7A4D_STRATEGY11_RANGE_FADE_ENTRY_BLOCKER_TRACE_V1"
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


def verify_source_semantics(root: Path, expected_sha: str) -> dict[str, Any]:
    path = (root / "backend/strategies/range_fade.py").resolve()
    source = path.read_text(encoding="utf-8")
    actual_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{actual_sha}:{expected_sha}")
    required = {
        "sideways_gate": "    if not sideways_ok:",
        "late_chase_gate": "    if late_chase_block and (long_setup or short_setup):",
        "long_entry": "    if long_setup and not in_long and not in_short:",
        "short_entry": "    if short_setup and not in_long and not in_short:",
        "long_reduce": "        long_reduce = range_break_down",
        "short_reduce": "        short_reduce = range_break_up",
    }
    counts = {name: source.count(text) for name, text in required.items()}
    if any(value != 1 for value in counts.values()):
        raise RuntimeError("SOURCE_CONTRACT_SHAPE_MISMATCH:" + json.dumps(counts, sort_keys=True))
    order = {name: source.index(text) for name, text in required.items()}
    if not (order["sideways_gate"] < order["late_chase_gate"] < order["long_entry"] < order["short_entry"]):
        raise RuntimeError("ENTRY_GATE_ORDER_MISMATCH")
    if not (order["long_reduce"] < order["long_entry"] and order["short_reduce"] < order["short_entry"]):
        raise RuntimeError("FAILURE_PREDICATE_PLACEMENT_MISMATCH")
    return {
        "source_path": "backend/strategies/range_fade.py",
        "source_sha": actual_sha,
        "required_clause_counts": counts,
        "entry_order_verified": True,
        "range_break_predicates_are_position_failure_only": True,
        "source_modified": False,
    }


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
                sideways = bool(indicators.get("sideways_ok"))
                late = bool(indicators.get("late_chase_block"))
                for side in ("long", "short"):
                    setup = bool(indicators.get(f"{side}_setup"))
                    if not setup:
                        continue
                    add(f"{side}_setup", window_id, symbol)
                    if not sideways:
                        blocker = "sideways_gate_block"
                    elif late:
                        blocker = "late_chase_block"
                    else:
                        blocker = "entry_eligible"
                    add(f"{side}_{blocker}", window_id, symbol)
                    if len(samples) < 20:
                        samples.append({
                            "window_id": window_id,
                            "symbol": symbol,
                            "side": side,
                            "first_blocker": blocker,
                            "sideways_ok": sideways,
                            "late_chase_block": late,
                            "box_pct": indicators.get("box_pct"),
                            "atr_pct": indicators.get("atr_pct"),
                            "dist_from_mid_atr": indicators.get("dist_from_mid_atr"),
                            "dist_from_fast_atr": indicators.get("dist_from_fast_atr"),
                            "rsi": indicators.get("rsi"),
                            "reclaim_up": indicators.get("reclaim_up"),
                            "reclaim_down": indicators.get("reclaim_down"),
                        })
                if bool(indicators.get("range_break_up")):
                    add("range_break_up_true", window_id, symbol)
                if bool(indicators.get("range_break_down")):
                    add("range_break_down_true", window_id, symbol)
                if str(result.get("action") or "hold").lower() == "enter":
                    add("actual_enter", window_id, symbol)

    long_setup = counts["long_setup"]
    short_setup = counts["short_setup"]
    setup_total = long_setup + short_setup
    categories = ("sideways_gate_block", "late_chase_block", "entry_eligible")
    long_accounted = sum(counts[f"long_{name}"] for name in categories)
    short_accounted = sum(counts[f"short_{name}"] for name in categories)
    eligible = counts["long_entry_eligible"] + counts["short_entry_eligible"]
    actual = counts["actual_enter"]
    if eligible != actual:
        state = "ROUTING_CONTRACT_MISMATCH"
        next_action = "TRACE_ENTRY_ROUTER_PAYLOAD"
    elif setup_total == 0:
        state = "NO_RANGE_SETUP_EVIDENCE"
        next_action = "WAIT_NEW_EVIDENCE"
    elif setup_total < 5:
        state = "LOW_FREQUENCY_RANGE_SETUP_HOLD"
        next_action = "WAIT_W1_NEW_NONOVERLAP"
    elif counts["long_late_chase_block"] + counts["short_late_chase_block"] == setup_total:
        state = "LATE_CHASE_BLOCKS_ALL_RANGE_SETUPS"
        next_action = "VERIFY_DISTANCE_DEFINITION_BEFORE_ONE_REPAIR"
    else:
        state = "RANGE_ENTRY_BLOCKERS_DECOMPOSED"
        next_action = "SOURCE_CAUSAL_REVIEW"

    return {
        "state": state,
        "next_action": next_action,
        "call_count": calls,
        "counts": dict(sorted(counts.items())),
        "long_setup_count": long_setup,
        "short_setup_count": short_setup,
        "total_setup_count": setup_total,
        "long_accounting_identity_pass": long_setup == long_accounted,
        "short_accounting_identity_pass": short_setup == short_accounted,
        "entry_eligible_count": eligible,
        "actual_enter_count": actual,
        "eligible_equals_actual_enter": eligible == actual,
        "failure_predicates_are_not_entry_gates": True,
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
    frames, _, _, manifest = p.load_fresh_data(args.fresh_root.resolve())
    registry = base._load_registry(root)
    registry_row = registry[STRATEGY_ID]
    expected_sha = str(registry_row["canonical_engine"]["source_sha256"])
    source_contract = verify_source_semantics(root, expected_sha)
    strategy = base._load_canonical_strategy(root, STRATEGY_ID, registry_row)
    result_trace = trace(strategy, symbols, frames, int(manifest["warmup_bars"]), 220)

    result = {
        "schema_version": "strategy11.range_fade_entry_blocker_trace.v1",
        "version": VERSION,
        "state": "PASS_RANGE_FADE_ENTRY_BLOCKER_TRACE",
        "strategy_id": STRATEGY_ID,
        "source_run_id": str(args.source_run_id),
        "source_head_sha": str(args.source_head_sha),
        "baseline_summary_sha": stable_sha(baseline),
        "symbols": list(symbols),
        "source_contract": source_contract,
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
    print(result["state"], result_trace["state"], result_trace["total_setup_count"], result_trace["actual_enter_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
