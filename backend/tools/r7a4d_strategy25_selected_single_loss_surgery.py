from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from backend.strategy25.indicator_contract_repair_adapter_v2 import REPAIR_SPECS
from backend.strategy25.indicator_contract_repair_loader_v2 import load_repaired_strategy


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
TRACE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repair_loss_anatomy.py"
OUTPUT_DIR = "artifacts/strategy25_selected_single_loss_surgery_v1"


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_module(BASE_RUNNER_PATH, "r7a4d_single_surgery_base_runner_v1")
trace = _load_module(TRACE_RUNNER_PATH, "r7a4d_single_surgery_trace_runner_v1")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _number(value: Any, default: float = 0.0) -> float:
    return float(value) if _finite(value) else default


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return base._stats(trades)


def _matches_trade(trade: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    kind = str(candidate["kind"])
    if kind == "WHY":
        return str(trade.get("entry_why") or "unknown") == str(candidate["value"])
    if kind == "SKILL":
        return str(trade.get("entry_skill") or "none") == str(candidate["value"])
    if kind == "TAG":
        return str(candidate["value"]) in {str(item) for item in (trade.get("entry_tags") or [])}
    if kind == "BOOL":
        indicators = trade.get("entry_indicators") if isinstance(trade.get("entry_indicators"), Mapping) else {}
        return indicators.get(str(candidate["key"])) is bool(candidate["value"])
    if kind == "WHY_BOOL":
        indicators = trade.get("entry_indicators") if isinstance(trade.get("entry_indicators"), Mapping) else {}
        return (
            str(trade.get("entry_why") or "unknown") == str(candidate["why"])
            and indicators.get(str(candidate["key"])) is bool(candidate["value"])
        )
    return False


def _matches_result(result: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    pseudo = {
        "entry_why": str(result.get("why") or "unknown"),
        "entry_skill": str(result.get("skill") or "none"),
        "entry_tags": [str(item) for item in (result.get("tags") or [])],
        "entry_indicators": dict(result.get("indicators")) if isinstance(result.get("indicators"), Mapping) else {},
    }
    return _matches_trade(pseudo, candidate)


def _candidate_label(candidate: Mapping[str, Any]) -> str:
    kind = str(candidate["kind"])
    if kind in {"WHY", "SKILL", "TAG"}:
        return f"{kind}:{candidate['value']}"
    if kind == "BOOL":
        return f"BOOL:{candidate['key']}={candidate['value']}"
    return f"WHY_BOOL:{candidate['why']}|{candidate['key']}={candidate['value']}"


def _generate_candidates(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    whys = sorted({str(row.get("entry_why") or "unknown") for row in trades})
    skills = sorted({str(row.get("entry_skill") or "none") for row in trades})
    tags = sorted({str(tag) for row in trades for tag in (row.get("entry_tags") or [])})
    for value in whys:
        candidates.append({"kind": "WHY", "value": value})
    for value in skills:
        if value != "none":
            candidates.append({"kind": "SKILL", "value": value})
    for value in tags:
        candidates.append({"kind": "TAG", "value": value})

    bool_counts: dict[tuple[str, bool], int] = {}
    for row in trades:
        indicators = row.get("entry_indicators") if isinstance(row.get("entry_indicators"), Mapping) else {}
        for key, value in indicators.items():
            if isinstance(value, bool):
                bool_counts[(str(key), value)] = bool_counts.get((str(key), value), 0) + 1
    bool_candidates = [
        {"kind": "BOOL", "key": key, "value": value}
        for (key, value), count in sorted(bool_counts.items())
        if count >= 5
    ]
    candidates.extend(bool_candidates)
    for why in whys:
        why_count = sum(str(row.get("entry_why") or "unknown") == why for row in trades)
        if why_count < 8:
            continue
        for candidate in bool_candidates:
            candidates.append(
                {
                    "kind": "WHY_BOOL",
                    "why": why,
                    "key": candidate["key"],
                    "value": candidate["value"],
                }
            )
    return candidates


def _row_level_candidates(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = _stats(trades)
    rows: list[dict[str, Any]] = []
    for candidate in _generate_candidates(trades):
        removed = [row for row in trades if _matches_trade(row, candidate)]
        if not removed or len(removed) == len(trades):
            continue
        remaining = [row for row in trades if not _matches_trade(row, candidate)]
        removed_stats = _stats(removed)
        remaining_stats = _stats(remaining)
        removed_count = int(removed_stats.get("trade_count") or 0)
        losses_removed = int(removed_stats.get("strict_loss_count") or 0)
        wins_removed = int(removed_stats.get("win_count") or 0)
        precision = losses_removed / max(removed_count, 1) * 100.0
        baseline_payoff = _number(baseline.get("payoff_ratio"), 0.0)
        remaining_payoff = _number(remaining_stats.get("payoff_ratio"), 0.0)
        eligible = bool(
            removed_count >= 5
            and losses_removed >= 4
            and precision >= 70.0
            and _number(remaining_stats.get("net_return_pct_sum"), -math.inf) > _number(baseline.get("net_return_pct_sum"), -math.inf)
            and _number(remaining_stats.get("net_profit_factor"), 0.0) >= _number(baseline.get("net_profit_factor"), 0.0)
            and (baseline_payoff <= 0.0 or remaining_payoff >= baseline_payoff * 0.95)
        )
        score = (
            _number(remaining_stats.get("net_return_pct_sum")) - _number(baseline.get("net_return_pct_sum"))
            + 10.0 * (_number(remaining_stats.get("net_profit_factor")) - _number(baseline.get("net_profit_factor")))
            + 2.0 * (_number(remaining_stats.get("win_rate_pct")) - _number(baseline.get("win_rate_pct")))
            - wins_removed * 0.5
        )
        rows.append(
            {
                "candidate": candidate,
                "label": _candidate_label(candidate),
                "eligible": eligible,
                "score": score,
                "removed": removed_stats,
                "remaining": remaining_stats,
                "loss_precision_pct": precision,
                "losses_removed": losses_removed,
                "wins_removed": wins_removed,
            }
        )
    return sorted(rows, key=lambda row: float(row["score"]), reverse=True)


def _wrapped_strategy(strategy: Callable[..., dict[str, Any]], candidate: Mapping[str, Any], counter: dict[str, int]) -> Callable[..., dict[str, Any]]:
    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = strategy(*args, **kwargs)
        if not isinstance(result, Mapping):
            raise RuntimeError("STRATEGY_RESULT_NOT_MAPPING")
        output = deepcopy(dict(result))
        action = str(output.get("action") or "hold").lower()
        side = str(output.get("side") or "").lower()
        if action == "enter" and side == "long" and _matches_result(output, candidate):
            counter["blocked_entry_signals"] += 1
            indicators = dict(output.get("indicators")) if isinstance(output.get("indicators"), Mapping) else {}
            output.update(
                {
                    "side": None,
                    "action": "hold",
                    "size": 0.0,
                    "why": "single_loss_cause_gate",
                    "skill": "none",
                    "confidence": 0.0,
                    "tags": [str(item) for item in (output.get("tags") or [])] + ["single_loss_cause_gate", "child_only"],
                    "indicators": {
                        **indicators,
                        "single_loss_cause_gate_blocked": True,
                        "single_loss_cause_label": _candidate_label(candidate),
                    },
                }
            )
        return output
    return wrapped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--census-summary", required=True)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    census_path = Path(args.census_summary).resolve()
    census = json.loads(census_path.read_text(encoding="utf-8"))
    selected_id = census.get("selected_strategy_id")
    blockers: list[str] = []
    if not selected_id:
        blockers.append("CENSUS_SELECTED_STRATEGY_MISSING")
    selected_id = str(selected_id or "")
    window = census.get("census_window") if isinstance(census.get("census_window"), Mapping) else {}
    start_ms = int(pd.Timestamp(str(window.get("start"))).timestamp() * 1000)
    end_ms = int(pd.Timestamp(str(window.get("end"))).timestamp() * 1000)
    expected_rows = int(window.get("bars") or 0)
    warmup_bars = int(window.get("warmup_bars") or 220)
    history_bars = 220

    registry = base._load_registry(root)
    effective = None
    if not blockers:
        effective = (
            load_repaired_strategy(root, selected_id)
            if selected_id in REPAIR_SPECS
            else base._load_canonical_strategy(root, selected_id, registry[selected_id])
        )

    frames: dict[str, pd.DataFrame] = {}
    fetch_results: list[dict[str, Any]] = []
    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, requests = base._fetch_exact(
                symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                expected_rows=expected_rows,
            )
            frames[symbol] = frame
            fetch_results.append({"symbol": symbol, "status": "PASS", "rows": len(frame), "endpoint": endpoint, "request_count": requests})
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    trace_rows: list[dict[str, Any]] = []
    baseline_runs: list[dict[str, Any]] = []
    if not blockers and effective is not None:
        for symbol in base.SYMBOLS:
            replay = trace._replay_trace(
                frames[symbol],
                effective,
                warmup_bars=warmup_bars,
                history_bars=history_bars,
                cost_bps_per_side=args.cost_bps_per_side,
            )
            baseline_runs.append(replay)
            for trade_row in replay.get("trades", []):
                if isinstance(trade_row, dict):
                    trace_rows.append({"symbol": symbol, **trade_row})

    baseline_stats = _stats(trace_rows) if trace_rows else {}
    candidates = _row_level_candidates(trace_rows) if trace_rows else []
    eligible = [row for row in candidates if row["eligible"]]
    selected_candidate = eligible[0] if eligible else None

    full_replay_rows: list[dict[str, Any]] = []
    full_replay_stats: dict[str, Any] = {}
    positive_symbols_before = 0
    positive_symbols_after = 0
    blocked_signals = 0
    accepted = False
    failure_reasons: list[str] = []

    if selected_candidate is None:
        failure_reasons.append("NO_ELIGIBLE_SINGLE_CAUSE")
    elif effective is not None:
        candidate_spec = selected_candidate["candidate"]
        for symbol in base.SYMBOLS:
            baseline = base._replay(
                frames[symbol],
                effective,
                warmup_bars=warmup_bars,
                history_bars=history_bars,
                cost_bps_per_side=args.cost_bps_per_side,
            )
            counter = {"blocked_entry_signals": 0}
            wrapped = _wrapped_strategy(effective, candidate_spec, counter)
            candidate_replay = base._replay(
                frames[symbol],
                wrapped,
                warmup_bars=warmup_bars,
                history_bars=history_bars,
                cost_bps_per_side=args.cost_bps_per_side,
            )
            blocked_signals += counter["blocked_entry_signals"]
            if _number(baseline["stats"].get("net_return_pct_sum")) > 0.0:
                positive_symbols_before += 1
            if _number(candidate_replay["stats"].get("net_return_pct_sum")) > 0.0:
                positive_symbols_after += 1
            for row in candidate_replay.get("trades", []):
                if isinstance(row, dict):
                    full_replay_rows.append({"symbol": symbol, **row})

        full_replay_stats = _stats(full_replay_rows)
        baseline_payoff = _number(baseline_stats.get("payoff_ratio"), 0.0)
        candidate_payoff = _number(full_replay_stats.get("payoff_ratio"), 0.0)
        if blocked_signals <= 0:
            failure_reasons.append("NO_BEHAVIORAL_DELTA")
        if _number(full_replay_stats.get("net_return_pct_sum"), -math.inf) <= _number(baseline_stats.get("net_return_pct_sum"), -math.inf):
            failure_reasons.append("NET_NOT_IMPROVED")
        if _number(full_replay_stats.get("net_profit_factor"), 0.0) < _number(baseline_stats.get("net_profit_factor"), 0.0):
            failure_reasons.append("PF_DEGRADED")
        if baseline_payoff > 0.0 and candidate_payoff < baseline_payoff * 0.95:
            failure_reasons.append("PAYOFF_DEGRADED_GT_5PCT")
        if positive_symbols_after < positive_symbols_before:
            failure_reasons.append("SYMBOL_DIVERSIFICATION_DEGRADED")
        accepted = not failure_reasons

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_SINGLE_CAUSE_SURGERY_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "selected_strategy_id": selected_id or None,
        "census_selection_mode": census.get("selection_mode"),
        "census_selected_summary": census.get("selected_summary"),
        "fetch_results": fetch_results,
        "baseline_stats": baseline_stats,
        "trade_count_traced": len(trace_rows),
        "loss_count_traced": sum(_number(row.get("net_return_pct")) < 0.0 for row in trace_rows),
        "candidate_count": len(candidates),
        "eligible_candidate_count": len(eligible),
        "top_candidates": candidates[:20],
        "selected_single_cause": selected_candidate,
        "full_replay_stats": full_replay_stats,
        "blocked_entry_signal_count": blocked_signals,
        "positive_symbols_before": positive_symbols_before,
        "positive_symbols_after": positive_symbols_after,
        "single_cause_surgery_accepted": accepted,
        "failure_reasons": failure_reasons,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "next": "THIRD_NONOVERLAP_OOS" if accepted and not blockers else "ROLLBACK_SINGLE_CAUSE_CHILD_AND_HOLD",
    }
    _atomic_json(root / OUTPUT_DIR / "summary.json", report)
    print(
        json.dumps(
            {
                "STATE": report["state"],
                "SELECTED_STRATEGY": report["selected_strategy_id"],
                "CAUSE": selected_candidate["label"] if selected_candidate else None,
                "BASELINE": baseline_stats,
                "CANDIDATE": full_replay_stats,
                "BLOCKED": blocked_signals,
                "ACCEPTED": accepted,
                "FAILURE_REASONS": failure_reasons,
                "BLOCKERS": blockers,
                "NEXT": report["next"],
            },
            sort_keys=True,
        )
    )
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
