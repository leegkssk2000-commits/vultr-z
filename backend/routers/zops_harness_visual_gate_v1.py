from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

ROOT = Path(os.environ.get("ZOPS_ROOT", "/home/z/z"))
DATA_DIR = ROOT / "data" / "harness"
REPORT_PATH = DATA_DIR / "visual_residue_latest.json"
EVENTS_PATH = DATA_DIR / "visual_residue_events.jsonl"

FORBIDDEN_PATTERNS = [
    "ledger offline",
    "replay offline",
    "WEB audit replay",
    "GATE advisory_only",
]

router = APIRouter(prefix="/api/harness", tags=["zops-harness-visual-gate-v1"])


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_mkdir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _safe_read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _safe_write_json(path: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    _safe_mkdir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(path))
        return {"ok": True, "path": str(path)}
    except Exception as e:
        # Never crash the app because harness cannot write. Return visible degraded state instead.
        fallback = Path("/tmp/zops_harness_visual_residue_latest.json")
        try:
            fallback.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            return {"ok": False, "path": str(fallback), "primary_path": str(path), "error": repr(e)}
        except Exception as e2:
            return {"ok": False, "path": None, "primary_path": str(path), "error": repr(e), "fallback_error": repr(e2)}


def _append_event(payload: Dict[str, Any]) -> None:
    _safe_mkdir(EVENTS_PATH.parent)
    row = dict(payload)
    row.setdefault("ts_ms", _now_ms())
    try:
        with EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # Event archive must never affect runtime.
        return


def _latest_report() -> Dict[str, Any]:
    report = _safe_read_json(REPORT_PATH, None)
    if not isinstance(report, dict):
        report = _safe_read_json(Path("/tmp/zops_harness_visual_residue_latest.json"), None)
    if not isinstance(report, dict):
        return {
            "status": "pending",
            "reason": "no_frontend_visual_report_yet",
            "ts_ms": _now_ms(),
            "rules": FORBIDDEN_PATTERNS,
        }
    return report


def _summarize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    failures = report.get("failures") or []
    hidden = report.get("hidden") or []
    ts_ms = int(report.get("ts_ms") or 0)
    age_ms = max(0, _now_ms() - ts_ms) if ts_ms else None
    if failures:
        status = "fail"
    elif report.get("status") in ("pass", "clean"):
        status = "pass"
    else:
        status = report.get("status") or "pending"
    return {
        "status": status,
        "age_ms": age_ms,
        "failure_count": len(failures),
        "hidden_count": len(hidden),
        "latest": report,
    }


@router.get("/health")
def harness_health() -> Dict[str, Any]:
    report = _summarize_report(_latest_report())
    return {
        "ok": True,
        "service": "zops_harness_visual_gate_v1",
        "status": report["status"],
        "ts_ms": _now_ms(),
        "rules_count": len(FORBIDDEN_PATTERNS),
        "visual": {
            "status": report["status"],
            "failure_count": report["failure_count"],
            "hidden_count": report["hidden_count"],
            "age_ms": report["age_ms"],
        },
        "contract": [
            "frontend must report visible residue scan",
            "forbidden fixed/off-canvas residues must be hidden and reported",
            "harness endpoint must return JSON, never HTML/404",
        ],
    }


@router.get("/status")
def harness_status() -> Dict[str, Any]:
    report = _summarize_report(_latest_report())
    return {
        "ok": True,
        "service": "zops_harness_visual_gate_v1",
        "status": report["status"],
        "ts_ms": _now_ms(),
        "visual": report,
        "data_dir": str(DATA_DIR),
        "report_path": str(REPORT_PATH),
    }


@router.get("/visual/rules")
def visual_rules() -> Dict[str, Any]:
    return {
        "ok": True,
        "status": "active",
        "ts_ms": _now_ms(),
        "rules": {
            "forbidden_text": FORBIDDEN_PATTERNS,
            "scope": "visible fixed/sticky/off-canvas residue outside intended app panel",
            "action": "auto-hide residue, report failure if residue is still visible after scan",
        },
    }


@router.get("/visual/latest")
def visual_latest() -> Dict[str, Any]:
    report = _summarize_report(_latest_report())
    return {
        "ok": True,
        "service": "zops_harness_visual_gate_v1",
        "ts_ms": _now_ms(),
        **report,
    }


@router.post("/visual/report")
async def visual_report(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {"raw": payload}
    except Exception:
        payload = {"raw": None, "parse_error": traceback.format_exc(limit=1)}
    payload.setdefault("ts_ms", _now_ms())
    payload.setdefault("source", "frontend_visual_gate")
    failures = payload.get("failures") or []
    payload["status"] = "fail" if (failures or payload.get("hidden")) else "pass"
    write_state = _safe_write_json(REPORT_PATH, payload)
    _append_event({"kind": "visual_report", "status": payload["status"], "failure_count": len(failures), "hidden_count": len(payload.get("hidden") or [])})
    return {
        "ok": True,
        "accepted": True,
        "status": payload["status"],
        "ts_ms": _now_ms(),
        "write": write_state,
    }


@router.post("/visual/reset")
def visual_reset() -> Dict[str, Any]:
    payload = {
        "status": "pending",
        "reason": "manual_reset",
        "failures": [],
        "hidden": [],
        "ts_ms": _now_ms(),
        "source": "backend_reset",
    }
    write_state = _safe_write_json(REPORT_PATH, payload)
    _append_event({"kind": "visual_reset", "status": "pending"})
    return {"ok": True, "status": "pending", "write": write_state, "ts_ms": _now_ms()}
