from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import inspect
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_ENTRY_REGIME_RECONSTRUCTION_V1"
SCHEMA = "zel.grid_entry_regime.reconstruction.receipt.v1"
STRATEGY_ID = "grid_rebalance"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def event_id(row: Mapping[str, Any]) -> str:
    return str(row.get("event_id") or row.get("trade_id") or "").strip()


def pnl_r(row: Mapping[str, Any]) -> float:
    value = row.get("realized_R")
    if value is None:
        value = row.get("net_R")
    if value is None:
        value = row.get("pnl_r")
    return safe_float(value)


def window_id(row: Mapping[str, Any]) -> str:
    return str(row.get("window_id") or row.get("window") or "unknown")


def symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or "").upper()


def timestamp_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("exit_ts") or row.get("exit_time") or row.get("captured_at") or ""), event_id(row)


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [pnl_r(row) for row in sorted(rows, key=timestamp_key)]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(rows),
        "net_R": sum(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "profit_factor": sum(wins) / gross_loss if gross_loss > 0 else None,
        "max_drawdown_R": max_dd,
        "event_id_set_sha256": stable_sha(sorted(event_id(row) for row in rows)),
    }


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_grid_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "") == STRATEGY_ID:
                rows.append(row)
    return rows


def normalized_epoch_ns(pd_module: Any, value: Any) -> int | None:
    try:
        timestamp = pd_module.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return int(timestamp.value)
    except Exception:
        return None


def resolve_file_path(data_root: Path, file_row: Mapping[str, Any]) -> Path:
    for key in ("path", "file", "csv_path", "relative_path"):
        value = file_row.get(key)
        if isinstance(value, str) and value:
            path = Path(value)
            return path if path.is_absolute() else data_root / path
    raise RuntimeError(f"DATA_FILE_PATH_MISSING:{file_row.get('window_id')}:{file_row.get('symbol')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    report = json.loads((args.terminal_root / "report.json").read_text(encoding="utf-8"))
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")
    source_root = Path(source_root_raw)

    engine = load_module(args.engine, "zel_entry_regime_engine")
    engine.worker_init(source_root, args.data_root, "1m")
    producer = engine._WORKER_PRODUCER
    producer_path = Path(inspect.getsourcefile(producer) or getattr(producer, "__file__", ""))
    manifest = engine._WORKER_MANIFEST
    files = list(manifest.get("files") or []) if isinstance(manifest, Mapping) else []
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for file_row in files:
        if not isinstance(file_row, Mapping):
            continue
        key = (str(file_row.get("window_id") or file_row.get("window") or "unknown"), str(file_row.get("symbol") or "").upper())
        file_map[key] = file_row

    rows = read_grid_rows(args.terminal_root / "trades.jsonl.gz")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(window_id(row), symbol(row))].append(row)

    reconstructed: dict[str, str] = {}
    unmatched: list[dict[str, Any]] = []
    frame_count = 0
    for lane_key, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane_key)
        if file_row is None:
            unmatched.extend({"event_sha256": stable_sha(event_id(row)), "reason": "LANE_FILE_MISSING", "lane": lane_key} for row in lane_rows)
            continue
        frame_path = resolve_file_path(args.data_root, file_row)
        frame = engine.frame_from_csv(frame_path)
        frame_count += 1
        timestamp_index: dict[int, int] = {}
        for index, value in enumerate(frame["timestamp"].tolist()):
            epoch_ns = normalized_epoch_ns(engine.pd, value)
            if epoch_ns is not None:
                timestamp_index[epoch_ns] = index
        for row in lane_rows:
            entry_ts = row.get("entry_ts") or row.get("entry_time")
            epoch_ns = normalized_epoch_ns(engine.pd, entry_ts)
            index = timestamp_index.get(epoch_ns) if epoch_ns is not None else None
            if index is None:
                unmatched.append({"event_sha256": stable_sha(event_id(row)), "reason": "ENTRY_TIMESTAMP_NOT_FOUND", "lane": lane_key})
                continue
            current = frame.iloc[max(0, index - int(engine.FRAME_LIMIT) + 1): index + 1].copy()
            features = producer.feature_snapshot(current)
            regime = str(features.get("regime") or features.get("market_regime") or "missing") if isinstance(features, Mapping) else "missing"
            reconstructed[event_id(row)] = regime

    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_regime_window: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        regime = reconstructed.get(event_id(row), "missing")
        by_regime[regime].append(row)
        by_regime_window[(regime, window_id(row))].append(row)

    entry_neutral = by_regime.get("neutral", [])
    exit_neutral = [row for row in rows if str(row.get("regime") or row.get("market_regime") or "missing") == "neutral"]
    entry_ids = {event_id(row) for row in entry_neutral}
    exit_ids = {event_id(row) for row in exit_neutral}
    union = entry_ids | exit_ids
    intersection = entry_ids & exit_ids

    blockers: list[str] = []
    if len(rows) != 580:
        blockers.append("GRID_TRADE_COUNT_MISMATCH")
    if frame_count != len(grouped):
        blockers.append("USED_LANE_FRAME_COUNT_MISMATCH")
    if len(reconstructed) != len(rows):
        blockers.append("ENTRY_REGIME_RECONSTRUCTION_INCOMPLETE")
    if unmatched:
        blockers.append("ENTRY_TIMESTAMP_OR_LANE_MISMATCH")
    if by_regime.get("missing"):
        blockers.append("RECONSTRUCTED_REGIME_MISSING")

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_ENTRY_REGIME_RECONSTRUCTED" if not blockers else "HOLD_GRID_ENTRY_REGIME_RECONSTRUCTION_INCOMPLETE",
        "strategy_id": STRATEGY_ID,
        "engine_sha256": sha256_file(args.engine),
        "producer_path": str(producer_path.resolve()),
        "producer_sha256": sha256_file(producer_path),
        "source_root": str(source_root),
        "data_file_count": len(files),
        "used_lane_count": len(grouped),
        "loaded_frame_count": frame_count,
        "trade_count": len(rows),
        "reconstructed_count": len(reconstructed),
        "unmatched_count": len(unmatched),
        "unmatched_reason_counts": dict(Counter(row["reason"] for row in unmatched)),
        "reconstructed_regime_counts": dict(sorted((key, len(value)) for key, value in by_regime.items())),
        "reconstructed_regime_metrics": {key: metrics(value) for key, value in sorted(by_regime.items())},
        "reconstructed_regime_window_metrics": {f"{regime}|{window}": metrics(value) for (regime, window), value in sorted(by_regime_window.items())},
        "entry_neutral_metrics": metrics(entry_neutral),
        "exit_neutral_metrics": metrics(exit_neutral),
        "entry_exit_neutral_comparison": {
            "entry_neutral_count": len(entry_ids),
            "exit_neutral_count": len(exit_ids),
            "intersection_count": len(intersection),
            "entry_only_count": len(entry_ids - exit_ids),
            "exit_only_count": len(exit_ids - entry_ids),
            "jaccard": len(intersection) / len(union) if union else None,
            "entry_neutral_event_set_sha256": stable_sha(sorted(entry_ids)),
            "exit_neutral_event_set_sha256": stable_sha(sorted(exit_ids)),
            "intersection_event_set_sha256": stable_sha(sorted(intersection)),
        },
        "blockers": blockers,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "REVIEW_RECONSTRUCTED_ENTRY_NEUTRAL_EDGE" if not blockers else "RESOLVE_RECONSTRUCTION_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
