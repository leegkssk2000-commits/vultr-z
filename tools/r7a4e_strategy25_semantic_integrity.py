#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_RESULT_KEYS = {
    "side", "action", "size", "entry", "sl", "tp",
    "pyramiding", "why", "skill", "confidence", "tags", "indicators",
}
PATCH_MARKERS = {
    "anchor_vwap_trend": ["anchors_are_confirmed_and_index_safe", "_confirmed_anchor_positions"],
    "break_and_continue": ["box_excludes_signal_bar", "history = frame.iloc[:-1]"],
    "fvg_revert": ["three_candle_fvg", "signal_bar_excluded_from_gap_discovery"],
    "mfi_rsi_div": ["prior_swing_window_excludes_signal_bar", "frame.iloc[-(cfg.swing_lookback + 1):-1]"],
    "pivot_reversal": ["confirmed_pivots_exclude_signal_bar", "_last_confirmed_pivots"],
    "range_fade": ["prior_range_excludes_signal_bar", "range_regime_required"],
    "session_bias": ["overlap_classified_before_single_session", "london_newyork_overlap"],
    "sr_levels": ["prior_sr_window_excludes_signal_bar", "volume_baseline_excludes_signal_bar"],
    "supertrend_pullback": ["prior_swing_excludes_signal_bar", "geometry_available"],
    "vol_spike_fade": ["spike_and_reversal_are_distinct_bars", "volfade_no_confirmed_reversal"],
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def synthetic_frame(rows: int = 260) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    base_ts = 1_700_000_000_000
    previous = 100.0
    for i in range(rows):
        drift = i * 0.025
        wave = math.sin(i / 8.0) * 1.8 + math.sin(i / 23.0) * 2.4
        close = 100.0 + drift + wave
        open_ = previous
        high = max(open_, close) + 0.65 + abs(math.sin(i / 5.0)) * 0.30
        low = min(open_, close) - 0.65 - abs(math.cos(i / 7.0)) * 0.30
        volume = 1000.0 + (i % 17) * 35.0 + abs(math.sin(i / 4.0)) * 420.0
        records.append({
            "timestamp": base_ts + i * 900_000,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
        previous = close
    return pd.DataFrame(records)


def module_name(path: str) -> str:
    if not path.endswith(".py"):
        raise ValueError(f"PYTHON_PATH_REQUIRED:{path}")
    return path[:-3].replace("/", ".")


def validate_result(strategy_id: str, result: Any) -> None:
    if not isinstance(result, dict):
        raise AssertionError(f"NON_DICT_RESULT:{strategy_id}:{type(result).__name__}")
    missing = sorted(REQUIRED_RESULT_KEYS - set(result))
    if missing:
        raise AssertionError(f"RESULT_KEYS_MISSING:{strategy_id}:{','.join(missing)}")
    if not isinstance(result.get("tags"), list):
        raise AssertionError(f"RESULT_TAGS_NOT_LIST:{strategy_id}")
    if not isinstance(result.get("indicators"), dict):
        raise AssertionError(f"RESULT_INDICATORS_NOT_OBJECT:{strategy_id}")
    action = str(result.get("action") or "")
    if action not in {"hold", "enter", "add", "reduce", "exit", "close", "block"}:
        raise AssertionError(f"RESULT_ACTION_INVALID:{strategy_id}:{action}")
    if action in {"enter", "add"}:
        entry = float(result.get("entry") or 0.0)
        sl = float(result.get("sl") or 0.0)
        tp = float(result.get("tp") or 0.0)
        side = str(result.get("side") or "")
        if min(entry, sl, tp) <= 0:
            raise AssertionError(f"ACTIVE_PRICE_INVALID:{strategy_id}")
        if side == "long" and not (sl < entry < tp):
            raise AssertionError(f"LONG_GEOMETRY_INVALID:{strategy_id}:{sl}:{entry}:{tp}")
        if side == "short" and not (tp < entry < sl):
            raise AssertionError(f"SHORT_GEOMETRY_INVALID:{strategy_id}:{tp}:{entry}:{sl}")


def verify(root: Path, *, write_registry: bool = False) -> dict[str, Any]:
    contract_path = root / "backend/strategy25/strategy25_semantic_contract_v1.json"
    registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    contract = load_json(contract_path)
    registry = load_json(registry_path)
    strategies = contract.get("strategies")
    entries = registry.get("entries")
    if not isinstance(strategies, list) or len(strategies) != 25:
        raise AssertionError(f"CONTRACT_COUNT_INVALID:{len(strategies or [])}")
    if not isinstance(entries, list) or len(entries) != 25:
        raise AssertionError(f"REGISTRY_COUNT_INVALID:{len(entries or [])}")
    if int(registry.get("active_entry_count") or 0) != 0:
        raise AssertionError("ACTIVE_ENTRY_COUNT_NOT_ZERO")

    contract_by_id = {str(row["strategy_id"]): row for row in strategies}
    registry_by_id = {str(row["strategy_id"]): row for row in entries}
    if len(contract_by_id) != 25 or len(registry_by_id) != 25:
        raise AssertionError("DUPLICATE_STRATEGY_ID")
    if set(contract_by_id) != set(registry_by_id):
        raise AssertionError("CONTRACT_REGISTRY_ID_MISMATCH")

    sys.path.insert(0, str(root))
    frame = synthetic_frame()
    report: list[dict[str, Any]] = []
    registry_changed = False
    try:
        for strategy_id in sorted(contract_by_id):
            contract_row = contract_by_id[strategy_id]
            registry_row = registry_by_id[strategy_id]
            engine = registry_row.get("canonical_engine")
            if not isinstance(engine, dict):
                raise AssertionError(f"ENGINE_OBJECT_MISSING:{strategy_id}")
            path_text = str(engine.get("implementation_path") or "")
            if path_text != str(contract_row.get("canonical_path") or ""):
                raise AssertionError(f"CANONICAL_PATH_MISMATCH:{strategy_id}")
            if registry_row.get("active_allowed") is not False or registry_row.get("fail_closed") is not True:
                raise AssertionError(f"AUTHORITY_NOT_FAIL_CLOSED:{strategy_id}")

            source_path = root / path_text
            data = source_path.read_bytes()
            source = data.decode("utf-8")
            ast.parse(source, filename=path_text)
            digest = sha256_bytes(data)
            blob = git_blob_sha(data)
            if engine.get("source_sha256") != digest:
                if write_registry:
                    engine["source_sha256"] = digest
                    registry_changed = True
                else:
                    raise AssertionError(f"SOURCE_SHA256_MISMATCH:{strategy_id}")
            if engine.get("source_blob_sha") != blob:
                if write_registry:
                    engine["source_blob_sha"] = blob
                    registry_changed = True
                elif engine.get("source_blob_sha") not in (None, ""):
                    raise AssertionError(f"SOURCE_BLOB_SHA_MISMATCH:{strategy_id}")

            callable_text = str(engine.get("callable") or "")
            class_name, separator, method_name = callable_text.partition(".")
            if not separator or not class_name or not method_name:
                raise AssertionError(f"CALLABLE_FORMAT_INVALID:{strategy_id}:{callable_text}")
            module = importlib.import_module(module_name(path_text))
            strategy_fn = getattr(module, "strategy", None)
            owner = getattr(module, class_name, None)
            if not callable(strategy_fn) or owner is None or not callable(getattr(owner, method_name, None)):
                raise AssertionError(f"CALLABLE_MISSING:{strategy_id}:{callable_text}")

            result = strategy_fn(
                frame.copy(),
                state={"position_side": "", "position_qty": 0.0, "avg_entry": 0.0, "add_count": 0},
                risk_action="hold",
            )
            validate_result(strategy_id, result)
            for marker in PATCH_MARKERS.get(strategy_id, []):
                if marker not in source:
                    raise AssertionError(f"PATCH_MARKER_MISSING:{strategy_id}:{marker}")
            report.append({
                "strategy_id": strategy_id,
                "path": path_text,
                "source_sha256": digest,
                "source_blob_sha": blob,
                "smoke_action": str(result.get("action") or ""),
                "smoke_reason": str(result.get("why") or ""),
                "audit_status": str(contract_row.get("audit_status") or ""),
            })
    finally:
        if sys.path and sys.path[0] == str(root):
            sys.path.pop(0)

    if write_registry:
        contract_digest = sha256_bytes(contract_path.read_bytes())
        if registry.get("semantic_contract_ref") != str(contract_path.relative_to(root)):
            registry["semantic_contract_ref"] = str(contract_path.relative_to(root))
            registry_changed = True
        if registry.get("semantic_contract_sha256") != contract_digest:
            registry["semantic_contract_sha256"] = contract_digest
            registry_changed = True
        if registry.get("semantic_closure_stage") != contract.get("stage"):
            registry["semantic_closure_stage"] = contract.get("stage")
            registry_changed = True
        if registry_changed:
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    return {
        "status": "PASS_R7A4E_STRATEGY25_SEMANTIC_INTEGRITY",
        "strategy_count": len(report),
        "patched_strategy_count": len(PATCH_MARKERS),
        "identity_blocker_count": len(contract.get("identity_blockers") or []),
        "active_entry_count": int(registry.get("active_entry_count") or 0),
        "registry_changed": registry_changed,
        "strategies": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--write-registry", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    result = verify(root, write_registry=args.write_registry)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
