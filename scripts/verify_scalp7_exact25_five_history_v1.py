#!/usr/bin/env python3
"""Anchor saved execution evidence to Git history; no replay or market I/O.

CI supplies its event-selected base commit and checkout commit explicitly.
This protects the normal workflow from coordinated evidence/seal replacement.
It does not claim to protect against replacing the entire workflow and checker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

CAMPAIGN = Path("research/campaigns/scalp7_20261001/exact25_five_v1")
SEAL = CAMPAIGN / "INPUT_SEAL.json"
SCOPE = "G4_EXACT25_SOURCE_TO_CODE_IMPLEMENTATION_AFTER_FINAL_REVIEW_V1"
BOOTSTRAP_COMMIT = "b23437663194b4f790cb4b2d3cef00c55d47aa0b"
BOOTSTRAP_SEAL_SHA256 = (
    "1fa3baf060ef1a050b7e954bc2d130de314527c0cb4a202718b890bbe51baad6"
)
LABELS = ("ST_CONTROL", "ST_TRAIL", "SR_CONTROL", "SR_RETEST", "NOISE_BASELINE")
EXECUTION_FILES = (
    {
        str(CAMPAIGN / name)
        for name in (
            "AUTHORIZATION.txt",
            "ALLOCATION_RECEIPT.json",
            "REGISTRY_EXPORT.json",
            "TERMINAL_RECEIPT.json",
            "recovery/INVENTORY_BEFORE_ALLOCATION.json",
            "recovery/RAW_INVENTORY_CHECK.json",
            "execution_logs/supervisor.log",
        )
    }
    | {str(CAMPAIGN / "results" / (label + ".json.gz")) for label in LABELS}
    | {str(CAMPAIGN / "execution_logs" / (label + ".log")) for label in LABELS}
)
SOURCES = ("PR_EVENT_BASE", "DEFAULT_BRANCH_PUSH_BEFORE", "PUBLISHED_DEFAULT_BRANCH")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def git(repo: Path, *arguments: str) -> bytes:
    process = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode:
        raise ValueError("GIT_HISTORY_UNAVAILABLE:" + " ".join(arguments[:2]))
    return process.stdout


def commit(repo: Path, value: str) -> str:
    require(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}", value) is not None
        and value != "0" * 40,
        "EXPLICIT_NONZERO_COMMIT_SHA_REQUIRED",
    )
    require(
        git(repo, "cat-file", "-t", value).strip() == b"commit",
        "COMMIT_OBJECT_REQUIRED",
    )
    return value


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_file(repo: Path, name: str) -> Path:
    path = Path(name)
    resolved = (repo / path).resolve()
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and str(path) == name
        and resolved.is_relative_to(repo)
        and resolved.is_file(),
        "MISSING_OR_UNSAFE_ANCHORED_FILE:" + name,
    )
    return resolved


def parse_seal(raw: bytes) -> dict[str, str]:
    seal = json.loads(raw)
    require(
        isinstance(seal, dict)
        and seal.get("scope_key") == SCOPE
        and isinstance(seal.get("hashes"), dict)
        and bool(seal["hashes"]),
        "TRUSTED_SEAL_SCHEMA_INVALID",
    )
    for name, digest in seal["hashes"].items():
        require(
            isinstance(name, str)
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "TRUSTED_SEAL_HASH_INVALID",
        )
    return seal["hashes"]


def check_files(repo: Path, expected: dict[str, str], selected: set[str]) -> None:
    require(selected <= expected.keys(), "TRUSTED_SEAL_EXECUTION_COVERAGE_MISSING")
    for name in sorted(selected):
        require(
            sha_file(local_file(repo, name)) == expected[name],
            "HISTORY_ANCHORED_EVIDENCE_CHANGED:" + name,
        )


def check_published(repo: Path, raw_seal: bytes) -> int:
    expected = parse_seal(raw_seal)
    require(
        sha_file(local_file(repo, str(SEAL))) == hashlib.sha256(raw_seal).hexdigest(),
        "PUBLISHED_SEAL_REPLACED",
    )
    check_files(repo, expected, set(expected))
    return len(expected)


def verify(
    repo: Path, base_sha: str, checkout_sha: str, source: str, default_branch: str
) -> dict[str, Any]:
    repo = repo.resolve()
    require(source in SOURCES, "EXPLICIT_TRUSTED_BASE_SOURCE_REQUIRED")
    checkout_sha = commit(repo, checkout_sha)
    require(
        git(repo, "rev-parse", "HEAD").decode().strip() == checkout_sha,
        "CI_CHECKOUT_SHA_MISMATCH",
    )
    base_sha = commit(repo, base_sha)
    require(base_sha != checkout_sha, "HEAD_CANNOT_BE_ITS_OWN_HISTORY_ANCHOR")
    require(
        re.fullmatch(r"[A-Za-z0-9._/-]+", default_branch) is not None,
        "DEFAULT_BRANCH_NAME_INVALID",
    )
    git(repo, "check-ref-format", "refs/heads/" + default_branch)
    if source == "PUBLISHED_DEFAULT_BRANCH":
        ref = "refs/remotes/origin/" + default_branch + "^{commit}"
        require(
            git(repo, "rev-parse", "--verify", ref).decode().strip() == base_sha,
            "FETCHED_DEFAULT_BRANCH_SHA_MISMATCH",
        )
    commit(repo, BOOTSTRAP_COMMIT)
    bootstrap = git(repo, "show", BOOTSTRAP_COMMIT + ":" + str(SEAL))
    require(
        hashlib.sha256(bootstrap).hexdigest() == BOOTSTRAP_SEAL_SHA256,
        "IMMUTABLE_BOOTSTRAP_SEAL_MISMATCH",
    )
    check_files(repo, parse_seal(bootstrap), EXECUTION_FILES)
    base_has_seal = bool(
        git(repo, "ls-tree", "--name-only", base_sha, "--", str(SEAL)).strip()
    )
    published_count = 0
    if base_has_seal:
        published_count = check_published(
            repo, git(repo, "show", base_sha + ":" + str(SEAL))
        )
    return {
        "status": "PASS",
        "base_sha": base_sha,
        "base_source": source,
        "checkout_sha": checkout_sha,
        "bootstrap_commit": BOOTSTRAP_COMMIT,
        "bootstrap_execution_files_checked": len(EXECUTION_FILES),
        "published_seal_present": base_has_seal,
        "published_files_checked": published_count,
        "new_full_runs": 0,
        "market_data_loaded": False,
        "workflow_replacement_protection_claimed": False,
    }


def self_test() -> dict[str, Any]:
    """Attack both the execution evidence and its mutable seal in a temporary repo."""
    rejected = 0
    with tempfile.TemporaryDirectory() as directory:
        repo = Path(directory).resolve()
        git(repo, "init", "--quiet")
        artifact = repo / CAMPAIGN / "results/ST_CONTROL.json.gz"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"original-saved-result")
        expected = {str(artifact.relative_to(repo)): sha_file(artifact)}
        seal_file = repo / SEAL
        original = json.dumps({"scope_key": SCOPE, "hashes": expected}).encode()
        seal_file.write_bytes(original)
        git(repo, "add", ".")
        git(
            repo,
            "-c",
            "user.name=Anchor Test",
            "-c",
            "user.email=anchor@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "immutable evidence",
        )
        base = commit(repo, git(repo, "rev-parse", "HEAD").decode().strip())
        trusted = git(repo, "show", base + ":" + str(SEAL))
        check_published(repo, trusted)
        artifact.write_bytes(b"fabricated-replacement")
        forged = {str(artifact.relative_to(repo)): sha_file(artifact)}
        seal_file.write_text(json.dumps({"scope_key": SCOPE, "hashes": forged}))
        for operation in (
            lambda: check_published(repo, trusted),
            lambda: check_files(repo, parse_seal(trusted), set(expected)),
        ):
            try:
                operation()
            except ValueError:
                rejected += 1
            else:
                raise RuntimeError("COORDINATED_EVIDENCE_AND_SEAL_TAMPER_ACCEPTED")
        seal_file.write_bytes(trusted)
        try:
            check_published(repo, trusted)
        except ValueError:
            rejected += 1
        else:
            raise RuntimeError("RESULT_ONLY_TAMPER_ACCEPTED")
        for invalid in ("HEAD", "master", "0" * 40):
            try:
                commit(repo, invalid)
            except ValueError:
                rejected += 1
            else:
                raise RuntimeError("UNTRUSTED_COMMIT_REFERENCE_ACCEPTED")
    require(rejected == 6, "HISTORY_TAMPER_COVERAGE_MISMATCH")
    return {"status": "PASS", "tamper_rejections": rejected, "new_full_runs": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--base-sha")
    parser.add_argument("--checkout-sha")
    parser.add_argument("--base-source", choices=SOURCES)
    parser.add_argument("--default-branch")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
    else:
        require(
            all(
                (
                    args.base_sha,
                    args.checkout_sha,
                    args.base_source,
                    args.default_branch,
                )
            ),
            "CI_BASE_CHECKOUT_SOURCE_AND_BRANCH_ARGUMENTS_REQUIRED",
        )
        result = verify(
            args.repo,
            args.base_sha,
            args.checkout_sha,
            args.base_source,
            args.default_branch,
        )
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
