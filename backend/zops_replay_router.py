# ZOPS_REPLAY_API_404_INCLUDE_REPAIR_V1_ROUTER
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/api/replay", tags=["zops-replay"])
CONTRACT_VERSION = "zops-replay-api-404-repair-v1"
ROOT = Path(os.environ.get("ZOPS_REPLAY_ROOT", "/home/z/z/data/replay"))
PACK_DIR = ROOT / "packs"
EVENT_LOG = ROOT / "events.jsonl"
SEED = os.environ.get("ZOPS_REPLAY_SEED", "zops-deterministic-seed-v1")
ALLOWED_ACTIONS = {"reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"}


def _ensure() -> None:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    ROOT.mkdir(parents=True, exist_ok=True)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _decision_id(payload: Dict[str, Any]) -> str:
    raw = str(payload.get("decision_id") or payload.get("id") or "").strip()
    if raw:
        return raw[:96]
    symbol = str(payload.get("symbol") or payload.get("ticker") or "NA").upper()
    strategy = str(payload.get("strategy") or payload.get("team") or "NA")
    digest = _sha256({"seed": SEED, "payload": payload})[:16]
    return f"replay_{symbol}_{strategy}_{digest}"


def _read_events() -> list[Dict[str, Any]]:
    _ensure()
    if not EVENT_LOG.exists():
        return []
    out: list[Dict[str, Any]] = []
    for line in EVENT_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({"event": "corrupt_line", "raw": line[:500]})
    return out


def _append_event(event: Dict[str, Any]) -> None:
    _ensure()
    with EVENT_LOG.open("a", encoding="utf-8") as f:
        f.write(_canonical(event) + "\n")


def _events_for(decision_id: str) -> list[Dict[str, Any]]:
    return [e for e in _read_events() if str(e.get("decision_id")) == decision_id]


def _sample_pack(decision_id: str = "decision_sample_001") -> Dict[str, Any]:
    sample_payload = {
        "symbol": "BTCUSDT",
        "strategy": "alpha1",
        "action": "hold",
        "market_feed": {"price": 0, "pos_pct": 0, "leverage": 0, "source": "sample"},
    }
    feed_hash = _sha256(sample_payload["market_feed"])
    decision_hash = hashlib.sha256((SEED + _canonical(sample_payload)).encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "decision_id": decision_id,
        "decision_hash": decision_hash,
        "feed_hash": feed_hash,
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "deterministic": True,
        "steps": [
            {"step": 1, "name": "decision", "status": "verified"},
            {"step": 2, "name": "projection_hash", "status": "verified"},
            {"step": 3, "name": "receipt_archive", "status": "ready"},
            {"step": 4, "name": "replay_pack", "status": "ready"},
            {"step": 5, "name": "surface_parity", "status": "verified"},
        ],
    }


@router.get("/health")
def replay_health() -> Dict[str, Any]:
    _ensure()
    return {
        "ok": True,
        "service": "zops-deterministic-replay",
        "contract_version": CONTRACT_VERSION,
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "root": str(ROOT),
    }


@router.get("/status")
def replay_status() -> Dict[str, Any]:
    events = _read_events()
    decision_ids = sorted({str(e.get("decision_id")) for e in events if e.get("decision_id")})
    return {
        "ok": True,
        "service": "zops-deterministic-replay",
        "contract_version": CONTRACT_VERSION,
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "counts": {"events": len(events), "decision_ids": len(decision_ids), "packs": len(list(PACK_DIR.glob("*.json"))) if PACK_DIR.exists() else 0},
        "latest_decision_id": decision_ids[-1] if decision_ids else "decision_sample_001",
    }


@router.get("/sample")
def replay_sample() -> Dict[str, Any]:
    return _sample_pack("decision_sample_001")


@router.post("/decision")
def replay_decision(payload: Optional[Dict[str, Any]] = Body(default=None)) -> Dict[str, Any]:
    payload = payload or {}
    did = _decision_id(payload)
    action = str(payload.get("action") or "hold")
    if action not in ALLOWED_ACTIONS:
        action = "hold"
    market_feed = payload.get("market_feed") or payload.get("market") or payload.get("inputs") or {}
    event = {
        "event": "decision_recorded",
        "contract_version": CONTRACT_VERSION,
        "ts_ms": _now_ms(),
        "decision_id": did,
        "decision_hash": hashlib.sha256((SEED + _canonical(payload)).encode("utf-8")).hexdigest(),
        "feed_hash": _sha256(market_feed),
        "action": action,
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "payload": payload,
    }
    _append_event(event)
    pack_path = PACK_DIR / f"{did}.json"
    pack_path.write_text(json.dumps({"event": event, "canonical_payload": _canonical(payload)}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {"ok": True, **event, "pack_url": f"/api/replay/pack/{did}", "trace_url": f"/api/replay/trace/{did}"}


@router.post("/run")
def replay_run(payload: Optional[Dict[str, Any]] = Body(default=None)) -> Dict[str, Any]:
    payload = payload or {}
    did = _decision_id(payload)
    market_feed = payload.get("market_feed") or payload.get("market") or payload.get("inputs") or {}
    result = {
        "event": "replay_run",
        "contract_version": CONTRACT_VERSION,
        "ts_ms": _now_ms(),
        "decision_id": did,
        "feed_hash": _sha256(market_feed),
        "simulator_hash": _sha256({"seed": SEED, "decision_id": did, "feed_hash": _sha256(market_feed), "simulator": "zops-exchange-sim-v1"}),
        "authority": "advisory_only",
        "order_mutation": "blocked",
        "os_final_approval_required": True,
        "parity": "deterministic_stub_ready",
        "events_found": len(_events_for(did)),
    }
    _append_event(result)
    return {"ok": True, **result, "trace_url": f"/api/replay/trace/{did}"}


@router.get("/pack/{decision_id}")
def replay_pack(decision_id: str) -> Dict[str, Any]:
    if decision_id in {"sample", "decision_sample_001"}:
        return _sample_pack("decision_sample_001")
    pack_path = PACK_DIR / f"{decision_id}.json"
    events = _events_for(decision_id)
    if not pack_path.exists() and not events:
        raise HTTPException(status_code=404, detail={"ok": False, "error": "decision_id_not_found", "decision_id": decision_id})
    pack_file = None
    if pack_path.exists():
        try:
            pack_file = json.loads(pack_path.read_text(encoding="utf-8"))
        except Exception:
            pack_file = {"raw_path": str(pack_path)}
    return {"ok": True, "contract_version": CONTRACT_VERSION, "decision_id": decision_id, "authority": "advisory_only", "order_mutation": "blocked", "events": events, "pack_file": pack_file}


@router.get("/trace/{decision_id}")
def replay_trace(decision_id: str) -> Dict[str, Any]:
    pack = replay_pack(decision_id)
    return {
        "ok": True,
        "contract_version": CONTRACT_VERSION,
        "decision_id": decision_id,
        "trace": [
            {"step": "decision", "status": "present" if pack.get("events") else "sample_or_pack"},
            {"step": "projection_hash", "status": "ready"},
            {"step": "receipt_archive", "status": "ready"},
            {"step": "deterministic_replay", "status": "ready"},
            {"step": "os_approval", "status": "required"},
        ],
        "pack": pack,
    }
