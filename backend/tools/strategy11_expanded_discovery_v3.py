from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from backend.tools.strategy11_v3_fast_causal import FastCausalConfigStrategyWrapper as ConfigStrategyWrapper, install_exact_prepare
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


def activate_compute_namespace(compute_root: Path) -> None:
    root = str(compute_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    import backend
    backend_path = str(compute_root / "backend")
    if hasattr(backend, "__path__") and backend_path not in backend.__path__:
        backend.__path__ = [backend_path, *list(backend.__path__)]


def exact_module(compute_root: Path) -> Any:
    activate_compute_namespace(compute_root)
    return load_module("s11_v3_exact", compute_root / "backend/tools/r7a4d_strategy11_exact.py")


def load_archive_cache(archive_root: Path, manifest: Mapping[str, Any], exact: Any) -> dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]]:
    cache: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]] = {}
    for row in manifest["rows"]:
        key = (str(row["window_id"]), str(row["symbol"]))
        frame = pd.read_csv(archive_root / row["path"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp_ms"], unit="ms", utc=True)
        cache[key] = (frame, exact.compute_feature_frame(frame))
    return cache


def materiality_evidence(candidate: Mapping[str, Any], control: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    thresholds = dict(policy["classification"]["materiality"])
    deltas = {
        "net_return_pct_sum": float(candidate["net_return_pct_sum"]) - float(control["net_return_pct_sum"]),
        "net_profit_factor": float(candidate["net_profit_factor"]) - float(control["net_profit_factor"]),
        "payoff_ratio": float(candidate["payoff_ratio"]) - float(control["payoff_ratio"]),
        "max_drawdown_pct_reduction": float(control["max_drawdown_pct"]) - float(candidate["max_drawdown_pct"]),
    }
    pf_saturated = min(float(candidate["net_profit_factor"]), float(control["net_profit_factor"])) >= 999.0
    flags = {
        "net": deltas["net_return_pct_sum"] >= float(thresholds["net_return_pct_points_min"]),
        "pf": (not pf_saturated) and deltas["net_profit_factor"] >= float(thresholds["profit_factor_min"]),
        "payoff": deltas["payoff_ratio"] >= float(thresholds["payoff_ratio_min"]),
        "dd": deltas["max_drawdown_pct_reduction"] >= float(thresholds["drawdown_pct_points_min"]),
    }
    return {"thresholds": thresholds, "deltas": deltas, "pf_saturated": pf_saturated, "flags": flags, "improved_count": sum(flags.values())}


def annotate_observer_trades(trades: list[dict[str, Any]], *, window_id: str, symbol: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for trade in trades:
        row = dict(trade)
        row["window_id"] = window_id
        row["symbol"] = symbol
        output.append(row)
    return output


def validate_archive_frame(frame: pd.DataFrame, *, expected_rows: int, interval_ms: int, label: str) -> tuple[int, int]:
    required = {"timestamp_ms", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise RuntimeError(f"ARCHIVE_COLUMNS_MISSING:{label}:{sorted(required - set(frame.columns))}")
    if len(frame) != expected_rows:
        raise RuntimeError(f"ARCHIVE_ROWS:{label}:{len(frame)}:{expected_rows}")
    timestamps = pd.to_numeric(frame["timestamp_ms"], errors="raise").astype("int64")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise RuntimeError(f"ARCHIVE_TIMESTAMP_ORDER:{label}")
    if len(timestamps) > 1 and not bool((timestamps.diff().dropna() == interval_ms).all()):
        raise RuntimeError(f"ARCHIVE_TIMESTAMP_GAP:{label}")
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or bool((numeric[["open", "high", "low", "close"]] <= 0).any().any()) or bool((numeric["volume"] < 0).any()):
        raise RuntimeError(f"ARCHIVE_NUMERIC_INVALID:{label}")
    if bool((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()) or bool((numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()):
        raise RuntimeError(f"ARCHIVE_OHLC_INVARIANT:{label}")
    return int(timestamps.iloc[0]), int(timestamps.iloc[-1])


def prepare_archive(args: argparse.Namespace) -> int:
    compute_root = Path(args.compute_root).resolve()
    historical_root = Path(args.historical_root).resolve()
    policy = read_json(Path(args.policy).resolve())
    exact = exact_module(compute_root)
    out = Path(args.out).resolve()
    archive_policy = policy["archive"]
    interval_ms = int(archive_policy["interval_ms"])
    total_bars = int(archive_policy["total_window_bars"])
    warmup = int(archive_policy["warmup_bars"])
    eval_bars = total_bars - warmup
    anchors = list(map(str, archive_policy["anchor_ends_utc"]))
    historical_roles = list(map(str, archive_policy["historical_roles"]))
    historical_anchor_count = len(historical_roles)
    if eval_bars <= 0 or len(anchors) != 12 or historical_anchor_count != 10:
        raise RuntimeError("ARCHIVE_POLICY_SHAPE_INVALID")
    source_manifest_path = historical_root / "manifest.json"
    source_manifest = read_json(source_manifest_path)
    if list(map(str, source_manifest.get("roles") or [])) != historical_roles:
        raise RuntimeError("HISTORICAL_ROLE_SET_MISMATCH")
    if list(map(str, source_manifest.get("anchors") or [])) != anchors[:historical_anchor_count]:
        raise RuntimeError("HISTORICAL_ANCHOR_SET_MISMATCH")
    rows: list[dict[str, Any]] = []
    intervals: list[tuple[int, int]] = []
    for window_id, (role, end_iso) in enumerate(zip(historical_roles, anchors[:historical_anchor_count]), start=1):
        expected_end_ms = int(pd.Timestamp(end_iso).timestamp() * 1000)
        for symbol in policy["symbols"]:
            source = historical_root / f"{role}-{symbol}.csv"
            if not source.is_file():
                raise RuntimeError(f"HISTORICAL_FILE_MISSING:{role}:{symbol}")
            frame = pd.read_csv(source)
            start_ms, end_ms = validate_archive_frame(frame, expected_rows=total_bars, interval_ms=interval_ms, label=f"{role}:{symbol}")
            if end_ms != expected_end_ms:
                raise RuntimeError(f"HISTORICAL_BOUNDARY_MISMATCH:{role}:{symbol}:{end_ms}:{expected_end_ms}")
            eval_start_ms = start_ms + warmup * interval_ms
            if symbol == policy["symbols"][0]:
                if any(not (eval_start_ms > previous_end or end_ms < previous_start) for previous_start, previous_end in intervals):
                    raise RuntimeError(f"ARCHIVE_EVALUATION_OVERLAP:{window_id}")
                intervals.append((eval_start_ms, end_ms))
            path = out / "market" / f"A{window_id:02d}-{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, path)
            rows.append({"window_id": f"A{window_id:02d}", "source_window_id": role, "symbol": symbol, "start_ms": start_ms, "evaluation_start_ms": eval_start_ms, "end_ms": end_ms, "rows": total_bars, "path": str(path.relative_to(out)), "sha256": sha256(path), "source_mode": "IMMUTABLE_ARTIFACT_RESTORE", "source_artifact_id": int(policy["historical_source"]["artifact_id"]), "source_run_id": int(policy["historical_source"]["run_id"]), "source_head_sha": str(policy["historical_source"]["head_sha"]), "state": "PASS"})
    for window_id, end_iso in enumerate(anchors[historical_anchor_count:], start=historical_anchor_count + 1):
        end_ms = int(pd.Timestamp(end_iso).timestamp() * 1000)
        start_ms = end_ms - (total_bars - 1) * interval_ms
        eval_start_ms = start_ms + warmup * interval_ms
        if any(not (eval_start_ms > previous_end or end_ms < previous_start) for previous_start, previous_end in intervals):
            raise RuntimeError(f"ARCHIVE_EVALUATION_OVERLAP:{window_id}")
        intervals.append((eval_start_ms, end_ms))
        for symbol in policy["symbols"]:
            frame, endpoint, request_count = exact.base._fetch_exact(symbol, start_ms=start_ms, end_ms=end_ms, expected_rows=total_bars)
            observed_start, observed_end = validate_archive_frame(frame, expected_rows=total_bars, interval_ms=interval_ms, label=f"A{window_id:02d}:{symbol}")
            if observed_start != start_ms or observed_end != end_ms:
                raise RuntimeError(f"RECENT_BOUNDARY_MISMATCH:A{window_id:02d}:{symbol}")
            path = out / "market" / f"A{window_id:02d}-{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
            rows.append({"window_id": f"A{window_id:02d}", "symbol": symbol, "start_ms": start_ms, "evaluation_start_ms": eval_start_ms, "end_ms": end_ms, "rows": total_bars, "path": str(path.relative_to(out)), "sha256": sha256(path), "endpoint": endpoint, "request_count": request_count, "source_mode": "BINGX_EXACT_INCREMENTAL", "state": "PASS"})
    manifest = {"schema_version": "3.1", "version": VERSION, "state": "PASS_EXPANDED_ARCHIVE", "window_count": len(anchors), "symbol_count": len(policy["symbols"]), "total_symbol_bars": len(anchors) * len(policy["symbols"]) * total_bars, "evaluation_symbol_bars": len(anchors) * len(policy["symbols"]) * eval_bars, "warmup_bars": warmup, "window_total_bars": total_bars, "evaluation_bars": eval_bars, "rows": rows, "historical_source_manifest_sha256": sha256(source_manifest_path), "historical_source": dict(policy["historical_source"]), "historical_window_count": historical_anchor_count, "incremental_window_count": len(anchors) - historical_anchor_count, "evaluation_periods_non_overlapping": True, **SAFETY}
    manifest["archive_sha256"] = stable_sha(manifest)
    write_json(out / "manifest.json", manifest)
    print(json.dumps({"state": manifest["state"], "total_symbol_bars": manifest["total_symbol_bars"], "evaluation_symbol_bars": manifest["evaluation_symbol_bars"], "files": len(rows)}, sort_keys=True))
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
    loss_epsilon = 1e-12
    profit_factor = sum(wins) / gross_loss if gross_loss > loss_epsilon else (999.0 if wins else 0.0)
    payoff_ratio = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and gross_loss > loss_epsilon else 0.0
    return {"trade_count": len(values), "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0, "net_return_pct_sum": sum(values), "net_profit_factor": profit_factor, "payoff_ratio": payoff_ratio, "max_drawdown_pct": dd}


def discovery_replay(args: argparse.Namespace) -> int:
    compute_root = Path(args.compute_root).resolve()
    archive_root = Path(args.archive_root).resolve()
    evidence_root = Path(args.evidence_root).resolve()
    plan = read_json(Path(args.plan).resolve())
    registry = read_json(Path(args.registry).resolve())
    policy = read_json(Path(args.policy).resolve())
    exact = install_exact_prepare(exact_module(compute_root))
    prior = load_module("s11_v3_prior", compute_root / "backend/tools/r7a4d_strategy11_gemini_22_prework_v1_1.py").v1
    canonical = exact.base._load_registry(compute_root)
    registry_map = {str(row["strategy_id"]): row for row in registry["rows"]}
    plan_map = {str(row["strategy_id"]): row for row in plan["rows"]}
    requested = [value for value in args.strategy_ids.split(",") if value]
    out = Path(args.out).resolve()
    manifest = read_json(archive_root / "manifest.json")
    archive_cache = load_archive_cache(archive_root, manifest, exact)
    batch_rows: list[dict[str, Any]] = []
    batch_started = time.monotonic()
    for strategy_id in requested:
        print(json.dumps({"event": "STRATEGY_START", "strategy_id": strategy_id, "elapsed_s": round(time.monotonic() - batch_started, 3)}, sort_keys=True), flush=True)
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
            window_stats: dict[str, Any] = {}
            observer_totals = {"long": [], "short": []}
            for repeat in ("A", "B"):
                repeat_trades: list[dict[str, Any]] = []
                wrapper.reset()
                for row in manifest["rows"]:
                    if row["symbol"] not in symbols:
                        continue
                    frame, features = archive_cache[(str(row["window_id"]), str(row["symbol"]))]
                    result = exact._replay(frame, features, wrapper, gate, exit_spec, surgery, warmup_bars=int(manifest["warmup_bars"]), history_bars=int(policy["archive"]["history_bars"]), cost_bps_per_side=float(policy["cost_bps_per_side"]))
                    for trade in result["trades"]:
                        trade = dict(trade)
                        trade["window_id"] = row["window_id"]
                        trade["symbol"] = row["symbol"]
                        repeat_trades.append(trade)
                    if repeat == "A":
                        window_stats.setdefault(row["window_id"], []).extend(result["trades"])
                        observer = replay_long_short(frame, wrapper, warmup_bars=int(manifest["warmup_bars"]), history_bars=int(policy["archive"]["history_bars"]), cost_bps_per_side=float(policy["cost_bps_per_side"]))
                        annotated_observer = annotate_observer_trades(observer["trades"], window_id=str(row["window_id"]), symbol=str(row["symbol"]))
                        observer_totals["long"].extend(value for value in annotated_observer if value["side"] == "long")
                        observer_totals["short"].extend(value for value in annotated_observer if value["side"] == "short")
                ledgers.append(sorted(repeat_trades, key=lambda value: (value.get("window_id"), value.get("entry_ts"), value.get("exit_ts"), value.get("symbol"))))
            parity = stable_sha(ledgers[0]) == stable_sha(ledgers[1]) and len({stable_sha(row) for row in ledgers[0]}) == len(ledgers[0])
            stats = combine_stats(ledgers[0])
            per_window = {window: combine_stats(rows) for window, rows in window_stats.items()}
            positive_windows = sum(value["net_return_pct_sum"] > 0 for value in per_window.values())
            observer_long = sorted(observer_totals["long"], key=lambda value: (value.get("window_id"), value.get("entry_ts"), value.get("exit_ts"), value.get("symbol")))
            observer_short = sorted(observer_totals["short"], key=lambda value: (value.get("window_id"), value.get("entry_ts"), value.get("exit_ts"), value.get("symbol")))
            summary = {"strategy_id": strategy_id, "variant_id": variant_id, "candidate_spec": variant, "candidate_spec_sha256": variant.get("candidate_spec_sha256") or stable_sha({key: value for key, value in variant.items() if key != "candidate_spec_sha256"}), **stats, "positive_window_count": positive_windows, "window_count": manifest["window_count"], "parity": {"state": "PASS" if parity else "HOLD", "replay_a_sha256": stable_sha(ledgers[0]), "replay_b_sha256": stable_sha(ledgers[1]), "duplicate_trade_count": len(ledgers[0]) - len({stable_sha(row) for row in ledgers[0]})}, "opportunity_diagnostics": wrapper.diagnostics(), "short_observer": {"long": combine_stats(observer_long), "short": combine_stats(observer_short), "observer_only": True, "chronological": True}, "canonical_mutated": False, **SAFETY}
            write_json(out / strategy_id / variant_id / "summary.json", summary)
            summaries.append(summary)
            print(json.dumps({"event": "VARIANT_COMPLETE", "strategy_id": strategy_id, "variant_id": variant_id, "trades": summary["trade_count"], "elapsed_s": round(time.monotonic() - batch_started, 3)}, sort_keys=True), flush=True)
        control = summaries[0]
        for row in summaries[1:]:
            row["deltas"] = {key: row[key] - control[key] for key in ("trade_count", "net_return_pct_sum", "net_profit_factor", "payoff_ratio", "max_drawdown_pct")}
            row["materiality"] = materiality_evidence(row, control, policy)
            row["research_state"] = "DISCOVERY_PASS_INTERNAL_OR_REGIME" if row["parity"]["state"] == "PASS" and row["trade_count"] >= int(policy["classification"]["archive_trade_count_min"]) and row["positive_window_count"] >= int(policy["classification"]["positive_windows_min"]) and row["materiality"]["improved_count"] >= int(policy["classification"]["materiality"]["material_metrics_min"]) and row["materiality"]["flags"]["net"] else "DISCOVERY_HOLD"
        strategy_payload = {"schema_version": "3.0", "version": VERSION, "strategy_id": strategy_id, "control": control, "variants": summaries[1:], "archive_sha256": manifest["archive_sha256"], "source_sha256": canonical_row["canonical_engine"]["source_sha256"], "next": "FRESH_W1_CONFIRMATION" if any(row.get("research_state", "").startswith("DISCOVERY_PASS") for row in summaries[1:]) else "WAIT_NEXT_AXIS", **SAFETY}
        strategy_payload["result_sha256"] = stable_sha(strategy_payload)
        write_json(out / strategy_id / "result.json", strategy_payload)
        batch_rows.append(strategy_payload)
    batch = {"schema_version": "3.0", "version": VERSION, "state": "PASS_V3_DISCOVERY_BATCH", "strategy_count": len(batch_rows), "rows": batch_rows, "archive_sha256": manifest["archive_sha256"], **SAFETY}
    batch["batch_sha256"] = stable_sha(batch)
    write_json(out / "batch.json", batch)
    print(json.dumps({"state": batch["state"], "strategies": len(batch_rows), "pass_candidates": sum(sum(str(v.get("research_state", "")).startswith("DISCOVERY_PASS") for v in row["variants"]) for row in batch_rows)}, sort_keys=True))
    return 0


def aggregate(args: argparse.Namespace) -> int:
    root = Path(args.batch_root).resolve()
    plan = read_json(Path(args.plan).resolve())
    policy = read_json(Path(args.policy).resolve())
    batches = [read_json(path) for path in sorted(root.glob("batch-*/batch.json"))]
    rows = [row for batch in batches for row in batch.get("rows", [])]
    expected = set(plan.get("active_strategy_ids", []))
    observed = {str(row["strategy_id"]) for row in rows}
    plan_digests = {(str(row["strategy_id"]), str(candidate_id)): str(row["candidate_specs"][candidate_id]["candidate_spec_sha256"]) for row in plan.get("rows", []) for candidate_id in row.get("candidate_ids", [])}
    blockers: list[str] = []
    if observed != expected:
        blockers.append(f"STRATEGY_SET_MISMATCH:{len(observed)}:{len(expected)}")
    for row in rows:
        if row.get("archive_sha256") != rows[0].get("archive_sha256"):
            blockers.append(f"ARCHIVE_SHA_MISMATCH:{row['strategy_id']}")
        for variant in row.get("variants", []):
            if variant.get("parity", {}).get("state") != "PASS":
                blockers.append(f"PARITY:{row['strategy_id']}:{variant.get('variant_id')}")
            expected_digest = plan_digests.get((str(row["strategy_id"]), str(variant.get("variant_id"))))
            if not expected_digest or variant.get("candidate_spec_sha256") != expected_digest:
                blockers.append(f"CANDIDATE_DIGEST:{row['strategy_id']}:{variant.get('variant_id')}")
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
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--compute-root", required=True); prepare.add_argument("--historical-root", required=True); prepare.add_argument("--policy", required=True); prepare.add_argument("--out", required=True)
    replay = sub.add_parser("replay")
    for name in ("compute_root", "archive_root", "evidence_root", "plan", "registry", "policy", "strategy_ids", "out"):
        replay.add_argument("--" + name.replace("_", "-"), required=True)
    agg = sub.add_parser("aggregate")
    agg.add_argument("--batch-root", required=True); agg.add_argument("--plan", required=True); agg.add_argument("--policy", required=True); agg.add_argument("--out", required=True)
    args = parser.parse_args()
    return prepare_archive(args) if args.mode == "prepare" else discovery_replay(args) if args.mode == "replay" else aggregate(args)


if __name__ == "__main__":
    raise SystemExit(main())
