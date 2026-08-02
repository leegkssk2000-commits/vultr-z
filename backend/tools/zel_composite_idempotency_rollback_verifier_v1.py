from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import zel_composite_terminal_v3_acceptance_harness_v1 as harness

VERSION = "ZEL_COMPOSITE_IDEMPOTENCY_ROLLBACK_VERIFIER_V1"
VOLATILE_KEYS = {
    "generated_at",
    "receipt_sha256",
    "sequence_id",
    "predecessor_receipt_sha256",
}
DEFAULT_PROTECTED_PATHS = (
    "backend/research/zel_composite_live_source_pin_v1.json",
    "backend/research/zel_composite_adapter_contract_v1.json",
    "backend/research/zel_composite_module_registry_v1.json",
    "backend/research/zel_composite_module_factory_contract_v1.json",
    "backend/research/zel_skill_counterfactual_contract_v1.json",
    "backend/strategy25/canonical_strategy25_config_v1.json",
    "backend/contracts/ZOS_SKILL_REGISTRY_v1.json",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode("utf-8")
    ).hexdigest()


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def protected_hashes(source_root: Path, paths: Iterable[str]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for relative in paths:
        path = source_root / relative
        result[relative] = sha256_path(path) if path.is_file() else None
    return result


def git_ref_sha(source_root: Path, ref: str) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def git_status(source_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return sorted(line for line in proc.stdout.splitlines() if line.strip())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def verify(source_root: Path, out_dir: Path, rollback_ref: str, protected_paths: Iterable[str]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = tuple(protected_paths)
    before_hashes = protected_hashes(source_root, paths)
    before_status = git_status(source_root)
    rollback_sha = git_ref_sha(source_root, rollback_ref)

    run_a = out_dir / "run_a"
    run_b = out_dir / "run_b"
    summary_a = harness.run_harness(source_root, run_a)
    summary_b = harness.run_harness(source_root, run_b)
    evaluation_a = load_json(run_a / "evaluation/latest.json")
    evaluation_b = load_json(run_b / "evaluation/latest.json")

    semantic_a = normalize(evaluation_a)
    semantic_b = normalize(evaluation_b)
    semantic_sha_a = stable_sha(semantic_a)
    semantic_sha_b = stable_sha(semantic_b)
    acceptance_sha_a = stable_sha(normalize(summary_a))
    acceptance_sha_b = stable_sha(normalize(summary_b))

    after_hashes = protected_hashes(source_root, paths)
    after_status = git_status(source_root)
    mutations = [
        path
        for path in paths
        if before_hashes.get(path) != after_hashes.get(path)
    ]
    missing_protected = [path for path in paths if before_hashes.get(path) is None]
    status_delta = sorted(set(after_status) - set(before_status))
    blockers: list[str] = []
    if rollback_sha is None:
        blockers.append("ROLLBACK_REF_MISSING")
    if missing_protected:
        blockers.append("PROTECTED_PATH_MISSING")
    if mutations:
        blockers.append("PROTECTED_PATH_MUTATED")
    if status_delta:
        blockers.append("TRACKED_GIT_STATUS_DELTA")
    if semantic_sha_a != semantic_sha_b:
        blockers.append("SEMANTIC_OUTPUT_NONDETERMINISTIC")
    if acceptance_sha_a != acceptance_sha_b:
        blockers.append("ACCEPTANCE_RECEIPT_NONDETERMINISTIC")
    if summary_a.get("state") != "PASS_COMPOSITE_TERMINAL_V3_ACCEPTANCE_HARNESS":
        blockers.append("RUN_A_ACCEPTANCE_FAILED")
    if summary_b.get("state") != "PASS_COMPOSITE_TERMINAL_V3_ACCEPTANCE_HARNESS":
        blockers.append("RUN_B_ACCEPTANCE_FAILED")

    state = "PASS_COMPOSITE_IDEMPOTENCY_AND_ROLLBACK" if not blockers else "HOLD_COMPOSITE_IDEMPOTENCY_AND_ROLLBACK"
    result: dict[str, Any] = {
        "schema_version": "zel.composite.idempotency_rollback.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "rollback_ref": rollback_ref,
        "rollback_commit_sha": rollback_sha,
        "protected_path_count": len(paths),
        "missing_protected_paths": missing_protected,
        "protected_mutations": mutations,
        "tracked_git_status_delta": status_delta,
        "semantic_sha_run_a": semantic_sha_a,
        "semantic_sha_run_b": semantic_sha_b,
        "semantic_outputs_identical": semantic_sha_a == semantic_sha_b,
        "acceptance_sha_run_a": acceptance_sha_a,
        "acceptance_sha_run_b": acceptance_sha_b,
        "acceptance_receipts_identical": acceptance_sha_a == acceptance_sha_b,
        "run_a_state": summary_a.get("state"),
        "run_b_state": summary_b.get("state"),
        "blockers": sorted(set(blockers)),
        "rollback_executed": False,
        "rollback_ready": rollback_sha is not None and not mutations,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["receipt_sha256"] = stable_sha({key: value for key, value in result.items() if key != "receipt_sha256"})
    (out_dir / "idempotency_rollback_receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def self_test() -> None:
    source_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="zel-idempotency-rollback.") as temp:
        row = verify(
            source_root,
            Path(temp),
            "HEAD",
            (
                "backend/research/zel_composite_adapter_contract_v1.json",
                "backend/research/zel_composite_live_source_pin_v1.json",
            ),
        )
    assert row["state"] == "PASS_COMPOSITE_IDEMPOTENCY_AND_ROLLBACK", row
    assert row["semantic_outputs_identical"] is True, row
    assert row["protected_mutations"] == [], row
    assert row["rollback_ready"] is True, row
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--rollback-ref", default="pre-composite-factory-v1-20260802")
    parser.add_argument("--protected-path", action="append", dest="protected_paths")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.source_root or not args.out_dir:
        parser.error("source-root and out-dir are required")
    row = verify(
        args.source_root.resolve(),
        args.out_dir.resolve(),
        args.rollback_ref,
        tuple(args.protected_paths or DEFAULT_PROTECTED_PATHS),
    )
    print(json.dumps(row, sort_keys=True))
    return 0 if row["state"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
