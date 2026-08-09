#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stable_sha(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def decode_env_json(name: str) -> Any:
    return json.loads(base64.b64decode(os.environ[name].encode("ascii")).decode("utf-8"))


def git(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(ROOT), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=15)
        return p.returncode, p.stdout
    except Exception:
        return 99, ""


def path_state(rel: str) -> dict[str, Any]:
    path = ROOT / rel
    exists = path.is_file()
    rc, _ = git(["ls-files", "--error-unmatch", "--", rel])
    tracked = rc == 0
    rc_head, _ = git(["cat-file", "-e", f"HEAD:{rel}"])
    in_head = rc_head == 0
    rc_status, status_out = git(["status", "--porcelain", "--untracked-files=all", "--", rel])
    status_code = None
    if rc_status == 0 and status_out.strip():
        first = status_out.splitlines()[0]
        status_code = first[:2]
    if not exists:
        classification = "MISSING_RUNTIME"
    elif not tracked:
        classification = "UNTRACKED_RUNTIME_SOURCE"
    elif status_code:
        classification = "TRACKED_DIRTY_RUNTIME_SOURCE"
    elif not in_head:
        classification = "TRACKED_NOT_IN_HEAD"
    else:
        classification = "TRACKED_CLEAN_IN_HEAD"
    return {
        "path": rel,
        "exists": exists,
        "git_tracked": tracked,
        "present_in_runtime_head": in_head,
        "git_status_code": status_code,
        "classification": classification,
    }


def main() -> int:
    pin = decode_env_json("EXPECTED_PIN_B64")
    inv = decode_env_json("LEGACY25_B64")
    source_paths: set[str] = set()
    path_modules: dict[str, list[str]] = {}
    for module in pin.get("modules", []):
        mid = str(module.get("module_id") or "")
        for raw in module.get("source_paths", []):
            rel = str(raw)
            if rel.startswith("external:"):
                continue
            source_paths.add(rel)
            path_modules.setdefault(rel, []).append(mid)
    for name in inv.get("historical_implementation_inventory_25", []):
        source_paths.add(f"backend/strategies/{name}.py")
        path_modules.setdefault(f"backend/strategies/{name}.py", []).append("LEGACY25")

    rows = []
    for rel in sorted(source_paths):
        row = path_state(rel)
        row["modules"] = sorted(set(path_modules.get(rel, [])))
        rows.append(row)

    counts: dict[str, int] = {}
    for row in rows:
        key = str(row["classification"])
        counts[key] = counts.get(key, 0) + 1
    nonpersistent = [row for row in rows if row["classification"] != "TRACKED_CLEAN_IN_HEAD"]
    result: dict[str, Any] = {
        "schema_version": "zel.g0.runtime_git_persistence.v1",
        "state": "PASS_G0_RUNTIME_GIT_PERSISTENCE" if not nonpersistent else "HOLD_G0_RUNTIME_GIT_PERSISTENCE",
        "root": str(ROOT),
        "runtime_git_head": git(["rev-parse", "HEAD"])[1].strip() or None,
        "runtime_git_branch": git(["rev-parse", "--abbrev-ref", "HEAD"])[1].strip() or None,
        "source_path_count": len(rows),
        "classification_counts": counts,
        "nonpersistent_source_count": len(nonpersistent),
        "nonpersistent_sources": nonpersistent,
        "runtime_mutated": False,
        "destructive_cleanup_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha(result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
