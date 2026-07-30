from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.tools.strategy11_regime_edge_router_v3 import ConfigStrategyWrapper
from backend.tools.strategy11_long_short_observer_v3 import replay as replay_long_short

VERSION = "STRATEGY11_EXPANDED_DISCOVERY_V3"
SAFETY = {"research_only": True, "promotion_authority": False, "protected_mutations": 0, "execution_allowed": False, "execution_authority": "NONE", "order_authority": "BLOCKED", "runtime_bound": False}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_SPEC_FAILED:{name}:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def exact_module(compute_root: Path) -> Any:
    if str(compute_root) not in sys.path:
        sys.path.insert(0, str(compute_root))
    return load_module("s11_v3_exact", compute_root / "backend/tools/r7a4d_strategy11_exact.py")


def prepare_archive(args: argparse.Namespace) -> int:
    compute_root = Path(args.compute_root).resolve()
    policy = read_json(Path(args.policy).resolve())
    exact = exact_module(compute_root)
    out = Path(args.out).resolve()
    interval_ms = int(policy["archive"]["interval_ms"])
    eval_bars = int(policy["archive"]["window_bars"])
    warmup = int(policy["archive"]["warmup_bars"])
    rows: list[dict[str, Any]] = []
    intervals: list[tuple[int, int]] = []
    for window_id, end_iso in enumerate(policy["archive"]["anchor_ends_utc"], start=1):
        end_ms = int(pd.Timestamp(end_iso).timestamp() * 1000)
        start_ms = end_ms - (eval_bars + warmup - 1) * interval_ms
        eval_start_ms = end_ms - (eval_bars - 1) * interval_ms
        if any(not (eval_start_ms > previous_end or end_ms < previous_start) for previous_start, previous_end in intervals):
            raise RuntimeError(f"ARCHIVE_EVALUATION_OVERLAP:{window_id}")
        intervals.append((eval_start_ms, end_ms))
        for symbol in policy["symbols"]:
            frame, endpoint, request_count = exact.base._fetch_exact(symbol, start_ms=start_ms, end_ms=end_ms, expected_rows=eval_bars + warmup)
            path = out / "market" / f"A{window_id:02d}-{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
            rows.append({"window_id": f"A{window_id:02d}", "symbol": symbol, "start_ms": start_ms, "evaluation_start_ms": eval_start_ms, "end_ms": end_ms, "rows": len(frame), "path": str(path.relative_to(out)), "sha256": sha256(path), "endpoint": endpoint, "request_count": request_count, "state": "PASS"})
    manifest = {"schema_version": "3.0", "version": VERSION, "state": "PASS_EXPANDED_ARCHIVE", "window_count": len(policy["archive"]["anchor_ends_utc"]), "symbol_count": len(policy["symbols"]), "evaluation_symbol_bars": len(policy["archive"]["anchor_ends_utc"]) * len(policy["symbols"]) * eval_bars, "warmup_bars": warmup, "window_bars": eval_bars, "rows": rows, "evaluation_periods_non_overlapping": True, **SAFETY}
    manifest["archive_sha256"] = stable_sha(manifest)
    write_json(out / "manifest.json", manifest)
    print(json.dumps({"state": manifest["state"], "symbol_bars": manifest["evaluation_symbol_bars"], "files": len(rows)}, sort_keys=True))
    return 0


def config_class(module: Any, name: str) -> type[Any]:
    cls = getattr(module, name, None)
    if not isinstance(cls, type) or not dataclasses.is_dataclass(cls):
        raise RuntimeError(f"CONFIG_CLASS_MISSING:{name}")
    return cls


def combine_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_return_pct"]) for row in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    cumulative = peak = dd = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        dd = max(dd, peak - cumulative)
    gross_loss = abs(sum(losses))
    return {"trade_count": len(values), "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0, "net_return_pct_sum": sum(values), "net_profit_factor": sum(wins) / gross_loss if gross_loss else (999.0 if wins else 0.0), "payoff_ratio": (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else 0.0, "max_drawdown_pct": dd}


def discovery_replay(args: argparse.Namespace) -> int:
    compute_root = Path(args.compute_root).resolve()
    archive_root = Path(args.archive_root).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    plan = read_json(Path(args.plan).resolve())
    registry = read_json(Path(args.registry).resolve())
    policy = read_json(Path(args.policy).resolve())
    exact = exact_module(compute_root)
    prior = load_module("s11_v3_prior", compute_root / "backend/tools/r7a4d_strategy11_gemini_22_prework_v1_1.py").v1
    canonical = exact.base._load_registry(compute_root)
    registry_map = {str(row["strategy_id"]): row for row in registry["rows"]}
    plan_map = {str(row["strategy_id"]): row for row in plan["rows"]}
    requested = [value for value in args.strategy_ids.split(",") if value]
    out = Path(args.out).resolve()
    manifest = read_json(archive_root / "manifest.json")
    batch_rows: list[dict[str, Any]] = []
    for strategy_id in requested:
        if strategy_id not in plan_map:
            continue
        evidence_summary = read_json(prior.find_summary(evidence_root, strategy_id))
        candidate = evidence_summary["candidate"]
        gate = exact._gate_from(candidate)
        exit_spec = exact._exit_from(candidate)
        surgery = prior.p.surgery_from(evidence_summary.get("surgery"))
        symbols = tuple(str(value) for value in evidence_summary.get("symbols", []))
        canonical_row = canonical[strategy_id]
        strategy = exact.base._load_canonical_strategy(compute_root, strategy_id, canonical_row)
        source_path = compute_root / canonical_row["canonical_engine"]["implementation_path"]
        module = load_module(f"s11_v3_strategy_{strategy_id}", source_path)
        cfg_cls = config_class(module, str(registry_map[strategy_id]["config_class"]))
        variants = [{"candidate_id": "NO_CHANGE_CONTROL", "field": None, "mutation_value": None, "regime_scope": None}] + [dict(plan_map[strategy_id]["candidate_specs"][cid]) for cid in plan_map[strategy_id]["candidate_ids"]]
        summaries: list[dict[str, Any]] = []
        for variant in variants:
            variant_id = str(variant["candidate_id"])
            wrapper = ConfigStrategyWrapper(strategy, cfg_cls, variant.get("field"), variant.get("mutation_value"), variant.get("regime_scope"))
            ledgers: list[list[dict[str, Any]]] = []
            window_stats: dict[str, list[dict[str, Any]]] = {}
            observer_totals = {"long": [], "short": []}
            for repeat in ("A", "B"):
                repeat_trades: list[dict[str, Any]] = []
                wrapper.reset()
                for row in manifest["rows"]:
                    if row["symbol"] not in symbols:
                        continue
                    frame = pd.read_csv(archive_root / row["path"])
                    frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
                    features = exact.compute_feature_frame(frame)
                    result = exact._replay(frame, features, wrapper, gate, exit_spec, surgery, warmup_bars=int(manifest["warmup_bars"]), history_bars=int(policy["archive"]["history_bars"]), cost_bps_per_side=float(policy["cost_bps_per_side"]))
                    for trade in result["trades"]:
                        trade = dict(trade); trade["window_id"] = row["window_id"]; trade["symbol"] = row["symbol"]; repeat_trades.append(trade)
                    if repeat == "A":
                        window_stats.setdefault(row["window_id"], []).extend(result["trades"])
                        observer = replay_long_short(frame, wrapper, warmup_bars=int(manifest["warmup_bars"]), history_bars=int(policy["archive"]["history_bars"]), cost_bps_per_side=float(policy["cost_bps_per_side"]))
                        observer_totals["long"].extend(value for value in observer["trades"] if value["side"] == "long")
                        observer_totals["short"].extend(value for value in observer["trades"] if value["side"] == "short")
                ledgers.append(sorted(repeat_trades, key=lambda value: (value.get("window_id"), value.get("symbol"), value.get("entry_ts"), value.get("exit_ts"))))
            parity = stable_sha(ledgers[0]) == stable_sha(ledgers[1]) and len({stable_sha(row) for row in ledgers[0]}) == len(ledgers[0])
            stats = combine_stats(ledgers[0])
            per_window = {window: combine_stats(values) for window, values in window_stats.items()}
            positive_windows = sum(value["net_return_pct_sum"] > 0 for value in per_window.values())
            summary = {"strategy_id": strategy_id, "variant_id": variant_id, "candidate_spec": variant, "candidate_spec_sha256": stable_sha(variant), **stats, "positive_window_count": positive_windows, "window_count": manifest["window_count"], "parity": {"state": "PASS" if parity else "HOLD", "replay_a_sha256": stable_sha(ledgers[0]), "replay_b_sha256": stable_sha(ledgers[1]), "duplicate_trade_count": len(ledgers[0]) - len({stable_sha(row) for row in ledgers[0]})}, "opportunity_diagnostics": wrapper.diagnostics(), "short_observer": {"long": combine_stats(observer_totals["long"]), "short": combine_stats(observer_totals["short"]), "observer_only": True}, "canonical_mutated": False, **SAFETY}
            write_json(out / strategy_id / variant_id / "summary.json", summary)
            summaries.append(summary)
        control = summaries[0]
        for row in summaries[1:]:
            row["deltas"] = {key: row[key] - control[key] for key in ("trade_count", "net_return_pct_sum", "net_profit_factor", "payoff_ratio", "max_drawdown_pct")}
            improved = sum(row["deltas"][key] > 0 for key in ("net_return_pct_sum", "net_profit_factor", "payoff_ratio")) + int(row["deltas"]["max_drawdown_pct"] < 0)
            row["research_state"] = "DISCOVERY_PASS_INTERNAL_OR_REGIME" if row["parity"]["state"] == "PASS" and row["trade_count"] >= int(policy["classification"]["archive_trade_count_min"]) and row["positive_window_count"] >= int(policy["classification"]["positive_windows_min"]) and improved >= 2 and row["net_return_pct_sum"] > control["net_return_pct_sum"] else "DISCOVERY_HOLD"
        strategy_payload = {"schema_version": "3.0", "version": VERSION, "strategy_id": strategy_id, "control": control, "variants": summaries[1:], "archive_sha256": manifest["archive_sha256"], "source_sha256": canonical_row["canonical_engine"]["source_sha256"], "next": "FRESH_W1_CONFIRMATION" if any(str(row.get("research_state", "")).startswith("DISCOVERY_PASS") for row in summaries[1:]) else "WAIT_NEXT_AXIS", **SAFETY}
        strategy_payload["result_sha256"] = stable_sha(strategy_payload)
        write_json(out / strategy_id / "result.json", strategy_payload)
        batch_rows.append(strategy_payload)
    batch = {"schema_version": "3.0", "version": VERSION, "state": "PASS_V3_DISCOVERY_BATCH", "strategy_count": len(batch_rows), "rows": batch_rows, "archive_sha256": manifest["archive_sha256"], **SAFETY}
    batch["batch_sha256"] = stable_sha(batch)
    write_json(out / "batch.json", batch)
    print(json.dumps({"state": batch["state"], "strategies": len(batch_rows), "pass_candidates": sum(sum(str(value.get("research_state", "")).startswith("DISCOVERY_PASS") for value in row["variants"]) for row in batch_rows)}, sort_keys=True))
    return 0


def aggregate(args: argparse.Namespace) -> int:
    root = Path(args.batch_root).resolve()
    plan = read_json(Path(args.plan).resolve())
    batches = [read_json(path) for path in sorted(root.glob("batch-*/batch.json"))]
    rows = [row for batch in batches for row in batch.get("rows", [])]
    expected = set(plan.get("active_strategy_ids", [])); observed = {str(row["strategy_id"]) for row in rows}
    blockers: list[str] = []
    if observed != expected:
        blockers.append(f"STRATEGY_SET_MISMATCH:{len(observed)}:{len(expected)}")
    for row in rows:
        if rows and row.get("archive_sha256") != rows[0].get("archive_sha256"):
            blockers.append(f"ARCHIVE_SHA_MISMATCH:{row['strategy_id']}")
        for variant in row.get("variants", []):
            if variant.get("parity", {}).get("state") != "PASS":
                blockers.append(f"PARITY:{row['strategy_id']}:{variant.get('variant_id')}")
            if variant.get("canonical_mutated") is not False or variant.get("promotion_authority") is not False:
                blockers.append(f"AUTHORITY:{row['strategy_id']}:{variant.get('variant_id')}")
            if "short_observer" not in variant or "opportunity_diagnostics" not in variant:
                blockers.append(f"DIAGNOSTICS_MISSING:{row['strategy_id']}:{variant.get('variant_id')}")
    pass_rows = [{"strategy_id": row["strategy_id"], "variant_id": variant["variant_id"], "research_state": variant["research_state"], "trade_count": variant["trade_count"], "net_return_pct_sum": variant["net_return_pct_sum"], "net_profit_factor": variant["net_profit_factor"], "max_drawdown_pct": variant["max_drawdown_pct"], "short_trade_count": variant["short_observer"]["short"]["trade_count"], "candidate_spec_sha256": variant["candidate_spec_sha256"]} for row in rows for variant in row.get("variants", []) if str(variant.get("research_state", "")).startswith("DISCOVERY_PASS")]
    payload = {"schema_version": "3.0", "version": VERSION, "state": "PASS_V3_ORGANIC_AUDIT" if not blockers else "HOLD_V3_ORGANIC_AUDIT", "strategy_count": len(rows), "candidate_count": sum(len(row.get("variants", [])) for row in rows), "discovery_pass_count": len(pass_rows), "discovery_pass_rows": sorted(pass_rows, key=lambda value: (-value["net_return_pct_sum"], -value["trade_count"])), "blockers": blockers, "fresh_confirmation_required": True, "w1_w2_w3_new_sealed_required": True, **SAFETY}
    payload["final_sha256"] = stable_sha(payload)
    write_json(Path(args.out).resolve(), payload)
    print(json.dumps({"state": payload["state"], "strategies": payload["strategy_count"], "candidates": payload["candidate_count"], "passes": payload["discovery_pass_count"], "blockers": len(blockers)}, sort_keys=True))
    return 0 if not blockers else 3


def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="mode", required=True)
    prepare = sub.add_parser("prepare"); prepare.add_argument("--compute-root", required=True); prepare.add_argument("--policy", required=True); prepare.add_argument("--out", required=True)
    replay = sub.add_parser("replay")
    for name in ("compute_root", "archive_root", "evidence_root", "plan", "registry", "policy", "strategy_ids", "out"):
        replay.add_argument("--" + name.replace("_", "-"), required=True)
    agg = sub.add_parser("aggregate"); agg.add_argument("--batch-root", required=True); agg.add_argument("--plan", required=True); agg.add_argument("--policy", required=True); agg.add_argument("--out", required=True)
    args = parser.parse_args()
    return prepare_archive(args) if args.mode == "prepare" else discovery_replay(args) if args.mode == "replay" else aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
