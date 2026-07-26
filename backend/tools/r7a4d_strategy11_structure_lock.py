from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


STRUCTURE_VERSION = "R7A4D_STRATEGY11_STRUCTURE_LOCK_V2"
INTERVAL_MS = 900_000
EXPECTED_ROWS = 900
EXPECTED_STRATEGIES = 25
EXPECTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
EXPECTED_ROLES = ("S1", "S2", "S3", "S4", "S5", "S6", "V1", "V2", "H1", "H2")
LOCK_DIR = Path("artifacts/strategy11_structure_lock_v2")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _strict_json(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"NONFINITE_JSON:{value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _walk_finite(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            errors.extend(_walk_finite(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_walk_finite(item, f"{path}[{index}]"))
    elif isinstance(value, float) and not math.isfinite(value):
        errors.append(f"NONFINITE:{path}:{value}")
    return errors


def _registry(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    payload = _strict_json(path)
    blockers: list[str] = []
    rows = [row for row in payload.get("entries", []) if isinstance(row, dict)]
    by_id = {str(row.get("strategy_id")): row for row in rows}
    if payload.get("fail_closed") is not True:
        blockers.append("REGISTRY_NOT_FAIL_CLOSED")
    if payload.get("active_entry_count") != 0:
        blockers.append("REGISTRY_ACTIVE_ENTRY_COUNT_NOT_ZERO")
    if len(rows) != EXPECTED_STRATEGIES or len(by_id) != EXPECTED_STRATEGIES:
        blockers.append(f"REGISTRY_COUNT:{len(rows)}:{len(by_id)}")

    paths: list[str] = []
    callables: list[str] = []
    for strategy_id, row in sorted(by_id.items()):
        if row.get("active_allowed") is not False or row.get("fail_closed") is not True:
            blockers.append(f"REGISTRY_AUTHORITY:{strategy_id}")
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), Mapping) else {}
        repo_path = str(engine.get("implementation_path") or "")
        callable_name = str(engine.get("callable") or "")
        expected_sha = str(engine.get("source_sha256") or "")
        source = root / repo_path
        paths.append(repo_path)
        callables.append(callable_name)
        if not repo_path or not source.is_file() or source.is_symlink():
            blockers.append(f"SOURCE_INVALID:{strategy_id}:{repo_path}")
            continue
        actual_sha = _sha256(source)
        if actual_sha != expected_sha:
            blockers.append(f"SOURCE_SHA_MISMATCH:{strategy_id}:{actual_sha}:{expected_sha}")
        if not callable_name:
            blockers.append(f"CALLABLE_MISSING:{strategy_id}")
    if len(set(paths)) != len(paths):
        blockers.append("DUPLICATE_IMPLEMENTATION_OWNER")
    if len(set(callables)) != len(callables):
        blockers.append("DUPLICATE_CALLABLE_OWNER")
    return by_id, blockers


def _lineage_checks(root: Path) -> list[str]:
    blockers: list[str] = []
    orchestrator = (root / "backend/tools/r7a4d_strategy11_orchestrator.py").read_text(encoding="utf-8")
    exact_v2 = (root / "backend/tools/r7a4d_strategy11_exact_v2.py").read_text(encoding="utf-8")
    exact = (root / "backend/tools/r7a4d_strategy11_exact.py").read_text(encoding="utf-8")
    required_orchestrator = (
        "r7a4d_strategy11_screen_v2.py",
        "r7a4d_strategy11_exact_v2.py",
        "r7a4d_strategy11_aggregate.py",
    )
    for token in required_orchestrator:
        if token not in orchestrator:
            blockers.append(f"CALLER_TOKEN_MISSING:{token}")
    if "r7a4d_strategy11_exact.py\"" in orchestrator:
        blockers.append("LEGACY_EXACT_DIRECT_CALL")
    if "v1.base._fetch_exact = _cached_fetch" not in exact_v2:
        blockers.append("CACHE_ADAPTER_BINDING_MISSING")
    if "base._load_canonical_strategy" not in exact:
        blockers.append("CANONICAL_LOADER_CALL_MISSING")
    if "position is not None or action != \"enter\" or side != \"long\"" not in exact:
        blockers.append("LONG_ONLY_ENTRY_GUARD_MISSING")
    return blockers


def _protected_paths(root: Path, registry: Mapping[str, Mapping[str, Any]]) -> list[Path]:
    paths: set[Path] = {
        root / "backend/strategy25/canonical_strategy_registry_v1.json",
        root / "backend/strategy25/canonical_strategy25_config_v1.json",
        root / "backend/strategy25/read_only_registry_adapter_v1.py",
    }
    for row in registry.values():
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), Mapping) else {}
        repo_path = str(engine.get("implementation_path") or "")
        if repo_path:
            paths.add(root / repo_path)
    for directory in ("backend/engine", "services", "canonical", "policy"):
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.suffix in {".py", ".json", ".yml", ".yaml"}:
                paths.add(path)
    return sorted(paths)


def protected_snapshot(root: Path) -> dict[str, str]:
    registry, blockers = _registry(root)
    if blockers:
        raise RuntimeError("PROTECTED_SNAPSHOT_REGISTRY_INVALID:" + "|".join(blockers))
    return {str(path.relative_to(root)): _sha256(path) for path in _protected_paths(root, registry)}


def protected_diff(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    paths = sorted(set(before) | set(after))
    return [path for path in paths if before.get(path) != after.get(path)]


def _timestamp_ms(frame: pd.DataFrame) -> pd.Series:
    if "timestamp_ms" in frame.columns:
        return frame["timestamp_ms"].astype("int64")
    if "timestamp" in frame.columns:
        return (pd.to_datetime(frame["timestamp"], utc=True).astype("int64") // 1_000_000).astype("int64")
    raise ValueError("TIMESTAMP_COLUMN_MISSING")


def _validate_market_frame(frame: pd.DataFrame, *, start_ms: int, end_ms: int, expected_rows: int) -> list[str]:
    blockers: list[str] = []
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        return ["OHLCV_COLUMNS_MISSING:" + ",".join(sorted(required - set(frame.columns)))]
    if len(frame) != expected_rows:
        blockers.append(f"ROWS:{len(frame)}!={expected_rows}")
    try:
        timestamps = _timestamp_ms(frame)
        if timestamps.duplicated().any():
            blockers.append("DUPLICATE_TIMESTAMP")
        if not timestamps.is_monotonic_increasing:
            blockers.append("TIMESTAMP_NOT_SORTED")
        if len(timestamps) > 1 and not bool((timestamps.diff().dropna() == INTERVAL_MS).all()):
            blockers.append("TIMESTAMP_GAP_OR_WRONG_INTERVAL")
        if len(timestamps) and (int(timestamps.iloc[0]) != start_ms or int(timestamps.iloc[-1]) != end_ms):
            blockers.append("WINDOW_BOUNDARY_MISMATCH")
    except Exception as exc:
        blockers.append(f"TIMESTAMP_INVALID:{type(exc).__name__}:{exc}")

    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        blockers.append("OHLCV_NONFINITE")
    if bool((numeric[["open", "high", "low", "close"]] <= 0.0).any().any()):
        blockers.append("PRICE_NONPOSITIVE")
    if bool((numeric["volume"] < 0.0).any()):
        blockers.append("VOLUME_NEGATIVE")
    if bool((numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()):
        blockers.append("HIGH_INVARIANT_FAILED")
    if bool((numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()):
        blockers.append("LOW_INVARIANT_FAILED")
    return blockers


def validate_cache(root: Path) -> tuple[dict[str, Any], list[str]]:
    cache = root / "artifacts/strategy11_market_cache_v2"
    manifest_path = cache / "manifest.json"
    blockers: list[str] = []
    if not manifest_path.is_file():
        return {}, ["CACHE_MANIFEST_MISSING"]
    manifest = _strict_json(manifest_path)
    rows = [row for row in manifest.get("rows", []) if isinstance(row, Mapping)]
    expected_pairs = {(role, symbol) for role in EXPECTED_ROLES for symbol in EXPECTED_SYMBOLS}
    actual_pairs = {(str(row.get("window_id")), str(row.get("symbol"))) for row in rows}
    if manifest.get("state") != "PASS" or manifest.get("blockers"):
        blockers.append("CACHE_MANIFEST_NOT_PASS")
    if actual_pairs != expected_pairs:
        blockers.append(f"CACHE_PAIR_SET_MISMATCH:{len(actual_pairs)}")

    file_rows: list[dict[str, Any]] = []
    intervals: list[tuple[int, int, str]] = []
    for row in rows:
        role = str(row.get("window_id"))
        symbol = str(row.get("symbol"))
        start_ms = int(row.get("start_ms") or 0)
        end_ms = int(row.get("end_ms") or 0)
        path = cache / f"{role}-{symbol}.csv"
        if not path.is_file():
            blockers.append(f"CACHE_FILE_MISSING:{role}:{symbol}")
            continue
        try:
            frame = pd.read_csv(path)
            errors = _validate_market_frame(frame, start_ms=start_ms, end_ms=end_ms, expected_rows=EXPECTED_ROWS)
            blockers.extend(f"{role}:{symbol}:{error}" for error in errors)
            file_rows.append({
                "window_id": role,
                "symbol": symbol,
                "rows": len(frame),
                "sha256": _sha256(path),
                "start_ms": start_ms,
                "end_ms": end_ms,
            })
            intervals.append((start_ms, end_ms, role))
        except Exception as exc:
            blockers.append(f"CACHE_READ:{role}:{symbol}:{type(exc).__name__}:{exc}")

    role_intervals: dict[str, tuple[int, int]] = {}
    for start_ms, end_ms, role in intervals:
        role_intervals.setdefault(role, (start_ms, end_ms))
        if role_intervals[role] != (start_ms, end_ms):
            blockers.append(f"ROLE_BOUNDARY_DIVERGENCE:{role}")
    ordered = sorted((start, end, role) for role, (start, end) in role_intervals.items())
    for left, right in zip(ordered, ordered[1:]):
        if left[1] >= right[0]:
            blockers.append(f"WINDOW_OVERLAP:{left[2]}:{right[2]}")

    combined = hashlib.sha256()
    for item in sorted(file_rows, key=lambda value: (value["window_id"], value["symbol"])):
        combined.update(f"{item['window_id']}|{item['symbol']}|{item['sha256']}\n".encode("utf-8"))
    return {
        "file_count": len(file_rows),
        "data_set_sha256": combined.hexdigest(),
        "files": file_rows,
        "window_intervals": [
            {"window_id": role, "start_ms": start, "end_ms": end}
            for start, end, role in ordered
        ],
    }, blockers


def _load_exact(root: Path) -> Any:
    path = root / "backend/tools/r7a4d_strategy11_exact.py"
    name = "r7a4d_strategy11_exact_structure_lock_v2"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("EXACT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _independent_stats(trades: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(trade["net_return_pct"]) for trade in trades]
    wins = [value for value in returns if value > 0.0]
    losses = [value for value in returns if value < 0.0]
    gross_gain = sum(wins)
    gross_loss = abs(sum(losses))
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    average_win = sum(wins) / len(wins) if wins else None
    average_loss = abs(sum(losses) / len(losses)) if losses else None
    return {
        "trade_count": len(returns),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": len(wins) / len(returns) * 100.0 if returns else None,
        "net_return_pct_sum": sum(returns),
        "net_profit_factor": gross_gain / gross_loss if gross_loss > 0.0 else (999.0 if gross_gain > 0.0 else None),
        "payoff_ratio": average_win / average_loss if average_win is not None and average_loss not in (None, 0.0) else None,
        "average_win_pct": average_win,
        "average_loss_pct_abs": average_loss,
        "max_drawdown_pct": drawdown,
    }


def _metric_equal(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= tolerance
    return left == right


def run_fixture_checks(root: Path) -> tuple[dict[str, Any], list[str]]:
    from backend.strategy25.strategy11_feature_library_v1 import ExitSpec, GateSpec, compute_feature_frame

    blockers: list[str] = []
    exact = _load_exact(root)
    count = 245
    timestamp = pd.date_range("2025-01-01T00:00:00Z", periods=count, freq="15min")
    frame = pd.DataFrame({
        "timestamp": timestamp,
        "timestamp_ms": (timestamp.astype("int64") // 1_000_000).astype("int64"),
        "ts": (timestamp.astype("int64") // 1_000_000).astype("int64"),
        "open": np.full(count, 100.0),
        "high": np.full(count, 100.2),
        "low": np.full(count, 99.8),
        "close": np.full(count, 100.0),
        "volume": np.full(count, 1000.0),
    })
    signal_index = 220
    fill_index = 221
    frame.loc[signal_index, ["open", "high", "low", "close"]] = [100.0, 101.2, 99.8, 101.0]
    frame.loc[fill_index, ["open", "high", "low", "close"]] = [102.0, 104.0, 100.0, 102.0]
    features = compute_feature_frame(frame)

    def strategy(history: pd.DataFrame, state: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        if not (state or {}).get("position_side") and abs(float(history["close"].iloc[-1]) - 101.0) <= 1e-12:
            return {
                "side": "long", "action": "enter", "size": 1.0,
                "entry": 101.0, "sl": 100.0, "tp": 102.0,
                "why": "STRUCTURE_FIXTURE", "skill": "fixture", "tags": ["fixture"],
            }
        return {"side": None, "action": "hold", "size": 0.0, "why": "hold", "skill": "none", "tags": []}

    kwargs = {
        "warmup_bars": 220,
        "history_bars": 220,
        "cost_bps_per_side": 4.0,
    }
    first = exact._replay(frame, features, strategy, GateSpec("BASE", "fixture"), ExitSpec("ORIG"), None, **kwargs)
    second = exact._replay(frame, features, strategy, GateSpec("BASE", "fixture"), ExitSpec("ORIG"), None, **kwargs)
    if json.dumps(first, sort_keys=True, allow_nan=False) != json.dumps(second, sort_keys=True, allow_nan=False):
        blockers.append("DETERMINISTIC_REPLAY_MISMATCH")
    trades = first.get("trades", [])
    if len(trades) != 1:
        blockers.append(f"FIXTURE_TRADE_COUNT:{len(trades)}")
    else:
        trade = trades[0]
        expected_signal = pd.Timestamp(frame["timestamp"].iloc[signal_index]).isoformat()
        expected_fill = pd.Timestamp(frame["timestamp"].iloc[fill_index]).isoformat()
        if trade.get("signal_ts") != expected_signal:
            blockers.append("SIGNAL_TIMESTAMP_MISMATCH")
        if trade.get("entry_ts") != expected_fill:
            blockers.append("NEXT_BAR_OPEN_FILL_MISMATCH")
        if trade.get("exit_reason") != "SL_CONSERVATIVE_SAME_BAR":
            blockers.append("SAME_BAR_SL_PRIORITY_MISMATCH")
        if abs(float(trade.get("entry_price")) - 102.0) > 1e-12:
            blockers.append("ENTRY_NOT_NEXT_BAR_OPEN")

    independent = _independent_stats(trades)
    engine = first.get("stats", {})
    metric_mismatches = [key for key in independent if not _metric_equal(independent[key], engine.get(key))]
    if metric_mismatches:
        blockers.append("METRIC_PARITY:" + ",".join(metric_mismatches))

    prefix_length = 235
    prefix_features = compute_feature_frame(frame.iloc[:prefix_length].copy())
    full_row = features.iloc[prefix_length - 1]
    prefix_row = prefix_features.iloc[-1]
    lookahead_mismatches: list[str] = []
    for column in prefix_features.columns:
        left = prefix_row[column]
        right = full_row[column]
        if pd.isna(left) and pd.isna(right):
            continue
        if isinstance(left, (bool, np.bool_)) or isinstance(right, (bool, np.bool_)):
            if bool(left) != bool(right):
                lookahead_mismatches.append(column)
        elif _finite(left) and _finite(right):
            if abs(float(left) - float(right)) > 1e-12:
                lookahead_mismatches.append(column)
        elif str(left) != str(right):
            lookahead_mismatches.append(column)
    if lookahead_mismatches:
        blockers.append("LOOKAHEAD_PREFIX_MISMATCH:" + ",".join(lookahead_mismatches))

    return {
        "deterministic_replay": not any(value.startswith("DETERMINISTIC") for value in blockers),
        "next_bar_open_fill": not any("NEXT_BAR" in value or "ENTRY_NOT" in value for value in blockers),
        "same_bar_sl_first": not any("SAME_BAR" in value for value in blockers),
        "metric_parity": not any(value.startswith("METRIC_PARITY") for value in blockers),
        "lookahead_prefix_invariant": not any(value.startswith("LOOKAHEAD") for value in blockers),
        "fixture_trade": trades[0] if trades else None,
        "engine_stats": engine,
        "independent_stats": independent,
    }, blockers


def _artifact_json_map(root: Path) -> tuple[dict[str, str], list[str]]:
    blockers: list[str] = []
    mapping: dict[str, str] = {}
    targets = (
        root / "artifacts/strategy11_screen_v1",
        root / "artifacts/strategy11_exact_v1",
        root / "artifacts/strategy11_final_roster_v1",
        root / "artifacts/strategy11_orchestrator_v1",
    )
    for target in targets:
        if not target.exists():
            blockers.append(f"ARTIFACT_DIR_MISSING:{target.name}")
            continue
        for path in sorted(target.rglob("*.json")):
            try:
                payload = _strict_json(path)
                blockers.extend(f"{path}:{error}" for error in _walk_finite(payload))
                mapping[str(path.relative_to(root))] = _sha256(path)
            except Exception as exc:
                blockers.append(f"ARTIFACT_JSON:{path}:{type(exc).__name__}:{exc}")
    return mapping, blockers


def validate_run(root: Path) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    screen = sorted((root / "artifacts/strategy11_screen_v1").glob("*/summary.json"))
    exact = sorted((root / "artifacts/strategy11_exact_v1").glob("*/summary.json"))
    if len(screen) != EXPECTED_STRATEGIES:
        blockers.append(f"SCREEN_SUMMARY_COUNT:{len(screen)}")
    if len(exact) != EXPECTED_STRATEGIES:
        blockers.append(f"EXACT_SUMMARY_COUNT:{len(exact)}")
    orchestrator_path = root / "artifacts/strategy11_orchestrator_v1/summary.json"
    roster_path = root / "artifacts/strategy11_final_roster_v1/summary.json"
    for path, name in ((orchestrator_path, "ORCHESTRATOR"), (roster_path, "ROSTER")):
        if not path.is_file():
            blockers.append(f"{name}_SUMMARY_MISSING")
            continue
        payload = _strict_json(path)
        if payload.get("state") != "PASS" or payload.get("blockers"):
            blockers.append(f"{name}_NOT_PASS")
    mapping, json_blockers = _artifact_json_map(root)
    blockers.extend(json_blockers)
    return {
        "screen_summary_count": len(screen),
        "exact_summary_count": len(exact),
        "json_file_count": len(mapping),
        "json_sha256": mapping,
    }, blockers


def _relative_artifact_map(run_root: Path) -> tuple[dict[str, str], list[str]]:
    mapping, blockers = _artifact_json_map(run_root)
    return mapping, blockers


def _capture(root: Path) -> int:
    registry, registry_blockers = _registry(root)
    lineage_blockers = _lineage_checks(root)
    fixtures, fixture_blockers = run_fixture_checks(root)
    snapshot = {str(path.relative_to(root)): _sha256(path) for path in _protected_paths(root, registry)} if not registry_blockers else {}
    blockers = registry_blockers + lineage_blockers + fixture_blockers
    payload = {
        "schema_version": "2.0",
        "structure_version": STRUCTURE_VERSION,
        "state": "PASS" if not blockers else "HOLD",
        "registry_strategy_count": len(registry),
        "protected_before": snapshot,
        "fixture_checks": fixtures,
        "blockers": blockers,
    }
    _atomic_json(root / LOCK_DIR / "capture.json", payload)
    print(json.dumps({"STATE": payload["state"], "BLOCKERS": blockers}, sort_keys=True))
    return 0 if not blockers else 2


def _pre(root: Path) -> int:
    capture_path = root / LOCK_DIR / "capture.json"
    blockers: list[str] = []
    if not capture_path.is_file():
        blockers.append("CAPTURE_MISSING")
        capture = {}
    else:
        capture = _strict_json(capture_path)
        if capture.get("state") != "PASS":
            blockers.append("CAPTURE_NOT_PASS")
    cache, cache_blockers = validate_cache(root)
    blockers.extend(cache_blockers)
    commit = os.environ.get("GITHUB_SHA") or "LOCAL"
    experiment_id = f"{STRUCTURE_VERSION}:{commit}:{cache.get('data_set_sha256', 'NO_DATA')}"
    payload = {
        "schema_version": "2.0",
        "structure_version": STRUCTURE_VERSION,
        "experiment_id": experiment_id,
        "state": "PASS" if not blockers else "HOLD",
        "cache": cache,
        "protected_before_count": len(capture.get("protected_before", {})) if isinstance(capture, Mapping) else 0,
        "blockers": blockers,
    }
    _atomic_json(root / LOCK_DIR / "preflight.json", payload)
    print(json.dumps({"STATE": payload["state"], "EXPERIMENT_ID": experiment_id, "BLOCKERS": blockers}, sort_keys=True))
    return 0 if not blockers else 2


def _compare(root: Path, run_a: Path, run_b: Path) -> int:
    blockers: list[str] = []
    capture_path = root / LOCK_DIR / "capture.json"
    preflight_path = root / LOCK_DIR / "preflight.json"
    if not capture_path.is_file() or not preflight_path.is_file():
        blockers.append("LOCK_INPUT_ARTIFACT_MISSING")
        capture = {}
        preflight = {}
    else:
        capture = _strict_json(capture_path)
        preflight = _strict_json(preflight_path)
        if capture.get("state") != "PASS" or preflight.get("state") != "PASS":
            blockers.append("LOCK_INPUT_NOT_PASS")

    run_a_validation, run_a_blockers = validate_run(run_a)
    run_b_validation, run_b_blockers = validate_run(run_b)
    blockers.extend(f"RUN_A:{value}" for value in run_a_blockers)
    blockers.extend(f"RUN_B:{value}" for value in run_b_blockers)
    map_a, map_a_blockers = _relative_artifact_map(run_a)
    map_b, map_b_blockers = _relative_artifact_map(run_b)
    blockers.extend(f"RUN_A:{value}" for value in map_a_blockers)
    blockers.extend(f"RUN_B:{value}" for value in map_b_blockers)
    differing_artifacts = sorted(path for path in set(map_a) | set(map_b) if map_a.get(path) != map_b.get(path))
    if differing_artifacts:
        blockers.append("FULL_REPLAY_NONDETERMINISTIC:" + ",".join(differing_artifacts[:20]))

    registry, registry_blockers = _registry(root)
    blockers.extend(registry_blockers)
    current = {str(path.relative_to(root)): _sha256(path) for path in _protected_paths(root, registry)} if not registry_blockers else {}
    before = capture.get("protected_before", {}) if isinstance(capture, Mapping) else {}
    mutations = protected_diff(before, current) if isinstance(before, Mapping) else ["PROTECTED_BEFORE_INVALID"]
    if mutations:
        blockers.append("PROTECTED_MUTATION:" + ",".join(mutations[:20]))

    payload = {
        "schema_version": "2.0",
        "structure_version": STRUCTURE_VERSION,
        "experiment_id": preflight.get("experiment_id") if isinstance(preflight, Mapping) else None,
        "state": "PASS" if not blockers else "HOLD",
        "deterministic_full_replay": not differing_artifacts,
        "run_a": run_a_validation,
        "run_b": run_b_validation,
        "protected_before_count": len(before) if isinstance(before, Mapping) else 0,
        "protected_after_count": len(current),
        "protected_mutations": mutations,
        "canonical_mutated": any(path.startswith("backend/strategies/") for path in mutations),
        "registry_mutated": "backend/strategy25/canonical_strategy_registry_v1.json" in mutations,
        "runtime_authority_mutated": any(path.startswith(("backend/engine/", "services/", "canonical/", "policy/")) for path in mutations),
        "route_allowed": False,
        "shadow_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_allowed": False,
        "blockers": blockers,
        "next": "STRUCTURE_LOCKED_PERFORMANCE_REVIEW" if not blockers else "DISCARD_ALL_PERFORMANCE_AND_REPAIR_STRUCTURE",
    }
    _atomic_json(root / LOCK_DIR / "final.json", payload)
    print(json.dumps({
        "STATE": payload["state"],
        "DETERMINISTIC": payload["deterministic_full_replay"],
        "MUTATIONS": mutations,
        "BLOCKERS": blockers,
        "NEXT": payload["next"],
    }, sort_keys=True))
    return 0 if not blockers else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("capture", "pre", "compare"))
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-a")
    parser.add_argument("--run-b")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.mode == "capture":
        return _capture(root)
    if args.mode == "pre":
        return _pre(root)
    if not args.run_a or not args.run_b:
        raise ValueError("COMPARE_RUN_PATHS_REQUIRED")
    return _compare(root, Path(args.run_a).resolve(), Path(args.run_b).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
