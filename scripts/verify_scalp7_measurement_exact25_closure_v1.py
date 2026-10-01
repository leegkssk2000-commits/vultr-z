#!/usr/bin/env python3
"""Verify preserved publication and synthetic-only closure artifacts, without replay.

The fixed merged predecessor is the trust root. CI additionally supplies its
published event base. Replacing the entire workflow is outside this guard's
claim and remains subject to normal repository review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCOPE = "G4_MEASUREMENT_REPAIR_AND_EXACT25_CLOSURE_AFTER_PR1345_V1"
CAMPAIGN = Path("research/campaigns/scalp7_20261001/measurement_exact25_closure_v1")
SEAL = CAMPAIGN / "INPUT_SEAL.json"
PREDECESSOR = "7bb11442454053c011082fd6034d965631e719ef"
OLD_SEAL = Path("research/campaigns/scalp7_20261001/exact25_five_v1/INPUT_SEAL.json")
OLD_SEAL_SHA256 = "907a013b6a8cc4179fd179627465f3f77bb496a4e092466e18ab6a7ecdd6c200"
SOURCES = ("PR_EVENT_BASE", "DEFAULT_BRANCH_PUSH_BEFORE", "PUBLISHED_DEFAULT_BRANCH")
SYMBOLS = {"BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT", "LINK-USDT"}
NEXT_LABELS = {"SR_CONTROL_CONTINUOUS_SEGMENTS_V1", "SR_RETEST_CONTINUOUS_SEGMENTS_V1"}
NEW_MODULES = {
    "backend/research/rebuild/scalp7_measurement_repair_v1.py",
    "backend/research/rebuild/scalp7_measurement_compare_v1.py",
    "backend/research/rebuild/scalp7_product_contracts_v1.py",
    "backend/research/rebuild/scalp7_hg_closure_v1.py",
    "backend/research/rebuild/scalp7_volume_contract_v1.py",
    "backend/research/rebuild/scalp7_kell_gajjala_closure_v1.py",
    "backend/research/rebuild/scalp7_closure_dispatch_v1.py",
}
REQUIRED = (
    {
        str(CAMPAIGN / name)
        for name in (
            "AUTHORIZATION.txt",
            "COMPLETION_SUMMARY.json",
            "NEXT_ECONOMIC_BATCH.json",
            "FINAL_REPORT.md",
            "COVERAGE.md",
            "WORK_NEXT.txt",
            "VALIDATION.json",
            "audits/guard/INDEPENDENT_PREFLIGHT.json",
            "audits/guard/INDEPENDENT_CODE_REVIEW.json",
            "measurement/CONTINUOUS_DATA_CONTRACT.json",
            "measurement/SOURCE_AND_OWNERSHIP_AUDIT.json",
            "measurement/SYNTHETIC_REGRESSION_RECEIPT.json",
            "implementation/hg/HG_CLOSURE.json",
            "implementation/kell_gajjala/CONTRACT.json",
            "implementation/kell_gajjala/SYNTHETIC_EVIDENCE.json",
            "next_freezes/SR_CONTROL.json",
            "next_freezes/SR_RETEST.json",
            "implementation/volume/SOURCE_CONTRACT.json",
        )
    }
    | NEW_MODULES
    | {
        "scripts/verify_scalp7_measurement_exact25_closure_v1.py",
        "tests/test_scalp7_measurement_closure_saved_v1.py",
        "tests/test_scalp7_measurement_repair_v1.py",
        "tests/test_scalp7_product_contracts_v1.py",
        "tests/test_scalp7_closure_dispatch_v1.py",
        "scripts/audit_scalp7_measurement_repair_v1.py",
        "scripts/assemble_scalp7_measurement_closure_v1.py",
        "tests/test_scalp7_hg_closure_v1.py",
        "tests/test_scalp7_volume_contract_v1.py",
        "tests/test_scalp7_kell_gajjala_closure_v1.py",
        ".github/workflows/scalp7-measurement-exact25-closure-v1.yml",
    }
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(proc.returncode == 0, "GIT_UNAVAILABLE:" + " ".join(args[:2]))
    return proc.stdout


def explicit_commit(repo: Path, value: str) -> str:
    require(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}", value) is not None
        and value != "0" * 40,
        "EXPLICIT_NONZERO_COMMIT_REQUIRED",
    )
    require(git(repo, "cat-file", "-t", value).strip() == b"commit", "NOT_COMMIT")
    return value


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_file(repo: Path, name: str) -> Path:
    path = Path(name)
    result = (repo / path).resolve()
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and str(path) == name
        and result.is_relative_to(repo)
        and result.is_file()
        and not (repo / path).is_symlink(),
        "UNSAFE_OR_MISSING_FILE:" + name,
    )
    return result


def hash_map(raw: bytes, key: str, scope: str | None = None) -> dict[str, str]:
    obj = json.loads(raw)
    require(isinstance(obj, dict), "SEAL_NOT_OBJECT")
    if scope is not None:
        require(obj.get("scope_key") == scope, "SEAL_SCOPE_MISMATCH")
    values = obj.get(key)
    require(isinstance(values, dict) and bool(values), "EMPTY_SEAL_HASHES")
    for name, digest in values.items():
        require(
            isinstance(name, str)
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "INVALID_SEAL_ENTRY",
        )
    return values


def check_files(repo: Path, expected: dict[str, str]) -> None:
    for name, digest in sorted(expected.items()):
        require(sha_file(local_file(repo, name)) == digest, "HASH_CHANGED:" + name)


def check_published(repo: Path, raw: bytes, path: Path, key: str) -> int:
    require(
        sha_file(local_file(repo, str(path))) == hashlib.sha256(raw).hexdigest(),
        "PUBLISHED_SEAL_REPLACED:" + str(path),
    )
    expected = hash_map(raw, key)
    check_files(repo, expected)
    return len(expected)


def preserve_predecessor(repo: Path) -> int:
    explicit_commit(repo, PREDECESSOR)
    raw = git(repo, "show", PREDECESSOR + ":" + str(OLD_SEAL))
    require(hashlib.sha256(raw).hexdigest() == OLD_SEAL_SHA256, "TRUST_ROOT_CHANGED")
    count = check_published(repo, raw, OLD_SEAL, "hashes")
    require(count == 181, "PREDECESSOR_SEAL_COUNT")
    return count


def preserve_backend(repo: Path, published_base: str | None = None) -> list[str]:
    """Only declared additions may differ from the authenticated published base."""
    baseline = explicit_commit(repo, published_base or PREDECESSOR)
    changed = set(
        git(repo, "diff", "--name-only", "-z", baseline, "--", "backend")
        .decode()
        .strip("\0")
        .split("\0")
    ) - {""}
    changed |= set(
        git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", "backend")
        .decode()
        .strip("\0")
        .split("\0")
    ) - {""}
    known = set(
        git(repo, "ls-tree", "-r", "--name-only", baseline, "--", "backend")
        .decode()
        .splitlines()
    )
    changed |= {
        str(path.relative_to(repo))
        for path in (repo / "backend").rglob("*.py")
        if str(path.relative_to(repo)) not in known
    }
    require(
        changed <= NEW_MODULES,
        "UNEXPECTED_BACKEND_CHANGE:" + repr(sorted(changed - NEW_MODULES)),
    )
    for name in changed:
        require(
            not git(repo, "ls-tree", "--name-only", baseline, "--", name).strip(),
            "EXISTING_BACKEND_REPLACED:" + name,
        )
        local_file(repo, name)
    return sorted(changed)


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
    if git(repo, "ls-tree", "--name-only", base, "--", str(SEAL)).strip():
        return check_published(
            repo, git(repo, "show", base + ":" + str(SEAL)), SEAL, "covered_files"
        )
    return 0


def authority(obj: dict[str, Any]) -> None:
    value = obj.get("authority", {})
    require(
        value.get("order") == "BLOCKED"
        and value.get("live") == "BLOCKED"
        and value.get("promotion") is False,
        "UNAUTHORIZED_AUTHORITY",
    )


def read_json(repo: Path, name: str) -> dict[str, Any]:
    result = json.loads(local_file(repo, str(CAMPAIGN / name)).read_bytes())
    require(isinstance(result, dict), "ARTIFACT_NOT_OBJECT:" + name)
    return result


def check_summary(summary: dict[str, Any]) -> None:
    require(summary.get("scope_key") == SCOPE, "SUMMARY_SCOPE")
    require(
        type(summary.get("new_full_runs")) is int
        and summary["new_full_runs"] == 0
        and type(summary.get("genuine_history_strategy_probes")) is int
        and summary["genuine_history_strategy_probes"] == 0,
        "UNAUTHORIZED_ECONOMIC_EXECUTION",
    )
    require(
        summary.get("original25_complete") is False
        and summary.get("g4_complete") is False,
        "FALSE_FULL_COMPLETION",
    )
    authority(summary)


def check_next_batch(batch: dict[str, Any]) -> None:
    require(batch.get("scope_key") == SCOPE, "NEXT_BATCH_SCOPE")
    require(
        type(batch.get("new_full_authorized")) is int
        and batch["new_full_authorized"] == 0,
        "NEXT_BATCH_NOT_AUTHORIZED",
    )
    authority(batch)
    rows: Any = batch.get("prepared_identities")
    require(isinstance(rows, list) and bool(rows), "NO_PREPARED_IDENTITIES")
    require(
        len({row["identity_key"] for row in rows}) == len(rows), "DUPLICATE_IDENTITY"
    )
    require(
        {row.get("label") for row in rows} == NEXT_LABELS and len(rows) == 2,
        "EXACT_TWO_SR_IDENTITIES_REQUIRED",
    )
    total = 0
    for row in rows:
        require(
            row.get("prior_control_reusable") is False,
            "CHANGED_DATA_OLD_CONTROL_REUSED",
        )
        require(
            type(row.get("required_new_full_runs")) is int
            and row["required_new_full_runs"] == 1,
            "IDENTITY_FULL_COUNT",
        )
        require(
            row.get("changed_axis") == "DATA_CONTINUITY_AND_INDEPENDENT_CAPITAL_ONLY",
            "UNAPPROVED_CHANGED_AXIS",
        )
        for key in ("data_sha256", "cost_sha256", "period_sha256"):
            require(
                isinstance(row.get(key), str)
                and re.fullmatch(r"[0-9a-f]{64}", row[key]) is not None,
                "UNBOUND_NEXT_BATCH:" + key,
            )
        total += row["required_new_full_runs"]
    require(batch.get("minimum_new_full_runs") == total, "MINIMUM_FULL_COUNT_MISMATCH")
    require(
        batch.get("evaluation_mode")
        == "INDEPENDENT_CONTINUOUS_SEGMENTS_NOT_WHOLE_ACCOUNT",
        "FALSE_WHOLE_ACCOUNT_CLAIM",
    )


def check_preflight(obj: dict[str, Any]) -> None:
    require(
        obj.get("scope_key") == SCOPE
        and obj.get("status") == "PASS"
        and obj.get("errors") == [],
        "PREFLIGHT_FAILED",
    )
    for key, value in {
        "old_scope_started": 5,
        "old_scope_completed": 5,
        "max_starts_per_identity": 1,
        "old_scope_remaining_full_budget": 0,
        "new_scope_registry_rows": 0,
        "new_full_runs_by_preflight": 0,
        "prior_sealed_files": 181,
        "prior_seal_sha256": OLD_SEAL_SHA256,
        "old_workers_or_supervisors": [],
        "partial_result_files": [],
        "prior_sealed_changed_files": [],
        "registry_mutated": False,
    }.items():
        require(obj.get(key) == value, "PREFLIGHT_INVARIANT:" + key)
    require(
        all(
            obj.get("live_old_ledger_matches_saved_export", {}).get(k) is True
            for k in ("scopes", "claims", "events")
        ),
        "OLD_LEDGER_DIVERGED",
    )
    require(
        len(obj.get("locks", {})) == 2
        and all(x.get("state") == "UNHELD" for x in obj["locks"].values()),
        "OLD_EXECUTION_LOCKED",
    )
    require(
        len(obj.get("old_raw_results", {})) == 5
        and all(
            x.get("matches_published_receipt") is True
            for x in obj["old_raw_results"].values()
        ),
        "OLD_RAW_MISMATCH",
    )


def check_continuous_contract(obj: dict[str, Any]) -> None:
    require(
        obj.get("schema") == "scalp7.measurement.continuous_common_data.v1",
        "CONTINUOUS_CONTRACT_SCHEMA",
    )
    claimed = obj.get("contract_sha256")
    payload = {key: value for key, value in obj.items() if key != "contract_sha256"}
    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    require(claimed == digest, "CONTINUOUS_CONTRACT_DIGEST")
    require(
        obj.get("authority", {}).get("new_full_runs") == 0, "CONTINUOUS_FULL_AUTHORITY"
    )
    require(
        obj.get("strategy_or_profit_used_for_selection") is False,
        "PROFIT_SELECTED_PERIODS",
    )
    require(
        obj.get("cross_segment_nav_aggregation") == "FORBIDDEN", "CROSS_SEGMENT_NAV"
    )
    require(
        obj.get("old_unresolved_positions") == "PRESERVED_SEPARATE_PARENT_STATE",
        "UNKNOWN_OWNER_DISCARDED",
    )
    require(
        isinstance(obj.get("segments"), list) and bool(obj["segments"]),
        "MISSING_CONTINUOUS_SEGMENTS",
    )
    require(obj.get("gap_fill") == "FORBIDDEN", "GAP_FILL_FORBIDDEN")
    require(
        obj.get("warmup_ms") == 90 * 86_400_000 and obj.get("decision_minutes") == 30,
        "UNIFORM_CONTEXT_AND_GRID_CHANGED",
    )
    coverage = obj.get("coverage", [])
    require(bool(coverage), "COVERAGE_MISSING")
    require(
        set(obj.get("symbols", [])) == SYMBOLS and len(obj["symbols"]) == len(SYMBOLS),
        "EXACT_SYMBOL_UNIVERSE_REQUIRED",
    )
    require(
        {row["symbol"] for row in coverage} == SYMBOLS
        and len(coverage) == len(SYMBOLS),
        "COVERAGE_SYMBOL_SET_MISMATCH",
    )
    common = [
        (r["start_ts_ms"], r["end_ts_ms"]) for r in coverage[0]["continuous_spans"]
    ]
    for item in coverage[1:]:
        common = [
            (max(a, r["start_ts_ms"]), min(b, r["end_ts_ms"]))
            for a, b in common
            for r in item["continuous_spans"]
            if max(a, r["start_ts_ms"]) < min(b, r["end_ts_ms"])
        ]
    expected = []
    grid = 30 * 60_000
    for start, end in sorted(common):
        first = ((start + 90 * 86_400_000 + grid - 1) // grid) * grid
        last = end // grid * grid
        expected.append((start, end, first, last, first < last))
    observed = [
        (
            r["raw_start_ts_ms"],
            r["raw_end_ts_ms"],
            r["evaluation_start_ts_ms"],
            r["evaluation_end_ts_ms"],
            r["eligible_by_data_only"],
        )
        for r in obj["segments"]
    ]
    require(observed == expected, "DATA_ONLY_ALL_COMMON_INTERVALS_MISMATCH")
    require(
        all(
            r.get("initial_state")
            == "SEPARATE_RESEARCH_ACCOUNT_FLAT_NOT_CLOSURE_OF_OLD_OWNERS"
            for r in obj["segments"]
        ),
        "FALSE_PARENT_POSITION_CLOSURE",
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def check_next_freezes(repo: Path, batch: dict[str, Any]) -> None:
    contract = read_json(repo, "measurement/CONTINUOUS_DATA_CONTRACT.json")
    eligible = {
        row["segment_id"]
        for row in contract["segments"]
        if row["eligible_by_data_only"]
    }
    for row in batch["prepared_identities"]:
        label = row["label"].removesuffix("_CONTINUOUS_SEGMENTS_V1")
        frozen = read_json(repo, "next_freezes/" + label + ".json")
        identity = frozen["candidate_identity"]
        require(
            frozen["label"] == label and identity["candidate_id"] == row["label"],
            "FROZEN_LABEL_MISMATCH",
        )
        require(
            frozen["continuous_contract"] == contract, "FROZEN_DATA_CONTRACT_CHANGED"
        )
        require(
            frozen["new_full_required"] == 1 and frozen["new_full_authorized"] == 0,
            "FROZEN_AUTHORITY_CHANGED",
        )
        require(
            frozen["binding_sha256"]
            == canonical_digest(
                {k: v for k, v in frozen.items() if k != "binding_sha256"}
            ),
            "FROZEN_BINDING_DIGEST",
        )
        require(
            frozen["identity_key"]
            == row["identity_key"]
            == canonical_digest(
                {k: v for k, v in identity.items() if k != "candidate_id"}
            ),
            "FROZEN_IDENTITY_DIGEST",
        )
        for target, origin in (
            ("data_sha256", "data_sha256"),
            ("cost_sha256", "cost_sha256"),
            ("period_sha256", "window_sha256"),
            ("changed_axis", "changed_axis"),
        ):
            require(
                row[target] == identity[origin], "NEXT_ROW_FROZEN_MISMATCH:" + target
            )
        check_files(repo, frozen["code_closure"])
        parent = frozen["parent_binding"]
        predecessor_parent = (
            "research/campaigns/scalp7_20260920/model_closure_v1/freezes/"
            + label
            + ".json"
        )
        require(
            parent == json.loads(local_file(repo, predecessor_parent).read_bytes()),
            "PRESERVED_PARENT_BINDING_CHANGED",
        )
        check_files(repo, parent["code_closure"])
        require(
            identity["cost_sha256"] == canonical_digest(parent["cost"]),
            "PARENT_COST_CHANGED",
        )
        children = frozen["segment_bindings"]
        require(set(children) == eligible, "FROZEN_SEGMENT_OMISSION")
        require(
            identity["window_sha256"]
            == canonical_digest({k: v["windows"] for k, v in children.items()}),
            "FROZEN_PERIOD_CHANGED",
        )
        for child in children.values():
            require(
                child["binding_sha256"]
                == canonical_digest(
                    {k: v for k, v in child.items() if k != "binding_sha256"}
                ),
                "SEGMENT_BINDING_DIGEST",
            )
            for field in (
                "model_id",
                "model_module",
                "config",
                "cost",
                "initial_cash_usdt",
                "code_closure",
                "execution_mode",
                "fill_model",
                "gap_policy",
                "price_basis",
            ):
                require(
                    child[field] == parent[field],
                    "UNAPPROVED_MODEL_OR_COST_CHANGE:" + field,
                )


def check_review_artifacts(repo: Path, review: dict[str, Any]) -> None:
    required = {
        str(CAMPAIGN / name)
        for name in (
            "FINAL_REPORT.md",
            "COVERAGE.json",
            "COVERAGE.md",
            "NEXT_ECONOMIC_BATCH.json",
            "VALIDATION.json",
            "WORK_NEXT.txt",
        )
    }
    artifacts: Any = review.get("artifact_sha256")
    require(
        isinstance(artifacts, dict) and required <= artifacts.keys(),
        "INDEPENDENT_REVIEW_ARTIFACT_COVERAGE",
    )
    check_files(repo, artifacts)


def verify(repo: Path, published_base: str | None = None) -> dict[str, Any]:
    repo = repo.resolve()
    count = preserve_predecessor(repo)
    additions = preserve_backend(repo, published_base)
    hashes = hash_map(local_file(repo, str(SEAL)).read_bytes(), "covered_files", SCOPE)
    require(
        REQUIRED <= hashes.keys(),
        "NEW_SEAL_REQUIRED_COVERAGE:" + repr(sorted(REQUIRED - hashes.keys())),
    )
    actual = {
        str(path.relative_to(repo))
        for path in (repo / CAMPAIGN).rglob("*")
        if path.is_file() and path != repo / SEAL
    }
    require(
        actual <= hashes.keys(),
        "UNSEALED_CAMPAIGN_FILES:" + repr(sorted(actual - hashes.keys())),
    )
    require(str(SEAL) not in hashes, "SELF_REFERENTIAL_SEAL")
    check_files(repo, hashes)
    check_summary(read_json(repo, "COMPLETION_SUMMARY.json"))
    batch = read_json(repo, "NEXT_ECONOMIC_BATCH.json")
    check_next_batch(batch)
    check_next_freezes(repo, batch)
    check_preflight(read_json(repo, "audits/guard/INDEPENDENT_PREFLIGHT.json"))
    check_continuous_contract(
        read_json(repo, "measurement/CONTINUOUS_DATA_CONTRACT.json")
    )
    review = read_json(repo, "audits/guard/INDEPENDENT_CODE_REVIEW.json")
    require(
        review.get("scope_key") == SCOPE
        and review.get("status") == "PASS"
        and review.get("errors") == []
        and review.get("new_full_runs") == 0,
        "INDEPENDENT_REVIEW_MISSING_OR_FAILED",
    )
    require(
        isinstance(review.get("code_sha256"), dict)
        and NEW_MODULES <= review["code_sha256"].keys(),
        "INDEPENDENT_REVIEW_CODE_COVERAGE",
    )
    check_files(repo, review["code_sha256"])
    check_review_artifacts(repo, review)
    validation = read_json(repo, "VALIDATION.json")
    require(validation.get("status") == "PASS", "VALIDATION_NOT_PASS")
    require(
        validation.get("new_full_runs") == 0
        and validation.get("genuine_history_strategy_probes") == 0,
        "VALIDATION_EXECUTION_SCOPE",
    )
    return {
        "schema": "g4.measurement_exact25.saved_guard.v1",
        "status": "PASS",
        "scope_key": SCOPE,
        "predecessor_commit": PREDECESSOR,
        "backend_baseline_commit": published_base or PREDECESSOR,
        "predecessor_sealed_files_checked": count,
        "new_sealed_files_checked": len(hashes),
        "new_backend_modules": additions,
        "new_full_runs": 0,
        "genuine_history_strategy_probes": 0,
        "market_data_loaded": False,
        "workflow_replacement_protection_claimed": False,
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
    backend_base = None
    backend_changes = []
    if any(values) or args.history_only:
        require(all(values), "ALL_CI_HISTORY_ARGUMENTS_REQUIRED")
        preserve_predecessor(repo)
        published = history(repo, *values)
        backend_base = args.base_sha
        backend_changes = preserve_backend(repo, backend_base)
    result = (
        {
            "status": "PASS",
            "new_full_runs": 0,
            "backend_baseline_commit": backend_base,
            "new_backend_modules": backend_changes,
        }
        if args.history_only
        else verify(repo, backend_base)
    )
    result["event_base_sealed_files_checked"] = published
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
