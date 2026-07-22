#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd

EXPECTED_SIGNATURE = [6, 0, 1, 2, 3, 4]
EXPECTED_SOURCE_COUNT = 5
MIN_1M_ROWS = 640
MIN_5M_ROWS = 120
MIN_15M_ROWS = 40


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def validate_rows_audit(audit: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[str] = []
    if audit.get("state") != "PASS_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE":
        blockers.append("ROWS_SCHEMA_AUDIT_NOT_PASS")
    if int(audit.get("blocker_count", -1)) != 0:
        blockers.append("ROWS_SCHEMA_AUDIT_BLOCKED")
    if int(audit.get("required_source_count", -1)) != EXPECTED_SOURCE_COUNT:
        blockers.append("REQUIRED_SOURCE_COUNT_MISMATCH")
    if int(audit.get("layout_ready_source_count", -1)) != EXPECTED_SOURCE_COUNT:
        blockers.append("LAYOUT_READY_SOURCE_COUNT_MISMATCH")
    if int(audit.get("unresolved_source_count", -1)) != 0:
        blockers.append("UNRESOLVED_SOURCE_PRESENT")
    if audit.get("shared_layout") is not True:
        blockers.append("SHARED_LAYOUT_FALSE")
    if audit.get("layout_signatures") != [EXPECTED_SIGNATURE]:
        blockers.append(f"LAYOUT_SIGNATURE_MISMATCH:{audit.get('layout_signatures')}")
    diagnostics = [row for row in audit.get("source_diagnostics", []) if isinstance(row, dict)]
    if len(diagnostics) != EXPECTED_SOURCE_COUNT:
        blockers.append(f"SOURCE_DIAGNOSTIC_COUNT_MISMATCH:{len(diagnostics)}")
    if blockers:
        raise ValueError(";".join(blockers))
    return diagnostics


def _timestamp_unit(values: pd.Series) -> str:
    median = float(values.abs().median())
    if median >= 1e17:
        return "ns"
    if median >= 1e14:
        return "us"
    if median >= 1e11:
        return "ms"
    return "s"


def load_audited_market_frame(path: Path, expected_sha256: str) -> pd.DataFrame:
    actual_sha = sha256_file(path)
    if actual_sha is None or actual_sha != expected_sha256:
        raise ValueError("FROZEN_SHA_MISMATCH")
    payload = load_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("MARKET_ROWS_REQUIRED")
    if any(not isinstance(row, list) or len(row) != 6 for row in rows):
        raise ValueError("MARKET_ROW_WIDTH_MISMATCH")
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    for column in ("timestamp", "open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.isna().any().any():
        raise ValueError("MARKET_NON_NUMERIC_VALUE")
    if not math.isclose(float(len(frame)), float(payload.get("row_count", len(frame)))):
        raise ValueError("MARKET_ROW_COUNT_MISMATCH")
    valid = (
        (frame["open"] > 0)
        & (frame["high"] > 0)
        & (frame["low"] > 0)
        & (frame["close"] > 0)
        & (frame["volume"] >= 0)
        & (frame["high"] >= frame[["open", "close"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close"]].min(axis=1))
    )
    if float(valid.mean()) < 0.999:
        raise ValueError(f"MARKET_GEOMETRY_RATIO_LOW:{float(valid.mean())}")
    frame = frame.loc[valid].copy()
    frame["__timestamp"] = frame["timestamp"]
    frame = frame.sort_values("__timestamp").drop_duplicates("__timestamp", keep="last").reset_index(drop=True)
    if len(frame) < MIN_1M_ROWS:
        raise ValueError(f"MARKET_ROWS_LT_MIN:{len(frame)}")
    if not frame["__timestamp"].is_monotonic_increasing:
        raise ValueError("MARKET_TIMESTAMP_NOT_MONOTONIC")
    frame["symbol"] = str(payload.get("symbol") or "UNKNOWN").upper()
    frame["timeframe"] = str(payload.get("interval") or "1m")
    return frame


def resample_complete_bars(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    if minutes not in {5, 15}:
        raise ValueError("UNSUPPORTED_RESAMPLE_MINUTES")
    timestamps = pd.to_numeric(frame["__timestamp"], errors="coerce")
    unit = _timestamp_unit(timestamps)
    dt = pd.to_datetime(timestamps, unit=unit, utc=True, errors="coerce")
    if dt.isna().any():
        raise ValueError("TIMESTAMP_PARSE_FAILED")
    work = frame[["open", "high", "low", "close", "volume"]].copy()
    work.index = dt
    rule = f"{minutes}min"
    grouped = work.resample(rule, label="left", closed="left")
    counts = grouped["close"].count()
    output = grouped.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    output = output[counts == minutes].dropna().reset_index(names="__datetime")
    output["__timestamp"] = output["__datetime"].astype("int64") // 1_000_000
    output = output.drop(columns=["__datetime"])
    geometry = (
        (output["high"] >= output[["open", "close"]].max(axis=1))
        & (output["low"] <= output[["open", "close"]].min(axis=1))
    )
    if len(output) == 0 or float(geometry.mean()) < 1.0:
        raise ValueError("RESAMPLED_GEOMETRY_INVALID")
    output["symbol"] = str(frame["symbol"].iloc[0])
    output["timeframe"] = f"{minutes}m"
    return output


def build_bind(root: Path, audit: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    diagnostics = validate_rows_audit(audit)
    source_results: list[dict[str, Any]] = []
    protected_paths: list[Path] = []
    for row in diagnostics:
        repo_path = safe_repo_path(str(row.get("path") or ""))
        path = root / repo_path
        protected_paths.append(path)
        expected_sha = str(row.get("expected_sha256") or row.get("actual_sha256") or "")
        try:
            frame_1m = load_audited_market_frame(path, expected_sha)
            frame_5m = resample_complete_bars(frame_1m, 5)
            frame_15m = resample_complete_bars(frame_1m, 15)
            if len(frame_5m) < MIN_5M_ROWS:
                raise ValueError(f"TF5_ROWS_LT_MIN:{len(frame_5m)}")
            if len(frame_15m) < MIN_15M_ROWS:
                raise ValueError(f"TF15_ROWS_LT_MIN:{len(frame_15m)}")
            source_results.append({
                "source_path": repo_path,
                "source_sha256": expected_sha,
                "symbol": str(frame_1m["symbol"].iloc[0]),
                "native_timeframe": "1m",
                "layout_signature": EXPECTED_SIGNATURE,
                "row_count_1m": int(len(frame_1m)),
                "complete_row_count_5m": int(len(frame_5m)),
                "complete_row_count_15m": int(len(frame_15m)),
                "geometry_valid_1m": True,
                "geometry_valid_5m": True,
                "geometry_valid_15m": True,
            })
        except Exception as exc:
            blockers.append(f"SOURCE_ADAPTER_BIND_FAILED:{repo_path}:{type(exc).__name__}:{exc}")
    symbols = sorted({row["symbol"] for row in source_results})
    if len(source_results) != EXPECTED_SOURCE_COUNT:
        blockers.append(f"BOUND_SOURCE_COUNT_MISMATCH:{len(source_results)}")
    if len(symbols) != EXPECTED_SOURCE_COUNT:
        blockers.append(f"BOUND_SYMBOL_COUNT_MISMATCH:{len(symbols)}")
    state = "PASS_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND" if not blockers else "HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND"
    result = {
        "schema": "r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind_v1",
        "official_stage": "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "layout_signature": EXPECTED_SIGNATURE,
        "bound_source_count": len(source_results),
        "bound_symbol_count": len(symbols),
        "bound_symbols": symbols,
        "derived_timeframes": ["5m", "15m"],
        "source_allowlist": source_results,
        "candidate_architecture_count": 3,
        "candidate_target_count": 36,
        "execution_cell_target_count": 216,
        "candidate_discovery_ready": not blockers,
        "source_file_mutation_allowed": False,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "next_stage": "R7.A4D2_SHORT_SCALP_TIMEFRAME_CANDIDATE_DISCOVERY_36" if not blockers else "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND",
    }
    return result, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    audit_path = root / "runtime/r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose/rows_schema_diagnose_v1.json"
    audit = load_json(audit_path)
    protected = [audit_path] + [root / safe_repo_path(str(row.get("path") or "")) for row in audit.get("source_diagnostics", []) if isinstance(row, dict)]
    before = {str(path): sha256_file(path) for path in protected}
    try:
        result, blockers = build_bind(root, audit)
    except Exception as exc:
        blockers = [f"ADAPTER_BIND_INPUT_INVALID:{type(exc).__name__}:{exc}"]
        result = {
            "schema": "r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind_v1",
            "official_stage": "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND",
            "state": "HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND",
            "blocker_count": len(blockers),
            "blockers": blockers,
            "bound_source_count": 0,
            "bound_symbol_count": 0,
            "bound_symbols": [],
            "derived_timeframes": [],
            "source_allowlist": [],
            "candidate_discovery_ready": False,
            "next_stage": "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND",
        }
    after = {str(path): sha256_file(path) for path in protected}
    mutations = sorted(path for path in before if before[path] != after[path])
    if mutations:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
        result["blockers"] = list(dict.fromkeys(blockers))
        result["blocker_count"] = len(result["blockers"])
        result["state"] = "HOLD_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND"
        result["candidate_discovery_ready"] = False
        result["next_stage"] = "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND"
    result["protected_mutation_path_count"] = len(mutations)
    result["protected_mutation_paths"] = mutations
    output = root / "runtime/r7a4d2_short_scalp_required_ohlcv_schema_adapter_bind/adapter_bind_v1.json"
    atomic_json(output, result)
    print("STATE=" + str(result["state"]))
    print("BLOCKER_COUNT=" + str(result["blocker_count"]))
    print("LAYOUT_SIGNATURE=" + json.dumps(result.get("layout_signature")))
    print("BOUND_SOURCE_COUNT=" + str(result.get("bound_source_count", 0)))
    print("BOUND_SYMBOL_COUNT=" + str(result.get("bound_symbol_count", 0)))
    print("BOUND_SYMBOLS=" + json.dumps(result.get("bound_symbols", [])))
    print("DERIVED_TIMEFRAMES=" + json.dumps(result.get("derived_timeframes", [])))
    print("SOURCE_ALLOWLIST=" + json.dumps(result.get("source_allowlist", []), sort_keys=True))
    print("CANDIDATE_DISCOVERY_READY=" + str(result.get("candidate_discovery_ready", False)).lower())
    print("CANDIDATE_TARGET_COUNT=" + str(result.get("candidate_target_count", 0)))
    print("EXECUTION_CELL_TARGET_COUNT=" + str(result.get("execution_cell_target_count", 0)))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(result.get("protected_mutation_path_count", 0)))
    print("ADAPTER_BIND_JSON=" + str(output))
    print("NEXT_STAGE=" + str(result["next_stage"]))
    print("BLOCKERS=" + json.dumps(result["blockers"], ensure_ascii=False))
    print("RC=" + ("0" if int(result["blocker_count"]) == 0 else "2"))
    return 0 if int(result["blocker_count"]) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
