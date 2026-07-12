from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

ROOT = Path(os.environ.get("Q4R3_ROOT", "/home/z/z"))
BINDING = ROOT / "backend/config/q4r3_exact25_shadow_binding_v1.json"
MANIFEST = ROOT / "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
EPOCH = ROOT / "runtime/exact25_edge_v1/epoch_latest.json"
CANARY = ROOT / "runtime/exact25_edge_v1/canary/canary_latest.json"
EXPECTED_WRITER = "tools/q4r3_vwap_mfe_mae_capture_sidecar.py"
EXPECTED_WRITER_SHA = "d8120a2b8b4d7ed2ac4d37734eb4d6e37c973dfb163572a6553bd91a13b19e50"
MAX_SCAN_FILES = 500
MAX_FILE_BYTES = 8 * 1024 * 1024
PATH_SUFFIXES = (".json", ".jsonl", ".ndjson", ".csv", ".parquet")
NAME_HINT = re.compile(r"(?i)(vwap|mfe|mae|capture|ledger|position|trade|open|close|pnl|risk|shadow)")
OPEN_GROUPS: Tuple[Set[str], ...] = (
    {"strategy_id", "strategy", "strategy_name"},
    {"entry_ts", "opened_at", "open_ts", "entry_time", "timestamp"},
    {"entry_price", "entry", "avg_entry_price"},
    {"stop_price", "sl", "stop_loss", "initial_stop_price"},
)
CLOSE_GROUPS: Tuple[Set[str], ...] = (
    {"strategy_id", "strategy", "strategy_name"},
    {"exit_ts", "closed_at", "close_ts", "exit_time", "timestamp"},
    {"realized_pnl_usdt", "realized_pnl", "pnl_usdt", "pnl"},
)
JOIN_KEYS = {"position_id", "trade_id", "event_id", "signal_id", "request_id", "open_id", "shadow_id"}
RISK_KEYS = {"initial_risk_usdt", "risk_usdt", "risk_amount", "initial_risk", "stop_price", "sl", "stop_loss"}
MEASUREMENT_KEYS = {"realized_r", "mfe_r", "mae_r", "fee", "slippage", "latency_ms"}


@dataclass
class Surface:
    path: str
    source: str
    size_bytes: int
    mtime_ns: int
    schema_keys: List[str]
    sampled_rows: int
    open_score: int
    close_score: int
    join_keys: List[str]
    risk_keys: List[str]
    measurement_keys: List[str]
    parse_error: Optional[str]
    sha256: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def load_object(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def verify_prerequisites() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    binding = load_object(BINDING)
    manifest = load_object(MANIFEST)
    epoch = load_object(EPOCH)
    canary = load_object(CANARY)
    if binding.get("schema") != "q4r3_exact25_shadow_binding_v1":
        raise ValueError("BINDING_SCHEMA_MISMATCH")
    if binding.get("epoch_id") != "EXACT25_EDGE_V1" or binding.get("shadow_enabled") is not True:
        raise ValueError("BINDING_NOT_EXACT25_SHADOW")
    for key in ("paper_enabled", "live_enabled", "order_enabled", "write_enabled", "canary_enabled"):
        if binding.get(key) is not False:
            raise ValueError(f"PREMATURE_OR_UNSAFE_BINDING_FLAG:{key}")
    if binding.get("authoritative_lifecycle_writer") != EXPECTED_WRITER:
        raise ValueError("WRITER_PATH_MISMATCH")
    if binding.get("authoritative_lifecycle_writer_sha256") != EXPECTED_WRITER_SHA:
        raise ValueError("WRITER_BINDING_SHA_MISMATCH")
    entries = manifest.get("strategies")
    if not isinstance(entries, list) or len(entries) != 25:
        raise ValueError("MANIFEST_NOT_EXACT25")
    ids = [str(item.get("strategy_id") or "") for item in entries if isinstance(item, dict)]
    if len(ids) != 25 or len(set(ids)) != 25 or any(not value for value in ids):
        raise ValueError("MANIFEST_IDENTITY_GAP")
    if epoch.get("epoch_id") != "EXACT25_EDGE_V1" or epoch.get("state") != "CANARY_PASS_FORWARD_WRITE_NOT_STARTED":
        raise ValueError("EPOCH_NOT_CANARY_PASS_READY")
    if epoch.get("write_enabled") is not False or epoch.get("canary_enabled") is not False:
        raise ValueError("EPOCH_FLAGS_NOT_SAFE")
    if canary.get("status") != "PASS_Q4R3_EXACT25_EDGE_V1_SHADOW_CANARY":
        raise ValueError("CANARY_NOT_PASS")
    if canary.get("verdict") != "CANARY_PASS_WRITE_PATH_DUPLICATE_LINEAGE_R_FORMULA" or canary.get("strategy_count") != 25:
        raise ValueError("CANARY_VERDICT_GAP")
    verification = canary.get("verification") or {}
    if verification.get("duplicate_count") != 0 or verification.get("owner_mismatches") or verification.get("formula_mismatches") or verification.get("unsafe_flags"):
        raise ValueError("CANARY_INTEGRITY_GAP")
    writer = ROOT / EXPECTED_WRITER
    if not writer.is_file() or file_sha256(writer) != EXPECTED_WRITER_SHA:
        raise ValueError("WRITER_FILE_SHA_MISMATCH")
    return binding, manifest, epoch, canary


def writer_literal_paths(writer: Path) -> Set[Path]:
    tree = ast.parse(writer.read_text(encoding="utf-8", errors="ignore"))
    values: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            lower = value.lower()
            if any(suffix in lower for suffix in PATH_SUFFIXES) or ("runtime" in lower and "/" in value):
                values.add(value)
    paths: Set[Path] = set()
    for value in values:
        if any(token in value for token in ("{", "}", "%")):
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved != ROOT and ROOT in resolved.parents:
            paths.add(resolved)
    return paths


def recent_hint_paths() -> Set[Path]:
    candidates: List[Path] = []
    for base in (ROOT / "runtime", ROOT / "data"):
        if not base.exists():
            continue
        for current, dirs, files in os.walk(base):
            dirs[:] = [name for name in dirs if name not in {".git", ".venv", "node_modules", "__pycache__"}]
            for filename in files:
                path = Path(current) / filename
                if not filename.lower().endswith(PATH_SUFFIXES) or not NAME_HINT.search(str(path.relative_to(ROOT))):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if 0 < stat.st_size <= MAX_FILE_BYTES:
                    candidates.append(path)
    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    return set(candidates[:MAX_SCAN_FILES])


def flatten_records(value: Any, limit: int = 100) -> List[Mapping[str, Any]]:
    records: List[Mapping[str, Any]] = []
    def visit(item: Any) -> None:
        if len(records) >= limit:
            return
        if isinstance(item, dict):
            records.append(item)
            for child in item.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
                if len(records) >= limit:
                    break
    visit(value)
    return records


def read_sample(path: Path) -> Tuple[List[Mapping[str, Any]], Optional[str]]:
    try:
        suffix = path.suffix.lower()
        if suffix in {".jsonl", ".ndjson"}:
            rows: List[Mapping[str, Any]] = []
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
                    if len(rows) >= 100:
                        break
            return rows, None
        if suffix == ".json":
            return flatten_records(json.loads(path.read_text(encoding="utf-8", errors="ignore"))), None
        if suffix == ".csv":
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                header = [field for field in handle.readline().strip().split(",") if field]
            return [{field: None for field in header}], None
        if suffix == ".parquet":
            return [], "PARQUET_SCHEMA_DEFERRED"
        return [], "UNSUPPORTED_SUFFIX"
    except Exception as exc:
        return [], f"{type(exc).__name__}:{str(exc)[:180]}"


def score_groups(keys: Set[str], groups: Sequence[Set[str]]) -> int:
    return sum(1 for group in groups if keys.intersection({item.lower() for item in group}))


def inspect_surface(path: Path, source: str) -> Surface:
    rows, error = read_sample(path)
    keys: Set[str] = set()
    for row in rows:
        keys.update(str(key) for key in row.keys())
    normalized = {key.lower() for key in keys}
    stat = path.stat()
    return Surface(
        path=str(path),
        source=source,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        schema_keys=sorted(keys),
        sampled_rows=len(rows),
        open_score=score_groups(normalized, OPEN_GROUPS),
        close_score=score_groups(normalized, CLOSE_GROUPS),
        join_keys=sorted(key for key in keys if key.lower() in JOIN_KEYS),
        risk_keys=sorted(key for key in keys if key.lower() in RISK_KEYS),
        measurement_keys=sorted(key for key in keys if key.lower() in MEASUREMENT_KEYS),
        parse_error=error,
        sha256=file_sha256(path),
    )


def select_surface(surfaces: Sequence[Surface], role: str) -> Tuple[Optional[Surface], List[str]]:
    attribute = "open_score" if role == "open" else "close_score"
    minimum = 4 if role == "open" else 3
    eligible = [item for item in surfaces if getattr(item, attribute) >= minimum and item.join_keys]
    eligible.sort(key=lambda item: (getattr(item, attribute), bool(item.risk_keys), bool(item.measurement_keys), item.mtime_ns), reverse=True)
    if not eligible:
        return None, [f"NO_{role.upper()}_SURFACE_WITH_JOIN_KEY"]
    best = eligible[0]
    if len(eligible) > 1:
        first_rank = (getattr(best, attribute), bool(best.risk_keys), bool(best.measurement_keys), best.mtime_ns)
        second = eligible[1]
        second_rank = (getattr(second, attribute), bool(second.risk_keys), bool(second.measurement_keys), second.mtime_ns)
        if first_rank == second_rank:
            return None, [f"AMBIGUOUS_{role.upper()}_SURFACE"]
    return best, []


def writer_services(writer: Path) -> List[Dict[str, Any]]:
    listed = subprocess.run(["systemctl", "list-units", "--all", "--type=service", "--no-legend", "--no-pager"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    references: List[Dict[str, Any]] = []
    for line in listed.stdout.splitlines():
        unit = line.split(None, 1)[0] if line.strip() else ""
        if not unit:
            continue
        shown = subprocess.run(["systemctl", "show", unit, "-p", "ExecStart", "-p", "ActiveState", "-p", "SubState", "-p", "MainPID"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
        if str(writer) not in shown.stdout and EXPECTED_WRITER not in shown.stdout:
            continue
        record: Dict[str, Any] = {"unit": unit}
        for row in shown.stdout.splitlines():
            if "=" not in row:
                continue
            key, value = row.split("=", 1)
            record[key] = int(value) if key == "MainPID" and value.isdigit() else ("AUTHORITATIVE_WRITER_REFERENCE_PRESENT" if key == "ExecStart" else value)
        references.append(record)
    return references


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        open_path = root / "open.jsonl"
        close_path = root / "close.jsonl"
        open_path.write_text(json.dumps({"strategy_id": "alpha_combo", "entry_ts": "x", "entry_price": 100, "stop_price": 99, "position_id": "p1"}) + "\n", encoding="utf-8")
        close_path.write_text(json.dumps({"strategy_id": "alpha_combo", "exit_ts": "y", "realized_pnl_usdt": 5, "position_id": "p1", "realized_R": 0.5}) + "\n", encoding="utf-8")
        opened = inspect_surface(open_path, "test")
        closed = inspect_surface(close_path, "test")
        assert opened.open_score == 4 and opened.join_keys == ["position_id"] and opened.risk_keys
        assert closed.close_score == 3 and closed.join_keys == ["position_id"] and closed.measurement_keys == ["realized_R"]
        assert select_surface([opened], "open")[0] is not None
        assert select_surface([closed], "close")[0] is not None
    print("SELF_TEST_PASS")


def run(output: Path) -> Dict[str, Any]:
    binding, manifest, epoch, canary = verify_prerequisites()
    writer = ROOT / EXPECTED_WRITER
    literals = writer_literal_paths(writer)
    hints = recent_hint_paths()
    surfaces: List[Surface] = []
    for path in sorted(path for path in literals.union(hints) if path.is_file()):
        try:
            surfaces.append(inspect_surface(path, "writer_literal" if path in literals else "runtime_hint"))
        except OSError:
            continue
    open_surface, open_gaps = select_surface(surfaces, "open")
    close_surface, close_gaps = select_surface(surfaces, "close")
    gaps = open_gaps + close_gaps
    common_join = sorted(set(open_surface.join_keys).intersection(close_surface.join_keys)) if open_surface and close_surface else []
    if open_surface and close_surface and not common_join:
        gaps.append("OPEN_CLOSE_COMMON_JOIN_KEY_MISSING")
    if open_surface and not open_surface.risk_keys:
        gaps.append("OPEN_SURFACE_INITIAL_RISK_INPUT_MISSING")
    if close_surface and not (close_surface.measurement_keys or any(key.lower() in {"realized_pnl", "realized_pnl_usdt", "pnl", "pnl_usdt"} for key in close_surface.schema_keys)):
        gaps.append("CLOSE_SURFACE_REALIZED_PNL_INPUT_MISSING")
    services = writer_services(writer)
    if not services:
        gaps.append("AUTHORITATIVE_WRITER_SYSTEMD_REFERENCE_NOT_FOUND")
    gaps = sorted(set(gaps))
    locked = not gaps
    result = {
        "schema": "q4r3_exact25_forward_writer_io_contract_lock_v1",
        "status": "PASS_Q4R3_EXACT25_FORWARD_WRITER_IO_CONTRACT_LOCK",
        "verdict": "FORWARD_WRITER_IO_CONTRACT_LOCKED" if locked else "FORWARD_WRITER_IO_CONTRACT_GAPS_REMAIN",
        "action": "HOLD",
        "next_action": "ENABLE_FORWARD_MEASUREMENT_WRITER_SHADOW_ONLY_WITH_LOCKED_IO_CONTRACT" if locked else "TRACE_ONLY_REPORTED_IO_GAPS_BEFORE_WRITE_ENABLE",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "epoch_id": "EXACT25_EDGE_V1",
        "strategy_count": len(manifest["strategies"]),
        "canary_status": canary["status"],
        "binding_write_enabled": binding["write_enabled"],
        "epoch_write_enabled": epoch["write_enabled"],
        "authoritative_writer": EXPECTED_WRITER,
        "authoritative_writer_sha256": EXPECTED_WRITER_SHA,
        "writer_literal_path_count": len(literals),
        "inspected_surface_count": len(surfaces),
        "writer_service_references": services,
        "open_surface": open_surface.as_dict() if open_surface else None,
        "close_surface": close_surface.as_dict() if close_surface else None,
        "common_join_keys": common_join,
        "gaps": gaps,
        "surfaces": [surface.as_dict() for surface in sorted(surfaces, key=lambda item: (max(item.open_score, item.close_score), item.mtime_ns), reverse=True)[:80]],
        "safety": {
            "read_only": True,
            "binding_modified": False,
            "epoch_modified": False,
            "production_measurement_write_enabled": False,
            "paper_enabled": False,
            "live_enabled": False,
            "order_enabled": False,
            "historical_backfill_performed": False,
            "raw_rows_published": False,
        },
    }
    atomic_json(output, result)
    print(json.dumps({key: result[key] for key in ("status", "verdict", "next_action", "inspected_surface_count", "common_join_keys", "gaps")}, ensure_ascii=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.output is None:
        raise SystemExit("OUTPUT_REQUIRED")
    run(args.output)


if __name__ == "__main__":
    main()
