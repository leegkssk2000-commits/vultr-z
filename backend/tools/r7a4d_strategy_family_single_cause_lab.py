from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

from backend.strategy25.indicator_contract_repair_adapter_v2 import REPAIR_SPECS
from backend.strategy25.indicator_contract_repair_loader_v2 import load_repaired_strategy
from backend.strategy25.strategy_family_indicator_search_v1 import variants_for, wrap_strategy


ROOT = Path(__file__).resolve().parents[2]
BASE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"
TRACE_RUNNER_PATH = ROOT / "backend/tools/r7a4d_strategy_indicator_repair_loss_anatomy.py"
OUTPUT_DIR = "artifacts/strategy_family_single_cause_lab_v1"


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_module(BASE_RUNNER_PATH, "r7a4d_family_surgery_base_v1")
trace = _load_module(TRACE_RUNNER_PATH, "r7a4d_family_surgery_trace_v1")


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


def _load_family_summaries(root: Path) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("summary.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("authority") == "READ_ONLY_FAMILY_INDICATOR_SEARCH_NO_EXECUTION":
            summaries.append(payload)
    if not summaries:
        raise RuntimeError("FAMILY_SUMMARIES_NOT_FOUND")
    return summaries


def _validation_net(candidate: Mapping[str, Any]) -> float:
    rows = candidate.get("validation_windows") or []
    if not rows:
        return -1000.0
    return _number(rows[0].get("stats", {}).get("net_return_pct_sum"), -1000.0)


def _select_candidate(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    pool: list[dict[str, Any]] = []
    for summary in summaries:
        for candidate in summary.get("finalists") or []:
            row = dict(candidate)
            row["family"] = summary["family"]
            row["window_contract"] = summary["window_contract"]
            pool.append(row)
    if not pool:
        raise RuntimeError("FAMILY_FINALISTS_EMPTY")
    validation_survivors = [row for row in pool if row.get("validation_eligible")]
    if validation_survivors:
        return max(validation_survivors, key=lambda row: (_validation_net(row), float(row.get("development_score", -1e9))))
    development_survivors = [row for row in pool if row.get("development_eligible")]
    if development_survivors:
        return max(development_survivors, key=lambda row: (float(row.get("development_score", -1e9)), _validation_net(row)))
    return max(pool, key=lambda row: float(row.get("development_score", -1e9)))


def _effective_strategy(root: Path, registry: Mapping[str, Any], strategy_id: str):
    canonical = base._load_canonical_strategy(root, strategy_id, registry[strategy_id])
    return load_repaired_strategy(root, strategy_id) if strategy_id in REPAIR_SPECS else canonical


def _match_descriptor(result: Mapping[str, Any], descriptor: Mapping[str, Any]) -> bool:
    if str(result.get("action") or "hold").lower() != "enter":
        return False
    kind = descriptor["kind"]
    value = descriptor["value"]
    if kind == "why":
        return str(result.get("why") or "unknown") == value
    if kind == "skill":
        return str(result.get("skill") or "none") == value
    if kind == "tag":
        return value in {str(item) for item in (result.get("tags") or [])}
    if kind == "indicator_true":
        indicators = result.get("indicators") if isinstance(result.get("indicators"), Mapping) else {}
        return indicators.get(value) is True
    if kind == "indicator_false":
        indicators = result.get("indicators") if isinstance(result.get("indicators"), Mapping) else {}
        return indicators.get(value) is False
    return False


def _block_descriptor(strategy: Callable[..., dict[str, Any]], descriptor: Mapping[str, Any]):
    counter = {"blocked_entry_signals": 0}

    def wrapped(history: pd.DataFrame, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = strategy(history, *args, **kwargs)
        if not isinstance(result, Mapping):
            raise TypeError("STRATEGY_RESULT_MAPPING_REQUIRED")
        output = dict(result)
        if _match_descriptor(output, descriptor):
            counter["blocked_entry_signals"] += 1
            indicators = dict(output.get("indicators") or {})
            indicators["single_cause_block"] = dict(descriptor)
            output.update({"side": None, "action": "hold", "size": 0.0, "why": f"single_cause_block:{descriptor['kind']}:{descriptor['value']}", "skill": "none", "confidence": 0.0, "indicators": indicators})
        return output

    return wrapped, counter


def _descriptors(trades: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for trade in trades:
        why = str(trade.get("entry_why") or "unknown")
        skill = str(trade.get("entry_skill") or "none")
        candidates[("why", why)] = {"kind": "why", "value": why}
        candidates[("skill", skill)] = {"kind": "skill", "value": skill}
        for tag in trade.get("entry_tags") or []:
            text = str(tag)
            candidates[("tag", text)] = {"kind": "tag", "value": text}
        indicators = trade.get("entry_indicators") if isinstance(trade.get("entry_indicators"), Mapping) else {}
        for key, value in indicators.items():
            if isinstance(value, bool) and key not in {"family_variant_allowed"}:
                kind = "indicator_true" if value else "indicator_false"
                candidates[(kind, str(key))] = {"kind": kind, "value": str(key)}
    return list(candidates.values())


def _trade_matches(trade: Mapping[str, Any], descriptor: Mapping[str, Any]) -> bool:
    kind = descriptor["kind"]
    value = descriptor["value"]
    if kind == "why":
        return str(trade.get("entry_why") or "unknown") == value
    if kind == "skill":
        return str(trade.get("entry_skill") or "none") == value
    if kind == "tag":
        return value in {str(item) for item in (trade.get("entry_tags") or [])}
    indicators = trade.get("entry_indicators") if isinstance(trade.get("entry_indicators"), Mapping) else {}
    if kind == "indicator_true":
        return indicators.get(value) is True
    if kind == "indicator_false":
        return indicators.get(value) is False
    return False


def _cluster_stats(trades: list[dict[str, Any]], descriptor: Mapping[str, Any]) -> dict[str, Any] | None:
    selected = [trade for trade in trades if _trade_matches(trade, descriptor)]
    if len(selected) < 5 or len(selected) >= len(trades):
        return None
    stats = trace._trade_stats(selected)
    count = int(stats.get("trade_count") or 0)
    losses = int(stats.get("loss_count") or 0)
    wins = int(stats.get("win_count") or 0)
    net = _number(stats.get("net_return_pct_sum"))
    precision = losses / count if count else 0.0
    if losses < 4 or precision < 0.65 or net >= 0.0:
        return None
    kind_weight = {"why": 1.20, "skill": 1.15, "tag": 1.0, "indicator_true": 0.90, "indicator_false": 0.85}.get(descriptor["kind"], 0.8)
    score = (-net) * precision * math.log1p(count) * kind_weight / max(wins + 1, 1)
    return {"descriptor": dict(descriptor), "stats": stats, "loss_precision_pct": precision * 100.0, "winner_contamination_count": wins, "cluster_score": score}


def _aggregate_windows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    runs = [{"stats": row["stats"]} for row in rows]
    return base._aggregate(runs)


def _replay_window_set(
    *,
    frames: Mapping[str, pd.DataFrame],
    strategy: Callable[..., dict[str, Any]],
    window_bars: int,
    warmup_bars: int,
    history_bars: int,
    cost_bps_per_side: float,
    total_windows: int,
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    labels = [f"D{i + 1}" for i in range(max(total_windows - 2, 0))] + ["V1", "H1"]
    for window_index in range(total_windows):
        start = window_index * window_bars
        end = start + window_bars
        runs: list[dict[str, Any]] = []
        symbols: list[dict[str, Any]] = []
        for symbol in base.SYMBOLS:
            replay = base._replay(
                frames[symbol].iloc[start:end].reset_index(drop=True),
                strategy,
                warmup_bars=warmup_bars,
                history_bars=history_bars,
                cost_bps_per_side=cost_bps_per_side,
            )
            runs.append(replay)
            symbols.append({"symbol": symbol, "stats": replay["stats"]})
        stats = base._aggregate(runs)
        windows.append({"window_id": labels[window_index], "stats": stats, "positive_symbols": sum(_number(row["stats"].get("net_return_pct_sum")) > 0.0 for row in symbols), "symbols": symbols})
    return windows


def _acceptance(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]], blocked: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    holdout_base = baseline[-1]["stats"]
    holdout_candidate = candidate[-1]["stats"]
    combined_base = _aggregate_windows(baseline)
    combined_candidate = _aggregate_windows(candidate)
    if blocked <= 0:
        reasons.append("NO_BEHAVIORAL_DELTA")
    if int(holdout_candidate.get("trade_count") or 0) < 4:
        reasons.append("HOLDOUT_TRADES_LT_4")
    if _number(holdout_candidate.get("net_return_pct_sum")) <= 0.0:
        reasons.append("HOLDOUT_NET_NOT_POSITIVE")
    if _number(holdout_candidate.get("net_profit_factor"), 0.0) <= 1.0:
        reasons.append("HOLDOUT_PF_NOT_ABOVE_1")
    if candidate[-1]["positive_symbols"] < 2:
        reasons.append("HOLDOUT_POSITIVE_SYMBOLS_LT_2")
    if _number(holdout_candidate.get("net_return_pct_sum")) < _number(holdout_base.get("net_return_pct_sum")):
        reasons.append("HOLDOUT_NET_BELOW_BASELINE")
    if int(combined_candidate.get("trade_count") or 0) < 25:
        reasons.append("COMBINED_TRADES_LT_25")
    if _number(combined_candidate.get("net_return_pct_sum")) <= 1.0:
        reasons.append("COMBINED_NET_LE_1PCT")
    if _number(combined_candidate.get("net_profit_factor"), 0.0) <= 1.05:
        reasons.append("COMBINED_PF_LE_1_05")
    base_payoff = _number(combined_base.get("payoff_ratio"), 0.0)
    candidate_payoff = _number(combined_candidate.get("payoff_ratio"), 0.0)
    if base_payoff > 0.0 and candidate_payoff < base_payoff * 0.90:
        reasons.append("COMBINED_PAYOFF_DEGRADED_GT_10PCT")
    return not reasons, reasons


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--family-artifacts", required=True)
    parser.add_argument("--window-bars", type=int, default=700)
    parser.add_argument("--warmup-bars", type=int, default=180)
    parser.add_argument("--history-bars", type=int, default=220)
    parser.add_argument("--cost-bps-per-side", type=float, default=4.0)
    parser.add_argument("--top-clusters", type=int, default=5)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    summaries = _load_family_summaries(Path(args.family_artifacts).resolve())
    selected = _select_candidate(summaries)
    strategy_id = str(selected["strategy_id"])
    variant_id = str(selected["variant_id"])
    family = str(selected["family"])
    contract = selected["window_contract"]
    total_windows = int(contract["development_windows"]) + int(contract["validation_windows"]) + int(contract["holdout_windows"])
    total_bars = int(contract["window_bars"]) * total_windows
    start_ms = int(pd.Timestamp(contract["lab_start"]).timestamp() * 1000)
    end_ms = int(pd.Timestamp(contract["lab_end"]).timestamp() * 1000)

    blockers: list[str] = []
    frames: dict[str, pd.DataFrame] = {}
    fetch_results: list[dict[str, Any]] = []
    for symbol in base.SYMBOLS:
        try:
            frame, endpoint, requests = base._fetch_exact(symbol, start_ms=start_ms, end_ms=end_ms, expected_rows=total_bars)
            frames[symbol] = frame
            fetch_results.append({"symbol": symbol, "status": "PASS", "rows": len(frame), "endpoint": endpoint, "request_count": requests})
        except Exception as exc:
            error = f"{symbol}:{type(exc).__name__}:{exc}"
            blockers.append(error)
            fetch_results.append({"symbol": symbol, "status": "HOLD", "error": error})

    registry = base._load_registry(root)
    effective = _effective_strategy(root, registry, strategy_id)
    spec = next(spec for spec in variants_for(strategy_id) if spec.variant_id == variant_id)
    baseline_strategy = wrap_strategy(effective, spec)

    discovery_trades: list[dict[str, Any]] = []
    discovery_window_count = total_windows - 1
    if not blockers:
        for window_index in range(discovery_window_count):
            start = window_index * args.window_bars
            end = start + args.window_bars
            for symbol in base.SYMBOLS:
                replay = trace._replay_trace(
                    frames[symbol].iloc[start:end].reset_index(drop=True),
                    baseline_strategy,
                    warmup_bars=args.warmup_bars,
                    history_bars=args.history_bars,
                    cost_bps_per_side=args.cost_bps_per_side,
                )
                for trade in replay.get("trades", []):
                    discovery_trades.append({"symbol": symbol, "window_id": f"W{window_index + 1}", **trade})

    clusters = []
    for descriptor in _descriptors(discovery_trades):
        row = _cluster_stats(discovery_trades, descriptor)
        if row is not None:
            clusters.append(row)
    clusters = sorted(clusters, key=lambda row: float(row["cluster_score"]), reverse=True)

    baseline_windows = _replay_window_set(
        frames=frames,
        strategy=baseline_strategy,
        window_bars=args.window_bars,
        warmup_bars=args.warmup_bars,
        history_bars=args.history_bars,
        cost_bps_per_side=args.cost_bps_per_side,
        total_windows=total_windows,
    ) if not blockers else []

    experiments: list[dict[str, Any]] = []
    for cluster in clusters[: args.top_clusters]:
        gated, counter = _block_descriptor(baseline_strategy, cluster["descriptor"])
        candidate_windows = _replay_window_set(
            frames=frames,
            strategy=gated,
            window_bars=args.window_bars,
            warmup_bars=args.warmup_bars,
            history_bars=args.history_bars,
            cost_bps_per_side=args.cost_bps_per_side,
            total_windows=total_windows,
        )
        discovery_candidate = candidate_windows[:-1]
        discovery_baseline = baseline_windows[:-1]
        discovery_net_delta = _number(_aggregate_windows(discovery_candidate).get("net_return_pct_sum")) - _number(_aggregate_windows(discovery_baseline).get("net_return_pct_sum"))
        experiments.append({
            "cluster": cluster,
            "blocked_entry_signals": counter["blocked_entry_signals"],
            "windows": candidate_windows,
            "discovery_net_delta_pct": discovery_net_delta,
        })

    # Select surgery only on development + validation. Holdout remains unused until after this choice.
    experiments = sorted(
        experiments,
        key=lambda row: (
            float(row["discovery_net_delta_pct"]),
            _number(_aggregate_windows(row["windows"][:-1]).get("net_profit_factor"), 0.0),
        ),
        reverse=True,
    )
    chosen = experiments[0] if experiments else None
    accepted = False
    acceptance_reasons = ["NO_CAUSAL_CLUSTER"]
    if chosen is not None:
        accepted, acceptance_reasons = _acceptance(baseline_windows, chosen["windows"], int(chosen["blocked_entry_signals"]))

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_FAMILY_SEARCH_AND_SINGLE_CAUSE_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "selected": {
            "family": family,
            "strategy_id": strategy_id,
            "variant_id": variant_id,
            "development_score": selected.get("development_score"),
            "development_eligible": selected.get("development_eligible"),
            "validation_eligible": selected.get("validation_eligible"),
        },
        "window_contract": contract,
        "fetch_results": fetch_results,
        "discovery_trade_count": len(discovery_trades),
        "cluster_candidates": clusters,
        "baseline_windows": baseline_windows,
        "baseline_combined": _aggregate_windows(baseline_windows) if baseline_windows else None,
        "surgery_experiments": experiments,
        "chosen_surgery": chosen,
        "single_cause_accepted": accepted,
        "acceptance_reasons": acceptance_reasons,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "shadow_allowed": False,
        "next": "THIRD_OOS_THEN_SHADOW" if accepted else "HOLD_NO_MEANINGFUL_POSITIVE_SURVIVOR",
    }
    _atomic_json(root / OUTPUT_DIR / "summary.json", report)
    print(json.dumps({
        "STATE": report["state"],
        "SELECTED": report["selected"],
        "DISCOVERY_TRADES": len(discovery_trades),
        "CLUSTERS": len(clusters),
        "CHOSEN": None if chosen is None else {"descriptor": chosen["cluster"]["descriptor"], "blocked": chosen["blocked_entry_signals"], "discovery_net_delta_pct": chosen["discovery_net_delta_pct"], "holdout": chosen["windows"][-1]["stats"]},
        "ACCEPTED": accepted,
        "REASONS": acceptance_reasons,
        "NEXT": report["next"],
    }, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
