#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any


MINIMUM_SOURCE_ROWS = 640
TARGET_TIMEFRAMES = ("5m", "15m")
TIMEFRAME_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def normalize_timeframe(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace(" ", "")
    aliases = {
        "1": "1m", "1m": "1m", "1min": "1m", "1minute": "1m",
        "3": "3m", "3m": "3m", "3min": "3m",
        "5": "5m", "5m": "5m", "5min": "5m", "5minute": "5m",
        "15": "15m", "15m": "15m", "15min": "15m", "15minute": "15m",
        "30": "30m", "30m": "30m", "30min": "30m",
        "60": "1h", "1h": "1h", "60m": "1h", "1hour": "1h",
    }
    return aliases.get(text)


def infer_timeframe(frame: Any, metadata: dict[str, Any]) -> str | None:
    normalized = normalize_timeframe(metadata.get("timeframe"))
    if normalized:
        return normalized
    if "__timestamp" not in frame.columns or len(frame) < 3:
        return None
    timestamp = frame["__timestamp"]
    numeric = timestamp.map(lambda value: finite(value, float("nan"))).dropna()
    if len(numeric) < 3:
        return None
    deltas = numeric.sort_values().diff().dropna()
    positive = [float(value) for value in deltas if finite(value) > 0]
    if not positive:
        return None
    median_delta = statistics.median(positive)
    if median_delta > 100000:
        median_delta /= 1000.0
    return min(TIMEFRAME_SECONDS, key=lambda key: abs(TIMEFRAME_SECONDS[key] - median_delta))


def infer_symbol(metadata: dict[str, Any], source_path: str) -> str | None:
    if metadata.get("symbol"):
        return str(metadata["symbol"]).upper()
    match = re.search(r"(?<![A-Z0-9])([A-Z]{2,12}(?:USDT|USD|BTC|ETH))(?![A-Z0-9])", source_path.upper())
    return match.group(1) if match else None


def path_role(path: str) -> str:
    lower = path.lower()
    if lower.startswith(("_backups/", "_incoming.patch/")) or "/backup" in lower:
        return "AUXILIARY_BACKUP_OR_PATCH"
    if "/contracts/" in lower or "schema" in lower or "contract" in lower:
        return "AUXILIARY_CONTRACT_OR_METADATA"
    if lower.startswith(("runtime/", "replay/", "static/", "ledger/")):
        return "AUXILIARY_RUNTIME_OR_DERIVED"
    if lower.startswith(("data/", "market/")) or "market_data" in lower:
        return "MARKET_DATA_CANDIDATE"
    return "AUXILIARY_UNCLASSIFIED"


def classify_reason(reason: str) -> str:
    if "FROZEN_SHA_MISMATCH" in reason:
        return "SHA_MISMATCH"
    if "UNSUPPORTED_MARKET_FORMAT" in reason:
        return "UNSUPPORTED_FORMAT"
    if "MARKET_COLUMNS_MISSING" in reason:
        return "OHLC_SCHEMA_MISSING"
    if "MARKET_TIMESTAMP_MISSING" in reason:
        return "TIMESTAMP_MISSING"
    if "MARKET_COLUMN_COLLISION" in reason:
        return "COLUMN_COLLISION"
    if "INSUFFICIENT_ROWS" in reason:
        return "INSUFFICIENT_ROWS"
    if "Expected object or value" in reason or "JSON" in reason or "ValueError" in reason:
        return "NON_MARKET_OR_MALFORMED_JSON"
    return "OTHER_LOAD_FAILURE"


def audit_sources(
    root: Path,
    runner: Any,
    contract: dict[str, Any],
    market_entries: list[dict[str, Any]],
    required_paths: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for entry in market_entries:
        raw_path = str(entry.get("path") or "")
        required = raw_path in required_paths
        try:
            repo_path = runner.safe_repo_path(raw_path)
            path = root / repo_path
            expected_sha = str(entry.get("sha256") or "")
            actual_sha = runner.sha256_file(path)
            if actual_sha is None or actual_sha != expected_sha:
                raise ValueError("FROZEN_SHA_MISMATCH")
            frame, metadata = runner.normalize_market_frame(runner.load_market_frame(path), contract)
            if len(frame) < MINIMUM_SOURCE_ROWS:
                raise ValueError(f"INSUFFICIENT_ROWS:{len(frame)}")
            timeframe = infer_timeframe(frame, metadata)
            if timeframe is None:
                raise ValueError("TIMEFRAME_UNRESOLVED")
            symbol = infer_symbol(metadata, repo_path)
            seconds = TIMEFRAME_SECONDS.get(timeframe)
            derivable = []
            if seconds is not None:
                for target in TARGET_TIMEFRAMES:
                    if TIMEFRAME_SECONDS[target] >= seconds and TIMEFRAME_SECONDS[target] % seconds == 0:
                        derivable.append(target)
            accepted.append({
                "path": repo_path,
                "sha256": actual_sha,
                "required_by_selected_manifest": required,
                "row_count": int(len(frame)),
                "symbol": symbol,
                "native_timeframe": timeframe,
                "derivable_timeframes": sorted(set(derivable)),
                "classification": "REQUIRED_CANONICAL_MARKET_SOURCE" if required else "AUXILIARY_VALID_MARKET_SOURCE",
            })
        except Exception as exc:
            reason = f"{type(exc).__name__}:{exc}"
            rejected.append({
                "path": raw_path,
                "expected_sha256": str(entry.get("sha256") or ""),
                "required_by_selected_manifest": required,
                "path_role": path_role(raw_path),
                "reason": reason,
                "reason_class": classify_reason(reason),
                "blocking": required,
            })
    accepted.sort(key=lambda row: (not bool(row["required_by_selected_manifest"]), str(row["path"])))
    rejected.sort(key=lambda row: (not bool(row["blocking"]), str(row["path"])))
    return accepted, rejected


def build_audit(
    frozen_manifest: dict[str, Any],
    selected_manifest: dict[str, Any],
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if frozen_manifest.get("state") != "PASS":
        blockers.append("FROZEN_MANIFEST_NOT_PASS")
    if selected_manifest.get("state") != "PASS":
        blockers.append("SELECTED_MANIFEST_NOT_PASS")

    selected_segments = [row for row in selected_manifest.get("selected_segments", []) if isinstance(row, dict)]
    required_paths = sorted({str(row.get("source_path") or "") for row in selected_segments if row.get("source_path")})
    required_accepted = [row for row in accepted if bool(row.get("required_by_selected_manifest"))]
    required_rejected = [row for row in rejected if bool(row.get("blocking"))]
    auxiliary_rejected = [row for row in rejected if not bool(row.get("blocking"))]
    allowlist = [row for row in accepted if "5m" in row.get("derivable_timeframes", []) and "15m" in row.get("derivable_timeframes", [])]

    accepted_required_paths = {str(row.get("path") or "") for row in required_accepted}
    missing_required_paths = sorted(set(required_paths) - accepted_required_paths)
    if required_rejected or missing_required_paths:
        blockers.append(f"REQUIRED_MARKET_SOURCE_REJECTED:{len(set(missing_required_paths))}")

    symbols = sorted({str(row.get("symbol") or "") for row in allowlist if row.get("symbol")})
    timeframes = sorted({tf for row in allowlist for tf in row.get("derivable_timeframes", [])})
    if len(allowlist) < 3:
        blockers.append(f"CANONICAL_ALLOWLIST_SOURCE_LT_3:{len(allowlist)}")
    if len(symbols) < 3:
        blockers.append(f"CANONICAL_ALLOWLIST_SYMBOL_LT_3:{len(symbols)}")
    if not {"5m", "15m"}.issubset(set(timeframes)):
        blockers.append("CANONICAL_ALLOWLIST_TIMEFRAME_INCOMPLETE")

    reason_histogram = dict(sorted(Counter(str(row.get("reason_class") or "") for row in auxiliary_rejected).items()))
    path_role_histogram = dict(sorted(Counter(str(row.get("path_role") or "") for row in auxiliary_rejected).items()))
    blockers = list(dict.fromkeys(blockers))
    state = "PASS_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT" if not blockers else "HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT"
    next_stage = (
        "R7.A4D2_SHORT_SCALP_TIMEFRAME_REDESIGN_PLAN_SOURCE_ALLOWLIST_BIND"
        if not blockers
        else "R7.A4D2_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT"
    )
    audit = {
        "schema": "r7a4d2_short_scalp_frozen_market_source_rejection_audit_v1",
        "official_stage": "R7.A4D2_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "selected_segment_count": len(selected_segments),
        "required_source_count": len(required_paths),
        "required_source_paths": required_paths,
        "accepted_source_count": len(accepted),
        "required_accepted_source_count": len(required_accepted),
        "required_rejected_source_count": len(required_rejected),
        "auxiliary_rejected_source_count": len(auxiliary_rejected),
        "auxiliary_rejects_blocking": False,
        "accepted_sources": accepted,
        "rejected_sources": rejected,
        "auxiliary_reject_reason_histogram": reason_histogram,
        "auxiliary_path_role_histogram": path_role_histogram,
        "canonical_allowlist_source_count": len(allowlist),
        "canonical_allowlist_symbol_count": len(symbols),
        "canonical_allowlist_symbols": symbols,
        "canonical_allowlist_derived_timeframes": timeframes,
        "canonical_allowlist": allowlist,
        "allowlist_contract": {
            "selected_manifest_required_sources_must_pass": True,
            "auxiliary_rejects_are_non_blocking": True,
            "sha_ohlc_timestamp_minimum_rows_required": True,
            "minimum_source_rows": MINIMUM_SOURCE_ROWS,
            "required_derived_timeframes": ["5m", "15m"],
            "source_sha_lineage_required": True,
        },
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "config_mutation_allowed": False,
        "router_mutation_allowed": False,
        "service_mutation_allowed": False,
        "shadow_start_allowed": False,
        "paper_live_order_allowed": False,
        "full_3600_reexecution_allowed": False,
        "event_replay_2880_allowed": False,
        "next_stage": next_stage,
    }
    return audit, blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--runner", required=True)
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runner = load_module(Path(args.runner).resolve(), "r7a4d2_frozen_source_audit_runner")
    contract_path = Path(args.contract).resolve()
    contract = load_json(contract_path)
    frozen_path = root / str(contract["frozen_manifest_path"])
    selected_path = root / str(contract["selected_manifest_path"])
    frozen = load_json(frozen_path)
    selected = load_json(selected_path)
    category_inputs = frozen.get("category_inputs") if isinstance(frozen.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    selected_segments = [row for row in selected.get("selected_segments", []) if isinstance(row, dict)]
    required_paths = {str(row.get("source_path") or "") for row in selected_segments if row.get("source_path")}

    protected = [frozen_path, selected_path, contract_path]
    before = {str(path): sha256_file(path) for path in protected}
    accepted, rejected = audit_sources(root, runner, contract, market_entries, required_paths)
    audit, blockers = build_audit(frozen, selected, accepted, rejected)
    after = {str(path): sha256_file(path) for path in protected}
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
        audit["blockers"] = list(dict.fromkeys(blockers))
        audit["blocker_count"] = len(audit["blockers"])
        audit["state"] = "HOLD_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT_INPUT"
        audit["next_stage"] = "R7.A4D2_SHORT_SCALP_FROZEN_MARKET_SOURCE_REJECTION_AUDIT"
    audit["protected_mutation_path_count"] = len(mutation_paths)
    audit["protected_mutation_paths"] = mutation_paths

    output = root / "runtime/r7a4d2_short_scalp_frozen_market_source_rejection_audit/source_rejection_audit_v1.json"
    atomic_json(output, audit)

    print("STATE=" + str(audit["state"]))
    print("BLOCKER_COUNT=" + str(audit["blocker_count"]))
    print("SELECTED_SEGMENT_COUNT=" + str(audit["selected_segment_count"]))
    print("REQUIRED_SOURCE_COUNT=" + str(audit["required_source_count"]))
    print("ACCEPTED_SOURCE_COUNT=" + str(audit["accepted_source_count"]))
    print("REQUIRED_ACCEPTED_SOURCE_COUNT=" + str(audit["required_accepted_source_count"]))
    print("REQUIRED_REJECTED_SOURCE_COUNT=" + str(audit["required_rejected_source_count"]))
    print("AUXILIARY_REJECTED_SOURCE_COUNT=" + str(audit["auxiliary_rejected_source_count"]))
    print("AUXILIARY_REJECTS_BLOCKING=" + str(audit["auxiliary_rejects_blocking"]).lower())
    print("CANONICAL_ALLOWLIST_SOURCE_COUNT=" + str(audit["canonical_allowlist_source_count"]))
    print("CANONICAL_ALLOWLIST_SYMBOL_COUNT=" + str(audit["canonical_allowlist_symbol_count"]))
    print("CANONICAL_ALLOWLIST_SYMBOLS=" + json.dumps(audit["canonical_allowlist_symbols"]))
    print("CANONICAL_ALLOWLIST_DERIVED_TIMEFRAMES=" + json.dumps(audit["canonical_allowlist_derived_timeframes"]))
    print("AUXILIARY_REJECT_REASON_HISTOGRAM=" + json.dumps(audit["auxiliary_reject_reason_histogram"], sort_keys=True))
    print("AUXILIARY_PATH_ROLE_HISTOGRAM=" + json.dumps(audit["auxiliary_path_role_histogram"], sort_keys=True))
    print("REJECTED_SOURCES=" + json.dumps(audit["rejected_sources"], ensure_ascii=False, sort_keys=True))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("AUDIT_JSON=" + str(output))
    print("NEXT_STAGE=" + str(audit["next_stage"]))
    print("BLOCKERS=" + json.dumps(audit["blockers"], ensure_ascii=False))
    print("RC=" + ("0" if int(audit["blocker_count"]) == 0 else "2"))
    return 0 if int(audit["blocker_count"]) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
