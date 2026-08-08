from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_HISTORICAL_OOS_LANE_CHECKPOINT_V1_REGISTRY_RESTORE_FIX"
_WORKER_ENGINE: Any = None


def load_module(path: Path, prefix: str) -> Any:
    name = f"{prefix}_{os.getpid()}_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def atomic_gzip_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    os.close(fd)
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)


def lane_key(strategy_id: str, row: Mapping[str, Any]) -> str:
    return "__".join((safe(strategy_id), safe(str(row["window_id"])), safe(str(row["symbol"])), safe(str(row["interval"]))))


def lane_path(root: Path, strategy_id: str, row: Mapping[str, Any]) -> Path:
    return root / safe(strategy_id) / f"{lane_key(strategy_id, row)}.json.gz"


def load_lane(path: Path, fingerprint: str, strategy_id: str, row: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != "zel.historical_oos_exact25_replay.lane_checkpoint.v1":
        return None
    if payload.get("input_fingerprint") != fingerprint:
        return None
    if payload.get("strategy_id") != strategy_id:
        return None
    if payload.get("source_sha256") != row.get("sha256"):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    if result.get("strategy_id") != strategy_id:
        return None
    if result.get("window_id") != str(row["window_id"]) or result.get("symbol") != str(row["symbol"]):
        return None
    return result


def save_lane(path: Path, fingerprint: str, strategy_id: str, row: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    atomic_gzip_json(path, {
        "schema_version": "zel.historical_oos_exact25_replay.lane_checkpoint.v1",
        "input_fingerprint": fingerprint,
        "strategy_id": strategy_id,
        "window_id": str(row["window_id"]),
        "symbol": str(row["symbol"]),
        "interval": str(row["interval"]),
        "source_sha256": row["sha256"],
        "result": dict(result),
    })


def restored_registry(engine: Any, producer: Any, source_root: Path, expected_count: int) -> dict[str, Any]:
    _, raw_registry = producer.load_registry(source_root)
    restore = getattr(engine, "_restore_structural_premium_registry", None)
    if not callable(restore):
        raise RuntimeError("STRUCTURAL_REGISTRY_RESTORE_HELPER_MISSING")
    registry = restore(source_root, raw_registry)
    if not isinstance(registry, dict):
        raise RuntimeError("STRUCTURAL_REGISTRY_RESTORE_NOT_DICT")
    if len(registry) != int(expected_count):
        raise RuntimeError(f"REGISTRY_COUNT:{len(registry)}!={expected_count}")
    return registry


def worker_init(engine_v1: str, source_root: str, data_root: str, interval: str) -> None:
    global _WORKER_ENGINE
    _WORKER_ENGINE = load_module(Path(engine_v1), "zel_lane_engine")
    _WORKER_ENGINE.init_worker(source_root, data_root, interval)


def worker_run(unit: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    if _WORKER_ENGINE is None:
        raise RuntimeError("LANE_WORKER_NOT_INITIALIZED")
    strategy_id, file_row = unit
    owner = _WORKER_ENGINE._WORKER_REGISTRY[strategy_id]
    data_root = _WORKER_ENGINE._WORKER_DATA_ROOT
    funding = _WORKER_ENGINE._WORKER_FUNDING
    frame = _WORKER_ENGINE.frame_from_csv(data_root / str(file_row["path"]))
    return _WORKER_ENGINE.replay_lane(
        strategy_id,
        owner,
        file_row,
        frame,
        funding.get(str(file_row["symbol"]), []),
    )


def self_test() -> None:
    assert safe("trend/rider") == "trend_rider"
    row = {"window_id": "W1", "symbol": "BTCUSDT", "interval": "1m"}
    assert lane_key("trend_rider", row) == "trend_rider__W1__BTCUSDT__1m"

    class FakeProducer:
        @staticmethod
        def load_registry(source_root: Path) -> tuple[None, dict[str, int]]:
            del source_root
            return None, {"raw_a": 1, "raw_b": 2}

    class FakeEngine:
        @staticmethod
        def _restore_structural_premium_registry(source_root: Path, raw_registry: dict[str, int]) -> dict[str, int]:
            del source_root
            return {"logical_a": raw_registry["raw_a"]}

    registry = restored_registry(FakeEngine(), FakeProducer(), Path("."), 1)
    assert registry == {"logical_a": 1}
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION, "restored_registry_contract": True}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-v1")
    parser.add_argument("--engine-v2")
    parser.add_argument("--source-root")
    parser.add_argument("--data-root")
    parser.add_argument("--interval", choices=("1m", "15m"))
    parser.add_argument("--output-dir")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.engine_v1, args.engine_v2, args.source_root, args.data_root, args.interval, args.output_dir)):
        parser.error("engine-v1, engine-v2, source-root, data-root, interval and output-dir are required")

    engine_v1 = Path(args.engine_v1).resolve()
    engine_v2 = Path(args.engine_v2).resolve()
    source_root = Path(args.source_root).resolve()
    data_root = Path(args.data_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    lane_root = output_dir / "lane_checkpoints"
    lane_root.mkdir(parents=True, exist_ok=True)

    base = load_module(engine_v2, "zel_lane_base")
    engine = base.load_engine(engine_v1)
    manifest, _ = engine.validate_data_manifest(data_root, args.interval)
    producer = engine.import_producer(source_root)
    registry = restored_registry(engine, producer, source_root, int(base.EXPECTED_STRATEGY_COUNT))
    fingerprint, _ = base.input_fingerprint(engine, engine_v1, source_root, data_root, args.interval, registry)

    files = [
        dict(row) for row in manifest.get("files", [])
        if isinstance(row, dict) and row.get("kind") == "market" and row.get("interval") == args.interval
    ]
    files = sorted(files, key=lambda row: (str(row["window_id"]), str(row["symbol"])))
    if not files:
        raise RuntimeError("NO_LANES")

    strategy_results: dict[str, dict[str, Any]] = {}
    lane_results: dict[tuple[str, str, str], dict[str, Any]] = {}
    missing_strategies: list[str] = []

    for strategy_id in sorted(registry):
        spath = base.checkpoint_path(output_dir / "checkpoints", strategy_id)
        result = base.load_checkpoint(spath, fingerprint, strategy_id) if spath.exists() else None
        if result is not None:
            strategy_results[strategy_id] = result
            continue
        missing_strategies.append(strategy_id)
        for row in files:
            lpath = lane_path(lane_root, strategy_id, row)
            loaded = load_lane(lpath, fingerprint, strategy_id, row) if lpath.exists() else None
            if loaded is not None:
                lane_results[(strategy_id, str(row["window_id"]), str(row["symbol"]))] = loaded

    pending: list[tuple[str, dict[str, Any]]] = []
    for strategy_id in missing_strategies:
        for row in files:
            key = (strategy_id, str(row["window_id"]), str(row["symbol"]))
            if key not in lane_results:
                pending.append((strategy_id, row))

    total_units = len(registry) * len(files)
    completed_units = len(strategy_results) * len(files) + len(lane_results)
    print(json.dumps({
        "state": "LANE_RESUME_START",
        "strategy_checkpoints": len(strategy_results),
        "missing_strategies": missing_strategies,
        "lane_checkpoints": len(lane_results),
        "completed_units": completed_units,
        "total_units": total_units,
        "pending_units": len(pending),
        "workers": max(1, min(int(args.workers), 8)),
    }, sort_keys=True), flush=True)

    failures: list[dict[str, Any]] = []
    if pending:
        workers = max(1, min(int(args.workers), 8))
        context = mp.get_context("fork")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=worker_init,
            initargs=(str(engine_v1), str(source_root), str(data_root), args.interval),
        ) as executor:
            futures = {executor.submit(worker_run, unit): unit for unit in pending}
            for future in as_completed(futures):
                strategy_id, row = futures[future]
                key = (strategy_id, str(row["window_id"]), str(row["symbol"]))
                try:
                    result = future.result()
                    save_lane(lane_path(lane_root, strategy_id, row), fingerprint, strategy_id, row, result)
                    lane_results[key] = result
                    print(json.dumps({
                        "state": "LANE_DONE_CHECKPOINTED",
                        "strategy_id": strategy_id,
                        "window_id": row["window_id"],
                        "symbol": row["symbol"],
                    }, sort_keys=True), flush=True)
                except Exception as exc:
                    failure = {
                        "strategy_id": strategy_id,
                        "window_id": str(row["window_id"]),
                        "symbol": str(row["symbol"]),
                        "error": f"{type(exc).__name__}:{exc}",
                    }
                    failures.append(failure)
                    print(json.dumps({"state": "LANE_FAILED", **failure}, sort_keys=True), flush=True)

    for strategy_id in missing_strategies:
        lanes = []
        complete = True
        for row in files:
            key = (strategy_id, str(row["window_id"]), str(row["symbol"]))
            result = lane_results.get(key)
            if result is None:
                complete = False
                break
            lanes.append(result)
        if not complete:
            continue
        owner = registry[strategy_id]
        combined = {
            "strategy_id": strategy_id,
            "owner_sha256": str(getattr(owner, "owner_sha256", "")),
            "lanes": lanes,
        }
        base.save_checkpoint(base.checkpoint_path(output_dir / "checkpoints", strategy_id), fingerprint, combined)
        strategy_results[strategy_id] = combined
        print(json.dumps({"state": "STRATEGY_DONE_FROM_LANES", "strategy_id": strategy_id, "lane_count": len(lanes)}, sort_keys=True), flush=True)

    completed = len(strategy_results)
    state = "PASS" if completed == len(registry) and not failures else "HOLD"
    print(json.dumps({
        "state": state,
        "version": VERSION,
        "strategy_count_expected": len(registry),
        "strategy_count_completed": completed,
        "failures": failures,
        "next": "RUN_BASE_V2_AGGREGATION" if state == "PASS" else "RESUME_LANES",
    }, sort_keys=True), flush=True)
    return 0 if state == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
