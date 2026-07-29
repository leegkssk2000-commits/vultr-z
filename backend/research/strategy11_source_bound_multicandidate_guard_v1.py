from __future__ import annotations

import copy
import re
from typing import Any, Mapping

from backend.contracts.strategy11_source_binding_contract_v1 import SAFETY, canonical_sha
from backend.research.strategy11_source_bound_multicandidate_orchestrator_v1 import (
    MulticandidateOrchestratorError,
    orchestrate as _core_orchestrate,
)

TOKEN = re.compile(r"([^.[\]]+)|\[(\d+)\]")


class MulticandidateIntegrityError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise MulticandidateIntegrityError(f"{code}:{detail}" if detail else code)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str):
        _fail("SHA256_REQUIRED", name)
    result = value.strip().lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    return value.strip()


def _resolve(groups: Mapping[str, Any], target_path: str) -> Any:
    if not isinstance(target_path, str) or not target_path:
        _fail("TARGET_PATH_REQUIRED")
    current: Any = groups
    consumed = ""
    for match in TOKEN.finditer(target_path):
        key, index = match.groups()
        if key is not None:
            consumed = f"{consumed}.{key}" if consumed else key
            if not isinstance(current, Mapping) or key not in current:
                _fail("BOUND_FIELD_TARGET_MISSING", consumed)
            current = current[key]
        else:
            consumed = f"{consumed}[{index}]"
            if not isinstance(current, list) or int(index) >= len(current):
                _fail("BOUND_FIELD_INDEX_MISSING", consumed)
            current = current[int(index)]
    return copy.deepcopy(current)


def validate_bound_package_integrity(package_value: Any, index: int) -> dict[str, Any]:
    package = _mapping(package_value, f"candidate_adapters[{index}].bound_package")
    groups = _mapping(package.get("groups"), f"candidate_adapters[{index}].groups")
    source_inventory = package.get("source_inventory")
    group_bindings = package.get("group_bindings")
    field_bindings = package.get("field_bindings")
    if not isinstance(source_inventory, list) or not source_inventory:
        _fail("SOURCE_INVENTORY_REQUIRED", str(index))
    if not isinstance(group_bindings, list) or not group_bindings:
        _fail("GROUP_BINDINGS_REQUIRED", str(index))
    if not isinstance(field_bindings, list) or not field_bindings:
        _fail("FIELD_BINDINGS_REQUIRED", str(index))
    if package.get("bound_group_count") != len(group_bindings):
        _fail("BOUND_GROUP_COUNT_MISMATCH", str(index))
    if package.get("bound_field_count") != len(field_bindings):
        _fail("BOUND_FIELD_COUNT_MISMATCH", str(index))

    inventory: dict[str, dict[str, Any]] = {}
    for row_index, raw in enumerate(source_inventory):
        row = _mapping(raw, f"source_inventory[{row_index}]")
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            _fail("SOURCE_ID_REQUIRED", f"{index}:{row_index}")
        if source_id in inventory:
            _fail("DUPLICATE_SOURCE_ID", source_id)
        _sha(row.get("artifact_sha"), f"source_inventory[{row_index}].artifact_sha")
        inventory[source_id] = row

    group_names: set[str] = set()
    for row_index, raw in enumerate(group_bindings):
        row = _mapping(raw, f"group_bindings[{row_index}]")
        group = row.get("group")
        if not isinstance(group, str) or group not in groups:
            _fail("GROUP_BINDING_TARGET_INVALID", f"{index}:{group}")
        if group in group_names:
            _fail("DUPLICATE_GROUP_BINDING", group)
        group_names.add(group)
        source_id = row.get("source_id")
        if source_id not in inventory:
            _fail("GROUP_BINDING_SOURCE_UNKNOWN", f"{group}:{source_id}")
        source = inventory[source_id]
        for field, source_field in (
            ("source_kind", "source_kind"),
            ("source_artifact", "artifact"),
            ("source_run_id", "run_id"),
            ("source_artifact_sha", "artifact_sha"),
        ):
            if row.get(field) != source.get(source_field):
                _fail("GROUP_BINDING_SOURCE_METADATA_MISMATCH", f"{group}:{field}")
        expected = canonical_sha(groups[group])
        if _sha(row.get("resolved_group_sha"), f"group_bindings[{row_index}].resolved_group_sha") != expected:
            _fail("GROUP_BINDING_SHA_MISMATCH", group)

    if group_names != set(groups):
        _fail("GROUP_BINDING_COVERAGE_MISMATCH", str(index))

    targets: set[str] = set()
    leaf_count_by_group: dict[str, int] = {group: 0 for group in groups}
    for row_index, raw in enumerate(field_bindings):
        row = _mapping(raw, f"field_bindings[{row_index}]")
        target = row.get("target_path")
        if not isinstance(target, str) or not target:
            _fail("FIELD_BINDING_TARGET_REQUIRED", f"{index}:{row_index}")
        if target in targets:
            _fail("DUPLICATE_FIELD_BINDING_TARGET", target)
        targets.add(target)
        group = target.split(".", 1)[0].split("[", 1)[0]
        if group not in groups:
            _fail("FIELD_BINDING_GROUP_UNKNOWN", target)
        source_id = row.get("source_id")
        if source_id not in inventory:
            _fail("FIELD_BINDING_SOURCE_UNKNOWN", f"{target}:{source_id}")
        source = inventory[source_id]
        for field, source_field in (
            ("source_kind", "source_kind"),
            ("source_artifact", "artifact"),
            ("source_run_id", "run_id"),
            ("source_artifact_sha", "artifact_sha"),
        ):
            if row.get(field) != source.get(source_field):
                _fail("FIELD_BINDING_SOURCE_METADATA_MISMATCH", f"{target}:{field}")
        actual = _resolve(groups, target)
        if _sha(row.get("value_sha"), f"field_bindings[{row_index}].value_sha") != canonical_sha(actual):
            _fail("FIELD_BINDING_VALUE_SHA_MISMATCH", target)
        leaf_count_by_group[group] += 1

    for row in group_bindings:
        group = row["group"]
        if row.get("leaf_binding_count") != leaf_count_by_group[group]:
            _fail("GROUP_LEAF_COUNT_MISMATCH", group)

    source_history = _mapping(package.get("source_history"), "source_history")
    binding_manifest_sha = _sha(package.get("binding_manifest_sha"), "binding_manifest_sha")
    expected_manifest_sha = canonical_sha({
        "package_id": package.get("package_id"),
        "sources": source_inventory,
        "groups": group_bindings,
        "fields": field_bindings,
        "source_history": source_history,
    })
    if binding_manifest_sha != expected_manifest_sha:
        _fail("BINDING_MANIFEST_SHA_MISMATCH", str(index))

    package_sha = _sha(package.get("package_sha"), "package_sha")
    expected_package_sha = canonical_sha({
        "groups": groups,
        "binding_manifest_sha": binding_manifest_sha,
        "authority": {**SAFETY, "runtime_bound": False},
    })
    if package_sha != expected_package_sha:
        _fail("BOUND_PACKAGE_SHA_MISMATCH", str(index))
    return {
        "package_sha": package_sha,
        "binding_manifest_sha": binding_manifest_sha,
        "verified_group_count": len(group_bindings),
        "verified_field_count": len(field_bindings),
    }


def _single(values: set[str], code: str) -> str:
    if len(values) != 1:
        _fail(code)
    return next(iter(values))


def orchestrate(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(value, "orchestrator_input")
    adapters = payload.get("candidate_adapters")
    if not isinstance(adapters, list) or not adapters:
        _fail("CANDIDATE_ADAPTERS_REQUIRED")

    integrity = []
    head_shas: set[str] = set()
    run_ids: set[str] = set()
    adapter_manifest_shas: set[str] = set()
    proposal_manifest_shas: set[str] = set()
    data_shas: set[str] = set()
    window_shas: set[str] = set()
    evidence_manifest_shas: set[str] = set()
    verified_trade_count = 0

    for index, adapter_value in enumerate(adapters):
        adapter = _mapping(adapter_value, f"candidate_adapters[{index}]")
        package = _mapping(adapter.get("bound_package"), f"candidate_adapters[{index}].bound_package")
        integrity.append(validate_bound_package_integrity(package, index))
        groups = _mapping(package.get("groups"), f"candidate_adapters[{index}].groups")
        proposal = _mapping(groups.get("proposal_core"), f"candidate_adapters[{index}].proposal_core")
        lineage = _mapping(proposal.get("lineage"), f"candidate_adapters[{index}].proposal_core.lineage")
        evidence = _mapping(groups.get("classifier_evidence"), f"candidate_adapters[{index}].classifier_evidence")
        source_ledger = _mapping(groups.get("source_ledger"), f"candidate_adapters[{index}].source_ledger")

        head_shas.add(_sha(adapter.get("source_w1_head_sha"), f"candidate_adapters[{index}].source_w1_head_sha"))
        run_ids.add(_string(adapter.get("source_w1_run_id"), f"candidate_adapters[{index}].source_w1_run_id"))
        adapter_manifest_shas.add(_sha(adapter.get("source_w1_manifest_sha"), f"candidate_adapters[{index}].source_w1_manifest_sha"))
        proposal_manifest_shas.add(_sha(lineage.get("source_manifest_sha"), f"candidate_adapters[{index}].proposal_manifest_sha"))
        data_shas.add(_sha(lineage.get("data_sha"), f"candidate_adapters[{index}].data_sha"))
        window_shas.add(_sha(lineage.get("window_sha"), f"candidate_adapters[{index}].window_sha"))
        evidence_manifest_shas.add(_sha(evidence.get("evidence_manifest_sha"), f"candidate_adapters[{index}].evidence_manifest_sha"))

        trades = source_ledger.get("trades")
        if not isinstance(trades, list) or not trades:
            _fail("SOURCE_LEDGER_TRADES_REQUIRED", str(index))
        for trade_index, trade_value in enumerate(trades):
            trade = _mapping(trade_value, f"candidate_adapters[{index}].source_ledger.trades[{trade_index}]")
            trade_data_sha = _sha(trade.get("data_sha"), f"trades[{trade_index}].data_sha")
            trade_window_sha = _sha(trade.get("window_sha"), f"trades[{trade_index}].window_sha")
            trade_manifest_sha = _sha(trade.get("manifest_sha"), f"trades[{trade_index}].manifest_sha")
            if trade_data_sha != lineage["data_sha"]:
                _fail("SOURCE_LEDGER_DATA_SHA_MISMATCH", f"{index}:{trade_index}")
            if trade_window_sha != lineage["window_sha"]:
                _fail("SOURCE_LEDGER_WINDOW_SHA_MISMATCH", f"{index}:{trade_index}")
            if trade_manifest_sha != lineage["source_manifest_sha"]:
                _fail("SOURCE_LEDGER_MANIFEST_SHA_MISMATCH", f"{index}:{trade_index}")
            verified_trade_count += 1

    shared_head_sha = _single(head_shas, "SHARED_W1_HEAD_SHA_MISMATCH")
    shared_run_id = _single(run_ids, "SHARED_W1_RUN_ID_MISMATCH")
    shared_adapter_manifest_sha = _single(adapter_manifest_shas, "SHARED_W1_MANIFEST_SHA_MISMATCH")
    shared_proposal_manifest_sha = _single(proposal_manifest_shas, "SHARED_PROPOSAL_MANIFEST_SHA_MISMATCH")
    if shared_adapter_manifest_sha != shared_proposal_manifest_sha:
        _fail("ADAPTER_PROPOSAL_MANIFEST_SHA_MISMATCH")
    shared_data_sha = _single(data_shas, "SHARED_DATA_SHA_MISMATCH")
    shared_window_sha = _single(window_shas, "SHARED_WINDOW_SHA_MISMATCH")
    shared_evidence_manifest_sha = _single(evidence_manifest_shas, "SHARED_EVIDENCE_MANIFEST_SHA_MISMATCH")

    try:
        result = _core_orchestrate(payload)
    except MulticandidateOrchestratorError:
        raise
    result = copy.deepcopy(result)
    result["bound_package_integrity_verified"] = True
    result["verified_bound_group_count"] = sum(row["verified_group_count"] for row in integrity)
    result["verified_bound_field_count"] = sum(row["verified_field_count"] for row in integrity)
    result["verified_source_trade_count"] = verified_trade_count
    result["shared_w1_head_sha"] = shared_head_sha
    result["guard_shared_lineage"] = {
        "source_w1_run_id": shared_run_id,
        "source_w1_manifest_sha": shared_adapter_manifest_sha,
        "data_sha": shared_data_sha,
        "window_sha": shared_window_sha,
        "evidence_manifest_sha": shared_evidence_manifest_sha,
    }
    result["integrity_guard_version"] = "strategy11.source_bound_multicandidate_guard.v1.1"
    result["orchestrator_sha"] = canonical_sha({key: value for key, value in result.items() if key != "orchestrator_sha"})
    return result
