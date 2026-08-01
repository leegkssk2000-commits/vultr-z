from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

VERSION = "ZEL_DATA_B_RISK_ADAPTER_ABLATION_V1"
INTERVALS = ("15m", "1m")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_adapter(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("zel_trade_method_risk_adapter_ablation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ADAPTER_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"NONFINITE:{value}")
    return number


def load_report(path: Path, interval: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"REPORT_NOT_OBJECT:{path}")
    if value.get("state") != "PASS" or value.get("interval") != interval:
        raise RuntimeError(f"REPORT_NOT_PASS:{interval}:{value.get('state')}:{value.get('interval')}")
    if int(value.get("replay", {}).get("strategy_count_completed") or 0) != 25:
        raise RuntimeError(f"REPORT_STRATEGY_COUNT:{interval}")
    if int(value.get("replay", {}).get("error_count") or 0) != 0:
        raise RuntimeError(f"REPORT_ERROR_COUNT:{interval}")
    return value


def load_trades(path: Path, interval: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise RuntimeError(f"TRADE_NOT_OBJECT:{interval}:{line_number}")
            for field in ("strategy_id", "window_id", "exit_ts", "realized_R"):
                if row.get(field) in (None, ""):
                    raise RuntimeError(f"TRADE_FIELD_MISSING:{interval}:{line_number}:{field}")
            row = dict(row)
            row["interval"] = interval
            row["realized_R"] = finite(row["realized_R"])
            rows.append(row)
    return rows


def max_drawdown(values: Sequence[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses == 0:
        return 999.0 if gains > 0 else None
    return gains / losses


def payoff_ratio(values: Sequence[float]) -> float | None:
    wins = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    if not wins or not losses:
        return None
    return statistics.fmean(wins) / statistics.fmean(losses)


def max_consecutive_losses(values: Sequence[float]) -> int:
    current = maximum = 0
    for value in values:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def metrics(values: Sequence[float]) -> dict[str, Any]:
    count = len(values)
    return {
        "sample_count": count,
        "net_R": sum(values),
        "expectancy_R": statistics.fmean(values) if values else None,
        "profit_factor": profit_factor(values),
        "win_rate_pct": (sum(value > 0 for value in values) / count * 100.0) if values else None,
        "payoff_ratio": payoff_ratio(values),
        "max_drawdown_R": max_drawdown(values),
        "max_consecutive_losses": max_consecutive_losses(values),
    }


def context_before(outcomes: Sequence[float]) -> dict[str, Any]:
    consecutive = 0
    for value in reversed(outcomes):
        if value < 0:
            consecutive += 1
        else:
            break
    return {
        "consecutive_losses": consecutive,
        "rolling_20_loss_r": sum(outcomes[-20:]),
        "rolling_50_loss_r": sum(outcomes[-50:]),
    }


def replay_window(rows: Sequence[Mapping[str, Any]], resolver: Callable[[Mapping[str, Any]], Any]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row.get("exit_ts")), str(row.get("event_id") or "")))
    control = [finite(row["realized_R"]) for row in ordered]
    candidate: list[float] = []
    warning_count = block_trigger_count = blocked_trade_count = 0
    first_warning_index: int | None = None
    first_block_index: int | None = None
    blocked = False
    decisions: list[dict[str, Any]] = []

    for index, row in enumerate(ordered, start=1):
        if blocked:
            blocked_trade_count += 1
            continue
        before = context_before(candidate)
        decision = resolver(before)
        mode = str(getattr(decision, "mode").value)
        action = str(getattr(decision, "action"))
        size = finite(getattr(decision, "size_multiplier"))
        if mode == "warning_reduce25":
            warning_count += 1
            first_warning_index = first_warning_index or index
        if action in {"block", "stop"} or size <= 0.0:
            block_trigger_count += 1
            blocked_trade_count += 1
            first_block_index = first_block_index or index
            blocked = True
            decisions.append({
                "trade_index": index,
                "context_before": before,
                "mode": mode,
                "action": action,
                "size_multiplier": size,
                "executed": False,
                "current_outcome_used_in_decision": False,
            })
            continue
        scaled = finite(row["realized_R"]) * size
        candidate.append(scaled)
        if mode != "normal" or index in {1, len(ordered)}:
            decisions.append({
                "trade_index": index,
                "context_before": before,
                "mode": mode,
                "action": action,
                "size_multiplier": size,
                "executed": True,
                "scaled_outcome_R": scaled,
                "current_outcome_used_in_decision": False,
            })

    return {
        "attempted_trade_count": len(control),
        "executed_trade_count": len(candidate),
        "blocked_trade_count": blocked_trade_count,
        "warning_count": warning_count,
        "block_trigger_count": block_trigger_count,
        "first_warning_trade_index": first_warning_index,
        "first_block_trade_index": first_block_index,
        "control_values": control,
        "candidate_values": candidate,
        "decision_samples": decisions[:50],
        "window_reset_after_end": True,
        "block_scope": "REMAINDER_OF_SEALED_WINDOW",
        "no_lookahead": True,
    }


def delta(control: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("net_R", "expectancy_R", "profit_factor", "win_rate_pct", "payoff_ratio", "max_drawdown_R")
    result: dict[str, Any] = {}
    for field in fields:
        left = control.get(field)
        right = candidate.get(field)
        result[field] = None if left is None or right is None else float(right) - float(left)
    return result


def classify(control: Mapping[str, Any], candidate: Mapping[str, Any], counts: Mapping[str, int]) -> str:
    if counts["warning_count"] == 0 and counts["block_trigger_count"] == 0:
        return "NO_POLICY_TRIGGER_NO_EFFECT"
    comparable = {
        "net": float(candidate.get("net_R") or 0.0) >= float(control.get("net_R") or 0.0),
        "expectancy": float(candidate.get("expectancy_R") or -1e18) >= float(control.get("expectancy_R") or -1e18),
        "pf": float(candidate.get("profit_factor") or 0.0) >= float(control.get("profit_factor") or 0.0),
        "dd": float(candidate.get("max_drawdown_R") or 0.0) <= float(control.get("max_drawdown_R") or 0.0),
    }
    wins = sum(comparable.values())
    if wins == 4:
        return "POSITIVE_MAIN_EFFECT_RESEARCH_ONLY"
    if wins >= 2:
        return "MIXED_MAIN_EFFECT_RESEARCH_ONLY"
    return "NEGATIVE_MAIN_EFFECT_RESEARCH_ONLY"


def strategy_result(strategy_id: str, rows: Sequence[Mapping[str, Any]], resolver: Callable[[Mapping[str, Any]], Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["interval"]), str(row["window_id"]))].append(row)
    windows: list[dict[str, Any]] = []
    control_values: list[float] = []
    candidate_values: list[float] = []
    counts = {"attempted_trade_count": 0, "executed_trade_count": 0, "blocked_trade_count": 0, "warning_count": 0, "block_trigger_count": 0}
    for (interval, window_id), items in sorted(grouped.items()):
        replayed = replay_window(items, resolver)
        control_values.extend(replayed.pop("control_values"))
        candidate_values.extend(replayed.pop("candidate_values"))
        for name in counts:
            counts[name] += int(replayed[name])
        windows.append({"interval": interval, "window_id": window_id, **replayed})
    control = metrics(control_values)
    candidate = metrics(candidate_values)
    return {
        "strategy_id": strategy_id,
        "window_count": len(windows),
        **counts,
        "control": control,
        "candidate": candidate,
        "delta_candidate_minus_control": delta(control, candidate),
        "classification": classify(control, candidate, counts),
        "windows": windows,
        "selection_authority": False,
        "promotion_authority": False,
        "action": "hold",
    }


def write_scoreboard(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "strategy_id", "classification", "attempted_trade_count", "executed_trade_count", "warning_count", "block_trigger_count", "blocked_trade_count",
        "control_net_R", "candidate_net_R", "delta_net_R", "control_expectancy_R", "candidate_expectancy_R", "delta_expectancy_R",
        "control_profit_factor", "candidate_profit_factor", "delta_profit_factor", "control_max_drawdown_R", "candidate_max_drawdown_R", "delta_max_drawdown_R",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "strategy_id": row["strategy_id"],
                "classification": row["classification"],
                "attempted_trade_count": row["attempted_trade_count"],
                "executed_trade_count": row["executed_trade_count"],
                "warning_count": row["warning_count"],
                "block_trigger_count": row["block_trigger_count"],
                "blocked_trade_count": row["blocked_trade_count"],
                "control_net_R": row["control"]["net_R"],
                "candidate_net_R": row["candidate"]["net_R"],
                "delta_net_R": row["delta_candidate_minus_control"]["net_R"],
                "control_expectancy_R": row["control"]["expectancy_R"],
                "candidate_expectancy_R": row["candidate"]["expectancy_R"],
                "delta_expectancy_R": row["delta_candidate_minus_control"]["expectancy_R"],
                "control_profit_factor": row["control"]["profit_factor"],
                "candidate_profit_factor": row["candidate"]["profit_factor"],
                "delta_profit_factor": row["delta_candidate_minus_control"]["profit_factor"],
                "control_max_drawdown_R": row["control"]["max_drawdown_R"],
                "candidate_max_drawdown_R": row["candidate"]["max_drawdown_R"],
                "delta_max_drawdown_R": row["delta_candidate_minus_control"]["max_drawdown_R"],
            })


def run(args: argparse.Namespace) -> dict[str, Any]:
    adapter_path = Path(args.adapter).resolve()
    adapter = load_adapter(adapter_path)
    reports = {interval: load_report(Path(getattr(args, f"report_{interval.replace('m', 'm')}")), interval) for interval in INTERVALS}
    trade_paths = {"15m": Path(args.trades_15m).resolve(), "1m": Path(args.trades_1m).resolve()}
    rows: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    for interval in INTERVALS:
        interval_rows = load_trades(trade_paths[interval], interval)
        expected = int(reports[interval]["replay"]["closed_trade_count"])
        if len(interval_rows) != expected:
            raise RuntimeError(f"TRADE_COUNT_MISMATCH:{interval}:{len(interval_rows)}:{expected}")
        rows.extend(interval_rows)
        source[interval] = {
            "report_sha256": sha256_path(Path(getattr(args, f"report_{interval.replace('m', 'm')}"))),
            "trades_sha256": sha256_path(trade_paths[interval]),
            "closed_trade_count": len(interval_rows),
        }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["strategy_id"])].append(row)
    if len(grouped) != 25:
        raise RuntimeError(f"STRATEGY_COUNT:{len(grouped)}")
    results = [strategy_result(strategy_id, items, adapter.resolve_risk_mode) for strategy_id, items in sorted(grouped.items())]
    counts: dict[str, int] = defaultdict(int)
    for row in results:
        counts[row["classification"]] += 1
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    terminal = {
        "schema_version": "zel.data_b.risk_adapter_ablation.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_DATA_B_RISK_ADAPTER_ABLATION",
        "strategy_count": len(results),
        "intervals": list(INTERVALS),
        "source": source,
        "total_closed_trade_count": len(rows),
        "classification_counts": dict(sorted(counts.items())),
        "strategies": results,
        "policy": {
            "warning_consecutive_losses": 20,
            "block_consecutive_losses": 30,
            "rolling_20_loss_guard_R": -8.0,
            "rolling_50_loss_guard_R": -20.0,
            "warning_size_multiplier": 0.75,
            "window_reset": True,
            "block_scope": "REMAINDER_OF_SEALED_WINDOW",
            "no_lookahead": True,
        },
        "adapter_sha256": sha256_path(adapter_path),
        "economic_improvement_claim_allowed": False,
        "interaction_admission_allowed": False,
        "next": "REVIEW_MAIN_EFFECT_THEN_ADMIT_ONLY_NONNEGATIVE_RISK_INTERACTIONS",
        "canonical_strategy_files_mutated": False,
        "canonical_trade_methods_mutated": False,
        "canonical_registry_mutated": False,
        "runtime_binding_allowed": False,
        "shadow_start_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
    }
    (output / "latest.json").write_text(json.dumps(terminal, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    write_scoreboard(output / "scoreboard.csv", results)
    return terminal


def self_test() -> None:
    class Mode:
        def __init__(self, value: str): self.value = value
    class Decision:
        def __init__(self, mode: str, action: str, size: float): self.mode, self.action, self.size_multiplier = Mode(mode), action, size
    def resolver(ctx: Mapping[str, Any]) -> Decision:
        if int(ctx["consecutive_losses"]) >= 30: return Decision("block", "block", 0.0)
        if int(ctx["consecutive_losses"]) >= 20: return Decision("warning_reduce25", "reduce25", 0.75)
        return Decision("normal", "hold", 1.0)
    rows = [{"exit_ts": f"2026-01-01T00:{i:02d}:00Z", "event_id": str(i), "realized_R": -0.2} for i in range(31)]
    result = replay_window(rows, resolver)
    assert result["first_warning_trade_index"] == 21, result
    assert result["first_block_trade_index"] == 31, result
    assert result["executed_trade_count"] == 30, result
    assert result["no_lookahead"] is True, result
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter")
    parser.add_argument("--trades-15m")
    parser.add_argument("--trades-1m")
    parser.add_argument("--report-15m")
    parser.add_argument("--report-1m")
    parser.add_argument("--output-dir")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.adapter, args.trades_15m, args.trades_1m, args.report_15m, args.report_1m, args.output_dir)):
        parser.error("all source and output arguments are required")
    result = run(args)
    print(json.dumps({"state": result["state"], "strategy_count": result["strategy_count"], "classifications": result["classification_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
