from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import pwd
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_HOLDOUT_VAULT_AUDIT_V1"
ZONES = ("W2_FORWARD", "W3_DURABILITY", "FINAL_HOLDOUT")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def path_sha(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()


def outside_repository(path: Path, repository_root: Path) -> bool:
    target = path.resolve()
    repo = repository_root.resolve()
    return target != repo and repo not in target.parents


def mode_octal(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


def group_membership(user: str) -> set[int]:
    row = pwd.getpwnam(user)
    groups = {row.pw_gid}
    groups.update(g.gr_gid for g in grp.getgrall() if user in g.gr_mem)
    return groups


def audit_zone(
    zone: str,
    root: Path,
    repository_root: Path,
    evaluator_gid: int,
    max_entries: int,
) -> dict[str, Any]:
    errors: list[str] = []
    checked = 0
    file_count = 0
    directory_count = 0
    total_bytes = 0
    if not root.is_dir():
        errors.append("ROOT_MISSING")
        return {
            "zone": zone,
            "root_sha256": path_sha(root),
            "exists": False,
            "errors": errors,
            "checked_entries": 0,
        }
    if not outside_repository(root, repository_root):
        errors.append("ROOT_INSIDE_REPOSITORY")
    root_stat = root.stat()
    if root_stat.st_gid != evaluator_gid:
        errors.append("ROOT_EVALUATOR_GROUP_MISMATCH")
    if stat.S_IMODE(root_stat.st_mode) & 0o007:
        errors.append("ROOT_OTHER_PERMISSIONS_PRESENT")
    for path in [root, *root.rglob("*")]:
        checked += 1
        if checked > max_entries:
            errors.append("ENTRY_SCAN_LIMIT_EXCEEDED")
            break
        row = path.stat()
        if row.st_gid != evaluator_gid:
            errors.append("ENTRY_EVALUATOR_GROUP_MISMATCH")
        if stat.S_IMODE(row.st_mode) & 0o007:
            errors.append("ENTRY_OTHER_PERMISSIONS_PRESENT")
        if path.is_file():
            file_count += 1
            total_bytes += row.st_size
        elif path.is_dir():
            directory_count += 1
    return {
        "zone": zone,
        "root_sha256": path_sha(root),
        "exists": True,
        "identity": {
            "uid": root_stat.st_uid,
            "user": pwd.getpwuid(root_stat.st_uid).pw_name,
            "gid": root_stat.st_gid,
            "group": grp.getgrgid(root_stat.st_gid).gr_name,
            "mode": mode_octal(root),
        },
        "checked_entries": min(checked, max_entries),
        "file_count": file_count,
        "directory_count": directory_count,
        "total_bytes": total_bytes,
        "errors": sorted(set(errors)),
    }


def audit(
    repository_root: Path,
    zone_roots: dict[str, Path],
    seal_root: Path,
    evaluator_group: str,
    proposer_users: list[str],
    hmac_configured: bool,
    max_entries: int,
) -> dict[str, Any]:
    global_errors: list[str] = []
    try:
        evaluator_gid = grp.getgrnam(evaluator_group).gr_gid
    except KeyError:
        evaluator_gid = -1
        global_errors.append("EVALUATOR_GROUP_MISSING")
    proposer_checks: list[dict[str, Any]] = []
    if evaluator_gid >= 0:
        for user in proposer_users:
            try:
                memberships = group_membership(user)
                in_group = evaluator_gid in memberships
                proposer_checks.append({"user_sha256": hashlib.sha256(user.encode()).hexdigest(), "in_evaluator_group": in_group})
                if in_group:
                    global_errors.append("PROPOSER_IN_EVALUATOR_GROUP")
            except KeyError:
                proposer_checks.append({"user_sha256": hashlib.sha256(user.encode()).hexdigest(), "missing": True})
                global_errors.append("PROPOSER_USER_MISSING")
    if not hmac_configured:
        global_errors.append("HMAC_KEY_NOT_CONFIGURED")
    if not seal_root.is_dir():
        global_errors.append("SEAL_ROOT_MISSING")
        seal_identity = None
    else:
        seal_stat = seal_root.stat()
        seal_identity = {
            "root_sha256": path_sha(seal_root),
            "uid": seal_stat.st_uid,
            "user": pwd.getpwuid(seal_stat.st_uid).pw_name,
            "gid": seal_stat.st_gid,
            "group": grp.getgrgid(seal_stat.st_gid).gr_name,
            "mode": mode_octal(seal_root),
        }
        if not outside_repository(seal_root, repository_root):
            global_errors.append("SEAL_ROOT_INSIDE_REPOSITORY")
        if stat.S_IMODE(seal_stat.st_mode) & 0o077:
            global_errors.append("SEAL_ROOT_NOT_PRIVATE")
    zone_results = [
        audit_zone(zone, zone_roots[zone], repository_root, evaluator_gid, max_entries)
        for zone in ZONES
    ] if evaluator_gid >= 0 else [
        {"zone": zone, "root_sha256": path_sha(zone_roots[zone]), "exists": zone_roots[zone].is_dir(), "errors": ["EVALUATOR_GROUP_UNRESOLVED"]}
        for zone in ZONES
    ]
    zone_errors = sorted({error for row in zone_results for error in row.get("errors", [])})
    all_errors = sorted(set(global_errors + zone_errors))
    passed = not all_errors
    return {
        "schema_version": "zel.holdout_vault.audit_receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_HOLDOUT_VAULT_AUDIT_READY_TO_SEAL" if passed else "HOLD_HOLDOUT_VAULT_AUDIT",
        "repository_root_disclosed": False,
        "repository_root_sha256": path_sha(repository_root),
        "evaluator_group_sha256": hashlib.sha256(evaluator_group.encode()).hexdigest(),
        "hmac_configured": hmac_configured,
        "proposer_checks": proposer_checks,
        "seal_identity": seal_identity,
        "zones": zone_results,
        "errors": all_errors,
        "permissions_mutated": False,
        "manifests_written": False,
        "holdout_bytes_read": False,
        "runtime_mutated": False,
        "canonical_strategy_mutated": False,
        "formal_ledger_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        repo = root / "repo"
        vault = root / "vault"
        seals = root / "seals"
        repo.mkdir(); vault.mkdir(); seals.mkdir()
        os.chmod(seals, 0o700)
        group = grp.getgrgid(os.getgid()).gr_name
        zone_roots = {}
        for zone in ZONES:
            path = vault / zone.lower()
            path.mkdir()
            os.chmod(path, 0o750)
            file = path / "manifest_source.json"
            file.write_text('{"fixture":true}\n', encoding="utf-8")
            os.chmod(file, 0o640)
            zone_roots[zone] = path
        result = audit(repo, zone_roots, seals, group, [], True, 100)
        assert result["state"] == "PASS_HOLDOUT_VAULT_AUDIT_READY_TO_SEAL", result
        assert result["holdout_bytes_read"] is False
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--w2-root", type=Path)
    parser.add_argument("--w3-root", type=Path)
    parser.add_argument("--final-root", type=Path)
    parser.add_argument("--seal-root", type=Path)
    parser.add_argument("--evaluator-group")
    parser.add_argument("--proposer-users", default="")
    parser.add_argument("--hmac-configured", action="store_true")
    parser.add_argument("--max-entries", type=int, default=10000)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (args.repository_root, args.w2_root, args.w3_root, args.final_root, args.seal_root, args.evaluator_group, args.out)
    if not all(required):
        parser.error("repository-root, three zone roots, seal-root, evaluator-group and out are required")
    users = [item.strip() for item in args.proposer_users.split(",") if item.strip()]
    result = audit(
        args.repository_root,
        {"W2_FORWARD": args.w2_root, "W3_DURABILITY": args.w3_root, "FINAL_HOLDOUT": args.final_root},
        args.seal_root,
        args.evaluator_group,
        users,
        args.hmac_configured,
        args.max_entries,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "errors": result["errors"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
