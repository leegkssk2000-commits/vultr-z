from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

try:
    from bots import *  # noqa: F401,F403
    from bots.team_config import TEAM_CONFIGS
    from bots.team_manager import TeamManager
    from state.snapshot_reader import read_market_state
    try:
        from bots.shadow_bridge import emit_team_detail_shadow
    except Exception:
        emit_team_detail_shadow = None
except ImportError:
    from backend.bots import *  # noqa: F401,F403
    from backend.bots.team_config import TEAM_CONFIGS
    from backend.bots.team_manager import TeamManager
    from backend.state.snapshot_reader import read_market_state
    try:
        from backend.bots.shadow_bridge import emit_team_detail_shadow
    except Exception:
        emit_team_detail_shadow = None

router = APIRouter(prefix="/api/bots", tags=["bots"])


DEFAULTS: Dict[str, Any] = {
    "mode": "paper",
    "regime": "trend",
    "mood": "calm",
    "consensus": "high",
    "venue_health": "strong",
    "trend_score": 0.82,
    "confirm_score": 0.64,
    "breakout_score": 0.58,
    "drawdown_score": 0.31,
    "intuition_score": 78.0,
    "decay_pct": 4.0,
    "dd_day_pct": 1.2,
    "dd_total_pct": 2.4,
    "liq_buffer_pct": 18.0,
    "funding_8h_pct": 0.01,
    "stale": False,
    "stale_ms": 0,
    "freeze_mode": False,
    "session_blocked": False,
    "shadow_preferred": False,
    "reconcile_status": "ok",
    "decision_id": None,
    "contract_version": "bots.api.v1",
}


def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _merge_state_from_request(request: Request) -> tuple[str, Dict[str, Any]]:
    params = request.query_params
    state = read_market_state()

    mode = params.get("mode", DEFAULTS["mode"])

    for key, default in DEFAULTS.items():
        if key == "mode":
            continue
        if key not in params:
            state.setdefault(key, default)
            continue

        raw = params.get(key)
        if isinstance(default, bool):
            state[key] = _coerce_bool(raw)
        elif isinstance(default, float):
            try:
                state[key] = float(raw) if raw is not None else default
            except (TypeError, ValueError):
                state[key] = default
        elif isinstance(default, int) and not isinstance(default, bool):
            try:
                state[key] = int(float(raw)) if raw is not None else default
            except (TypeError, ValueError):
                state[key] = default
        else:
            state[key] = raw if raw is not None else default

    source = state.get("source") or state.get("_source")
    if source in (None, "", "None", "default"):
        source = "json:/home/z/z/backend/state.json"
    state["source"] = source
    state["_source"] = state.get("_source") or source

    source_ts = state.get("source_ts")
    if source_ts is None:
        source_ts = state.get("_source_ts")
    state["source_ts"] = source_ts
    state["_source_ts"] = state.get("_source_ts", source_ts)

    state.setdefault("stale_ms", 0)
    state.setdefault("reconcile_status", "ok")
    state.setdefault("decision_id", None)
    state.setdefault("contract_version", "bots.api.v1")
    state.setdefault("_raw", {})

    return mode, state


def _force_source_meta(payload: Dict[str, Any], market_state: Dict[str, Any], *, contract_version: str) -> Dict[str, Any]:
    out = dict(payload or {})

    if "source" not in out:
        out["source"] = market_state.get("source")
    if "source_ts" not in out:
        out["source_ts"] = market_state.get("source_ts")
    if "_source" not in out:
        out["_source"] = market_state.get("_source")
    if "_source_ts" not in out:
        out["_source_ts"] = market_state.get("_source_ts")
    if "stale" not in out:
        out["stale"] = market_state.get("stale")
    if "stale_ms" not in out:
        out["stale_ms"] = market_state.get("stale_ms")
    if "reconcile_status" not in out:
        out["reconcile_status"] = market_state.get("reconcile_status")
    if "decision_id" not in out:
        out["decision_id"] = market_state.get("decision_id")
    if "contract_version" not in out:
        out["contract_version"] = contract_version

    return out

@router.get("/teams")
def get_bot_teams(request: Request):
    mode, market_state = _merge_state_from_request(request)
    tm = TeamManager(mode=mode)
    teams = tm.list_teams(market_state)
    payload = {
        "contract_version": "bots.team_list.v1",
        "team_list": [t.model_dump() for t in teams],
        "selected": teams[0].name if teams else None,
        "mode": mode,
        "warnings": teams[0].warnings if teams else [],
        "health": teams[0].health if teams else "unknown",
        "source": market_state.get("source"),
        "source_ts": market_state.get("source_ts"),
        "_source": market_state.get("_source"),
        "_source_ts": market_state.get("_source_ts"),
        "stale": market_state.get("stale"),
        "stale_ms": market_state.get("stale_ms", 0),
        "reconcile_status": market_state.get("reconcile_status", "ok"),
        "decision_id": market_state.get("decision_id"),
    }
    return payload


@router.get("/team/{team_name}")
def get_bot_team_detail(team_name: str, request: Request):
    team_name = team_name.upper().strip()
    if team_name not in TEAM_CONFIGS:
        raise HTTPException(status_code=404, detail=f"unknown team: {team_name}")

    team_cfg = TEAM_CONFIGS[team_name]
    mode, market_state = _merge_state_from_request(request)
    tm = TeamManager(mode=mode)
    detail = tm.get_team_detail(team_name, market_state)
    payload = detail.model_dump()
    payload = _force_source_meta(payload, market_state, contract_version="bots.team_detail.v1")

    if emit_team_detail_shadow is not None:
        try:
            emit_team_detail_shadow(team_name, team_cfg, market_state, payload, decision_id=payload.get("decision_id"))
        except Exception:
            pass

    return payload
