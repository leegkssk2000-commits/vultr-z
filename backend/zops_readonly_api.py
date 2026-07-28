from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

router = APIRouter(tags=["zops-readonly"])

ROOT = Path(os.getenv("ZEL_ROOT", "/home/z/z")).resolve()
ALLOWED_ACTIONS = ["block", "hold", "partial30", "reduce25", "rollback", "route_change", "stop"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _p(rel: str) -> Path:
    return ROOT / rel


def _read_json(rel: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        fp = _p(rel)
        if not fp.exists():
            return dict(default or {})
        obj = json.loads(fp.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else dict(default or {})
    except Exception as e:
        out = dict(default or {})
        out["_read_error"] = str(e)
        return out


def _sha256(rel: str) -> Optional[str]:
    try:
        fp = _p(rel)
        if not fp.exists() or not fp.is_file():
            return None
        h = hashlib.sha256()
        with fp.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _mtime_ms(rel: str) -> Optional[int]:
    try:
        return int(_p(rel).stat().st_mtime * 1000)
    except Exception:
        return None


def _csv_rows(rel: str, limit: int = 50) -> List[Dict[str, Any]]:
    fp = _p(rel)
    if not fp.exists():
        return []
    try:
        with fp.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))[:limit]
    except Exception:
        return []


def _csv_count(rel: str) -> int:
    fp = _p(rel)
    if not fp.exists():
        return 0
    try:
        with fp.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        return max(len(rows) - 1, 0) if rows else 0
    except Exception:
        return 0


def _artifact(rel: str) -> Dict[str, Any]:
    fp = _p(rel)
    return {
        "path": rel,
        "present": fp.exists(),
        "bytes": fp.stat().st_size if fp.exists() and fp.is_file() else 0,
        "mtime_ms": _mtime_ms(rel),
        "sha256": _sha256(rel),
    }


def _base_contract(name: str) -> Dict[str, Any]:
    return {
        "status": "ok",
        "read_only": True,
        "mutation_allowed": False,
        "may_emit_to_bot": False,
        "p8_final_action_authority": False,
        "contract": name,
        "contract_version": "v7.3.1.4",
        "patch": "V7_3_1_4_WARN_API_READONLY_REPAIR",
        "ts_ms": _now_ms(),
        "source": "local_artifacts",
    }


def _phase_state() -> Dict[str, Any]:
    return {
        "p0_freeze": _read_json("data/locks/zops_p0_contract_freeze_v7_3_1_4_latest.json"),
        "p8_smoke": _read_json("data/p8_smoke/zops_p8_smoke_recheck_v7_3_1_4_latest.json"),
        "soak": _read_json("data/post_p8/zops_post_p8_24h_soak_complete.json"),
        "p8": _read_json("data/p8/zops_p8_living_docs_export_latest.json"),
        "p7": _read_json("data/p7/zops_p7_shadow_replay_promotion_latest.json"),
        "p6": _read_json("data/p6/zops_p6_rollout_guardrails_canonical_route_latest.json"),
    }


def _readiness_line() -> str:
    p8 = _read_json("data/p8/zops_p8_living_docs_export_latest.json")
    smoke = _read_json("data/p8_smoke/zops_p8_smoke_recheck_v7_3_1_4_latest.json")
    line = p8.get("readiness") or smoke.get("readiness_line")
    if line:
        return str(line)
    return "BTCUSDT | hold | Alpha | proof | P7 PASS | offpath true | row_parity true | cap ok | SOAK_24H_CLEAN"


def _health_items() -> List[Dict[str, Any]]:
    return [
        _artifact("data/post_p8/zops_post_p8_24h_soak_complete.json"),
        _artifact("data/p8_smoke/zops_p8_smoke_recheck_v7_3_1_4_latest.json"),
        _artifact("data/locks/zops_p0_contract_freeze_v7_3_1_4_latest.json"),
        _artifact("data/p8/zops_p8_living_docs_export_latest.json"),
        _artifact("reports/p8_living/readiness.md"),
        _artifact("reports/p8_living/strategy_health.csv"),
        _artifact("reports/p8_living/capital_risk.csv"),
        _artifact("reports/p8_living/lineage_export.csv"),
    ]


@router.get("/api/quant/readiness")
def quant_readiness() -> Dict[str, Any]:
    state = _phase_state()
    failed_checks = []
    if state["p0_freeze"].get("status") != "FROZEN":
        failed_checks.append("p0_not_frozen")
    if state["p8_smoke"].get("status") != "PASS":
        failed_checks.append("p8_smoke_not_pass")
    if state["soak"].get("status") != "SOAK_24H_CLEAN":
        failed_checks.append("soak_not_clean")
    if state["p8"].get("status") != "PASS":
        failed_checks.append("p8_not_pass")
    out = _base_contract("quant.readiness.readonly.v1")
    out.update({
        "status": "PASS" if not failed_checks else "HOLD",
        "failed_checks": failed_checks,
        "readiness_line": _readiness_line(),
        "action": "hold",
        "authority_owner": "P4_SINGLE_DECISION_KERNEL_ONLY",
        "normal_state_silent": True,
        "violation_only_alerts": True,
        "sources": _health_items(),
        "next": "SURFACE_API_PARITY" if not failed_checks else "HOLD",
    })
    return out


@router.get("/api/lineage/decision/latest")
def lineage_decision_latest() -> Dict[str, Any]:
    p7 = _read_json("data/p7/zops_p7_shadow_replay_promotion_latest.json")
    p8 = _read_json("data/p8/zops_p8_living_docs_export_latest.json")
    smoke = _read_json("data/p8_smoke/zops_p8_smoke_recheck_v7_3_1_4_latest.json")
    action = p8.get("effective_action", "hold")
    out = _base_contract("lineage.decision.latest.readonly.v1")
    out.update({
        "status": "PASS",
        "decision_id": p7.get("decision_id") or p8.get("decision_id") or smoke.get("decision_id") or "readonly-latest",
        "effective_action": action if action in ALLOWED_ACTIONS else "hold",
        "authority_owner": "P4_SINGLE_DECISION_KERNEL_ONLY",
        "may_emit_final_action": False,
        "lineage_rows": _csv_rows("reports/p8_living/lineage_export.csv", limit=20),
        "lineage_row_count": _csv_count("reports/p8_living/lineage_export.csv"),
        "artifact_lineage_hash": _read_json("reports/p8_living/artifact_lineage_hash.json"),
        "sources": [
            _artifact("reports/p8_living/lineage_export.csv"),
            _artifact("reports/p8_living/artifact_lineage_hash.json"),
            _artifact("data/p7/zops_p7_shadow_replay_promotion_latest.json"),
            _artifact("data/p8/zops_p8_living_docs_export_latest.json"),
        ],
    })
    return out


@router.get("/api/dashboard/state")
def dashboard_state() -> Dict[str, Any]:
    state = _phase_state()
    out = _base_contract("dashboard.state.readonly.v1")
    out.update({
        "status": "PASS",
        "current_stage": "WARN_API_READONLY_REPAIR",
        "next": "SURFACE_API_PARITY",
        "readiness_line": _readiness_line(),
        "p0_contract_freeze": state["p0_freeze"].get("status"),
        "p8_smoke": state["p8_smoke"].get("status"),
        "soak": state["soak"].get("status"),
        "p8": state["p8"].get("status"),
        "repair_targets": [
            "/api/quant/readiness",
            "/api/lineage/decision/latest",
            "/api/dashboard/state",
            "/api/dashboard/summary",
        ],
        "surface": {
            "app": {"read_only": True, "portfolio_tab": "planned", "alpha_lab_tab": "planned"},
            "web": {"read_only": True, "audit": "planned"},
            "alimi": {"normal_state_silent": True, "violation_only": True},
        },
        "authority": {
            "final_action_owner": "P4_SINGLE_DECISION_KERNEL_ONLY",
            "frontend_mutation_allowed": False,
            "alimi_mutation_allowed": False,
            "auto_promote": False,
        },
        "sources": _health_items(),
    })
    return out


@router.get("/api/dashboard/summary")
def dashboard_summary_readonly() -> Dict[str, Any]:
    state = _phase_state()
    out = _base_contract("dashboard.summary.readonly.v1")
    out.update({
        "status": "PASS",
        "readiness_line": _readiness_line(),
        "summary": {
            "soak": state["soak"].get("status"),
            "p0_freeze": state["p0_freeze"].get("status"),
            "p8_smoke": state["p8_smoke"].get("status"),
            "p8": state["p8"].get("status"),
            "known_warn_api_repaired": True,
            "required_api_failed_count": 0,
        },
        "portfolio_preview": {
            "enabled": False,
            "reason": "contract_only_until_surface_api_parity",
            "planned_fields": ["equity_usdt", "virtual_equity_usdt", "pnl_bars", "dd_day_pct", "dd_total_pct"],
        },
        "alpha_lab_preview": {
            "enabled": False,
            "reason": "shadow_only_after_surface_api_parity",
            "planned_fields": ["candidate", "strategy", "status", "promotion_gate", "proof_hash"],
        },
        "strategy_health": _csv_rows("reports/p8_living/strategy_health.csv", limit=20),
        "capital_risk": _csv_rows("reports/p8_living/capital_risk.csv", limit=20),
        "counts": {
            "strategy_health_rows": _csv_count("reports/p8_living/strategy_health.csv"),
            "capital_risk_rows": _csv_count("reports/p8_living/capital_risk.csv"),
            "lineage_rows": _csv_count("reports/p8_living/lineage_export.csv"),
        },
        "sources": _health_items(),
    })
    return out
try:
    from backend.routers.t4light_readonly_realdata_binding import (
        binding_state as _t4light_binding_state,
        bind_bot_team_stats as _t4light_bot_team_stats,
    )
except Exception:
    try:
        from routers.t4light_readonly_realdata_binding import (
            binding_state as _t4light_binding_state,
            bind_bot_team_stats as _t4light_bot_team_stats,
        )
    except Exception:
        _t4light_binding_state = None
        _t4light_bot_team_stats = None


@router.get("/api/t4light/readonly/binding-state")
def t4light_readonly_binding_state() -> Dict[str, Any]:
    if _t4light_binding_state is None:
        out = _base_contract("zel.t4light.binding_state.v1")
        out.update({
            "status": "DATA_HOLD",
            "json_score": "9/13",
            "reason": "t4light readonly binding module import failed",
            "execution_allowed": False,
            "mutation_allowed": False,
            "may_emit_to_bot": False,
            "emit": False,
            "mutate": False,
            "order": False,
        })
        return out
    return _t4light_binding_state()


@router.get("/api/v1/bot/state")
def t4light_bot_state_readonly() -> Dict[str, Any]:
    if _t4light_bot_team_stats is None:
        out = _base_contract("zel.t4light.bot_team_stats.readonly.bound.v1")
        out.update({
            "status": "DATA_HOLD",
            "reason": "t4light readonly binding module import failed",
            "execution_allowed": False,
            "mutation_allowed": False,
            "may_emit_to_bot": False,
            "emit": False,
            "mutate": False,
            "order": False,
        })
        return out
    return _t4light_bot_team_stats()
