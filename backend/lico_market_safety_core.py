from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

VERSION = "ZOPS_LICO_FRESHNESS_POLICY_V9"
ACTION_ENUM = {"reduce25", "partial30", "hold", "stop", "route_change", "rollback", "block"}
REQUIRED_MIN_FIELDS = ["price", "pos_pct", "lev", "entry_ts", "funding_8h_pct", "dd_day_pct", "dd_total_pct"]
LIQ_ALTERNATIVES = [("liq_price", "liq_buffer_pct")]
DEFAULT_ROOT = Path(os.environ.get("Z_HOME", Path(__file__).resolve().parents[1])).resolve()


def now_ms() -> int:
    return int(time.time() * 1000)


def load_json(path: str | Path, fallback: Any = None) -> Any:
    p = Path(path)
    try:
        if p.exists():
            raw = p.read_text(encoding="utf-8").strip()
            if raw:
                return json.loads(raw)
    except Exception:
        return fallback
    return fallback


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _defaults(root: Path = DEFAULT_ROOT) -> Dict[str, Any]:
    obj = load_json(root / "ssot" / "defaults.json", {})
    return obj if isinstance(obj, dict) else {}


def _threshold_map(defaults: Mapping[str, Any]) -> Dict[str, Any]:
    th = defaults.get("thresholds") if isinstance(defaults, Mapping) else None
    out: Dict[str, Any] = {}
    if isinstance(th, dict):
        for k, v in th.items():
            if isinstance(v, dict):
                val = v.get("value", v.get("default"))
                out[str(k)] = val
                if v.get("runtime_env"):
                    out[str(v.get("runtime_env"))] = val
            else:
                out[str(k)] = v
    elif isinstance(th, list):
        for item in th:
            if isinstance(item, dict):
                val = item.get("value", item.get("default"))
                out[str(item.get("canonical_key", item.get("runtime_env", "")))] = val
                if item.get("runtime_env"):
                    out[str(item.get("runtime_env"))] = val
    for k, v in defaults.items():
        if k not in {"thresholds", "defaults"}:
            out.setdefault(str(k), v)
    if isinstance(defaults.get("defaults"), dict):
        for k, v in defaults.get("defaults", {}).items():
            out.setdefault(str(k), v)
    return out


def _threshold_value(defaults: Mapping[str, Any], key: str, fallback: float) -> float:
    vals = _threshold_map(defaults)
    for k in (key, key.upper(), key.lower(), f"ZOS_{key.upper()}"):
        try:
            if k in vals and vals.get(k) not in (None, ""):
                return float(vals.get(k))
        except Exception:
            pass
    return float(fallback)


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str):
            s = value.strip().replace(" ", "")
            if s.upper() in {"TRUE", "FALSE", "N/A", "NA", "NULL", "NONE", "-", "—"}:
                return None
            if s.endswith("%"):
                s = s[:-1]
            if "," in s and "." not in s:
                parts = s.split(",")
                if len(parts) == 2 and 1 <= len(parts[1]) <= 4:
                    s = parts[0] + "." + parts[1]
                else:
                    s = s.replace(",", "")
            elif "," in s and "." in s:
                s = s.replace(",", "")
            return float(s)
        return float(value)
    except Exception:
        return None


def _required_fields(defaults: Mapping[str, Any]) -> list[str]:
    v = defaults.get("ZOS_ATOMIC_REQUIRED_MIN_DATA_FIELDS", REQUIRED_MIN_FIELDS)
    return [str(x) for x in v] if isinstance(v, list) else list(REQUIRED_MIN_FIELDS)


def _liq_alternatives(defaults: Mapping[str, Any]) -> list[tuple[str, ...]]:
    raw = defaults.get("ZOS_ATOMIC_LIQ_FIELD_ALTERNATIVES", [list(x) for x in LIQ_ALTERNATIVES])
    out: list[tuple[str, ...]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, list) and item:
                out.append(tuple(str(x) for x in item))
    return out or list(LIQ_ALTERNATIVES)


def _field_source_ok(field: str, src_keys: Iterable[str]) -> bool:
    keys = [str(x) for x in (src_keys or [])]
    if "|" in field:
        return any(_field_source_ok(x, keys) for x in field.split("|"))
    needles = (f"cf:/{field}", f"sheets:/{field}", f"gs:/{field}")
    return any(k in keys for k in needles)


def _source_gaps(fields: Iterable[str], src_keys: Iterable[str]) -> list[str]:
    return [f for f in fields if not _field_source_ok(f, src_keys)]


def _snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    base = json.dumps({k: snapshot.get(k) for k in sorted(snapshot.keys()) if k != "market_safety_context"}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _bridge_config(root: Path) -> Dict[str, Any]:
    cfg = load_json(root / "config" / "lico_source_bridge.json", {})
    return cfg if isinstance(cfg, dict) else {}


def _source_kind(snapshot: Mapping[str, Any]) -> str:
    source = str(snapshot.get("source") or "").lower()
    ref = str(snapshot.get("source_ref") or snapshot.get("snapshot_ref") or "").lower()
    if source in {"sheets", "gs", "google_sheets"} or "docs.google.com" in ref or "output=csv" in ref:
        return "sheets"
    if source == "cf" or "workers.dev" in ref or "cloudflare" in ref:
        return "cf"
    return source or "unknown"


def _freshness_limits(root: Path, defaults: Mapping[str, Any], snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    cfg = _bridge_config(root)
    policy = cfg.get("freshness_policy_v9") if isinstance(cfg.get("freshness_policy_v9"), dict) else {}
    source_kind = _source_kind(snapshot)

    # CF keeps low-latency live strictness. Published Sheets CSV is human/poller source, not 1.5s websocket feed.
    strict_ms = int(_threshold_value(defaults, "DATA_STALE_MS", 1500.0))
    max_signal_ms = int(_threshold_value(defaults, "MAX_SIGNAL_AGE_MS", strict_ms))
    cf_ms = int(float(os.environ.get("ZOPS_LICO_CF_STALE_MS", policy.get("cf_stale_ms", strict_ms))))
    sheets_ms = int(float(os.environ.get("ZOPS_LICO_SHEETS_STALE_MS", policy.get("sheets_stale_ms", 60000))))
    csv_ms = int(float(os.environ.get("ZOPS_LICO_SHEETS_CSV_STALE_MS", policy.get("sheets_published_csv_stale_ms", sheets_ms))))

    ref = str(snapshot.get("source_ref") or "").lower()
    if source_kind == "cf":
        selected = cf_ms
        label = "cf_strict"
    elif source_kind == "sheets" and ("docs.google.com" in ref or "output=csv" in ref or ref.startswith("url:")):
        selected = csv_ms
        label = "sheets_published_csv"
    elif source_kind == "sheets":
        selected = sheets_ms
        label = "sheets_snapshot"
    else:
        selected = strict_ms
        label = "default_strict"

    return {
        "source_kind": source_kind,
        "label": label,
        "selected_stale_ms": int(selected),
        "strict_data_stale_ms": int(strict_ms),
        "max_signal_age_ms": int(max_signal_ms),
        "cf_stale_ms": int(cf_ms),
        "sheets_stale_ms": int(sheets_ms),
        "sheets_published_csv_stale_ms": int(csv_ms),
    }


def _snapshot_age_ms(snapshot: Mapping[str, Any], ts_ms: int) -> Optional[float]:
    age_ms = _as_float(snapshot.get("age_ms"))
    if age_ms is not None:
        return max(0.0, age_ms)
    for k in ("observed_ts_ms", "ingress_observed_ts_ms", "_fetch_observed_ts_ms", "source_ts_ms"):
        v = _as_float(snapshot.get(k))
        if v is not None and v > 0:
            return max(0.0, float(ts_ms) - v)
    return None


def _classify(snapshot: Mapping[str, Any], defaults: Mapping[str, Any], ts_ms: int, root: Path) -> tuple[list[str], list[str], Dict[str, Any], Dict[str, Any]]:
    flags: list[str] = []
    warnings: list[str] = []
    required = _required_fields(defaults)
    missing = [f for f in required if snapshot.get(f) in (None, "")]
    for alt in _liq_alternatives(defaults):
        if not any(snapshot.get(k) not in (None, "") for k in alt):
            missing.append("|".join(alt))
    if missing:
        flags.append("missing_min_data:" + ",".join(missing))

    source_required = list(required) + ["|".join(alt) for alt in _liq_alternatives(defaults)]
    src_gaps = _source_gaps(source_required, snapshot.get("src_keys", []))
    if src_gaps:
        flags.append("missing_core_src_keys:" + ",".join(src_gaps))

    policy = _freshness_limits(root, defaults, snapshot)
    selected_stale_ms = int(policy["selected_stale_ms"])
    age_ms = _snapshot_age_ms(snapshot, ts_ms)
    stale_state = str(snapshot.get("stale_state") or "").upper()
    source_policy_fresh = age_ms is not None and age_ms <= selected_stale_ms

    # v9 핵심: Sheets CSV는 1.5s strict stale_state=STALE여도 source-specific TTL 안이면 FRESH로 재분류.
    if stale_state and stale_state != "FRESH" and not source_policy_fresh:
        flags.append(f"snapshot_not_fresh:{stale_state}")
    elif stale_state and stale_state != "FRESH" and source_policy_fresh:
        warnings.append(f"snapshot_bridge_stale_but_policy_fresh:{stale_state}")

    if age_ms is None:
        warnings.append("age_ms_unknown")
    elif age_ms > selected_stale_ms:
        flags.append(f"data_stale_ms:{int(age_ms)}>{int(selected_stale_ms)}")

    price = _as_float(snapshot.get("price"))
    pos_pct = _as_float(snapshot.get("pos_pct"))
    lev = _as_float(snapshot.get("lev"))
    liq_buffer_pct = _as_float(snapshot.get("liq_buffer_pct"))
    funding_8h_pct = _as_float(snapshot.get("funding_8h_pct"))
    dd_day_pct = _as_float(snapshot.get("dd_day_pct"))
    dd_total_pct = _as_float(snapshot.get("dd_total_pct"))
    spread_bp = _as_float(snapshot.get("spread_bp"))
    slip_bp = _as_float(snapshot.get("slip_bp"))
    depth_notional = _as_float(snapshot.get("depth_notional"))

    exposure_pct = None
    exposure_x = None
    if pos_pct is not None and lev is not None:
        exposure_pct = pos_pct * lev
        exposure_x = exposure_pct / 100.0
        if exposure_pct >= 200:
            warnings.append(f"exposure_high:{exposure_pct:.2f}%")
        elif exposure_pct >= 100:
            warnings.append(f"exposure_watch:{exposure_pct:.2f}%")

    if liq_buffer_pct is not None:
        if liq_buffer_pct < 3.0:
            flags.append(f"liq_buffer_critical:{liq_buffer_pct:.2f}%")
        elif liq_buffer_pct < 6.0:
            warnings.append(f"liq_buffer_risk:{liq_buffer_pct:.2f}%")
        elif liq_buffer_pct < 10.0:
            warnings.append(f"liq_buffer_watch:{liq_buffer_pct:.2f}%")

    if funding_8h_pct is not None and abs(funding_8h_pct) >= 0.08:
        warnings.append(f"funding_8h_watch:{funding_8h_pct:.4f}%")
    if dd_day_pct is not None and dd_day_pct <= -3.0:
        warnings.append(f"dd_day_watch:{dd_day_pct:.2f}%")
    if dd_total_pct is not None and dd_total_pct <= -8.0:
        warnings.append(f"dd_total_risk:{dd_total_pct:.2f}%")
    max_spread = _threshold_value(defaults, "MAX_SPREAD_BP", 8.0)
    max_slip = _threshold_value(defaults, "MAX_SLIP_BP", 3.0)
    if spread_bp is not None and spread_bp > max_spread:
        flags.append(f"spread_bp:{spread_bp:.2f}>{max_spread:.2f}")
    if slip_bp is not None and slip_bp > max_slip:
        flags.append(f"slip_bp:{slip_bp:.2f}>{max_slip:.2f}")

    metrics = {
        "price_usdt": price,
        "pos_pct": pos_pct,
        "lev_x": lev,
        "exposure_pct": exposure_pct,
        "exposure_x": exposure_x,
        "liq_buffer_pct": liq_buffer_pct,
        "liq_price_usdt": _as_float(snapshot.get("liq_price")),
        "funding_8h_pct": funding_8h_pct,
        "dd_day_pct": dd_day_pct,
        "dd_total_pct": dd_total_pct,
        "spread_bp": spread_bp,
        "slip_bp": slip_bp,
        "depth_notional_usdt": depth_notional,
        "data_age_ms": int(age_ms) if age_ms is not None else None,
        "freshness_limit_ms": selected_stale_ms,
    }
    return flags, warnings, metrics, policy


def evaluate_market_safety(snapshot: Mapping[str, Any] | None, *, root: str | Path | None = None, ts_ms: int | None = None) -> Dict[str, Any]:
    root_path = Path(root).resolve() if root else DEFAULT_ROOT
    defaults = _defaults(root_path)
    ts = int(ts_ms if ts_ms is not None else now_ms())
    snap = dict(snapshot or {})
    flags, warnings, metrics, freshness_policy = _classify(snap, defaults, ts, root_path)

    score = 100
    score -= 30 * sum(1 for x in flags if x.startswith("missing_min_data"))
    score -= 25 * sum(1 for x in flags if x.startswith("missing_core_src_keys"))
    score -= 25 * sum(1 for x in flags if x.startswith("data_stale_ms") or x.startswith("snapshot_not_fresh"))
    score -= 18 * sum(1 for x in flags if x.startswith("spread_bp") or x.startswith("slip_bp") or x.startswith("liq_buffer_critical"))
    # freshness policy warning should not over-penalize; exposure still matters.
    score -= 8 * sum(1 for x in warnings if not x.startswith("snapshot_bridge_stale_but_policy_fresh"))
    score = max(0, min(100, score))

    hard_flags = [x for x in flags if x.startswith(("missing_min_data", "missing_core_src_keys", "data_stale_ms", "snapshot_not_fresh"))]
    if hard_flags:
        state = "risk"
        risk_level = "high"
        recommendation = "hold"
        integrity_state = "HOLD"
        p4_consumable = True
    elif any(x.startswith("liq_buffer_critical") for x in flags):
        state = "block"
        risk_level = "critical"
        recommendation = "reduce25"
        integrity_state = "PASS"
        p4_consumable = True
    elif any(x.startswith("spread_bp") for x in flags):
        state = "risk"
        risk_level = "high"
        recommendation = "route_change"
        integrity_state = "PASS"
        p4_consumable = True
    elif any(x.startswith("slip_bp") for x in flags):
        state = "risk"
        risk_level = "high"
        recommendation = "hold"
        integrity_state = "PASS"
        p4_consumable = True
    elif warnings:
        state = "watch"
        risk_level = "moderate"
        recommendation = "hold"
        integrity_state = "PASS"
        p4_consumable = True
    else:
        state = "ok"
        risk_level = "low"
        recommendation = "hold"
        integrity_state = "PASS"
        p4_consumable = True

    src_keys = [str(x) for x in snap.get("src_keys", []) if isinstance(x, str)]
    context_id = f"lico.msf.{ts}.{_snapshot_hash(snap)}"
    payload: Dict[str, Any] = {
        "ok": integrity_state == "PASS",
        "version": VERSION,
        "component": "LICO",
        "role": "market_safety_decision_feed",
        "context_id": context_id,
        "market_safety_state": state,
        "integrity_state": integrity_state,
        "score": score,
        "risk_level": risk_level,
        "p4_consumable": p4_consumable,
        "action_authority": "none",
        "may_emit_final_action": False,
        "recommendation": recommendation if recommendation in ACTION_ENUM else "hold",
        "veto_flags": flags,
        "warnings": warnings,
        "metrics": metrics,
        "freshness_policy": freshness_policy,
        "src_keys": src_keys,
        "source_required": ["cf:/", "sheets:", "ssot:"],
        "fail_action_if_invalid": "hold",
        "decision_feed": {
            "consumed_by": "P4_atomic_validation_gate",
            "consumer_field": "market_safety_context",
            "direct_bot_signal": False,
            "bot_signal_path": "P4_final_action_only",
        },
        "authority": {
            "lico_action_authority": "none",
            "p4_final_action_authority": True,
            "order_mutation": "blocked",
            "autotrade_effect": "none_until_p4_final_action",
        },
        "ts_ms": ts,
    }
    return payload


def validate_market_safety_context(ctx: Mapping[str, Any] | None, *, now: int | None = None, max_age_ms: int | None = None) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(ctx, Mapping):
        return False, ["missing_lico_market_safety_context"]
    if ctx.get("component") != "LICO" or ctx.get("role") != "market_safety_decision_feed":
        errors.append("invalid_lico_context_identity")
    if ctx.get("p4_consumable") is not True:
        errors.append("lico_not_p4_consumable")
    if str(ctx.get("action_authority")) != "none" or ctx.get("may_emit_final_action") is not False:
        errors.append("lico_authority_violation")
    if str(ctx.get("recommendation", "hold")) not in ACTION_ENUM:
        errors.append("invalid_lico_recommendation")
    if str(ctx.get("market_safety_state", "")) not in {"ok", "watch", "risk", "block"}:
        errors.append("invalid_lico_market_safety_state")
    try:
        ts = int(ctx.get("ts_ms") or 0)
    except Exception:
        ts = 0
    if ts <= 0:
        errors.append("missing_lico_ts_ms")
    if max_age_ms is not None and ts > 0:
        n = int(now if now is not None else now_ms())
        if n - ts > int(max_age_ms):
            errors.append(f"stale_lico_context:{n-ts}>{max_age_ms}")
    return not errors, errors
