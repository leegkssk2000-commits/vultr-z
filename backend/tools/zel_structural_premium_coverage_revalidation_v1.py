from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_STRUCTURAL_PREMIUM_COVERAGE_REVALIDATION_V1"
SCHEMA = "zel.structural_premium.coverage_revalidation.v1"
EXPECTED_SOURCE_DATASET_SHA256 = "53676bb379635c6f81908be2c20e1598e00bffa4d0e08d8b492646416b8a46d8"
EXPECTED_SOURCE_VERIFY_RECEIPT_SHA256 = "b7d04a66c9088803521daf8f9063e032fda20dd3b541ab6e0159ce720c68ba39"
EXPECTED_SOURCE_FILE_COUNT = 10
EXPECTED_SOURCE_TOTAL_ROWS = 1_072_800
EXPECTED_POST_GAP_ROWS_PER_SYMBOL = 192_030
WINDOW_ROWS = 64_010
EXPECTED_EXPANDED_TOTAL_ROWS = 960_150
SYMBOLS = ("BTCUSDT", "ETHUSDT", "LINKUSDT", "SOLUSDT", "XRPUSDT")
MAIN = ("vwap_revert", "support_resistance")
RESERVE = ("liquidity_sweep", "trend_rider")
FILTER_ONLY = ("market_structure",)
ENTRY_OWNERS = MAIN + RESERVE
WINDOWS = ("W1", "W2", "W3")
WINDOW_IDS = {"W1": "1m_w1", "W2": "1m_w2", "W3": "1m_w3"}
R_FIELDS = (
    "realized_R_including_funding_estimate", "pnl_r", "realized_R", "realized_r", "net_R", "net_r"
)
IDENTITY_FIELDS = ("event_id", "position_id", "trade_id")
SIDE_FIELDS = ("side", "position_side", "direction")
WINDOW_FIELDS = ("window_id", "window", "split", "partition")
STRATEGY_FIELDS = ("strategy_id", "strategy", "strategy_name")
CONFIGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("MAIN_ONLY", MAIN),
    ("MAIN_PLUS_LIQUIDITY_SWEEP", MAIN + ("liquidity_sweep",)),
    ("MAIN_PLUS_TREND_RIDER", MAIN + ("trend_rider",)),
    ("MAIN_PLUS_BOTH_RESERVES", MAIN + RESERVE),
)
MIN_TRADES_PER_WINDOW = 20
MIN_ACTIVE_STRATEGIES_PER_WINDOW = 2


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat()


def normalize_symbol(value: str) -> str:
    return value.upper().replace("-", "").replace("_", "").replace("/", "")


def deterministic_gzip_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                writer = csv.writer(text, lineterminator="\n")
                writer.writerow(header)
                writer.writerows(rows)


def read_csv_gzip_bytes(raw: bytes) -> tuple[list[str], list[list[str]]]:
    with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
            reader = csv.reader(text)
            header = next(reader)
            rows = [row for row in reader]
    return header, rows


def validate_ohlcv_rows(rows: Sequence[Sequence[str]], expected_count: int) -> dict[str, Any]:
    if len(rows) != expected_count:
        raise RuntimeError(f"ROW_COUNT:{len(rows)}!={expected_count}")
    timestamps = [int(row[0]) for row in rows]
    if len(timestamps) != len(set(timestamps)):
        raise RuntimeError("DUPLICATE_TIMESTAMPS")
    if any(right - left != 60_000 for left, right in zip(timestamps, timestamps[1:])):
        raise RuntimeError("NON_CONTIGUOUS_1M_TIMESTAMPS")
    for row in rows:
        if len(row) != 6:
            raise RuntimeError("CSV_WIDTH_MISMATCH")
        _, o, h, l, c, v = row
        values = [float(o), float(h), float(l), float(c), float(v)]
        if not all(math.isfinite(x) for x in values):
            raise RuntimeError("NONFINITE_OHLCV")
        if float(h) < max(float(o), float(l), float(c)) or float(l) > min(float(o), float(h), float(c)):
            raise RuntimeError("OHLC_INVARIANT")
        if float(v) < 0:
            raise RuntimeError("NEGATIVE_VOLUME")
    return {
        "row_count": len(rows),
        "first_timestamp_ms": timestamps[0],
        "last_timestamp_ms": timestamps[-1],
        "start_utc": utc_iso_from_ms(timestamps[0]),
        "end_exclusive_utc": utc_iso_from_ms(timestamps[-1] + 60_000),
        "duplicate_timestamp_count": 0,
        "missing_interval_count": 0,
    }


def materialize_dataset(source_zip: Path, output_root: Path) -> dict[str, Any]:
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    (output_root / "market").mkdir()
    (output_root / "funding").mkdir()

    with zipfile.ZipFile(source_zip) as archive:
        names = set(archive.namelist())
        if "manifest.json" not in names or "verification_receipt.json" not in names:
            raise RuntimeError("SOURCE_METADATA_MISSING")
        source_manifest = json.loads(archive.read("manifest.json"))
        source_verify = json.loads(archive.read("verification_receipt.json"))
        if source_manifest.get("dataset_sha256") != EXPECTED_SOURCE_DATASET_SHA256:
            raise RuntimeError("SOURCE_DATASET_SHA_MISMATCH")
        if source_verify.get("receipt_sha256") != EXPECTED_SOURCE_VERIFY_RECEIPT_SHA256:
            raise RuntimeError("SOURCE_VERIFY_RECEIPT_MISMATCH")
        if source_verify.get("state") != "PASS_BINGX_1M_GAP_EXCLUDED_DATASET_VERIFIED":
            raise RuntimeError("SOURCE_VERIFY_STATE_MISMATCH")
        if int(source_verify.get("verified_file_count") or 0) != EXPECTED_SOURCE_FILE_COUNT:
            raise RuntimeError("SOURCE_FILE_COUNT_MISMATCH")
        if int(source_verify.get("verified_total_rows") or 0) != EXPECTED_SOURCE_TOTAL_ROWS:
            raise RuntimeError("SOURCE_TOTAL_ROWS_MISMATCH")

        source_results = [row for row in source_manifest.get("results", []) if isinstance(row, dict)]
        post_gap = {
            normalize_symbol(str(row["symbol"])): row
            for row in source_results if row.get("segment_id") == "POST_GAP"
        }
        if set(post_gap) != set(SYMBOLS):
            raise RuntimeError(f"POST_GAP_SYMBOL_SET:{sorted(post_gap)}")

        source_timestamp_fingerprint: list[int] | None = None
        file_rows: list[dict[str, Any]] = []
        window_boundaries: dict[str, dict[str, Any]] = {}

        for symbol in SYMBOLS:
            meta = post_gap[symbol]
            source_name = "data/" + str(meta["file"])
            if source_name not in names:
                raise RuntimeError(f"SOURCE_FILE_MISSING:{source_name}")
            source_raw = archive.read(source_name)
            if sha256_bytes(source_raw) != str(meta["file_sha256"]):
                raise RuntimeError(f"SOURCE_FILE_SHA_MISMATCH:{symbol}")
            header, rows = read_csv_gzip_bytes(source_raw)
            if header != ["timestamp_ms", "open", "high", "low", "close", "volume"]:
                raise RuntimeError(f"SOURCE_HEADER_MISMATCH:{symbol}:{header}")
            validate_ohlcv_rows(rows, EXPECTED_POST_GAP_ROWS_PER_SYMBOL)
            timestamps = [int(row[0]) for row in rows]
            if source_timestamp_fingerprint is None:
                source_timestamp_fingerprint = timestamps
            elif timestamps != source_timestamp_fingerprint:
                raise RuntimeError(f"CROSS_SYMBOL_TIMESTAMP_MISMATCH:{symbol}")

            for index, window in enumerate(WINDOWS):
                start = index * WINDOW_ROWS
                end = start + WINDOW_ROWS
                window_rows = rows[start:end]
                check = validate_ohlcv_rows(window_rows, WINDOW_ROWS)
                relative = f"market/{WINDOW_IDS[window]}/{symbol}_1m.csv.gz"
                target = output_root / relative
                deterministic_gzip_csv(target, header, window_rows)
                file_rows.append({
                    "kind": "market", "path": relative, "sha256": sha256_path(target),
                    "bytes": target.stat().st_size, "rows": WINDOW_ROWS, "symbol": symbol,
                    "interval": "1m", "window_id": WINDOW_IDS[window], **check,
                })
                boundary = window_boundaries.setdefault(window, {
                    "window_id": WINDOW_IDS[window], "row_count_per_symbol": WINDOW_ROWS,
                    "start_utc": check["start_utc"], "end_exclusive_utc": check["end_exclusive_utc"],
                    "start_ms": check["first_timestamp_ms"], "end_exclusive_ms": check["last_timestamp_ms"] + 60_000,
                })
                if boundary["start_ms"] != check["first_timestamp_ms"] or boundary["end_exclusive_ms"] != check["last_timestamp_ms"] + 60_000:
                    raise RuntimeError(f"WINDOW_BOUNDARY_MISMATCH:{symbol}:{window}")

    if len(file_rows) != len(SYMBOLS) * len(WINDOWS):
        raise RuntimeError("MATERIALIZED_FILE_COUNT_MISMATCH")
    total_rows = sum(int(row["rows"]) for row in file_rows)
    if total_rows != EXPECTED_EXPANDED_TOTAL_ROWS:
        raise RuntimeError(f"EXPANDED_TOTAL_ROWS:{total_rows}")
    windows = [window_boundaries[name] for name in WINDOWS]
    for left, right in zip(windows, windows[1:]):
        if int(left["end_exclusive_ms"]) != int(right["start_ms"]):
            raise RuntimeError("WINDOWS_NOT_CONTIGUOUS_NONOVERLAP")

    manifest: dict[str, Any] = {
        "schema_version": "zel.historical_oos.data_manifest.v1", "version": VERSION,
        "state": "PASS_HISTORICAL_OOS_DATA_READY", "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifact_id": 8916685107, "source_dataset_sha256": EXPECTED_SOURCE_DATASET_SHA256,
        "source_verification_receipt_sha256": EXPECTED_SOURCE_VERIFY_RECEIPT_SHA256,
        "partition_policy": "POST_GAP_ONLY_THREE_EQUAL_CONTIGUOUS_NONOVERLAP_WINDOWS",
        "excluded_pre_gap_rows_per_symbol": 22_530,
        "excluded_source_gap_day": "2026-02-13T00:00:00Z/2026-02-14T00:00:00Z",
        "symbols": list(SYMBOLS), "intervals": ["1m"], "windows": windows,
        "files": sorted(file_rows, key=lambda row: (row["window_id"], row["symbol"])),
        "total_market_rows": total_rows, "authority_end": windows[-1]["end_exclusive_utc"],
        "forward_overlap_count": 0, "historical_data_is_promotion_authority": False,
        "final_holdout_accessed": False, "synthetic_rows_created": 0, "interpolation_used": False,
        "forward_fill_used": False, "duplicate_timestamp_count": 0, "missing_interval_count": 0,
        "cross_symbol_timestamp_alignment": True, "selection_authority": False,
        "promotion_authority": False, "execution_authority": "NONE", "order_authority": "BLOCKED",
        "protected_mutations": 0, "action": "hold",
    }
    manifest["dataset_sha256"] = stable_sha([
        {"path": row["path"], "sha256": row["sha256"], "rows": row["rows"]} for row in manifest["files"]
    ])
    manifest["receipt_sha256"] = stable_sha(manifest)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def nested(row: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    for container in ("result", "execution_evidence", "market_context", "risk_context", "entry_features"):
        value = row.get(container)
        if isinstance(value, Mapping):
            for key in keys:
                if value.get(key) not in (None, ""):
                    return value[key]
    return None


def normalize_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "bull", "1", "enter_long"}:
        return "long"
    if text in {"short", "sell", "bear", "-1", "enter_short"}:
        return "short"
    return "unknown"


def normalize_window(value: Any) -> str:
    text = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "W1": "W1", "1M_W1": "W1", "TRAIN": "W1", "RESEARCH": "W1",
        "W2": "W2", "1M_W2": "W2", "FORWARD": "W2", "VALIDATION": "W2",
        "W3": "W3", "1M_W3": "W3", "DURABILITY": "W3", "TEST": "W3",
    }
    return aliases.get(text, "UNKNOWN")


def load_trade_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    identities: list[str] = []
    errors: list[str] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                source = json.loads(raw)
                if not isinstance(source, dict):
                    raise ValueError("row_not_object")
                identity = str(nested(source, IDENTITY_FIELDS) or "").strip()
                strategy = str(nested(source, STRATEGY_FIELDS) or "").strip()
                side = normalize_side(nested(source, SIDE_FIELDS))
                window = normalize_window(nested(source, WINDOW_FIELDS))
                r = float(nested(source, R_FIELDS))
                if not identity or not strategy or side == "unknown" or window == "UNKNOWN" or not math.isfinite(r):
                    raise ValueError("missing_or_invalid_required_field")
                identities.append(identity)
                rows.append({"identity": identity, "strategy_id": strategy, "side": side, "window": window, "r": r})
            except Exception as exc:
                if len(errors) < 20:
                    errors.append(f"line={line_number}:{type(exc).__name__}:{exc}")
    integrity = {
        "row_count": len(rows), "parse_or_required_field_error_count": len(errors), "error_samples": errors,
        "duplicate_identity_count": len(identities) - len(set(identities)),
        "unknown_strategy_count": sum(row["strategy_id"] not in MAIN + RESERVE + FILTER_ONLY for row in rows),
        "non_long_entry_owner_trade_count": sum(row["strategy_id"] in ENTRY_OWNERS and row["side"] != "long" for row in rows),
    }
    return rows, integrity


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(row["r"]) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    equity = peak = max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    active = sorted({str(row["strategy_id"]) for row in rows})
    return {
        "trade_count": len(values), "active_strategy_count": len(active), "active_strategies": active,
        "net_R": sum(values),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "expectancy_R": sum(values) / len(values) if values else 0.0,
        "payoff_ratio": avg_win / avg_loss if avg_loss > 0 else (999.0 if avg_win > 0 else 0.0),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else 0.0,
        "avg_win_R": avg_win, "avg_loss_R": -avg_loss, "max_drawdown_R": max_dd,
    }


def absolute_gate(row: Mapping[str, Any]) -> bool:
    return (
        int(row["trade_count"]) >= MIN_TRADES_PER_WINDOW
        and int(row["active_strategy_count"]) >= MIN_ACTIVE_STRATEGIES_PER_WINDOW
        and float(row["net_R"]) > 0 and float(row["profit_factor"]) >= 1.0
        and float(row["expectancy_R"]) > 0 and float(row["payoff_ratio"]) >= 1.0
    )


def evaluate(report_path: Path, ledger_path: Path, dataset_manifest_path: Path, output_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text())
    dataset_manifest = json.loads(dataset_manifest_path.read_text())
    rows, ledger_integrity = load_trade_rows(ledger_path)
    report_replay = report.get("replay") or {}
    report_ok = {
        "report_state_pass": report.get("state") == "PASS",
        "five_strategies_completed": int(report_replay.get("strategy_count_completed") or -1) == 5,
        "strategy_failures_zero": int(report_replay.get("strategy_failure_count") or -1) == 0,
        "errors_zero": int(report_replay.get("error_count") or -1) == 0,
        "censored_open_zero": int(report_replay.get("censored_open_at_window_end") or -1) == 0,
        "dataset_manifest_match": (report.get("data") or {}).get("manifest_sha256") == sha256_path(dataset_manifest_path),
        "dataset_rows_match": int((report.get("data") or {}).get("market_row_count") or -1) == EXPECTED_EXPANDED_TOTAL_ROWS,
        "source_strategy_tree_unchanged": bool((report.get("source") or {}).get("strategy_tree_unchanged")),
        "canonical_runtime_safe": all([
            bool((report.get("canonical_runtime") or {}).get("producer_pid_unchanged")),
            bool((report.get("canonical_runtime") or {}).get("writer_pid_unchanged")),
            bool(((report.get("canonical_runtime") or {}).get("formal_ledger") or {}).get("prefix_unchanged")),
        ]),
    }
    ledger_ok = {
        "parse_or_required_field_errors_zero": ledger_integrity["parse_or_required_field_error_count"] == 0,
        "duplicate_identities_zero": ledger_integrity["duplicate_identity_count"] == 0,
        "unknown_strategies_zero": ledger_integrity["unknown_strategy_count"] == 0,
        "non_long_entry_owner_trades_zero": ledger_integrity["non_long_entry_owner_trade_count"] == 0,
    }
    long_rows = [row for row in rows if row["side"] == "long" and row["strategy_id"] in ENTRY_OWNERS]
    filter_rows = [row for row in rows if row["side"] == "long" and row["strategy_id"] in FILTER_ONLY]
    per_strategy: dict[str, Any] = {}
    for strategy in MAIN + RESERVE + FILTER_ONLY:
        strategy_rows = [row for row in rows if row["strategy_id"] == strategy and row["side"] == "long"]
        per_strategy[strategy] = {window: metrics([row for row in strategy_rows if row["window"] == window]) for window in WINDOWS}
        per_strategy[strategy]["ALL"] = metrics(strategy_rows)
    configurations: dict[str, Any] = {}
    for name, owners in CONFIGS:
        selected_rows = [row for row in long_rows if row["strategy_id"] in owners]
        window_metrics = {window: metrics([row for row in selected_rows if row["window"] == window]) for window in WINDOWS}
        configurations[name] = {
            "entry_owners": list(owners), "windows": window_metrics, "ALL": metrics(selected_rows),
            "W1_absolute_gate": absolute_gate(window_metrics["W1"]),
        }
    passing_w1 = [name for name, row in configurations.items() if row["W1_absolute_gate"]]
    if passing_w1:
        selected_name = max(passing_w1, key=lambda name: (
            float(configurations[name]["windows"]["W1"]["net_R"]),
            float(configurations[name]["windows"]["W1"]["profit_factor"]),
            float(configurations[name]["windows"]["W1"]["expectancy_R"]),
            -len(configurations[name]["entry_owners"]), name,
        ))
        selection_kind = "W1_ABSOLUTE_GATE_PASS"
    else:
        selected_name = max(configurations, key=lambda name: (
            float(configurations[name]["windows"]["W1"]["net_R"]),
            float(configurations[name]["windows"]["W1"]["profit_factor"]), name,
        ))
        selection_kind = "DIAGNOSTIC_ONLY_NO_W1_PASS"
    selected = configurations[selected_name]
    window_gates = {window: absolute_gate(selected["windows"][window]) for window in WINDOWS}
    sample_coverage = {window: (
        int(selected["windows"][window]["trade_count"]) >= MIN_TRADES_PER_WINDOW
        and int(selected["windows"][window]["active_strategy_count"]) >= MIN_ACTIVE_STRATEGIES_PER_WINDOW
    ) for window in WINDOWS}
    main_activity = {window: sum(int(per_strategy[strategy][window]["trade_count"]) for strategy in MAIN) > 0 for window in WINDOWS}
    all_integrity = all(report_ok.values()) and all(ledger_ok.values())
    coverage_restored = all(sample_coverage.values()) and all(main_activity.values())
    survivor = all_integrity and coverage_restored and all(window_gates.values()) and selection_kind == "W1_ABSOLUTE_GATE_PASS"
    blockers: list[str] = []
    for key, passed in report_ok.items():
        if not passed: blockers.append(f"REPORT_{key.upper()}")
    for key, passed in ledger_ok.items():
        if not passed: blockers.append(f"LEDGER_{key.upper()}")
    for window, passed in sample_coverage.items():
        if not passed: blockers.append(f"{window}_SAMPLE_COVERAGE_FAIL")
    for window, passed in main_activity.items():
        if not passed: blockers.append(f"{window}_MAIN_ACTIVITY_FAIL")
    for window, passed in window_gates.items():
        if not passed: blockers.append(f"{window}_ABSOLUTE_ECONOMIC_GATE_FAIL")
    if selection_kind != "W1_ABSOLUTE_GATE_PASS": blockers.append("NO_W1_ADMISSIBLE_CONFIGURATION")
    result: dict[str, Any] = {
        "schema_version": SCHEMA, "version": VERSION,
        "state": "PASS_STRUCTURAL_PREMIUM_COVERAGE_SURVIVOR" if survivor else (
            "PASS_STRUCTURAL_PREMIUM_COVERAGE_REVALIDATED_NO_SURVIVOR" if all_integrity
            else "HOLD_STRUCTURAL_PREMIUM_COVERAGE_INTEGRITY"
        ),
        "source_run": {
            "dataset_source_artifact_id": 8916685107, "dataset_sha256": dataset_manifest.get("dataset_sha256"),
            "dataset_manifest_sha256": sha256_path(dataset_manifest_path),
            "expanded_market_rows": EXPECTED_EXPANDED_TOTAL_ROWS,
            "post_gap_rows_per_symbol": EXPECTED_POST_GAP_ROWS_PER_SYMBOL,
            "window_rows_per_symbol": WINDOW_ROWS, "ledger_sha256": sha256_path(ledger_path),
            "report_sha256": sha256_path(report_path),
        },
        "contract": {
            "main": [f"{value}|enter_long" for value in MAIN],
            "reserve": [f"{value}|enter_long" for value in RESERVE],
            "filter_only": [f"{value}|enter_long" for value in FILTER_ONLY],
            "market_structure_entry_owner": False,
        },
        "integrity": {"report_checks": report_ok, "ledger_checks": ledger_ok, "ledger_detail": ledger_integrity, "all_pass": all_integrity},
        "coverage": {
            "registered_strategy_count": 5, "entry_owner_count": 4, "filter_only_count": 1,
            "entry_owner_long_trade_count": len(long_rows), "filter_only_observation_count": len(filter_rows),
            "sample_gate_min_trades_per_window": MIN_TRADES_PER_WINDOW,
            "sample_gate_min_active_strategies_per_window": MIN_ACTIVE_STRATEGIES_PER_WINDOW,
            "selected_window_sample_coverage": sample_coverage, "main_activity_by_window": main_activity,
            "coverage_restored": coverage_restored,
        },
        "selection": {
            "selection_window": "W1", "selection_kind": selection_kind,
            "selected_configuration": selected_name, "selected_entry_owners": selected["entry_owners"],
            "configuration_frozen_unchanged_in_W2_W3": True, "passing_W1_configurations": passing_w1,
        },
        "configurations": configurations, "per_strategy": per_strategy, "selected": selected,
        "window_absolute_gates": window_gates, "survivor": survivor, "blockers": sorted(set(blockers)),
        "raw_trade_rows_published": False, "selection_authority": False, "promotion_authority": False,
        "execution_authority": "NONE", "order_authority": "BLOCKED", "protected_mutations": 0,
        "action": "hold" if survivor else "route_change",
    }
    result["receipt_sha256"] = stable_sha(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def self_test() -> None:
    synthetic: list[dict[str, Any]] = []
    for window in WINDOWS:
        for index in range(12): synthetic.append({"strategy_id": "vwap_revert", "window": window, "r": 1.0 if index < 8 else -0.5})
        for index in range(12): synthetic.append({"strategy_id": "support_resistance", "window": window, "r": 0.8 if index < 8 else -0.4})
    row = metrics(synthetic)
    assert row["trade_count"] == 72 and row["active_strategy_count"] == 2
    assert row["net_R"] > 0 and row["profit_factor"] > 1 and row["payoff_ratio"] > 1
    assert absolute_gate({**row, "trade_count": 24})
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--source-zip", type=Path, required=True)
    materialize.add_argument("--output-root", type=Path, required=True)
    evaluate_parser = sub.add_parser("evaluate")
    evaluate_parser.add_argument("--report", type=Path, required=True)
    evaluate_parser.add_argument("--ledger", type=Path, required=True)
    evaluate_parser.add_argument("--dataset-manifest", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test": self_test(); return 0
    if args.command == "materialize":
        manifest = materialize_dataset(args.source_zip, args.output_root)
        print(json.dumps({"state": manifest["state"], "total_market_rows": manifest["total_market_rows"], "file_count": len(manifest["files"]), "dataset_sha256": manifest["dataset_sha256"], "receipt_sha256": manifest["receipt_sha256"]}, sort_keys=True))
        return 0
    if args.command == "evaluate":
        result = evaluate(args.report, args.ledger, args.dataset_manifest, args.output)
        print(json.dumps({"state": result["state"], "coverage_restored": result["coverage"]["coverage_restored"], "selected_configuration": result["selection"]["selected_configuration"], "survivor": result["survivor"], "receipt_sha256": result["receipt_sha256"]}, sort_keys=True))
        return 0 if result["integrity"]["all_pass"] else 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
