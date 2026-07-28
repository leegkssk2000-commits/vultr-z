from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

try:
    from engine.state_contracts import (
        ALERT_LADDER_LEVELS,
        CORE_CONTRACT_RULES,
        apply_hysteresis,
        normalize_alert_ladder,
    )
except Exception:  # pragma: no cover
    ALERT_LADDER_LEVELS = ("silent", "badge", "banner", "blocking")
    CORE_CONTRACT_RULES = {
        "hysteresis_ms": 30_000,
        "dedupe_window_ms": 600_000,
        "ack_scope_ttl_ms": 900_000,
        "degrade_precedence": ["blocking", "banner", "badge", "silent"],
        "cooldown_ms": 120_000,
    }

    def normalize_alert_ladder(level: Any) -> str:
        raw = str(level or "silent").strip().lower()
        return raw if raw in ALERT_LADDER_LEVELS else "silent"

    def apply_hysteresis(previous_level: Any, proposed_level: Any, last_changed_at_ms: Any, now_ms: Any, hysteresis_ms: Any = None) -> str:
        prev = normalize_alert_ladder(previous_level)
        new = normalize_alert_ladder(proposed_level)
        if prev == new:
            return new
        try:
            delta = int(now_ms) - int(last_changed_at_ms or 0)
        except Exception:
            delta = 999999999
        gate = int(hysteresis_ms or CORE_CONTRACT_RULES["hysteresis_ms"])
        return prev if delta < gate else new


TRUST_RAIL_KEYS = (
    "mode",
    "freshness",
    "reconcile_confidence",
    "change_digest",
)

READ_MODEL_KEYS = (
    "backend_ver",
    "decision_id",
    "missingness",
    "counterfactual",
    "recovery_path",
    "alert_ladder",
)

_DELTA_DIR = Path(os.getenv("CHANGE12_DELTA_DIR", "/tmp"))
_DELTA_FILE = _DELTA_DIR / "change12_delta_snapshot.json"


def now_ms() -> int:
    return int(time.time() * 1000)


def _to_int(value: Any, default: int = 0) -> int:
    if value in (None, "", "None"):
        return int(default)
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "None"):
        return float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _parse_ts_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        iv = int(value)
        if iv > 10_000_000_000:
            return iv
        if iv > 0:
            return iv * 1000
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return _parse_ts_ms(int(raw))
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return 0
    return 0


def _resolve_mode(state: Mapping[str, Any]) -> str:
    candidates = (
        state.get("mode"),
        state.get("run_mode"),
        state.get("execution_mode"),
        state.get("paper"),
    )
    for item in candidates:
        s = _to_str(item).lower()
        if s in ("paper", "live"):
            return s
        if s in ("true", "1", "yes"):
            return "paper"
        if s in ("false", "0", "no"):
            return "live"
    return "paper"


def _resolve_source_ts_ms(state: Mapping[str, Any]) -> int:
    for key in (
        "source_ts",
        "source_ts_ms",
        "updated_at_ms",
        "updated_at",
        "snapshot_ts",
        "last_event_ts",
        "webhook_ts",
        "ts",
        "timestamp",
    ):
        ts = _parse_ts_ms(state.get(key))
        if ts > 0:
            return ts
    return now_ms()


def _resolve_route(state: Mapping[str, Any]) -> str:
    for key in ("route", "routing_key", "execution_route", "selected_route"):
        route = _to_str(state.get(key))
        if route:
            return route
    return "primary"


def _resolve_backend_ver(state: Mapping[str, Any]) -> str:
    for key in ("backend_ver", "backend_version", "service_version"):
        val = _to_str(state.get(key))
        if val:
            return val
    return os.getenv("APP_VERSION") or os.getenv("BACKEND_VERSION") or "dev"


def _resolve_decision_id(state: Mapping[str, Any], current_ts: int) -> str:
    existing = _to_str(state.get("decision_id"))
    if existing:
        return existing
    strat = _to_str(state.get("strategy") or state.get("strategy_key") or state.get("bot_id") or "core")
    symbol = _to_str(state.get("symbol") or state.get("market") or state.get("ticker") or "na")
    return f"{symbol}:{strat}:{current_ts}"


def compute_missingness(state: Mapping[str, Any]) -> Dict[str, Any]:
    required = (
        "symbol",
        "strategy",
        "source_ts",
        "reconcile_status",
        "mode",
        "position_side",
    )
    field_aliases = {
        "symbol": ("symbol", "market", "ticker"),
        "strategy": ("strategy", "strategy_key", "bot_id"),
        "source_ts": ("source_ts", "source_ts_ms", "updated_at_ms", "updated_at"),
        "reconcile_status": ("reconcile_status", "reconcile", "sync_status"),
        "mode": ("mode", "run_mode", "execution_mode"),
        "position_side": ("position_side", "side"),
    }
    missing: List[str] = []
    for field in required:
        aliases = field_aliases.get(field, (field,))
        found = False
        for alias in aliases:
            value = state.get(alias)
            if value not in (None, "", [], {}):
                found = True
                break
        if not found:
            missing.append(field)
    return {
        "count": len(missing),
        "fields": missing,
        "ratio": round(len(missing) / max(len(required), 1), 4),
        "status": "ok" if not missing else "degraded",
    }


def compute_confidence_band(state: Mapping[str, Any], missingness: Mapping[str, Any], stale_ms: int) -> Tuple[float, str]:
    raw = state.get("confidence_score") or state.get("confidence")
    score: Optional[float] = None
    if isinstance(raw, (int, float)):
        score = float(raw)
        if score > 1.0:
            score = score / 100.0
    missing_count = _to_int(missingness.get("count"), 0)
    if score is None:
        stale_penalty = min(max(stale_ms - 30_000, 0) / 300_000.0, 0.35)
        miss_penalty = min(missing_count * 0.12, 0.6)
        block_penalty = 0.15 if _to_str(state.get("blocking_reason")) else 0.0
        score = max(0.05, 1.0 - stale_penalty - miss_penalty - block_penalty)
    score = round(max(0.0, min(score, 1.0)), 4)
    if score >= 0.85:
        band = "high"
    elif score >= 0.65:
        band = "partial"
    elif score >= 0.45:
        band = "recon_pending"
    else:
        band = "low"
    return score, band


def build_counterfactual(state: Mapping[str, Any], route: str) -> Dict[str, Any]:
    alt_route = "backup" if route == "primary" else "primary"
    impact_bps = 12 if alt_route == "backup" else 4
    return {
        "scenario": f"if_route_{alt_route}",
        "summary": f"route {alt_route} 사용 시 슬리피지 +{impact_bps}bps 가정",
        "impact_bps": impact_bps,
    }


def build_recovery_path(state: Mapping[str, Any], alert_level: str, missingness: Mapping[str, Any]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = [
        {"step": "ack", "status": "required" if alert_level in ("banner", "blocking") else "optional"},
        {"step": "inspect", "target": "trust_rail + decision_sheet"},
    ]
    if _to_int(missingness.get("count"), 0) > 0:
        steps.append({"step": "action", "target": "repair_missing_fields", "fields": list(missingness.get("fields") or [])})
    else:
        steps.append({"step": "action", "target": "execute_or_hold", "route": _resolve_route(state)})
    steps.append({"step": "verify", "target": "delta_projection + alert_ladder"})
    return steps


def build_change_digest(state: Mapping[str, Any], stale_ms: int, missingness: Mapping[str, Any]) -> str:
    parts: List[str] = []
    fills_pct = state.get("fills_pct")
    if fills_pct is not None:
        parts.append(f"fills {round(_to_float(fills_pct), 1)}%")
    degraded = state.get("degraded_bots") or state.get("degraded_bot_count")
    if degraded not in (None, "", 0, "0"):
        parts.append(f"degraded {int(_to_float(degraded))}")
    route = _resolve_route(state)
    if route:
        parts.append(f"route={route}")
    if stale_ms > 0:
        parts.append(f"stale {int(round(stale_ms / 1000.0))}s")
    missing_count = _to_int(missingness.get("count"), 0)
    if missing_count > 0:
        parts.append(f"missing {missing_count}")
    return " · ".join(parts[:4]) if parts else "steady"


def derive_alert_ladder(state: Mapping[str, Any], missingness: Mapping[str, Any], stale_ms: int, confidence_band: str, current_ts: int) -> Dict[str, Any]:
    blocking_reason = _to_str(state.get("blocking_reason") or state.get("block_reason"))
    reconcile_status = _to_str(state.get("reconcile_status") or state.get("reconcile") or "ok").lower()
    missing_count = _to_int(missingness.get("count"), 0)
    proposed = "silent"
    reasons: List[str] = []
    if blocking_reason or reconcile_status in ("blocking", "failed", "halt"):
        proposed = "blocking"
        reasons.append(blocking_reason or reconcile_status or "blocking")
    elif stale_ms >= 300_000 or missing_count >= 3:
        proposed = "banner"
        reasons.append("freshness_or_missingness")
    elif stale_ms >= 90_000 or missing_count >= 1 or confidence_band in ("partial", "recon_pending", "low"):
        proposed = "badge"
        reasons.append("attention_needed")
    else:
        reasons.append("healthy")

    previous_level = state.get("alert_ladder_level") or state.get("alert_ladder")
    last_changed_at_ms = _to_int(state.get("alert_ladder_changed_at_ms") or state.get("alert_changed_at_ms"), 0)
    effective = apply_hysteresis(previous_level, proposed, last_changed_at_ms, current_ts, CORE_CONTRACT_RULES.get("hysteresis_ms"))
    effective = normalize_alert_ladder(effective)
    return {
        "level": effective,
        "proposed": proposed,
        "reasons": reasons,
        "server_contract": {
            "silent": {"notify": False, "interrupt": False},
            "badge": {"notify": True, "interrupt": False},
            "banner": {"notify": True, "interrupt": True},
            "blocking": {"notify": True, "interrupt": True, "block": True},
        },
        "hysteresis_ms": CORE_CONTRACT_RULES.get("hysteresis_ms"),
        "dedupe_window_ms": CORE_CONTRACT_RULES.get("dedupe_window_ms"),
        "ack_scope_ttl_ms": CORE_CONTRACT_RULES.get("ack_scope_ttl_ms"),
        "degrade_precedence": CORE_CONTRACT_RULES.get("degrade_precedence"),
        "changed": effective != normalize_alert_ladder(previous_level),
        "changed_at_ms": current_ts,
    }


def build_projection(state: Mapping[str, Any]) -> Dict[str, Any]:
    current_ts = now_ms()
    source_ts_ms = _resolve_source_ts_ms(state)
    stale_ms = max(current_ts - source_ts_ms, 0)
    missingness = compute_missingness(state)
    confidence_score, confidence_band = compute_confidence_band(state, missingness, stale_ms)
    alert_ladder = derive_alert_ladder(state, missingness, stale_ms, confidence_band, current_ts)
    counterfactual = build_counterfactual(state, _resolve_route(state))
    recovery_path = build_recovery_path(state, alert_ladder["level"], missingness)
    change_digest = build_change_digest(state, stale_ms, missingness)
    backend_ver = _resolve_backend_ver(state)
    decision_id = _resolve_decision_id(state, current_ts)
    trust_rail = {
        "mode": _resolve_mode(state),
        "freshness": {
            "source_ts": source_ts_ms,
            "stale": stale_ms,
            "stale_ms": stale_ms,
        },
        "reconcile_confidence": {
            "reconcile": _to_str(state.get("reconcile_status") or state.get("reconcile") or "ok"),
            "confidence": confidence_band,
            "confidence_score": confidence_score,
        },
        "change_digest": change_digest,
    }
    decision_sheet = {
        "backend_ver": backend_ver,
        "decision_id": decision_id,
        "missingness": missingness,
        "counterfactual": counterfactual,
        "recovery_path": recovery_path,
        "alert_ladder": alert_ladder,
    }
    return {
        "trust_rail": trust_rail,
        "decision_sheet": decision_sheet,
        "alert_ladder": alert_ladder,
        "core_contract": deepcopy(CORE_CONTRACT_RULES),
        "backend_ver": backend_ver,
        "decision_id": decision_id,
        "missingness": missingness,
        "counterfactual": counterfactual,
        "recovery_path": recovery_path,
        "change_digest": change_digest,
        "source_ts": source_ts_ms,
        "stale_ms": stale_ms,
        "reconcile_status": trust_rail["reconcile_confidence"]["reconcile"],
        "confidence": confidence_band,
        "confidence_score": confidence_score,
        "updated_at_ms": current_ts,
    }


def augment_trade_state(state: Mapping[str, Any]) -> Dict[str, Any]:
    merged = dict(state or {})
    projection = build_projection(merged)
    merged.update(
        {
            "backend_ver": projection["backend_ver"],
            "decision_id": projection["decision_id"],
            "missingness": projection["missingness"],
            "counterfactual": projection["counterfactual"],
            "recovery_path": projection["recovery_path"],
            "alert_ladder": projection["alert_ladder"],
            "alert_ladder_level": projection["alert_ladder"]["level"],
            "alert_ladder_changed_at_ms": projection["alert_ladder"]["changed_at_ms"],
            "source_ts": projection["source_ts"],
            "stale_ms": projection["stale_ms"],
            "reconcile_status": projection["reconcile_status"],
            "confidence": projection["confidence"],
            "confidence_score": projection["confidence_score"],
            "change_digest": projection["change_digest"],
            "trust_rail": projection["trust_rail"],
            "decision_sheet": projection["decision_sheet"],
            "core_contract": projection["core_contract"],
            "updated_at_ms": projection["updated_at_ms"],
        }
    )
    return merged


def _flatten_projection(prefix: str, value: Any, out: Dict[str, Any]) -> None:
    if isinstance(value, Mapping):
        for k, v in value.items():
            child = f"{prefix}.{k}" if prefix else str(k)
            _flatten_projection(child, v, out)
        return
    if isinstance(value, list):
        out[prefix] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return
    out[prefix] = value


def build_delta_feed(state: Mapping[str, Any], persist: bool = True) -> Dict[str, Any]:
    projection = build_projection(state)
    flat: Dict[str, Any] = {}
    _flatten_projection("", projection, flat)
    previous = {}
    if _DELTA_FILE.exists():
        try:
            previous = json.loads(_DELTA_FILE.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    changes: List[Dict[str, Any]] = []
    tracked_keys = [
        "trust_rail.mode",
        "trust_rail.freshness.stale_ms",
        "trust_rail.reconcile_confidence.reconcile",
        "trust_rail.reconcile_confidence.confidence",
        "trust_rail.change_digest",
        "decision_sheet.backend_ver",
        "decision_sheet.missingness.count",
        "decision_sheet.counterfactual.summary",
        "decision_sheet.recovery_path",
        "alert_ladder.level",
    ]
    for key in tracked_keys:
        prev = previous.get(key)
        curr = flat.get(key)
        if prev != curr:
            changes.append({"field": key, "before": prev, "after": curr})
    if persist:
        _DELTA_DIR.mkdir(parents=True, exist_ok=True)
        _DELTA_FILE.write_text(json.dumps(flat, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "projection": projection,
        "changes": changes,
        "count": len(changes),
        "delta_endpoint": "/dashboard/delta",
    }
