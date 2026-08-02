from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_ALPHA_COMBO_CAUSAL_LOSS_AUDIT_V1"
SCHEMA = "zel.alpha_combo.causal_loss_audit.receipt.v1"
STRATEGY_ID = "alpha_combo"
EXPECTED_TERMINAL_SHA256 = "62a7d51a02b75ebfee5765d81d955d583d442c995604bb9d4a8a5e7e7a4e2fe3"
EXPECTED_ENGINE_SHA256 = "14fc2600f3ca0dae4bf17e9768461661cf07ef7f1aa5934c317baac95b52fc50"
CONTEXT_PATH = Path("/home/z/z/tools/q4r3_exact25_market_context_collector.py")
CONTEXT_SHA256 = "408ee3edf3899ad626e25f01be19d447af16d4a033996fb5d2c76a516efe82ca"
DERIVE_PATH = Path("/home/z/z/tools/q4r3_exact25_preentry_method_context_capture.py")
DERIVE_SHA256 = "1ad1cc721a88cef9f8c08a8ed1727736d61ad036495f5b650f798332ad7b684c"
WINDOWS = ("1m_w1", "1m_w2", "1m_w3")
MAX_SOURCE_BYTES = 2_000_000


def stable_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def text(row: Mapping[str, Any], keys: Sequence[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def number(row: Mapping[str, Any], keys: Sequence[str], default: float = 0.0) -> float:
    for key in keys:
        parsed = finite(row.get(key))
        if parsed is not None:
            return parsed
    return default


def event_id(row: Mapping[str, Any]) -> str:
    return text(row, ("event_id", "trade_id", "position_id"))


def strategy_id(row: Mapping[str, Any]) -> str:
    return text(row, ("strategy_id", "strategy", "strategy_name"))


def window_id(row: Mapping[str, Any]) -> str:
    return text(row, ("window_id", "window"), "unknown")


def symbol(row: Mapping[str, Any]) -> str:
    return text(row, ("symbol", "market"), "unknown").upper()


def side(row: Mapping[str, Any]) -> str:
    return text(row, ("side", "direction"), "unknown").lower()


def parse_epoch_ns(pd_module: Any, value: Any) -> int | None:
    try:
        stamp = pd_module.Timestamp(value)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        return int(stamp.value)
    except Exception:
        return None


def timestamp_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return text(row, ("exit_ts", "exit_time", "closed_at", "captured_at")), event_id(row)


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise RuntimeError(f"ROW_NOT_OBJECT:{line_number}")
            if strategy_id(payload) == STRATEGY_ID:
                rows.append(dict(payload))
    return rows


def max_drawdown(values: Sequence[float]) -> float:
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=timestamp_key)
    values = [number(row, ("realized_R", "net_R", "pnl_r", "net_reference_R")) for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    return {
        "trade_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(values) * 100.0 if values else None,
        "net_R": sum(values),
        "expectancy_R": statistics.fmean(values) if values else None,
        "median_R": statistics.median(values) if values else None,
        "gross_profit_R": gross_profit,
        "gross_loss_R": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else None),
        "max_drawdown_R": max_drawdown(values),
        "event_id_set_sha256": stable_sha(sorted(event_id(row) for row in rows)),
    }


def grouped_metrics(rows: Sequence[Mapping[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)
    return {key: metrics(group) for key, group in sorted(groups.items())}


def time_bucket(row: Mapping[str, Any]) -> str:
    value = number(row, ("time_exposure_min", "exposure_min", "holding_minutes"), -1.0)
    if value < 0:
        return "missing"
    if value < 5:
        return "lt_5m"
    if value < 15:
        return "5_15m"
    if value < 30:
        return "15_30m"
    if value < 60:
        return "30_60m"
    if value < 120:
        return "60_120m"
    return "gte_120m"


def entry_session(epoch_ns: int) -> str:
    hour = datetime.fromtimestamp(epoch_ns / 1_000_000_000, tz=timezone.utc).hour
    if hour < 6:
        return "utc_00_06"
    if hour < 12:
        return "utc_06_12"
    if hour < 18:
        return "utc_12_18"
    return "utc_18_24"


def phenotype(row: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    realized = number(row, ("realized_R", "net_R", "pnl_r", "net_reference_R"))
    mfe = finite(row.get("MFE_R") or row.get("mfe_R") or row.get("mfe_r"))
    mae = finite(row.get("MAE_R") or row.get("mae_R") or row.get("mae_r"))
    if realized < 0 and mfe is not None and mfe < 0.25:
        labels.append("immediate_fail_mfe_lt_0_25R")
    if realized < 0 and mfe is not None and mfe >= 0.50:
        labels.append("favorable_then_loss_mfe_ge_0_50R")
    if realized < 0 and mae is not None and mae <= -0.75:
        labels.append("deep_adverse_mae_le_neg_0_75R")
    if realized < 0 and not labels:
        labels.append("other_loss")
    if realized >= 0:
        labels.append("non_loss")
    return labels


def phenotype_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        for label in phenotype(row):
            groups[label].append(row)
    output: dict[str, Any] = {}
    for label, group in sorted(groups.items()):
        values = [number(row, ("realized_R", "net_R", "pnl_r", "net_reference_R")) for row in group]
        output[label] = {
            "trade_count": len(group),
            "net_R": sum(values),
            "gross_loss_R": -sum(value for value in values if value < 0),
            "share_pct": len(group) / len(rows) * 100.0 if rows else None,
            "window_counts": dict(Counter(window_id(row) for row in group)),
        }
    return output


def resolve_path(root: Path, row: Mapping[str, Any]) -> Path:
    for key in ("path", "file", "csv_path", "relative_path"):
        value = row.get(key)
        if isinstance(value, str) and value:
            candidate = Path(value)
            return candidate if candidate.is_absolute() else root / candidate
    raise RuntimeError("DATA_FILE_PATH_MISSING")


def source_candidates(source_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", "archive", "archives", "backup", "backups"}
    for base, dirs, files in os.walk(source_root):
        dirs[:] = [name for name in dirs if name not in skip]
        for name in files:
            path = Path(base) / name
            if path.suffix not in {".py", ".json", ".yaml", ".yml"}:
                continue
            try:
                stat = path.stat()
                if stat.st_size <= 0 or stat.st_size > MAX_SOURCE_BYTES:
                    continue
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if STRATEGY_ID not in content:
                continue
            row: dict[str, Any] = {
                "relative_path": str(path.resolve().relative_to(source_root.resolve())),
                "sha256": file_sha(path),
                "size_bytes": stat.st_size,
                "suffix": path.suffix,
                "raw_code_published": False,
            }
            if path.suffix == ".py":
                try:
                    tree = ast.parse(content)
                    row["classes"] = sorted({node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)})
                    row["functions"] = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
                    row["return_dict_keys"] = sorted({
                        key.value
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
                        for key in node.value.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    })
                except SyntaxError as exc:
                    row["parse_error"] = f"{type(exc).__name__}:{exc.lineno}"
            results.append(row)
    return sorted(results, key=lambda row: (row["relative_path"], row["sha256"] or ""))


def reconstruct_entry_features(rows: Sequence[Mapping[str, Any]], *, engine: Any, manifest: Mapping[str, Any], data_root: Path) -> tuple[dict[str, dict[str, str]], list[str], int]:
    context_mod = load_module(CONTEXT_PATH, "zel_alpha_combo_context")
    derive_mod = load_module(DERIVE_PATH, "zel_alpha_combo_derive")
    compute_context = getattr(context_mod, "compute_context", None)
    derive_regime = getattr(derive_mod, "derive_regime", None)
    if not callable(compute_context) or not callable(derive_regime):
        raise RuntimeError("CONTEXT_CALLABLE_MISSING")

    file_map: dict[tuple[str, str], Mapping[str, Any]] = {}
    for file_row in list(manifest.get("files") or []):
        if isinstance(file_row, Mapping):
            file_map[(text(file_row, ("window_id", "window"), "unknown"), text(file_row, ("symbol",), "").upper())] = file_row
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(window_id(row), symbol(row))].append(row)

    features: dict[str, dict[str, str]] = {}
    failures: list[str] = []
    duplicate_count = 0
    for lane, lane_rows in sorted(grouped.items()):
        file_row = file_map.get(lane)
        if file_row is None:
            failures.extend("LANE_FILE_MISSING" for _ in lane_rows)
            continue
        frame = engine.frame_from_csv(resolve_path(data_root, file_row))
        index_by_epoch: dict[int, int] = {}
        duplicates: set[int] = set()
        for index, value in enumerate(frame["timestamp"].tolist()):
            epoch = parse_epoch_ns(engine.pd, value)
            if epoch is None:
                continue
            if epoch in index_by_epoch:
                duplicates.add(epoch)
            index_by_epoch[epoch] = index
        duplicate_count += len(duplicates)
        for row in lane_rows:
            epoch = parse_epoch_ns(engine.pd, row.get("entry_ts") or row.get("entry_time") or row.get("opened_at"))
            index = index_by_epoch.get(epoch) if epoch is not None else None
            if epoch is None or index is None:
                failures.append("ENTRY_TIMESTAMP_NOT_FOUND")
                continue
            prefix = frame.iloc[max(0, index - int(engine.FRAME_LIMIT) + 1): index + 1].copy()
            if len(prefix) < 14 or parse_epoch_ns(engine.pd, prefix["timestamp"].iloc[-1]) != epoch:
                failures.append("ENTRY_PREFIX_INVALID")
                continue
            try:
                context = compute_context(f"{lane[0]}:{lane[1]}", prefix, None, None, None)
                regime = str(derive_regime(context) or "missing")
            except Exception as exc:
                failures.append(f"CONTEXT_ERROR:{type(exc).__name__}")
                continue
            if regime not in {"range", "trend_long", "trend_short", "transition"}:
                failures.append("REGIME_INVALID")
                continue
            current_side = side(row)
            if current_side not in {"long", "short"}:
                failures.append("SIDE_INVALID")
                continue
            features[event_id(row)] = {
                "entry_regime": regime,
                "side": current_side,
                "utc_session": entry_session(epoch),
            }
    return features, failures, duplicate_count


def candidate_delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_pf = base.get("profit_factor")
    candidate_pf = candidate.get("profit_factor")
    return {
        "delta_net_R": float(candidate["net_R"]) - float(base["net_R"]),
        "delta_max_drawdown_R": float(candidate["max_drawdown_R"]) - float(base["max_drawdown_R"]),
        "delta_profit_factor": float(candidate_pf) - float(base_pf) if base_pf is not None and candidate_pf is not None else None,
        "retention_pct": int(candidate["trade_count"]) / max(int(base["trade_count"]), 1) * 100.0,
    }


def single_axis_screen(rows: Sequence[Mapping[str, Any]], features: Mapping[str, Mapping[str, str]]) -> list[dict[str, Any]]:
    by_window = {window: [row for row in rows if window_id(row) == window] for window in WINDOWS}
    baseline = {window: metrics(by_window[window]) for window in WINDOWS}
    baseline["all"] = metrics(rows)
    w1 = by_window["1m_w1"]
    rules: list[tuple[str, str]] = []
    for dimension in ("entry_regime", "side", "utc_session"):
        values = sorted({features[event_id(row)][dimension] for row in w1})
        rules.extend((dimension, value) for value in values)
    candidates: list[dict[str, Any]] = []
    for dimension, value in rules:
        candidate_metrics: dict[str, Any] = {}
        deltas: dict[str, Any] = {}
        blocked_phenotype: dict[str, Any] = {}
        for window in WINDOWS:
            kept = [row for row in by_window[window] if features[event_id(row)][dimension] != value]
            blocked = [row for row in by_window[window] if features[event_id(row)][dimension] == value]
            candidate_metrics[window] = metrics(kept)
            deltas[window] = candidate_delta(baseline[window], candidate_metrics[window])
            blocked_phenotype[window] = phenotype_metrics(blocked)
        kept_all = [row for row in rows if features[event_id(row)][dimension] != value]
        candidate_metrics["all"] = metrics(kept_all)
        deltas["all"] = candidate_delta(baseline["all"], candidate_metrics["all"])
        w1_pass = (
            deltas["1m_w1"]["retention_pct"] >= 60.0
            and deltas["1m_w1"]["delta_net_R"] > 0
            and deltas["1m_w1"]["delta_max_drawdown_R"] >= 0
            and deltas["1m_w1"]["delta_profit_factor"] is not None
            and deltas["1m_w1"]["delta_profit_factor"] >= 0
        )
        holdout_pass = w1_pass and all(
            candidate_metrics[window]["trade_count"] >= 20
            and deltas[window]["retention_pct"] >= 60.0
            and deltas[window]["delta_net_R"] >= 0
            and deltas[window]["delta_max_drawdown_R"] >= 0
            and deltas[window]["delta_profit_factor"] is not None
            and deltas[window]["delta_profit_factor"] >= 0
            for window in ("1m_w2", "1m_w3")
        )
        candidates.append({
            "candidate_id": f"BLOCK_{dimension.upper()}_{value.upper()}",
            "rule": {"block_dimension": dimension, "block_value": value},
            "metrics": candidate_metrics,
            "delta": deltas,
            "blocked_phenotype": blocked_phenotype,
            "w1_pass": w1_pass,
            "holdout_pass": holdout_pass,
            "selection_scope": "W1_ONLY",
            "production_applied": False,
        })
    return sorted(candidates, key=lambda row: (not row["w1_pass"], -float(row["delta"]["1m_w1"]["delta_net_R"]), row["candidate_id"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--data-root", type=Path, default=Path("/opt/zel/historical-oos-v1"))
    parser.add_argument("--engine", type=Path, default=Path("/opt/zel/research-runtime/data-b-v2/zel_historical_oos_exact25_replay_v1.py"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    trades_path = args.terminal_root / "trades.jsonl.gz"
    source_checks = {
        "terminal_sha_match": file_sha(trades_path) == EXPECTED_TERMINAL_SHA256,
        "engine_sha_match": file_sha(args.engine) == EXPECTED_ENGINE_SHA256,
        "context_sha_match": file_sha(CONTEXT_PATH) == CONTEXT_SHA256,
        "derive_sha_match": file_sha(DERIVE_PATH) == DERIVE_SHA256,
    }
    if not all(source_checks.values()):
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source_checks}")
    rows = read_rows(trades_path)
    if not rows:
        raise RuntimeError("ALPHA_COMBO_TRADES_EMPTY")

    report = json.loads((args.terminal_root / "report.json").read_text(encoding="utf-8"))
    source = report.get("source") if isinstance(report.get("source"), Mapping) else {}
    source_root_raw = source.get("root") if isinstance(source, Mapping) else None
    if not isinstance(source_root_raw, str) or not source_root_raw:
        raise RuntimeError("SOURCE_ROOT_MISSING")
    source_root = Path(source_root_raw).resolve()

    engine = load_module(args.engine, "zel_alpha_combo_engine")
    engine.init_worker(str(source_root), str(args.data_root), "1m")
    manifest = engine._WORKER_MANIFEST
    if not isinstance(manifest, Mapping):
        raise RuntimeError("DATA_MANIFEST_INVALID")
    features, failures, duplicate_count = reconstruct_entry_features(rows, engine=engine, manifest=manifest, data_root=args.data_root)
    reconstruction_pass = len(features) == len(rows) and not failures and duplicate_count == 0
    candidates = single_axis_screen(rows, features) if reconstruction_pass else []

    overall = metrics(rows)
    by_window = {window: metrics([row for row in rows if window_id(row) == window]) for window in WINDOWS}
    selected = next((row for row in candidates if row["w1_pass"]), None)
    holdout_survivor = next((row for row in candidates if row["holdout_pass"]), None)
    sources = source_candidates(source_root)
    blockers: list[str] = []
    if not reconstruction_pass:
        blockers.append("ENTRY_FEATURE_RECONSTRUCTION_INCOMPLETE")
    if not sources:
        blockers.append("SOURCE_OWNER_NOT_FOUND")
    state = "PASS_ALPHA_COMBO_CAUSAL_AUDIT_READY" if not blockers else "HOLD_ALPHA_COMBO_CAUSAL_AUDIT_INCOMPLETE"

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": STRATEGY_ID,
        "source_checks": source_checks,
        "trade_count": len(rows),
        "event_id_set_sha256": stable_sha(sorted(event_id(row) for row in rows)),
        "overall": overall,
        "by_window": by_window,
        "by_side": grouped_metrics(rows, side),
        "by_symbol": grouped_metrics(rows, symbol),
        "by_time_exposure": grouped_metrics(rows, time_bucket),
        "loss_phenotypes": phenotype_metrics(rows),
        "entry_feature_reconstruction": {
            "reconstructed_count": len(features),
            "failure_count": len(failures),
            "failure_counts": dict(Counter(failures)),
            "duplicate_timestamp_count": duplicate_count,
            "pass": reconstruction_pass,
        },
        "source_candidates": sources,
        "single_axis_candidate_count": len(candidates),
        "single_axis_candidates": candidates,
        "best_w1_candidate": selected,
        "holdout_survivor": holdout_survivor,
        "blockers": blockers,
        "selection_authority": False,
        "promotion_authority": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "raw_price_data_published": False,
        "raw_code_published": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "GEMINI_CAUSAL_REVIEW_AND_SINGLE_AXIS_SELECTION" if not blockers else "RESOLVE_SINGLE_ALPHA_AUDIT_BLOCKER",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": state,
        "trades": len(rows),
        "net_R": overall["net_R"],
        "profit_factor": overall["profit_factor"],
        "best_w1": (selected or {}).get("candidate_id"),
        "holdout_survivor": (holdout_survivor or {}).get("candidate_id"),
        "blockers": blockers,
        "next": receipt["next"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
