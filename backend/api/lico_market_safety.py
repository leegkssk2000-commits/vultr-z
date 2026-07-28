from __future__ import annotations

import copy
import os
import time
from pathlib import Path
from typing import Any, Dict, Mapping

from fastapi import APIRouter
from fastapi.responses import JSONResponse

try:
    from backend.lico_market_safety_core import evaluate_market_safety, load_json, write_json_atomic
except Exception:  # pragma: no cover
    from lico_market_safety_core import evaluate_market_safety, load_json, write_json_atomic

router = APIRouter(tags=["lico_market_safety_decision_feed"])
ROOT = Path(os.environ.get("Z_HOME", Path(__file__).resolve().parents[2])).resolve()
VERSION = "ZOPS_LICO_SOURCEBRIDGE_DEBUG_ROUTE_V10"


def _bridge_funcs():
    try:
        from backend.lico_snapshot_bridge import build_lico_input_snapshot, bridge_diagnostics
        return build_lico_input_snapshot, bridge_diagnostics, "backend.lico_snapshot_bridge"
    except Exception:  # pragma: no cover
        try:
            from lico_snapshot_bridge import build_lico_input_snapshot, bridge_diagnostics
            return build_lico_input_snapshot, bridge_diagnostics, "lico_snapshot_bridge"
        except Exception as e:
            return None, None, f"bridge_import_failed:{type(e).__name__}:{str(e)[:160]}"


def _redact_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    s = value
    # Preserve enough to debug source class while preventing accidental token leakage.
    if "url:http" in s or s.startswith("http"):
        prefix = "url:" if s.startswith("url:") else ""
        u = s[4:] if prefix else s
        try:
            from urllib.parse import urlsplit
            p = urlsplit(u)
            tail = ""
            if "output=csv" in p.query:
                tail = "?output=csv"
            return f"{prefix}{p.scheme}://{p.netloc}{p.path[:72]}...{tail}"
        except Exception:
            return prefix + u[:88] + "..."
    return s


def _redact_obj(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_redact_obj(x) for x in obj]
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in {"source_ref", "chosen_ref", "ref", "url", "cf_url", "sheets_url", "gs_url", "sheets_csv_url"}:
                out[k] = _redact_value(v)
            else:
                out[k] = _redact_obj(v)
        return out
    return _redact_value(obj)


def _candidate_snapshot() -> Dict[str, Any]:
    build_lico_input_snapshot, _diag, import_ref = _bridge_funcs()
    if build_lico_input_snapshot is not None:
        try:
            snap = build_lico_input_snapshot(ROOT)  # type: ignore[misc]
            if isinstance(snap, dict) and snap:
                snap.setdefault("_source_path", f"{import_ref}.build_lico_input_snapshot")
                return snap
        except Exception as e:
            err = f"bridge:{type(e).__name__}:{str(e)[:200]}"
        else:
            err = "empty_bridge_snapshot"
    else:
        err = str(import_ref)

    candidates = [
        ROOT / "reports" / "lico" / "source_bridge_latest_snapshot.json",
        ROOT / "data" / "fastlane" / "latest_snapshot.json",
        ROOT / "fastlane" / "latest_snapshot.json",
        ROOT / "data" / "p4" / "latest_atomic_snapshot.json",
        ROOT / "validation" / "runtime" / "latest_atomic_snapshot.json",
    ]
    for path in candidates:
        obj = load_json(path, None)
        if isinstance(obj, dict) and obj:
            try:
                obj.setdefault("_source_path", str(path.relative_to(ROOT)))
            except Exception:
                obj.setdefault("_source_path", str(path))
            obj.setdefault("_bridge_fallback_reason", err)
            return obj
    return {
        "snapshot_id": "runtime_snapshot_missing",
        "symbol": os.environ.get("ZOS_SYMBOL", "UNKNOWN"),
        "strategy": os.environ.get("ZOS_STRATEGY", "UNKNOWN"),
        "stale_state": "MISSING",
        "src_keys": [],
        "_source_path": "none",
        "_bridge_fallback_reason": err,
    }


def _payload() -> Dict[str, Any]:
    snapshot = _candidate_snapshot()
    ctx = evaluate_market_safety(snapshot, root=ROOT)
    ctx["snapshot_ref"] = snapshot.get("source_ref") or snapshot.get("_source_path", "none")
    ctx["bridge_version"] = snapshot.get("bridge_version")
    ctx["bridge_state"] = snapshot.get("bridge_state")
    ctx["bridge_reason"] = snapshot.get("bridge_reason") or snapshot.get("route_change_reason")
    ctx["bridge_candidates"] = snapshot.get("bridge_candidates", [])
    ctx["routes"] = [
        "GET /api/lico/market-safety",
        "GET /lico/market-safety",
        "GET /api/lico/decision-feed",
        "GET /lico/decision-feed",
        "GET /api/lico/source-bridge",
        "GET /lico/source-bridge",
        "GET /api/lico/source-bridge/raw",
        "GET /lico/source-bridge/raw",
    ]
    ctx["mutation_endpoint_allowed"] = False
    ctx["autotrade_effect"] = "none_until_p4_final_action"
    try:
        write_json_atomic(ROOT / "reports" / "lico" / "market_safety_context.runtime.json", ctx)
    except Exception:
        pass
    return ctx


def _source_bridge_payload(*, raw: bool = False) -> Dict[str, Any]:
    ts = int(time.time() * 1000)
    build_lico_input_snapshot, bridge_diagnostics, import_ref = _bridge_funcs()
    errors = []
    snapshot: Dict[str, Any] = {}
    diagnostics: Dict[str, Any] = {}

    if build_lico_input_snapshot is None or bridge_diagnostics is None:
        errors.append(str(import_ref))
    else:
        try:
            diagnostics = bridge_diagnostics(ROOT)  # type: ignore[misc]
        except Exception as e:
            diagnostics = {"ok": False, "error": f"diagnostics:{type(e).__name__}:{str(e)[:200]}"}
            errors.append(diagnostics["error"])
        try:
            snapshot = build_lico_input_snapshot(ROOT)  # type: ignore[misc]
        except Exception as e:
            snapshot = {"bridge_state": "HOLD", "error": f"snapshot:{type(e).__name__}:{str(e)[:200]}"}
            errors.append(snapshot["error"])

    try:
        market_ctx = evaluate_market_safety(snapshot, root=ROOT)
    except Exception as e:
        market_ctx = {"ok": False, "error": f"market:{type(e).__name__}:{str(e)[:200]}"}
        errors.append(market_ctx["error"])

    bridge_state = str(snapshot.get("bridge_state") or diagnostics.get("bridge_state") or "HOLD")
    source = snapshot.get("source") or diagnostics.get("chosen_source") or "none"
    ok = bridge_state == "PASS" and bool(snapshot.get("price") is not None and snapshot.get("pos_pct") is not None and snapshot.get("lev") is not None)

    summary = {
        "source": source,
        "symbol": snapshot.get("symbol") or diagnostics.get("symbol"),
        "strategy": snapshot.get("strategy") or diagnostics.get("strategy"),
        "bridge_state": bridge_state,
        "stale_state": snapshot.get("stale_state") or diagnostics.get("stale_state"),
        "age_ms": snapshot.get("age_ms") if snapshot.get("age_ms") is not None else diagnostics.get("age_ms"),
        "price": snapshot.get("price") if snapshot.get("price") is not None else diagnostics.get("price"),
        "pos_pct": snapshot.get("pos_pct") if snapshot.get("pos_pct") is not None else diagnostics.get("pos_pct"),
        "lev": snapshot.get("lev") if snapshot.get("lev") is not None else diagnostics.get("lev"),
        "liq_buffer_pct": snapshot.get("liq_buffer_pct") if snapshot.get("liq_buffer_pct") is not None else diagnostics.get("liq_buffer_pct"),
        "source_ref": snapshot.get("source_ref") or diagnostics.get("chosen_ref"),
        "reason": snapshot.get("bridge_reason") or snapshot.get("route_change_reason") or diagnostics.get("reason"),
        "src_keys": snapshot.get("src_keys") or diagnostics.get("src_keys", []),
        "bridge_candidates": snapshot.get("bridge_candidates") or diagnostics.get("bridge_candidates", []),
    }
    payload: Dict[str, Any] = {
        "ok": bool(ok),
        "version": VERSION,
        "component": "LICO",
        "role": "source_bridge_debug_route",
        "route_state": "PASS" if ok else "HOLD",
        "bridge_version": snapshot.get("bridge_version") or diagnostics.get("version"),
        "bridge_summary": summary,
        "market_safety_summary": {
            "ok": market_ctx.get("ok"),
            "market_safety_state": market_ctx.get("market_safety_state"),
            "integrity_state": market_ctx.get("integrity_state"),
            "score": market_ctx.get("score"),
            "recommendation": market_ctx.get("recommendation"),
            "p4_consumable": market_ctx.get("p4_consumable"),
            "veto_flags": market_ctx.get("veto_flags", []),
            "warnings": market_ctx.get("warnings", []),
            "metrics": market_ctx.get("metrics", {}),
        },
        "action_authority": "none",
        "may_emit_final_action": False,
        "mutation_endpoint_allowed": False,
        "autotrade_effect": "none_until_p4_final_action",
        "routes": [
            "GET /api/lico/source-bridge",
            "GET /lico/source-bridge",
            "GET /api/lico/source-bridge/raw",
            "GET /lico/source-bridge/raw",
            "GET /api/lico/market-safety",
        ],
        "errors": errors,
        "ts_ms": ts,
    }
    if raw:
        payload["diagnostics"] = diagnostics
        payload["snapshot"] = snapshot
        payload["market_safety_context"] = market_ctx
    else:
        payload = _redact_obj(payload)  # type: ignore[assignment]

    try:
        write_json_atomic(ROOT / "reports" / "lico" / "source_bridge_debug.runtime.json", payload)
    except Exception:
        pass
    return payload


@router.get("/api/lico/market-safety", include_in_schema=False)
@router.get("/lico/market-safety", include_in_schema=False)
def lico_market_safety() -> Dict[str, Any]:
    return _payload()


@router.get("/api/lico/decision-feed", include_in_schema=False)
@router.get("/lico/decision-feed", include_in_schema=False)
def lico_decision_feed() -> Dict[str, Any]:
    return _payload()


@router.get("/api/lico/source-bridge", include_in_schema=False)
@router.get("/lico/source-bridge", include_in_schema=False)
def lico_source_bridge_debug() -> Dict[str, Any]:
    return _source_bridge_payload(raw=False)


@router.get("/api/lico/source-bridge/raw", include_in_schema=False)
@router.get("/lico/source-bridge/raw", include_in_schema=False)
def lico_source_bridge_raw() -> Dict[str, Any]:
    return _source_bridge_payload(raw=True)


@router.get("/api/lico/source-bridge/proof", include_in_schema=False)
@router.get("/lico/source-bridge/proof", include_in_schema=False)
def lico_source_bridge_proof() -> JSONResponse:
    p = _source_bridge_payload(raw=False)
    code = 200 if p.get("ok") is True else 503
    return JSONResponse(status_code=code, content={
        "ok": p.get("ok") is True,
        "component": "LICO",
        "proof": {
            "route_state": p.get("route_state"),
            "bridge_state": p.get("bridge_summary", {}).get("bridge_state"),
            "source": p.get("bridge_summary", {}).get("source"),
            "price": p.get("bridge_summary", {}).get("price"),
            "pos_pct": p.get("bridge_summary", {}).get("pos_pct"),
            "lev": p.get("bridge_summary", {}).get("lev"),
            "action_authority": p.get("action_authority"),
            "may_emit_final_action": p.get("may_emit_final_action"),
        },
        "ts_ms": int(time.time() * 1000),
    })


@router.get("/api/lico/market-safety/proof", include_in_schema=False)
@router.get("/lico/market-safety/proof", include_in_schema=False)
def lico_market_safety_proof() -> JSONResponse:
    p = _payload()
    code = 200 if p.get("p4_consumable") is True else 503
    return JSONResponse(status_code=code, content={
        "ok": p.get("p4_consumable") is True,
        "component": "LICO",
        "proof": {
            "feed_integrity": "PASS" if p.get("p4_consumable") is True else "HOLD",
            "action_authority": p.get("action_authority"),
            "may_emit_final_action": p.get("may_emit_final_action"),
            "p4_consumed_contract": p.get("decision_feed", {}).get("consumed_by"),
            "market_safety_state": p.get("market_safety_state"),
            "recommendation": p.get("recommendation"),
            "freshness_policy": p.get("freshness_policy", {}),
        },
        "ts_ms": int(time.time() * 1000),
    })
