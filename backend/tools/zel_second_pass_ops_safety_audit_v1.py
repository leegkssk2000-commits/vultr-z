#!/usr/bin/env python3
"""Read-only second-pass ZEL owner/service/DB/AI operational safety audit."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

SAFETY = {
    "canonical_mutated": False,
    "registry_mutated": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
}

OWNER_TERMS = {
    "state": ("state_manager", "state_store", "state_db", "state_writer", "snapshot_writer"),
    "selector": ("selector", "strategy_selector", "route_selector"),
    "ledger": ("ledger_writer", "pnl_writer", "trade_writer", "close_writer"),
}
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3")
EXCLUDED_TOKENS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "backup",
    "archive", "rollback", "restore", "snapshot", "trash", "__pycache__",
}
APPROVED_AI_FILES = {
    "scripts/strategy11_ai_review_router.py",
    "scripts/strategy11_groq_redteam.py",
    "scripts/strategy11_workers_ai_guard.py",
    "scripts/strategy11_github_models_review.py",
    ".github/workflows/strategy11-ai-review-router-v1.yml",
    "backend/tools/zel_second_pass_ops_safety_audit_v1.py",
    ".github/workflows/zel-second-pass-ops-safety-audit-v1.yml",
}
DIRECT_AI_MARKERS = (
    "api.groq.com", "CLOUDFLARE_WORKERS_AI_TOKEN", "models.github.ai",
    "strategy11_groq_redteam.py", "strategy11_workers_ai_guard.py",
    "strategy11_github_models_review.py",
)
DEPENDENCY_NAMES = {
    "pyproject.toml", "poetry.lock", "uv.lock", "Pipfile", "Pipfile.lock",
    "requirements.txt", "requirements-dev.txt", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "active_backend_dependency_lock_v1.json", "active_backend_requirements_lock_v1.txt",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def allowed(path: Path) -> bool:
    for part in path.parts:
        low = part.lower()
        if any(token == low or token in low for token in EXCLUDED_TOKENS):
            return False
    return True


def iter_files(root: Path):
    for base in ("backend", "scripts", "services", "systemd", ".github/workflows", "config"):
        start = root / base
        if not start.exists():
            continue
        for path in start.rglob("*"):
            if path.is_file() and allowed(path.relative_to(root)):
                yield path


def python_owner_and_db_scan(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    owners: dict[str, list[dict[str, Any]]] = defaultdict(list)
    db_refs: list[dict[str, Any]] = []
    import_rows: list[dict[str, Any]] = []

    for path in iter_files(root):
        if path.suffix != ".py":
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=rel)
        except Exception as exc:
            import_rows.append({"path": rel, "parse_state": "ERROR", "error": type(exc).__name__})
            continue

        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name.lower()
                for family, terms in OWNER_TERMS.items():
                    if any(term in name for term in terms):
                        owners[family].append({"path": rel, "symbol": node.name, "line": node.lineno})
            elif isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                low = value.lower()
                if any(suffix in low for suffix in DB_SUFFIXES) or "database_url" in low or "db_path" in low:
                    if len(value) <= 400:
                        db_refs.append({"path": rel, "line": getattr(node, "lineno", None), "value": value})
        import_rows.append({"path": rel, "parse_state": "PASS", "imports": sorted(imports)})

    owner_summary = {
        family: {
            "candidate_count": len(rows),
            "unique_path_count": len({row["path"] for row in rows}),
            "rows": sorted(rows, key=lambda r: (r["path"], r["line"], r["symbol"])),
        }
        for family, rows in sorted(owners.items())
    }
    return owner_summary, sorted(db_refs, key=lambda r: (r["path"], r.get("line") or 0)), import_rows


def repository_surface_scan(root: Path) -> dict[str, Any]:
    units: list[str] = []
    backup_restore: list[str] = []
    dependency_manifests: list[dict[str, Any]] = []
    workflow_permissions: list[dict[str, Any]] = []
    direct_ai_calls: list[dict[str, Any]] = []

    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        low_name = path.name.lower()
        if path.suffix in {".service", ".timer", ".socket"}:
            units.append(rel)
        if any(term in low_name for term in ("backup", "restore", "rollback", "snapshot")):
            backup_restore.append(rel)

        if rel.startswith(".github/workflows/") and path.suffix in {".yml", ".yaml"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            perms = sorted(set(re.findall(r"(?m)^\s{2,}([a-z-]+):\s*(read|write|none)\s*$", text)))
            secrets = sorted(set(re.findall(r"secrets\.([A-Z0-9_]+)", text)))
            workflow_permissions.append({"path": rel, "permissions": perms, "secret_names": secrets})

        if path.suffix.lower() in {".py", ".yml", ".yaml", ".sh", ".json"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            markers = sorted(marker for marker in DIRECT_AI_MARKERS if marker in text)
            if markers and rel not in APPROVED_AI_FILES:
                direct_ai_calls.append({"path": rel, "markers": markers})

    # Dependency files may sit at repository root or outside the bounded runtime roots.
    for path in root.rglob("*"):
        if not path.is_file() or not allowed(path.relative_to(root)):
            continue
        if path.name in DEPENDENCY_NAMES or (path.name.startswith("requirements") and path.suffix == ".txt"):
            rel = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            dependency_manifests.append({"path": rel, "sha256": sha256_bytes(raw), "size_bytes": len(raw)})

    unique_manifests = {row["path"]: row for row in dependency_manifests}
    return {
        "unit_files": sorted(units),
        "backup_restore_surfaces": sorted(set(backup_restore)),
        "dependency_manifests": sorted(unique_manifests.values(), key=lambda r: r["path"]),
        "workflow_permissions": sorted(workflow_permissions, key=lambda r: r["path"]),
        "direct_ai_router_bypass_candidates": sorted(direct_ai_calls, key=lambda r: r["path"]),
    }


def build_import_sbom(import_rows: list[dict[str, Any]]) -> dict[str, Any]:
    modules: dict[str, int] = defaultdict(int)
    parse_errors = 0
    for row in import_rows:
        if row["parse_state"] != "PASS":
            parse_errors += 1
            continue
        for module in row.get("imports", []):
            modules[module] += 1
    return {
        "schema_version": "zel.python_import_sbom.v1",
        "module_count": len(modules),
        "modules": [{"name": name, "file_reference_count": count} for name, count in sorted(modules.items())],
        "parse_error_count": parse_errors,
    }


def backup_restore_fixture() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="zel-restore-fixture-") as tmp:
        root = Path(tmp)
        source = root / "source"
        restored = root / "restored"
        source.mkdir()
        fixtures = {
            "state/sample.json": b'{"state":"fixture","execution_allowed":false}\n',
            "ledger/sample.jsonl": b'{"trade_id":"fixture","pnl_r":0.0}\n',
            "config/sample.txt": b"order_authority=BLOCKED\n",
        }
        for rel, data in fixtures.items():
            path = source / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        source_manifest = {rel: sha256_bytes(data) for rel, data in fixtures.items()}
        archive = root / "fixture.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(source, arcname="payload")
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(restored, filter="data")
        restored_manifest = {
            rel: sha256_bytes((restored / "payload" / rel).read_bytes()) for rel in sorted(fixtures)
        }
        return {
            "state": "PASS_BACKUP_RESTORE_FIXTURE" if restored_manifest == source_manifest else "HOLD_BACKUP_RESTORE_FIXTURE",
            "file_count": len(fixtures),
            "source_manifest_sha256": sha256_bytes(json.dumps(source_manifest, sort_keys=True).encode()),
            "restored_manifest_sha256": sha256_bytes(json.dumps(restored_manifest, sort_keys=True).encode()),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()

    owners, db_refs, import_rows = python_owner_and_db_scan(root)
    surfaces = repository_surface_scan(root)
    sbom = build_import_sbom(import_rows)
    restore = backup_restore_fixture()

    blockers: list[str] = []
    if sbom["parse_error_count"]:
        blockers.append("PYTHON_PARSE_ERRORS")
    if not surfaces["dependency_manifests"]:
        blockers.append("DEPENDENCY_MANIFEST_MISSING")
    if surfaces["direct_ai_router_bypass_candidates"]:
        blockers.append("AI_ROUTER_BYPASS_CANDIDATES")
    if restore["state"] != "PASS_BACKUP_RESTORE_FIXTURE":
        blockers.append("BACKUP_RESTORE_FIXTURE_FAIL")

    result = {
        "schema_version": "zel.second_pass_ops_safety_audit.v1",
        "state": "HOLD_SECOND_PASS_FINDINGS_REQUIRE_ADJUDICATION" if blockers else "PASS_SECOND_PASS_AUDIT_CAPTURED",
        "blocker_codes": blockers,
        "owner_candidates": owners,
        "db_path_references": db_refs,
        "surfaces": surfaces,
        "import_sbom": sbom,
        "backup_restore_fixture": restore,
        "next": "REMOTE_SERVICE_TIMER_WRITER_DB_SNAPSHOT_AND_SINGLE_CAUSE_ADJUDICATION",
        **SAFETY,
    }
    write_json(args.out, result)
    print(result["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
