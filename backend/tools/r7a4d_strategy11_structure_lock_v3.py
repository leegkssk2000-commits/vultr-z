from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


STRUCTURE_VERSION = "3.0"
INTERVAL_MS = 900_000
EXPECTED_WINDOWS = ("S1", "S2", "S3", "S4", "S5", "S6", "V1", "V2", "H1", "H2")
EXPECTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
PROTECTED_PATHS = (
    "backend/strategy25/canonical_strategy_registry_v1.json",
    "backend/strategy25/canonical_strategy25_config_v1.json",
    "backend/engine",
    "services",
)
BASE_RUNNER = "backend/tools/r7a4d_strategy_indicator_repairs_real_oos.py"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tree_hash(root: Path, relative: str) -> dict[str, str]:
    target = root / relative
    if not target.exists():
        return {relative: "MISSING"}
    if target.is_file():
        return {relative: sha256(target)}
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(target.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def protected_snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in PROTECTED_PATHS:
        result.update(tree_hash(root, relative))
    return result


def load_base(root: Path) -> Any:
    path = root / BASE_RUNNER
    spec = importlib.util.spec_from_file_location("strategy11_structure_lock_base_v3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_true(condition: bool, code: str, blockers: list[str]) -> None:
    if not condition:
        blockers.append(code)


def validate_registry(root: Path, blockers: list[str]) -> dict[str, Any]:
    registry_path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    ids: list[str] = []
    paths: list[str] = []
    rows: list[dict[str, Any]] = []
    for row in entries:
        if not isinstance(row, Mapping):
            blockers.append("REGISTRY_ROW_NOT_MAPPING")
            continue
        strategy_id = str(row.get("strategy_id") or "")
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), Mapping) else {}
        relative = str(engine.get("implementation_path") or "")
        expected = str(engine.get("source_sha256") or "")
        path = root / relative
        actual = sha256(path) if path.is_file() and not path.is_symlink() else "MISSING"
        ids.append(strategy_id)
        paths.append(relative)
        if not strategy_id or not relative or actual != expected:
            blockers.append(f"OWNER_SOURCE_SHA:{strategy_id}:{relative}:{actual}:{expected}")
        rows.append({"strategy_id": strategy_id, "path": relative, "expected_sha": expected, "actual_sha": actual})
    assert_true(len(entries) == 25, f"REGISTRY_COUNT:{len(entries)}", blockers)
    assert_true(len(set(ids)) == 25, "DUPLICATE_STRATEGY_OWNER", blockers)
    assert_true(len(set(paths)) == 25, "DUPLICATE_SOURCE_OWNER", blockers)
    assert_true(payload.get("active_entry_count") == 0, "ACTIVE_ENTRY_NOT_ZERO", blockers)
    return {"registry_sha": sha256(registry_path), "entries": rows}


def timestamp_ms(frame: pd.DataFrame) -> pd.Series:
    if "timestamp_ms" in frame.columns:
        return pd.to_numeric(frame["timestamp_ms"], errors="coerce").astype("Int64")
    if "timestamp" in frame.columns:
        return (pd.to_datetime(frame["timestamp"], utc=True).astype("int64") // 1_000_000).astype("Int64")
    raise ValueError("TIMESTAMP_COLUMN_MISSING")


def validate_cache(root: Path, blockers: list[str]) -> dict[str, Any]:
    cache = root / "artifacts/strategy11_market_cache_v2"
    manifest_path = cache / "manifest.json"
    if not manifest_path.is_file():
        blockers.append("CACHE_MANIFEST_MISSING")
        return {"files": []}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_rows = int(manifest.get("window_bars") or 0)
    manifest_rows = {
        (str(row.get("window_id")), str(row.get("symbol"))): row
        for row in manifest.get("rows", []) if isinstance(row, Mapping)
    }
    results: list[dict[str, Any]] = []
    for window in EXPECTED_WINDOWS:
        for symbol in EXPECTED_SYMBOLS:
            key = (window, symbol)
            row = manifest_rows.get(key)
            path = cache / f"{window}-{symbol}.csv"
            if row is None or not path.is_file():
                blockers.append(f"CACHE_MISSING:{window}:{symbol}")
                continue
            frame = pd.read_csv(path)
            try:
                ts = timestamp_ms(frame)
                numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
                finite = bool(numeric.apply(lambda col: col.map(math.isfinite)).all().all())
                start_ms = int(row.get("start_ms"))
                end_ms = int(row.get("end_ms"))
                checks = {
                    "rows": len(frame) == expected_rows == 900,
                    "duplicates": not bool(ts.duplicated().any()),
                    "sorted": bool(ts.is_monotonic_increasing),
                    "gap": bool((ts.diff().dropna() == INTERVAL_MS).all()),
                    "bounds": int(ts.iloc[0]) == start_ms and int(ts.iloc[-1]) == end_ms,
                    "finite": finite,
                    "ohlc": bool(((numeric["high"] >= numeric[["open", "close", "low"]].max(axis=1)) & (numeric["low"] <= numeric[["open", "close", "high"]].min(axis=1))).all()),
                    "positive_price": bool((numeric[["open", "high", "low", "close"]] > 0).all().all()),
                    "nonnegative_volume": bool((numeric["volume"] >= 0).all()),
                    "fresh_fetch": str(row.get("endpoint")) != "CACHE_REUSE",
                }
                for name, passed in checks.items():
                    if not passed:
                        blockers.append(f"CACHE_{name.upper()}:{window}:{symbol}")
                results.append({"window_id": window, "symbol": symbol, "sha256": sha256(path), "checks": checks, "start_ms": start_ms, "end_ms": end_ms})
            except Exception as exc:
                blockers.append(f"CACHE_EXCEPTION:{window}:{symbol}:{type(exc).__name__}:{exc}")
    assert_true(len(results) == 50, f"CACHE_FILE_COUNT:{len(results)}", blockers)
    return {"manifest_sha": sha256(manifest_path), "files": results}


def validate_static_causality(root: Path, registry: Mapping[str, Any], blockers: list[str]) -> dict[str, Any]:
    forbidden = (
        re.compile(r"\.shift\(\s*-\d+"),
        re.compile(r"\.iloc\s*\[[^\]]*\+\s*1"),
        re.compile(r"future_(?:high|low|close|open)"),
    )
    findings: list[dict[str, Any]] = []
    for row in registry.get("entries", []):
        path = root / str(row["path"])
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden:
            matches = [match.group(0) for match in pattern.finditer(text)]
            if matches:
                findings.append({"path": str(row["path"]), "pattern": pattern.pattern, "matches": matches[:5]})
                blockers.append(f"STATIC_LOOKAHEAD:{row['strategy_id']}:{pattern.pattern}")
    return {"findings": findings}


def synthetic_replay_checks(root: Path, blockers: list[str]) -> dict[str, Any]:
    base = load_base(root)
    timestamps = pd.date_range("2026-01-01", periods=12, freq="15min", tz="UTC")
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "open": [100.0] * 12,
        "high": [100.2, 100.2, 100.2, 102.0] + [100.2] * 8,
        "low": [99.8, 99.8, 99.8, 98.0] + [99.8] * 8,
        "close": [100.0] * 12,
        "volume": [10.0] * 12,
    })
    signal_ts: list[str] = []
    calls = {"count": 0}
    def strategy(history: pd.DataFrame, **_: Any) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            signal_ts.append(pd.Timestamp(history.iloc[-1]["timestamp"]).isoformat())
            return {"side": "long", "action": "enter", "size": 1.0, "entry": 100.0, "sl": 99.0, "tp": 101.0}
        return {"side": None, "action": "hold", "size": 0.0}
    first = base._replay(frame, strategy, warmup_bars=2, history_bars=20, cost_bps_per_side=4.0)
    calls["count"] = 0
    signal_ts.clear()
    second = base._replay(frame, strategy, warmup_bars=2, history_bars=20, cost_bps_per_side=4.0)
    assert_true(first == second, "SYNTHETIC_REPLAY_NONDETERMINISTIC", blockers)
    trades = first.get("trades", [])
    assert_true(len(trades) == 1, f"SYNTHETIC_TRADE_COUNT:{len(trades)}", blockers)
    if trades:
        trade = trades[0]
        expected_fill = pd.Timestamp(timestamps[3]).isoformat()
        assert_true(trade.get("entry_ts") == expected_fill, f"NEXT_BAR_FILL:{trade.get('entry_ts')}:{expected_fill}", blockers)
        assert_true(trade.get("exit_reason") == "SL_CONSERVATIVE_SAME_BAR", f"SAME_BAR_POLICY:{trade.get('exit_reason')}", blockers)
    known = [{"net_return_pct": 2.0}, {"net_return_pct": -1.0}, {"net_return_pct": 1.0}, {"net_return_pct": -0.5}]
    stats = base._stats(known)
    independent = {"trade_count": 4, "win_count": 2, "loss_count": 2, "win_rate_pct": 50.0, "net_return_pct_sum": 1.5, "net_profit_factor": 2.0, "payoff_ratio": 2.0, "average_win_pct": 1.5, "average_loss_pct_abs": 0.75, "max_drawdown_pct": 1.0}
    for key, expected in independent.items():
        actual = stats.get(key)
        if actual is None or abs(float(actual) - float(expected)) > 1e-12:
            blockers.append(f"METRIC_PARITY:{key}:{actual}:{expected}")
    return {"replay_first": first, "replay_second": second, "metric_stats": stats, "metric_expected": independent}


def json_digest(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def artifact_digests(root: Path, run_root: Path, blockers: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in ("strategy11_screen_v1", "strategy11_exact_v1", "strategy11_final_roster_v1"):
        directory = run_root / relative
        files = sorted(directory.rglob("summary.json")) if directory.is_dir() else []
        if not files:
            blockers.append(f"ARTIFACT_SUMMARY_MISSING:{relative}")
        for path in files:
            result[str(path.relative_to(run_root))] = json_digest(path)
    return result


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--phase", choices=("pre", "post", "digest"), required=True)
    parser.add_argument("--snapshot")
    parser.add_argument("--run-root")
    parser.add_argument("--output", required=True)
    parser.add_argument("--experiment-id", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    blockers: list[str] = []
    report: dict[str, Any] = {"structure_version": STRUCTURE_VERSION, "experiment_id": args.experiment_id, "phase": args.phase, "authority": "READ_ONLY_RESEARCH_NO_EXECUTION"}

    if args.phase == "pre":
        registry = validate_registry(root, blockers)
        report["registry"] = registry
        report["cache"] = validate_cache(root, blockers)
        report["causality"] = validate_static_causality(root, registry, blockers)
        report["fixtures"] = synthetic_replay_checks(root, blockers)
        snapshot = protected_snapshot(root)
        report["protected_before"] = snapshot
        if args.snapshot:
            write_json(Path(args.snapshot), snapshot)
    elif args.phase == "post":
        if not args.snapshot:
            blockers.append("SNAPSHOT_ARGUMENT_MISSING")
        else:
            before = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
            after = protected_snapshot(root)
            changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
            report.update({"protected_before": before, "protected_after": after, "protected_changed": changed})
            if changed:
                blockers.append("PROTECTED_PATH_MUTATION:" + ",".join(changed))
    else:
        if not args.run_root:
            blockers.append("RUN_ROOT_ARGUMENT_MISSING")
        else:
            report["digests"] = artifact_digests(root, Path(args.run_root), blockers)

    report["state"] = "PASS" if not blockers else "HOLD"
    report["blockers"] = blockers
    report["route_allowed"] = False
    report["shadow_allowed"] = False
    report["execution_allowed"] = False
    write_json(Path(args.output), report)
    print(json.dumps({"STATE": report["state"], "PHASE": args.phase, "BLOCKERS": blockers}, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
