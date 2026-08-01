from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_HISTORICAL_OOS_EXACT25_REPLAY_V2"
EXPECTED_STRATEGY_COUNT = 25
_WORKER_ENGINE: Any = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def atomic_gzip_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    os.close(fd)
    try:
        with gzip.open(tmp_name, "wt", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, allow_nan=False)
            handle.write("\n")
        with open(tmp_name, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def atomic_scoreboard(engine: Any, path: Path, scorecards: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".csv", dir=str(path.parent))
    os.close(fd)
    try:
        engine.write_scoreboard(Path(tmp_name), scorecards)
        with open(tmp_name, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def atomic_trades(path: Path, rows: Sequence[Mapping[str, Any]], engine: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".gz", dir=str(path.parent))
    os.close(fd)
    try:
        ordered = sorted(
            rows,
            key=lambda item: (engine.parse_epoch(item.get("exit_ts")) or 0.0, str(item.get("event_id"))),
        )
        with gzip.open(tmp_name, "wt", encoding="utf-8") as handle:
            for row in ordered:
                handle.write(json.dumps(dict(row), sort_keys=True, allow_nan=False) + "\n")
        with open(tmp_name, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def load_engine(path: Path) -> Any:
    name = f"zel_historical_oos_exact25_replay_v1_{os.getpid()}_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"ENGINE_IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def worker_init(engine_path: str, source_root: str, data_root: str, interval: str) -> None:
    global _WORKER_ENGINE
    _WORKER_ENGINE = load_engine(Path(engine_path))
    _WORKER_ENGINE.init_worker(source_root, data_root, interval)


def worker_run(strategy_id: str) -> dict[str, Any]:
    if _WORKER_ENGINE is None:
        raise RuntimeError("V2_WORKER_NOT_INITIALIZED")
    return _WORKER_ENGINE.replay_strategy(strategy_id)


def input_fingerprint(
    engine: Any,
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    interval: str,
    registry: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    strategy_paths = [str(getattr(owner, "owner_path", "")) for owner in registry.values()]
    if any(not path for path in strategy_paths):
        raise RuntimeError("OWNER_PATH_MISSING")
    payload = {
        "engine_v1_sha256": sha256_path(engine_path),
        "data_manifest_sha256": sha256_path(data_root / "manifest.json"),
        "strategy_tree_sha256": engine.tree_hash(source_root, strategy_paths),
        "producer_sha256": sha256_path(source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"),
        "owner_manifest_sha256": sha256_path(source_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"),
        "interval": interval,
        "expected_strategy_count": EXPECTED_STRATEGY_COUNT,
        "warmup_bars": engine.WARMUP_BARS,
        "frame_limit": engine.FRAME_LIMIT,
        "risk_unit_usdt": engine.RISK_UNIT_USDT,
        "fee_rate": engine.FEE_RATE,
        "slippage_bps": engine.SLIPPAGE_BPS,
        "max_hold_min": engine.MAX_HOLD_MIN,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), payload


def checkpoint_path(root: Path, strategy_id: str) -> Path:
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in strategy_id)
    return root / f"{safe}.json.gz"


def load_checkpoint(path: Path, fingerprint: str, strategy_id: str) -> dict[str, Any] | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != "zel.historical_oos_exact25_replay.checkpoint.v2":
        return None
    if payload.get("input_fingerprint") != fingerprint:
        return None
    result = payload.get("result")
    if not isinstance(result, dict) or result.get("strategy_id") != strategy_id:
        return None
    return result


def save_checkpoint(path: Path, fingerprint: str, result: Mapping[str, Any]) -> None:
    atomic_gzip_json(path, {
        "schema_version": "zel.historical_oos_exact25_replay.checkpoint.v2",
        "generated_at": now_iso(),
        "input_fingerprint": fingerprint,
        "strategy_id": result["strategy_id"],
        "result": dict(result),
    })


def quarantine_invalid(path: Path) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(path.name + f".invalid.{stamp}")
    path.replace(target)


def eta_minutes(started_monotonic: float, completed: int, total: int) -> float | None:
    if completed < 3 or completed >= total:
        return 0.0 if completed >= total else None
    elapsed = max(time.monotonic() - started_monotonic, 0.001)
    return round((elapsed / completed) * (total - completed) / 60.0, 3)


def write_progress(
    path: Path,
    run_id: str,
    fingerprint: str,
    started_at: str,
    started_monotonic: float,
    total: int,
    completed_ids: Sequence[str],
    failed: Sequence[Mapping[str, Any]],
    state: str,
    current_unit: str | None,
) -> None:
    completed = len(completed_ids)
    atomic_json(path, {
        "schema_version": "zel.progress.heartbeat.v2",
        "pipeline_id": "DATA_B_EXACT25",
        "stage_id": "HISTORICAL_OOS_1M_15M_REPLAY",
        "run_id": run_id,
        "source_sha": fingerprint,
        "started_at": started_at,
        "heartbeat_at": now_iso(),
        "unit_kind": "strategy",
        "total_units": total,
        "completed_units": completed,
        "completed_unit_ids": sorted(completed_ids),
        "current_unit": current_unit,
        "error_count": len(failed),
        "failures": list(failed),
        "progress_pct": round(completed / total * 100.0, 3) if total else 0.0,
        "eta_min": eta_minutes(started_monotonic, completed, total),
        "state": state,
        "action": "hold",
        "next": "TERMINAL_ARTIFACT_VALIDATION" if completed == total and not failed else "CONTINUE_REPLAY",
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    })


def artifact_manifest(output_dir: Path, names: Sequence[str], fingerprint: str) -> dict[str, Any]:
    files = []
    for name in names:
        path = output_dir / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"TERMINAL_ARTIFACT_MISSING:{path}")
        files.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256_path(path)})
    return {
        "schema_version": "zel.historical_oos_exact25_replay.artifact_manifest.v2",
        "generated_at": now_iso(),
        "input_fingerprint": fingerprint,
        "files": files,
        "terminal_complete": True,
        "atomic_publication": True,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        atomic_json(root / "a.json", {"x": 1})
        assert json.loads((root / "a.json").read_text())["x"] == 1
        atomic_gzip_json(root / "checkpoint.json.gz", {"x": [1, 2, 3]})
        with gzip.open(root / "checkpoint.json.gz", "rt", encoding="utf-8") as handle:
            assert json.load(handle)["x"] == [1, 2, 3]
        write_progress(root / "progress.json", "self", "sha", now_iso(), time.monotonic(), 5, ["a", "b", "c"], [], "RUNNING", "c")
        progress = json.loads((root / "progress.json").read_text())
        assert progress["progress_pct"] == 60.0
        assert progress["eta_min"] is not None
        manifest = artifact_manifest(root, ["a.json", "checkpoint.json.gz", "progress.json"], "sha")
        assert len(manifest["files"]) == 3
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-v1", default=str(Path(__file__).with_name("zel_historical_oos_exact25_replay_v1.py")))
    parser.add_argument("--source-root")
    parser.add_argument("--data-root")
    parser.add_argument("--interval", choices=("1m", "15m"))
    parser.add_argument("--output-dir")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not all((args.source_root, args.data_root, args.interval, args.output_dir)):
        parser.error("source-root, data-root, interval and output-dir are required")

    engine_path = Path(args.engine_v1).resolve()
    source_root = Path(args.source_root).resolve()
    data_root = Path(args.data_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_root = output_dir / "checkpoints"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.json"
    workers = max(1, min(int(args.workers), 8))
    engine = load_engine(engine_path)

    manifest, files = engine.validate_data_manifest(data_root, args.interval)
    producer = engine.import_producer(source_root)
    _, registry = producer.load_registry(source_root)
    if len(registry) != EXPECTED_STRATEGY_COUNT:
        raise RuntimeError(f"REGISTRY_COUNT:{len(registry)}")

    fingerprint, fingerprint_inputs = input_fingerprint(engine, engine_path, source_root, data_root, args.interval, registry)
    strategy_paths = [str(getattr(owner, "owner_path", "")) for owner in registry.values()]
    source_tree_before = engine.tree_hash(source_root, strategy_paths)
    producer_before = sha256_path(source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py")
    owner_manifest_before = sha256_path(source_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json")
    canonical_producer_before = engine.service_snapshot(engine.CANONICAL_PRODUCER_UNIT)
    canonical_writer_before = engine.service_snapshot(engine.CANONICAL_WRITER_UNIT)
    formal_before = engine.formal_prefix_snapshot(engine.FORMAL_LEDGER)
    if canonical_producer_before["active_state"] != "active" or canonical_writer_before["active_state"] != "active":
        raise RuntimeError("CANONICAL_RUNTIME_NOT_ACTIVE")

    run_id = os.environ.get("GITHUB_RUN_ID") or f"local-{os.getpid()}"
    started_at = now_iso()
    started_monotonic = time.monotonic()
    raw_by_strategy: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    invalid_checkpoint_count = 0

    for strategy_id in sorted(registry):
        path = checkpoint_path(checkpoint_root, strategy_id)
        if args.no_resume or not path.exists():
            continue
        result = load_checkpoint(path, fingerprint, strategy_id)
        if result is None:
            quarantine_invalid(path)
            invalid_checkpoint_count += 1
        else:
            raw_by_strategy[strategy_id] = result

    write_progress(
        progress_path, run_id, fingerprint, started_at, started_monotonic,
        EXPECTED_STRATEGY_COUNT, list(raw_by_strategy), failures, "RUNNING", None,
    )

    pending = [strategy_id for strategy_id in sorted(registry) if strategy_id not in raw_by_strategy]
    if pending:
        context = mp.get_context("fork")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=worker_init,
            initargs=(str(engine_path), str(source_root), str(data_root), args.interval),
        ) as executor:
            futures = {executor.submit(worker_run, strategy_id): strategy_id for strategy_id in pending}
            for future in as_completed(futures):
                strategy_id = futures[future]
                try:
                    result = future.result()
                    save_checkpoint(checkpoint_path(checkpoint_root, strategy_id), fingerprint, result)
                    raw_by_strategy[strategy_id] = result
                    print(json.dumps({"strategy_id": strategy_id, "state": "DONE_CHECKPOINTED"}), flush=True)
                except Exception as exc:
                    failure = {"strategy_id": strategy_id, "error": f"{type(exc).__name__}:{exc}"}
                    failures.append(failure)
                    print(json.dumps({"strategy_id": strategy_id, "state": "FAILED", "error": failure["error"]}), flush=True)
                write_progress(
                    progress_path, run_id, fingerprint, started_at, started_monotonic,
                    EXPECTED_STRATEGY_COUNT, list(raw_by_strategy), failures, "RUNNING", strategy_id,
                )

    scorecards: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for result in sorted(raw_by_strategy.values(), key=lambda row: row["strategy_id"]):
        card, rows = engine.aggregate_strategy(result)
        scorecards.append(card)
        all_rows.extend(rows)

    canonical_producer_after = engine.service_snapshot(engine.CANONICAL_PRODUCER_UNIT)
    canonical_writer_after = engine.service_snapshot(engine.CANONICAL_WRITER_UNIT)
    formal_after = engine.verify_formal_prefix(formal_before, engine.FORMAL_LEDGER)
    source_tree_after = engine.tree_hash(source_root, strategy_paths)
    producer_after = sha256_path(source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py")
    owner_manifest_after = sha256_path(source_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json")

    runtime_safe = (
        canonical_producer_after["active_state"] == "active"
        and canonical_writer_after["active_state"] == "active"
        and canonical_producer_before["main_pid"] == canonical_producer_after["main_pid"]
        and canonical_writer_before["main_pid"] == canonical_writer_after["main_pid"]
        and formal_after["prefix_unchanged"] is True
        and source_tree_before == source_tree_after
        and producer_before == producer_after
        and owner_manifest_before == owner_manifest_after
    )
    infrastructure_complete = len(raw_by_strategy) == EXPECTED_STRATEGY_COUNT and not failures
    state = "PASS" if runtime_safe and infrastructure_complete else "HOLD"
    verdict = "HISTORICAL_OOS_EXACT25_REPLAY_COMPLETE" if state == "PASS" else "HISTORICAL_OOS_EXACT25_REPLAY_HOLD"

    scorecards = sorted(
        scorecards,
        key=lambda card: (
            -(engine.safe_float(card["closed_metrics_ex_funding"].get("expectancy_R"), -1e9) or -1e9),
            -int(card["closed_metrics_ex_funding"].get("sample_count") or 0),
            str(card["strategy_id"]),
        ),
    )
    fingerprint_counts: dict[str, int] = defaultdict(int)
    tier_counts: dict[str, int] = defaultdict(int)
    for card in scorecards:
        fingerprint_counts[str(card["failure_fingerprint"])] += 1
        tier_counts[str(card["claim_tier"])] += 1

    report = {
        "schema_version": "zel.historical_oos_exact25_replay.result.v2",
        "version": VERSION,
        "state": state,
        "verdict": verdict,
        "generated_at": now_iso(),
        "elapsed_sec": time.monotonic() - started_monotonic,
        "interval": args.interval,
        "workers": workers,
        "checkpoint": {
            "resume_enabled": not args.no_resume,
            "input_fingerprint": fingerprint,
            "input_fingerprint_fields": fingerprint_inputs,
            "valid_checkpoint_count": len(raw_by_strategy),
            "invalid_checkpoint_count": invalid_checkpoint_count,
            "strategy_level_atomic_checkpoint": True,
        },
        "data": {
            "root": str(data_root),
            "manifest_sha256": sha256_path(data_root / "manifest.json"),
            "authority_end": manifest.get("authority_end"),
            "symbol_count": len(manifest.get("symbols") or []),
            "symbols": manifest.get("symbols"),
            "window_count": len({str(row["window_id"]) for row in files}),
            "file_count": len(files),
            "market_row_count": sum(int(row["rows"]) for row in files),
            "forward_overlap_count": 0,
            "final_holdout_accessed": False,
        },
        "source": {
            "root": str(source_root),
            "strategy_count": len(registry),
            "strategy_tree_sha256_before": source_tree_before,
            "strategy_tree_sha256_after": source_tree_after,
            "strategy_tree_unchanged": source_tree_before == source_tree_after,
            "producer_sha256_before": producer_before,
            "producer_sha256_after": producer_after,
            "producer_unchanged": producer_before == producer_after,
            "manifest_sha256_before": owner_manifest_before,
            "manifest_sha256_after": owner_manifest_after,
            "manifest_unchanged": owner_manifest_before == owner_manifest_after,
        },
        "canonical_runtime": {
            "producer_before": canonical_producer_before,
            "producer_after": canonical_producer_after,
            "writer_before": canonical_writer_before,
            "writer_after": canonical_writer_after,
            "producer_pid_unchanged": canonical_producer_before["main_pid"] == canonical_producer_after["main_pid"],
            "writer_pid_unchanged": canonical_writer_before["main_pid"] == canonical_writer_after["main_pid"],
            "formal_ledger": formal_after,
        },
        "replay": {
            "strategy_count_expected": EXPECTED_STRATEGY_COUNT,
            "strategy_count_completed": len(scorecards),
            "strategy_failure_count": len(failures),
            "strategy_failures": failures,
            "closed_trade_count": len(all_rows),
            "strategy_call_count": sum(int(card["strategy_call_count"]) for card in scorecards),
            "signal_count": sum(int(card["signal_count"]) for card in scorecards),
            "valid_entry_count": sum(int(card["valid_entry_count"]) for card in scorecards),
            "open_count": sum(int(card["open_count"]) for card in scorecards),
            "censored_open_at_window_end": sum(int(card["censored_open_at_window_end"]) for card in scorecards),
            "error_count": sum(int(card["error_count"]) for card in scorecards),
            "claim_tier_counts": dict(sorted(tier_counts.items())),
            "failure_fingerprint_counts": dict(sorted(fingerprint_counts.items())),
            "aggregate_metrics_ex_funding": engine.metrics(all_rows, "realized_R"),
            "aggregate_metrics_including_funding_estimate": engine.metrics(all_rows, "realized_R_including_funding_estimate"),
            "funding_model": "ENTRY_NOTIONAL_STATIC_ESTIMATE_NON_PROMOTABLE",
            "same_bar_collision_policy": "STOP_FIRST",
            "window_end_open_policy": "CENSORED_EXCLUDED_FROM_ECONOMIC_METRICS",
            "max_hold_min": engine.MAX_HOLD_MIN,
            "fee_rate_per_side": engine.FEE_RATE,
            "slippage_bps_per_side": engine.SLIPPAGE_BPS,
        },
        "scorecards": scorecards,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "paper_enabled": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }

    atomic_scoreboard(engine, output_dir / "scoreboard.csv", scorecards)
    atomic_trades(output_dir / "trades.jsonl.gz", all_rows, engine)
    atomic_json(output_dir / "report.json", report)
    atomic_json(output_dir / "summary.json", {
        "state": state,
        "verdict": verdict,
        "interval": args.interval,
        "closed_trade_count": len(all_rows),
        "strategy_count_completed": len(scorecards),
        "strategy_failure_count": len(failures),
        "error_count": report["replay"]["error_count"],
        "claim_tier_counts": report["replay"]["claim_tier_counts"],
        "failure_fingerprint_counts": report["replay"]["failure_fingerprint_counts"],
        "canonical_runtime_safe": runtime_safe,
        "checkpoint_resume_enabled": not args.no_resume,
        "research_only": True,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    })
    manifest_payload = artifact_manifest(
        output_dir,
        ["report.json", "summary.json", "scoreboard.csv", "trades.jsonl.gz", "progress.json"],
        fingerprint,
    )
    atomic_json(output_dir / "artifact_manifest.json", manifest_payload)
    atomic_json(output_dir / "terminal_receipt.json", {
        "schema_version": "zel.historical_oos_exact25_replay.terminal_receipt.v2",
        "generated_at": now_iso(),
        "state": state,
        "verdict": verdict,
        "interval": args.interval,
        "input_fingerprint": fingerprint,
        "artifact_manifest_sha256": sha256_path(output_dir / "artifact_manifest.json"),
        "artifact_count": len(manifest_payload["files"]),
        "strategy_count_completed": len(scorecards),
        "strategy_failure_count": len(failures),
        "runtime_safe": runtime_safe,
        "atomic_publication": True,
        "resume_capable": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    })
    write_progress(
        progress_path, run_id, fingerprint, started_at, started_monotonic,
        EXPECTED_STRATEGY_COUNT, list(raw_by_strategy), failures, state, None,
    )
    print(json.dumps(json.loads((output_dir / "terminal_receipt.json").read_text()), sort_keys=True))
    return 0 if state == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
