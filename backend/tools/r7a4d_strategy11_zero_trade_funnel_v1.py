from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from backend.strategy25.strategy11_feature_library_v1 import GateSpec
from backend.tools import r7a4d_strategy11_multimodal_l090_replay_v1 as replay

prior = replay.prior
repair = replay.repair
p = replay.p
exact = replay.exact
base = replay.base

VERSION = "R7A4D_STRATEGY11_ZERO_TRADE_FUNNEL_V1"
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


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def metric(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def find_strategy_summary(root: Path, strategy_id: str) -> Path:
    matches = sorted(root.glob(f"batch-*/{strategy_id}/summary.json"))
    if len(matches) != 1:
        raise RuntimeError(f"REPLAY_SUMMARY_MATCH:{strategy_id}:{len(matches)}")
    return matches[0]


def payload_valid(result: Mapping[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    entry = metric(result.get("entry"), math.nan)
    stop = metric(result.get("sl"), math.nan)
    target = metric(result.get("tp"), math.nan)
    size = metric(result.get("size"), 0.0)
    if not math.isfinite(entry):
        blockers.append("ENTRY_NONFINITE")
    if not math.isfinite(stop):
        blockers.append("SL_NONFINITE")
    if not math.isfinite(target):
        blockers.append("TP_NONFINITE")
    if size <= 0.0:
        blockers.append("SIZE_NONPOSITIVE")
    if math.isfinite(entry) and math.isfinite(stop) and entry - stop <= 0.0:
        blockers.append("LONG_RISK_NONPOSITIVE")
    if math.isfinite(target) and math.isfinite(entry) and target - entry <= 0.0:
        blockers.append("LONG_REWARD_NONPOSITIVE")
    return not blockers, blockers


def scan_raw_signals(
    *, strategy: Any, gate: GateSpec, surgery: Any, symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], Any], features: Mapping[tuple[str, str], Any],
    warmup_bars: int, history_bars: int,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    condition_false: Counter[str] = Counter()
    condition_true: Counter[str] = Counter()
    surgery_block_feature_rows: list[str] = []
    raw_events: list[dict[str, Any]] = []

    for window_id in repair.FRESH_ROLES:
        for symbol in symbols:
            frame = frames[(window_id, symbol)]
            feature_frame = features[(window_id, symbol)]
            for index in range(warmup_bars, len(frame) - 1):
                history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
                state = {"position_side": "", "position_qty": 0.0, "avg_entry": 0.0, "add_count": 0, "last_add_price": 0.0}
                result = exact._call_strategy(strategy, history, state)
                counts["call_count"] += 1
                action = str(result.get("action") or "hold").lower()
                side = str(result.get("side") or "").lower()
                counts[f"action:{action}"] += 1
                counts[f"side:{side or 'none'}"] += 1
                if action in {"add", "reduce"}:
                    counts["add_reduce_signal_count"] += 1
                if side == "short" and action in {"enter", "add", "reduce"}:
                    counts["short_signal_count"] += 1
                if action != "enter" or side != "long":
                    continue

                counts["raw_enter_long_count"] += 1
                valid, payload_blockers = payload_valid(result)
                for blocker in payload_blockers:
                    counts[f"payload_block:{blocker}"] += 1
                if valid:
                    counts["valid_enter_payload_count"] += 1

                feature_values = exact.feature_snapshot(feature_frame.iloc[index].to_dict())
                for name in gate.required:
                    if bool(feature_values.get(name)):
                        condition_true[name] += 1
                    else:
                        condition_false[name] += 1
                for name in gate.forbidden:
                    key = f"NOT_{name}"
                    if not bool(feature_values.get(name)):
                        condition_true[key] += 1
                    else:
                        condition_false[key] += 1
                gate_pass = exact.gate_allows(gate, feature_values)
                surgery_pass = p.surgery_allows(surgery, feature_values)
                counts["base_gate_pass_count" if gate_pass else "base_gate_block_count"] += 1
                if gate_pass:
                    counts["surgery_pass_count" if surgery_pass else "surgery_block_count"] += 1
                if gate_pass and not surgery_pass:
                    surgery_block_feature_rows.append(stable_sha(feature_values))
                if len(raw_events) < 50:
                    raw_events.append({
                        "window_id": window_id,
                        "symbol": symbol,
                        "signal_ts": str(frame["timestamp"].iloc[index]),
                        "payload_valid": valid,
                        "payload_blockers": payload_blockers,
                        "gate_pass": gate_pass,
                        "surgery_pass": surgery_pass,
                        "feature_sha": stable_sha(feature_values),
                    })

    raw_count = counts["raw_enter_long_count"]
    condition_rows = []
    for name in sorted(set(condition_true) | set(condition_false)):
        false_count = condition_false[name]
        true_count = condition_true[name]
        condition_rows.append({
            "condition": name,
            "true_count": true_count,
            "false_count": false_count,
            "false_rate_pct": false_count / max(1, raw_count) * 100.0,
        })
    condition_rows.sort(key=lambda row: (-row["false_count"], row["condition"]))
    return {
        "counts": dict(sorted(counts.items())),
        "condition_funnel": condition_rows,
        "dominant_blocking_condition": condition_rows[0]["condition"] if condition_rows and condition_rows[0]["false_count"] else None,
        "surgery_block_feature_shas": sorted(set(surgery_block_feature_rows)),
        "raw_event_sample": raw_events,
    }


def classify(funnel: Mapping[str, Any], current_trade_count: int) -> tuple[str, str]:
    counts = funnel["counts"]
    raw = int(counts.get("raw_enter_long_count", 0))
    valid = int(counts.get("valid_enter_payload_count", 0))
    gate_pass = int(counts.get("base_gate_pass_count", 0))
    surgery_pass = int(counts.get("surgery_pass_count", 0))
    if raw == 0:
        return "CANONICAL_LONG_SIGNAL_ABSENT", "DECOMPOSE_CANONICAL_TRIGGER_PREDICATES"
    if valid == 0:
        return "INVALID_LONG_ENTRY_PAYLOAD", "REPAIR_ENTRY_SL_TP_SIZE_ADAPTER"
    if gate_pass == 0:
        return "BASE_GATE_OVERFILTER", "REMOVE_ONE_DOMINANT_BASE_GATE_CONDITION_DIAGNOSTIC_ONLY"
    if surgery_pass == 0:
        return "SURGERY_OVERFILTER", "DISABLE_ONE_SURGERY_CONDITION_DIAGNOSTIC_ONLY"
    if current_trade_count == 0:
        return "PENDING_OR_EXECUTION_BRIDGE_GAP", "TRACE_PENDING_TO_POSITION_CONVERSION"
    return "CONTROL_ACTIVE", "NO_ZERO_TRADE_REPAIR"


def candidate_gate_funnel(gate_value: Mapping[str, Any], raw_funnel: Mapping[str, Any]) -> dict[str, Any]:
    gate = GateSpec(**dict(gate_value))
    sample = raw_funnel.get("raw_event_sample", [])
    return {
        "gate": asdict(gate),
        "raw_event_sample_count": len(sample),
        "note": "Full candidate condition counts require direct feature rows; raw event SHAs preserve identity without duplicating market data.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    frames, features, funding, manifest = p.load_fresh_data(args.fresh_root.resolve())
    registry = base._load_registry(args.root.resolve())
    warmup_bars = int(manifest["warmup_bars"])
    rows: list[dict[str, Any]] = []
    repair_queue: list[dict[str, Any]] = []

    for strategy_id in prior.STRATEGIES:
        baseline_summary = strict_json(prior.find_summary(args.evidence_root.resolve(), strategy_id))
        candidate = baseline_summary["candidate"]
        gate = exact._gate_from(candidate)
        exit_spec = exact._exit_from(candidate)
        surgery = p.surgery_from(baseline_summary.get("surgery"))
        symbols = tuple(str(value) for value in baseline_summary.get("symbols", []))
        registry_row = registry[strategy_id]
        strategy = base._load_canonical_strategy(args.root.resolve(), strategy_id, registry_row)
        replay_summary = strict_json(find_strategy_summary(args.replay_root.resolve(), strategy_id))
        control = next(row for row in replay_summary["variants"] if row["variant_id"] == "NO_CHANGE_CONTROL")
        current_trade_count = int(control.get("trade_count") or 0)

        funnel = scan_raw_signals(
            strategy=strategy,
            gate=gate,
            surgery=surgery,
            symbols=symbols,
            frames=frames,
            features=features,
            warmup_bars=warmup_bars,
            history_bars=220,
        )
        cause, next_action = classify(funnel, current_trade_count)
        nonzero_candidate_ids = [
            row["variant_id"] for row in replay_summary["variants"][1:]
            if int(row.get("trade_count") or 0) > 0
        ]
        if cause == "CANONICAL_LONG_SIGNAL_ABSENT" and nonzero_candidate_ids:
            cause = "CANONICAL_TRIGGER_DEAD_FEATURE_PROXY_ACTIVE"
            next_action = "REPAIR_TRIGGER_ADAPTER_USING_EXISTING_NONZERO_SINGLE_FEATURE_PROXY"

        row = {
            "strategy_id": strategy_id,
            "family": str(candidate.get("family") or "UNKNOWN"),
            "source_sha": str(registry_row["canonical_engine"]["source_sha256"]),
            "symbols": list(symbols),
            "base_gate": asdict(gate),
            "surgery": asdict(surgery) if surgery is not None else None,
            "exit": asdict(exit_spec),
            "current_control_trade_count": current_trade_count,
            "current_nonzero_candidate_ids": nonzero_candidate_ids,
            "cause": cause,
            "next_action": next_action,
            "funnel": funnel,
            "replay_summary_sha": stable_sha(replay_summary),
        }
        rows.append(row)
        if current_trade_count == 0:
            repair_queue.append({
                "strategy_id": strategy_id,
                "cause": cause,
                "dominant_blocking_condition": funnel.get("dominant_blocking_condition"),
                "nonzero_proxy_candidate_ids": nonzero_candidate_ids,
                "next_action": next_action,
                "change_budget": 1,
                "research_only": True,
            })

    cause_counts = Counter(row["cause"] for row in rows if row["current_control_trade_count"] == 0)
    repair_queue.sort(key=lambda row: (
        0 if row["cause"] == "CANONICAL_TRIGGER_DEAD_FEATURE_PROXY_ACTIVE" else
        1 if row["cause"] == "BASE_GATE_OVERFILTER" else
        2 if row["cause"] == "SURGERY_OVERFILTER" else 3,
        row["strategy_id"],
    ))
    result = {
        "schema_version": "strategy11.zero_trade_funnel.v1",
        "version": VERSION,
        "state": "PASS_ZERO_TRADE_FUNNEL_DECOMPOSITION",
        "source_run_id": args.source_run_id,
        "source_head_sha": args.source_head_sha,
        "strategy_count": len(rows),
        "zero_control_strategy_count": sum(row["current_control_trade_count"] == 0 for row in rows),
        "cause_counts": dict(sorted(cause_counts.items())),
        "repair_queue": repair_queue,
        "rows": rows,
        "repair_policy": {
            "single_cause_per_child": True,
            "single_change_per_candidate": True,
            "no_blanket_threshold_relaxation": True,
            "ai_review_required_before_promotion": True,
            "w1_confirmation_required": True,
            "new_sealed_required": True,
        },
        **SAFETY,
    }
    result["funnel_sha"] = stable_sha(result)
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / "zero_trade_funnel.json", result)
    atomic_json(args.out / "repair_queue.json", {
        "state": "PASS_REPAIR_QUEUE_BUILT",
        "rows": repair_queue,
        "funnel_sha": result["funnel_sha"],
        **SAFETY,
    })
    print(result["state"], result["cause_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
