"""Bounded parent/child development comparison for Issue 1377.

The module has no order, promotion, or retry authority.  It will not generate
an opportunity until an immutable approval and a non-retryable two-instance
claim bind the reviewed source, protocol, input inventory, rule, cost and
calendar.  Historical bars are modeled bar-close research evidence only.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

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
CLASSIFICATION = "DEVELOPMENT_ONLY_ALREADY_INSPECTED_NOT_FRESH_NOT_OOS"


class Issue1377Error(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    if len(reviewed_source_sha) != 40 or any(c not in "0123456789abcdef" for c in reviewed_source_sha):
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
    for key, expected in common.items():
        if approval.get(key) != expected:
            raise Issue1377Error("APPROVAL_BINDING:" + key)
    if claim.get("schema") != "zel.issue1377.mr_claim.v1" or claim.get("state") != "RESERVED_NONRETRYABLE":
        raise Issue1377Error("CLAIM_STATE")
    if claim.get("claim_ref") != CLAIM_REF or claim.get("economic_instances") != 2:
        raise Issue1377Error("CLAIM_REF_OR_COUNT")
    for key, expected in common.items():
        if claim.get(key) != expected:
            raise Issue1377Error("CLAIM_BINDING:" + key)
    if claim.get("independent_approval_commit_sha") != approval.get("approval_commit_sha"):
        raise Issue1377Error("CLAIM_APPROVAL_COMMIT_BINDING")
    if claim.get("global_heavy_group") != "a1-global-heavy-economic-evaluator-v1" or claim.get("global_heavy_exclusive") is not True:
        raise Issue1377Error("GLOBAL_HEAVY_BINDING")


def load_market(source_root: Path, cache_dir: Path | None = None) -> dict[str, Any]:
    from backend.research.rebuild import scalp7_source_data_v2 as source

    if file_sha256(COST_PATH) != COST_SHA256:
        raise Issue1377Error("FROZEN_COST_FILE_DRIFT")
    frames = source.load_candles(source_root, 30, cache_dir=cache_dir)
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


def compare(market: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    parent = _run_identity(PARENT, market)
    child = _run_identity(CANDIDATE, market)
    p = {_key(row): row for row in parent["trades"]}
    c = {_key(row): row for row in child["trades"]}
    common = sorted(set(p) & set(c))
    parent_winners = {key for key, row in p.items() if float(row["net_bps"]) > 0}
    harmed = [
        key for key in common
        if float(p[key]["net_bps"]) > 0 and float(c[key]["net_bps"]) <= 0
    ]
    value = {
        "schema": "zel.issue1377.mr_comparison_result.v1",
        "issue": 1377,
        "manifest_sha256": manifest["manifest_sha256"],
        "classification": CLASSIFICATION,
        "clock_profile": "MODELED_BAR_CLOSE_NOT_OBSERVED_HISTORICAL_DELIVERY",
        "period_ms": [START_MS, END_MS],
        "instances": {"N_PARENT": parent, "N_CANDIDATE": child},
        "paired": {
            "common_completed": len(common),
            "parent_only_completed": len(set(p) - set(c)),
            "candidate_only_completed": len(set(c) - set(p)),
            "parent_winners": len(parent_winners),
            "parent_winners_preserved": len(parent_winners & set(c)) - len(harmed),
            "parent_winners_harmed": len(harmed),
            "parent_winners_missed": len(parent_winners - set(c)),
            "common_trade_net_delta_1x_bps": sum(float(c[k]["net_bps"]) - float(p[k]["net_bps"]) for k in common),
        },
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
    if value.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise Issue1377Error("SAVED_MANIFEST_BINDING")
    for instance in value["instances"].values():
        for multiplier, name in ((1, "cost_1x"), (2, "cost_2x")):
            if metrics.summarize(instance["trades"], START_MS, END_MS, multiplier) != instance[name]:
                raise Issue1377Error("SAVED_ACCOUNTING_MISMATCH:" + name)
        census = instance["census"]
        if census["completed"] != len(instance["trades"]) or census["unresolved"] != len(instance["unresolved"]):
            raise Issue1377Error("SAVED_CENSUS_MISMATCH")
    return {"state": "PASS_SAVED_CENSUS_AND_ACCOUNTING", "result_sha256": supplied}


def execute(
    manifest: Mapping[str, Any],
    approval: Mapping[str, Any],
    claim: Mapping[str, Any],
    market: Mapping[str, Any],
    output: Path,
) -> dict[str, Any]:
    validate_authority(manifest, approval, claim)
    if output.exists():
        raise Issue1377Error("RESULT_ALREADY_EXISTS_NO_RETRY")
    result = compare(market, manifest)
    write_once(output, result)
    audit_result(output, manifest)
    return result
