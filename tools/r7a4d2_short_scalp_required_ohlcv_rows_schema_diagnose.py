#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

SAMPLE_LIMIT = 256
OUTPUT_SAMPLE_ROWS = 3
MAX_ROW_WIDTH = 24


def safe_repo_path(value: str) -> str:
    if not value or "\x00" in value or "\\" in value:
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    candidate = value[2:] if value.startswith("./") else value
    pure = PurePosixPath(candidate)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_REPO_PATH:{value!r}")
    return pure.as_posix()


def sha256_file(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except Exception:
        return None


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / max(denominator, 1), 6)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def timestamp_profile(values: list[Any]) -> dict[str, Any]:
    numeric = [finite(value) for value in values]
    valid = [value for value in numeric if value is not None]
    if len(valid) < 3:
        return {
            "finite_ratio": ratio(len(valid), len(values)),
            "strict_increase_ratio": 0.0,
            "unique_ratio": ratio(len(set(valid)), len(valid)),
            "median_value": None,
            "median_delta": None,
            "plausible_epoch": False,
        }
    increases = sum(1 for left, right in zip(valid, valid[1:]) if right > left)
    deltas = [right - left for left, right in zip(valid, valid[1:]) if right > left]
    median_value = statistics.median(valid)
    return {
        "finite_ratio": ratio(len(valid), len(values)),
        "strict_increase_ratio": ratio(increases, len(valid) - 1),
        "unique_ratio": ratio(len(set(valid)), len(valid)),
        "median_value": median_value,
        "median_delta": statistics.median(deltas) if deltas else None,
        "plausible_epoch": 1e8 <= abs(median_value) <= 1e16,
    }


def ohlc_profile(rows: list[list[Any]], open_i: int, high_i: int, low_i: int, close_i: int) -> dict[str, Any]:
    numeric_count = 0
    positive_count = 0
    geometry_count = 0
    nonzero_spread_count = 0
    for row in rows:
        values = [finite(row[index]) if index < len(row) else None for index in (open_i, high_i, low_i, close_i)]
        if any(value is None for value in values):
            continue
        open_v, high_v, low_v, close_v = [float(value) for value in values]
        numeric_count += 1
        if min(open_v, high_v, low_v, close_v) > 0:
            positive_count += 1
        if high_v >= max(open_v, close_v) and low_v <= min(open_v, close_v):
            geometry_count += 1
        if high_v > low_v:
            nonzero_spread_count += 1
    total = len(rows)
    return {
        "numeric_ratio": ratio(numeric_count, total),
        "positive_ratio": ratio(positive_count, total),
        "geometry_ratio": ratio(geometry_count, total),
        "nonzero_spread_ratio": ratio(nonzero_spread_count, total),
    }


def continuity_profile(rows: list[list[Any]], open_i: int, high_i: int, low_i: int, close_i: int) -> dict[str, Any]:
    gap_pcts: list[float] = []
    gap_to_ranges: list[float] = []
    exact_count = 0
    valid_count = 0
    for previous, current in zip(rows, rows[1:]):
        if max(open_i, high_i, low_i, close_i) >= min(len(previous), len(current)):
            continue
        previous_close = finite(previous[close_i])
        current_open = finite(current[open_i])
        previous_high = finite(previous[high_i])
        previous_low = finite(previous[low_i])
        current_high = finite(current[high_i])
        current_low = finite(current[low_i])
        if any(value is None for value in (previous_close, current_open, previous_high, previous_low, current_high, current_low)):
            continue
        previous_close = float(previous_close)
        current_open = float(current_open)
        gap = abs(current_open - previous_close)
        price_scale = max(abs(previous_close), 1e-12)
        range_scale = max(
            abs(float(previous_high) - float(previous_low)),
            abs(float(current_high) - float(current_low)),
            price_scale * 1e-10,
        )
        gap_pcts.append(gap / price_scale)
        gap_to_ranges.append(gap / range_scale)
        if gap <= price_scale * 1e-10:
            exact_count += 1
        valid_count += 1
    return {
        "valid_pair_ratio": ratio(valid_count, max(len(rows) - 1, 1)),
        "exact_link_ratio": ratio(exact_count, valid_count),
        "median_gap_pct": statistics.median(gap_pcts) if gap_pcts else None,
        "p95_gap_pct": percentile(gap_pcts, 0.95),
        "median_gap_to_range": statistics.median(gap_to_ranges) if gap_to_ranges else None,
        "p95_gap_to_range": percentile(gap_to_ranges, 0.95),
    }


def candidate_score(timestamp: dict[str, Any], ohlc: dict[str, Any], continuity: dict[str, Any]) -> float:
    median_gap_to_range = continuity.get("median_gap_to_range")
    continuity_quality = 0.0 if median_gap_to_range is None else 1.0 / (1.0 + float(median_gap_to_range))
    score = (
        2.0 * float(timestamp["finite_ratio"])
        + 2.0 * float(timestamp["strict_increase_ratio"])
        + 1.0 * float(timestamp["unique_ratio"])
        + (1.0 if timestamp["plausible_epoch"] else 0.0)
        + 2.0 * float(ohlc["numeric_ratio"])
        + 2.0 * float(ohlc["positive_ratio"])
        + 4.0 * float(ohlc["geometry_ratio"])
        + 1.0 * float(ohlc["nonzero_spread_ratio"])
        + 3.0 * float(continuity["exact_link_ratio"])
        + 3.0 * continuity_quality
    )
    return round(score, 9)


def orientation_is_resolved(best: dict[str, Any], second: dict[str, Any] | None) -> bool:
    if second is None:
        return True
    best_cont = best["continuity_profile"]
    second_cont = second["continuity_profile"]
    exact_advantage = float(best_cont["exact_link_ratio"]) - float(second_cont["exact_link_ratio"])
    best_gap = best_cont.get("median_gap_to_range")
    second_gap = second_cont.get("median_gap_to_range")
    gap_advantage = False
    if best_gap is not None and second_gap is not None:
        best_gap = float(best_gap)
        second_gap = float(second_gap)
        gap_advantage = second_gap > 0 and best_gap <= second_gap * 0.8 and (second_gap - best_gap) >= 1e-9
    return exact_advantage >= 0.05 or gap_advantage or float(best["score"]) - float(second["score"]) >= 0.25


def diagnose_matrix_rows(rows: list[Any]) -> dict[str, Any]:
    matrix_rows = [list(row) for row in rows[:SAMPLE_LIMIT] if isinstance(row, (list, tuple))]
    width_histogram = Counter(len(row) for row in matrix_rows)
    if not matrix_rows or not width_histogram:
        return {
            "matrix_row_count": len(matrix_rows),
            "row_width_histogram": dict(sorted(width_histogram.items())),
            "layout_candidates": [],
            "layout_ready": False,
            "reason": "ROWS_NOT_MATRIX",
        }
    modal_width, modal_count = width_histogram.most_common(1)[0]
    consistent_rows = [row for row in matrix_rows if len(row) == modal_width]
    if modal_width < 5 or modal_width > MAX_ROW_WIDTH:
        return {
            "matrix_row_count": len(matrix_rows),
            "modal_width": modal_width,
            "modal_width_ratio": ratio(modal_count, len(matrix_rows)),
            "row_width_histogram": dict(sorted(width_histogram.items())),
            "layout_candidates": [],
            "layout_ready": False,
            "reason": "ROW_WIDTH_UNSUPPORTED",
        }

    timestamp_candidates: list[tuple[int, dict[str, Any]]] = []
    for index in range(modal_width):
        profile = timestamp_profile([row[index] for row in consistent_rows])
        if (
            profile["finite_ratio"] >= 0.95
            and profile["strict_increase_ratio"] >= 0.95
            and profile["unique_ratio"] >= 0.95
            and profile["plausible_epoch"]
        ):
            timestamp_candidates.append((index, profile))

    layouts: list[dict[str, Any]] = []
    for timestamp_i, timestamp in timestamp_candidates:
        price_indices = [index for index in range(modal_width) if index != timestamp_i]
        for open_i, high_i, low_i, close_i in itertools.permutations(price_indices, 4):
            ohlc = ohlc_profile(consistent_rows, open_i, high_i, low_i, close_i)
            if ohlc["numeric_ratio"] < 0.95 or ohlc["geometry_ratio"] < 0.95 or ohlc["positive_ratio"] < 0.95:
                continue
            continuity = continuity_profile(consistent_rows, open_i, high_i, low_i, close_i)
            if continuity["valid_pair_ratio"] < 0.95:
                continue
            layouts.append({
                "timestamp_index": timestamp_i,
                "open_index": open_i,
                "high_index": high_i,
                "low_index": low_i,
                "close_index": close_i,
                "timestamp_profile": timestamp,
                "ohlc_profile": ohlc,
                "continuity_profile": continuity,
                "score": candidate_score(timestamp, ohlc, continuity),
            })
    layouts.sort(
        key=lambda row: (
            -float(row["score"]),
            float(row["continuity_profile"].get("median_gap_to_range") or 0.0),
            row["timestamp_index"],
            row["open_index"],
            row["high_index"],
            row["low_index"],
            row["close_index"],
        )
    )
    top = layouts[:10]
    unique_best = bool(top and orientation_is_resolved(top[0], top[1] if len(top) > 1 else None))
    layout_ready = bool(
        top
        and unique_best
        and float(top[0]["ohlc_profile"]["geometry_ratio"]) >= 0.99
        and float(top[0]["timestamp_profile"]["strict_increase_ratio"]) >= 0.99
        and float(top[0]["continuity_profile"]["valid_pair_ratio"]) >= 0.99
    )
    return {
        "matrix_row_count": len(matrix_rows),
        "modal_width": modal_width,
        "modal_width_ratio": ratio(modal_count, len(matrix_rows)),
        "row_width_histogram": {str(key): value for key, value in sorted(width_histogram.items())},
        "row_type_histogram": dict(sorted(Counter(type(row).__name__ for row in rows[:SAMPLE_LIMIT]).items())),
        "sample_rows": [row[:MAX_ROW_WIDTH] for row in matrix_rows[:OUTPUT_SAMPLE_ROWS]],
        "timestamp_candidate_indices": [index for index, _ in timestamp_candidates],
        "layout_candidate_count": len(layouts),
        "layout_candidates": top,
        "layout_ready": layout_ready,
        "unique_best_layout": unique_best,
        "reason": "UNIQUE_LAYOUT_READY" if layout_ready else "LAYOUT_AMBIGUOUS_OR_INVALID",
    }


def inspect_source(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    repo_path = safe_repo_path(str(entry.get("path") or ""))
    path = root / repo_path
    expected_sha = str(entry.get("sha256") or "")
    actual_sha = sha256_file(path)
    if actual_sha is None:
        raise ValueError("SOURCE_FILE_MISSING_OR_SYMLINK")
    if actual_sha != expected_sha:
        raise ValueError("FROZEN_SHA_MISMATCH")
    root_value = load_json(path)
    if not isinstance(root_value, dict):
        raise ValueError("TOP_LEVEL_OBJECT_REQUIRED")
    rows = root_value.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"ROWS_LIST_REQUIRED:{type(rows).__name__}")
    matrix = diagnose_matrix_rows(rows)
    declared_row_count = root_value.get("row_count")
    return {
        "path": repo_path,
        "expected_sha256": expected_sha,
        "actual_sha256": actual_sha,
        "symbol": root_value.get("symbol"),
        "interval": root_value.get("interval"),
        "top_level_keys": sorted(str(key) for key in root_value.keys()),
        "declared_row_count": declared_row_count,
        "actual_row_count": len(rows),
        "declared_actual_row_count_match": finite(declared_row_count) == float(len(rows)) if finite(declared_row_count) is not None else False,
        **matrix,
    }


def build_audit(frozen: dict[str, Any], selected: dict[str, Any], inspected: list[dict[str, Any]], failures: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if frozen.get("state") != "PASS":
        blockers.append("FROZEN_MANIFEST_NOT_PASS")
    if selected.get("state") != "PASS":
        blockers.append("SELECTED_MANIFEST_NOT_PASS")
    selected_segments = [row for row in selected.get("selected_segments", []) if isinstance(row, dict)]
    required_paths = sorted({str(row.get("source_path") or "") for row in selected_segments if row.get("source_path")})
    ready = [row for row in inspected if bool(row.get("layout_ready"))]
    unresolved = [row for row in inspected if not bool(row.get("layout_ready"))]
    if failures:
        blockers.append(f"ROWS_SCHEMA_DIAGNOSE_FAILURE:{len(failures)}")
    if unresolved:
        blockers.append(f"ROWS_LAYOUT_UNRESOLVED:{len(unresolved)}")
    if len(inspected) != len(required_paths):
        blockers.append(f"INSPECTED_SOURCE_COUNT_MISMATCH:{len(inspected)}:{len(required_paths)}")

    layout_signatures = []
    for row in ready:
        top = row.get("layout_candidates") if isinstance(row.get("layout_candidates"), list) else []
        if not top:
            continue
        candidate = top[0]
        layout_signatures.append((
            int(row.get("modal_width", -1)),
            int(candidate["timestamp_index"]),
            int(candidate["open_index"]),
            int(candidate["high_index"]),
            int(candidate["low_index"]),
            int(candidate["close_index"]),
        ))
    unique_signatures = sorted(set(layout_signatures))
    shared_layout = len(ready) == len(required_paths) and len(unique_signatures) == 1
    if ready and not shared_layout:
        blockers.append(f"REQUIRED_SOURCE_LAYOUT_DIVERGENCE:{len(unique_signatures)}")

    blockers = list(dict.fromkeys(blockers))
    state = "PASS_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE" if not blockers else "HOLD_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_INPUT"
    next_stage = "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_SCHEMA_ADAPTER_BIND" if not blockers else "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE"
    audit = {
        "schema": "r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose_v1",
        "official_stage": "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "selected_segment_count": len(selected_segments),
        "required_source_count": len(required_paths),
        "inspected_source_count": len(inspected),
        "layout_ready_source_count": len(ready),
        "unresolved_source_count": len(unresolved),
        "failure_count": len(failures),
        "shared_layout": shared_layout,
        "layout_signature_count": len(unique_signatures),
        "layout_signatures": [list(signature) for signature in unique_signatures],
        "source_diagnostics": inspected,
        "failures": failures,
        "source_file_mutation_allowed": False,
        "frozen_manifest_mutation_allowed": False,
        "selected_manifest_mutation_allowed": False,
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
    parser.add_argument("--contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract_path = Path(args.contract).resolve()
    contract = load_json(contract_path)
    frozen_path = root / str(contract["frozen_manifest_path"])
    selected_path = root / str(contract["selected_manifest_path"])
    frozen = load_json(frozen_path)
    selected = load_json(selected_path)

    selected_segments = [row for row in selected.get("selected_segments", []) if isinstance(row, dict)]
    required_paths = sorted({str(row.get("source_path") or "") for row in selected_segments if row.get("source_path")})
    category_inputs = frozen.get("category_inputs") if isinstance(frozen.get("category_inputs"), dict) else {}
    entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    entry_by_path = {str(row.get("path") or ""): row for row in entries}

    protected = [frozen_path, selected_path, contract_path]
    before = {str(path): sha256_file(path) for path in protected}
    inspected: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for repo_path in required_paths:
        entry = entry_by_path.get(repo_path)
        if entry is None:
            failures.append({"path": repo_path, "reason": "FROZEN_MARKET_ENTRY_MISSING"})
            continue
        try:
            inspected.append(inspect_source(root, entry))
        except Exception as exc:
            failures.append({"path": repo_path, "reason": f"{type(exc).__name__}:{exc}"})
    inspected.sort(key=lambda row: str(row.get("path") or ""))
    failures.sort(key=lambda row: str(row.get("path") or ""))

    audit, blockers = build_audit(frozen, selected, inspected, failures)
    after = {str(path): sha256_file(path) for path in protected}
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if mutation_paths:
        blockers.append("PROTECTED_INPUT_MUTATION_DETECTED")
        audit["blockers"] = list(dict.fromkeys(blockers))
        audit["blocker_count"] = len(audit["blockers"])
        audit["state"] = "HOLD_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE_INPUT"
        audit["next_stage"] = "R7.A4D2_SHORT_SCALP_REQUIRED_OHLCV_ROWS_SCHEMA_DIAGNOSE"
    audit["protected_mutation_path_count"] = len(mutation_paths)
    audit["protected_mutation_paths"] = mutation_paths

    output = root / "runtime/r7a4d2_short_scalp_required_ohlcv_rows_schema_diagnose/rows_schema_diagnose_v1.json"
    atomic_json(output, audit)

    print("STATE=" + str(audit["state"]))
    print("BLOCKER_COUNT=" + str(audit["blocker_count"]))
    print("REQUIRED_SOURCE_COUNT=" + str(audit["required_source_count"]))
    print("INSPECTED_SOURCE_COUNT=" + str(audit["inspected_source_count"]))
    print("LAYOUT_READY_SOURCE_COUNT=" + str(audit["layout_ready_source_count"]))
    print("UNRESOLVED_SOURCE_COUNT=" + str(audit["unresolved_source_count"]))
    print("FAILURE_COUNT=" + str(audit["failure_count"]))
    print("SHARED_LAYOUT=" + str(audit["shared_layout"]).lower())
    print("LAYOUT_SIGNATURE_COUNT=" + str(audit["layout_signature_count"]))
    print("LAYOUT_SIGNATURES=" + json.dumps(audit["layout_signatures"]))
    print("SOURCE_DIAGNOSTICS=" + json.dumps(audit["source_diagnostics"], ensure_ascii=False, sort_keys=True))
    print("FAILURES=" + json.dumps(audit["failures"], ensure_ascii=False, sort_keys=True))
    print("PROTECTED_MUTATION_PATH_COUNT=" + str(audit["protected_mutation_path_count"]))
    print("AUDIT_JSON=" + str(output))
    print("NEXT_STAGE=" + str(audit["next_stage"]))
    print("BLOCKERS=" + json.dumps(audit["blockers"], ensure_ascii=False))
    print("RC=" + ("0" if int(audit["blocker_count"]) == 0 else "2"))
    return 0 if int(audit["blocker_count"]) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
