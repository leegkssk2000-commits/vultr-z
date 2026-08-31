from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import importlib.util
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_EMA_RIBBON_INTRATRADE_PATH_AUDIT_V1"
SCHEMA = "zel.ema_ribbon_intratrade_path_audit.receipt.v1"
STRATEGY_ID = "ema_ribbon_scalp"
EXPECTED_TRADES = 424
EXPECTED_WINDOWS = {"1m_w1", "1m_w2", "1m_w3"}
MAX_SOURCE_BYTES = 2_000_000

ENTRY_PRICE_KEYS = (
    "entry_price",
    "entry_px",
    "open_price",
    "entry",
)
EXIT_PRICE_KEYS = (
    "exit_price",
    "exit_px",
    "close_price",
    "exit",
)
STOP_PRICE_KEYS = (
    "initial_stop_price",
    "initial_stop",
    "stop_loss_price",
    "stop_price",
    "stop_loss",
    "sl_price",
    "sl",
)
RISK_DISTANCE_KEYS = (
    "initial_risk_price",
    "initial_risk_distance",
    "risk_distance",
    "one_r_price",
    "r_price",
)
SIDE_KEYS = ("side", "direction", "position_side")
ENTRY_TS_KEYS = ("entry_ts", "entry_time", "opened_at")
EXIT_TS_KEYS = ("exit_ts", "exit_time", "closed_at")
REALIZED_R_KEYS = ("realized_R", "net_R", "pnl_r", "net_reference_R")
MFE_R_KEYS = ("MFE_R", "mfe_R", "mfe_r", "max_favorable_excursion_R")
MAE_R_KEYS = ("MAE_R", "mae_R", "mae_r", "max_adverse_excursion_R")


def stable_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def first_number(row: Mapping[str, Any], keys: Sequence[str]) -> tuple[str | None, float | None]:
    for key in keys:
        value = finite(row.get(key))
        if value is not None:
            return key, value
    return None, None


def first_text(row: Mapping[str, Any], keys: Sequence[str]) -> tuple[str | None, str | None]:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return key, str(value).strip()
    return None, None


def parse_timestamp(pd_module: Any, value: Any) -> int | None:
    try:
        timestamp = pd_module.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return int(timestamp.value)
    except Exception:
        return None


def event_id(row: Mapping[str, Any]) -> str:
    return str(row.get("event_id") or row.get("trade_id") or row.get("position_id") or "").strip()


def strategy_id(row: Mapping[str, Any]) -> str:
    return str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or row.get("source_strategy_id") or "")


def window_id(row: Mapping[str, Any]) -> str:
    return str(row.get("window_id") or row.get("window") or row.get("dataset_window") or "unknown")


def symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or row.get("market") or "").upper()


def normalized_side(row: Mapping[str, Any]) -> str:
    _, raw = first_text(row, SIDE_KEYS)
    value = (raw or "unknown").lower()
    if value in {"buy", "bull", "long"}:
        return "long"
    if value in {"sell", "bear", "short"}:
        return "short"
    return value


def realized_r(row: Mapping[str, Any]) -> float:
    return first_number(row, REALIZED_R_KEYS)[1] or 0.0


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (
            str(first_text(row, EXIT_TS_KEYS)[1] or ""),
            event_id(row),
        ),
    )
    values = [realized_r(row) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    gross_loss = abs(sum(losses))
    mfe_values = [first_number(row, MFE_R_KEYS)[1] for row in rows]
    mae_values = [first_number(row, MAE_R_KEYS)[1] for row in rows]
    valid_mfe = [value for value in mfe_values if value is not None]
    valid_mae = [value for value in mae_values if value is not None]
    return {
        "trade_count": len(rows),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else None,
        "net_R": sum(values),
        "gross_profit_R": sum(wins),
        "gross_loss_R": gross_loss,
        "profit_factor": sum(wins) / gross_loss if gross_loss > 0 else None,
        "max_drawdown_R": max_drawdown,
        "average_MFE_R": sum(valid_mfe) / len(valid_mfe) if valid_mfe else None,
        "average_MAE_R": sum(valid_mae) / len(valid_mae) if valid_mae else None,
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(f"ROW_OBJECT_REQUIRED:{line_number}")
            if strategy_id(value) == STRATEGY_ID:
                rows.append(value)
    return rows


def field_inventory(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    numeric_counts: Counter[str] = Counter()
    text_counts: Counter[str] = Counter()
    for row in rows:
        for key, value in row.items():
            if value is None:
                continue
            counts[str(key)] += 1
            if finite(value) is not None:
                numeric_counts[str(key)] += 1
            elif isinstance(value, str) and value.strip():
                text_counts[str(key)] += 1
    keys = sorted(counts)
    return {
        "field_count": len(keys),
        "fields": [
            {
                "key": key,
                "coverage_count": counts[key],
                "coverage_pct": counts[key] / max(len(rows), 1) * 100.0,
                "numeric_count": numeric_counts[key],
                "text_count": text_counts[key],
            }
            for key in keys
        ],
    }


def key_group_coverage(rows: Sequence[Mapping[str, Any]], groups: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, keys in groups.items():
        selected = Counter()
        complete = 0
        for row in rows:
            key, value = first_number(row, keys)
            if value is None:
                key_text, text = first_text(row, keys)
                if text is not None:
                    key = key_text
                    value = 1.0
            if value is not None:
                complete += 1
                selected[str(key)] += 1
        output[name] = {
            "coverage_count": complete,
            "coverage_pct": complete / max(len(rows), 1) * 100.0,
            "selected_key_counts": dict(sorted(selected.items())),
            "candidate_keys": list(keys),
        }
    return output


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_file(data_root: Path, row: Mapping[str, Any]) -> Path:
    for key in ("path", "file", "csv_path", "relative_path"):
        value = row.get(key)
        if isinstance(value, str) and value:
            path = Path(value)
            return path if path.is_absolute() else data_root / path
    raise RuntimeError(f"DATA_FILE_PATH_MISSING:{row}")


def risk_distance(row: Mapping[str, Any], entry_price: float | None) -> tuple[str, float | None]:
    key, explicit = first_number(row, RISK_DISTANCE_KEYS)
    if explicit is not None and explicit > 0:
        return f"explicit:{key}", abs(explicit)
    stop_key, stop = first_number(row, STOP_PRICE_KEYS)
    if entry_price is not None and stop is not None and abs(entry_price - stop) > 0:
        return f"entry_minus_stop:{stop_key}", abs(entry_price - stop)
    return "missing", None


def path_excursions(
    side: str,
    entry_price: float,
    path_frame: Any,
) -> tuple[float | None, float | None]:
    if path_frame.empty:
        return None, None
    high = finite(path_frame["high"].max())
    low = finite(path_frame["low"].min())
    if high is None or low is None:
        return None, None
    if side == "long":
        return max(0.0, high - entry_price), min(0.0, low - entry_price)
    if side == "short":
        return max(0.0, entry_price - low), min(0.0, entry_price - high)
    return None, None


def path_audit(
    rows: Sequence[Mapping[str, Any]],
    engine: Any,
    manifest: Mapping[str, Any],
    data_root: Path,
) -> dict[str, Any]:
    files = list(manifest.get("files") or [])
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for file_row in files:
        if isinstance(file_row, Mapping):
            file_map[
                (
                    str(file_row.get("window_id") or file_row.get("window") or "unknown"),
                    str(file_row.get("symbol") or "").upper(),
                )
            ] = file_row

    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(window_id(row), symbol(row))].append(row)

    mapped_count = 0
    exact_entry_count = 0
    exact_exit_count = 0
    valid_path_count = 0
    risk_known_count = 0
    explicit_entry_count = 0
    entry_bar_open_fallback_count = 0
    mfe_compare_count = 0
    mae_compare_count = 0
    mfe_abs_errors: list[float] = []
    mae_abs_errors: list[float] = []
    exposure_bar_counts: list[int] = []
    reasons: Counter[str] = Counter()
    risk_sources: Counter[str] = Counter()
    duplicate_timestamp_lanes = 0
    lane_receipts: list[dict[str, Any]] = []

    for lane, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane)
        if file_row is None:
            reasons["LANE_FILE_MISSING"] += len(lane_rows)
            continue
        frame_path = resolve_file(data_root, file_row)
        frame = engine.frame_from_csv(frame_path)
        index_by_timestamp: dict[int, int] = {}
        duplicates = 0
        for index, value in enumerate(frame["timestamp"].tolist()):
            epoch = parse_timestamp(engine.pd, value)
            if epoch is None:
                continue
            if epoch in index_by_timestamp:
                duplicates += 1
            index_by_timestamp[epoch] = index
        if duplicates:
            duplicate_timestamp_lanes += 1
        lane_mapped = 0
        for row in lane_rows:
            entry_epoch = parse_timestamp(engine.pd, first_text(row, ENTRY_TS_KEYS)[1])
            exit_epoch = parse_timestamp(engine.pd, first_text(row, EXIT_TS_KEYS)[1])
            entry_index = index_by_timestamp.get(entry_epoch) if entry_epoch is not None else None
            exit_index = index_by_timestamp.get(exit_epoch) if exit_epoch is not None else None
            if entry_index is None:
                reasons["ENTRY_TIMESTAMP_NOT_FOUND"] += 1
                continue
            exact_entry_count += 1
            if exit_index is None:
                reasons["EXIT_TIMESTAMP_NOT_FOUND"] += 1
                continue
            exact_exit_count += 1
            if exit_index < entry_index:
                reasons["EXIT_BEFORE_ENTRY"] += 1
                continue
            path = frame.iloc[entry_index : exit_index + 1].copy()
            if path.empty:
                reasons["PATH_EMPTY"] += 1
                continue
            valid_path_count += 1
            mapped_count += 1
            lane_mapped += 1
            exposure_bar_counts.append(len(path))

            _, entry = first_number(row, ENTRY_PRICE_KEYS)
            if entry is not None:
                explicit_entry_count += 1
            else:
                entry = finite(frame["open"].iloc[entry_index])
                if entry is not None:
                    entry_bar_open_fallback_count += 1
            side = normalized_side(row)
            if entry is None or side not in {"long", "short"}:
                reasons["ENTRY_PRICE_OR_SIDE_MISSING"] += 1
                continue
            risk_source, risk = risk_distance(row, entry)
            risk_sources[risk_source] += 1
            if risk is None or risk <= 0:
                reasons["INITIAL_RISK_MISSING"] += 1
                continue
            risk_known_count += 1
            favorable_px, adverse_px = path_excursions(side, entry, path)
            if favorable_px is None or adverse_px is None:
                reasons["PATH_EXCURSION_INVALID"] += 1
                continue
            ledger_mfe = first_number(row, MFE_R_KEYS)[1]
            ledger_mae = first_number(row, MAE_R_KEYS)[1]
            reconstructed_mfe = favorable_px / risk
            reconstructed_mae = adverse_px / risk
            if ledger_mfe is not None:
                mfe_compare_count += 1
                mfe_abs_errors.append(abs(reconstructed_mfe - ledger_mfe))
            if ledger_mae is not None:
                mae_compare_count += 1
                mae_abs_errors.append(abs(reconstructed_mae - ledger_mae))
        lane_receipts.append(
            {
                "window_id": lane[0],
                "symbol": lane[1],
                "trade_count": len(lane_rows),
                "mapped_count": lane_mapped,
                "frame_sha256": sha256_file(frame_path),
                "frame_rows": len(frame),
                "duplicate_timestamp_count": duplicates,
            }
        )

    return {
        "manifest_file_count": len(files),
        "used_lane_count": len(grouped),
        "lane_receipts": lane_receipts,
        "mapped_count": mapped_count,
        "exact_entry_count": exact_entry_count,
        "exact_exit_count": exact_exit_count,
        "valid_path_count": valid_path_count,
        "risk_known_count": risk_known_count,
        "explicit_entry_price_count": explicit_entry_count,
        "entry_bar_open_fallback_count": entry_bar_open_fallback_count,
        "mfe_compare_count": mfe_compare_count,
        "mae_compare_count": mae_compare_count,
        "mfe_mean_abs_error_R": sum(mfe_abs_errors) / len(mfe_abs_errors) if mfe_abs_errors else None,
        "mfe_max_abs_error_R": max(mfe_abs_errors) if mfe_abs_errors else None,
        "mae_mean_abs_error_R": sum(mae_abs_errors) / len(mae_abs_errors) if mae_abs_errors else None,
        "mae_max_abs_error_R": max(mae_abs_errors) if mae_abs_errors else None,
        "minimum_path_bars": min(exposure_bar_counts) if exposure_bar_counts else None,
        "maximum_path_bars": max(exposure_bar_counts) if exposure_bar_counts else None,
        "risk_source_counts": dict(sorted(risk_sources.items())),
        "failure_reason_counts": dict(sorted(reasons.items())),
        "duplicate_timestamp_lane_count": duplicate_timestamp_lanes,
    }


def loss_clusters(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    gross_loss: Counter[str] = Counter()
    by_window: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        value = realized_r(row)
        if value >= 0:
            continue
        mfe = first_number(row, MFE_R_KEYS)[1]
        mae = first_number(row, MAE_R_KEYS)[1]
        labels: list[str] = []
        if mfe is not None and mfe >= 0.50:
            labels.append("favorable_then_loss_mfe_ge_0_50R")
        if mfe is not None and mfe < 0.25:
            labels.append("immediate_fail_mfe_lt_0_25R")
        if mae is not None and mae <= -0.75:
            labels.append("deep_adverse_mae_le_neg_0_75R")
        if not labels:
            labels.append("other_loss")
        for label in labels:
            counts[label] += 1
            gross_loss[label] += -value
            by_window[label][window_id(row)] += 1
    return {
        label: {
            "loss_count": counts[label],
            "gross_loss_R": gross_loss[label],
            "window_loss_counts": dict(sorted(by_window[label].items())),
        }
        for label in sorted(counts)
    }


def source_candidates(source_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "archive", "archives", "backup", "backups"}
    for base, directories, files in os.walk(source_root):
        directories[:] = [name for name in directories if name not in skip]
        for name in files:
            path = Path(base) / name
            if path.suffix not in {".py", ".json"}:
                continue
            try:
                stat = path.stat()
                if stat.st_size <= 0 or stat.st_size > MAX_SOURCE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if STRATEGY_ID not in text:
                continue
            row: dict[str, Any] = {
                "path": str(path.resolve()),
                "relative_path": str(path.resolve().relative_to(source_root.resolve())),
                "sha256": sha256_file(path),
                "size_bytes": stat.st_size,
                "suffix": path.suffix,
                "raw_code_published": False,
            }
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                except SyntaxError as exc:
                    row["parse_error"] = f"{type(exc).__name__}:{exc.lineno}"
                    row["classes"] = []
                    row["functions"] = []
                    row["return_dict_keys"] = []
                else:
                    row["classes"] = sorted({node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)})
                    row["functions"] = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
                    return_keys: set[str] = set()
                    for node in ast.walk(tree):
                        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                            continue
                        for key in node.value.keys:
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                return_keys.add(key.value)
                    row["return_dict_keys"] = sorted(return_keys)
            candidates.append(row)
    candidates.sort(key=lambda row: (row["relative_path"], row["sha256"] or ""))
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    report = json.loads((args.terminal_root / "report.json").read_text(encoding="utf-8"))
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")
    source_root = Path(source_root_raw).resolve()
    rows = read_rows(args.terminal_root / "trades.jsonl.gz")
    engine = load_module(args.engine, "zel_ema_intratrade_engine")
    manifest_result = engine.validate_data_manifest(args.data_root, "1m")
    manifest = manifest_result[0] if isinstance(manifest_result, tuple) else manifest_result
    if not isinstance(manifest, Mapping):
        raise RuntimeError("DATA_MANIFEST_INVALID")

    inventory = field_inventory(rows)
    coverage = key_group_coverage(
        rows,
        {
            "entry_price": ENTRY_PRICE_KEYS,
            "exit_price": EXIT_PRICE_KEYS,
            "stop_price": STOP_PRICE_KEYS,
            "risk_distance": RISK_DISTANCE_KEYS,
            "side": SIDE_KEYS,
            "entry_ts": ENTRY_TS_KEYS,
            "exit_ts": EXIT_TS_KEYS,
            "realized_R": REALIZED_R_KEYS,
            "MFE_R": MFE_R_KEYS,
            "MAE_R": MAE_R_KEYS,
        },
    )
    path = path_audit(rows, engine, manifest, args.data_root)
    sources = source_candidates(source_root)
    overall = metrics(rows)
    by_window = {
        window: metrics([row for row in rows if window_id(row) == window])
        for window in sorted(EXPECTED_WINDOWS)
    }
    clusters = loss_clusters(rows)

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, actual: Any, expected: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "actual": actual, "expected": expected})

    check("trade_count", len(rows) == EXPECTED_TRADES, len(rows), EXPECTED_TRADES)
    check("window_set", {window_id(row) for row in rows} == EXPECTED_WINDOWS, sorted({window_id(row) for row in rows}), sorted(EXPECTED_WINDOWS))
    check("event_id_complete", all(event_id(row) for row in rows), sum(bool(event_id(row)) for row in rows), EXPECTED_TRADES)
    check("event_id_unique", len({event_id(row) for row in rows}) == EXPECTED_TRADES, len({event_id(row) for row in rows}), EXPECTED_TRADES)
    check("entry_timestamp_complete", coverage["entry_ts"]["coverage_count"] == EXPECTED_TRADES, coverage["entry_ts"]["coverage_count"], EXPECTED_TRADES)
    check("exit_timestamp_complete", coverage["exit_ts"]["coverage_count"] == EXPECTED_TRADES, coverage["exit_ts"]["coverage_count"], EXPECTED_TRADES)
    check("side_complete", coverage["side"]["coverage_count"] == EXPECTED_TRADES, coverage["side"]["coverage_count"], EXPECTED_TRADES)
    check("mfe_complete", coverage["MFE_R"]["coverage_count"] == EXPECTED_TRADES, coverage["MFE_R"]["coverage_count"], EXPECTED_TRADES)
    check("mae_complete", coverage["MAE_R"]["coverage_count"] == EXPECTED_TRADES, coverage["MAE_R"]["coverage_count"], EXPECTED_TRADES)
    check("entry_path_exact", path["exact_entry_count"] == EXPECTED_TRADES, path["exact_entry_count"], EXPECTED_TRADES)
    check("exit_path_exact", path["exact_exit_count"] == EXPECTED_TRADES, path["exact_exit_count"], EXPECTED_TRADES)
    check("valid_path_complete", path["valid_path_count"] == EXPECTED_TRADES, path["valid_path_count"], EXPECTED_TRADES)
    check("risk_basis_complete", path["risk_known_count"] == EXPECTED_TRADES, path["risk_known_count"], EXPECTED_TRADES)
    check("source_candidate_present", len(sources) > 0, len(sources), ">0")
    check("duplicate_timestamp_free", path["duplicate_timestamp_lane_count"] == 0, path["duplicate_timestamp_lane_count"], 0)
    if path["mfe_compare_count"] == EXPECTED_TRADES:
        check("mfe_path_parity", finite(path["mfe_mean_abs_error_R"]) is not None and float(path["mfe_mean_abs_error_R"]) <= 0.05, path["mfe_mean_abs_error_R"], "<=0.05R mean absolute error")
    if path["mae_compare_count"] == EXPECTED_TRADES:
        check("mae_path_parity", finite(path["mae_mean_abs_error_R"]) is not None and float(path["mae_mean_abs_error_R"]) <= 0.05, path["mae_mean_abs_error_R"], "<=0.05R mean absolute error")

    blockers = [row["name"] for row in checks if not row["passed"]]
    replay_ready = not blockers
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_EMA_RIBBON_INTRATRADE_PATH_READY" if replay_ready else "HOLD_EMA_RIBBON_INTRATRADE_PATH_INCOMPLETE",
        "strategy_id": STRATEGY_ID,
        "source_root": str(source_root),
        "engine_path": str(args.engine.resolve()),
        "engine_sha256": sha256_file(args.engine),
        "data_root": str(args.data_root.resolve()),
        "trade_count": len(rows),
        "overall": overall,
        "by_window": by_window,
        "loss_clusters": clusters,
        "key_group_coverage": coverage,
        "field_inventory": inventory,
        "path_audit": path,
        "source_candidates": sources,
        "checks": checks,
        "blockers": blockers,
        "intratrade_replay_ready": replay_ready,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "raw_price_data_published": False,
        "raw_code_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "RUN_EMA_RIBBON_TRAILING_COUNTERFACTUAL" if replay_ready else "RESOLVE_SINGLE_PATH_CONTRACT_BLOCKER",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
