from __future__ import annotations
import datetime

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


def _policy_resolution(rt: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resolved = resolve_policy_ssot(rt)
        return resolved if isinstance(resolved, dict) else {}
    except TypeError:
        try:
            resolved = resolve_policy_ssot(trade_runtime=rt)
            return resolved if isinstance(resolved, dict) else {}
        except Exception:
            return {}
    except Exception:
        return {}

CONTRACT_VERSION = "trade.read_bridge.v3"
TRADE_CONTEXT_CONTRACT_VERSION = "trade.context.v3"


def _dictish(v: Any, fallback_key: str = "value") -> Dict[str, Any]:
    return v if isinstance(v, dict) else ({fallback_key: v} if v is not None else {})


def _json_num(v: Any) -> float | None:
    try:
        return None if v in (None, "", "None") else float(v)
    except Exception:
        return None


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v in (None, "", "None"):
            return default
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        s = str(v).strip()
        if not s:
            return default
        return int(float(s))
    except Exception:
        return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, "", "None"):
            return default
        if isinstance(v, bool):
            return float(int(v))
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if not s:
            return default
        return float(s)
    except Exception:
        return default


def _safe_iso_from_epoch(v: Any, default: str = "1970-01-01T00:00:00Z") -> str:
    ts = _to_float(v, 0.0)
    if ts <= 0:
        return default
    # epoch seconds / milliseconds 자동 보정
    if ts > 10_000_000_000:
        ts = ts / 1000.0
    try:
        return datetime.datetime.utcfromtimestamp(ts).isoformat() + "Z"
    except Exception:
        return default


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




def _non_empty_str(v: Any, default: str) -> str:
    if v in (None, "", "None"):
        return default
    s = str(v).strip()
    return s if s else default


def _normalize_strategy_registry_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload or {})
    normalized["strategy_key"] = _non_empty_str(normalized.get("strategy_key"), "unknown")
    normalized["profile"] = _non_empty_str(normalized.get("profile"), "paper")
    normalized["lookup_status"] = _non_empty_str(normalized.get("lookup_status"), "runtime_only")
    normalized["family"] = _non_empty_str(normalized.get("family"), "unknown")
    normalized["deploy_stage"] = _non_empty_str(normalized.get("deploy_stage"), normalized["profile"])
    normalized["bot_id"] = _non_empty_str(normalized.get("bot_id"), "unassigned")
    normalized["strategy_spec_version"] = _non_empty_str(normalized.get("strategy_spec_version"), "runtime_only")
    normalized["source"] = _non_empty_str(normalized.get("source"), "runtime_default")
    normalized["allowed_bot_ids"] = [str(x) for x in _safe_list(normalized.get("allowed_bot_ids")) if x not in (None, "", "None")]
    normalized["lookup_payload"] = normalized.get("lookup_payload") if isinstance(normalized.get("lookup_payload"), dict) else {}
    return normalized


def _normalize_execution_chain_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload or {})
    mode = _non_empty_str(normalized.get("mode"), "paper")
    authority = _non_empty_str(normalized.get("authority"), "shadow")
    live_enabled = _safe_bool(normalized.get("live_execution_enabled"), default=False)
    normalized["mode"] = mode
    normalized["route"] = _non_empty_str(normalized.get("route"), "paper_engine" if mode == "paper" else "default")
    normalized["route_reason"] = _non_empty_str(normalized.get("route_reason"), "mode_default")
    normalized["reconcile_status"] = _non_empty_str(normalized.get("reconcile_status"), "ok")
    normalized["bot_health"] = _non_empty_str(normalized.get("bot_health"), "unknown")
    normalized["venue_health"] = _non_empty_str(normalized.get("venue_health"), "unknown")
    normalized["policy_source"] = _non_empty_str(normalized.get("policy_source"), "policy_resolver_ssot")
    normalized["decision_action"] = _non_empty_str(normalized.get("decision_action"), "hold")
    normalized["risk_action"] = _non_empty_str(normalized.get("risk_action"), normalized["decision_action"])
    normalized["live_execution_enabled"] = live_enabled
    normalized["authority"] = authority
    normalized["strategy_key"] = _non_empty_str(normalized.get("strategy_key"), "unknown")
    normalized["strategy_lookup_status"] = _non_empty_str(normalized.get("strategy_lookup_status"), "runtime_only")
    return normalized




def _normalize_epoch_seconds(value: Any) -> int:
    iv = _to_int(value, 0)
    if iv <= 0:
        return 0
    if iv >= 10**18:
        iv //= 10**9
    elif iv >= 10**15:
        iv //= 10**6
    elif iv >= 10**12:
        iv //= 10**3
    return iv


def _epoch_to_iso8601z(value: Any, default: str = "1970-01-01T00:00:00Z") -> str:
    ts = _normalize_epoch_seconds(value)
    if ts <= 0:
        return default
    try:
        return datetime.datetime.utcfromtimestamp(ts).isoformat() + "Z"
    except (OverflowError, OSError, ValueError):
        return default


def _normalize_contract_freshness_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload or {})
    source_ts = _normalize_epoch_seconds(normalized.get("source_ts"))
    normalized["source"] = _non_empty_str(normalized.get("source"), "trade_state")
    normalized["source_ts"] = source_ts
    normalized["source_ts_iso"] = _non_empty_str(normalized.get("source_ts_iso"), _epoch_to_iso8601z(source_ts))
    normalized["stale"] = _safe_bool(normalized.get("stale"), default=True)
    stale_ms = normalized.get("stale_ms")
    normalized["stale_ms"] = int(stale_ms) if isinstance(stale_ms, (int, float)) else 0
    return normalized
def _normalized_runtime_meta(trade: Dict[str, Any], market: Dict[str, Any], projection: Dict[str, Any], params: Any) -> Dict[str, Any]:
    trust_rail = projection.get("trust_rail") if isinstance(projection.get("trust_rail"), dict) else {}
    mode = _first_non_empty(
        params.get("mode") if params is not None else None,
        market.get("profile"),
        trade.get("profile"),
        market.get("mode"),
        trade.get("mode"),
        trust_rail.get("mode"),
        projection.get("regime"),
        "paper",
    )
    source = _first_non_empty(
        projection.get("source"),
        projection.get("source_ref"),
        trade.get("source"),
        trade.get("_source"),
        market.get("source"),
        market.get("_source"),
        "trade_state",
    )
    source_ts = _first_non_empty(
        projection.get("source_ts"),
        trade.get("source_ts"),
        trade.get("_source_ts"),
        market.get("source_ts"),
        market.get("_source_ts"),
        0,
    )
    stale = _safe_bool(_first_non_empty(
        projection.get("stale"),
        trade.get("stale"),
        market.get("stale"),
        False,
    ))
    stale_ms = _first_non_empty(
        projection.get("stale_ms"),
        trade.get("stale_ms"),
        market.get("stale_ms"),
        0,
    )
    reconcile_status = _first_non_empty(
        projection.get("reconcile_status"),
        trade.get("reconcile_status"),
        market.get("reconcile_status"),
        "ok",
    )
    return {
        "mode": mode,
        "source": source,
        "source_ts": source_ts,
        "stale": stale,
        "stale_ms": stale_ms,
        "reconcile_status": reconcile_status,
    }


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

    runtime_meta = _normalized_runtime_meta(trade, market, projection, params)
    decision_id = _first_non_empty(
        trade.get("decision_id"),
        market.get("decision_id"),
        projection.get("decision_id"),
    )

    return {
        "mode": runtime_meta["mode"],
        "contract_version": CONTRACT_VERSION,
        "source": runtime_meta["source"],
        "source_ts": runtime_meta["source_ts"],
        "stale": runtime_meta["stale"],
        "stale_ms": runtime_meta["stale_ms"],
        "reconcile_status": runtime_meta["reconcile_status"],
        "decision_id": decision_id,
        "projection": projection,
        "delta": delta,
        "trade": trade,
        "market": market,
    }




def _normalize_context_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)

    normalized["backend_ver"] = _non_empty_str(normalized.get("backend_ver"), "unknown")

    freshness = dict(normalized.get("freshness") or {})
    source_ts = _to_int(freshness.get("source_ts"), _to_int(normalized.get("source_ts"), 0))
    freshness["source_ts_iso"] = _non_empty_str(
        freshness.get("source_ts_iso"),
        _safe_iso_from_epoch(source_ts),
    )
    normalized["freshness"] = freshness

    strategy_registry = dict(normalized.get("strategy_registry") or {})
    strategy_registry["family"] = _non_empty_str(strategy_registry.get("family"), "standalone")
    strategy_registry["bot_id"] = _non_empty_str(strategy_registry.get("bot_id"), "unassigned")
    strategy_registry["strategy_spec_version"] = _non_empty_str(strategy_registry.get("strategy_spec_version"), "runtime_only")
    normalized["strategy_registry"] = strategy_registry

    execution_chain = dict(normalized.get("execution_chain") or {})
    execution_chain["route"] = _non_empty_str(execution_chain.get("route"), "unrouted")
    execution_chain["route_reason"] = _non_empty_str(execution_chain.get("route_reason"), "mode_default")
    execution_chain["bot_health"] = _non_empty_str(execution_chain.get("bot_health"), "unknown")
    execution_chain["decision_action"] = _non_empty_str(execution_chain.get("decision_action"), "block")
    execution_chain["risk_action"] = _non_empty_str(execution_chain.get("risk_action"), "block")
    normalized["execution_chain"] = execution_chain

    defaults_str = {
        "symbol": "UNKNOWN",
        "side": "flat",
        "route": "unrouted",
        "route_reason": "mode_default",
        "bot_health": "unknown",
    }
    defaults_num = {
        "size_pct": 0.0,
        "qty": 0.0,
        "entry": 0.0,
        "mark": 0.0,
        "lev": 0.0,
        "liq_price": 0.0,
        "liq_buffer_pct": 0.0,
        "pnl_pct": 0.0,
        "dd_day_pct": 0.0,
        "dd_total_pct": 0.0,
        "funding_8h_pct": 0.0,
        "position_age_min": 0,
    }
    for key, default in defaults_str.items():
        normalized[key] = _non_empty_str(normalized.get(key), default)
    for key, default in defaults_num.items():
        normalized[key] = _to_float(normalized.get(key), default) if isinstance(default, float) else _to_int(normalized.get(key), default)

    normalized["risk_action_current"] = _non_empty_str(
        normalized.get("risk_action_current"),
        _non_empty_str(execution_chain.get("risk_action"), "block"),
    )
    normalized["decision_action_current"] = _non_empty_str(
        normalized.get("decision_action_current"),
        _non_empty_str(execution_chain.get("decision_action"), "block"),
    )

    policy_resolution = dict(normalized.get("policy_resolution") or {})
    policy_resolution["decision_action"] = _non_empty_str(policy_resolution.get("decision_action"), "block")
    policy_resolution["risk_action"] = _non_empty_str(policy_resolution.get("risk_action"), "block")
    policy_resolution["reason_code"] = _non_empty_str(policy_resolution.get("reason_code"), "DEFAULT")
    policy_resolution["policy_source"] = _non_empty_str(policy_resolution.get("policy_source"), "policy_resolver_ssot")
    policy_resolution["resolver_contract_version"] = _non_empty_str(policy_resolution.get("resolver_contract_version"), "unknown")
    policy_resolution["profile"] = _non_empty_str(policy_resolution.get("profile"), "paper")
    policy_resolution["subtype"] = _non_empty_str(policy_resolution.get("subtype"), "default")
    policy_resolution["strategy"] = _non_empty_str(policy_resolution.get("strategy"), "unknown")
    normalized["policy_resolution"] = policy_resolution

    return normalized
def _contract_freshness(rt: Dict[str, Any]) -> Dict[str, Any]:
    source = rt.get("source")
    source_ts = rt.get("source_ts") or 0
    return {
        "source": source,
        "source_raw": source,
        "source_ts": source_ts,
        "source_ts_epoch_ms": source_ts,
        "source_ts_iso": _safe_iso_from_epoch(source_ts),
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
        "route": _non_empty_str(market.get("route"), "unrouted"),
        "route_reason": _non_empty_str(market.get("route_reason"), "mode_default"),
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
        "contracts": {"schema": "15C.1", "ingestion_converged_ver": "15B.1"},
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
        "route": _non_empty_str(market.get("route"), "unrouted"),
        "route_reason": _non_empty_str(market.get("route_reason"), "mode_default"),
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
    return _normalize_context_payload(payload)

@router.get("/context", response_model=TradeContextResponse, openapi_extra={"examples": [TRADE_CONTEXT_EXAMPLE]})
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
