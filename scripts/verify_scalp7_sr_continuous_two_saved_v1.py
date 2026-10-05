#!/usr/bin/env python3
"""Check saved SR receipts and immutable predecessors without market execution."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCOPE = "G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1"
CAMPAIGN = Path("research/campaigns/scalp7_20261001/sr_continuous_two_v1")
PREVIOUS = Path("research/campaigns/scalp7_20261001/measurement_exact25_closure_v1")
TRUST_ROOT = "80556d5b617810ef9e0cd888684290d0d24b460d"
PREVIOUS_SEAL_SHA256 = (
    "d4e0389190cfb50a657fddaff37c67ec9588c53baea75c30960f901873fb6ec8"
)
OLD_ROOT = "7bb11442454053c011082fd6034d965631e719ef"
OLD_CAMPAIGN = Path("research/campaigns/scalp7_20261001/exact25_five_v1")
OLD_SEAL_SHA256 = "907a013b6a8cc4179fd179627465f3f77bb496a4e092466e18ab6a7ecdd6c200"
IDENTITIES = {
    "SR_CONTROL": {
        "identity_key": "08e02370c96bd0c65ced1bb3f65bcb19099665c1b0a487a4226a3bfc49c53200",
        "binding_sha256": "c8dc2ab777b9a48442e0aaac60b4a8665a1578702d28a24234bad3cfb187c91e",
    },
    "SR_RETEST": {
        "identity_key": "6ccad0c2e6939d801a2a216661213414edd46db79f31ae3f017125afbd348b70",
        "binding_sha256": "063b9280c566274b51bfd0103cb76f4866e80eeed91ddeaff712c9fcc40f0af8",
    },
}
SEGMENTS = {"common_contiguous_1", "common_contiguous_2"}
SOURCES = ("PR_EVENT_BASE", "DEFAULT_BRANCH_PUSH_BEFORE", "PUBLISHED_DEFAULT_BRANCH")
REQUIRED_NAMES = {
    "AUTHORIZATION.txt",
    "USER_APPROVAL.json",
    "COMPLETION_SUMMARY.json",
    "FINAL_REPORT.md",
    "COVERAGE.json",
    "WORK_NEXT.txt",
    "VALIDATION.json",
    "audits/INDEPENDENT_ECONOMIC_AUDIT.json",
    "recovery/FINAL_LEDGER_EXPORT.json",
    "results/SR_CONTROL.json.gz",
    "results/SR_RETEST.json.gz",
}
REQUIRED_CODE = {
    "scripts/verify_scalp7_sr_continuous_two_saved_v1.py",
    "scripts/verify_scalp7_sr_continuous_two_arithmetic_v1.py",
    "tests/test_scalp7_sr_continuous_two_saved_v1.py",
    ".github/workflows/scalp7-sr-continuous-two-saved-v1.yml",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def local_file(repo: Path, name: str) -> Path:
    path = Path(name)
    result = (repo / path).resolve()
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and str(path) == name
        and result.is_relative_to(repo.resolve())
        and result.is_file()
        and not (repo / path).is_symlink(),
        "UNSAFE_OR_MISSING_FILE:" + name,
    )
    return result


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(result.returncode == 0, "GIT_UNAVAILABLE:" + " ".join(args[:2]))
    return result.stdout


def hashes(raw: bytes, key: str) -> dict[str, str]:
    value = json.loads(raw)
    result = value.get(key)
    require(isinstance(result, dict) and bool(result), "EMPTY_SEAL_HASHES")
    for name, digest in result.items():
        require(
            isinstance(name, str)
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "INVALID_SEAL_ENTRY",
        )
    return result


def check_files(repo: Path, expected: dict[str, str]) -> None:
    for name, digest in sorted(expected.items()):
        require(sha_file(local_file(repo, name)) == digest, "HASH_CHANGED:" + name)


def preserve(
    repo: Path, commit: str, campaign: Path, seal_sha: str, key: str, count: int
) -> int:
    path = campaign / "INPUT_SEAL.json"
    trusted = git(repo, "show", commit + ":" + str(path))
    require(hashlib.sha256(trusted).hexdigest() == seal_sha, "TRUST_ROOT_CHANGED")
    require(
        sha_file(local_file(repo, str(path))) == seal_sha,
        "PUBLISHED_SEAL_REPLACED:" + str(path),
    )
    values = hashes(trusted, key)
    require(len(values) == count, "PRESERVED_SEAL_COUNT")
    check_files(repo, values)
    return len(values)


def explicit_commit(repo: Path, value: str) -> str:
    require(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}", value) is not None
        and value != "0" * 40,
        "EXPLICIT_NONZERO_COMMIT_REQUIRED",
    )
    require(git(repo, "cat-file", "-t", value).strip() == b"commit", "NOT_COMMIT")
    return value


def history(repo: Path, base: str, checkout: str, source: str, branch: str) -> int:
    require(source in SOURCES, "UNTRUSTED_BASE_SOURCE")
    explicit_commit(repo, checkout)
    require(
        git(repo, "rev-parse", "HEAD").decode().strip() == checkout, "CHECKOUT_MISMATCH"
    )
    explicit_commit(repo, base)
    require(base != checkout, "HEAD_CANNOT_ANCHOR_ITSELF")
    require(re.fullmatch(r"[A-Za-z0-9._/-]+", branch) is not None, "INVALID_BRANCH")
    git(repo, "check-ref-format", "refs/heads/" + branch)
    if source == "PUBLISHED_DEFAULT_BRANCH":
        ref = "refs/remotes/origin/" + branch + "^{commit}"
        require(
            git(repo, "rev-parse", "--verify", ref).decode().strip() == base,
            "BASE_REF_MISMATCH",
        )
    path = CAMPAIGN / "INPUT_SEAL.json"
    if not git(repo, "ls-tree", "--name-only", base, "--", str(path)).strip():
        return 0
    trusted = git(repo, "show", base + ":" + str(path))
    require(
        sha_file(local_file(repo, str(path))) == hashlib.sha256(trusted).hexdigest(),
        "PUBLISHED_BATCH_SEAL_REPLACED",
    )
    values = hashes(trusted, "covered_files")
    check_files(repo, values)
    return len(values)


def read_json(repo: Path, name: str) -> dict[str, Any]:
    path = local_file(repo, str(CAMPAIGN / name))
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict), "ARTIFACT_NOT_OBJECT:" + name)
    return value


def authority(value: dict[str, Any]) -> None:
    auth = value.get("authority", {})
    require(
        auth.get("order") == "BLOCKED"
        and auth.get("live") == "BLOCKED"
        and auth.get("promotion") is False,
        "UNAUTHORIZED_AUTHORITY",
    )


def check_summary(value: dict[str, Any]) -> None:
    require(value.get("scope_key") == SCOPE, "SUMMARY_SCOPE")
    for key, expected in {
        "new_full_authorized": 2,
        "new_full_started": 2,
        "new_full_completed": 2,
        "remaining_full_budget": 0,
        "max_starts_per_identity": 1,
        "cost_2x_additional_full_runs": 0,
    }.items():
        require(
            type(value.get(key)) is int and value[key] == expected,
            "EXECUTION_BUDGET:" + key,
        )
    require(
        value.get("original25_complete") is False
        and value.get("g4_complete") is False
        and value.get("profitability_pass") is False,
        "FALSE_COMPLETION_OR_PROFITABILITY_PASS",
    )
    require(
        value.get("funding_status") == "UNKNOWN_NOT_ZERO"
        and value.get("whole_period_nav") is None
        and value.get("cross_segment_nav_aggregation") == "FORBIDDEN",
        "INVALID_ECONOMIC_LIMITATIONS",
    )
    predecessor = value.get("predecessor_budget", {})
    for key, expected in {
        "started": 5,
        "completed": 5,
        "remaining_full": 0,
        "reset_or_retries": 0,
    }.items():
        require(
            type(predecessor.get(key)) is int and predecessor[key] == expected,
            "OLD_FIVE_BUDGET_CHANGED:" + key,
        )
    rows = value.get("identity_results")
    require(
        isinstance(rows, dict) and set(rows) == set(IDENTITIES), "EXACT_TWO_RESULTS"
    )
    for label, expected in IDENTITIES.items():
        for key, expected_value in expected.items():
            require(rows[label].get(key) == expected_value, "FROZEN_RESULT_IDENTITY")
        require(
            rows[label].get("result_path")
            == str(CAMPAIGN / "results" / (label + ".json.gz")),
            "RESULT_PATH_CHANGED",
        )
    authority(value)


def check_outer(label: str, value: dict[str, Any]) -> None:
    require(
        value.get("schema") == "scalp7.measurement.segment_comparison_result.v1",
        "RESULT_SCHEMA",
    )
    for key, expected in IDENTITIES[label].items():
        require(value.get(key) == expected, "RESULT_FROZEN_BINDING")
    require(
        value.get("full_execution_performed") is True
        and type(value.get("full_execution_count")) is int
        and value["full_execution_count"] == 1,
        "IDENTITY_FULL_COUNT",
    )
    require(
        isinstance(value.get("segments"), dict) and set(value["segments"]) == SEGMENTS,
        "ALL_TWO_SEGMENTS_REQUIRED",
    )
    require(
        isinstance(value.get("segment_checkpoints"), dict)
        and set(value["segment_checkpoints"]) == SEGMENTS,
        "ALL_TWO_CHECKPOINTS_REQUIRED",
    )
    require(
        value.get("whole_period_nav") is None
        and value.get("cross_segment_nav_aggregation") == "FORBIDDEN"
        and value.get("funding_status") == "UNKNOWN_NOT_ZERO"
        and value.get("old_unresolved_positions") == "PRESERVED_SEPARATE_PARENT_STATE",
        "FALSE_WHOLE_ACCOUNT_OR_OWNER_CLOSURE",
    )
    authority(value)


def check_ledger(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scopes = [r for r in value.get("scopes", []) if r["scope"] == SCOPE]
    require(len(scopes) == 1, "EXACT_SCOPE_REQUIRED")
    require(
        all(
            type(scopes[0].get(k)) is int and scopes[0][k] == 2
            for k in ("max_candidates", "max_executions")
        ),
        "LEDGER_SCOPE_BUDGET",
    )
    claims = [r for r in value.get("claims", []) if r["scope"] == SCOPE]
    by_key = {r["identity_key"]: r for r in claims}
    keys = {v["identity_key"] for v in IDENTITIES.values()}
    require(len(claims) == 2 and set(by_key) == keys, "EXACT_LEDGER_IDENTITIES")
    events = [r for r in value.get("events", []) if r["scope"] == SCOPE]
    require(
        not any(r["event"] in {"FAILED", "HOLD", "REJECTED"} for r in events),
        "TERMINAL_HISTORY_CANNOT_BE_RESET",
    )
    for label, identity in IDENTITIES.items():
        key = identity["identity_key"]
        claim = by_key[key]
        require(
            claim.get("candidate_id") == label + "_CONTINUOUS_SEGMENTS_V1"
            and claim.get("state") == "COMPLETED",
            "LEDGER_EXECUTION_NOT_COMPLETED",
        )
        for event in ("RESERVED", "STARTED", "COMPLETED"):
            require(
                sum(r["identity_key"] == key and r["event"] == event for r in events)
                == 1,
                "MAX_ONE_EVENT_PER_IDENTITY:" + event,
            )
    require(
        sum(r["event"] == "STARTED" for r in events) == 2,
        "TOTAL_FULL_COUNT",
    )
    return by_key


def decoded(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else value


def check_saved_chain(
    repo: Path,
    label: str,
    row: dict[str, Any],
    raw_result: bytes,
    outer: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    ledger: dict[str, Any],
) -> None:
    key = IDENTITIES[label]["identity_key"]
    receipt = decoded(claims[key]["result_json"])
    require(
        receipt.get("result_file_sha256") == hashlib.sha256(raw_result).hexdigest()
        and receipt.get("binding_sha256") == IDENTITIES[label]["binding_sha256"],
        "LEDGER_RESULT_RECEIPT_CHANGED",
    )
    completed = next(
        r
        for r in ledger["events"]
        if r["scope"] == SCOPE
        and r["identity_key"] == key
        and r["event"] == "COMPLETED"
    )
    require(decoded(completed["payload_json"]) == receipt, "TERMINAL_EVENT_MISMATCH")
    entries = row.get("segment_checkpoints")
    require(
        isinstance(entries, dict) and set(entries) == SEGMENTS, "CHECKPOINT_ARCHIVE_SET"
    )
    for sid, entry in entries.items():
        expected_path = str(
            CAMPAIGN / "checkpoints" / (label + "." + sid + ".checkpoint.json.gz")
        )
        require(entry.get("archive_path") == expected_path, "CHECKPOINT_ARCHIVE_PATH")
        path = local_file(repo, entry["archive_path"])
        require(
            sha_file(path) == entry.get("storage_sha256"), "CHECKPOINT_STORAGE_CHANGED"
        )
        with gzip.open(path, "rb") as stream:
            raw = stream.read()
        digest = hashlib.sha256(raw).hexdigest()
        require(
            digest
            == entry.get("raw_sha256")
            == outer["segment_checkpoints"][sid]["sha256"],
            "CHECKPOINT_RAW_CHANGED",
        )
        checkpoint = json.loads(raw)
        require(
            checkpoint
            == {
                "outer_identity_key": key,
                "segment_id": sid,
                "binding_sha256": IDENTITIES[label]["binding_sha256"],
                "result": outer["segments"][sid],
            },
            "CHECKPOINT_RESULT_CHANGED",
        )


def check_coverage(value: dict[str, Any], previous: dict[str, Any]) -> None:
    for key in (
        "original25_strategy_ids",
        "original25_count",
        "prior_unfinished19_ids",
        "unfinished19_preserved",
        "unfinished19_reclassified_as_completed",
        "rows",
    ):
        require(value.get(key) == previous[key], "ORIGINAL25_GAPS_CHANGED:" + key)
    require(
        value.get("original25_complete") is False and value.get("g4_complete") is False,
        "FALSE_ORIGINAL25_COMPLETION",
    )


def verify(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    old_count = preserve(repo, OLD_ROOT, OLD_CAMPAIGN, OLD_SEAL_SHA256, "hashes", 181)
    prior_count = preserve(
        repo, TRUST_ROOT, PREVIOUS, PREVIOUS_SEAL_SHA256, "covered_files", 93
    )
    seal_path = CAMPAIGN / "INPUT_SEAL.json"
    raw = local_file(repo, str(seal_path)).read_bytes()
    require(json.loads(raw).get("scope_key") == SCOPE, "SEAL_SCOPE")
    sealed = hashes(raw, "covered_files")
    required = {str(CAMPAIGN / name) for name in REQUIRED_NAMES} | REQUIRED_CODE
    require(required <= sealed.keys(), "NEW_SEAL_REQUIRED_COVERAGE")
    require(str(seal_path) not in sealed, "SELF_REFERENTIAL_SEAL")
    actual = {
        str(path.relative_to(repo))
        for path in (repo / CAMPAIGN).rglob("*")
        if path.is_file() and path != repo / seal_path
    }
    require(actual <= sealed.keys(), "UNSEALED_CAMPAIGN_FILES")
    check_files(repo, sealed)
    summary = read_json(repo, "COMPLETION_SUMMARY.json")
    check_summary(summary)
    ledger = read_json(repo, "recovery/FINAL_LEDGER_EXPORT.json")
    claims = check_ledger(ledger)
    check_coverage(
        read_json(repo, "COVERAGE.json"),
        json.loads(local_file(repo, str(PREVIOUS / "COVERAGE.json")).read_bytes()),
    )
    audit = read_json(repo, "audits/INDEPENDENT_ECONOMIC_AUDIT.json")
    require(
        audit.get("schema") == "g4.sr_continuous_two.independent_saved_arithmetic.v1"
        and audit.get("status") == "PASS"
        and audit.get("errors") == []
        and audit.get("error_count") == 0
        and type(audit.get("new_full_runs")) is int
        and audit["new_full_runs"] == 0,
        "INDEPENDENT_SAVED_AUDIT_FAILED",
    )
    require(
        isinstance(audit.get("segments"), dict) and set(audit["segments"]) == SEGMENTS,
        "INDEPENDENT_AUDIT_SEGMENT_COVERAGE",
    )
    validation = read_json(repo, "VALIDATION.json")
    require(
        validation.get("status") == "PASS"
        and type(validation.get("new_full_runs")) is int
        and validation["new_full_runs"] == 0,
        "SAVED_VALIDATION_FAILED",
    )
    for label in IDENTITIES:
        row = summary["identity_results"][label]
        path = local_file(repo, row["result_path"])
        require(
            sha_file(path) == row.get("result_sha256"), "SUMMARY_RESULT_SHA_CHANGED"
        )
        with gzip.open(path, "rb") as stream:
            raw_result = stream.read()
        outer = json.loads(raw_result)
        check_outer(label, outer)
        check_saved_chain(repo, label, row, raw_result, outer, claims, ledger)
    return {
        "schema": "g4.sr_continuous_two.saved_publication_guard.v1",
        "status": "PASS",
        "scope_key": SCOPE,
        "old_five_sealed_files_checked": old_count,
        "pr1346_sealed_files_checked": prior_count,
        "new_sealed_files_checked": len(sealed),
        "approved_full_started": 2,
        "approved_full_completed": 2,
        "new_full_runs_by_verification": 0,
        "market_data_loaded": False,
        "g4_complete": False,
        "profitability_pass": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base-sha")
    parser.add_argument("--checkout-sha")
    parser.add_argument("--base-source", choices=SOURCES)
    parser.add_argument("--default-branch")
    parser.add_argument("--history-only", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    values = (args.base_sha, args.checkout_sha, args.base_source, args.default_branch)
    published = 0
    if any(values) or args.history_only:
        require(all(values), "ALL_CI_HISTORY_ARGUMENTS_REQUIRED")
        preserve(repo, OLD_ROOT, OLD_CAMPAIGN, OLD_SEAL_SHA256, "hashes", 181)
        preserve(repo, TRUST_ROOT, PREVIOUS, PREVIOUS_SEAL_SHA256, "covered_files", 93)
        published = history(repo, *values)
    result = (
        {"status": "PASS", "new_full_runs_by_verification": 0}
        if args.history_only
        else verify(repo)
    )
    result["event_base_sealed_files_checked"] = published
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
