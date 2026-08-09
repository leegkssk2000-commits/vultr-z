#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("G0_ROOT", "/home/z/z")).resolve()
ESCROW = Path(os.environ.get("G0_ESCROW_ROOT", "/home/z/.zel-g0-source-escrow")).resolve()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stable_sha(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def decode_b64_json(name: str) -> Any:
    return json.loads(base64.b64decode(os.environ[name]).decode("utf-8"))


def decode_b64_bytes(name: str) -> bytes | None:
    raw = os.environ.get(name, "")
    return base64.b64decode(raw) if raw else None


def run(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(args, cwd=str(cwd) if cwd else None, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return p.returncode, p.stdout.strip()


def chmod_private_tree(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        try:
            path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            pass


def source_paths(pin: dict[str, Any]) -> list[str]:
    found: set[str] = set()
    for module in pin.get("modules", []):
        for item in module.get("source_paths", []):
            found.add(str(item))
    return sorted(found)


def source_file(source_path: str) -> Path:
    if source_path.startswith("external:"):
        return Path(source_path[len("external:"):])
    return ROOT / source_path


def escrow_rel(source_path: str) -> Path:
    if source_path.startswith("external:"):
        raw = source_path[len("external:"):].lstrip("/")
        return Path("sources_external") / raw
    return Path("sources") / source_path


def main() -> int:
    pin = decode_b64_json("EXPECTED_PIN_B64")
    governor_candidate = decode_b64_bytes("GOVERNOR_CANDIDATE_B64")
    governor_rel = "backend/research/strategy11_portfolio_governor_v1.py"

    if ROOT == ESCROW or ESCROW.is_relative_to(ROOT):
        raise SystemExit("escrow must remain outside active runtime root")

    ESCROW.mkdir(parents=True, exist_ok=True)
    ESCROW.chmod(0o700)

    copied: list[dict[str, Any]] = []
    missing: list[str] = []
    for item in source_paths(pin):
        src = source_file(item)
        if not src.is_file():
            missing.append(item)
            continue
        raw = src.read_bytes()
        dst = ESCROW / escrow_rel(item)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
        copied.append({"source_path": item, "sha256": sha256_bytes(raw), "size_bytes": len(raw)})

    candidate_written = False
    candidate_sha = None
    if governor_rel in missing and governor_candidate:
        candidate = ESCROW / "recovery_candidates" / governor_rel
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(governor_candidate)
        candidate_sha = sha256_bytes(governor_candidate)
        candidate_written = True

    fingerprint = stable_sha({"copied": copied, "missing": missing, "governor_candidate_sha256": candidate_sha})
    manifest = {
        "schema_version": "zel.g0.local_private_source_escrow.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_root": str(ROOT),
        "escrow_root": str(ESCROW),
        "source_path_count": len(source_paths(pin)),
        "copied_source_count": len(copied),
        "missing_source_count": len(missing),
        "missing_source_paths": missing,
        "governor_recovery_candidate_written": candidate_written,
        "governor_recovery_candidate_sha256": candidate_sha,
        "source_fingerprint_sha256": fingerprint,
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

    manifest_path = ESCROW / "manifest.json"
    prior_fingerprint = None
    if manifest_path.is_file():
        try:
            prior_fingerprint = json.loads(manifest_path.read_text()).get("source_fingerprint_sha256")
        except Exception:
            prior_fingerprint = None
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    if not (ESCROW / ".git").exists():
        rc, out = run(["git", "init"], ESCROW)
        if rc != 0:
            raise SystemExit(out)
        run(["git", "branch", "-M", "escrow"], ESCROW)
        run(["git", "config", "user.name", "ZEL G0 Escrow"], ESCROW)
        run(["git", "config", "user.email", "g0-escrow@localhost"], ESCROW)

    chmod_private_tree(ESCROW)
    run(["git", "add", "-A"], ESCROW)
    rc, status = run(["git", "status", "--porcelain"], ESCROW)
    if rc != 0:
        raise SystemExit(status)
    committed = False
    commit_sha = None
    if status:
        msg = "G0 exact runtime source escrow " + fingerprint[:12]
        rc, out = run(["git", "commit", "-m", msg], ESCROW)
        if rc != 0:
            raise SystemExit(out)
        committed = True
    rc, head = run(["git", "rev-parse", "HEAD"], ESCROW)
    if rc == 0:
        commit_sha = head

    state = "PASS_LOCAL_PRIVATE_ESCROW"
    if missing:
        state = "PASS_LOCAL_ESCROW_WITH_RECOVERY_CANDIDATE" if candidate_written and missing == [governor_rel] else "HOLD_LOCAL_ESCROW_INCOMPLETE"

    receipt = {
        **manifest,
        "state": state,
        "prior_same_fingerprint": prior_fingerprint == fingerprint,
        "escrow_git_commit_created": committed,
        "escrow_git_head": commit_sha,
        "receipt_sha256": stable_sha({**manifest, "state": state, "escrow_git_head": commit_sha}),
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if state.startswith("PASS_LOCAL_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
