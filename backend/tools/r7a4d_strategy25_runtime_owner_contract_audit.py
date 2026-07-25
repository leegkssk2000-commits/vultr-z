from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.strategy25.indicator_contract_repair_adapter_v2 import REPAIR_SPECS, repair_manifest, transformed_source


EXPECTED_IDS = (
    "alpha_combo",
    "anchor_vwap_trend",
    "bb_revert",
    "break_and_continue",
    "ema_ribbon_scalp",
    "fvg_revert",
    "grid_rebalance",
    "keltner_trend",
    "liquidity_sweep",
    "mfi_rsi_div",
    "obv_trend",
    "pivot_reversal",
    "range_fade",
    "rbreaker_like",
    "rsi_swing_fail",
    "scalp_snap",
    "session_bias",
    "squeeze_break",
    "sr_levels",
    "supertrend_pullback",
    "trend_ma_macd",
    "trend_rider",
    "turtle_trend",
    "vol_spike_fade",
    "vwap_revert",
)

STRUCTURAL_LOCKS: Mapping[str, tuple[str, ...]] = {
    "ema_ribbon_scalp": (
        "class EmaRibbonScalpLBotStrategy",
        "ema1_len: int = 8",
        "ema2_len: int = 21",
        "ema3_len: int = 55",
        "ribbon_long = e1 > e2 > e3",
    ),
    "vol_spike_fade": (
        "class VolSpikeFadeLBotStrategy",
        "vol_spike = vol_now > vol_ma * cfg.vol_mult",
        "atr_spike = atr_now > atr_ma * cfg.atr_spike_mult",
        "spike_ok = vol_spike and atr_spike",
    ),
    "fvg_revert": ("class FvgRevertLBotStrategy",),
    "session_bias": ("class SessionBiasLBotStrategy",),
}

PARTIAL_CONTRACT_LOCKS: Mapping[str, tuple[str, ...]] = {
    "anchor_vwap_trend": ("def _anchor_from_swing", "def _vwap_from"),
    "grid_rebalance": ("class GridRebalanceConfig", "long_setup =", "short_setup ="),
    "supertrend_pullback": ("def _supertrend", "long_pullback_zone =", "short_pullback_zone ="),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _top_level_contract(tree: ast.Module) -> tuple[set[str], dict[str, set[str]]]:
    functions: set[str] = set()
    classes: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return functions, classes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    config_path = root / "backend/strategy25/canonical_strategy25_config_v1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    entries = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    ids = [str(row.get("strategy_id")) for row in entries]
    blockers: list[str] = []
    rows: list[dict[str, Any]] = []

    if tuple(sorted(ids)) != tuple(sorted(EXPECTED_IDS)):
        blockers.append(f"STRATEGY_SET_MISMATCH:{ids}")
    if len(ids) != 25 or len(set(ids)) != 25:
        blockers.append(f"STRATEGY_COUNT_OR_DUPLICATE:{len(ids)}:{len(set(ids))}")
    if registry.get("active_entry_count") != 0:
        blockers.append(f"ACTIVE_ENTRY_COUNT_NOT_ZERO:{registry.get('active_entry_count')}")

    implementation_paths: list[str] = []
    for entry in entries:
        strategy_id = str(entry.get("strategy_id"))
        engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
        implementation_path = str(engine.get("implementation_path") or "")
        runtime_callable = str(engine.get("callable") or "")
        implementation_paths.append(implementation_path)
        row_blockers: list[str] = []
        source_path = root / implementation_path
        if entry.get("active_allowed") is not False:
            row_blockers.append("ACTIVE_ALLOWED_NOT_FALSE")
        if entry.get("fail_closed") is not True:
            row_blockers.append("FAIL_CLOSED_NOT_TRUE")
        if not source_path.is_file() or source_path.is_symlink():
            row_blockers.append("SOURCE_INVALID")
            source = ""
            actual_sha = None
        else:
            source = source_path.read_text(encoding="utf-8")
            actual_sha = _sha256(source_path)
            expected_sha = str(engine.get("source_sha256") or "")
            if expected_sha != actual_sha:
                row_blockers.append(f"SOURCE_SHA_MISMATCH:{expected_sha}:{actual_sha}")
            try:
                tree = ast.parse(source, filename=implementation_path)
                functions, classes = _top_level_contract(tree)
                if "strategy" not in functions:
                    row_blockers.append("TOP_LEVEL_STRATEGY_MISSING")
                callable_parts = runtime_callable.split(".")
                if len(callable_parts) != 2:
                    row_blockers.append(f"CALLABLE_FORMAT_INVALID:{runtime_callable}")
                else:
                    class_name, method_name = callable_parts
                    if class_name not in classes:
                        row_blockers.append(f"CALLABLE_CLASS_MISSING:{class_name}")
                    elif method_name not in classes[class_name]:
                        row_blockers.append(f"CALLABLE_METHOD_MISSING:{runtime_callable}")
            except SyntaxError as exc:
                row_blockers.append(f"SOURCE_SYNTAX:{exc}")

        config_strategies = config.get("strategies") if isinstance(config.get("strategies"), dict) else {}
        if strategy_id not in config_strategies:
            row_blockers.append("CONFIG_BINDING_MISSING")
        config_ref = str(entry.get("config_ref") or "")
        expected_ref = f"backend/strategy25/canonical_strategy25_config_v1.json#/strategies/{strategy_id}"
        if config_ref != expected_ref:
            row_blockers.append(f"CONFIG_REF_MISMATCH:{config_ref}")

        for marker in STRUCTURAL_LOCKS.get(strategy_id, ()):
            if marker not in source:
                row_blockers.append(f"STRUCTURAL_MARKER_MISSING:{marker}")
        for marker in PARTIAL_CONTRACT_LOCKS.get(strategy_id, ()):
            if marker not in source:
                row_blockers.append(f"PARTIAL_CONTRACT_MARKER_MISSING:{marker}")

        repair_status = "NOT_REQUIRED"
        if strategy_id in REPAIR_SPECS:
            try:
                repaired = transformed_source(root, strategy_id)
                compile(repaired, f"<runtime-contract-audit:{strategy_id}>", "exec")
                repair_status = "CHILD_COMPILE_PASS"
            except Exception as exc:
                repair_status = "CHILD_COMPILE_HOLD"
                row_blockers.append(f"REPAIR_CHILD_INVALID:{type(exc).__name__}:{exc}")

        if row_blockers:
            blockers.extend(f"{strategy_id}:{value}" for value in row_blockers)
        rows.append(
            {
                "strategy_id": strategy_id,
                "implementation_path": implementation_path,
                "runtime_callable": runtime_callable,
                "source_sha256": actual_sha,
                "config_ref": config_ref,
                "active_allowed": entry.get("active_allowed"),
                "fail_closed": entry.get("fail_closed"),
                "repair_status": repair_status,
                "blockers": row_blockers,
                "owner_locked": not row_blockers,
            }
        )

    duplicate_paths = sorted({path for path in implementation_paths if implementation_paths.count(path) > 1})
    if duplicate_paths:
        blockers.append(f"DUPLICATE_IMPLEMENTATION_PATHS:{duplicate_paths}")

    report = {
        "schema_version": "1.0",
        "authority": "READ_ONLY_CONTRACT_AUDIT_NO_EXECUTION",
        "state": "PASS" if not blockers else "HOLD",
        "strategy_count": len(rows),
        "owner_locked_count": sum(row["owner_locked"] for row in rows),
        "expected_strategy_ids": list(EXPECTED_IDS),
        "rows": rows,
        "repair_manifest": [dict(item) for item in repair_manifest()],
        "duplicate_implementation_paths": duplicate_paths,
        "blockers": blockers,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "execution_allowed": False,
        "next": "RUN_NEW_NONOVERLAP_BASELINE_CENSUS" if not blockers else "HOLD_AND_FIX_OWNER_OR_CONTRACT_BLOCKERS",
    }
    _atomic_json(root / "artifacts/strategy25_runtime_owner_contract_audit_v1/summary.json", report)
    print(json.dumps({"STATE": report["state"], "LOCKED": report["owner_locked_count"], "BLOCKERS": blockers, "NEXT": report["next"]}, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
