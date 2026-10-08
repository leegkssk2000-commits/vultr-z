"""Bounded parent/child development comparison for Issue 1377.

The module has no order, promotion, or retry authority.  V8 replaces the old
approval -> claim -> consumption administration for this *one* development
comparison with a single permanent start record.  The record is created only
after the real source, cost, calendar and reviewed source have been verified,
and before either model is evaluated.  Historical bars are modeled bar-close
research evidence only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# Direct execution as `python ops/issue1377_mr_batch_v1.py` otherwise places
# only ops/ on sys.path.  Bootstrap the repository root before package imports.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild import scalp7_mr_formation_v2 as rules
from backend.research.rebuild import scalp7_mr_cost2_child_v1 as child_rules
from backend.research.rebuild import scalp7_source_binding_repair_v2 as binding
PROTOCOL_PATH = ROOT / "research/campaigns/scalp7_20261006/issue1377_keltner_orthogonal_v1/PROTOCOL.json"
COST_PATH = ROOT / (
    "research/campaigns/scalp7_20260915/cost_snapshot_v2/"
    "SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json"
)
SOURCE_ROOT = Path("/home/z/z/runtime/economic7_campaign_20260915")
SOURCE_INVENTORY_SHA256 = "53c64616fa98ddd446533cbc7b8e90eb2866ce9b1b0b3243df4211d59f155ba2"
COST_SHA256 = "cb9c337d95aa9eb65c32776ca68c63390350c501de4df8024b5416ed778dbe73"
RULE_SHA256 = "e32154e58d0c04fb77376f0e1e0433bd7c6c6c272fbd1c10d04decaadf70ee7a"
START_MS = 1_768_262_400_000
END_MS = 1_781_654_400_000
WARMUP_MS = 90 * 86_400_000
PARENT = rules.PARENT_IDENTITY
CANDIDATE = child_rules.COST_COVERED_IDENTITY
INSTANCE_IDS = ("N_PARENT", "N_CANDIDATE")
APPROVAL_REF = "refs/heads/research-approvals/issue1377-mr-20261007-v1"
CLAIM_REF = "refs/heads/research-execution-claims/issue1377-mr-20261007-v1"
CONSUMPTION_REF = (
    "refs/heads/research-execution-consumptions/issue1377-mr-20261007-v1"
)
V8_COMMENT_ID = 6_029_066_402
V8_TOKEN = "[issue1377-mr-v8-once-20261007T0210Z-7631c9a]"
V8_ACTIVATION_PATH = ROOT / (
    "research/campaigns/scalp7_20261006/issue1377_keltner_orthogonal_v1/"
    "V8_EXECUTION_ACTIVATION.json"
)
V8_EXECUTION_REF = (
    "refs/heads/research-execution-consumptions/issue1377-mr-v8-20261007-v1"
)
V8_RESULT_REFS = {
    "N_PARENT": "refs/heads/research-results/issue1377-mr-v8-parent-20261007-v1",
    "N_CANDIDATE": "refs/heads/research-results/issue1377-mr-v8-candidate-20261007-v1",
    "COMPARISON": "refs/heads/research-results/issue1377-mr-v8-comparison-20261007-v1",
}
GLOBAL_HEAVY_GROUP = "a1-global-heavy-economic-evaluator-v1"
CLASSIFICATION = "DEVELOPMENT_ONLY_ALREADY_INSPECTED_NOT_FRESH_NOT_OOS"


class Issue1377Error(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def github(method: str, route: str) -> dict[str, Any]:
    if method != "GET" or not route.startswith("/"):
        raise Issue1377Error("READ_ONLY_RELATIVE_GITHUB_API_REQUIRED")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise Issue1377Error("GITHUB_TOKEN_REQUIRED")
    base = "https://api.github.com/repos/leegkssk2000-commits/vultr-z"
    request = Request(
        base + route,
        method="GET",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            if not response.geturl().startswith(base + "/"):
                raise Issue1377Error("GITHUB_REDIRECT_REJECTED")
            value = json.load(response)
    except HTTPError as exc:
        raise Issue1377Error("GITHUB_GET_HTTP_" + str(exc.code)) from None
    if not isinstance(value, dict):
        raise Issue1377Error("GITHUB_OBJECT_REQUIRED")
    return value


def github_create(
    method: str, route: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    allowed = ("/git/blobs", "/git/trees", "/git/commits", "/git/refs")
    if method != "POST" or route not in allowed:
        raise Issue1377Error("FIXED_GIT_OBJECT_CREATE_ROUTE_REQUIRED")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise Issue1377Error("GITHUB_TOKEN_REQUIRED")
    base = "https://api.github.com/repos/leegkssk2000-commits/vultr-z"
    request = Request(
        base + route,
        method="POST",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            if not response.geturl().startswith(base + "/"):
                raise Issue1377Error("GITHUB_REDIRECT_REJECTED")
            value = json.load(response)
    except HTTPError as exc:
        if route == "/git/refs" and exc.code == 422:
            raise Issue1377Error("PERMANENT_REF_ALREADY_EXISTS_NO_RETRY") from None
        raise Issue1377Error("GITHUB_CREATE_HTTP_" + str(exc.code)) from None
    if not isinstance(value, dict):
        raise Issue1377Error("GITHUB_OBJECT_REQUIRED")
    return value


def _git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw,
        usedforsecurity=False,
    ).hexdigest()


def _verified_single_file_ref(
    ref_name: str,
    filename: str,
    api: Callable[[str, str], Mapping[str, Any]],
) -> tuple[dict[str, Any], str, str]:
    ref = api("GET", "/git/ref/" + ref_name.removeprefix("refs/"))
    commit_sha = ref.get("object", {}).get("sha")
    if (
        ref.get("ref") != ref_name
        or ref.get("object", {}).get("type") != "commit"
        or not _commit(commit_sha)
    ):
        raise Issue1377Error("AUTHORITY_REF_PROFILE")
    commit = api("GET", "/git/commits/" + commit_sha)
    tree_sha = commit.get("tree", {}).get("sha")
    parents = commit.get("parents")
    if (
        not _commit(tree_sha)
        or not isinstance(parents, list)
        or len(parents) != 1
        or not _commit(parents[0].get("sha"))
    ):
        raise Issue1377Error("AUTHORITY_COMMIT_PROFILE")
    tree = api("GET", "/git/trees/" + tree_sha)
    entries = tree.get("tree", [])
    if (
        len(entries) != 1
        or entries[0].get("path") != filename
        or entries[0].get("type") != "blob"
        or not _commit(entries[0].get("sha"))
    ):
        raise Issue1377Error("AUTHORITY_TREE_PROFILE")
    blob = api("GET", "/git/blobs/" + entries[0]["sha"])
    if blob.get("encoding") != "base64":
        raise Issue1377Error("AUTHORITY_BLOB_ENCODING")
    raw = base64.b64decode(blob.get("content", ""), validate=False)
    if _git_blob_sha(raw) != entries[0]["sha"]:
        raise Issue1377Error("AUTHORITY_BLOB_HASH")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise Issue1377Error("AUTHORITY_CONTENT_PROFILE")
    return value, commit_sha, parents[0]["sha"]


def verified_approval(
    api: Callable[[str, str], Mapping[str, Any]] = github,
) -> dict[str, Any]:
    value, commit_sha, parent_sha = _verified_single_file_ref(
        APPROVAL_REF, "APPROVED.json", api
    )
    if value.get("approval_commit_sha") is not None:
        raise Issue1377Error("APPROVAL_SELF_ASSERTED_COMMIT")
    if parent_sha != value.get("reviewed_source_sha"):
        raise Issue1377Error("APPROVAL_PARENT_IDENTITY")
    return {**value, "approval_commit_sha": commit_sha}


def verified_claim(
    api: Callable[[str, str], Mapping[str, Any]] = github,
) -> dict[str, Any]:
    value, commit_sha, parent_sha = _verified_single_file_ref(
        CLAIM_REF, "CLAIM.json", api
    )
    if value.get("claim_commit_sha") is not None:
        raise Issue1377Error("CLAIM_SELF_ASSERTED_COMMIT")
    if parent_sha != value.get("independent_approval_commit_sha"):
        raise Issue1377Error("CLAIM_PARENT_IDENTITY")
    return {**value, "claim_commit_sha": commit_sha}


def current_head() -> str:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
    )
    if dirty:
        raise Issue1377Error("EXECUTING_CHECKOUT_DIRTY")
    if not _commit(head):
        raise Issue1377Error("EXECUTING_CHECKOUT_COMMIT")
    return head


def _workflow_activation() -> dict[str, str]:
    activation = {
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "github_job": os.environ.get("GITHUB_JOB", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
    }
    if (
        not all(activation.values())
        or activation["github_run_attempt"] != "1"
        or not _commit(activation["github_sha"])
        or os.environ.get("GITHUB_EVENT_NAME") != "push"
        or os.environ.get("ISSUE1377_GLOBAL_HEAVY_GROUP") != GLOBAL_HEAVY_GROUP
    ):
        raise Issue1377Error("V8_WORKFLOW_ACTIVATION_PROFILE")
    return activation


def validate_v8_activation(
    value: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    required = {
        "schema": "zel.issue1377.mr_v8_activation.v1",
        "issue": 1377,
        "v8_comment_id": V8_COMMENT_ID,
        "token": V8_TOKEN,
        "reviewed_source_sha": manifest.get("reviewed_source_sha"),
        "protocol_sha256": manifest.get("protocol_sha256"),
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "rule_sha256": RULE_SHA256,
        "cost_sha256": COST_SHA256,
        "period_ms": [START_MS, END_MS],
        "instance_ids": list(INSTANCE_IDS),
        "economic_instances": 2,
        "global_heavy_group": GLOBAL_HEAVY_GROUP,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise Issue1377Error("V8_ACTIVATION_BINDING:" + key)
    source_files = value.get("source_files_sha256")
    expected_files = {
        "ops/issue1377_mr_batch_v1.py",
        ".github/workflows/issue1377-keltner-orthogonal-v1.yml",
        "tests/test_issue1377_mr_batch_v1.py",
    }
    if not isinstance(source_files, Mapping) or set(source_files) != expected_files:
        raise Issue1377Error("V8_ACTIVATION_SOURCE_FILE_SET")
    for relative, expected in source_files.items():
        if not isinstance(expected, str) or len(expected) != 64:
            raise Issue1377Error("V8_ACTIVATION_SOURCE_FILE_HASH_PROFILE")
        if file_sha256(ROOT / relative) != expected:
            raise Issue1377Error("V8_ACTIVATION_SOURCE_FILE_DRIFT:" + relative)
    return dict(value)


def source_receipt(market: Mapping[str, Any]) -> dict[str, Any]:
    frames = market["frames"]
    costs = market["costs"]
    rows: dict[str, Any] = {}
    inventory_hashes = set()
    for symbol in rules.PARENT_SYMBOLS:
        frame = frames[symbol]
        inventory_hashes.add(frame.attrs.get("source_inventory_sha256"))
        rows[symbol] = {
            "rows_30m": len(frame),
            "first_open_ts_ms": int(frame.iloc[0].open_ts_ms),
            "last_open_ts_ms": int(frame.iloc[-1].open_ts_ms),
            "last_close_ts_ms": int(frame.iloc[-1].close_ts_ms),
            "first_available_ts_ms": int(frame.iloc[0].available_ts_ms),
            "last_available_ts_ms": int(frame.iloc[-1].available_ts_ms),
            "minute_gap_count": len(frame.attrs.get("minute_gaps", [])),
            "incomplete_bucket_count": len(frame.attrs.get("incomplete_buckets", [])),
        }
    if inventory_hashes != {SOURCE_INVENTORY_SHA256}:
        raise Issue1377Error("SOURCE_RECEIPT_INVENTORY_DRIFT")
    if set(costs) != set(rules.PARENT_SYMBOLS) or any(
        not math.isfinite(float(value)) or float(value) <= 0 for value in costs.values()
    ):
        raise Issue1377Error("SOURCE_RECEIPT_COST_PROFILE")
    value = {
        "schema": "zel.issue1377.mr_source_receipt.v1",
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "cost_sha256": COST_SHA256,
        "timeframe_min": 30,
        "period_ms": [START_MS, END_MS],
        "warmup_start_ms": START_MS - WARMUP_MS,
        "symbols": list(rules.PARENT_SYMBOLS),
        "frames": rows,
        "costs_bps": {symbol: float(costs[symbol]) for symbol in rules.PARENT_SYMBOLS},
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "actual_historical_receipt_time": "UNAVAILABLE_NOT_INFERRED",
        "order_authority": "BLOCKED",
    }
    return {**value, "receipt_sha256": digest(value)}


def _create_single_file_ref(
    *,
    ref_name: str,
    filename: str,
    value: Mapping[str, Any],
    parent_sha: str,
    message: str,
    api: Callable[[str, str, Mapping[str, Any]], Mapping[str, Any]],
) -> str:
    if not _commit(parent_sha):
        raise Issue1377Error("PERMANENT_REF_PARENT_PROFILE")
    raw = canonical_bytes(value)
    expected_blob = _git_blob_sha(raw)
    blob = api(
        "POST",
        "/git/blobs",
        {"content": base64.b64encode(raw).decode(), "encoding": "base64"},
    )
    if blob.get("sha") != expected_blob:
        raise Issue1377Error("PERMANENT_REF_BLOB_CREATE_MISMATCH")
    tree = api(
        "POST",
        "/git/trees",
        {
            "tree": [
                {
                    "path": filename,
                    "mode": "100644",
                    "type": "blob",
                    "sha": expected_blob,
                }
            ]
        },
    )
    if not _commit(tree.get("sha")):
        raise Issue1377Error("PERMANENT_REF_TREE_CREATE")
    commit = api(
        "POST",
        "/git/commits",
        {"message": message, "tree": tree["sha"], "parents": [parent_sha]},
    )
    if not _commit(commit.get("sha")):
        raise Issue1377Error("PERMANENT_REF_COMMIT_CREATE")
    created = api("POST", "/git/refs", {"ref": ref_name, "sha": commit["sha"]})
    if created.get("ref") != ref_name or created.get("object", {}).get("sha") != commit["sha"]:
        raise Issue1377Error("PERMANENT_REF_CREATE_READBACK")
    return str(commit["sha"])


def atomic_start_v8(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
    activation_document: Mapping[str, Any],
    api: Callable[[str, str, Mapping[str, Any]], Mapping[str, Any]] = github_create,
) -> dict[str, Any]:
    activation = _workflow_activation()
    value = {
        "schema": "zel.issue1377.mr_v8_execution.v1",
        "issue": 1377,
        "state": "STARTED_NONRETRYABLE_AFTER_INPUT_VALIDATION_BEFORE_COMPUTE",
        "v8_comment_id": V8_COMMENT_ID,
        "execution_ref": V8_EXECUTION_REF,
        "reviewed_source_sha": manifest["reviewed_source_sha"],
        "manifest_sha256": manifest["manifest_sha256"],
        "source_receipt_sha256": receipt["receipt_sha256"],
        "protocol_sha256": manifest["protocol_sha256"],
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "rule_sha256": RULE_SHA256,
        "cost_sha256": COST_SHA256,
        "period_ms": [START_MS, END_MS],
        "instance_ids": list(INSTANCE_IDS),
        "economic_instances": 2,
        "activation_commit_sha": activation["github_sha"],
        "activation": activation,
        "activation_document_sha256": digest(dict(activation_document)),
        "global_heavy_group": GLOBAL_HEAVY_GROUP,
        "global_heavy_exclusive": True,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    commit_sha = _create_single_file_ref(
        ref_name=V8_EXECUTION_REF,
        filename="STARTED.json",
        value=value,
        parent_sha=manifest["reviewed_source_sha"],
        message="Issue1377 record V8 MR comparison start",
        api=api,
    )
    return {**value, "execution_commit_sha": commit_sha}


def persist_v8_result(
    result_id: str,
    value: Mapping[str, Any],
    start: Mapping[str, Any],
    api: Callable[[str, str, Mapping[str, Any]], Mapping[str, Any]] = github_create,
) -> dict[str, Any]:
    if result_id not in V8_RESULT_REFS:
        raise Issue1377Error("V8_RESULT_ID")
    envelope = {
        "schema": "zel.issue1377.mr_v8_persisted_result.v1",
        "issue": 1377,
        "result_id": result_id,
        "execution_ref": V8_EXECUTION_REF,
        "execution_commit_sha": start["execution_commit_sha"],
        "reviewed_source_sha": start["reviewed_source_sha"],
        "manifest_sha256": start["manifest_sha256"],
        "activation": start["activation"],
        "result": dict(value),
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    envelope = {**envelope, "envelope_sha256": digest(envelope)}
    commit_sha = _create_single_file_ref(
        ref_name=V8_RESULT_REFS[result_id],
        filename=result_id + ".json",
        value=envelope,
        parent_sha=start["execution_commit_sha"],
        message="Issue1377 persist V8 " + result_id,
        api=api,
    )
    return {**envelope, "result_commit_sha": commit_sha}


def _activation(claim: Mapping[str, Any]) -> dict[str, str]:
    expected = {
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "github_job": os.environ.get("GITHUB_JOB", ""),
    }
    if not all(expected.values()) or claim.get("activation") != expected:
        raise Issue1377Error("CLAIM_ACTIVATION_IDENTITY")
    if claim.get("global_heavy_active_count") != 1:
        raise Issue1377Error("GLOBAL_HEAVY_ACTIVE_COUNT")
    if claim.get("global_heavy_active_job") != expected:
        raise Issue1377Error("GLOBAL_HEAVY_ACTIVE_JOB")
    return expected


def atomic_consume_claim(
    claim: Mapping[str, Any],
    manifest: Mapping[str, Any],
    api: Callable[[str, str, Mapping[str, Any]], Mapping[str, Any]] = github_create,
) -> dict[str, Any]:
    activation = _activation(claim)
    value = {
        "schema": "zel.issue1377.mr_consumption.v1",
        "issue": 1377,
        "state": "CONSUMED_NONRETRYABLE_BEFORE_COMPUTE",
        "consumption_ref": CONSUMPTION_REF,
        "claim_ref": CLAIM_REF,
        "claim_commit_sha": claim["claim_commit_sha"],
        "manifest_sha256": manifest["manifest_sha256"],
        "reviewed_source_sha": manifest["reviewed_source_sha"],
        "instance_ids": list(INSTANCE_IDS),
        "economic_instances": 2,
        "activation": activation,
        "order_authority": "BLOCKED",
    }
    raw = canonical_bytes(value)
    expected_blob = _git_blob_sha(raw)
    blob = api(
        "POST",
        "/git/blobs",
        {"content": base64.b64encode(raw).decode(), "encoding": "base64"},
    )
    if blob.get("sha") != expected_blob:
        raise Issue1377Error("CONSUMPTION_BLOB_CREATE_MISMATCH")
    tree = api(
        "POST",
        "/git/trees",
        {
            "tree": [
                {
                    "path": "CONSUMED.json",
                    "mode": "100644",
                    "type": "blob",
                    "sha": expected_blob,
                }
            ]
        },
    )
    if not _commit(tree.get("sha")):
        raise Issue1377Error("CONSUMPTION_TREE_CREATE")
    commit = api(
        "POST",
        "/git/commits",
        {
            "message": "Issue1377 consume MR comparison claim",
            "tree": tree["sha"],
            "parents": [claim["claim_commit_sha"]],
        },
    )
    if not _commit(commit.get("sha")):
        raise Issue1377Error("CONSUMPTION_COMMIT_CREATE")
    created = api(
        "POST",
        "/git/refs",
        {"ref": CONSUMPTION_REF, "sha": commit["sha"]},
    )
    if (
        created.get("ref") != CONSUMPTION_REF
        or created.get("object", {}).get("sha") != commit["sha"]
    ):
        raise Issue1377Error("CONSUMPTION_REF_READBACK")
    return {**value, "consumption_commit_sha": commit["sha"]}




def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise Issue1377Error("JSON_OBJECT_REQUIRED:" + path.name)
    return value


def write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def protocol() -> dict[str, Any]:
    value = read_json(PROTOCOL_PATH)
    supplied = value.pop("protocol_sha256", None)
    if supplied != digest(value):
        raise Issue1377Error("PROTOCOL_HASH_MISMATCH")
    if value.get("rule_sha256") != RULE_SHA256 or value.get("cost_sha256") != COST_SHA256:
        raise Issue1377Error("PROTOCOL_RULE_OR_COST_DRIFT")
    if value.get("period_ms") != [START_MS, END_MS] or value.get("instance_ids") != list(INSTANCE_IDS):
        raise Issue1377Error("PROTOCOL_PERIOD_OR_INSTANCE_DRIFT")
    return {**value, "protocol_sha256": supplied}


def build_manifest(reviewed_source_sha: str, source_inventory_sha256: str) -> dict[str, Any]:
    if not _commit(reviewed_source_sha):
        raise Issue1377Error("REVIEWED_SOURCE_COMMIT_REQUIRED")
    if source_inventory_sha256 != SOURCE_INVENTORY_SHA256:
        raise Issue1377Error("SOURCE_INVENTORY_HASH_MISMATCH")
    p = protocol()
    value = {
        "schema": "zel.issue1377.mr_manifest.v1",
        "issue": 1377,
        "reviewed_source_sha": reviewed_source_sha,
        "protocol_sha256": p["protocol_sha256"],
        "source_inventory_sha256": source_inventory_sha256,
        "rule_sha256": RULE_SHA256,
        "cost_sha256": COST_SHA256,
        "period_ms": [START_MS, END_MS],
        "warmup_start_ms": START_MS - WARMUP_MS,
        "warmup_role": "PRICE_WARMUP_ONLY_IDENTITY_HAS_NO_FITTED_CONTEXT_PARAMETERS",
        "instance_ids": list(INSTANCE_IDS),
        "max_instances": 2,
        "parent": PARENT,
        "candidate": CANDIDATE,
        "classification": CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    return {**value, "manifest_sha256": digest(value)}


def validate_authority(
    manifest: Mapping[str, Any], approval: Mapping[str, Any], claim: Mapping[str, Any]
) -> None:
    common = {
        "issue": 1377,
        "reviewed_source_sha": manifest.get("reviewed_source_sha"),
        "manifest_sha256": manifest.get("manifest_sha256"),
        "protocol_sha256": manifest.get("protocol_sha256"),
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "rule_sha256": RULE_SHA256,
        "cost_sha256": COST_SHA256,
        "period_ms": [START_MS, END_MS],
        "instance_ids": list(INSTANCE_IDS),
        "max_instances": 2,
        "order_authority": "BLOCKED",
    }
    if approval.get("schema") != "zel.issue1377.mr_approval.v1" or approval.get("state") != "APPROVED_DEVELOPMENT_ONLY":
        raise Issue1377Error("APPROVAL_STATE")
    if approval.get("approval_ref") != APPROVAL_REF:
        raise Issue1377Error("APPROVAL_REF")
    if not _commit(approval.get("approval_commit_sha")):
        raise Issue1377Error("APPROVAL_COMMIT_IDENTITY")
    for key, expected in common.items():
        if approval.get(key) != expected:
            raise Issue1377Error("APPROVAL_BINDING:" + key)
    if claim.get("schema") != "zel.issue1377.mr_claim.v1" or claim.get("state") != "RESERVED_NONRETRYABLE":
        raise Issue1377Error("CLAIM_STATE")
    if claim.get("claim_ref") != CLAIM_REF or claim.get("economic_instances") != 2:
        raise Issue1377Error("CLAIM_REF_OR_COUNT")
    if not _commit(claim.get("claim_commit_sha")):
        raise Issue1377Error("CLAIM_COMMIT_IDENTITY")
    for key, expected in common.items():
        if claim.get(key) != expected:
            raise Issue1377Error("CLAIM_BINDING:" + key)
    if claim.get("independent_approval_commit_sha") != approval.get("approval_commit_sha"):
        raise Issue1377Error("CLAIM_APPROVAL_COMMIT_BINDING")
    if claim.get("global_heavy_group") != "a1-global-heavy-economic-evaluator-v1" or claim.get("global_heavy_exclusive") is not True:
        raise Issue1377Error("GLOBAL_HEAVY_BINDING")


def load_market(source_root: Path) -> dict[str, Any]:
    from backend.research.rebuild import scalp7_source_data_v2 as source

    if file_sha256(COST_PATH) != COST_SHA256:
        raise Issue1377Error("FROZEN_COST_FILE_DRIFT")
    frames = source.load_candles(source_root, 30, cache_dir=None)
    if set(frames) != set(rules.PARENT_SYMBOLS):
        raise Issue1377Error("SOURCE_SYMBOL_COHORT_DRIFT")
    sliced = {}
    for symbol, frame in frames.items():
        if frame.attrs.get("source_inventory_sha256") != SOURCE_INVENTORY_SHA256:
            raise Issue1377Error("SOURCE_INVENTORY_ATTRIBUTE_DRIFT")
        selected = frame[
            (frame.open_ts_ms >= START_MS - WARMUP_MS) & (frame.open_ts_ms < END_MS)
        ].copy().reset_index(drop=True)
        if selected.empty or int(selected.iloc[0].open_ts_ms) > START_MS - WARMUP_MS:
            raise Issue1377Error("SOURCE_WARMUP_NOT_COVERED")
        if int(selected.iloc[-1].close_ts_ms) != END_MS:
            raise Issue1377Error("SOURCE_END_EXCLUSIVE_NOT_COVERED")
        selected.attrs = dict(frame.attrs)
        sliced[symbol] = selected
    costs = read_json(COST_PATH)["costs_bps"]
    if set(costs) != set(rules.PARENT_SYMBOLS):
        raise Issue1377Error("COST_SYMBOL_COHORT_DRIFT")
    return {"frames": sliced, "costs": costs}


def _key(row: Mapping[str, Any]) -> tuple[str, int, str]:
    return str(row["symbol"]), int(row["signal_ts_ms"]), str(row.get("side", 0))


def _run_identity(identity: str, market: Mapping[str, Any]) -> dict[str, Any]:
    frames, costs = market["frames"], market["costs"]
    if identity == CANDIDATE:
        signals = child_rules.generate_signals(frames, identity=identity, costs_bps=costs)
        exit_update = child_rules.exit_update
    else:
        signals = rules.generate_signals(frames, identity=identity)
        exit_update = rules.exit_update
    selected = [
        row for row in signals if START_MS <= int(row["signal_ts_ms"]) < END_MS
    ]
    replay = binding.replay(
        selected, frames, costs, identity=identity, exit_update=exit_update
    )
    complete, excluded = metrics.partition_rows(replay["trades"], START_MS, END_MS)
    if excluded:
        raise Issue1377Error("ENGINE_USED_OUT_OF_WINDOW_OUTCOME")
    return {
        "identity": identity,
        "signals": selected,
        "trades": complete,
        "unresolved": replay["unresolved"],
        "rejections": replay["rejections"],
        "census": {
            "signals": len(selected),
            "completed": len(complete),
            "unresolved": len(replay["unresolved"]),
            "rejected": sum(replay["rejections"].values()),
            "rejection_reasons": replay["rejections"],
        },
        "cost_1x": metrics.summarize(complete, START_MS, END_MS, 1),
        "cost_2x": metrics.summarize(complete, START_MS, END_MS, 2),
    }


def _paired(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    parent_rows = {_key(row): row for row in parent["trades"]}
    child_rows = {_key(row): row for row in child["trades"]}
    common = sorted(set(parent_rows) & set(child_rows))
    parent_winners = {
        key for key, row in parent_rows.items() if float(row["net_bps"]) > 0
    }
    harmed = [
        key
        for key in common
        if float(parent_rows[key]["net_bps"]) > 0
        and float(child_rows[key]["net_bps"]) <= 0
    ]
    return {
        "common_completed": len(common),
        "parent_only_completed": len(set(parent_rows) - set(child_rows)),
        "candidate_only_completed": len(set(child_rows) - set(parent_rows)),
        "parent_winners": len(parent_winners),
        "parent_winners_preserved": len(parent_winners & set(child_rows)) - len(harmed),
        "parent_winners_harmed": len(harmed),
        "parent_winners_missed": len(parent_winners - set(child_rows)),
        "common_trade_net_delta_1x_bps": sum(
            float(child_rows[key]["net_bps"])
            - float(parent_rows[key]["net_bps"])
            for key in common
        ),
    }


def _paired_at_cost(
    parent: Mapping[str, Any], child: Mapping[str, Any], multiplier: int
) -> dict[str, Any]:
    parent_rows = {_key(row): row for row in parent["trades"]}
    child_rows = {_key(row): row for row in child["trades"]}
    parent_winners = {
        key
        for key, row in parent_rows.items()
        if float(row["gross_bps"]) - multiplier * float(row["cost_bps"]) > 0
    }
    child_winners = {
        key
        for key, row in child_rows.items()
        if float(row["gross_bps"]) - multiplier * float(row["cost_bps"]) > 0
    }
    common = set(parent_rows) & set(child_rows)
    return {
        "cost_multiplier": multiplier,
        "parent_winners": len(parent_winners),
        "parent_winners_preserved_positive": len(parent_winners & child_winners),
        "parent_winners_harmed_nonpositive": len((parent_winners & common) - child_winners),
        "parent_winners_missed": len(parent_winners - set(child_rows)),
        "candidate_only_winners": len(child_winners - set(parent_rows)),
    }


def comparison_from_instances(
    parent: Mapping[str, Any], child: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    value = {
        "schema": "zel.issue1377.mr_comparison_result.v1",
        "issue": 1377,
        "manifest_sha256": manifest["manifest_sha256"],
        "classification": CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "period_ms": [START_MS, END_MS],
        "instances": {"N_PARENT": parent, "N_CANDIDATE": child},
        "paired": _paired(parent, child),
        "paired_by_cost": {
            "1x": _paired_at_cost(parent, child, 1),
            "2x": _paired_at_cost(parent, child, 2),
        },
        "fresh_oos": False,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    return {**value, "result_sha256": digest(value)}


def compare(market: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Fixture convenience only; production V8 calls each model separately once."""
    return comparison_from_instances(
        _run_identity(PARENT, market),
        _run_identity(CANDIDATE, market),
        manifest,
    )


def audit_result(path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    value = read_json(path)
    supplied = value.pop("result_sha256", None)
    if supplied != digest(value):
        raise Issue1377Error("SAVED_RESULT_HASH_MISMATCH")
    expected_profile = {
        "schema": "zel.issue1377.mr_comparison_result.v1",
        "issue": 1377,
        "classification": CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "period_ms": [START_MS, END_MS],
        "fresh_oos": False,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    for key, expected in expected_profile.items():
        if value.get(key) != expected:
            raise Issue1377Error("SAVED_PROFILE_MISMATCH:" + key)
    if value.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise Issue1377Error("SAVED_MANIFEST_BINDING")
    if set(value.get("instances", {})) != set(INSTANCE_IDS):
        raise Issue1377Error("SAVED_INSTANCE_SET_MISMATCH")
    expected_identities = {"N_PARENT": PARENT, "N_CANDIDATE": CANDIDATE}
    for instance_id, instance in value["instances"].items():
        expected_identity = expected_identities[instance_id]
        if instance.get("identity") != expected_identity:
            raise Issue1377Error("SAVED_INSTANCE_IDENTITY_MISMATCH:" + instance_id)
        for collection in ("signals", "trades", "unresolved"):
            for row in instance[collection]:
                if row.get("identity") != expected_identity:
                    raise Issue1377Error(
                        "SAVED_ROW_IDENTITY_MISMATCH:"
                        + instance_id
                        + ":"
                        + collection
                    )
                nested = row.get("signal")
                if isinstance(nested, Mapping) and nested.get("identity") != expected_identity:
                    raise Issue1377Error(
                        "SAVED_NESTED_SIGNAL_IDENTITY_MISMATCH:"
                        + instance_id
                        + ":"
                        + collection
                    )
        for multiplier, name in ((1, "cost_1x"), (2, "cost_2x")):
            if metrics.summarize(instance["trades"], START_MS, END_MS, multiplier) != instance[name]:
                raise Issue1377Error("SAVED_ACCOUNTING_MISMATCH:" + name)
        census = instance["census"]
        expected_census = {
            "signals": len(instance["signals"]),
            "completed": len(instance["trades"]),
            "unresolved": len(instance["unresolved"]),
            "rejected": sum(instance["rejections"].values()),
            "rejection_reasons": instance["rejections"],
        }
        if census != expected_census:
            raise Issue1377Error("SAVED_CENSUS_MISMATCH")
    expected_paired = _paired(
        value["instances"]["N_PARENT"],
        value["instances"]["N_CANDIDATE"],
    )
    if value.get("paired") != expected_paired:
        raise Issue1377Error("SAVED_PAIRED_MISMATCH")
    expected_by_cost = {
        "1x": _paired_at_cost(
            value["instances"]["N_PARENT"], value["instances"]["N_CANDIDATE"], 1
        ),
        "2x": _paired_at_cost(
            value["instances"]["N_PARENT"], value["instances"]["N_CANDIDATE"], 2
        ),
    }
    if value.get("paired_by_cost") != expected_by_cost:
        raise Issue1377Error("SAVED_PAIRED_COST_MISMATCH")
    return {"state": "PASS_SAVED_CENSUS_AND_ACCOUNTING", "result_sha256": supplied}


def instance_result(
    instance_id: str, identity: str, market: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    instance = _run_identity(identity, market)
    value = {
        "schema": "zel.issue1377.mr_instance_result.v1",
        "issue": 1377,
        "instance_id": instance_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "classification": CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "period_ms": [START_MS, END_MS],
        "instance": instance,
        "fresh_oos": False,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    return {**value, "result_sha256": digest(value)}


def audit_instance_result(
    path: Path, instance_id: str, identity: str, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    value = read_json(path)
    supplied = value.pop("result_sha256", None)
    if supplied != digest(value):
        raise Issue1377Error("SAVED_INSTANCE_RESULT_HASH_MISMATCH")
    expected = {
        "schema": "zel.issue1377.mr_instance_result.v1",
        "issue": 1377,
        "instance_id": instance_id,
        "manifest_sha256": manifest["manifest_sha256"],
        "classification": CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "period_ms": [START_MS, END_MS],
        "fresh_oos": False,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise Issue1377Error("SAVED_INSTANCE_PROFILE_MISMATCH:" + key)
    instance = value.get("instance")
    if not isinstance(instance, Mapping) or instance.get("identity") != identity:
        raise Issue1377Error("SAVED_INSTANCE_IDENTITY_MISMATCH:" + instance_id)
    for multiplier, name in ((1, "cost_1x"), (2, "cost_2x")):
        if metrics.summarize(instance["trades"], START_MS, END_MS, multiplier) != instance[name]:
            raise Issue1377Error("SAVED_INSTANCE_ACCOUNTING_MISMATCH:" + name)
    expected_census = {
        "signals": len(instance["signals"]),
        "completed": len(instance["trades"]),
        "unresolved": len(instance["unresolved"]),
        "rejected": sum(instance["rejections"].values()),
        "rejection_reasons": instance["rejections"],
    }
    if instance.get("census") != expected_census:
        raise Issue1377Error("SAVED_INSTANCE_CENSUS_MISMATCH")
    return {"state": "PASS_SAVED_INSTANCE", "result_sha256": supplied}


def economic_table(comparison: Mapping[str, Any]) -> dict[str, Any]:
    parent = comparison["instances"]["N_PARENT"]
    child = comparison["instances"]["N_CANDIDATE"]

    def row(instance: Mapping[str, Any]) -> dict[str, Any]:
        one, two = instance["cost_1x"], instance["cost_2x"]
        return {
            "identity": instance["identity"],
            "T": one["T"],
            "T_per_day": one["T_per_day"],
            "WR_1x_pct": one["WR_pct"],
            "WR_2x_pct": two["WR_pct"],
            "Gross_bps": one["Gross_bps"],
            "Cost_1x_bps": one["Cost_bps"],
            "Cost_2x_bps": two["Cost_bps"],
            "Net_1x_bps": one["Net_bps"],
            "Net_2x_bps": two["Net_bps"],
            "Net_1x_bps_per_trade": one["NetExp_bps_T"],
            "Net_2x_bps_per_trade": two["NetExp_bps_T"],
            "Net_1x_bps_per_day": one["Net_bps"] / one["calendar_days"],
            "Net_2x_bps_per_day": two["Net_bps"] / two["calendar_days"],
            "PF_1x": one["PF"],
            "PF_2x": two["PF"],
            "DD_1x_bps": one["DD_bps"],
            "DD_2x_bps": two["DD_bps"],
            "DD_kind": one["DD_kind"],
            "MaxLossStreak_1x": one["MaxLossStreak"],
            "MaxLossStreak_2x": two["MaxLossStreak"],
            "concentration_1x": one["concentration"],
            "concentration_2x": two["concentration"],
            "signals": instance["census"]["signals"],
            "rejected_or_unfilled": instance["census"]["rejected"],
            "unresolved": instance["census"]["unresolved"],
        }

    parent_1, parent_2 = parent["cost_1x"], parent["cost_2x"]
    child_1, child_2 = child["cost_1x"], child["cost_2x"]
    keep = bool(
        child_1["T"] > 0
        and child_1["Net_bps"] > 0
        and child_2["Net_bps"] > 0
        and child_1["PF"] is not None
        and child_2["PF"] is not None
        and child_1["PF"] > 1
        and child_2["PF"] > 1
        and child_1["Net_bps"] > parent_1["Net_bps"]
        and child_2["Net_bps"] > parent_2["Net_bps"]
        and child_2["DD_bps"] <= parent_2["DD_bps"]
    )
    value = {
        "schema": "zel.issue1377.mr_economic_table.v1",
        "issue": 1377,
        "classification": CLASSIFICATION,
        "manifest_sha256": comparison["manifest_sha256"],
        "models": {"N_PARENT": row(parent), "N_CANDIDATE": row(child)},
        "paired": comparison["paired"],
        "paired_by_cost": comparison["paired_by_cost"],
        "fixed_disposition_rule": (
            "KEEP only if candidate has T>0, Net1x>0, Net2x>0, PF1x>1, PF2x>1, "
            "both Net views improve parent, and 2x realized DD does not worsen; otherwise REJECT"
        ),
        "disposition": (
            "KEEP_DEVELOPMENT_ONLY_NOT_G5_NOT_OOS"
            if keep
            else "REJECT_FROZEN_CANDIDATE"
        ),
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    return {**value, "table_sha256": digest(value)}


def execute_v8(
    output_dir: Path,
    activation_path: Path,
    source_root: Path = SOURCE_ROOT,
    *,
    create_api: Callable[
        [str, str, Mapping[str, Any]], Mapping[str, Any]
    ] = github_create,
) -> dict[str, Any]:
    head = current_head()
    manifest = build_manifest(head, SOURCE_INVENTORY_SHA256)
    activation_document = validate_v8_activation(read_json(activation_path), manifest)
    if output_dir.exists():
        raise Issue1377Error("OUTPUT_DIRECTORY_ALREADY_EXISTS_NO_RETRY")

    # V8 requires full real-source validation before consuming the one allowed
    # comparison.  load_market forms no signal and invokes neither model.
    market = load_market(source_root)
    receipt = source_receipt(market)
    start = atomic_start_v8(
        manifest, receipt, activation_document, api=create_api
    )

    output_dir.mkdir(parents=True, exist_ok=False)
    write_once(output_dir / "MANIFEST.json", manifest)
    write_once(output_dir / "SOURCE_RECEIPT.json", receipt)
    write_once(output_dir / "EXECUTION_STARTED.json", start)

    parent_result = instance_result("N_PARENT", PARENT, market, manifest)
    parent_path = output_dir / "N_PARENT.json"
    write_once(parent_path, parent_result)
    audit_instance_result(parent_path, "N_PARENT", PARENT, manifest)
    parent_persisted = persist_v8_result(
        "N_PARENT", parent_result, start, api=create_api
    )
    write_once(output_dir / "N_PARENT_PERSISTED.json", parent_persisted)

    candidate_result = instance_result("N_CANDIDATE", CANDIDATE, market, manifest)
    candidate_path = output_dir / "N_CANDIDATE.json"
    write_once(candidate_path, candidate_result)
    audit_instance_result(candidate_path, "N_CANDIDATE", CANDIDATE, manifest)
    candidate_persisted = persist_v8_result(
        "N_CANDIDATE", candidate_result, start, api=create_api
    )
    write_once(output_dir / "N_CANDIDATE_PERSISTED.json", candidate_persisted)

    comparison = comparison_from_instances(
        parent_result["instance"], candidate_result["instance"], manifest
    )
    comparison_path = output_dir / "COMPARISON.json"
    write_once(comparison_path, comparison)
    audit_result(comparison_path, manifest)
    comparison_persisted = persist_v8_result(
        "COMPARISON", comparison, start, api=create_api
    )
    write_once(output_dir / "COMPARISON_PERSISTED.json", comparison_persisted)

    table = economic_table(comparison)
    write_once(output_dir / "ECONOMIC_TABLE.json", table)
    return {
        "state": "COMPLETE_TWO_INSTANCES_PERSISTED_AND_AUDITED",
        "execution_commit_sha": start["execution_commit_sha"],
        "parent_result_sha256": parent_result["result_sha256"],
        "candidate_result_sha256": candidate_result["result_sha256"],
        "comparison_result_sha256": comparison["result_sha256"],
        "economic_table_sha256": table["table_sha256"],
        "disposition": table["disposition"],
        "economic_table": table,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--activation", type=Path, required=True)
    args = parser.parse_args()
    result = execute_v8(args.output_dir, args.activation, args.source_root)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
