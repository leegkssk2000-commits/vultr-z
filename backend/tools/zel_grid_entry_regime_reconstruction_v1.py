from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import inspect
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_ENTRY_REGIME_RECONSTRUCTION_V2"
SCHEMA = "zel.grid_entry_regime.reconstruction.receipt.v2"
STRATEGY_ID = "grid_rebalance"
CONTEXT_SOURCE_SHA256 = "408ee3edf3899ad626e25f01be19d447af16d4a033996fb5d2c76a516efe82ca"
DERIVE_SOURCE_SHA256 = "1ad1cc721a88cef9f8c08a8ed1727736d61ad036495f5b650f798332ad7b684c"
ALLOWED_REGIMES = {"range", "trend_long", "trend_short", "transition"}
EXPECTED_TRADES = 580
EXPECTED_WINDOWS = {"1m_w1", "1m_w2", "1m_w3"}


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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


def legacy_exit_regime(row: Mapping[str, Any]) -> str:
    return str(row.get("regime") or row.get("market_regime") or "missing")


def timestamp_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("exit_ts") or row.get("exit_time") or row.get("captured_at") or ""), event_id(row)


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=timestamp_key)
    values = [pnl_r(row) for row in ordered]
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


def metric_delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_pf = finite_float(base.get("profit_factor"))
    candidate_pf = finite_float(candidate.get("profit_factor"))
    return {
        "delta_net_R": safe_float(candidate.get("net_R")) - safe_float(base.get("net_R")),
        "delta_max_drawdown_R": safe_float(candidate.get("max_drawdown_R"))
        - safe_float(base.get("max_drawdown_R")),
        "delta_profit_factor": candidate_pf - base_pf
        if base_pf is not None and candidate_pf is not None
        else None,
        "trade_retention_pct": int(candidate.get("trade_count") or 0)
        / max(int(base.get("trade_count") or 0), 1)
        * 100.0,
    }


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_grid_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise RuntimeError(f"ROW_OBJECT_REQUIRED:{line_number}")
            strategy = str(
                row.get("strategy_id")
                or row.get("strategy")
                or row.get("strategy_name")
                or ""
            )
            if strategy == STRATEGY_ID:
                rows.append(row)
    return rows


def normalized_epoch_ns(pd_module: Any, value: Any) -> int | None:
    try:
        timestamp = pd_module.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return int(timestamp.value)
    except Exception:
        return None


def resolve_file_path(data_root: Path, file_row: Mapping[str, Any]) -> Path:
    for key in ("path", "file", "csv_path", "relative_path"):
        value = file_row.get(key)
        if isinstance(value, str) and value:
            path = Path(value)
            return path if path.is_absolute() else data_root / path
    raise RuntimeError(
        f"DATA_FILE_PATH_MISSING:{file_row.get('window_id')}:{file_row.get('symbol')}"
    )


def grouped_metrics(
    rows: list[dict[str, Any]],
    labels: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_regime: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_regime_window: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        regime = labels.get(event_id(row), "missing")
        by_regime[regime].append(row)
        by_regime_window[(regime, window_id(row))].append(row)
    return (
        {key: metrics(value) for key, value in sorted(by_regime.items())},
        {
            f"{regime}|{window}": metrics(value)
            for (regime, window), value in sorted(by_regime_window.items())
        },
    )


def candidate_matrix(
    rows: list[dict[str, Any]],
    labels: Mapping[str, str],
) -> dict[str, Any]:
    baseline = metrics(rows)
    output: dict[str, Any] = {}
    regimes = sorted(set(labels.values()))
    for regime in regimes:
        include_rows = [row for row in rows if labels.get(event_id(row)) == regime]
        exclude_rows = [row for row in rows if labels.get(event_id(row)) != regime]
        include_metrics = metrics(include_rows)
        exclude_metrics = metrics(exclude_rows)
        by_window: dict[str, Any] = {}
        for window in sorted(EXPECTED_WINDOWS):
            base_window_rows = [row for row in rows if window_id(row) == window]
            include_window_rows = [
                row
                for row in base_window_rows
                if labels.get(event_id(row)) == regime
            ]
            exclude_window_rows = [
                row
                for row in base_window_rows
                if labels.get(event_id(row)) != regime
            ]
            base_window = metrics(base_window_rows)
            include_window = metrics(include_window_rows)
            exclude_window = metrics(exclude_window_rows)
            by_window[window] = {
                "base": base_window,
                "include_only": include_window,
                "include_only_delta": metric_delta(base_window, include_window),
                "exclude": exclude_window,
                "exclude_delta": metric_delta(base_window, exclude_window),
            }
        output[regime] = {
            "include_only": include_metrics,
            "include_only_delta": metric_delta(baseline, include_metrics),
            "exclude": exclude_metrics,
            "exclude_delta": metric_delta(baseline, exclude_metrics),
            "by_window": by_window,
            "selection_allowed": False,
            "production_applied": False,
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--engine",
        type=Path,
        default=Path(
            "/opt/zel/research-runtime/data-b-v2/"
            "zel_historical_oos_exact25_replay_v1.py"
        ),
    )
    parser.add_argument(
        "--terminal-root",
        type=Path,
        default=Path("/var/lib/zel-research/data-b-1m-v2"),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/opt/zel/historical-oos-v1"),
    )
    parser.add_argument(
        "--context-source",
        type=Path,
        default=Path("/home/z/z/tools/q4r3_exact25_market_context_collector.py"),
    )
    parser.add_argument(
        "--derive-source",
        type=Path,
        default=Path("/home/z/z/tools/q4r3_exact25_preentry_method_context_capture.py"),
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    source_hashes = {
        "context": sha256_file(args.context_source),
        "derive": sha256_file(args.derive_source),
    }
    if source_hashes["context"] != CONTEXT_SOURCE_SHA256:
        raise RuntimeError(
            f"CONTEXT_SOURCE_SHA_MISMATCH:{source_hashes['context']}"
        )
    if source_hashes["derive"] != DERIVE_SOURCE_SHA256:
        raise RuntimeError(
            f"DERIVE_SOURCE_SHA_MISMATCH:{source_hashes['derive']}"
        )

    report = json.loads(
        (args.terminal_root / "report.json").read_text(encoding="utf-8")
    )
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")
    source_root = Path(source_root_raw)

    engine = load_module(args.engine, "zel_entry_regime_engine")
    context_module = load_module(args.context_source, "zel_market_context_classifier")
    derive_module = load_module(args.derive_source, "zel_preentry_regime_deriver")
    compute_context = getattr(context_module, "compute_context", None)
    derive_regime = getattr(derive_module, "derive_regime", None)
    if not callable(compute_context) or not callable(derive_regime):
        raise RuntimeError("CLASSIFIER_CALLABLE_MISSING")

    engine.worker_init(source_root, args.data_root, "1m")
    manifest = engine._WORKER_MANIFEST
    files = list(manifest.get("files") or []) if isinstance(manifest, Mapping) else []
    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for file_row in files:
        if not isinstance(file_row, Mapping):
            continue
        key = (
            str(file_row.get("window_id") or file_row.get("window") or "unknown"),
            str(file_row.get("symbol") or "").upper(),
        )
        file_map[key] = file_row

    rows = read_grid_rows(args.terminal_root / "trades.jsonl.gz")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(window_id(row), symbol(row))].append(row)

    reconstructed: dict[str, str] = {}
    context_facts: dict[str, dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []
    frame_count = 0
    causal_prefix_count = 0
    duplicate_frame_timestamp_count = 0
    minimum_prefix_bars: int | None = None

    for lane_key, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane_key)
        if file_row is None:
            unmatched.extend(
                {
                    "event_sha256": stable_sha(event_id(row)),
                    "reason": "LANE_FILE_MISSING",
                    "lane": lane_key,
                }
                for row in lane_rows
            )
            continue
        frame_path = resolve_file_path(args.data_root, file_row)
        frame = engine.frame_from_csv(frame_path)
        frame_count += 1
        timestamp_index: dict[int, int] = {}
        duplicate_epochs: set[int] = set()
        for index, value in enumerate(frame["timestamp"].tolist()):
            epoch_ns = normalized_epoch_ns(engine.pd, value)
            if epoch_ns is None:
                continue
            if epoch_ns in timestamp_index:
                duplicate_epochs.add(epoch_ns)
            timestamp_index[epoch_ns] = index
        duplicate_frame_timestamp_count += len(duplicate_epochs)

        for row in lane_rows:
            current_event_id = event_id(row)
            entry_ts = row.get("entry_ts") or row.get("entry_time")
            epoch_ns = normalized_epoch_ns(engine.pd, entry_ts)
            index = timestamp_index.get(epoch_ns) if epoch_ns is not None else None
            if index is None:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "ENTRY_TIMESTAMP_NOT_FOUND",
                        "lane": lane_key,
                    }
                )
                continue
            current = frame.iloc[
                max(0, index - int(engine.FRAME_LIMIT) + 1) : index + 1
            ].copy()
            prefix_bars = len(current)
            minimum_prefix_bars = (
                prefix_bars
                if minimum_prefix_bars is None
                else min(minimum_prefix_bars, prefix_bars)
            )
            current_last_epoch = normalized_epoch_ns(
                engine.pd, current["timestamp"].iloc[-1]
            )
            if current_last_epoch != epoch_ns:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "PREFIX_LAST_BAR_NOT_ENTRY",
                        "lane": lane_key,
                    }
                )
                continue
            if prefix_bars < 14:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "PREFIX_BELOW_ATR14_WARMUP",
                        "lane": lane_key,
                    }
                )
                continue

            token = f"{lane_key[0]}:{lane_key[1]}"
            try:
                context = compute_context(token, current, None, None, None)
            except Exception as exc:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": f"COMPUTE_CONTEXT_FAILED:{type(exc).__name__}",
                        "lane": lane_key,
                    }
                )
                continue
            if not isinstance(context, Mapping):
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "CONTEXT_NOT_MAPPING",
                        "lane": lane_key,
                    }
                )
                continue
            strength = finite_float(context.get("trend_strength"))
            direction = str(context.get("trend_direction") or "")
            if strength is None or direction not in {"long", "short", "neutral"}:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "TREND_CONTEXT_INVALID",
                        "lane": lane_key,
                    }
                )
                continue
            try:
                regime = str(derive_regime(dict(context)))
            except Exception as exc:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": f"DERIVE_REGIME_FAILED:{type(exc).__name__}",
                        "lane": lane_key,
                    }
                )
                continue
            if regime not in ALLOWED_REGIMES:
                unmatched.append(
                    {
                        "event_sha256": stable_sha(current_event_id),
                        "reason": "DERIVED_REGIME_INVALID",
                        "lane": lane_key,
                    }
                )
                continue
            reconstructed[current_event_id] = regime
            context_facts[current_event_id] = {
                "trend_direction": direction,
                "trend_strength": strength,
                "prefix_bars": prefix_bars,
            }
            causal_prefix_count += 1

    regime_metrics, regime_window_metrics = grouped_metrics(rows, reconstructed)
    baseline_metrics = metrics(rows)
    candidates = candidate_matrix(rows, reconstructed) if reconstructed else {}

    confusion = Counter(
        f"{reconstructed.get(event_id(row), 'missing')}|{legacy_exit_regime(row)}"
        for row in rows
    )
    legacy_neutral_ids = {
        event_id(row) for row in rows if legacy_exit_regime(row) == "neutral"
    }
    entry_range_ids = {
        current_event_id
        for current_event_id, regime in reconstructed.items()
        if regime == "range"
    }
    union = legacy_neutral_ids | entry_range_ids
    intersection = legacy_neutral_ids & entry_range_ids

    blockers: list[str] = []
    if len(rows) != EXPECTED_TRADES:
        blockers.append("GRID_TRADE_COUNT_MISMATCH")
    if {window_id(row) for row in rows} != EXPECTED_WINDOWS:
        blockers.append("WINDOW_SET_MISMATCH")
    if frame_count != len(grouped):
        blockers.append("USED_LANE_FRAME_COUNT_MISMATCH")
    if len(reconstructed) != len(rows):
        blockers.append("ENTRY_REGIME_RECONSTRUCTION_INCOMPLETE")
    if causal_prefix_count != len(rows):
        blockers.append("CAUSAL_PREFIX_COUNT_MISMATCH")
    if unmatched:
        blockers.append("ENTRY_CONTEXT_OR_TIMESTAMP_MISMATCH")
    if set(reconstructed.values()) - ALLOWED_REGIMES:
        blockers.append("UNEXPECTED_ENTRY_REGIME")
    if duplicate_frame_timestamp_count:
        blockers.append("DUPLICATE_FRAME_TIMESTAMP")

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": (
            "PASS_GRID_ENTRY_REGIME_CAUSALLY_RECONSTRUCTED"
            if not blockers
            else "HOLD_GRID_ENTRY_REGIME_RECONSTRUCTION_INCOMPLETE"
        ),
        "strategy_id": STRATEGY_ID,
        "engine_path": str(args.engine.resolve()),
        "engine_sha256": sha256_file(args.engine),
        "context_source_path": str(args.context_source.resolve()),
        "context_source_sha256": source_hashes["context"],
        "derive_source_path": str(args.derive_source.resolve()),
        "derive_source_sha256": source_hashes["derive"],
        "context_compute_signature": str(inspect.signature(compute_context)),
        "derive_regime_signature": str(inspect.signature(derive_regime)),
        "classifier_external_to_frozen_source": True,
        "classifier_stage_status": "PINNED_RESEARCH_SIDECAR_NOT_BOUND",
        "source_root": str(source_root),
        "data_file_count": len(files),
        "used_lane_count": len(grouped),
        "loaded_frame_count": frame_count,
        "duplicate_frame_timestamp_count": duplicate_frame_timestamp_count,
        "trade_count": len(rows),
        "reconstructed_count": len(reconstructed),
        "causal_prefix_count": causal_prefix_count,
        "minimum_prefix_bars": minimum_prefix_bars,
        "unmatched_count": len(unmatched),
        "unmatched_reason_counts": dict(
            sorted(Counter(row["reason"] for row in unmatched).items())
        ),
        "entry_regime_counts": dict(sorted(Counter(reconstructed.values()).items())),
        "entry_regime_metrics": regime_metrics,
        "entry_regime_window_metrics": regime_window_metrics,
        "baseline_metrics": baseline_metrics,
        "candidate_matrix": candidates,
        "legacy_exit_regime_invalid_for_entry_filter": True,
        "entry_exit_regime_confusion_counts": dict(sorted(confusion.items())),
        "entry_range_vs_legacy_exit_neutral": {
            "entry_range_count": len(entry_range_ids),
            "legacy_exit_neutral_count": len(legacy_neutral_ids),
            "intersection_count": len(intersection),
            "entry_range_only_count": len(entry_range_ids - legacy_neutral_ids),
            "legacy_exit_neutral_only_count": len(legacy_neutral_ids - entry_range_ids),
            "jaccard": len(intersection) / len(union) if union else None,
            "entry_range_event_set_sha256": stable_sha(sorted(entry_range_ids)),
            "legacy_exit_neutral_event_set_sha256": stable_sha(
                sorted(legacy_neutral_ids)
            ),
            "intersection_event_set_sha256": stable_sha(sorted(intersection)),
        },
        "context_fact_set_sha256": stable_sha(context_facts),
        "blockers": blockers,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "raw_price_data_published": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "GEMINI_CAUSAL_REVIEW_OF_ENTRY_REGIME_CANDIDATE_MATRIX"
            if not blockers
            else "RESOLVE_RECONSTRUCTION_BLOCKERS"
        ),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(
        receipt,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
