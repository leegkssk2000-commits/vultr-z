from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_GRID_SOURCE_AUTHORITY_DISAMBIGUATION_V1"
SCHEMA = "zel.grid.source_authority_disambiguation.receipt.v1"
STRATEGY_ID = "grid_rebalance"
IMPLEMENTATION_PATH = "backend/strategies/grid_rebalance.py"
OWNER_MODULE = "backend.strategies.grid_rebalance"
CALLABLE = "GridRebalanceLBotStrategy.decide"
OWNER_MANIFEST_PATH = "backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"
REGISTRY_PATH = "backend/strategy25/canonical_strategy_registry_v1.json"
SECRET_KEY = re.compile(r"(?i)(secret|token|password|api[_-]?key|private[_-]?key|credential)")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def walk_mappings(value: Any, path: str = "$") -> Iterable[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        yield path, value
        for key, child in value.items():
            yield from walk_mappings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_mappings(child, f"{path}[{index}]")


def safe_scalar_contract(item: Mapping[str, Any]) -> dict[str, Any]:
    contract: dict[str, Any] = {}
    for key, value in item.items():
        key_text = str(key)
        if SECRET_KEY.search(key_text):
            contract[key_text] = "<redacted>"
        elif value is None or isinstance(value, (str, int, float, bool)):
            contract[key_text] = value
        elif isinstance(value, list) and len(value) <= 20 and all(
            child is None or isinstance(child, (str, int, float, bool)) for child in value
        ):
            contract[key_text] = value
        else:
            contract[key_text] = f"<{type(value).__name__}>"
    return contract


def strategy_entries(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for json_path, item in walk_mappings(value):
        if str(item.get("strategy_id") or item.get("strategy") or "") != STRATEGY_ID:
            continue
        rows.append(
            {
                "json_path": json_path,
                "strategy_id": item.get("strategy_id") or item.get("strategy"),
                "owner_path": item.get("owner_path"),
                "owner_module": item.get("owner_module"),
                "implementation_path": item.get("implementation_path"),
                "callable": item.get("callable"),
                "safe_contract": safe_scalar_contract(item),
            }
        )
    return rows


def exact_manifest_binding(entries: list[dict[str, Any]]) -> bool:
    return any(
        row.get("owner_path") == IMPLEMENTATION_PATH
        and row.get("owner_module") == OWNER_MODULE
        for row in entries
    )


def exact_registry_binding(entries: list[dict[str, Any]]) -> bool:
    return any(
        row.get("implementation_path") == IMPLEMENTATION_PATH
        and row.get("callable") == CALLABLE
        for row in entries
    )


def source_root_from_report(report: Mapping[str, Any]) -> Path | None:
    source = report.get("source")
    if not isinstance(source, Mapping):
        return None
    root = source.get("root")
    if not isinstance(root, str) or not root.strip():
        return None
    path = Path(root.strip())
    return path.resolve() if path.is_absolute() else None


def root_evidence(root: Path) -> dict[str, Any]:
    source_path = root / IMPLEMENTATION_PATH
    manifest_path = root / OWNER_MANIFEST_PATH
    registry_path = root / REGISTRY_PATH

    manifest_value: dict[str, Any] | None = None
    registry_value: dict[str, Any] | None = None
    manifest_error: str | None = None
    registry_error: str | None = None
    try:
        manifest_value = read_object(manifest_path)
    except Exception as exc:
        manifest_error = f"{type(exc).__name__}:{exc}"
    try:
        registry_value = read_object(registry_path)
    except Exception as exc:
        registry_error = f"{type(exc).__name__}:{exc}"

    manifest_entries = strategy_entries(manifest_value) if manifest_value is not None else []
    registry_entries = strategy_entries(registry_value) if registry_value is not None else []
    return {
        "root": str(root),
        "source_path": str(source_path),
        "source_exists": source_path.is_file(),
        "source_sha256": sha256_file(source_path),
        "owner_manifest_path": str(manifest_path),
        "owner_manifest_exists": manifest_path.is_file(),
        "owner_manifest_sha256": sha256_file(manifest_path),
        "owner_manifest_entries": manifest_entries,
        "owner_manifest_exact_binding": exact_manifest_binding(manifest_entries),
        "owner_manifest_error": manifest_error,
        "strategy_registry_path": str(registry_path),
        "strategy_registry_exists": registry_path.is_file(),
        "strategy_registry_sha256": sha256_file(registry_path),
        "strategy_registry_entries": registry_entries,
        "strategy_registry_exact_binding": exact_registry_binding(registry_entries),
        "strategy_registry_error": registry_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--terminal-root", type=Path, default=Path("/var/lib/zel-research/data-b-1m-v2"))
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    runtime_root = args.runtime_root.resolve()
    terminal_root = args.terminal_root.resolve()
    report_path = terminal_root / "report.json"
    progress_path = terminal_root / "progress.json"

    report: dict[str, Any] | None = None
    report_error: str | None = None
    try:
        report = read_object(report_path)
    except Exception as exc:
        report_error = f"{type(exc).__name__}:{exc}"

    replay_root = source_root_from_report(report or {})
    runtime = root_evidence(runtime_root)
    replay = root_evidence(replay_root) if replay_root is not None else None

    progress_source_sha: str | None = None
    if progress_path.is_file():
        try:
            progress_source_sha = str(read_object(progress_path).get("source_sha") or "") or None
        except Exception:
            progress_source_sha = None

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, actual: Any, expected: Any) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "actual": actual,
                "expected": expected,
            }
        )

    check("terminal_report_exists", report_path.is_file(), report_path.is_file(), True)
    check("terminal_report_parse", report is not None, report_error, None)
    check("terminal_replay_root_absolute", replay_root is not None, str(replay_root) if replay_root else None, "absolute path")
    check("runtime_source_exists", runtime["source_exists"], runtime["source_path"], True)
    check("runtime_owner_manifest_exact_binding", runtime["owner_manifest_exact_binding"], runtime["owner_manifest_entries"], {"owner_path": IMPLEMENTATION_PATH, "owner_module": OWNER_MODULE})
    check("runtime_registry_exact_binding", runtime["strategy_registry_exact_binding"], runtime["strategy_registry_entries"], {"implementation_path": IMPLEMENTATION_PATH, "callable": CALLABLE})
    check("replay_source_exists", bool(replay and replay["source_exists"]), replay["source_path"] if replay else None, True)
    check("replay_owner_manifest_exact_binding", bool(replay and replay["owner_manifest_exact_binding"]), replay["owner_manifest_entries"] if replay else None, {"owner_path": IMPLEMENTATION_PATH, "owner_module": OWNER_MODULE})
    check("replay_registry_exact_binding", bool(replay and replay["strategy_registry_exact_binding"]), replay["strategy_registry_entries"] if replay else None, {"implementation_path": IMPLEMENTATION_PATH, "callable": CALLABLE})
    check(
        "runtime_replay_source_sha_parity",
        bool(replay and runtime["source_sha256"] and runtime["source_sha256"] == replay["source_sha256"]),
        {
            "runtime": runtime["source_sha256"],
            "replay": replay["source_sha256"] if replay else None,
        },
        "equal non-null SHA-256",
    )

    blockers = [row["name"] for row in checks if not row["passed"]]
    passed = not blockers
    authority_chain = None
    if passed and replay is not None:
        authority_chain = {
            "logical_authority_count": 1,
            "strategy_id": STRATEGY_ID,
            "canonical_path": runtime["source_path"],
            "terminal_replay_path": replay["source_path"],
            "source_sha256": runtime["source_sha256"],
            "roles": [
                "canonical_owner_manifest_bound",
                "canonical_strategy_registry_bound",
                "terminal_report_source_root_bound",
                "runtime_replay_sha256_parity",
            ],
        }

    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_GRID_LOGICAL_SOURCE_AUTHORITY_UNIQUE" if passed else "HOLD_GRID_LOGICAL_SOURCE_AUTHORITY_UNRESOLVED",
        "strategy_id": STRATEGY_ID,
        "terminal_report_path": str(report_path),
        "terminal_report_sha256": sha256_file(report_path),
        "terminal_report_error": report_error,
        "terminal_replay_root": str(replay_root) if replay_root else None,
        "progress_source_sha": progress_source_sha,
        "runtime_evidence": runtime,
        "replay_evidence": replay,
        "authority_chain": authority_chain,
        "checks": checks,
        "blockers": blockers,
        "logical_authority_count": 1 if passed else 0,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "raw_code_published": False,
        "raw_trade_rows_published": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "MERGE_AUTHORITY_CHAIN_INTO_LINEAGE_AUDIT" if passed else "RESOLVE_EXACT_SOURCE_AUTHORITY_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
