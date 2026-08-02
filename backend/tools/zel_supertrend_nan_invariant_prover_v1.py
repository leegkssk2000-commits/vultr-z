from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_SUPERTREND_NAN_INVARIANT_PROVER_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_module(path: Path, prefix: str) -> Any:
    name = f"{prefix}_{os.getpid()}_{path.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def deterministic_indices(length: int, first_index: int) -> list[int]:
    if length <= first_index:
        return []
    candidates = {
        first_index,
        min(first_index + 1, length - 1),
        min(first_index + 17, length - 1),
        max(first_index, length // 4),
        max(first_index, length // 2),
        max(first_index, (length * 3) // 4),
        length - 2,
        length - 1,
    }
    return sorted(index for index in candidates if first_index <= index < length)


def source_invariants(strategy_fn: Any) -> dict[str, Any]:
    globals_ = strategy_fn.__globals__
    atr_fn = globals_.get("_atr")
    st_fn = globals_.get("_supertrend")
    if not callable(atr_fn) or not callable(st_fn):
        raise RuntimeError("ATR_OR_SUPERTREND_FUNCTION_MISSING")
    atr_source = inspect.getsource(atr_fn)
    st_source = inspect.getsource(st_fn)
    strategy_source = inspect.getsource(strategy_fn)
    required_atr = (
        ".rolling(length, min_periods=length).mean()",
        "prev_close = close.shift(1)",
    )
    required_st = (
        "final_upperband = upperband.copy()",
        "final_lowerband = lowerband.copy()",
        "st.iloc[i] = lowerband.iloc[i]",
        "final_upperband.iloc[i] = final_upperband.iloc[i - 1]",
        "final_lowerband.iloc[i] = final_lowerband.iloc[i - 1]",
    )
    required_strategy = (
        "st_df = _supertrend",
        "if min(",
        "indicator_nan",
    )
    missing = [marker for marker in required_atr if marker not in atr_source]
    missing += [marker for marker in required_st if marker not in st_source]
    missing += [marker for marker in required_strategy if marker not in strategy_source]
    return {
        "state": "PASS_STATIC_SOURCE_INVARIANTS" if not missing else "HOLD_STATIC_SOURCE_INVARIANTS",
        "missing_markers": missing,
        "atr_source_sha256": hashlib.sha256(atr_source.encode()).hexdigest(),
        "supertrend_source_sha256": hashlib.sha256(st_source.encode()).hexdigest(),
        "strategy_source_sha256": hashlib.sha256(strategy_source.encode()).hexdigest(),
    }


def prove(
    contract_path: Path,
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    interval: str,
) -> dict[str, Any]:
    contract = load_json(contract_path)
    engine = load_module(engine_path, "zel_nan_proof_engine")
    manifest, _ = engine.validate_data_manifest(data_root, interval)
    producer = engine.import_producer(source_root)
    _, registry = producer.load_registry(source_root)
    source_locks = contract.get("source_locks") if isinstance(contract.get("source_locks"), dict) else {}
    expected_ids = sorted(source_locks)
    if expected_ids != ["supertrend_pullback", "trend_rider"]:
        raise RuntimeError(f"CONTRACT_PENDING_IDS_INVALID:{expected_ids}")

    sample_rows: list[dict[str, Any]] = []
    source_receipts: dict[str, Any] = {}
    failures: list[str] = []
    market_files = [
        row for row in manifest.get("files", [])
        if isinstance(row, dict) and row.get("kind") == "market" and row.get("interval") == interval
    ]
    if not market_files:
        raise RuntimeError("MARKET_FILES_MISSING")

    for strategy_id in expected_ids:
        owner = registry.get(strategy_id)
        if owner is None:
            failures.append(f"REGISTRY_OWNER_MISSING:{strategy_id}")
            continue
        lock = source_locks[strategy_id]
        owner_path = source_root / str(lock["owner_path"])
        actual_sha = sha256_path(owner_path)
        owner_sha = str(getattr(owner, "owner_sha256", ""))
        if actual_sha != lock["owner_sha256"] or owner_sha != lock["owner_sha256"]:
            failures.append(f"OWNER_SHA_MISMATCH:{strategy_id}")
        static = source_invariants(owner.strategy)
        if not static["state"].startswith("PASS_"):
            failures.append(f"STATIC_INVARIANT_FAILED:{strategy_id}")
        source_receipts[strategy_id] = {
            "owner_path": str(lock["owner_path"]),
            "expected_sha256": lock["owner_sha256"],
            "actual_sha256": actual_sha,
            "registry_owner_sha256": owner_sha,
            "expected_hold_reason": lock["expected_hold_reason"],
            "static": static,
        }

        globals_ = owner.strategy.__globals__
        st_fn = globals_["_supertrend"]
        for file_row in sorted(market_files, key=lambda row: (str(row.get("window_id")), str(row.get("symbol")))):
            frame = engine.frame_from_csv(data_root / str(file_row["path"]))
            first_index = max(int(engine.WARMUP_BARS) - 1, 0)
            for index in deterministic_indices(len(frame), first_index):
                current = frame.iloc[max(0, index - int(engine.FRAME_LIMIT) + 1): index + 1].copy()
                result = owner.strategy(current, state=None, risk_action="hold")
                st_df = st_fn(current, 10, 3.0)
                st_all_nan = bool(st_df["supertrend"].isna().all())
                action = str(result.get("action") or "").lower() if isinstance(result, dict) else ""
                why = str(result.get("why") or "") if isinstance(result, dict) else ""
                side = result.get("side") if isinstance(result, dict) else "INVALID"
                size = float(result.get("size") or 0.0) if isinstance(result, dict) else math.nan
                passed = (
                    isinstance(result, dict)
                    and action == "hold"
                    and why == lock["expected_hold_reason"]
                    and side is None
                    and size == 0.0
                    and st_all_nan
                )
                if not passed:
                    failures.append(f"SAMPLE_PARITY_FAILED:{strategy_id}:{file_row.get('window_id')}:{index}")
                sample_rows.append({
                    "strategy_id": strategy_id,
                    "window_id": file_row.get("window_id"),
                    "symbol": file_row.get("symbol"),
                    "frame_index": index,
                    "frame_length": len(current),
                    "action": action,
                    "why": why,
                    "side": side,
                    "size": size,
                    "supertrend_all_nan": st_all_nan,
                    "passed": passed,
                })

    passed_count = sum(1 for row in sample_rows if row["passed"])
    required_min = int(contract.get("semantic_invariant", {}).get("required_runtime_sample_count_min") or 12)
    if len(sample_rows) < required_min:
        failures.append("RUNTIME_SAMPLE_COUNT_BELOW_MIN")
    parity_pct = (passed_count / len(sample_rows) * 100.0) if sample_rows else 0.0
    if parity_pct != 100.0:
        failures.append("RUNTIME_HOLD_PARITY_NOT_100")

    result: dict[str, Any] = {
        "schema_version": "zel.supertrend_nan_semantic_invariant.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_SUPERTREND_NAN_SEMANTIC_INVARIANT" if not failures else "HOLD_SUPERTREND_NAN_SEMANTIC_INVARIANT",
        "interval": interval,
        "strategy_ids": expected_ids,
        "source_receipts": source_receipts,
        "market_file_count": len(market_files),
        "runtime_sample_count": len(sample_rows),
        "runtime_pass_count": passed_count,
        "runtime_hold_parity_pct": parity_pct,
        "samples": sample_rows,
        "failures": sorted(set(failures)),
        "semantic_result": {
            "signal_count": 0,
            "open_count": 0,
            "close_count": 0,
            "error_count": 0,
            "deterministic_hold_only": not failures,
        },
        "read_only": True,
        "runtime_mutated": False,
        "service_restarted": False,
        "signal_sent": False,
        "files_written_on_vps": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    return result


def self_test() -> None:
    indices = deterministic_indices(1000, 239)
    assert indices[0] == 239 and indices[-1] == 999, indices
    assert len(indices) >= 6, indices
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--engine-v1", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--interval", default="1m", choices=("1m", "15m"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.contract, args.engine_v1, args.source_root, args.data_root)):
        parser.error("contract, engine-v1, source-root and data-root are required")
    row = prove(
        args.contract.resolve(),
        args.engine_v1.resolve(),
        args.source_root.resolve(),
        args.data_root.resolve(),
        args.interval,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
