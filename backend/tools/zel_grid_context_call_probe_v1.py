from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import inspect
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_CONTEXT_CALL_PROBE_V1"
SCHEMA = "zel.grid_context_call_probe.receipt.v1"
STRATEGY_ID = "grid_rebalance"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def first_grid_trade(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "") == STRATEGY_ID:
                return row
    raise RuntimeError("GRID_TRADE_MISSING")


def safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}:{str(exc)[:160]}"


def normalize_ns(pd_module: Any, value: Any) -> int | None:
    try:
        ts = pd_module.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return int(ts.value)
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
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    engine = load_module(args.engine, "zel_context_probe_engine")
    context_owner = load_module(args.context_owner, "zel_context_owner")
    regime_owner = load_module(args.regime_owner, "zel_regime_owner")
    trade = first_grid_trade(args.terminal_root / "trades.jsonl.gz")
    manifest_result = engine.validate_data_manifest(args.data_root, "1m")
    manifest = manifest_result[0] if isinstance(manifest_result, tuple) else manifest_result
    files = list(manifest.get("files") or []) if isinstance(manifest, Mapping) else []
    lane = (str(trade.get("window_id") or trade.get("window") or "unknown"), str(trade.get("symbol") or "").upper())
    file_row = next((row for row in files if isinstance(row, Mapping) and (str(row.get("window_id") or row.get("window") or "unknown"), str(row.get("symbol") or "").upper()) == lane), None)
    if file_row is None:
        raise RuntimeError("LANE_FILE_MISSING")
    frame = engine.frame_from_csv(resolve_file(args.data_root, file_row))
    entry_ns = normalize_ns(engine.pd, trade.get("entry_ts") or trade.get("entry_time"))
    index = next((i for i, value in enumerate(frame["timestamp"].tolist()) if normalize_ns(engine.pd, value) == entry_ns), None)
    if index is None:
        raise RuntimeError("ENTRY_TIMESTAMP_NOT_FOUND")
    current = frame.iloc[max(0, index - int(engine.FRAME_LIMIT) + 1): index + 1].copy()

    symbol = lane[1]
    window = lane[0]
    candidates = [
        ("dict_context", {"symbol": symbol, "window_id": window, "timeframe": "1m"}),
        ("string_lane", f"{window}:{symbol}:1m"),
        ("string_symbol", symbol),
        ("none", None),
    ]
    results: list[dict[str, Any]] = []
    for label, token in candidates:
        try:
            context = context_owner.compute_context(token, current, {}, {}, {})
            if not isinstance(context, Mapping):
                raise RuntimeError(f"CONTEXT_TYPE_{type(context).__name__}")
            direction = context.get("trend_direction")
            strength = context.get("trend_strength")
            regime = regime_owner.derive_regime(context)
            results.append({
                "candidate": label,
                "success": True,
                "context_key_count": len(context),
                "trend_direction": str(direction) if direction is not None else None,
                "trend_strength_finite": isinstance(strength, (int, float)) and math.isfinite(float(strength)),
                "regime": str(regime) if regime is not None else None,
            })
        except Exception as exc:
            results.append({"candidate": label, "success": False, "error": safe_error(exc)})

    successful = [row for row in results if row.get("success") and row.get("trend_direction") is not None and row.get("trend_strength_finite") and row.get("regime")]
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_CONTEXT_CALL_CONTRACT" if successful else "HOLD_GRID_CONTEXT_CALL_CONTRACT_UNRESOLVED",
        "compute_context_signature": str(inspect.signature(context_owner.compute_context)),
        "derive_regime_signature": str(inspect.signature(regime_owner.derive_regime)),
        "engine_frame_limit": int(engine.FRAME_LIMIT),
        "data_file_count": len(files),
        "candidate_results": results,
        "successful_candidate_labels": [row["candidate"] for row in successful],
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_row_published": False,
        "raw_price_data_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
