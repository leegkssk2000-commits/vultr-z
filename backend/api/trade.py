from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Request

try:
    from backend.contracts.change15a5_models import TradeContextResponse, TRADE_CONTEXT_EXAMPLE
except Exception:
    try:
        from contracts.change15a5_models import TradeContextResponse, TRADE_CONTEXT_EXAMPLE
    except Exception:
        TradeContextResponse = dict  # type: ignore
        TRADE_CONTEXT_EXAMPLE = {}

try:
    from state.trade_state import read_trade_state
except ImportError:
    from backend.state.trade_state import read_trade_state

try:
    from engine.change12_projection import build_delta_feed, build_projection
except ImportError:
    from backend.engine.change12_projection import build_delta_feed, build_projection

try:
    from state.snapshot_reader import read_current_state
except Exception:
    try:
        from state.snapshot_reader import read_market_state as read_current_state
    except Exception:
        try:
            from backend.state.snapshot_reader import read_current_state
        except Exception:
            from backend.state.snapshot_reader import read_market_state as read_current_state

try:
    from backend.contracts.policy_resolver_ssot import resolve_policy_ssot
except Exception:
    from contracts.policy_resolver_ssot import resolve_policy_ssot

router = APIRouter(prefix="/api/trade", tags=["trade"])

CONTRACT_VERSION = "trade.read_bridge.v3"
TRADE_CONTEXT_CONTRACT_VERSION = "trade.context.v3"


def _dictish(v: Any, fallback_key: str = "value") -> Dict[str, Any]:
    return v if isinstance(v, dict) else ({fallback_key: v} if v is not None else {})


def _json_num(v: Any) -> float | None:
    try:
        return None if v in (None, "", "None") else float(v)
    except Exception:
        return None


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _safe_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, tuple):
        return list(v)
    return [v]


def _first_non_empty(*values: Any) -> Any:
    for v in values:
        if v not in (None, "", "None"):
            return v
    return None


def _safe_import_strategy_modules() -> List[Any]:
    modules: List[Any] = []
    candidates = [
        "backend.engine.strategy_registry",
        "engine.strategy_registry",
        "backend.engine.read_only_strategy_lookup_bridge",
        "engine.read_only_strategy_lookup_bridge",
    ]
    for name in candidates:
        try:
            module = __import__(name, fromlist=["*"])
            modules.append(module)
        except Exception:
            continue
    return modules


def _call_lookup(module: Any, strategy_key: str, profile: str | None, runtime: Dict[str, Any]) -> Dict[str, Any] | None:
    lookup_fns = [
        "lookup_strategy",
        "get_strategy",
        "resolve_strategy",
        "read_only_strategy_lookup_bridge",
    ]
    for fn_name in lookup_fns:
        fn = getattr(module, fn_name, None)
        if fn is None:
            continue
        for args in (
            {"strategy_key": strategy_key, "profile": profile, "runtime": runtime},
            {"strategy": strategy_key, "profile": profile, "runtime": runtime},
            {"key": strategy_key, "profile": profile},
            {"strategy_key": strategy_key, "profile": profile},
        ):
            try:
                result = fn(**args)
                if isinstance(result, dict):
                    return result
            except TypeError:
                continue
            except Exception:
                return {"lookup_error": f"{module.__name__}.{fn_name}"}
    snapshot = getattr(module, "registry_snapshot", None)
    if callable(snapshot):
        try:
            result = snapshot()
            if isinstance(result, dict):
                bucket = result.get(strategy_key)
                if isinstance(bucket, dict):
                    return bucket
        except Exception:
            return {"lookup_error": f"{module.__name__}.registry_snapshot"}
    return None


def _merge_runtime(request: Request) -> Dict[str, Any]:
    params = request.query_params
    trade = read_trade_state() or {}
    market = read_current_state() or {}
    runtime_state: Dict[str, Any] = {}
    runtime_state.update(market)
    runtime_state.update(trade)
    projection = build_projection(runtime_state) or {}
    delta = build_delta_feed(runtime_state, persist=False)

    source = _first_non_empty(
        trade.get("source"), trade.get("_source"),
        market.get("source"), market.get("_source"),
        "json:/home/z/z/backend/trade_state.json",
    )
    source_ts = _first_non_empty(
        projection.get("source_ts"),
        trade.get("source_ts"), trade.get("_source_ts"),
        market.get("source_ts"), market.get("_source_ts"),
    )
    decision_id = _first_non_empty(
        trade.get("decision_id"),
        market.get("decision_id"),
        projection.get("decision_id"),
    )

    return {
        "mode": params.get("mode", projection.get("trust_rail", {}).get("mode", market.get("mode", "paper"))),
        "contract_version": CONTRACT_VERSION,
        "source": source,
        "source_ts": source_ts,
        "stale": _safe_bool(_first_non_empty(trade.get("stale"), market.get("stale"), False)),
        "stale_ms": projection.get("stale_ms", trade.get("stale_ms", 0)),
        "reconcile_status": projection.get("reconcile_status", trade.get("reconcile_status", "ok")),
        "decision_id": decision_id,
        "projection": projection,
        "delta": delta,
        "trade": trade,
        "market": market,
    }


def _contract_freshness(rt: Dict[str, Any]) -> Dict[str, Any]:
    source = rt.get("source")
    source_ts = rt.get("source_ts") or 0
    return {
        "source": source,
        "source_raw": source,
        "source_ts": source_ts,
        "source_ts_epoch_ms": source_ts,
        "source_ts_iso": None,
        "normalized": True,
        "stale": bool(rt.get("stale", False)),
        "stale_ms": rt.get("stale_ms") or 0,
        "verification_status": "stale" if rt.get("stale") else "ready",
    }


def _contract_ack(decision_id: Any) -> Dict[str, Any]:
    did = str(decision_id or "trade:context:0")
    return {"scope": "decision_id", "ttl_s": 600, "key": did, "status": "ready"}


def _execution_chain(rt: Dict[str, Any], policy_resolution: Dict[str, Any], strategy_registry: Dict[str, Any]) -> Dict[str, Any]:
    trade = rt["trade"]
    market = rt["market"]
    projection = rt["projection"]
    return {
        "mode": rt.get("mode"),
        "route": market.get("route"),
        "route_reason": market.get("route_reason"),
        "reconcile_status": rt.get("reconcile_status"),
        "bot_health": market.get("bot_health", market.get("health")),
        "venue_health": market.get("venue_health"),
        "policy_source": policy_resolution.get("policy_source"),
        "decision_action": policy_resolution.get("decision_action"),
        "risk_action": policy_resolution.get("risk_action"),
        "live_execution_enabled": _safe_bool(
            _first_non_empty(
                trade.get("live_execution_enabled"),
                market.get("live_execution_enabled"),
                projection.get("live_execution_enabled"),
                False,
            )
        ),
        "authority": _first_non_empty(
            trade.get("execution_authority"),
            market.get("execution_authority"),
            projection.get("execution_authority"),
            "shadow",
        ),
        "strategy_key": strategy_registry.get("strategy_key"),
        "strategy_lookup_status": strategy_registry.get("lookup_status"),
    }


def _counterfactual(rt: Dict[str, Any], policy_resolution: Dict[str, Any], strategy_key: str | None) -> Dict[str, Any]:
    trade = rt["trade"]
    market = rt["market"]
    projection = rt["projection"]
    decision_sheet = projection.get("decision_sheet") if isinstance(projection.get("decision_sheet"), dict) else {}
    live_allowed = _safe_bool(
        _first_non_empty(
            trade.get("live_execution_enabled"),
            market.get("live_execution_enabled"),
            projection.get("live_execution_enabled"),
            False,
        )
    )
    alt_action = "hold"
    alt_reason = "default"
    if live_allowed and not rt.get("stale"):
        alt_action = policy_resolution.get("decision_action") or "hold"
        alt_reason = "policy_resolver"
    elif rt.get("stale"):
        alt_reason = "stale_guard"
    elif rt.get("reconcile_status") not in (None, "", "ok", "ready"):
        alt_reason = "reconcile_guard"
    return {
        "actual_action": policy_resolution.get("decision_action"),
        "actual_risk_action": policy_resolution.get("risk_action"),
        "alt_action_if_live_ready": alt_action,
        "alt_reason": alt_reason,
        "strategy": _first_non_empty(
            strategy_key,
            market.get("strategy"),
            trade.get("strategy"),
            decision_sheet.get("strategy"),
        ),
        "profile": _first_non_empty(market.get("profile"), rt.get("mode")),
    }


def _resolve_strategy_registry(rt: Dict[str, Any], policy_resolution: Dict[str, Any]) -> Dict[str, Any]:
    trade = rt["trade"]
    market = rt["market"]
    projection = rt["projection"]
    decision_sheet = projection.get("decision_sheet") if isinstance(projection.get("decision_sheet"), dict) else {}
    strategy_key = _first_non_empty(
        market.get("strategy"),
        trade.get("strategy"),
        decision_sheet.get("strategy"),
        policy_resolution.get("strategy"),
        "btc_trend_v1",
    )
    profile = _first_non_empty(
        market.get("profile"),
        trade.get("profile"),
        decision_sheet.get("profile"),
        rt.get("mode"),
        "paper",
    )
    runtime = {
        "strategy": strategy_key,
        "profile": profile,
        "mode": rt.get("mode"),
        "decision_id": rt.get("decision_id"),
    }
    lookup_payload: Dict[str, Any] = {}
    source = "runtime_default"
    lookup_status = "runtime_only"
    for module in _safe_import_strategy_modules():
        result = _call_lookup(module, str(strategy_key), str(profile) if profile is not None else None, runtime)
        if isinstance(result, dict) and result:
            lookup_payload = result
            source = module.__name__
            lookup_status = "bridge_ready" if "lookup_error" not in result else "bridge_error"
            break

    enabled = _safe_bool(_first_non_empty(
        lookup_payload.get("enabled") if isinstance(lookup_payload, dict) else None,
        trade.get("strategy_enabled"),
        market.get("strategy_enabled"),
        True,
    ), True)
    return {
        "read_only": True,
        "strategy_key": strategy_key,
        "profile": profile,
        "lookup_status": lookup_status,
        "enabled": enabled,
        "family": _first_non_empty(
            lookup_payload.get("family") if isinstance(lookup_payload, dict) else None,
            trade.get("strategy_family"),
            market.get("strategy_family"),
        ),
        "deploy_stage": _first_non_empty(
            lookup_payload.get("deploy_stage") if isinstance(lookup_payload, dict) else None,
            lookup_payload.get("stage") if isinstance(lookup_payload, dict) else None,
            trade.get("deploy_stage"),
            market.get("deploy_stage"),
            rt.get("mode"),
        ),
        "bot_id": _first_non_empty(
            lookup_payload.get("bot_id") if isinstance(lookup_payload, dict) else None,
            trade.get("bot_id"),
            market.get("bot_id"),
        ),
        "allowed_bot_ids": _safe_list(_first_non_empty(
            lookup_payload.get("allowed_bot_ids") if isinstance(lookup_payload, dict) else None,
            trade.get("allowed_bot_ids"),
            market.get("allowed_bot_ids"),
        )),
        "strategy_spec_version": _first_non_empty(
            lookup_payload.get("strategy_spec_version") if isinstance(lookup_payload, dict) else None,
            lookup_payload.get("spec_version") if isinstance(lookup_payload, dict) else None,
            trade.get("strategy_spec_version"),
            market.get("strategy_spec_version"),
        ),
        "source": source,
        "lookup_payload": lookup_payload,
    }


def _recovery_path(rt: Dict[str, Any], policy_resolution: Dict[str, Any], strategy_registry: Dict[str, Any]) -> Dict[str, Any]:
    blockers: List[str] = []
    steps: List[str] = []
    if rt.get("stale"):
        blockers.append("freshness_stale")
        steps.append("refresh trade_state source_ts")
    if (rt.get("reconcile_status") or "").lower() not in {"", "ok", "ready"}:
        blockers.append("reconcile_not_ready")
        steps.append("clear reconcile drift before live route")
    if (policy_resolution.get("reason_code") or "").upper() not in {"", "OK"}:
        blockers.append(f"reason_code:{policy_resolution.get('reason_code')}")
        steps.append("resolve policy blocker")
    if strategy_registry.get("lookup_status") == "bridge_error":
        blockers.append("strategy_registry_bridge_error")
        steps.append("repair strategy_registry read-only bridge")
    if not blockers:
        steps.append("state ready; keep envelope stable")
        if strategy_registry.get("lookup_status") != "bridge_ready":
            steps.append("optional: wire strategy_registry read-only bridge")
    return {
        "status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "next_steps": steps,
    }


def _alert_ladder(rt: Dict[str, Any], policy_resolution: Dict[str, Any]) -> Dict[str, Any]:
    severity = "info"
    if rt.get("stale"):
        severity = "warning"
    if (policy_resolution.get("reason_code") or "").upper() not in {"", "OK"}:
        severity = "warning"
    if _json_num(rt["trade"].get("liq_buffer_pct")) is not None and (_json_num(rt["trade"].get("liq_buffer_pct")) or 0) <= 5:
        severity = "critical"
    return {
        "severity": severity,
        "reason_code": policy_resolution.get("reason_code"),
        "decision_action": policy_resolution.get("decision_action"),
        "risk_action": policy_resolution.get("risk_action"),
    }




def _policy_resolution(rt: Dict[str, Any]) -> Dict[str, Any]:
    trade = rt["trade"]
    market = rt["market"]
    projection = rt["projection"]
    decision_sheet = projection.get("decision_sheet") if isinstance(projection.get("decision_sheet"), dict) else {}
    return resolve_policy_ssot({
        "strategy": market.get("strategy") or trade.get("strategy") or decision_sheet.get("strategy") or "btc_trend_v1",
        "profile": market.get("profile") or rt.get("mode") or projection.get("regime") or "default",
        "subtype": decision_sheet.get("method") or market.get("subtype") or trade.get("subtype") or "default",
        "fit_tier": decision_sheet.get("fit") or market.get("fit_tier") or trade.get("fit_tier") or "",
        "mood": decision_sheet.get("mood") or market.get("mood") or "",
        "consensus": decision_sheet.get("consensus") or market.get("consensus") or "",
        "intuition_score": decision_sheet.get("intuition_score") or market.get("intuition_score") or 0,
        "decay_pct": decision_sheet.get("decay_pct") or market.get("decay_pct") or 0,
        "venue_health": market.get("venue_health") or projection.get("reconcile_status") or "",
        "stale": rt.get("stale", False),
        "feature_flags": market.get("feature_flags") or trade.get("feature_flags") or [],
    })


def _build_context_payload(rt: Dict[str, Any]) -> Dict[str, Any]:
    trade = rt["trade"]
    market = rt["market"]
    projection = rt["projection"]

    policy_resolution = _policy_resolution(rt)
    strategy_registry = _resolve_strategy_registry(rt, policy_resolution)

    payload = {
        "contract_version": TRADE_CONTEXT_CONTRACT_VERSION,
        "decision_id": rt["decision_id"],
        "freshness": _contract_freshness(rt),
        "ack": _contract_ack(rt.get("decision_id")),
        "contracts": {"schema": "16.1", "ingestion_converged_ver": "15B.1"},
        "change_digest": _dictish(projection.get("change_digest"), "summary"),
        "source": "trade_state",
        "source_ts": rt.get("source_ts"),
        "stale": rt.get("stale"),
        "stale_ms": rt.get("stale_ms"),
        "reconcile_status": rt.get("reconcile_status"),
        "symbol": trade.get("symbol"),
        "side": trade.get("side"),
        "size_pct": _json_num(trade.get("size_pct")),
        "qty": _json_num(trade.get("qty")),
        "entry": _json_num(trade.get("entry")),
        "mark": _json_num(trade.get("mark")),
        "lev": _json_num(trade.get("lev")),
        "liq_price": _json_num(trade.get("liq_price")),
        "liq_buffer_pct": _json_num(trade.get("liq_buffer_pct")),
        "pnl_pct": _json_num(trade.get("pnl_pct")),
        "dd_day_pct": _json_num(trade.get("dd_day_pct")),
        "dd_total_pct": _json_num(trade.get("dd_total_pct")),
        "funding_8h_pct": _json_num(trade.get("funding_8h_pct")),
        "position_age_min": _json_num(trade.get("position_age_min")),
        "risk_action_current": trade.get("risk_action"),
        "decision_action_current": trade.get("decision_action"),
        "route": market.get("route"),
        "route_reason": market.get("route_reason"),
        "bot_health": market.get("bot_health", market.get("health")),
        "decision_action": policy_resolution.get("decision_action"),
        "risk_action": policy_resolution.get("risk_action"),
        "reason_code": policy_resolution.get("reason_code"),
        "policy_source": policy_resolution.get("policy_source"),
        "resolver_contract_version": policy_resolution.get("resolver_contract_version"),
        "policy_resolution": policy_resolution,
        "strategy_registry": strategy_registry,
    }

    payload["execution_chain"] = _execution_chain(rt, policy_resolution, strategy_registry)
    payload["counterfactual"] = _counterfactual(rt, policy_resolution, strategy_registry.get("strategy_key"))
    payload["recovery_path"] = _recovery_path(rt, policy_resolution, strategy_registry)
    payload["alert_ladder"] = _alert_ladder(rt, policy_resolution)
    return payload

@router.get("/context", response_model=dict, openapi_extra={"examples": [TRADE_CONTEXT_EXAMPLE]})
def get_trade_context(request: Request):
    rt = _merge_runtime(request)
    return _build_context_payload(rt)


@router.get("/position")
def get_trade_position(request: Request):
    rt = _merge_runtime(request)
    trade = rt["trade"]
    return {
        "contract_version": rt["contract_version"],
        "mode": rt["mode"],
        "source": rt["source"],
        "source_ts": rt["source_ts"],
        "stale": rt["stale"],
        "stale_ms": rt["stale_ms"],
        "reconcile_status": rt["reconcile_status"],
        "decision_id": rt["decision_id"],
        "position": trade.get("position"),
        "positions": _safe_list(trade.get("positions")),
        "pending_orders": _safe_list(trade.get("pending_orders")),
        "last_fill": trade.get("last_fill"),
        "last_fill_ts": trade.get("last_fill_ts"),
    }


@router.get("/recent_trades")
def get_recent_trades(request: Request):
    rt = _merge_runtime(request)
    trade = rt["trade"]
    recent = _safe_list(trade.get("recent_trades"))
    return {
        "contract_version": rt["contract_version"],
        "mode": rt["mode"],
        "source": rt["source"],
        "source_ts": rt["source_ts"],
        "stale": rt["stale"],
        "stale_ms": rt["stale_ms"],
        "reconcile_status": rt["reconcile_status"],
        "decision_id": rt["decision_id"],
        "count": len(recent),
        "items": recent,
    }


@router.get("/signals")
def get_trade_signals(request: Request):
    rt = _merge_runtime(request)
    trade = rt["trade"]
    signals = _safe_list(trade.get("signals"))
    return {
        "contract_version": rt["contract_version"],
        "mode": rt["mode"],
        "source": rt["source"],
        "source_ts": rt["source_ts"],
        "stale": rt["stale"],
        "stale_ms": rt["stale_ms"],
        "reconcile_status": rt["reconcile_status"],
        "decision_id": rt["decision_id"],
        "count": len(signals),
        "items": signals,
    }


@router.get("/delta")
def get_trade_delta(request: Request):
    rt = _merge_runtime(request)
    return rt["delta"]
