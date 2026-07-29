from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["qi_absorbed_final_readonly"])

REPO_ROOT = Path(os.environ.get("Z_HOME", Path(__file__).resolve().parents[2])).resolve()
VERSION = "v7.3.1.3_QI_Absorbed_Final"
STARTED_AT = time.time()

READONLY_ALLOWED_ENDPOINTS = [
    "GET /qi/context",
    "GET /reports/p8_living",
    "GET /proof_guard/decision_authority_graph",
    "GET /api/qi/context",
    "GET /api/qi/reports/p8_living",
    "GET /api/qi/proof_guard/decision_authority_graph",
]
MUTATION_ENDPOINT_ALLOWED = False
FORBIDDEN_QI_MUTATIONS = [
    "POST /final_action",
    "PATCH /final_action",
    "POST /orders",
    "POST /promotion/apply",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _read_json(rel: str, fallback: Any) -> Any:
    path = REPO_ROOT / rel
    try:
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            if raw:
                return json.loads(raw)
    except Exception as exc:
        return {"status": "HOLD", "error": f"read_json_failed:{rel}:{exc.__class__.__name__}"}
    return fallback


def _read_csv_rows(rel: str) -> List[Dict[str, Any]]:
    path = REPO_ROOT / rel
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except Exception:
        return []


def _status_of(obj: Any, fallback: str = "UNKNOWN") -> str:
    if isinstance(obj, dict):
        val = obj.get("status")
        if isinstance(val, str) and val:
            return val
    return fallback


def _short_hash(value: Any, n: int = 12) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return value[:n]


def _thresholds() -> Dict[str, Any]:
    defaults = _read_json("ssot/defaults.json", {})
    th = defaults.get("thresholds", {}) if isinstance(defaults, dict) else {}
    keys = ["DATA_STALE_MS", "MAX_SIGNAL_AGE_MS", "MAX_SPREAD_BP", "MAX_SLIP_BP", "ALERT_BUNDLE_WINDOW_MIN"]
    return {k: th.get(k) for k in keys if isinstance(th.get(k), dict)}


def _allowed_actions() -> List[str]:
    enums = _read_json("ssot/enums.json", {})
    if isinstance(enums, dict) and isinstance(enums.get("actions"), list):
        return [str(x) for x in enums["actions"]]
    defaults = _read_json("ssot/defaults.json", {})
    if isinstance(defaults, dict) and isinstance(defaults.get("ZOS_ACTION_ENUM"), list):
        return [str(x) for x in defaults["ZOS_ACTION_ENUM"]]
    return ["reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"]


def _all_pass(items: Iterable[Any]) -> bool:
    return all(_status_of(item) in {"PASS", "PROPOSAL_ONLY"} for item in items)


def _reports_bundle() -> Dict[str, Any]:
    quant = _read_json("reports/p8_living/quant_readiness_summary.json", {})
    parity = _read_json("reports/p8_living/export_md_csv_parity.json", {})
    surface = _read_json("reports/p8_living/surface_parity_report.json", {})
    api_contract = _read_json("reports/p8_living/api_contract_report.json", {})
    promotion = _read_json("reports/p8_living/promotion_decision.json", {})
    row_count = _read_csv_rows("reports/p8_living/row_count_parity.csv")
    return {
        "quant_readiness_summary": quant,
        "export_md_csv_parity": parity,
        "surface_parity_report": surface,
        "api_contract_report": api_contract,
        "promotion_decision": promotion,
        "row_count_parity": row_count,
    }


def _proof_guard_bundle() -> Dict[str, Any]:
    return {
        "decision_authority_graph": _read_json("reports/proof_guard/decision_authority_graph.json", {}),
        "mutation_denylist_report": _read_json("reports/proof_guard/mutation_denylist_report.json", {}),
        "tca_emit_only_contract": _read_json("reports/proof_guard/tca_emit_only_contract.json", {}),
        "artifact_lineage_hash": _read_json("reports/proof_guard/artifact_lineage_hash.json", {}),
        "promotion_human_receipt_template": _read_json("reports/proof_guard/promotion_human_receipt_template.json", {}),
        "lico_decision_feed_integrity": _read_json("reports/proof_guard/lico_decision_feed_integrity.json", {}),
    }


def _context() -> Dict[str, Any]:
    reports = _reports_bundle()
    proof = _proof_guard_bundle()
    quant = reports["quant_readiness_summary"]
    surface = reports["surface_parity_report"]
    promotion = reports["promotion_decision"]
    authority = proof["decision_authority_graph"]
    mutation = proof["mutation_denylist_report"]
    lineage = proof["artifact_lineage_hash"]

    required = [
        quant,
        reports["export_md_csv_parity"],
        surface,
        reports["api_contract_report"],
        authority,
        mutation,
        proof["tca_emit_only_contract"],
        lineage,
    ]
    readonly_pass = _all_pass(required)

    final_authority = "P4_atomic_validation_gate"
    if isinstance(authority, dict):
        final_authority = str(authority.get("final_action_authority") or final_authority)

    return {
        "ok": readonly_pass,
        "version": VERSION,
        "service": "qi_absorbed_final_readonly_surface",
        "status": "PASS" if readonly_pass else "HOLD",
        "ts_ms": _now_ms(),
        "uptime_sec": round(time.time() - STARTED_AT, 3),
        "authority": {
            "qi_authority": "read_only evidence",
            "final_action_authority": final_authority,
            "p4_only_final_action": True,
            "mutation_endpoint_allowed": MUTATION_ENDPOINT_ALLOWED,
            "auto_promote": bool(promotion.get("auto_promote", False)) if isinstance(promotion, dict) else False,
            "operator_confirm_required": bool(promotion.get("operator_confirm_required", True)) if isinstance(promotion, dict) else True,
            "fail_action": str(promotion.get("fail_action", "hold")) if isinstance(promotion, dict) else "hold",
        },
        "readiness": {
            "score": quant.get("score") if isinstance(quant, dict) else None,
            "mode": quant.get("mode") if isinstance(quant, dict) else None,
            "surface_parity_smoke": surface.get("surface_parity_smoke") if isinstance(surface, dict) else None,
            "mobile_readiness_line": surface.get("mobile_readiness_line") if isinstance(surface, dict) else None,
            "row_count_parity_rows": len(reports["row_count_parity"]),
        },
        "checks": {
            "quant_readiness": _status_of(quant),
            "export_md_csv_parity": _status_of(reports["export_md_csv_parity"]),
            "surface_parity": _status_of(surface),
            "decision_authority_graph": _status_of(authority),
            "mutation_denylist": _status_of(mutation),
            "tca_emit_only": _status_of(proof["tca_emit_only_contract"]),
            "artifact_lineage_hash": _status_of(lineage),
            "promotion_decision": _status_of(promotion, "PROPOSAL_ONLY"),
            "lico_feed_integrity": _status_of(proof.get("lico_decision_feed_integrity", {})),
            "lico_action_authority": str(proof.get("lico_decision_feed_integrity", {}).get("lico_action_authority", "none")),
            "lico_p4_consumed": str(proof.get("lico_decision_feed_integrity", {}).get("p4_consumed_contract", "P4_atomic_validation_gate")),
        },
        "policy": {
            "allowed_actions": _allowed_actions(),
            "readonly_allowed_endpoints": READONLY_ALLOWED_ENDPOINTS,
            "forbidden_qi_mutations": FORBIDDEN_QI_MUTATIONS,
            "source_required": ["cf:/", "sheets:", "ssot:"],
            "thresholds": _thresholds(),
        },
        "lineage": {
            "ssot_version": lineage.get("ssot_version") if isinstance(lineage, dict) else None,
            "report_hash": lineage.get("report_hash") if isinstance(lineage, dict) else None,
            "report_hash_short": _short_hash(lineage.get("report_hash") if isinstance(lineage, dict) else ""),
            "work_matrix_csv_hash_short": _short_hash(lineage.get("work_matrix_csv_hash") if isinstance(lineage, dict) else ""),
            "work_matrix_md_hash_short": _short_hash(lineage.get("work_matrix_md_hash") if isinstance(lineage, dict) else ""),
        },
        "autotrade_effect": "none",
    }


@router.get("/qi/context", include_in_schema=False)
@router.get("/api/qi/context", include_in_schema=False)
def qi_context() -> Dict[str, Any]:
    return _context()


@router.get("/reports/p8_living", include_in_schema=False)
@router.get("/api/qi/reports/p8_living", include_in_schema=False)
def qi_p8_living_reports() -> Dict[str, Any]:
    return {"ok": True, "version": VERSION, "reports": _reports_bundle(), "autotrade_effect": "none"}


@router.get("/proof_guard/decision_authority_graph", include_in_schema=False)
@router.get("/api/qi/proof_guard/decision_authority_graph", include_in_schema=False)
def qi_decision_authority_graph() -> Dict[str, Any]:
    graph = _proof_guard_bundle()["decision_authority_graph"]
    status = _status_of(graph)
    code = 200 if status == "PASS" else 503
    return JSONResponse(status_code=code, content={"ok": status == "PASS", "version": VERSION, "decision_authority_graph": graph, "autotrade_effect": "none"})
