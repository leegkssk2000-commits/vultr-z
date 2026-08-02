from __future__ import annotations

import argparse
import getpass
import grp
import hashlib
import hmac
import json
import os
import pwd
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_HOLDOUT_VAULT_V1"
ZONES = {"W2_FORWARD", "W3_DURABILITY", "FINAL_HOLDOUT"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def outside_repository(dataset_root: Path, repository_root: Path) -> bool:
    dataset = dataset_root.resolve()
    repo = repository_root.resolve()
    return dataset != repo and repo not in dataset.parents


def identity(path: Path) -> dict[str, Any]:
    s = path.stat()
    return {
        "uid": s.st_uid,
        "user": pwd.getpwuid(s.st_uid).pw_name,
        "gid": s.st_gid,
        "group": grp.getgrgid(s.st_gid).gr_name,
        "mode": oct(stat.S_IMODE(s.st_mode)),
    }


def build_manifest(dataset_root: Path, zone: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in dataset_root.rglob("*") if p.is_file()):
        rel = path.relative_to(dataset_root).as_posix()
        rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": file_sha(path)})
    return {
        "schema_version": "zel.holdout_vault.manifest.v1",
        "version": VERSION,
        "zone": zone,
        "generated_at": now_iso(),
        "dataset_root_name": dataset_root.name,
        "file_count": len(rows),
        "total_bytes": sum(row["bytes"] for row in rows),
        "files": rows,
    }


def receipt(
    zone: str,
    dataset_root: Path,
    errors: list[str],
    manifest_sha: str | None,
    signature: str | None,
    seal_written: bool,
    ident: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    passed = not errors and seal_written
    return {
        "schema_version": "zel.holdout_vault.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_HOLDOUT_VAULT_SEALED" if passed else "HOLD_HOLDOUT_VAULT",
        "zone": zone,
        "dataset_root_disclosed": False,
        "dataset_root_sha256": hashlib.sha256(str(dataset_root.resolve()).encode()).hexdigest(),
        "manifest_sha256": manifest_sha,
        "manifest_hmac_sha256": hashlib.sha256((signature or "").encode()).hexdigest() if signature else None,
        "file_count": manifest.get("file_count") if manifest else None,
        "total_bytes": manifest.get("total_bytes") if manifest else None,
        "identity": ident,
        "errors": sorted(set(errors)),
        "proposer_access_granted": False,
        "judge_dataset_access_granted": False,
        "one_shot_required": zone == "FINAL_HOLDOUT",
        "runtime_mutated": False,
        "canonical_strategy_mutated": False,
        "formal_ledger_mutated": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def seal(
    dataset_root: Path,
    repository_root: Path,
    seal_root: Path,
    zone: str,
    hmac_key: str,
    evaluator_group: str,
    proposer_users: list[str],
    apply_permissions: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    if zone not in ZONES:
        errors.append("INVALID_ZONE")
    if not dataset_root.is_dir():
        errors.append("DATASET_ROOT_MISSING")
    if not outside_repository(dataset_root, repository_root):
        errors.append("DATASET_INSIDE_REPOSITORY")
    try:
        evaluator_gid = grp.getgrnam(evaluator_group).gr_gid
    except KeyError:
        evaluator_gid = -1
        errors.append("EVALUATOR_GROUP_MISSING")
    if not hmac_key:
        errors.append("HMAC_KEY_MISSING")
    if errors:
        return receipt(zone, dataset_root, errors, None, None, False)

    if apply_permissions:
        os.chown(dataset_root, dataset_root.stat().st_uid, evaluator_gid)
        os.chmod(dataset_root, 0o750)
        for path in dataset_root.rglob("*"):
            os.chown(path, path.stat().st_uid, evaluator_gid)
            os.chmod(path, 0o640 if path.is_file() else 0o750)

    ident = identity(dataset_root)
    if ident["gid"] != evaluator_gid:
        errors.append("EVALUATOR_GROUP_NOT_BOUND")
    mode = int(ident["mode"], 8)
    if mode & stat.S_IROTH:
        errors.append("WORLD_READABLE")
    if mode & stat.S_IWOTH:
        errors.append("WORLD_WRITABLE")
    for user in proposer_users:
        try:
            member = pwd.getpwnam(user)
        except KeyError:
            errors.append(f"PROPOSER_USER_MISSING:{user}")
            continue
        supplementary = {g.gr_gid for g in grp.getgrall() if user in g.gr_mem}
        supplementary.add(member.pw_gid)
        if evaluator_gid in supplementary:
            errors.append(f"PROPOSER_IN_EVALUATOR_GROUP:{user}")

    manifest = build_manifest(dataset_root, zone)
    manifest_sha = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    signature = hmac.new(hmac_key.encode(), canonical_bytes(manifest), hashlib.sha256).hexdigest()
    seal_root.mkdir(parents=True, exist_ok=True)
    os.chmod(seal_root, 0o700)
    manifest_path = seal_root / f"{zone.lower()}_manifest.json"
    signature_path = seal_root / f"{zone.lower()}_manifest.hmac"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    signature_path.write_text(signature + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    os.chmod(signature_path, 0o600)
    return receipt(zone, dataset_root, errors, manifest_sha, signature, True, ident, manifest)


def consume_once(receipt_path: Path, marker_path: Path, token: str) -> dict[str, Any]:
    source = json.loads(receipt_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if source.get("state") != "PASS_HOLDOUT_VAULT_SEALED":
        errors.append("VAULT_NOT_SEALED")
    if source.get("zone") != "FINAL_HOLDOUT":
        errors.append("NOT_FINAL_HOLDOUT")
    if marker_path.exists():
        errors.append("FINAL_HOLDOUT_ALREADY_CONSUMED")
    if not token:
        errors.append("CONSUMPTION_TOKEN_MISSING")
    result = {
        "schema_version": "zel.holdout_vault.consume_receipt.v1",
        "generated_at": now_iso(),
        "state": "PASS_FINAL_HOLDOUT_CONSUMED_ONCE" if not errors else "HOLD_FINAL_HOLDOUT_CONSUMPTION",
        "vault_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "errors": errors,
        "detailed_feedback_allowed": False,
        "second_use_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    if not errors:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(hmac.new(token.encode(), canonical_bytes(result), hashlib.sha256).hexdigest() + "\n", encoding="utf-8")
        os.chmod(marker_path, 0o600)
    return result


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        repo = root / "repo"
        data = root / "vault" / "w2"
        seals = root / "seals"
        repo.mkdir()
        data.mkdir(parents=True)
        (data / "x.json").write_text('{"x":1}\n', encoding="utf-8")
        current_group = grp.getgrgid(os.getgid()).gr_name
        result = seal(data, repo, seals, "W2_FORWARD", "test-key", current_group, [], True)
        assert result["state"] == "PASS_HOLDOUT_VAULT_SEALED", result
        assert result["file_count"] == 1, result
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION, "user": getpass.getuser()}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    seal_cmd = sub.add_parser("seal")
    seal_cmd.add_argument("--dataset-root", type=Path, required=True)
    seal_cmd.add_argument("--repository-root", type=Path, required=True)
    seal_cmd.add_argument("--seal-root", type=Path, required=True)
    seal_cmd.add_argument("--zone", choices=sorted(ZONES), required=True)
    seal_cmd.add_argument("--evaluator-group", required=True)
    seal_cmd.add_argument("--proposer-user", action="append", default=[])
    seal_cmd.add_argument("--apply-permissions", action="store_true")
    seal_cmd.add_argument("--out", type=Path, required=True)
    consume_cmd = sub.add_parser("consume-once")
    consume_cmd.add_argument("--receipt", type=Path, required=True)
    consume_cmd.add_argument("--marker", type=Path, required=True)
    consume_cmd.add_argument("--out", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.command == "seal":
        result = seal(
            args.dataset_root,
            args.repository_root,
            args.seal_root,
            args.zone,
            os.environ.get("ZEL_HOLDOUT_HMAC_KEY", ""),
            args.evaluator_group,
            args.proposer_user,
            args.apply_permissions,
        )
    elif args.command == "consume-once":
        result = consume_once(args.receipt, args.marker, os.environ.get("ZEL_FINAL_HOLDOUT_TOKEN", ""))
    else:
        parser.error("command required")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "errors": result.get("errors", [])}, sort_keys=True))
    return 0 if result["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
