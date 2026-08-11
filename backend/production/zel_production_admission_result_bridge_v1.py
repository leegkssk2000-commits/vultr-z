from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SOURCE_SCHEMA = "zel.squeeze_break.150d_admission.v1"
EVIDENCE_SCHEMA = "zel.production_bootstrap_admission_evidence.v1"
BRIDGE_SCHEMA = "zel.production_admission_result_bridge.v1"
STRATEGY_ID = "squeeze_break"
EXPECTED_OWNER_SHA256 = "c22b4016601ce37fc28999ca7690804c92d3f04997b4d01f06775aa49837ed38"


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        raise RuntimeError("ADMISSION_BRIDGE_INPUT_NOT_OBJECT")
    return row


def validate_source(row: Mapping[str, Any]) -> None:
    if row.get("schema_version") != SOURCE_SCHEMA:
        raise RuntimeError("ADMISSION_BRIDGE_SOURCE_SCHEMA_INVALID")
    if str(row.get("strategy_id") or "") != STRATEGY_ID:
        raise RuntimeError("ADMISSION_BRIDGE_STRATEGY_INVALID")
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError("ADMISSION_BRIDGE_SOURCE_AUTHORITY_INVALID")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError("ADMISSION_BRIDGE_SOURCE_EXECUTION_INVALID")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("ADMISSION_BRIDGE_SOURCE_LIVE_INVALID")
    source = row.get("source_binding")
    if not isinstance(source, Mapping):
        raise RuntimeError("ADMISSION_BRIDGE_SOURCE_BINDING_MISSING")
    if source.get("expected_owner_sha256") != EXPECTED_OWNER_SHA256:
        raise RuntimeError("ADMISSION_BRIDGE_EXPECTED_OWNER_SHA_INVALID")
    if source.get("owner_sha256_before") != EXPECTED_OWNER_SHA256 or source.get("owner_sha256_after") != EXPECTED_OWNER_SHA256:
        raise RuntimeError("ADMISSION_BRIDGE_OWNER_SHA_MISMATCH")
    if source.get("source_unchanged") is not True:
        raise RuntimeError("ADMISSION_BRIDGE_SOURCE_CHANGED")
    for key in ("strategy_parameter_changes", "feature_gate_changes", "side_filter_changes"):
        if int(source.get(key) or 0) != 0:
            raise RuntimeError(f"ADMISSION_BRIDGE_MUTATION_DETECTED:{key}")
    integrity = row.get("integrity")
    if not isinstance(integrity, Mapping):
        raise RuntimeError("ADMISSION_BRIDGE_INTEGRITY_MISSING")
    if integrity.get("integrity_ok") is not True:
        raise RuntimeError("ADMISSION_BRIDGE_INTEGRITY_NOT_PASS")
    if int(integrity.get("duplicate_trade_identity_count") or 0) != 0:
        raise RuntimeError("ADMISSION_BRIDGE_DUPLICATE_FAIL")
    funding = row.get("funding")
    if not isinstance(funding, Mapping) or funding.get("complete_for_scoring") is not True:
        raise RuntimeError("ADMISSION_BRIDGE_FUNDING_NOT_COMPLETE")
    receipt = str(row.get("receipt_sha256") or "").strip()
    if not receipt:
        raise RuntimeError("ADMISSION_BRIDGE_SOURCE_RECEIPT_MISSING")
    material = dict(row)
    material.pop("receipt_sha256", None)
    if stable_sha(material) != receipt:
        raise RuntimeError("ADMISSION_BRIDGE_SOURCE_RECEIPT_MISMATCH")


def _reject_evidence(source: Mapping[str, Any]) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA,
        "state": "REJECT_BOOTSTRAP_ADMISSION_EVIDENCE",
        "strategy_id": STRATEGY_ID,
        "source_schema_version": source.get("schema_version"),
        "source_receipt_sha256": source.get("receipt_sha256"),
        "reason": "PRODUCTION_W1_W2_W3_DURABILITY_NOT_ALL_POSITIVE_AFTER_COSTS",
        "integrity": {
            "error_count": 0,
            "duplicate_count": 0,
            "censored_count": 0,
        },
        "production_window_gates": dict(source.get("production_window_gates") or {}),
        "aggregate_metrics_source": dict(source.get("aggregate") or {}).get("production_symbols"),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "action": "route_change",
        "next": "ROUTE_CHANGE_TO_NEXT_SOURCE_READY_ECONOMIC_FAMILY",
    }
    evidence["receipt_sha256"] = stable_sha(evidence)
    return evidence


def bridge(source: Mapping[str, Any]) -> dict[str, Any]:
    validate_source(source)
    state = str(source.get("state") or "")
    if state == "REJECT_SQUEEZE150_PRODUCTION_DURABILITY":
        evidence = _reject_evidence(source)
        out: dict[str, Any] = {
            "schema_version": BRIDGE_SCHEMA,
            "state": "PASS_TERMINAL_REJECT_EVIDENCE_READY",
            "strategy_id": STRATEGY_ID,
            "write_admission_evidence": True,
            "admission_evidence": evidence,
            "source_receipt_sha256": source.get("receipt_sha256"),
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "route_change",
        }
    elif state == "HOLD_SQUEEZE150_ECONOMIC_PASS_AUTHORITY_GATES_PENDING":
        gates = source.get("bootstrap_authority_gates")
        if not isinstance(gates, Mapping):
            raise RuntimeError("ADMISSION_BRIDGE_AUTHORITY_GATES_MISSING")
        if any(gates.get(k) is not False for k in ("risk_request_bound", "dd_pct_bound", "retention_semantics_bound", "bootstrap_pass_evidence_emitted")):
            raise RuntimeError("ADMISSION_BRIDGE_UNEXPECTED_AUTHORITY_STATE")
        out = {
            "schema_version": BRIDGE_SCHEMA,
            "state": "HOLD_ECONOMIC_PASS_AUTHORITY_BINDING_REQUIRED",
            "strategy_id": STRATEGY_ID,
            "write_admission_evidence": False,
            "admission_evidence": None,
            "missing_authority": ["risk_request", "dd_pct", "retention_semantics"],
            "source_receipt_sha256": source.get("receipt_sha256"),
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
    else:
        out = {
            "schema_version": BRIDGE_SCHEMA,
            "state": "HOLD_SOURCE_NOT_TERMINAL_FOR_BRIDGE",
            "strategy_id": STRATEGY_ID,
            "source_state": state,
            "write_admission_evidence": False,
            "admission_evidence": None,
            "source_receipt_sha256": source.get("receipt_sha256"),
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        }
    out["receipt_sha256"] = stable_sha(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--evidence-out", type=Path)
    ns = ap.parse_args()
    result = bridge(load(ns.source))
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    if result["write_admission_evidence"]:
        if ns.evidence_out is None:
            raise RuntimeError("ADMISSION_BRIDGE_EVIDENCE_OUT_REQUIRED")
        ns.evidence_out.parent.mkdir(parents=True, exist_ok=True)
        ns.evidence_out.write_text(json.dumps(result["admission_evidence"], indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "write_admission_evidence": result["write_admission_evidence"],
        "action": result["action"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
