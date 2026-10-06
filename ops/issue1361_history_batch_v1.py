"""One-shot H1->H3 retrospective batch for the frozen Issue 1361 pair.

This driver has no order or promotion authority.  It refuses to form test
signals until an externally published permanent claim binds the reviewed fit
manifest and all six instance identities.  Historical availability is the
explicit modeled bar-close profile, never reconstructed receipt time.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ops import issue1361_history_v1 as prep
from ops import issue1361_repeatability_v1 as scope

ROOT = Path(__file__).resolve().parents[1]
CLAIM_REF = prep.HISTORY_CLAIM_REF
APPROVAL_REF = "refs/heads/research-approvals/issue1361-history-20261006-v1"
SCHEMA = "zel.issue1361.history_batch.v1"
RESULT_SCHEMA = "zel.issue1361.history_instance_result.v1"
IDENTITY_MODEL = {
    prep.CANDIDATE: "EMA21_BUY_LIMIT",
    prep.PARENT: "SQUEEZE_PARENT",
}


class HistoryBatchError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise HistoryBatchError("JSON_OBJECT_REQUIRED:" + path.name)
    return value


def write_once(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _commit(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def github(method: str, route: str) -> dict[str, Any]:
    if method != "GET" or not route.startswith("/"):
        raise HistoryBatchError("READ_ONLY_RELATIVE_GITHUB_API_REQUIRED")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise HistoryBatchError("GITHUB_TOKEN_REQUIRED")
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
                raise HistoryBatchError("GITHUB_REDIRECT_REJECTED")
            value = json.load(response)
    except HTTPError as exc:
        raise HistoryBatchError("GITHUB_GET_HTTP_" + str(exc.code)) from None
    if not isinstance(value, dict):
        raise HistoryBatchError("GITHUB_OBJECT_REQUIRED")
    return value


def _git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def verified_claim(api: Callable[[str, str], Mapping[str, Any]] = github) -> dict[str, Any]:
    """Read the claim only from the fixed authenticated permanent Git ref."""
    route = "/git/ref/" + CLAIM_REF.removeprefix("refs/")
    ref = api("GET", route)
    commit_sha = ref.get("object", {}).get("sha")
    if ref.get("ref") != CLAIM_REF or ref.get("object", {}).get("type") != "commit" or not _commit(commit_sha):
        raise HistoryBatchError("CLAIM_REF_PROFILE")
    commit = api("GET", "/git/commits/" + commit_sha)
    tree_sha = commit.get("tree", {}).get("sha")
    if not isinstance(tree_sha, str) or commit.get("parents"):
        raise HistoryBatchError("CLAIM_COMMIT_PROFILE")
    tree = api("GET", "/git/trees/" + tree_sha)
    entries = tree.get("tree", [])
    if len(entries) != 1 or entries[0].get("path") != "CLAIM.json" or entries[0].get("type") != "blob":
        raise HistoryBatchError("CLAIM_TREE_PROFILE")
    blob = api("GET", "/git/blobs/" + entries[0]["sha"])
    if blob.get("encoding") != "base64":
        raise HistoryBatchError("CLAIM_BLOB_ENCODING")
    raw = base64.b64decode(blob.get("content", ""), validate=False)
    if _git_blob_sha(raw) != entries[0]["sha"]:
        raise HistoryBatchError("CLAIM_BLOB_HASH")
    value = json.loads(raw)
    if not isinstance(value, dict) or "claim_commit_sha" in value:
        raise HistoryBatchError("CLAIM_CONTENT_PROFILE")
    return {**value, "claim_commit_sha": commit_sha}


def _verified_single_file_ref(
    ref_name: str,
    filename: str,
    api: Callable[[str, str], Mapping[str, Any]],
) -> tuple[dict[str, Any], str]:
    ref = api("GET", "/git/ref/" + ref_name.removeprefix("refs/"))
    commit_sha = ref.get("object", {}).get("sha")
    if ref.get("ref") != ref_name or ref.get("object", {}).get("type") != "commit" or not _commit(commit_sha):
        raise HistoryBatchError("APPROVAL_REF_PROFILE")
    commit = api("GET", "/git/commits/" + commit_sha)
    tree_sha = commit.get("tree", {}).get("sha")
    if not isinstance(tree_sha, str) or commit.get("parents"):
        raise HistoryBatchError("APPROVAL_COMMIT_PROFILE")
    tree = api("GET", "/git/trees/" + tree_sha)
    entries = tree.get("tree", [])
    if len(entries) != 1 or entries[0].get("path") != filename or entries[0].get("type") != "blob":
        raise HistoryBatchError("APPROVAL_TREE_PROFILE")
    blob = api("GET", "/git/blobs/" + entries[0]["sha"])
    if blob.get("encoding") != "base64":
        raise HistoryBatchError("APPROVAL_BLOB_ENCODING")
    raw = base64.b64decode(blob.get("content", ""), validate=False)
    if _git_blob_sha(raw) != entries[0]["sha"]:
        raise HistoryBatchError("APPROVAL_BLOB_HASH")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise HistoryBatchError("APPROVAL_CONTENT_PROFILE")
    return value, commit_sha


def verified_approval(api: Callable[[str, str], Mapping[str, Any]] = github) -> dict[str, Any]:
    value, commit_sha = _verified_single_file_ref(APPROVAL_REF, "APPROVED.json", api)
    return {**value, "approval_commit_sha": commit_sha}


def validate_approval(approval: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    instances = sorted(x["instance_id"] for x in manifest.get("instances", []))
    required = {
        "schema": "zel.issue1361.history_approval.v1",
        "issue": 1361,
        "state": "APPROVED_RETROSPECTIVE_H_ONLY",
        "approval_ref": APPROVAL_REF,
        "classification": scope.CLASSIFICATION,
        "manifest_sha256": manifest.get("manifest_sha256"),
        "source_inventory_sha256": scope.SOURCE_INVENTORY_SHA256,
        "protocol_sha256": scope.PROTOCOL_SHA256,
        "rule_sha256": scope.RULE_SHA256,
        "cost_sha256": scope.COST_SHA256,
        "runtime_sha256": manifest.get("runtime_sha256"),
        "trusted_fit_sha256": {row["id"]: row["fit"]["sha256"] for row in manifest.get("fits", [])},
        "trusted_coverage_sha256": manifest.get("coverage_sha256"),
        "instance_ids": instances,
        "max_instances": 6,
        "order_authority": "BLOCKED",
    }
    for key, expected in required.items():
        if approval.get(key) != expected:
            raise HistoryBatchError("APPROVAL_BINDING_MISMATCH:" + key)
    if not _commit(approval.get("approval_commit_sha")) or not _commit(approval.get("reviewed_source_sha")):
        raise HistoryBatchError("APPROVAL_COMMIT_IDENTITY")
    if not isinstance(approval.get("fit_artifact_id"), int) or approval["fit_artifact_id"] <= 0:
        raise HistoryBatchError("APPROVAL_ARTIFACT_ID")
    digest = approval.get("fit_artifact_digest")
    receipt = approval.get("fit_receipt_sha256")
    if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
        raise HistoryBatchError("APPROVAL_ARTIFACT_DIGEST")
    if not isinstance(receipt, str) or len(receipt) != 64:
        raise HistoryBatchError("APPROVAL_RECEIPT_HASH")
    return dict(approval)


def validate_claim(
    claim: Mapping[str, Any],
    manifest: Mapping[str, Any],
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    validate_approval(approval, manifest)
    expected_instances = sorted(x["instance_id"] for x in manifest.get("instances", []))
    required = {
        "schema": "zel.issue1361.history_claim.v1",
        "issue": 1361,
        "state": "RESERVED_NONRETRYABLE",
        "claim_ref": CLAIM_REF,
        "manifest_sha256": manifest.get("manifest_sha256"),
        "source_inventory_sha256": scope.SOURCE_INVENTORY_SHA256,
        "protocol_sha256": scope.PROTOCOL_SHA256,
        "rule_sha256": scope.RULE_SHA256,
        "cost_sha256": scope.COST_SHA256,
        "instance_ids": expected_instances,
        "max_instances": 6,
        "economic_instances": 6,
        "global_heavy_group": "a1-global-heavy-economic-evaluator-v1",
        "global_heavy_exclusive": True,
        "order_authority": "BLOCKED",
    }
    for key in (
        "reviewed_source_sha",
        "fit_artifact_id",
        "fit_artifact_digest",
        "fit_receipt_sha256",
        "runtime_sha256",
    ):
        required[key] = approval.get(key)
    for key, expected in required.items():
        if claim.get(key) != expected:
            raise HistoryBatchError("CLAIM_BINDING_MISMATCH:" + key)
    if not _commit(claim.get("claim_commit_sha")) or claim.get(
        "independent_approval_commit_sha"
    ) != approval.get("approval_commit_sha"):
        raise HistoryBatchError("CLAIM_OR_APPROVAL_COMMIT_IDENTITY")
    fits = claim.get("trusted_fit_sha256")
    coverage = claim.get("trusted_coverage_sha256")
    if not isinstance(fits, Mapping) or not isinstance(coverage, str):
        raise HistoryBatchError("CLAIM_TRUST_ANCHORS_REQUIRED")
    prep.validate_manifest(
        manifest,
        trusted_fit_sha256=fits,
        trusted_coverage_sha256=coverage,
    )
    prep.validate_runtime()
    return dict(claim)


def _modeled_minutes(frame: Any) -> list[list[Any]]:
    rows = []
    for row in frame.itertuples():
        stamp = int(row.timestamp_ms)
        rows.append(
            [
                stamp,
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(row.volume),
                stamp + 60_000,
            ]
        )
    return rows


def prepare_market(source_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    from backend.research.rebuild import scalp7_rolling_context_v2 as context
    from backend.research.rebuild import scalp7_source_data_v2 as source

    inventory = scope.inventory_source(source_root)
    if inventory.get("history_input_state") != "READY":
        raise HistoryBatchError("SOURCE_INVENTORY_NOT_READY")
    if prep.time_witness_bundle_sha256() != prep.TIME_WITNESS_BUNDLE_SHA256:
        raise HistoryBatchError("TIME_WITNESS_BUNDLE_HASH_MISMATCH")
    minutes_frame = source._load_verified_minutes(source_root)
    frames = {symbol: source.aggregate_minutes(minutes_frame[symbol], 30) for symbol in scope.SYMBOLS}
    features = context.cross_features(frames)
    windows = [prep.fit_window(row) for row in scope.planned_history()]
    bound, fits = context.bind_context(frames, features, windows)
    recorded = [row["fit"] for row in manifest["fits"]]
    if fits != recorded:
        raise HistoryBatchError("SOURCE_RECOMPUTED_FIT_MISMATCH")
    minutes = {symbol: _modeled_minutes(minutes_frame[symbol]) for symbol in scope.SYMBOLS}
    clocks = {
        symbol: {int(row.open_ts_ms): int(row.close_ts_ms) for row in frame.itertuples()}
        for symbol, frame in bound.items()
    }
    return {"frames": bound, "minutes": minutes, "clocks": clocks, "fits": fits}


def run_instance(
    *,
    identity: str,
    fold: Mapping[str, Any],
    market: Mapping[str, Any],
    costs: Mapping[str, float],
) -> dict[str, Any]:
    from backend.research.rebuild import scalp7_execution_v2 as parent_engine
    from backend.research.rebuild import scalp7_metrics_v2 as metrics
    from backend.research.rebuild import scalp7_positive_lanes_v2 as rules
    from ops import issue1358_ema21_limit_v1 as candidate_engine
    from ops import scalp7_clocked_execution_v1 as clock

    signals = rules.generate_signals(
        market["frames"], costs=costs, identities=(prep.PARENT,)
    )
    selected = [
        signal
        for signal in signals
        if fold["test_start_ms"] <= int(signal["signal_open_ts_ms"])
        and int(signal["signal_ts_ms"]) < fold["test_end_ms"]
    ]
    if identity == prep.PARENT:
        replay = parent_engine.replay(
            selected,
            market["frames"],
            costs,
            exit_update=rules.exit_update,
            identity=prep.PARENT,
            entry_update=rules.entry_update,
        )
        census = {
            "signals": replay["signal_count"],
            "completed": replay["closed_trade_count"],
            "unresolved": len(replay["unresolved"]),
            "rejections": replay["rejections"],
        }
    elif identity == prep.CANDIDATE:
        ready = clock.prefix_clocks(market["clocks"])
        replay = candidate_engine.replay(
            selected,
            market["frames"],
            market["minutes"],
            ready,
            costs,
            rules.entry_update,
            rules.exit_update,
        )
        census = {
            "signals": len(selected),
            "completed": len(replay["trades"]),
            "unresolved": len(replay["unresolved"]),
            "status_counts": replay["status_counts"],
        }
    else:
        raise HistoryBatchError("UNKNOWN_INSTANCE_IDENTITY")
    start, end = int(fold["test_start_ms"]), int(fold["test_end_ms"])
    result = {
        "schema": RESULT_SCHEMA,
        "fold_id": fold["id"],
        "identity": identity,
        "model": IDENTITY_MODEL[identity],
        "classification": scope.CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "cost_1x": metrics.summarize(replay["trades"], start, end, 1),
        "cost_2x": metrics.summarize(replay["trades"], start, end, 2),
        "census": census,
        "trades": replay["trades"],
        "unresolved": replay["unresolved"],
        "order_authority": "BLOCKED",
        "fresh_oos": False,
    }
    result["result_sha256"] = sha256(result)
    return result


def audit_saved_result(path: Path) -> dict[str, Any]:
    from backend.research.rebuild import scalp7_metrics_v2 as metrics

    value = read_json(path)
    supplied = value.pop("result_sha256", None)
    if supplied != sha256(value):
        raise HistoryBatchError("SAVED_RESULT_HASH_MISMATCH")
    fold = next(row for row in scope.planned_history() if row["id"] == value["fold_id"])
    for multiplier, key in ((1, "cost_1x"), (2, "cost_2x")):
        rebuilt = metrics.summarize(
            value["trades"], fold["test_start_ms"], fold["test_end_ms"], multiplier
        )
        if rebuilt != value[key]:
            raise HistoryBatchError("SAVED_ACCOUNTING_MISMATCH:" + key)
    return {"result_sha256": supplied, "state": "PASS_SAVED_RESULT_AND_ACCOUNTING"}


def execute_batch(
    source_root: Path,
    manifest_path: Path,
    output: Path,
    *,
    claim_loader: Callable[[], Mapping[str, Any]] = verified_claim,
    approval_loader: Callable[[], Mapping[str, Any]] = verified_approval,
    market_loader: Callable[[Path, Mapping[str, Any]], Mapping[str, Any]] = prepare_market,
    instance_runner: Callable[..., dict[str, Any]] = run_instance,
) -> dict[str, Any]:
    manifest, claim, approval = read_json(manifest_path), dict(claim_loader()), dict(approval_loader())
    validate_claim(claim, manifest, approval)
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "STARTED.json", {"schema": SCHEMA, "claim_commit_sha": claim["claim_commit_sha"]})
    market = market_loader(source_root, manifest)
    completed = []
    for fold in scope.planned_history():
        for identity in (prep.PARENT, prep.CANDIDATE):
            instance_id = fold["id"] + ":" + IDENTITY_MODEL[identity]
            if instance_id not in claim["instance_ids"]:
                raise HistoryBatchError("INSTANCE_NOT_CLAIMED:" + instance_id)
            result = instance_runner(
                identity=identity, fold=fold, market=market, costs=manifest["costs_bps"]
            )
            path = output / fold["id"] / IDENTITY_MODEL[identity] / "RESULT.json"
            write_once(path, result)
            audit = audit_saved_result(path)
            write_once(path.with_name("AUDIT.json"), audit)
            completed.append({"instance_id": instance_id, **audit})
    summary = {
        "schema": SCHEMA,
        "state": "COMPLETE_SIX_RETROSPECTIVE_INSTANCES",
        "classification": scope.CLASSIFICATION,
        "claim_commit_sha": claim["claim_commit_sha"],
        "manifest_sha256": manifest["manifest_sha256"],
        "completed_instances": completed,
        "economic_instances": len(completed),
        "fresh_oos": False,
        "order_authority": "BLOCKED",
        "promotion": False,
    }
    summary["summary_sha256"] = sha256(summary)
    write_once(output / "SUMMARY.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute_batch(args.source_root, args.manifest, args.output)
    print(json.dumps({"state": result["state"], "summary_sha256": result["summary_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
