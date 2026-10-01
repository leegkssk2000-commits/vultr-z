#!/usr/bin/env python3
"""Validate sealed saved research evidence; never import market loaders or replay."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

CAMPAIGN = Path("research/campaigns/scalp7_20261001/exact25_five_v1")
PREVIOUS = Path("research/campaigns/scalp7_20260920/model_closure_v1")
SCOPE = "G4_EXACT25_SOURCE_TO_CODE_IMPLEMENTATION_AFTER_FINAL_REVIEW_V1"
LABELS = ("ST_CONTROL", "ST_TRAIL", "SR_CONTROL", "SR_RETEST", "NOISE_BASELINE")
AUTHORITY = {"order": "BLOCKED", "live": "BLOCKED", "promotion": False}
TERMINAL = {"COMPLETED", "FAILED", "HOLD", "REJECTED"}
SELF = "scripts/verify_scalp7_exact25_five_publication_v1.py"
ARITHMETIC = "scripts/verify_scalp7_exact25_five_arithmetic_v1.py"
REQUIRED = {
    SELF,
    ARITHMETIC,
    "scripts/run_scalp7_exact25_five_authorized_v1.py",
    "scripts/supervise_scalp7_exact25_five_v1.py",
    "scripts/report_scalp7_exact25_five_v1.py",
    ".github/workflows/scalp7-exact25-five-saved-v1.yml",
} | {
    str(CAMPAIGN / name)
    for name in (
        "AUTHORIZATION.txt",
        "ALLOCATION_RECEIPT.json",
        "REGISTRY_EXPORT.json",
        "ECONOMIC_COMPARISON.json",
        "ECONOMIC_REPORT.md",
        "recovery/INVENTORY_BEFORE_ALLOCATION.json",
        "recovery/RAW_INVENTORY_CHECK.json",
        "audits/RUNNER_PREFLIGHT_REVIEW.json",
        "audits/INDEPENDENT_ECONOMIC_AUDIT.json",
        "audits/build_independent_comparison_audit.py",
    )
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_digest(value: Any) -> str:
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    result = hashlib.sha256()
    for chunk in encoder.iterencode(value):
        result.update(chunk.encode())
    return result.hexdigest()


def sha(path: Path, *, uncompressed: bool = False) -> str:
    opener: Any = gzip.open if uncompressed and path.suffix == ".gz" else open
    result = hashlib.sha256()
    with opener(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def no_nonfinite(value: str) -> None:
    raise ValueError("NONFINITE_JSON:" + value)


def loads(value: str) -> Any:
    return json.loads(value, parse_constant=no_nonfinite)


def load(path: Path) -> dict[str, Any]:
    opener: Any = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        value = json.load(stream, parse_constant=no_nonfinite)
    require(isinstance(value, dict), "JSON_OBJECT_REQUIRED:" + str(path))
    return value


def safe_path(repo: Path, name: str) -> Path:
    candidate = Path(name)
    resolved = (repo / candidate).resolve()
    require(
        not candidate.is_absolute()
        and ".." not in candidate.parts
        and str(candidate) == name
        and resolved.is_relative_to(repo)
        and resolved.is_file(),
        "FILE_MISSING_OR_UNSAFE_PATH:" + name,
    )
    return resolved


def verify_registry(
    registry: dict[str, Any],
    prepared: dict[str, dict[str, Any]],
    allocation: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    require(
        registry["schema"] == "g4.exact25.five_registry_export.v1", "REGISTRY_SCHEMA"
    )
    require(registry["scope_key"] == SCOPE, "REGISTRY_SCOPE")
    scopes, claims, events = (registry[k] for k in ("scopes", "claims", "events"))
    require(len(scopes) == 1 and scopes[0]["scope"] == SCOPE, "SINGLE_SCOPE_REQUIRED")
    scope = scopes[0]
    require(
        scope["owner"] == "WORK_ROOT_EXACT25_FIVE_SINGLE_OWNER", "SCOPE_OWNER_CHANGED"
    )
    require(
        type(scope["max_candidates"]) is int
        and type(scope["max_executions"]) is int
        and scope["max_candidates"] == scope["max_executions"] == 5,
        "CUMULATIVE_BUDGET_CHANGED",
    )
    contract = loads(scope["contract_json"])
    require(contract == allocation["contract"], "ALLOCATION_CONTRACT_MISMATCH")
    keys = {row["identity"] for row in prepared.values()}
    require(
        contract["new_full_authorized"] is True
        and contract["prior_target_started"] == 0
        and contract["cumulative_cap_all_sessions"] == 5
        and contract["max_per_identity"] == 1
        and len(contract["allowed_identities"]) == 5
        and set(contract["allowed_identities"]) == keys
        and contract["automatic_retry_forbidden"] is True
        and contract["orders"] == contract["live"] == "BLOCKED"
        and contract["paid_spending"] is False
        and contract["promotion"] is False
        and contract["services"] == "NO_CHANGE",
        "AUTHORIZATION_LIMITS_CHANGED",
    )
    require(
        len(claims) == 5 and {c["identity_key"] for c in claims} == keys,
        "CLAIM_SET_MISMATCH",
    )
    require(
        [e["sequence"] for e in events] == list(range(1, len(events) + 1)),
        "EVENT_SEQUENCE_GAP_DUPLICATE_OR_REORDER",
    )
    require(all(e["scope"] == SCOPE for e in events), "CROSS_SCOPE_EVENT")
    scope_events = [e for e in events if e["identity_key"] is None]
    require(
        len(scope_events) == 1
        and scope_events[0]["event"] == "SCOPE_CREATED"
        and scope_events[0]["sequence"] == 1
        and loads(scope_events[0]["payload_json"]) == contract,
        "SCOPE_EVENT_MISMATCH",
    )
    require(
        all(e["identity_key"] in keys or e["identity_key"] is None for e in events),
        "UNAUTHORIZED_IDENTITY_EVENT",
    )
    started = sum(e["event"] == "STARTED" for e in events)
    require(started <= 5, "CUMULATIVE_EXECUTION_BUDGET_EXCEEDED")
    by_key = {c["identity_key"]: c for c in claims}
    for key, claim in by_key.items():
        require(claim["scope"] == SCOPE, "CLAIM_SCOPE_MISMATCH")
        identity = loads(claim["identity_json"])
        require(
            canonical_digest({k: v for k, v in identity.items() if k != "candidate_id"})
            == key,
            "CLAIM_IDENTITY_DIGEST_MISMATCH",
        )
        require(
            identity["candidate_id"] == claim["candidate_id"], "CANDIDATE_ID_MISMATCH"
        )
        history = [e for e in events if e["identity_key"] == key]
        kinds = [e["event"] for e in history]
        state = claim["state"]
        if state == "RESERVED":
            allowed = [["RESERVED"]]
        elif state == "RUNNING":
            allowed = [["RESERVED", "STARTED"]]
        elif state in TERMINAL:
            allowed = [["RESERVED", "STARTED", state]]
            if state in {"HOLD", "REJECTED"}:
                allowed.append(["RESERVED", state])
        else:
            raise ValueError("UNKNOWN_CLAIM_STATE")
        require(kinds in allowed, "RETRY_OR_IMMUTABLE_HISTORY_CONFLICT:" + key)
        require(
            loads(history[0]["payload_json"]) == identity,
            "RESERVATION_IDENTITY_MISMATCH",
        )
        if state in TERMINAL:
            require(
                loads(history[-1]["payload_json"]) == loads(claim["result_json"]),
                "TERMINAL_RECEIPT_MISMATCH",
            )
        else:
            require(claim["result_json"] is None, "NONTERMINAL_RESULT_RECEIPT")
    return {label: by_key[row["identity"]] for label, row in prepared.items()}


def verify_report(report: dict[str, Any], completed: set[str]) -> None:
    require(report["schema"] == "scalp7.exact25.five_report.v1", "REPORT_SCHEMA")
    require(report["scope_key"] == SCOPE, "REPORT_SCOPE")
    require(
        report["results_count"] == len(completed)
        and len(report["completed_saved_results"]) == len(completed)
        and set(report["completed_saved_results"]) == completed
        and len(report["missing_results"]) == len(set(LABELS) - completed)
        and set(report["missing_results"]) == set(LABELS) - completed
        and set(report["results"]) == completed,
        "REPORT_COMPLETION_MISMATCH",
    )
    prefix = "SAVED_RESULTS" if len(completed) == 5 else "PARTIAL_SAVED_RESULTS"
    expected = (
        prefix + "_COLLECTED_PENDING_INDEPENDENT_AUDIT"
        if len(completed) == 5
        else prefix + "_PENDING_INDEPENDENT_AUDIT"
    )
    require(report["report_status"] == expected, "REPORT_STATUS_MISMATCH")
    require(
        report["audit_status"] == "PENDING_INDEPENDENT_AUDIT"
        and report["authorized_identity_total"] == 5
        and report["additional_full_runs_by_report"] == 0
        and report["original25_complete"] is False
        and report["original25_total"] == 25
        and report["remaining19_preserved"] is True
        and report["g4_complete"] is False
        and report["funding_status"] == "UNKNOWN_NOT_ZERO"
        and report["actual_historical_net_usdt"] is None
        and report["formal_promotion"] == "BLOCKED"
        and report["authority"] == AUTHORITY
        and isinstance(report["limitations"], list)
        and bool(report["limitations"]),
        "UNSUPPORTED_ECONOMIC_OR_AUTHORITY_CLAIM",
    )


def verify(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    seal = load(repo / CAMPAIGN / "INPUT_SEAL.json")
    require(seal["scope_key"] == SCOPE, "SEAL_SCOPE")
    hashes = seal["hashes"]
    require(
        isinstance(hashes, dict) and REQUIRED <= hashes.keys(),
        "ESSENTIAL_SEAL_COVERAGE",
    )
    for name, expected in hashes.items():
        require(sha(safe_path(repo, name)) == expected, "SEALED_FILE_CHANGED:" + name)
    for path in (repo / CAMPAIGN).rglob("*"):
        if path.is_file() and path.name != "INPUT_SEAL.json":
            require(str(path.relative_to(repo)) in hashes, "UNSEALED_CAMPAIGN_ARTIFACT")
    # This previous verifier is standard-library-only and checks frozen code bytes.
    previous_script = repo / "scripts/verify_scalp7_exact25_model_closure_v1.py"
    spec = importlib.util.spec_from_file_location(
        "exact25_saved_previous", previous_script
    )
    if spec is None or spec.loader is None:
        raise ValueError("PREVIOUS_CHECKER_UNAVAILABLE")
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    previous.verify(repo)
    request = load(repo / PREVIOUS / "PREPARED_EXECUTION_REQUEST.json")
    prepared = {row["label"]: row for row in request["identities"]}
    require(set(prepared) == set(LABELS), "FROZEN_FIVE_CHANGED")
    allocation = load(repo / CAMPAIGN / "ALLOCATION_RECEIPT.json")
    authorization = str(CAMPAIGN / "AUTHORIZATION.txt")
    require(
        allocation["contract"]["approval_ref"]
        == authorization + "#sha256=" + hashes[authorization],
        "APPROVAL_FILE_BINDING_MISMATCH",
    )
    claims = verify_registry(
        load(repo / CAMPAIGN / "REGISTRY_EXPORT.json"), prepared, allocation
    )
    for label, claim in claims.items():
        frozen = load(repo / prepared[label]["freeze_path"])
        require(
            loads(claim["identity_json"]) == frozen["candidate_identity"],
            "CLAIM_FROZEN_IDENTITY_MISMATCH:" + label,
        )
    completed = {
        label for label, claim in claims.items() if claim["state"] == "COMPLETED"
    }
    report_path = repo / CAMPAIGN / "ECONOMIC_COMPARISON.json"
    report = load(report_path)
    verify_report(report, completed)
    sources = {}
    for label in LABELS:
        raw_name = str(CAMPAIGN / "results" / (label + ".json.gz"))
        if label not in completed:
            require(
                not (repo / raw_name).exists(),
                "NONCOMPLETED_RAW_RESULT_REQUIRES_REVIEW",
            )
            continue
        require(raw_name in hashes, "UNSEALED_RESULT:" + label)
        raw_path = safe_path(repo, raw_name)
        source_sha = sha(raw_path, uncompressed=True)
        raw = load(raw_path)
        receipt = loads(claims[label]["result_json"])
        row = prepared[label]
        frozen = load(repo / row["freeze_path"])
        require(
            loads(claims[label]["identity_json"]) == frozen["candidate_identity"],
            "CLAIM_FROZEN_IDENTITY_MISMATCH",
        )
        require(
            raw["schema"] == "zel.scalp7.exact25_model_runner.v1"
            and raw["identity_key"] == row["identity"]
            and raw["binding_sha256"]
            == receipt["binding_sha256"]
            == row["binding_sha256"]
            and receipt["result_file_sha256"] == source_sha
            and receipt["result_sha256"] == canonical_digest(raw)
            and receipt["unknown_execution_count"] == raw["unknown_execution_count"],
            "RAW_RESULT_REGISTRY_BINDING_MISMATCH:" + label,
        )
        require(
            raw["full_execution_performed"] is True
            and raw["data_kind"] == "GENUINE_RAW_HISTORY"
            and raw["authority"] == AUTHORITY
            and raw["formal_promotion"] == "BLOCKED"
            and raw["fresh_T"] == 0,
            "RAW_EVIDENCE_AUTHORITY_MISMATCH:" + label,
        )
        summary = report["results"][label]
        require(
            summary["source_file"] == raw_name
            and summary["source_file_sha256"] == source_sha
            and summary["source_storage_sha256"] == hashes[raw_name]
            and summary["identity_key"] == row["identity"]
            and summary["binding_sha256"] == row["binding_sha256"],
            "REPORT_RESULT_BINDING_MISMATCH:" + label,
        )
        audit_name = str(CAMPAIGN / "audits" / (label + "_ARITHMETIC.json"))
        require(audit_name in hashes, "UNSEALED_ARITHMETIC_AUDIT:" + label)
        audit = load(repo / audit_name)
        require(
            audit["schema"] == "g4.exact25.independent_saved_arithmetic.v1"
            and audit["status"] == "PASS"
            and audit["error_count"] == 0
            and audit["errors"] == []
            and audit["check_count"] > 0
            and audit["new_economic_executions"] == 0
            and audit["model_or_loader_imported"] is False
            and audit["inputs"]["result_sha256"] == source_sha
            and audit["inputs"]["freeze_sha256"] == sha(repo / row["freeze_path"])
            and audit["inputs"]["verifier_sha256"] == hashes[ARITHMETIC],
            "INDEPENDENT_AUDIT_INVALID_OR_UNBOUND:" + label,
        )
        sources[label] = source_sha
        del raw
    audit = load(repo / CAMPAIGN / "audits/INDEPENDENT_ECONOMIC_AUDIT.json")
    require(
        audit["scope_key"] == SCOPE
        and audit["status"] == "PASS"
        and audit["error_count"] == 0
        and audit["errors"] == []
        and audit["check_count"] > 0
        and audit["recipe_path"]
        == str(CAMPAIGN / "audits/build_independent_comparison_audit.py")
        and audit["recipe_sha256"] == hashes[audit["recipe_path"]]
        and set(audit["completed_saved_results"]) == completed
        and len(audit["completed_saved_results"]) == len(completed)
        and set(audit["missing_results"]) == set(LABELS) - completed
        and len(audit["missing_results"]) == 5 - len(completed)
        and audit["coverage_status"]
        == (
            "COMPLETE_FIVE_SAVED_RESULTS"
            if len(completed) == 5
            else "PARTIAL_SAVED_RESULTS"
        )
        and set(audit["per_result_audit_paths"])
        == {
            str(CAMPAIGN / "audits" / (label + "_ARITHMETIC.json"))
            for label in completed
        }
        and len(audit["per_result_audit_paths"]) == len(completed)
        and audit["market_data_loaded"] is False
        and audit["new_full_runs"] == 0
        and audit["source_result_sha256"] == sources
        and audit["economic_comparison_sha256"] == sha(report_path)
        and bool(audit["checks"]),
        "COMPARISON_AUDIT_INVALID_OR_UNBOUND",
    )
    markdown = (repo / CAMPAIGN / "ECONOMIC_REPORT.md").read_text(encoding="utf-8")
    audit_path = repo / CAMPAIGN / "audits/INDEPENDENT_ECONOMIC_AUDIT.json"
    require(
        "독립 검산: PASS." in markdown
        and "경제 JSON SHA256=" + sha(report_path) in markdown
        and "감사 SHA256=" + sha(audit_path) in markdown
        and "- 저장 결과 확보: " + str(len(completed)) + "/5;" in markdown
        and "PENDING 표시는 검산 전 생성단계" in markdown,
        "MARKDOWN_ATTESTATION_MISSING_OR_STALE",
    )
    registry = load(repo / CAMPAIGN / "REGISTRY_EXPORT.json")
    return {
        "status": "PASS" if len(completed) == 5 else "PASS_PARTIAL_EVIDENCE",
        "completed_saved_results": len(completed),
        "cumulative_started": sum(e["event"] == "STARTED" for e in registry["events"]),
        "states": {label: claim["state"] for label, claim in claims.items()},
        "five_identity_batch_complete": len(completed) == 5,
        "original25_complete": False,
        "g4_complete": False,
        "funding_status": "UNKNOWN_NOT_ZERO",
        "new_full_runs": 0,
        "market_data_loaded": False,
        "sealed_files": len(hashes),
    }


def self_test() -> dict[str, Any]:
    """Adversarial state-history checks do not execute market data or models."""
    prepared: dict[str, dict[str, Any]] = {}
    claims: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    identities = []
    for label in LABELS:
        identity = {
            "candidate_id": label,
            "strategy_id": label,
            "rule_sha256": "a" * 64,
        }
        key = canonical_digest(
            {k: v for k, v in identity.items() if k != "candidate_id"}
        )
        identities.append(key)
        prepared[label] = {"identity": key}
        claims.append(
            {
                "identity_key": key,
                "scope": SCOPE,
                "candidate_id": label,
                "identity_json": json.dumps(identity),
                "state": "RESERVED",
                "result_json": None,
            }
        )
        events.append(
            {
                "scope": SCOPE,
                "identity_key": key,
                "event": "RESERVED",
                "payload_json": json.dumps(identity),
            }
        )
    contract = {
        "new_full_authorized": True,
        "prior_target_started": 0,
        "cumulative_cap_all_sessions": 5,
        "max_per_identity": 1,
        "allowed_identities": identities,
        "automatic_retry_forbidden": True,
        "orders": "BLOCKED",
        "live": "BLOCKED",
        "paid_spending": False,
        "promotion": False,
        "services": "NO_CHANGE",
    }
    scope = {
        "owner": "WORK_ROOT_EXACT25_FIVE_SINGLE_OWNER",
        "scope": SCOPE,
        "max_candidates": 5,
        "max_executions": 5,
        "contract_json": json.dumps(contract),
    }
    events.insert(
        0,
        {
            "scope": SCOPE,
            "identity_key": None,
            "event": "SCOPE_CREATED",
            "payload_json": json.dumps(contract),
        },
    )
    for index, event in enumerate(events, 1):
        event["sequence"] = index
    registry: dict[str, Any] = {
        "schema": "g4.exact25.five_registry_export.v1",
        "scope_key": SCOPE,
        "scopes": [scope],
        "claims": claims,
        "events": events,
    }
    allocation = {"contract": contract}
    verify_registry(registry, prepared, allocation)
    failures = 0

    def rejected(value: dict[str, Any]) -> None:
        nonlocal failures
        try:
            verify_registry(value, prepared, allocation)
        except (ValueError, KeyError, TypeError):
            failures += 1
        else:
            raise RuntimeError("TAMPER_WAS_ACCEPTED")

    altered = copy.deepcopy(registry)
    altered["scopes"][0]["owner"] = "OTHER_OWNER"
    rejected(altered)
    altered = copy.deepcopy(registry)
    altered["scopes"][0]["max_executions"] = 10
    rejected(altered)
    altered = copy.deepcopy(registry)
    altered["events"].pop(2)
    rejected(altered)
    altered = copy.deepcopy(registry)
    altered["claims"][0]["state"] = "COMPLETED"
    altered["claims"][0]["result_json"] = "{}"
    rejected(altered)
    altered = copy.deepcopy(registry)
    altered["claims"][0]["identity_json"] = json.dumps({"candidate_id": "renamed"})
    rejected(altered)
    failed = copy.deepcopy(registry)
    failed["claims"][0].update(state="FAILED", result_json='{"budget_consumed":true}')
    for kind, payload in (("STARTED", "{}"), ("FAILED", '{"budget_consumed":true}')):
        failed["events"].append(
            {
                "sequence": len(failed["events"]) + 1,
                "scope": SCOPE,
                "identity_key": identities[0],
                "event": kind,
                "payload_json": payload,
            }
        )
    verify_registry(failed, prepared, allocation)
    failed["events"].append(
        {
            "sequence": len(failed["events"]) + 1,
            "scope": SCOPE,
            "identity_key": identities[0],
            "event": "STARTED",
            "payload_json": "{}",
        }
    )
    failed["claims"][0].update(state="RUNNING", result_json=None)
    rejected(failed)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        for name in ("../escape", "/absolute", "missing.json"):
            try:
                safe_path(root, name)
            except ValueError:
                failures += 1
            else:
                raise RuntimeError("UNSAFE_PATH_WAS_ACCEPTED")
    require(failures == 9, "SELF_TEST_COVERAGE_MISMATCH")
    return {"status": "PASS", "tamper_rejections": failures, "new_full_runs": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    result = self_test() if args.self_test else verify(args.repo)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
