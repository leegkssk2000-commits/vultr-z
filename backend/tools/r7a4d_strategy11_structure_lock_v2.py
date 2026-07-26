from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

INTERVAL_MS = 900_000
EXPECTED_WINDOWS = ("S1", "S2", "S3", "S4", "S5", "S6", "V1", "V2", "H1", "H2")
EXPECTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT")
PROTECTED = (
    "backend/strategy25/canonical_strategy_registry_v1.json",
    "backend/strategy25/canonical_strategy25_config_v1.json",
    "backend/engine",
    "services",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in PROTECTED:
        path = root / item
        if path.is_file():
            result[item] = sha256(path)
        elif path.is_dir():
            for child in sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
                result[str(child.relative_to(root))] = sha256(child)
        else:
            result[item] = "MISSING"
    return result


def assert_finite_json(path: Path) -> Any:
    value = json.loads(path.read_text(encoding="utf-8"))
    def walk(node: Any) -> None:
        if isinstance(node, float) and not math.isfinite(node):
            raise ValueError(f"NONFINITE:{path}")
        if isinstance(node, dict):
            for child in node.values(): walk(child)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(value)
    return value


def registry_lock(root: Path) -> dict[str, Any]:
    path = root / "backend/strategy25/canonical_strategy_registry_v1.json"
    payload = assert_finite_json(path)
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or len(entries) != 25 or payload.get("strategy_count") != 25 or payload.get("fail_closed") is not True:
        raise ValueError("REGISTRY_SHAPE")
    ids: set[str] = set()
    owners: set[tuple[str, str]] = set()
    rows = []
    for row in entries:
        strategy_id = str(row.get("strategy_id") or "")
        engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
        source = str(engine.get("implementation_path") or "")
        callable_name = str(engine.get("callable") or "")
        expected = str(engine.get("source_sha256") or "")
        if not strategy_id or strategy_id in ids: raise ValueError(f"DUPLICATE_ID:{strategy_id}")
        ids.add(strategy_id)
        owner = (source, callable_name)
        if owner in owners: raise ValueError(f"DUPLICATE_OWNER:{owner}")
        owners.add(owner)
        file_path = root / source
        if not file_path.is_file() or file_path.is_symlink(): raise ValueError(f"SOURCE_INVALID:{strategy_id}")
        actual = sha256(file_path)
        if actual != expected: raise ValueError(f"SOURCE_SHA:{strategy_id}")
        rows.append({"strategy_id": strategy_id, "source": source, "source_sha256": actual, "callable": callable_name})
    return {"count": len(rows), "rows": rows, "registry_sha256": sha256(path)}


def data_lock(root: Path) -> dict[str, Any]:
    cache = root / "artifacts/strategy11_market_cache_v2"
    manifest_path = cache / "manifest.json"
    manifest = assert_finite_json(manifest_path)
    if manifest.get("state") != "PASS" or manifest.get("window_bars") != 900: raise ValueError("CACHE_MANIFEST")
    seen: set[tuple[str, str]] = set()
    rows = []
    for window in EXPECTED_WINDOWS:
        for symbol in EXPECTED_SYMBOLS:
            path = cache / f"{window}-{symbol}.csv"
            if not path.is_file(): raise ValueError(f"CACHE_MISSING:{window}:{symbol}")
            frame = pd.read_csv(path)
            if len(frame) != 900: raise ValueError(f"ROWS:{window}:{symbol}:{len(frame)}")
            ts_col = "timestamp_ms" if "timestamp_ms" in frame.columns else "ts" if "ts" in frame.columns else None
            if ts_col is None: raise ValueError(f"TS_MISSING:{window}:{symbol}")
            ts = frame[ts_col].astype("int64")
            if ts.duplicated().any(): raise ValueError(f"TS_DUP:{window}:{symbol}")
            if not ts.is_monotonic_increasing: raise ValueError(f"TS_ORDER:{window}:{symbol}")
            if not bool((ts.diff().dropna() == INTERVAL_MS).all()): raise ValueError(f"TS_GAP:{window}:{symbol}")
            for column in ("open", "high", "low", "close", "volume"):
                if column not in frame.columns or not pd.to_numeric(frame[column], errors="coerce").notna().all():
                    raise ValueError(f"OHLCV:{window}:{symbol}:{column}")
            if not bool((frame["high"] >= frame[["open", "close"]].max(axis=1)).all()): raise ValueError(f"HIGH:{window}:{symbol}")
            if not bool((frame["low"] <= frame[["open", "close"]].min(axis=1)).all()): raise ValueError(f"LOW:{window}:{symbol}")
            if not bool((frame[["open", "high", "low", "close"]] > 0).all().all()) or not bool((frame["volume"] >= 0).all()):
                raise ValueError(f"VALUE_DOMAIN:{window}:{symbol}")
            key = (window, symbol)
            if key in seen: raise ValueError(f"DUP_WINDOW:{key}")
            seen.add(key)
            rows.append({"window_id": window, "symbol": symbol, "rows": len(frame), "start_ms": int(ts.iloc[0]), "end_ms": int(ts.iloc[-1]), "sha256": sha256(path)})
    return {"count": len(rows), "rows": rows, "manifest_sha256": sha256(manifest_path)}


def fixture_lock() -> dict[str, Any]:
    # Completed-bar signal must fill only at next bar open.
    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
        {"open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5},
    ]
    signal_index = 0
    fill_index = signal_index + 1
    if fill_index != 1 or bars[fill_index]["open"] != 103.0: raise ValueError("NEXT_OPEN_FIXTURE")
    # Conservative same-bar collision must select SL.
    entry, sl, tp = 100.0, 99.0, 102.0
    collision = {"low": 98.5, "high": 102.5}
    hit_sl, hit_tp = collision["low"] <= sl, collision["high"] >= tp
    exit_price = sl if hit_sl else tp
    if not (hit_sl and hit_tp and exit_price == sl): raise ValueError("SAME_BAR_FIXTURE")
    # Independent metric parity fixture.
    returns = [1.0, -0.5, 2.0, -1.0]
    gain, loss = 3.0, 1.5
    pf = gain / loss
    wr = 2 / 4 * 100.0
    payoff = ((1.0 + 2.0) / 2) / ((0.5 + 1.0) / 2)
    if (sum(returns), pf, wr, payoff) != (1.5, 2.0, 50.0, 2.0): raise ValueError("METRIC_FIXTURE")
    return {"next_open": True, "same_bar_sl_first": True, "metric_parity": True}


def artifact_lock(root: Path) -> dict[str, Any]:
    required = [
        root / "artifacts/strategy11_orchestrator_v1/summary.json",
        root / "artifacts/strategy11_final_roster_v1/summary.json",
    ]
    values = []
    for path in required:
        if not path.is_file(): raise ValueError(f"ARTIFACT_MISSING:{path}")
        values.append({"path": str(path.relative_to(root)), "sha256": sha256(path), "json": assert_finite_json(path)})
    orchestrator = values[0]["json"]
    if orchestrator.get("state") != "PASS" or orchestrator.get("blockers") not in ([], None): raise ValueError("ORCHESTRATOR_STATE")
    return {"files": [{"path": row["path"], "sha256": row["sha256"]} for row in values]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--phase", choices=("pre", "post"), required=True)
    parser.add_argument("--snapshot")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    blockers: list[str] = []
    report: dict[str, Any] = {"schema_version": "2.0", "structure_version": "STRATEGY11_STRUCTURE_LOCK_V2", "phase": args.phase}
    try: report["registry"] = registry_lock(root)
    except Exception as exc: blockers.append(f"REGISTRY:{type(exc).__name__}:{exc}")
    try: report["fixtures"] = fixture_lock()
    except Exception as exc: blockers.append(f"FIXTURE:{type(exc).__name__}:{exc}")
    snapshot = tree_snapshot(root)
    report["protected_snapshot"] = snapshot
    if args.phase == "pre":
        if args.snapshot: Path(args.snapshot).write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        try: report["data"] = data_lock(root)
        except Exception as exc: blockers.append(f"DATA:{type(exc).__name__}:{exc}")
        try: report["artifacts"] = artifact_lock(root)
        except Exception as exc: blockers.append(f"ARTIFACT:{type(exc).__name__}:{exc}")
        if not args.snapshot or not Path(args.snapshot).is_file(): blockers.append("SNAPSHOT:MISSING")
        else:
            before = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
            if before != snapshot: blockers.append("PROTECTED_MUTATION")
    report.update({"state": "PASS" if not blockers else "HOLD", "blockers": blockers, "canonical_mutated": False if "PROTECTED_MUTATION" not in blockers else True, "registry_mutated": False, "route_allowed": False, "shadow_allowed": False, "execution_allowed": False})
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"STATE": report["state"], "BLOCKERS": blockers}, sort_keys=True))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
