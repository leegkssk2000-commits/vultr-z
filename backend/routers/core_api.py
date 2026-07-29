from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter
from backend.contracts.change15a5_models import (
    RailStatusResponse,
    StateSummaryResponse,
    RAIL_STATUS_EXAMPLE,
    STATE_SUMMARY_EXAMPLE,
)

from backend.config import settings
from backend.contracts.null_error_contract import NULL_ERROR_CONTRACT_VERSION
from backend.engine.journal_reader import build_journal_summary
try:
    from backend.contracts.policy_resolver_ssot import resolve_policy_ssot
except Exception:
    from contracts.policy_resolver_ssot import resolve_policy_ssot

logger = logging.getLogger("z-backend")
router = APIRouter()

try:
    from backend.contracts.core_contract_validator import validate_core_contract
except Exception:
    def validate_core_contract(payload: Dict[str, Any]) -> Dict[str, Any]:
        decision_id = str(payload.get("decision_id") or "missing")
        violations: List[Dict[str, Any]] = []
        freshness = payload.get("freshness")
        if not decision_id or decision_id == "missing":
            violations.append({"rule_id": "decision_id_required", "field": "decision_id"})
        if not isinstance(freshness, dict):
            violations.append({"rule_id": "freshness_required", "field": "freshness"})
        return {
            "ok": len(violations) == 0,
            "count": len(violations),
            "violations": violations,
            "rules": ["decision_id_required", "freshness_required"],
        }

try:
    from backend.contracts.violation_logger_contract import build_violation_events
except Exception:
    def build_violation_events(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        validator = payload.get("validator") or {}
        out: List[Dict[str, Any]] = []
        for violation in validator.get("violations") or []:
            out.append(
                {
                    "decision_id": payload.get("decision_id") or "missing",
                    "backend_ver": payload.get("backend_ver") or NULL_ERROR_CONTRACT_VERSION,
                    "rule_id": violation.get("rule_id") or "unknown_rule",
                    "severity": "high",
                    "reason_code": violation.get("rule_id") or "contract_violation",
                    "path": payload.get("path") or "",
                    "details": violation,
                }
            )
        return out

try:
    from backend.engine.violation_logger import log_violation
except Exception:
    def log_violation(**kwargs: Any) -> Dict[str, Any]:
        return kwargs

HEALTH = {"ok": True}


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path_like: Any) -> Dict[str, Any]:
    try:
        path = Path(str(path_like))
        if not path.exists():
            return {}
        return _safe_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "ready"}
    return default


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _build_freshness(payload: Dict[str, Any]) -> Dict[str, Any]:
    freshness = _safe_dict(payload.get("freshness"))
    source = str(payload.get("source") or freshness.get("source") or payload.get("source_raw") or "route_status")
    source_raw = str(payload.get("source_raw") or freshness.get("source_raw") or source)
    source_ts_epoch_ms = _coerce_int(payload.get("source_ts_epoch_ms") or freshness.get("source_ts_epoch_ms") or payload.get("source_ts") or freshness.get("source_ts"))
    stale_ms = _coerce_int(payload.get("stale_ms") or freshness.get("stale_ms"), default=0)
    verification_status = str(payload.get("verification_status") or freshness.get("verification_status") or ("ready" if not _coerce_bool(payload.get("stale") or freshness.get("stale")) else "stale"))
    return {
        "source": source,
        "source_raw": source_raw,
        "source_ts": source_ts_epoch_ms,
        "source_ts_epoch_ms": source_ts_epoch_ms,
        "source_ts_iso": payload.get("source_ts_iso") or freshness.get("source_ts_iso"),
        "normalized": _coerce_bool(payload.get("normalized", freshness.get("normalized", True)), default=True),
        "stale": _coerce_bool(payload.get("stale", freshness.get("stale", False)), default=False),
        "stale_ms": stale_ms,
        "verification_status": verification_status,
    }


def _build_ack(payload: Dict[str, Any]) -> Dict[str, Any]:
    ack = _safe_dict(payload.get("ack"))
    return {
        "scope": str(ack.get("scope") or payload.get("ack_scope") or "decision_id"),
        "ttl_s": _coerce_int(ack.get("ttl_s") or payload.get("ack_ttl_s"), default=600),
        "key": str(ack.get("key") or payload.get("ack_key") or payload.get("decision_id") or f"settings:route:{getattr(settings, 'route_ts', 0)}"),
        "status": str(ack.get("status") or payload.get("ack_status") or "ready"),
    }


def _build_change_digest(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = payload.get("change_digest")
    if isinstance(raw, dict):
        sha256 = raw.get("sha256")
        source = raw.get("source")
        return {
            "sha256": str(sha256).strip() if sha256 not in (None, "") else None,
            "source": str(source).strip() if source not in (None, "") else "route_status",
        }
    if isinstance(raw, str) and raw.strip():
        return {
            "sha256": raw.strip(),
            "source": str(payload.get("change_digest_source") or payload.get("source") or payload.get("source_raw") or "route_status"),
        }

    sha256 = None
    for key in ("change_digest_sha256", "digest_sha256", "sha256"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            sha256 = value.strip()
            break

    source = None
    for key in ("change_digest_source", "source", "source_raw", "route_source"):
        value = payload.get(key)
        if value not in (None, ""):
            source = str(value).strip()
            break

    return {
        "sha256": sha256,
        "source": source or "route_status",
    }



def _coerce_state_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    raw = _safe_dict(raw)
    freshness = _build_freshness(raw)
    decision_id = str(raw.get("decision_id") or getattr(settings, "route_decision_id", "") or f"settings:route:{getattr(settings, 'route_ts', 0)}")
    ack = _safe_dict(raw.get("ack")) or _build_ack({"decision_id": decision_id, **raw})
    contracts = _safe_dict(raw.get("contracts")) or {
        "ingestion_converged_ver": str(raw.get("ingestion_converged_ver") or getattr(settings, "ingestion_converged_ver", "15B.1")),
        "schema": "15A.6",
    }
    out = {
        **raw,
        "contract_version": str(raw.get("contract_version") or "state.summary.v1"),
        "backend_ver": str(raw.get("backend_ver") or NULL_ERROR_CONTRACT_VERSION),
        "decision_id": decision_id,
        "freshness": freshness,
        "verification_status": str(raw.get("verification_status") or freshness.get("verification_status") or "ready"),
        "change_digest": _build_change_digest(raw),
        "ack": ack,
        "contracts": contracts,
        "source": str(raw.get("source") or "journal_summary"),
        "source_ts": freshness.get("source_ts", 0),
        "stale": freshness.get("stale", False),
        "stale_ms": freshness.get("stale_ms", 0),
    }
    policy_resolution = resolve_policy_ssot({
        "strategy": out.get("strategy") or out.get("favorite_strategy") or "btc_trend_v1",
        "profile": out.get("mode") or out.get("profile") or out.get("regime") or "default",
        "subtype": out.get("subtype") or out.get("method") or "default",
        "fit_tier": out.get("fit_tier") or out.get("fit") or "",
        "mood": out.get("mood") or "",
        "consensus": out.get("consensus") or out.get("watcher_consensus") or "",
        "intuition_score": out.get("intuition_score") or 0,
        "decay_pct": out.get("decay_pct") or 0,
        "venue_health": out.get("venue_health") or out.get("reconcile_status") or "",
        "stale": out.get("stale", False),
        "feature_flags": out.get("feature_flags") or [],
    })
    out.setdefault("decision_action", policy_resolution.get("decision_action"))
    out.setdefault("risk_action", policy_resolution.get("risk_action"))
    out["reason_code"] = policy_resolution.get("reason_code")
    out["policy_source"] = policy_resolution.get("policy_source")
    out["resolver_contract_version"] = policy_resolution.get("resolver_contract_version")
    out["policy_resolution"] = policy_resolution
    return out


def _log_events(events: List[Dict[str, Any]]) -> None:
    for event in events:
        try:
            log_violation(
                decision_id=str(event.get("decision_id") or "missing"),
                backend_ver=str(event.get("backend_ver") or NULL_ERROR_CONTRACT_VERSION),
                rule_id=str(event.get("rule_id") or "unknown_rule"),
                severity=str(event.get("severity") or "high"),
                reason=str(event.get("reason_code") or event.get("reason") or "contract_violation"),
                details=_safe_dict(event.get("details")),
                path=str(event.get("path") or "/api/rail-status"),
            )
        except Exception:
            logger.exception("rail-status violation logging failed")


@router.get("/api/v1/health")
def api_v1_health() -> Dict[str, bool]:
    return HEALTH


@router.get("/health")
def health() -> Dict[str, bool]:
    return HEALTH


@router.get("/api/v1/state/summary", response_model=StateSummaryResponse, openapi_extra={"examples": [STATE_SUMMARY_EXAMPLE]})
def api_v1_state_summary() -> Dict[str, Any]:
    return _coerce_state_summary(build_journal_summary())


@router.get("/state/summary", response_model=StateSummaryResponse, openapi_extra={"examples": [STATE_SUMMARY_EXAMPLE]})
def state_summary() -> Dict[str, Any]:
    return _coerce_state_summary(build_journal_summary())


@router.get("/api/rail-status", response_model=RailStatusResponse, openapi_extra={"examples": [RAIL_STATUS_EXAMPLE]})
def rail_status() -> Any:
    payload = _read_json(getattr(settings, "route_status_path", ""))
    freshness = _build_freshness(payload)
    decision_id = str(payload.get("decision_id") or getattr(settings, "route_decision_id", "") or f"settings:route:{getattr(settings, 'route_ts', 0)}")
    ack = _build_ack({**payload, "decision_id": decision_id})
    change_digest = _build_change_digest(payload)
    validator = validate_core_contract(
        {
            "decision_id": decision_id,
            "freshness": freshness,
            "change_digest": change_digest,
            "ack": ack,
        }
    )
    contracts = {
        "ingestion_converged_ver": str(payload.get("ingestion_converged_ver") or getattr(settings, "ingestion_converged_ver", "15B.1"))
    }
    events = build_violation_events(
        {
            "decision_id": decision_id,
            "backend_ver": NULL_ERROR_CONTRACT_VERSION,
            "path": "/api/rail-status",
        },
        validator,
    )
    _log_events(events)
    response = {
        "ok": True,
        "backend_ver": NULL_ERROR_CONTRACT_VERSION,
        "decision_id": decision_id,
        "freshness": freshness,
        "verification_status": freshness.get("verification_status") or "ready",
        "change_digest": change_digest,
        "hold": _coerce_bool(payload.get("hold"), default=False),
        "ack": ack,
        "contracts": contracts,
        "validator": validator,
        "synthetic_events": events,
    }
    try:
        return RailStatusResponse(**response)
    except Exception:
        return response
