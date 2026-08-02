from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_ENTRY_REGIME_RECONSTRUCTION_V2"
SCHEMA = "zel.grid_entry_regime.reconstruction.receipt.v2"
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


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event_id(row: Mapping[str, Any]) -> str:
    return str(row.get("event_id") or row.get("trade_id") or "").strip()


def pnl_r(row: Mapping[str, Any]) -> float:
    for key in ("realized_R", "net_R", "pnl_r"):
        if row.get(key) is not None:
            return safe_float(row.get(key))
    return 0.0


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


def normalized_ns(pd_module: Any, value: Any) -> int | None:
    try:
        timestamp = pd_module.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return int(timestamp.value)
    except Exception:
        return None


def resolve_file(data_root: Path, row: Mapping[str, Any]) -> Path:
    for key in ("path", "file", "csv_path", "relative_path"):
        value = row.get(key)
        if isinstance(value, str) and value:
            path = Path(value)
            return path if path.is_absolute() else data_root / path
    raise RuntimeError("DATA_FILE_PATH_MISSING")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--context-owner", type=Path, default=Path("/home/z/z/tools/q4r3_exact25_market_context_collector.py"))
    parser.add_argument("--regime-owner", type=Path, default=Path("/home/z/z/tools/q4r3_exact25_preentry_method_context_capture.py"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    engine = load_module(args.engine, "zel_entry_regime_engine_v2")
    context_owner = load_module(args.context_owner, "zel_market_context_owner_v2")
    regime_owner = load_module(args.regime_owner, "zel_regime_owner_v2")
    manifest_result = engine.validate_data_manifest(args.data_root, "1m")
    manifest = manifest_result[0] if isinstance(manifest_result, tuple) else manifest_result
    files = list(manifest.get("files") or []) if isinstance(manifest, Mapping) else []
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for file_row in files:
        if isinstance(file_row, Mapping):
            key = (str(file_row.get("window_id") or file_row.get("window") or "unknown"), str(file_row.get("symbol") or "").upper())
            file_map[key] = file_row

    rows = read_grid_rows(args.terminal_root / "trades.jsonl.gz")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(window_id(row), symbol(row))].append(row)

    reconstructed: dict[str, str] = {}
    unmatched: list[str] = []
    loaded_lane_count = 0
    for lane, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane)
        if file_row is None:
            unmatched.extend("LANE_FILE_MISSING" for _ in lane_rows)
            continue
        frame = engine.frame_from_csv(resolve_file(args.data_root, file_row))
        loaded_lane_count += 1
        timestamp_index: dict[int, int] = {}
        for index, value in enumerate(frame["timestamp"].tolist()):
            epoch_ns = normalized_ns(engine.pd, value)
            if epoch_ns is not None:
                timestamp_index[epoch_ns] = index
        for row in lane_rows:
            entry_ns = normalized_ns(engine.pd, row.get("entry_ts") or row.get("entry_time"))
            index = timestamp_index.get(entry_ns) if entry_ns is not None else None
            if index is None:
                unmatched.append("ENTRY_TIMESTAMP_NOT_FOUND")
                continue
            current = frame.iloc[max(0, index - int(engine.FRAME_LIMIT) + 1): index + 1].copy()
            context = context_owner.compute_context(lane[1], current, None, None, None)
            regime = regime_owner.derive_regime(context)
            reconstructed[event_id(row)] = str(regime) if regime is not None else "missing"

    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_regime_window: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        regime = reconstructed.get(event_id(row), "missing")
        by_regime[regime].append(row)
        by_regime_window[(regime, window_id(row))].append(row)

    entry_neutral = by_regime.get("range", [])
    exit_neutral = [row for row in rows if str(row.get("regime") or row.get("market_regime") or "missing") == "neutral"]
    entry_ids = {event_id(row) for row in entry_neutral}
    exit_ids = {event_id(row) for row in exit_neutral}
    union = entry_ids | exit_ids
    intersection = entry_ids & exit_ids

    blockers: list[str] = []
    if len(rows) != 580:
        blockers.append("GRID_TRADE_COUNT_MISMATCH")
    if len(set(event_id(row) for row in rows)) != len(rows) or not all(event_id(row) for row in rows):
        blockers.append("GRID_EVENT_ID_INTEGRITY_FAILED")
    if loaded_lane_count != len(grouped):
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
        "context_owner_sha256": sha256_file(args.context_owner),
        "regime_owner_sha256": sha256_file(args.regime_owner),
        "data_file_count": len(files),
        "used_lane_count": len(grouped),
        "loaded_lane_count": loaded_lane_count,
        "frame_limit": int(engine.FRAME_LIMIT),
        "trade_count": len(rows),
        "reconstructed_count": len(reconstructed),
        "unmatched_count": len(unmatched),
        "unmatched_reason_counts": dict(Counter(unmatched)),
        "reconstructed_regime_counts": dict(sorted((key, len(value)) for key, value in by_regime.items())),
        "reconstructed_regime_metrics": {key: metrics(value) for key, value in sorted(by_regime.items())},
        "reconstructed_regime_window_metrics": {f"{regime}|{window}": metrics(value) for (regime, window), value in sorted(by_regime_window.items())},
        "entry_range_metrics": metrics(entry_neutral),
        "exit_neutral_metrics": metrics(exit_neutral),
        "entry_range_vs_exit_neutral": {
            "entry_range_count": len(entry_ids),
            "exit_neutral_count": len(exit_ids),
            "intersection_count": len(intersection),
            "entry_only_count": len(entry_ids - exit_ids),
            "exit_only_count": len(exit_ids - entry_ids),
            "jaccard": len(intersection) / len(union) if union else None,
            "entry_range_event_set_sha256": stable_sha(sorted(entry_ids)),
            "exit_neutral_event_set_sha256": stable_sha(sorted(exit_ids)),
        },
        "blockers": blockers,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "raw_price_data_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "REVIEW_ENTRY_RANGE_ECONOMIC_EDGE" if not blockers else "RESOLVE_RECONSTRUCTION_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
