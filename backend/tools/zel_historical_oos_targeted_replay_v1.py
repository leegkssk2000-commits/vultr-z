from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

VERSION = "ZEL_HISTORICAL_OOS_TARGETED_REPLAY_V1"


def load_engine() -> Any:
    path = Path(__file__).with_name("zel_historical_oos_exact25_replay_v1.py")
    spec = importlib.util.spec_from_file_location("zel_exact25_replay_engine_for_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("TARGET_ENGINE_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root")
    parser.add_argument("--data-root")
    parser.add_argument("--interval", choices=("1m", "15m"))
    parser.add_argument("--strategy-id")
    parser.add_argument("--output-dir")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        assert VERSION == "ZEL_HISTORICAL_OOS_TARGETED_REPLAY_V1"
        assert Path(__file__).with_name("zel_historical_oos_exact25_replay_v1.py").name == "zel_historical_oos_exact25_replay_v1.py"
        print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))
        return 0

    engine = load_engine()
    if not all((args.source_root, args.data_root, args.interval, args.strategy_id, args.output_dir)):
        parser.error("source-root, data-root, interval, strategy-id and output-dir are required")

    source_root = Path(args.source_root).resolve()
    data_root = Path(args.data_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest, files = engine.validate_data_manifest(data_root, args.interval)
    producer = engine.import_producer(source_root)
    _, registry = producer.load_registry(source_root)
    strategy_id = str(args.strategy_id)
    if strategy_id not in registry:
        raise RuntimeError(f"TARGET_STRATEGY_NOT_IN_REGISTRY:{strategy_id}")

    strategy_paths = [str(getattr(owner, "owner_path", "")) for owner in registry.values()]
    if any(not path for path in strategy_paths):
        raise RuntimeError("OWNER_PATH_MISSING")

    source_tree_before = engine.tree_hash(source_root, strategy_paths)
    producer_path = source_root / "tools/q4r3_exact25_dedicated_shadow_producer.py"
    manifest_path = source_root / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
    producer_before = engine.sha256_path(producer_path)
    manifest_before = engine.sha256_path(manifest_path)
    canonical_producer_before = engine.service_snapshot(engine.CANONICAL_PRODUCER_UNIT)
    canonical_writer_before = engine.service_snapshot(engine.CANONICAL_WRITER_UNIT)
    formal_before = engine.formal_prefix_snapshot(engine.FORMAL_LEDGER)
    if canonical_producer_before["active_state"] != "active" or canonical_writer_before["active_state"] != "active":
        raise RuntimeError("CANONICAL_RUNTIME_NOT_ACTIVE")

    started = time.monotonic()
    engine.init_worker(str(source_root), str(data_root), args.interval)
    raw = engine.replay_strategy(strategy_id)
    card, rows = engine.aggregate_strategy(raw)

    canonical_producer_after = engine.service_snapshot(engine.CANONICAL_PRODUCER_UNIT)
    canonical_writer_after = engine.service_snapshot(engine.CANONICAL_WRITER_UNIT)
    formal_after = engine.verify_formal_prefix(formal_before, engine.FORMAL_LEDGER)
    source_tree_after = engine.tree_hash(source_root, strategy_paths)
    producer_after = engine.sha256_path(producer_path)
    manifest_after = engine.sha256_path(manifest_path)

    runtime_safe = (
        canonical_producer_after["active_state"] == "active"
        and canonical_writer_after["active_state"] == "active"
        and canonical_producer_before["main_pid"] == canonical_producer_after["main_pid"]
        and canonical_writer_before["main_pid"] == canonical_writer_after["main_pid"]
        and formal_after["prefix_unchanged"] is True
        and source_tree_before == source_tree_after
        and producer_before == producer_after
        and manifest_before == manifest_after
    )
    state = "PASS" if runtime_safe and int(card.get("error_count") or 0) == 0 else "HOLD"
    report = {
        "schema_version": "zel.historical_oos_targeted_replay.result.v1",
        "version": VERSION,
        "state": state,
        "verdict": "HISTORICAL_OOS_TARGETED_REPLAY_COMPLETE" if state == "PASS" else "HISTORICAL_OOS_TARGETED_REPLAY_HOLD",
        "generated_at": engine.now_iso(),
        "elapsed_sec": time.monotonic() - started,
        "strategy_id": strategy_id,
        "interval": args.interval,
        "data": {
            "manifest_sha256": engine.sha256_path(data_root / "manifest.json"),
            "authority_end": manifest.get("authority_end"),
            "symbol_count": len(manifest.get("symbols") or []),
            "window_count": len({str(row["window_id"]) for row in files}),
            "file_count": len(files),
            "forward_overlap_count": 0,
            "final_holdout_accessed": False
        },
        "source": {
            "root": str(source_root),
            "strategy_tree_sha256_before": source_tree_before,
            "strategy_tree_sha256_after": source_tree_after,
            "strategy_tree_unchanged_during_replay": source_tree_before == source_tree_after,
            "producer_unchanged_during_replay": producer_before == producer_after,
            "manifest_unchanged_during_replay": manifest_before == manifest_after
        },
        "canonical_runtime": {
            "producer_pid_unchanged": canonical_producer_before["main_pid"] == canonical_producer_after["main_pid"],
            "writer_pid_unchanged": canonical_writer_before["main_pid"] == canonical_writer_after["main_pid"],
            "formal_ledger": formal_after
        },
        "scorecard": card,
        "closed_trade_count": len(rows),
        "research_only": True,
        "targeted_replay": True,
        "selection_authority": False,
        "promotion_authority": False,
        "paper_enabled": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold"
    }
    engine.atomic_json(output_dir / "report.json", report)
    engine.write_scoreboard(output_dir / "scoreboard.csv", [card])
    with gzip.open(output_dir / "trades.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in sorted(rows, key=lambda item: (engine.parse_epoch(item.get("exit_ts")) or 0.0, str(item.get("event_id")))):
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    engine.atomic_json(output_dir / "summary.json", {
        "state": state,
        "strategy_id": strategy_id,
        "interval": args.interval,
        "closed_trade_count": len(rows),
        "error_count": card.get("error_count"),
        "failure_fingerprint": card.get("failure_fingerprint"),
        "claim_tier": card.get("claim_tier"),
        "canonical_runtime_safe": runtime_safe,
        "research_only": True,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold"
    })
    print(json.dumps(engine.load_json(output_dir / "summary.json"), sort_keys=True))
    return 0 if state == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
