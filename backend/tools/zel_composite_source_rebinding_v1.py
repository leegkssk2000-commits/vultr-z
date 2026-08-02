from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "ZEL_COMPOSITE_SOURCE_REBINDING_V1"
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
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "tests",
    "test",
    "tools",
    "fixtures",
    "evidence",
    "runtime_results",
    "results",
    "archive",
    "archives",
    "backup",
    "backups",
    "quarantine",
    "_quarantine",
    "frontend",
}
SOURCE_SUFFIXES = {".py", ".json", ".yaml", ".yml"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_sha(value: Any) -> str:
    return sha256_bytes(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def safe_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def allowed(path: Path, root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    if any(part.casefold() in EXCLUDED_PARTS for part in rel.parts):
        return False
    return path.is_file() and path.suffix.casefold() in SOURCE_SUFFIXES


def tracked(root: Path, rel: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def file_rows(root: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    unique: dict[str, Path] = {}
    for path in paths:
        if not allowed(path, root):
            continue
        rel = safe_relative(root, path)
        unique[rel] = path
    rows: list[dict[str, Any]] = []
    for rel in sorted(unique):
        path = unique[rel]
        raw = path.read_bytes()
        rows.append(
            {
                "path": rel,
                "sha256": sha256_bytes(raw),
                "size_bytes": len(raw),
                "git_tracked": tracked(root, rel),
            }
        )
    return rows


def glob_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    rows: list[Path] = []
    for pattern in patterns:
        rows.extend(root.glob(pattern))
    return rows


def scan_named(root: Path, token: str, roots: Iterable[str]) -> list[Path]:
    rows: list[Path] = []
    needle = token.casefold()
    for relative in roots:
        base = root / relative
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not allowed(path, root):
                continue
            stem = path.stem.casefold().replace("-", "_")
            if needle in stem:
                rows.append(path)
    return rows


def strategy_paths(root: Path) -> list[Path]:
    rows: list[Path] = []
    for relative in ("backend/strategy25", "backend/strategies", "backend/strategy"):
        base = root / relative
        if base.is_dir():
            rows.extend(path for path in base.rglob("*") if allowed(path, root))
    if rows:
        return rows
    manifest_path = root / "backend/recovery/active_backend_source_manifest_v1.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in manifest.get("files", []):
                rel = str(item.get("path") or "")
                compact = rel.casefold()
                if rel.endswith(".py") and "strategy" in compact:
                    candidate = root / rel
                    if allowed(candidate, root):
                        rows.append(candidate)
        except Exception:
            pass
    return rows


def skill_paths(root: Path) -> list[Path]:
    rows: list[Path] = []
    for relative in ("backend/contracts", "backend/engine", "backend/skills"):
        base = root / relative
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not allowed(path, root):
                continue
            name = path.name.casefold()
            if "skill" not in name:
                continue
            if any(token in name for token in ("registry", "resolver", "event", "profile", "permission")):
                rows.append(path)
    return rows


def preferred_or_scan(
    root: Path,
    preferred: Iterable[str],
    token: str,
    scan_roots: Iterable[str] = ("canonical", "backend"),
) -> tuple[list[Path], str]:
    preferred_paths = [root / item for item in preferred if (root / item).is_file()]
    if preferred_paths:
        return preferred_paths, "PREFERRED_CANONICAL_OR_ACTIVE_PATHS"
    return scan_named(root, token, scan_roots), "SANITIZED_FIRST_PARTY_FAMILY_BUNDLE"


def module_sources(root: Path) -> dict[str, tuple[list[Path], str]]:
    modules: dict[str, tuple[list[Path], str]] = {}
    modules["STRATEGY_SIGNAL"] = (strategy_paths(root), "STRATEGY_SOURCE_FAMILY_BUNDLE")
    modules["TRADE_METHOD"] = (
        glob_files(root, ["backend/trade_methods/**/*.py", "backend/trade_methods/*.py"]),
        "TRADE_METHOD_PACKAGE_BUNDLE",
    )
    modules["SKILL_PROFILE"] = (skill_paths(root), "SKILL_CONTRACT_RESOLVER_BUNDLE")
    for module_id, filename in (
        ("LBOT", "lbot.py"),
        ("MBOT", "mbot.py"),
        ("OBOT", "obot.py"),
        ("SBOT", "sbot.py"),
    ):
        modules[module_id] = preferred_or_scan(
            root,
            [f"backend/bots/{filename}", f"canonical/bots/{filename}"],
            module_id.casefold(),
            ("backend/bots", "canonical/bots", "backend/engine"),
        )
    modules["ZBOT"] = preferred_or_scan(
        root,
        ["canonical/zbot.py", "backend/advisors/zbot.py", "backend/zbot.py"],
        "zbot",
    )
    lico_paths, lico_policy = preferred_or_scan(
        root,
        ["canonical/lico.py", "canonical/lico_calibration.py", "backend/lico.py"],
        "lico",
    )
    lico_paths.extend(
        path
        for path in glob_files(root, ["config/q4r3_lico*.json", "backend/config/*lico*.json"])
        if allowed(path, root)
    )
    modules["LICO"] = (lico_paths, lico_policy)
    modules["ZICO"] = preferred_or_scan(
        root,
        ["canonical/zico/control.py", "canonical/zico.py", "backend/zico.py"],
        "zico",
    )
    zlice_paths, zlice_policy = preferred_or_scan(
        root,
        ["canonical/zlice/ledger.py", "canonical/zlice/projection.py", "backend/zlice.py"],
        "zlice",
    )
    canonical_zlice = root / "canonical/zlice"
    if canonical_zlice.is_dir():
        zlice_paths.extend(path for path in canonical_zlice.rglob("*") if allowed(path, root))
    modules["ZLICE"] = (zlice_paths, zlice_policy)
    portfolio = root / "backend/research/strategy11_portfolio_governor_v1.py"
    modules["PORTFOLIO_GOVERNOR"] = (
        [portfolio] if portfolio.is_file() else scan_named(root, "portfolio_governor", ("backend/research", "backend")),
        "PORTFOLIO_GOVERNOR_SOURCE",
    )
    return modules


def inventory(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    bindings: dict[str, Any] = {}
    discovered = module_sources(root)
    for module_id in MODULE_IDS:
        paths, policy = discovered.get(module_id, ([], "MISSING_SPEC"))
        rows = file_rows(root, paths)
        if not rows:
            errors.append(f"MISSING_SOURCE_BUNDLE:{module_id}")
        tracked_count = sum(1 for row in rows if row["git_tracked"])
        bundle_payload = [{"path": row["path"], "sha256": row["sha256"]} for row in rows]
        bindings[module_id] = {
            "module_id": module_id,
            "selection_policy": policy,
            "file_count": len(rows),
            "git_tracked_count": tracked_count,
            "untracked_count": len(rows) - tracked_count,
            "total_size_bytes": sum(int(row["size_bytes"]) for row in rows),
            "source_bundle_sha256": stable_sha(bundle_payload) if rows else None,
            "files": rows,
        }
    duplicate_bundle_hashes: dict[str, list[str]] = {}
    for module_id, row in bindings.items():
        digest = row.get("source_bundle_sha256")
        if digest:
            duplicate_bundle_hashes.setdefault(str(digest), []).append(module_id)
    duplicate_bundle_hashes = {
        digest: ids for digest, ids in duplicate_bundle_hashes.items() if len(ids) > 1
    }
    if duplicate_bundle_hashes:
        errors.append("DUPLICATE_MODULE_SOURCE_BUNDLE_HASH")
    state = (
        "PASS_LIVE_COMPOSITE_SOURCE_INVENTORY"
        if not errors and len(bindings) == len(MODULE_IDS)
        else "HOLD_LIVE_COMPOSITE_SOURCE_INVENTORY"
    )
    result: dict[str, Any] = {
        "schema_version": "zel.composite.source_inventory.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "root": str(root),
        "state": state,
        "module_count": len(bindings),
        "bound_module_count": sum(1 for row in bindings.values() if row["file_count"] > 0),
        "git_tracked_file_count": sum(row["git_tracked_count"] for row in bindings.values()),
        "untracked_file_count": sum(row["untracked_count"] for row in bindings.values()),
        "source_git_pin_required_before_activation": any(
            row["untracked_count"] > 0 for row in bindings.values()
        ),
        "duplicate_bundle_hashes": duplicate_bundle_hashes,
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


def placeholder(value: str) -> bool:
    return len(value) != 64 or len(set(value.casefold())) <= 1


def apply_registry(
    inventory_row: Mapping[str, Any], registry: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    bindings = inventory_row.get("bindings") if isinstance(inventory_row.get("bindings"), dict) else {}
    modules = registry.get("modules") if isinstance(registry.get("modules"), list) else []
    rebound_modules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in modules:
        row = dict(raw)
        module_id = str(row.get("module_id") or "")
        seen.add(module_id)
        binding = bindings.get(module_id)
        if not isinstance(binding, dict) or not binding.get("source_bundle_sha256"):
            errors.append(f"BINDING_MISSING:{module_id}")
            rebound_modules.append(row)
            continue
        digest = str(binding["source_bundle_sha256"])
        if placeholder(digest):
            errors.append(f"BINDING_PLACEHOLDER:{module_id}")
        row["source_sha256"] = digest
        row["source_binding"] = {
            "mode": "LIVE_RUNTIME_SOURCE_BUNDLE_SHA256",
            "selection_policy": binding.get("selection_policy"),
            "source_file_count": binding.get("file_count"),
            "git_tracked_count": binding.get("git_tracked_count"),
            "untracked_count": binding.get("untracked_count"),
            "source_paths": [item["path"] for item in binding.get("files", [])],
            "inventory_receipt_sha256": inventory_row.get("receipt_sha256"),
        }
        rebound_modules.append(row)
    missing_registry_ids = sorted(set(MODULE_IDS) - seen)
    extra_registry_ids = sorted(seen - set(MODULE_IDS))
    if missing_registry_ids:
        errors.append("REGISTRY_MODULES_MISSING:" + ",".join(missing_registry_ids))
    if extra_registry_ids:
        errors.append("REGISTRY_MODULES_EXTRA:" + ",".join(extra_registry_ids))
    rebound = dict(registry)
    rebound["generated_from"] = "LIVE_RUNTIME_SOURCE_INVENTORY_V1"
    rebound["modules"] = rebound_modules
    safety = dict(rebound.get("safety") or {})
    safety.update(
        {
            "action": "hold",
            "activation_enabled": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "runtime_discovery_performed": True,
            "source_sha_placeholders_require_rebinding_before_activation": False,
            "source_git_pin_required_before_activation": bool(
                inventory_row.get("source_git_pin_required_before_activation")
            ),
        }
    )
    rebound["safety"] = safety
    source_rebinding_required = any(
        placeholder(str(row.get("source_sha256") or "")) for row in rebound_modules
    )
    if source_rebinding_required:
        errors.append("SOURCE_REBINDING_INCOMPLETE")
    state = (
        "PASS_COMPOSITE_SOURCE_SHA_REBOUND_HOLD_ACTIVATION"
        if not errors and inventory_row.get("state") == "PASS_LIVE_COMPOSITE_SOURCE_INVENTORY"
        else "HOLD_COMPOSITE_SOURCE_SHA_REBINDING"
    )
    receipt: dict[str, Any] = {
        "schema_version": "zel.composite.source_rebinding.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "module_count": len(rebound_modules),
        "rebound_module_count": sum(
            1 for row in rebound_modules if not placeholder(str(row.get("source_sha256") or ""))
        ),
        "source_rebinding_required_before_activation": source_rebinding_required,
        "source_git_pin_required_before_activation": bool(
            inventory_row.get("source_git_pin_required_before_activation")
        ),
        "inventory_receipt_sha256": inventory_row.get("receipt_sha256"),
        "registry_sha256": stable_sha(rebound),
        "errors": sorted(set(errors)),
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "activation_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return rebound, receipt


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        examples = {
            "backend/strategies/s.py": "def signal(): return 1\n",
            "backend/trade_methods/m.py": "def method(): return 1\n",
            "backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json": "{}\n",
            "backend/engine/skill_resolver_v2_candidate.py": "def resolve(): return 1\n",
            "backend/bots/lbot.py": "LBOT=1\n",
            "backend/bots/mbot.py": "MBOT=1\n",
            "backend/bots/obot.py": "OBOT=1\n",
            "backend/bots/sbot.py": "SBOT=1\n",
            "backend/zbot.py": "ZBOT=1\n",
            "backend/lico.py": "LICO=1\n",
            "backend/zico.py": "ZICO=1\n",
            "backend/zlice.py": "ZLICE=1\n",
            "backend/research/strategy11_portfolio_governor_v1.py": "GOV=1\n",
        }
        for rel, text in examples.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        row = inventory(root)
        assert row["state"] == "PASS_LIVE_COMPOSITE_SOURCE_INVENTORY", row
        assert row["bound_module_count"] == 12, row
        registry = {
            "modules": [{"module_id": module_id, "source_sha256": module_id[0].lower() * 64} for module_id in MODULE_IDS],
            "safety": {},
        }
        rebound, receipt = apply_registry(row, registry)
        assert receipt["state"] == "PASS_COMPOSITE_SOURCE_SHA_REBOUND_HOLD_ACTIVATION", receipt
        assert receipt["rebound_module_count"] == 12, receipt
        assert all(not placeholder(item["source_sha256"]) for item in rebound["modules"])
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--inventory-out", type=Path)
    parser.add_argument("--inventory-stdout", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--out-registry", type=Path)
    parser.add_argument("--out-receipt", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.apply:
        required = [args.inventory, args.registry, args.out_registry, args.out_receipt]
        if any(value is None for value in required):
            parser.error("apply requires inventory, registry, out-registry and out-receipt")
        inventory_row = json.loads(args.inventory.read_text(encoding="utf-8"))
        registry = json.loads(args.registry.read_text(encoding="utf-8"))
        rebound, receipt = apply_registry(inventory_row, registry)
        args.out_registry.parent.mkdir(parents=True, exist_ok=True)
        args.out_receipt.parent.mkdir(parents=True, exist_ok=True)
        args.out_registry.write_text(json.dumps(rebound, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.out_receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"state": receipt["state"], "rebound": receipt["rebound_module_count"], "git_pin_required": receipt["source_git_pin_required_before_activation"], "errors": receipt["errors"]}, sort_keys=True))
        return 0 if receipt["state"].startswith("PASS") else 1
    if args.root is None:
        parser.error("root is required")
    row = inventory(args.root.resolve())
    if args.inventory_out:
        args.inventory_out.parent.mkdir(parents=True, exist_ok=True)
        args.inventory_out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.inventory_stdout or not args.inventory_out:
        print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
