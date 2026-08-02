from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "ZEL_REPOSITORY_CLEANUP_READONLY_AUDIT_V1"
EXCLUDED_TOP_LEVEL = {
    ".git", "results", "node_modules", ".venv", "venv",
    "quarantine", "archive", "archives", "backup", "backups",
}
EXCLUDED_ANY_PART = {"__pycache__", ".pytest_cache", ".mypy_cache"}
DEBRIS_SUFFIXES = {".bak", ".old", ".orig", ".rej", ".tmp", ".swp", ".pyc", ".pyo"}
INTENTIONAL_MIRROR_PARTS = {"baseline", "dist", "fixtures", "fixture", "snapshots", "golden"}
ONE_SHOT_MARKERS = ("recovery-once", "one-shot", "oneshot", "execute-once")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_repo_files(root: Path) -> Iterable[tuple[Path, Path]]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        if any(part in EXCLUDED_ANY_PART for part in rel.parts):
            continue
        yield path, rel


def exact_duplicate_groups(root: Path) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[str]] = {}
    for path, rel in iter_repo_files(root):
        size = path.stat().st_size
        if size <= 0 or size > 2_000_000:
            continue
        grouped.setdefault((size, sha256_file(path)), []).append(str(rel))
    rows: list[dict[str, Any]] = []
    for (size, digest), paths in grouped.items():
        if len(paths) < 2:
            continue
        parts = {part.lower() for value in paths for part in Path(value).parts}
        classification = (
            "LIKELY_INTENTIONAL_MIRROR"
            if parts & INTENTIONAL_MIRROR_PARTS
            else "REVIEW_REQUIRED"
        )
        rows.append({
            "sha256": digest,
            "size_bytes": size,
            "count": len(paths),
            "classification": classification,
            "paths": sorted(paths),
        })
    return sorted(rows, key=lambda row: (-row["count"], row["paths"][0]))


def debris_candidates(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path, rel in iter_repo_files(root):
        lower = path.name.lower()
        reasons = []
        if path.suffix.lower() in DEBRIS_SUFFIXES:
            reasons.append("DEBRIS_SUFFIX")
        if lower.endswith("~"):
            reasons.append("EDITOR_BACKUP_SUFFIX")
        if reasons:
            rows.append({
                "path": str(rel),
                "size_bytes": path.stat().st_size,
                "reasons": reasons,
                "sha256": sha256_file(path),
            })
    return sorted(rows, key=lambda row: row["path"])


def workflow_audit(root: Path) -> dict[str, list[dict[str, Any]]]:
    workflow_root = root / ".github/workflows"
    noise: list[dict[str, Any]] = []
    one_shot: list[dict[str, Any]] = []
    if not workflow_root.is_dir():
        return {"noise_candidates": noise, "one_shot_candidates": one_shot}
    for path in sorted(workflow_root.glob("*.y*ml")):
        rel = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8", errors="replace")
        header = text.split("\njobs:", 1)[0]
        automatic = [
            name for name, token in (
                ("push", "push:"),
                ("pull_request", "pull_request:"),
                ("schedule", "schedule:"),
            ) if token in header
        ]
        if len(automatic) >= 2 and "workflow_dispatch:" in header:
            noise.append({
                "path": rel,
                "automatic_triggers": automatic,
                "reason": "MULTIPLE_AUTOMATIC_TRIGGERS_PLUS_MANUAL",
            })
        lower = rel.lower()
        if any(marker in lower for marker in ONE_SHOT_MARKERS):
            one_shot.append({
                "path": rel,
                "reason": "ONE_SHOT_WORKFLOW_NAME_REQUIRES_POST_RUN_REMOVAL_REVIEW",
            })
    return {"noise_candidates": noise, "one_shot_candidates": one_shot}


def build(root: Path) -> dict[str, Any]:
    duplicates = exact_duplicate_groups(root)
    debris = debris_candidates(root)
    workflows = workflow_audit(root)
    suspicious = [row for row in duplicates if row["classification"] == "REVIEW_REQUIRED"]
    payload: dict[str, Any] = {
        "schema_version": "zel.repository_cleanup_readonly_audit.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_REPOSITORY_CLEANUP_READONLY_AUDIT",
        "scope": "MASTER_WORKTREE_EXCLUDING_RESULT_CLONE_AND_ARCHIVE_ZONES",
        "excluded_top_level": sorted(EXCLUDED_TOP_LEVEL),
        "exact_duplicate_group_count": len(duplicates),
        "suspicious_duplicate_group_count": len(suspicious),
        "debris_candidate_count": len(debris),
        "workflow_noise_candidate_count": len(workflows["noise_candidates"]),
        "one_shot_workflow_candidate_count": len(workflows["one_shot_candidates"]),
        "exact_duplicate_groups": duplicates[:300],
        "suspicious_duplicate_groups": suspicious[:200],
        "debris_candidates": debris[:500],
        "workflow_noise_candidates": workflows["noise_candidates"],
        "one_shot_workflow_candidates": workflows["one_shot_candidates"],
        "cleanup_performed": False,
        "deletion_authority": False,
        "quarantine_required_before_deletion": True,
        "recommended_order": [
            "VERIFY_OWNER_AND_ACTIVE_ROUTE",
            "CLASSIFY_INTENTIONAL_MIRRORS",
            "QUARANTINE_REVIEW_REQUIRED_ITEMS",
            "RE_RUN_OWNER_POLICY_AND_13_STAGE_FIXTURE",
            "DELETE_ONLY_AFTER_EXPLICIT_APPROVAL",
        ],
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    payload["receipt_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return payload


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "backend").mkdir()
        (root / "results/backend").mkdir(parents=True)
        (root / ".github/workflows").mkdir(parents=True)
        (root / "backend/a.py").write_text("same\n", encoding="utf-8")
        (root / "backend/b.py").write_text("same\n", encoding="utf-8")
        (root / "results/backend/a.py").write_text("same\n", encoding="utf-8")
        (root / "backend/stale.tmp").write_text("x", encoding="utf-8")
        (root / ".github/workflows/test.yml").write_text(
            "name: test\non:\n  workflow_dispatch:\n  push:\n  pull_request:\njobs:\n  x:\n    runs-on: ubuntu-latest\n",
            encoding="utf-8",
        )
        payload = build(root)
        assert payload["exact_duplicate_group_count"] == 1, payload
        assert all(not any(path.startswith("results/") for path in row["paths"])
                   for row in payload["exact_duplicate_groups"]), payload
        assert payload["debris_candidate_count"] == 1, payload
        assert payload["workflow_noise_candidate_count"] == 1, payload
        assert payload["cleanup_performed"] is False
        assert payload["execution_authority"] == "NONE"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.root or not args.out:
        parser.error("root and out are required")
    payload = build(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "duplicates": payload["exact_duplicate_group_count"],
        "suspicious": payload["suspicious_duplicate_group_count"],
        "debris": payload["debris_candidate_count"],
        "workflow_noise": payload["workflow_noise_candidate_count"],
        "one_shot": payload["one_shot_workflow_candidate_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
