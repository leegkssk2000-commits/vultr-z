from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = Path("backend/strategy25/canonical_strategy_registry_v1.json")
ORCHESTRATOR = Path("backend/tools/r7a4d_strategy11_orchestrator.py")
CACHE = Path("artifacts/strategy11_market_cache_v2")
EXACT = Path("artifacts/strategy11_exact_v1")
FINAL = Path("artifacts/strategy11_final_roster_v1/summary.json")
OUT = Path("artifacts/strategy11_structure_lock_v2")
INTERVAL_MS = 900_000
EXPECTED_BARS = 900
EXPECTED_STRATEGIES = 25
PROTECTED = (
    Path("backend/strategy25/canonical_strategy_registry_v1.json"),
    Path("backend/strategy25/canonical_strategy25_config_v1.json"),
    Path("backend/engine"),
    Path("backend/services"),
    Path("backend/router"),
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha(root: Path, path: Path) -> str:
    target = root / path
    if not target.exists():
        return "MISSING"
    files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


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


def _walk_finite(value: Any, path: str = "$") -> list[str]:
    failures: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            failures.extend(_walk_finite(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            failures.extend(_walk_finite(item, f"{path}[{index}]"))
    elif isinstance(value, float) and not math.isfinite(value):
        failures.append(f"NON_FINITE:{path}:{value}")
    return failures


def _extract_orchestrator_strategies(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "STRATEGIES":
                    value = ast.literal_eval(node.value)
                    return tuple(str(item) for item in value)
    raise RuntimeError("ORCHESTRATOR_STRATEGIES_MISSING")


def _callable_exists(source: Path, dotted: str) -> bool:
    parts = dotted.split(".")
    if len(parts) != 2:
        return False
    class_name, method_name = parts
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name for child in node.body)
    return False


def _owner_source_lock(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    registry = json.loads((root / REGISTRY).read_text(encoding="utf-8"))
    entries = registry.get("entries") or []
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    ids = [str(entry.get("strategy_id")) for entry in entries]
    if len(entries) != EXPECTED_STRATEGIES:
        failures.append(f"REGISTRY_COUNT:{len(entries)}!={EXPECTED_STRATEGIES}")
    if len(ids) != len(set(ids)):
        failures.append("REGISTRY_DUPLICATE_STRATEGY_ID")
    if int(registry.get("active_entry_count") or 0) != 0:
        failures.append("REGISTRY_ACTIVE_ENTRY_NONZERO")

    orchestrator_ids = _extract_orchestrator_strategies(root / ORCHESTRATOR)
    if tuple(sorted(orchestrator_ids)) != tuple(sorted(ids)):
        failures.append("ORCHESTRATOR_REGISTRY_ID_MISMATCH")
    if len(orchestrator_ids) != len(set(orchestrator_ids)):
        failures.append("ORCHESTRATOR_DUPLICATE_STRATEGY_ID")

    seen_paths: dict[str, str] = {}
    for entry in entries:
        strategy_id = str(entry.get("strategy_id"))
        engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), Mapping) else {}
        implementation = str(engine.get("implementation_path") or "")
        callable_name = str(engine.get("callable") or "")
        expected_sha = str(engine.get("source_sha256") or "")
        source = root / implementation
        actual_sha = _sha(source) if source.is_file() else "MISSING"
        row = {
            "strategy_id": strategy_id,
            "implementation_path": implementation,
            "callable": callable_name,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
        }
        rows.append(row)
        if not source.is_file():
            failures.append(f"SOURCE_MISSING:{strategy_id}:{implementation}")
            continue
        if expected_sha != actual_sha:
            failures.append(f"SOURCE_SHA_MISMATCH:{strategy_id}")
        if not _callable_exists(source, callable_name):
            failures.append(f"CALLABLE_MISSING:{strategy_id}:{callable_name}")
        previous = seen_paths.get(implementation)
        if previous is not None and previous != strategy_id:
            failures.append(f"DUPLICATE_OWNER:{implementation}:{previous}:{strategy_id}")
        seen_paths[implementation] = strategy_id
        if bool(entry.get("active_allowed")):
            failures.append(f"ACTIVE_ALLOWED_TRUE:{strategy_id}")
        if not bool(entry.get("fail_closed")):
            failures.append(f"FAIL_CLOSED_FALSE:{strategy_id}")
    return rows, failures


def _data_lock(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    manifest_path = root / CACHE / "manifest.json"
    if not manifest_path.is_file():
        return [], ["DATA_MANIFEST_MISSING"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = _walk_finite(manifest)
    rows: list[dict[str, Any]] = []
    manifest_rows = manifest.get("rows") or []
    if len(manifest_rows) != 50:
        failures.append(f"DATA_MANIFEST_ROW_COUNT:{len(manifest_rows)}!=50")
    for item in manifest_rows:
        if item.get("status") != "PASS":
            failures.append(f"DATA_STATUS_NOT_PASS:{item}")
            continue
        path = root / Path(str(item.get("path")))
        if not path.is_file():
            failures.append(f"DATA_FILE_MISSING:{path}")
            continue
        frame = pd.read_csv(path)
        if "timestamp" not in frame.columns:
            failures.append(f"DATA_TIMESTAMP_MISSING:{path.name}")
            continue
        ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        numeric_columns = [column for column in ("open", "high", "low", "close", "volume") if column in frame.columns]
        row = {
            "window_id": item.get("window_id"),
            "symbol": item.get("symbol"),
            "rows": len(frame),
            "sha256": _sha(path),
            "first_ts": None if ts.isna().all() else ts.iloc[0].isoformat(),
            "last_ts": None if ts.isna().all() else ts.iloc[-1].isoformat(),
        }
        rows.append(row)
        if len(frame) != EXPECTED_BARS:
            failures.append(f"DATA_ROWS:{path.name}:{len(frame)}!={EXPECTED_BARS}")
        if ts.isna().any():
            failures.append(f"DATA_TIMESTAMP_NAN:{path.name}")
        if ts.duplicated().any():
            failures.append(f"DATA_TIMESTAMP_DUPLICATE:{path.name}")
        if not ts.is_monotonic_increasing:
            failures.append(f"DATA_TIMESTAMP_UNSORTED:{path.name}")
        diffs = ts.astype("int64").diff().dropna() // 1_000_000
        if len(diffs) and not (diffs == INTERVAL_MS).all():
            failures.append(f"DATA_INTERVAL_GAP:{path.name}")
        expected_start = int(item.get("start_ms"))
        expected_end = int(item.get("end_ms"))
        if len(ts) and int(ts.iloc[0].timestamp() * 1000) != expected_start:
            failures.append(f"DATA_START_BOUNDARY:{path.name}")
        if len(ts) and int(ts.iloc[-1].timestamp() * 1000) != expected_end:
            failures.append(f"DATA_END_BOUNDARY:{path.name}")
        if set(numeric_columns) != {"open", "high", "low", "close", "volume"}:
            failures.append(f"DATA_OHLCV_COLUMNS:{path.name}")
        else:
            values = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
            if values.isna().any().any():
                failures.append(f"DATA_OHLCV_NAN:{path.name}")
            if (values[["open", "high", "low", "close"]] <= 0).any().any() or (values["volume"] < 0).any():
                failures.append(f"DATA_OHLCV_RANGE:{path.name}")
            if ((values["high"] < values[["open", "close", "low"]].max(axis=1)) | (values["low"] > values[["open", "close", "high"]].min(axis=1))).any():
                failures.append(f"DATA_OHLC_RELATION:{path.name}")
    return rows, failures


def _execution_fixture() -> list[str]:
    failures: list[str] = []
    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
        {"open": 102.0, "high": 106.0, "low": 96.0, "close": 103.0},
    ]
    signal_entry = bars[0]["close"]
    fill_entry = bars[1]["open"]
    if fill_entry == signal_entry:
        failures.append("FIXTURE_NEXT_OPEN_NOT_DISTINCT")
    sl, tp = 98.0, 105.0
    hit_sl = bars[1]["low"] <= sl
    hit_tp = bars[1]["high"] >= tp
    reason = "SL" if hit_sl else ("TP" if hit_tp else "NONE")
    if not (hit_sl and hit_tp and reason == "SL"):
        failures.append("FIXTURE_SAME_BAR_SL_FIRST_FAILED")
    cost = 0.5 * (4.0 / 10_000.0) * 100.0 * 2.0
    expected = 0.04
    if abs(cost - expected) > 1e-12:
        failures.append(f"FIXTURE_COST_PARITY:{cost}!={expected}")
    return failures


def _post_output_lock(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    summaries = sorted((root / EXACT).glob("*/summary.json"))
    if len(summaries) != EXPECTED_STRATEGIES:
        failures.append(f"EXACT_SUMMARY_COUNT:{len(summaries)}!={EXPECTED_STRATEGIES}")
    for path in summaries:
        value = json.loads(path.read_text(encoding="utf-8"))
        failures.extend(f"{path.parent.name}:{item}" for item in _walk_finite(value))
        if value.get("state") != "PASS" or value.get("blockers"):
            failures.append(f"EXACT_NOT_CLEAN:{path.parent.name}")
        for forbidden in ("canonical_mutated", "registry_mutated", "route_allowed", "shadow_allowed", "execution_allowed"):
            if bool(value.get(forbidden)):
                failures.append(f"EXACT_AUTHORITY_VIOLATION:{path.parent.name}:{forbidden}")
        rows.append({"strategy_id": path.parent.name, "sha256": _sha(path), "result_count": value.get("result_count")})
    final_path = root / FINAL
    if not final_path.is_file():
        failures.append("FINAL_SUMMARY_MISSING")
    else:
        final = json.loads(final_path.read_text(encoding="utf-8"))
        failures.extend(_walk_finite(final))
        for forbidden in ("canonical_mutated", "registry_mutated", "route_allowed", "shadow_allowed", "paper_allowed", "live_allowed", "execution_allowed"):
            if bool(final.get(forbidden)):
                failures.append(f"FINAL_AUTHORITY_VIOLATION:{forbidden}")
    return rows, failures


def _deterministic_probe(root: Path) -> tuple[dict[str, Any], list[str]]:
    strategy_id = "vol_spike_fade"
    screen = root / "artifacts/strategy11_screen_v1" / strategy_id / "summary.json"
    if not screen.is_file():
        return {}, ["DETERMINISTIC_SCREEN_MISSING"]
    command = [sys.executable, "backend/tools/r7a4d_strategy11_exact_v2.py", "--root", str(root), "--strategy-id", strategy_id, "--screen-summary", str(screen)]
    target = root / EXACT / strategy_id / "summary.json"
    hashes: list[str] = []
    for _ in range(2):
        completed = subprocess.run(command, cwd=root, env={**os.environ, "PYTHONPATH": "."}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        if completed.returncode != 0:
            return {"strategy_id": strategy_id, "log_tail": completed.stdout[-2000:]}, [f"DETERMINISTIC_RC:{completed.returncode}"]
        hashes.append(_sha(target))
    failures = [] if hashes[0] == hashes[1] else ["DETERMINISTIC_HASH_MISMATCH"]
    return {"strategy_id": strategy_id, "hashes": hashes}, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--phase", choices=("pre", "post"), required=True)
    parser.add_argument("--structure-version", default="strategy11-structure-lock-v2")
    parser.add_argument("--experiment-id", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output_dir = root / OUT
    output_dir.mkdir(parents=True, exist_ok=True)
    protected_snapshot_path = output_dir / "protected-before.json"

    owner_rows, owner_failures = _owner_source_lock(root)
    fixture_failures = _execution_fixture()
    failures = owner_failures + fixture_failures
    report: dict[str, Any] = {
        "schema_version": "2.0",
        "structure_version": args.structure_version,
        "experiment_id": args.experiment_id,
        "phase": args.phase,
        "owner_source": owner_rows,
        "fixture_failures": fixture_failures,
        "canonical_mutated": False,
        "registry_mutated": False,
        "route_allowed": False,
        "shadow_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_allowed": False,
    }

    current_protected = {path.as_posix(): _tree_sha(root, path) for path in PROTECTED}
    if args.phase == "pre":
        _atomic_json(protected_snapshot_path, current_protected)
        report["protected_before"] = current_protected
    else:
        if not protected_snapshot_path.is_file():
            failures.append("PROTECTED_BEFORE_MISSING")
            before = {}
        else:
            before = json.loads(protected_snapshot_path.read_text(encoding="utf-8"))
        mutations = [path for path, sha in before.items() if current_protected.get(path) != sha]
        if mutations:
            failures.append("PROTECTED_MUTATION:" + ",".join(mutations))
        data_rows, data_failures = _data_lock(root)
        output_rows, output_failures = _post_output_lock(root)
        deterministic, deterministic_failures = _deterministic_probe(root)
        failures.extend(data_failures + output_failures + deterministic_failures)
        report.update({
            "protected_before": before,
            "protected_after": current_protected,
            "protected_mutations": mutations,
            "data": data_rows,
            "exact_outputs": output_rows,
            "deterministic_probe": deterministic,
        })

    report["blockers"] = sorted(set(failures))
    report["state"] = "PASS" if not failures else "HOLD"
    report["performance_evidence_valid"] = not failures and args.phase == "post"
    _atomic_json(output_dir / f"{args.phase}.json", report)
    print(json.dumps({"STATE": report["state"], "PHASE": args.phase, "BLOCKERS": report["blockers"]}, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
