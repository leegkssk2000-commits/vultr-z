from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import secrets
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_HOLDOUT_RUNTIME_PROVISION_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def path_sha(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "zel.holdout.runtime_config.v1":
        raise ValueError("CONFIG_SCHEMA")
    return value


def outside_repository(path: Path, repository_root: Path) -> bool:
    target = path.resolve()
    repo = repository_root.resolve()
    return target != repo and repo not in target.parents


def ensure_group(name: str) -> tuple[int, bool]:
    try:
        return grp.getgrnam(name).gr_gid, False
    except KeyError:
        subprocess.run(["groupadd", "--system", name], check=True)
        return grp.getgrnam(name).gr_gid, True


def secure_existing_empty_dir(path: Path, uid: int, gid: int, mode: int) -> bool:
    if path.is_symlink():
        raise RuntimeError(f"SYMLINK_FORBIDDEN:{path}")
    created = False
    if path.exists():
        if not path.is_dir():
            raise RuntimeError(f"DIRECTORY_REQUIRED:{path}")
        if any(path.iterdir()):
            raise RuntimeError(f"NONEMPTY_ROOT_REQUIRES_MANUAL_REVIEW:{path}")
    else:
        path.mkdir(parents=True, mode=mode)
        created = True
    os.chown(path, uid, gid)
    os.chmod(path, mode)
    return created


def ensure_hmac_key(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chown(path.parent, 0, 0)
    os.chmod(path.parent, 0o700)
    if path.is_symlink():
        raise RuntimeError("HMAC_KEY_SYMLINK_FORBIDDEN")
    if path.exists():
        row = path.stat()
        if not stat.S_ISREG(row.st_mode):
            raise RuntimeError("HMAC_KEY_NOT_REGULAR")
        if row.st_uid != 0 or row.st_gid != 0 or stat.S_IMODE(row.st_mode) != 0o600:
            raise RuntimeError("HMAC_KEY_PERMISSION_MISMATCH")
        if row.st_size < 64:
            raise RuntimeError("HMAC_KEY_TOO_SHORT")
        return False
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (secrets.token_hex(32) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chown(path, 0, 0)
    os.chmod(path, 0o600)
    return True


def provision(config: dict[str, Any]) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise PermissionError("ROOT_REQUIRED")
    repo = Path(str(config["repository_root"]))
    roots = {
        "W2_ROOT": Path(str(config["w2_root"])),
        "W3_ROOT": Path(str(config["w3_root"])),
        "FINAL_ROOT": Path(str(config["final_root"])),
    }
    seal_root = Path(str(config["seal_root"]))
    key_file = Path(str(config["hmac_key_file"]))
    group_name = str(config["evaluator_group"])
    all_paths = [repo, *roots.values(), seal_root, key_file]
    if not all(path.is_absolute() for path in all_paths):
        raise ValueError("ABSOLUTE_PATHS_REQUIRED")
    if not repo.is_dir():
        raise RuntimeError("REPOSITORY_ROOT_MISSING")
    resolved_roots = [path.resolve() for path in roots.values()]
    if len(set(resolved_roots)) != 3:
        raise ValueError("ZONE_ROOTS_NOT_DISTINCT")
    if not all(outside_repository(path, repo) for path in [*roots.values(), seal_root, key_file]):
        raise ValueError("EXTERNAL_PATH_REQUIRED")

    gid, group_created = ensure_group(group_name)
    created: list[str] = []
    parent = Path(os.path.commonpath([str(path.parent) for path in roots.values()]))
    parent.mkdir(parents=True, exist_ok=True)
    os.chown(parent, 0, gid)
    os.chmod(parent, 0o710)
    for name, path in roots.items():
        if secure_existing_empty_dir(path, 0, gid, 0o750):
            created.append(name)
    if secure_existing_empty_dir(seal_root, 0, 0, 0o700):
        created.append("SEAL_ROOT")
    key_created = ensure_hmac_key(key_file)

    return {
        "schema_version": "zel.holdout.runtime_provision.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_HOLDOUT_RUNTIME_PROVISIONED",
        "config_sha256": canonical_sha(config),
        "config_items_set": [
            "REPOSITORY_ROOT", "W2_ROOT", "W3_ROOT", "FINAL_ROOT",
            "SEAL_ROOT", "EVALUATOR_GROUP", "HOLDOUT_HMAC_KEY"
        ],
        "repository_root_sha256": path_sha(repo),
        "zone_root_sha256": {name: path_sha(path) for name, path in roots.items()},
        "seal_root_sha256": path_sha(seal_root),
        "evaluator_group_sha256": hashlib.sha256(group_name.encode()).hexdigest(),
        "hmac_key_file_sha256": path_sha(key_file),
        "group_created": group_created,
        "created_roots": sorted(created),
        "hmac_key_created": key_created,
        "hmac_value_disclosed": False,
        "raw_holdout_published": False,
        "vault_configuration_mutated": True,
        "trading_runtime_mutated": False,
        "canonical_strategy_mutated": False,
        "formal_ledger_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    config = {
        "schema_version": "zel.holdout.runtime_config.v1",
        "repository_root": "/opt/zel",
        "w2_root": "/var/lib/zel-holdout/w2_forward",
        "w3_root": "/var/lib/zel-holdout/w3_durability",
        "final_root": "/var/lib/zel-holdout/final_holdout",
        "seal_root": "/var/lib/zel-holdout/seals",
        "evaluator_group": "zel-evaluator",
        "hmac_key_file": "/etc/zel/holdout_hmac.key",
    }
    assert canonical_sha(config)
    repo = Path("/opt/zel")
    assert outside_repository(Path("/var/lib/zel-holdout/w2_forward"), repo)
    assert not outside_repository(Path("/opt/zel/holdout"), repo)
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.config or not args.out:
        parser.error("config and out are required")
    try:
        receipt = provision(load_config(args.config))
        code = 0
    except Exception as exc:
        receipt = {
            "schema_version": "zel.holdout.runtime_provision.receipt.v1",
            "version": VERSION,
            "generated_at": now_iso(),
            "state": "HOLD_HOLDOUT_RUNTIME_PROVISION",
            "error": f"{type(exc).__name__}:{exc}",
            "hmac_value_disclosed": False,
            "raw_holdout_published": False,
            "trading_runtime_mutated": False,
            "canonical_strategy_mutated": False,
            "formal_ledger_mutated": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
        code = 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"]}, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
