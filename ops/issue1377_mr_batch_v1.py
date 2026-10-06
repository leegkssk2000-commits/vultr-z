"""Bounded parent/child development comparison for Issue 1377.

The module has no order, promotion, or retry authority.  It will not generate
an opportunity until an immutable approval and a non-retryable two-instance
claim bind the reviewed source, protocol, input inventory, rule, cost and
calendar.  Historical bars are modeled bar-close research evidence only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.research.rebuild import scalp7_metrics_v2 as metrics
from backend.research.rebuild import scalp7_mr_formation_v2 as rules
from backend.research.rebuild import scalp7_source_binding_repair_v2 as binding

ROOT = Path(__file__).resolve().parents[1]
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
CANDIDATE = rules.COST_COVERED_IDENTITY
INSTANCE_IDS = ("N_PARENT", "N_CANDIDATE")
APPROVAL_REF = "refs/heads/research-approvals/issue1377-mr-20261007-v1"
CLAIM_REF = "refs/heads/research-execution-claims/issue1377-mr-20261007-v1"
CONSUMPTION_REF = (
    "refs/heads/research-execution-consumptions/issue1377-mr-20261007-v1"
)
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
            raise Issue1377Error("CLAIM_ALREADY_CONSUMED_NO_RETRY") from None
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
    signals = rules.generate_signals(
        frames,
        identity=identity,
        costs_bps=costs if identity == CANDIDATE else None,
    )
    selected = [
        row for row in signals if START_MS <= int(row["signal_ts_ms"]) < END_MS
    ]
    replay = binding.replay(
        selected, frames, costs, identity=identity, exit_update=rules.exit_update
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


def compare(market: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    parent = _run_identity(PARENT, market)
    child = _run_identity(CANDIDATE, market)
    value = {
        "schema": "zel.issue1377.mr_comparison_result.v1",
        "issue": 1377,
        "manifest_sha256": manifest["manifest_sha256"],
        "classification": CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "period_ms": [START_MS, END_MS],
        "instances": {"N_PARENT": parent, "N_CANDIDATE": child},
        "paired": _paired(parent, child),
        "fresh_oos": False,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    return {**value, "result_sha256": digest(value)}


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
    return {"state": "PASS_SAVED_CENSUS_AND_ACCOUNTING", "result_sha256": supplied}


def execute(
    output: Path,
    source_root: Path = SOURCE_ROOT,
    *,
    api: Callable[[str, str], Mapping[str, Any]] = github,
) -> dict[str, Any]:
    head = current_head()
    manifest = build_manifest(head, SOURCE_INVENTORY_SHA256)
    approval = verified_approval(api)
    claim = verified_claim(api)
    if approval.get("reviewed_source_sha") != head:
        raise Issue1377Error("EXECUTING_CHECKOUT_NOT_REVIEWED_SOURCE")
    validate_authority(manifest, approval, claim)
    if output.exists():
        raise Issue1377Error("RESULT_ALREADY_EXISTS_NO_RETRY")
    atomic_consume_claim(claim, manifest)
    market = load_market(source_root)
    result = compare(market, manifest)
    write_once(output, result)
    audit_result(output, manifest)
    return result
