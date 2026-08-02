from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zel_holdout_vault_audit_v1 import ZONES, audit
from zel_holdout_vault_v1 import seal

VERSION = "ZEL_HOLDOUT_VAULT_SEAL_RUNNER_V1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def split_users(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def safe_summary(
    state: str,
    receipts: list[dict[str, Any]],
    post_audit_path: Path | None,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "zel.holdout_vault.seal_summary.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "zone_count": len(receipts),
        "zones": [
            {
                "zone": row.get("zone"),
                "state": row.get("state"),
                "manifest_sha256": row.get("manifest_sha256"),
                "manifest_hmac_sha256": row.get("manifest_hmac_sha256"),
                "file_count": row.get("file_count"),
                "total_bytes": row.get("total_bytes"),
                "one_shot_required": row.get("one_shot_required"),
            }
            for row in receipts
        ],
        "post_audit_sha256": (
            hashlib.sha256(post_audit_path.read_bytes()).hexdigest()
            if post_audit_path and post_audit_path.is_file()
            else None
        ),
        "errors": sorted(set(errors)),
        "raw_holdout_published": False,
        "canonical_strategy_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def run_seal(
    repository_root: Path,
    zone_roots: dict[str, Path],
    seal_root: Path,
    evaluator_group: str,
    proposer_users_csv: str,
    hmac_key: str,
    out_dir: Path,
) -> dict[str, Any]:
    users = split_users(proposer_users_csv)
    errors: list[str] = []
    receipts: list[dict[str, Any]] = []
    pre = audit(
        repository_root,
        zone_roots,
        seal_root,
        evaluator_group,
        users,
        bool(hmac_key),
        100_000,
    )
    write_json(out_dir / "pre_audit.json", pre)
    if pre["state"] != "PASS_HOLDOUT_VAULT_AUDIT_READY_TO_SEAL":
        errors.append("PRE_AUDIT_NOT_PASS")
        summary = safe_summary("HOLD_EXTERNAL_HOLDOUT_PRE_AUDIT", receipts, None, errors + pre.get("errors", []))
        write_json(out_dir / "seal_summary.json", summary)
        return summary

    for zone in ZONES:
        receipt = seal(
            zone_roots[zone],
            repository_root,
            seal_root,
            zone,
            hmac_key,
            evaluator_group,
            users,
            True,
        )
        receipts.append(receipt)
        filename = {
            "W2_FORWARD": "w2_receipt.json",
            "W3_DURABILITY": "w3_receipt.json",
            "FINAL_HOLDOUT": "final_receipt.json",
        }[zone]
        write_json(out_dir / filename, receipt)
        if receipt["state"] != "PASS_HOLDOUT_VAULT_SEALED":
            errors.extend(receipt.get("errors", []))
            errors.append(f"SEAL_FAILED:{zone}")
            break

    post_path: Path | None = None
    if len(receipts) == 3 and not errors:
        post = audit(
            repository_root,
            zone_roots,
            seal_root,
            evaluator_group,
            users,
            True,
            100_000,
        )
        post_path = out_dir / "post_audit.json"
        write_json(post_path, post)
        if post["state"] != "PASS_HOLDOUT_VAULT_AUDIT_READY_TO_SEAL":
            errors.extend(post.get("errors", []))
            errors.append("POST_AUDIT_NOT_PASS")

    passed = len(receipts) == 3 and not errors
    if passed and receipts[-1].get("one_shot_required") is not True:
        errors.append("FINAL_HOLDOUT_NOT_ONE_SHOT")
        passed = False
    summary = safe_summary(
        "PASS_EXTERNAL_HOLDOUT_VAULTS_SEALED" if passed else "HOLD_EXTERNAL_HOLDOUT_SEAL",
        receipts,
        post_path,
        errors,
    )
    write_json(out_dir / "seal_summary.json", summary)
    return summary


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        repo = root / "repo"
        vault = root / "vault"
        seals = root / "seals"
        out = root / "out"
        repo.mkdir()
        vault.mkdir()
        seals.mkdir()
        os.chmod(seals, 0o700)
        group = grp.getgrgid(os.getgid()).gr_name
        zone_roots: dict[str, Path] = {}
        for zone in ZONES:
            path = vault / zone.lower()
            path.mkdir()
            os.chmod(path, 0o750)
            source = path / "source.json"
            source.write_text('{"fixture":true}\n', encoding="utf-8")
            os.chmod(source, 0o640)
            zone_roots[zone] = path
        result = run_seal(repo, zone_roots, seals, group, "", "fixture-key", out)
        assert result["state"] == "PASS_EXTERNAL_HOLDOUT_VAULTS_SEALED", result
        assert result["zone_count"] == 3, result
        assert result["zones"][-1]["one_shot_required"] is True, result
        assert result["raw_holdout_published"] is False, result
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
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = (
        args.repository_root,
        args.w2_root,
        args.w3_root,
        args.final_root,
        args.seal_root,
        args.evaluator_group,
        args.out_dir,
    )
    if not all(required):
        parser.error("repository-root, three zone roots, seal-root, evaluator-group and out-dir are required")
    hmac_key = os.environ.get("ZEL_HOLDOUT_HMAC_KEY", "")
    result = run_seal(
        args.repository_root,
        {
            "W2_FORWARD": args.w2_root,
            "W3_DURABILITY": args.w3_root,
            "FINAL_HOLDOUT": args.final_root,
        },
        args.seal_root,
        args.evaluator_group,
        args.proposer_users,
        hmac_key,
        args.out_dir,
    )
    print(json.dumps({
        "state": result["state"],
        "zone_count": result["zone_count"],
        "error_count": len(result["errors"]),
    }, sort_keys=True))
    return 0 if result["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
