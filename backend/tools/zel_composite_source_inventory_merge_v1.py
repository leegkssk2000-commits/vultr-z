from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_COMPOSITE_SOURCE_INVENTORY_MERGE_V1"
MODULE_IDS = (
    "STRATEGY_SIGNAL",
    "TRADE_METHOD",
    "SKILL_PROFILE",
    "LBOT",
    "MBOT",
    "OBOT",
    "SBOT",
    "ZBOT",
    "LICO",
    "ZICO",
    "ZLICE",
    "PORTFOLIO_GOVERNOR",
)
REPLACE_FROM_LIVE_PATCH = {"ZBOT", "LICO", "ZICO", "ZLICE"}
EXCLUDED_TOKENS = ("backup", "archive", "quarantine", "fixture", "test", "__pycache__")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def excluded_path(value: str) -> bool:
    parts = value.casefold().replace("\\", "/").split("/")
    return any(token in part for part in parts for token in EXCLUDED_TOKENS)


def normalize_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for raw in files:
        path = str(raw.get("path") or "")
        digest = str(raw.get("sha256") or "")
        if not path or len(digest) != 64 or excluded_path(path):
            continue
        row = {
            "path": path,
            "sha256": digest,
            "size_bytes": int(raw.get("size_bytes") or 0),
            "git_tracked": bool(raw.get("git_tracked")),
            "source_scope": str(raw.get("source_scope") or ("GIT" if raw.get("git_tracked") else "LIVE_VPS")),
        }
        unique[path] = row
    return [unique[path] for path in sorted(unique)]


def binding(module_id: str, policy: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    rows = normalize_files(files)
    payload = [{"path": row["path"], "sha256": row["sha256"]} for row in rows]
    tracked_count = sum(1 for row in rows if row["git_tracked"])
    return {
        "module_id": module_id,
        "selection_policy": policy,
        "file_count": len(rows),
        "git_tracked_count": tracked_count,
        "untracked_count": len(rows) - tracked_count,
        "total_size_bytes": sum(row["size_bytes"] for row in rows),
        "source_bundle_sha256": stable_sha(payload) if rows else None,
        "files": rows,
    }


def git_file_row(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    raw = path.read_bytes()
    return {
        "path": relative,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "git_tracked": True,
        "source_scope": "GIT_MASTER_PR_HEAD",
    }


def merge(base: dict[str, Any], live_patch: dict[str, Any], git_root: Path) -> dict[str, Any]:
    base_bindings = base.get("bindings") if isinstance(base.get("bindings"), dict) else {}
    patch_bindings = live_patch.get("bindings") if isinstance(live_patch.get("bindings"), dict) else {}
    bindings: dict[str, Any] = {}
    errors: list[str] = []

    for module_id in MODULE_IDS:
        if module_id == "PORTFOLIO_GOVERNOR":
            relative = "backend/research/strategy11_portfolio_governor_v1.py"
            path = git_root / relative
            if not path.is_file():
                bindings[module_id] = binding(module_id, "GIT_PORTFOLIO_GOVERNOR_SOURCE", [])
                errors.append("MISSING_GIT_SOURCE:PORTFOLIO_GOVERNOR")
            else:
                bindings[module_id] = binding(
                    module_id,
                    "GIT_PORTFOLIO_GOVERNOR_SOURCE",
                    [git_file_row(git_root, relative)],
                )
            continue

        if module_id in REPLACE_FROM_LIVE_PATCH:
            patch = patch_bindings.get(module_id) if isinstance(patch_bindings.get(module_id), dict) else {}
            files = patch.get("files") if isinstance(patch.get("files"), list) else []
            policy = str(patch.get("selection_policy") or "LIVE_PATCH_SOURCE")
            bindings[module_id] = binding(module_id, policy, files)
        else:
            source = base_bindings.get(module_id) if isinstance(base_bindings.get(module_id), dict) else {}
            files = source.get("files") if isinstance(source.get("files"), list) else []
            policy = str(source.get("selection_policy") or "BASE_LIVE_SOURCE")
            bindings[module_id] = binding(module_id, policy, files)

        if bindings[module_id]["file_count"] == 0:
            errors.append(f"MISSING_SOURCE_BUNDLE:{module_id}")

    digest_to_modules: dict[str, list[str]] = {}
    for module_id, row in bindings.items():
        digest = row.get("source_bundle_sha256")
        if digest:
            digest_to_modules.setdefault(str(digest), []).append(module_id)
    duplicates = {digest: ids for digest, ids in digest_to_modules.items() if len(ids) > 1}
    if duplicates:
        errors.append("DUPLICATE_MODULE_SOURCE_BUNDLE_HASH")

    backup_paths = [
        file["path"]
        for row in bindings.values()
        for file in row["files"]
        if excluded_path(file["path"])
    ]
    if backup_paths:
        errors.append("EXCLUDED_SOURCE_PATH_RETAINED")

    state = "PASS_COMPOSITE_SOURCE_INVENTORY_MERGED" if not errors else "HOLD_COMPOSITE_SOURCE_INVENTORY_MERGED"
    result: dict[str, Any] = {
        "schema_version": "zel.composite.source_inventory.merged.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "module_count": len(bindings),
        "bound_module_count": sum(1 for row in bindings.values() if row["file_count"] > 0),
        "git_tracked_file_count": sum(row["git_tracked_count"] for row in bindings.values()),
        "untracked_file_count": sum(row["untracked_count"] for row in bindings.values()),
        "source_git_pin_required_before_activation": any(row["untracked_count"] > 0 for row in bindings.values()),
        "duplicate_bundle_hashes": duplicates,
        "excluded_source_path_count": len(backup_paths),
        "excluded_source_paths": backup_paths,
        "base_inventory_receipt_sha256": base.get("receipt_sha256"),
        "live_patch_state": live_patch.get("state"),
        "bindings": bindings,
        "errors": sorted(set(errors)),
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
    result["receipt_sha256"] = stable_sha(result)
    return result


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        portfolio = root / "backend/research/strategy11_portfolio_governor_v1.py"
        portfolio.parent.mkdir(parents=True)
        portfolio.write_text("GOV=1\n", encoding="utf-8")
        base_files = {module: [{"path": f"backend/{module.lower()}.py", "sha256": hashlib.sha256(module.encode()).hexdigest(), "size_bytes": 1, "git_tracked": False}] for module in MODULE_IDS if module not in REPLACE_FROM_LIVE_PATCH and module != "PORTFOLIO_GOVERNOR"}
        base = {"bindings": {module: {"selection_policy": "BASE", "files": files} for module, files in base_files.items()}, "receipt_sha256": "a" * 64}
        patch = {"state": "PASS_LIVE_SOURCE_PATCH", "bindings": {module: {"selection_policy": "PATCH", "files": [{"path": f"backend/{module.lower()}/core.py", "sha256": hashlib.sha256((module+'x').encode()).hexdigest(), "size_bytes": 1, "git_tracked": False}]} for module in REPLACE_FROM_LIVE_PATCH}}
        row = merge(base, patch, root)
        assert row["state"] == "PASS_COMPOSITE_SOURCE_INVENTORY_MERGED", row
        assert row["bound_module_count"] == 12, row
        assert row["bindings"]["PORTFOLIO_GOVERNOR"]["git_tracked_count"] == 1
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path)
    parser.add_argument("--live-patch", type=Path)
    parser.add_argument("--git-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.base or not args.live_patch or not args.out:
        parser.error("base, live-patch and out are required")
    row = merge(
        json.loads(args.base.read_text(encoding="utf-8")),
        json.loads(args.live_patch.read_text(encoding="utf-8")),
        args.git_root.resolve(),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": row["state"], "bound": row["bound_module_count"], "tracked": row["git_tracked_file_count"], "untracked": row["untracked_file_count"], "errors": row["errors"]}, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
