#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

ESCROW = Path(os.environ.get("G0_ESCROW_ROOT", "/home/z/.zel-g0-source-escrow")).resolve()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stable_sha(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def decode_pin() -> dict[str, Any]:
    return json.loads(base64.b64decode(os.environ["EXPECTED_PIN_B64"]).decode("utf-8"))


def run(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, cwd=str(ESCROW), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return p.returncode, p.stdout.strip()


def canonical_path(source_path: str) -> Path:
    if source_path.startswith("external:"):
        return ESCROW / "sources_external" / source_path[len("external:"):].lstrip("/")
    return ESCROW / "sources" / source_path


def main() -> int:
    pin = decode_pin()
    governor_rel = "backend/research/strategy11_portfolio_governor_v1.py"
    governor_dst = ESCROW / "sources" / governor_rel
    governor_candidate = ESCROW / "recovery_candidates" / governor_rel

    if not (ESCROW / ".git").exists():
        raise SystemExit("escrow git repository missing")

    governor_promoted = False
    if not governor_dst.is_file() and governor_candidate.is_file():
        governor_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(governor_candidate, governor_dst)
        governor_dst.chmod(0o600)
        governor_promoted = True

    modules: list[dict[str, Any]] = []
    missing: list[str] = []
    old_pin_match_count = 0
    total_paths: set[str] = set()

    for raw_module in pin.get("modules", []):
        module = dict(raw_module)
        module_id = str(module.get("module_id") or "")
        source_paths = sorted(str(x) for x in module.get("source_paths", []))
        payload: list[dict[str, str]] = []
        file_rows: list[dict[str, Any]] = []
        module_missing: list[str] = []
        for source_path in source_paths:
            total_paths.add(source_path)
            path = canonical_path(source_path)
            if not path.is_file():
                missing.append(source_path)
                module_missing.append(source_path)
                file_rows.append({"source_path": source_path, "exists": False, "sha256": None})
                continue
            digest = sha256_bytes(path.read_bytes())
            payload.append({"path": source_path, "sha256": digest})
            file_rows.append({"source_path": source_path, "exists": True, "sha256": digest})
        computed = stable_sha(payload) if source_paths and not module_missing and len(payload) == len(source_paths) else None
        expected = str(module.get("source_bundle_sha256") or "") or None
        old_match = bool(computed and expected and computed == expected)
        if old_match:
            old_pin_match_count += 1
        modules.append({
            "module_id": module_id,
            "selection_policy": module.get("selection_policy"),
            "source_paths": source_paths,
            "source_bundle_sha256": computed,
            "previous_source_bundle_sha256": expected,
            "previous_pin_match": old_match,
            "missing_source_paths": module_missing,
            "files": file_rows,
        })

    missing = sorted(set(missing))
    candidate = {
        "schema_version": "zel.g0.local_private_canonical_source_pin.v1",
        "canonical_storage": str(ESCROW),
        "module_count": len(modules),
        "source_path_count": len(total_paths),
        "modules": [
            {
                "module_id": m["module_id"],
                "selection_policy": m["selection_policy"],
                "source_paths": m["source_paths"],
                "source_bundle_sha256": m["source_bundle_sha256"],
            }
            for m in modules
        ],
        "runtime_mutated": False,
        "active_runtime_tree_mutated": False,
        "public_repository_publish_authority": False,
        "destructive_cleanup_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    candidate["source_pin_sha256"] = stable_sha(candidate)
    candidate_path = ESCROW / "canonical_source_pin_candidate.json"
    candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
    candidate_path.chmod(0o600)

    run(["git", "add", "-A"])
    rc, status = run(["git", "status", "--porcelain"])
    if rc != 0:
        raise SystemExit(status)
    committed = False
    if status:
        rc, out = run(["git", "commit", "-m", "G0 local canonical source set " + candidate["source_pin_sha256"][:12]])
        if rc != 0:
            raise SystemExit(out)
        committed = True
    rc, head = run(["git", "rev-parse", "HEAD"])
    if rc != 0:
        raise SystemExit(head)

    state = "PASS_LOCAL_CANONICAL_SOURCE_SET" if not missing and len(modules) == 12 else "HOLD_LOCAL_CANONICAL_SOURCE_SET"
    receipt = {
        "schema_version": "zel.g0.local_canonicalization_receipt.v1",
        "state": state,
        "escrow_root": str(ESCROW),
        "source_path_count": len(total_paths),
        "canonical_source_present_count": len(total_paths) - len(missing),
        "canonical_source_missing_count": len(missing),
        "canonical_source_missing_paths": missing,
        "module_count": len(modules),
        "previous_pin_match_count": old_pin_match_count,
        "previous_pin_mismatch_count": len(modules) - old_pin_match_count,
        "governor_candidate_promoted_inside_escrow": governor_promoted,
        "canonical_source_pin_sha256": candidate["source_pin_sha256"],
        "canonical_modules": modules,
        "escrow_git_commit_created": committed,
        "escrow_git_head": head,
        "runtime_mutated": False,
        "active_runtime_tree_mutated": False,
        "service_state_mutated": False,
        "public_repository_publish_authority": False,
        "destructive_cleanup_authority": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if state == "PASS_LOCAL_CANONICAL_SOURCE_SET" else 2


if __name__ == "__main__":
    raise SystemExit(main())
