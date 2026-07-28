from __future__ import annotations

import json
import os
import time
import threading
from pathlib import Path
from typing import Any, Dict, Tuple

BASE_DIR = Path("/home/z/z/backend/data")
SETTINGS_DIR = BASE_DIR / "settings"
STATE_DIR = BASE_DIR / "state"
SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = SETTINGS_DIR / "ingress_settings.json"
SIGNAL_STATE_FILE = STATE_DIR / "seen_signal_ids.json"
EVENT_STATE_FILE = STATE_DIR / "seen_event_ids.json"

_LOCK = threading.Lock()

DEFAULTS = {
    "enabled": True,
    "max_signal_age_sec": 60 * 60 * 24 * 30, # 30d
    "future_skew_sec": 300, # +5m
    "signal_ttl_sec": 60 * 60 * 24 * 45, # 45d
    "event_ttl_sec": 60 * 60 * 24 * 7, # 7d
    "require_fields": ["signal_id", "symbol", "strategy", "side", "price", "ts"],
    "allowed_sides": ["buy", "sell", "long", "short"],
}

PAYLOAD_OPTIONAL_KEYS = {"lev", "liq", "tp", "sl", "rr", "liq_warn", "sl_ok"}


def _load_json(fp: Path, default: Any) -> Any:
    if not fp.exists():
        return default
    try:
        return json.load(open(fp, "r", encoding="utf-8"))
    except Exception:
        return default


def _save_json(fp: Path, obj: Any) -> None:
    tmp = fp.with_suffix(fp.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, fp)


def load_settings() -> Dict[str, Any]:
    cur = _load_json(SETTINGS_FILE, {})
    out = dict(DEFAULTS)
    if isinstance(cur, dict):
        out.update(cur)
    return out


def ensure_settings_file() -> Dict[str, Any]:
    cfg = load_settings()
    if not SETTINGS_FILE.exists():
        _save_json(SETTINGS_FILE, cfg)
    return cfg


def _prune_seen(d: Dict[str, float], ttl_sec: int, now_ts: float) -> Dict[str, float]:
    keep_from = now_ts - ttl_sec
    return {k: v for k, v in d.items() if isinstance(v, (int, float)) and v >= keep_from}


def _load_seen(fp: Path) -> Dict[str, float]:
    obj = _load_json(fp, {})
    return obj if isinstance(obj, dict) else {}


def _save_seen(fp: Path, obj: Dict[str, float]) -> None:
    _save_json(fp, obj)


def mark_once(kind: str, key: str, ttl_sec: int) -> Tuple[bool, str]:
    """
    returns (ok, reason)
    ok=False => duplicate
    """
    if not key:
        return False, f"{kind}_missing"

    fp = SIGNAL_STATE_FILE if kind == "signal" else EVENT_STATE_FILE
    now_ts = time.time()

    with _LOCK:
        seen = _load_seen(fp)
        seen = _prune_seen(seen, ttl_sec=ttl_sec, now_ts=now_ts)
        if key in seen:
            _save_seen(fp, seen)
            return False, f"duplicate_{kind}_id"
        seen[key] = now_ts
        _save_seen(fp, seen)
        return True, "ok"


def validate_signal_envelope(req: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    req expected:
    {
      "mode": "...",
      "route": "...",
      "signal": {...}
    }
    """
    cfg = ensure_settings_file()

    if not cfg.get("enabled", True):
        return True, "guard_disabled", {}

    if not isinstance(req, dict):
        return False, "malformed_request_not_dict", {}

    sig = req.get("signal")
    if not isinstance(sig, dict):
        return False, "malformed_signal_not_dict", {}

    missing = [k for k in cfg["require_fields"] if sig.get(k) in (None, "")]
    if missing:
        return False, f"missing_required:{','.join(missing)}", {"missing": missing}

    side = str(sig.get("side", "")).strip().lower()
    if side not in set(cfg["allowed_sides"]):
        return False, "invalid_side", {"side": sig.get("side")}

    try:
        float(sig.get("price"))
    except Exception:
        return False, "invalid_price", {"price": sig.get("price")}

    ts_raw = sig.get("ts")
    try:
        ts_int = int(ts_raw)
    except Exception:
        return False, "invalid_ts", {"ts": ts_raw}

    now_ts = int(time.time())
    max_age = int(cfg["max_signal_age_sec"])
    future_skew = int(cfg["future_skew_sec"])

    if ts_int < now_ts - max_age:
        return False, "stale_ts", {"ts": ts_int, "now": now_ts, "max_age_sec": max_age}
    if ts_int > now_ts + future_skew:
        return False, "future_ts", {"ts": ts_int, "now": now_ts, "future_skew_sec": future_skew}

    payload = sig.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return False, "malformed_payload_not_dict", {}

    bad_keys = [k for k in payload.keys() if k not in PAYLOAD_OPTIONAL_KEYS]
    if bad_keys:
        return False, "malformed_payload_unknown_keys", {"bad_keys": bad_keys}

    signal_id = str(sig.get("signal_id", "")).strip()
    ok, reason = mark_once("signal", signal_id, ttl_sec=int(cfg["signal_ttl_sec"]))
    if not ok:
        return False, reason, {"signal_id": signal_id}

    return True, "ok", {
        "signal_id": signal_id,
        "symbol": sig.get("symbol"),
        "strategy": sig.get("strategy"),
        "side": sig.get("side"),
        "price": sig.get("price"),
        "ts": ts_int,
    }


def check_and_mark_event_id(event_id: str) -> Tuple[bool, str]:
    cfg = ensure_settings_file()
    if not cfg.get("enabled", True):
        return True, "guard_disabled"
    return mark_once("event", str(event_id or "").strip(), ttl_sec=int(cfg["event_ttl_sec"]))