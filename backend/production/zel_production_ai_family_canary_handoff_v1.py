from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_ai_admission_executor_v1 import SCHEMA as ECONOMIC_SCHEMA, _authority_guard
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_ai_family_canary_handoff.v1"
REQUEST_SCHEMA = "zel.production_family_paper_canary_request.v1"
POLICY_SCHEMA = "zel.production_ai_family_canary_handoff_policy.v1"
CONTRACT_STATE_SCHEMA = "zel.production_ai_admission_materializer.v1"
FAMILY_EVIDENCE_POLICY_SCHEMA = "zel.production_family_paper_evidence_producer_policy.v1"
DEFAULT_POLICY = Path("config/zel_production_ai_family_canary_handoff_v1.json")
EXPECTED_CONTROLS = ["DIRECTION_REVERSAL", "PLUS_ONE_EVENT_DELAY", "NO_SIGNAL_PLACEBO"]


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_NON_PAPER_FORBIDDEN")
    for key in ("economic_result_path", "contract_state_path", "family_evidence_policy_path", "request_path", "state_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"AI_FAMILY_CANARY_HANDOFF_PATH_MISSING:{key}")
    if int(policy.get("max_requests_per_tick") or 0) not in (1, 2):
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_REQUEST_CAP_INVALID")
    _authority_guard(policy, "AI_FAMILY_CANARY_HANDOFF_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_MUTATION_FORBIDDEN")
    return dict(policy)


def _hold(state: str, reason: str, now_ms: int) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA,
        "state": state,
        "action": "hold",
        "reason": reason,
        "request_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now_ms,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def _verified_receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"AI_FAMILY_CANARY_HANDOFF_{label}_RECEIPT_INVALID")
    payload = {k: v for k, v in row.items() if k != "receipt_sha256"}
    actual = stable_sha(payload)
    if actual != claimed:
        raise RuntimeError(f"AI_FAMILY_CANARY_HANDOFF_{label}_RECEIPT_MISMATCH")
    return claimed


def _survivor_contract(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != FAMILY_EVIDENCE_POLICY_SCHEMA:
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_EVIDENCE_POLICY_SCHEMA_INVALID")
    _authority_guard(policy, "AI_FAMILY_CANARY_HANDOFF_EVIDENCE_POLICY")
    raw = policy.get("survivor_contract")
    if not isinstance(raw, Mapping):
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_SURVIVOR_CONTRACT_MISSING")
    expected = {
        "min_trades_per_window": 60,
        "min_profit_factor": 1.0,
        "min_expectancy_exclusive": 0.0,
        "min_net_pnl_exclusive": 0.0,
        "min_payoff_ratio": 1.0,
        "min_retention": 0.60,
        "max_dd_pct": 10.0,
    }
    out = dict(raw)
    for key, value in expected.items():
        if float(out.get(key)) != float(value):
            raise RuntimeError(f"AI_FAMILY_CANARY_HANDOFF_SURVIVOR_CONTRACT_DRIFT:{key}")
    if not str(out.get("source") or "").strip():
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_SURVIVOR_CONTRACT_SOURCE_MISSING")
    return out


def _contract_map(contract_state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if contract_state.get("schema_version") != CONTRACT_STATE_SCHEMA:
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_CONTRACT_STATE_SCHEMA_INVALID")
    _authority_guard(contract_state, "AI_FAMILY_CANARY_HANDOFF_CONTRACT_STATE")
    rows = contract_state.get("contracts")
    if not isinstance(rows, list):
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_CONTRACT_LIST_INVALID")
    out: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_CONTRACT_ROW_INVALID")
        cid = str(raw.get("contract_id") or "")
        if not cid or cid in out:
            raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_CONTRACT_ID_INVALID")
        _authority_guard(raw, "AI_FAMILY_CANARY_HANDOFF_CONTRACT")
        _verified_receipt(raw, "CONTRACT")
        out[cid] = dict(raw)
    return out


def handoff_tick(
    policy: Mapping[str, Any],
    *,
    economic_result: Mapping[str, Any] | None,
    contract_state: Mapping[str, Any] | None,
    family_evidence_policy: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(economic_result, Mapping):
        return _hold("HOLD_AI_FAMILY_CANARY_ECONOMIC_RESULT_MISSING", "ECONOMIC_ADMISSION_RESULT_NOT_AVAILABLE", now), None
    if economic_result.get("schema_version") != ECONOMIC_SCHEMA:
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_ECONOMIC_SCHEMA_INVALID")
    _authority_guard(economic_result, "AI_FAMILY_CANARY_HANDOFF_ECONOMIC")
    if economic_result.get("exchange_order_submitted") is not False:
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_ECONOMIC_ORDER_INVALID")
    batch_receipt = _verified_receipt(economic_result, "ECONOMIC")
    if economic_result.get("state") != "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE":
        return _hold("HOLD_AI_FAMILY_CANARY_NO_ECONOMIC_CANDIDATE", str(economic_result.get("state") or "UNKNOWN"), now), None
    if not isinstance(contract_state, Mapping) or not isinstance(family_evidence_policy, Mapping):
        return _hold("HOLD_AI_FAMILY_CANARY_LINEAGE_MISSING", "CONTRACT_OR_SURVIVOR_POLICY_NOT_AVAILABLE", now), None

    contracts = _contract_map(contract_state)
    survivor_contract = _survivor_contract(family_evidence_policy)
    results = economic_result.get("results")
    if not isinstance(results, list):
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_ECONOMIC_RESULTS_INVALID")

    requests: list[dict[str, Any]] = []
    for raw in results:
        if not isinstance(raw, Mapping) or raw.get("state") != "PASS_AI_ADMISSION_ECONOMIC_CANDIDATE":
            continue
        if raw.get("economic_candidate") is not True:
            raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_CANDIDATE_FLAG_INVALID")
        result_receipt = _verified_receipt(raw, "ECONOMIC_RESULT")
        cid = str(raw.get("contract_id") or "")
        contract = contracts.get(cid)
        if contract is None:
            raise RuntimeError(f"AI_FAMILY_CANARY_HANDOFF_CONTRACT_NOT_FOUND:{cid}")
        for key in ("family_id", "template_id"):
            if str(raw.get(key) or "") != str(contract.get(key) or ""):
                raise RuntimeError(f"AI_FAMILY_CANARY_HANDOFF_LINEAGE_MISMATCH:{key}")
        if list(contract.get("negative_controls") or []) != EXPECTED_CONTROLS:
            raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_CONTROLS_DRIFT")
        required_sources = sorted(set(map(str, contract.get("required_sources") or [])))
        if not required_sources:
            raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_REQUIRED_SOURCES_MISSING")
        contract_receipt = str(contract["receipt_sha256"])
        request_id = stable_sha({
            "economic_result_receipt_sha256": result_receipt,
            "contract_receipt_sha256": contract_receipt,
        })[:32]
        req = {
            "schema_version": REQUEST_SCHEMA,
            "state": "READY_INDEPENDENT_FAMILY_PAPER_CANARY",
            "action": "hold",
            "request_id": request_id,
            "family_id": str(contract["family_id"]),
            "contract_id": cid,
            "template_id": str(contract["template_id"]),
            "proposal_id": str(contract.get("proposal_id") or ""),
            "required_sources": required_sources,
            "outcome_source": str(contract.get("outcome_source") or ""),
            "mechanism_class": str(contract.get("mechanism_class") or ""),
            "event_anchor": str(contract.get("event_anchor") or ""),
            "direction_rule": str(contract.get("direction_rule") or ""),
            "context_rule": contract.get("context_rule"),
            "horizon_rule": str(contract.get("horizon_rule") or ""),
            "negative_controls": EXPECTED_CONTROLS,
            "execution_cost_bps": float(raw.get("execution_cost_bps")),
            "survivor_contract": survivor_contract,
            "survivor_contract_sha256": stable_sha(survivor_contract),
            "independence_contract": {
                "prospective_only": True,
                "admission_history_reuse_allowed": False,
                "not_before_ms": int(economic_result.get("updated_at_ms") or now) + 1,
                "windows": ["W1", "W2", "W3"],
            },
            "lineage": {
                "proposal_receipt_sha256": str(contract.get("proposal_receipt_sha256") or ""),
                "template_sha256": str(contract.get("template_sha256") or ""),
                "source_registry_sha256": str(contract.get("source_registry_sha256") or ""),
                "contract_receipt_sha256": contract_receipt,
                "economic_result_receipt_sha256": result_receipt,
                "economic_batch_receipt_sha256": batch_receipt,
            },
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "created_at_ms": now,
        }
        for key, value in req["lineage"].items():
            if len(str(value)) != 64:
                raise RuntimeError(f"AI_FAMILY_CANARY_HANDOFF_LINEAGE_SHA_INVALID:{key}")
        req["receipt_sha256"] = stable_sha(req)
        requests.append(req)

    if not requests:
        return _hold("HOLD_AI_FAMILY_CANARY_NO_PASSING_RESULT", "BATCH_PASS_WITHOUT_PASSING_RESULT", now), None
    if len(requests) > int(cfg["max_requests_per_tick"]):
        raise RuntimeError("AI_FAMILY_CANARY_HANDOFF_REQUEST_CAP_EXCEEDED")
    envelope = {
        "schema_version": REQUEST_SCHEMA + ".batch",
        "state": "PASS_INDEPENDENT_FAMILY_PAPER_CANARY_REQUEST_READY",
        "requests": requests,
        "request_count": len(requests),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    }
    envelope["receipt_sha256"] = stable_sha(envelope)
    state = {
        "schema_version": SCHEMA,
        "state": "PASS_AI_FAMILY_CANARY_HANDOFF_READY",
        "action": "hold",
        "request_count": len(requests),
        "request_receipt_sha256": envelope["receipt_sha256"],
        "next": "RUN_INDEPENDENT_PROSPECTIVE_FAMILY_PAPER_CANARY",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    }
    state["receipt_sha256"] = stable_sha(state)
    return state, envelope


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bridge economic candidates into independent prospective family PAPER canary requests")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    cfg = validate_policy(json.loads(ns.policy.read_text(encoding="utf-8")))
    state, request = handoff_tick(
        cfg,
        economic_result=read_json(Path(str(cfg["economic_result_path"]))),
        contract_state=read_json(Path(str(cfg["contract_state_path"]))),
        family_evidence_policy=read_json(Path(str(cfg["family_evidence_policy_path"]))),
    )
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if request is not None:
        atomic_json_write(Path(str(cfg["request_path"])), request)
    print(json.dumps({"state": state["state"], "request_count": state["request_count"], "next": state.get("next"), "receipt_sha256": state["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
