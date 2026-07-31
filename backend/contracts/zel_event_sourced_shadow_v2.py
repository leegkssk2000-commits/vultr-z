from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

SCHEMA_VERSION = "zel.shadow.event.v2"
EVENT_TYPES = {
    "strategy_signal_emitted", "admission_decided", "shadow_open_requested",
    "shadow_open_confirmed", "skill_triggered", "skill_blocked", "shadow_managed",
    "shadow_close_requested", "shadow_closed", "shadow_ledger_joined",
    "formal_ledger_joined", "held", "blocked", "rolled_back",
}
NEXT_TYPES = {
    None: {"strategy_signal_emitted"},
    "strategy_signal_emitted": {"admission_decided", "held", "blocked"},
    "admission_decided": {"shadow_open_requested", "held", "blocked"},
    "shadow_open_requested": {"shadow_open_confirmed", "held", "blocked", "rolled_back"},
    "shadow_open_confirmed": {"skill_triggered", "skill_blocked", "shadow_managed", "shadow_close_requested", "held", "blocked"},
    "skill_triggered": {"shadow_managed", "shadow_close_requested", "held", "blocked"},
    "skill_blocked": {"shadow_managed", "shadow_close_requested", "held", "blocked"},
    "shadow_managed": {"skill_triggered", "skill_blocked", "shadow_managed", "shadow_close_requested", "held", "blocked"},
    "shadow_close_requested": {"shadow_closed", "held", "blocked", "rolled_back"},
    "shadow_closed": {"shadow_ledger_joined", "held", "blocked"},
    "shadow_ledger_joined": {"formal_ledger_joined", "held", "blocked"},
    "held": {"admission_decided", "shadow_open_requested", "shadow_managed", "shadow_close_requested", "blocked"},
    "formal_ledger_joined": set(), "blocked": set(), "rolled_back": set(),
}
REQUIRED_FIELDS = {
    "event_id", "parent_event_id", "decision_id", "position_id", "strategy_id",
    "strategy_source_sha256", "method_id", "skill_set", "team_id", "symbol", "side",
    "market_snapshot_sha256", "risk_snapshot_sha256", "sequence_no", "event_ts",
    "idempotency_key", "event_type", "payload", "source_ids", "authority",
}
PRIVATE_TOKENS = {
    "api_key", "apikey", "secret", "credential", "password", "private_key",
    "account_id", "wallet", "access_token", "refresh_token",
}


class ShadowEventV2Error(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise ShadowEventV2Error(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, *, maximum: int = 300, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if not result and not allow_empty:
        _fail("STRING_REQUIRED", name)
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail("BOOL_REQUIRED", name)
    return value


def _strings(value: Any, name: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or len(value) > 64:
        _fail("STRING_LIST_REQUIRED", name)
    result = sorted({_string(item, f"{name}[]") for item in value})
    if not result and not allow_empty:
        _fail("STRING_LIST_EMPTY", name)
    return result


def _timestamp(value: Any) -> str:
    text = _string(value, "event_ts", maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("EVENT_TIMESTAMP_INVALID", text)
    if parsed.tzinfo is None:
        _fail("EVENT_TIMESTAMP_TIMEZONE_REQUIRED", text)
    return parsed.isoformat()


def _reject_private(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lower = str(key).lower()
            if any(token in lower for token in PRIVATE_TOKENS):
                _fail("PRIVATE_FIELD_FORBIDDEN", f"{path}.{key}")
            _reject_private(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private(child, f"{path}[{index}]")


def normalize_authority(value: Any) -> dict[str, Any]:
    raw = _mapping(value, "authority")
    authority = {
        "shadow_only": _bool(raw.get("shadow_only"), "authority.shadow_only"),
        "runtime_bound": _bool(raw.get("runtime_bound"), "authority.runtime_bound"),
        "formal_ledger_write_allowed": _bool(raw.get("formal_ledger_write_allowed"), "authority.formal_ledger_write_allowed"),
        "paper_allowed": _bool(raw.get("paper_allowed"), "authority.paper_allowed"),
        "live_allowed": _bool(raw.get("live_allowed"), "authority.live_allowed"),
        "promotion_authority": _bool(raw.get("promotion_authority"), "authority.promotion_authority"),
        "execution_authority": _string(raw.get("execution_authority"), "authority.execution_authority", maximum=40).upper(),
        "order_authority": _string(raw.get("order_authority"), "authority.order_authority", maximum=40).upper(),
    }
    if authority["shadow_only"] is not True:
        _fail("SHADOW_ONLY_REQUIRED")
    if authority["paper_allowed"] or authority["live_allowed"] or authority["promotion_authority"]:
        _fail("CAPITAL_OR_PROMOTION_AUTHORITY_FORBIDDEN")
    if authority["execution_authority"] != "NONE" or authority["order_authority"] != "BLOCKED":
        _fail("EXECUTION_OR_ORDER_AUTHORITY_FORBIDDEN")
    return authority


def seal_event(value: Mapping[str, Any], *, require_sealed_sha: bool = False) -> dict[str, Any]:
    raw = _mapping(value, "event")
    missing = sorted(REQUIRED_FIELDS - set(raw))
    if missing:
        _fail("EVENT_FIELDS_MISSING", ",".join(missing))
    event_type = _string(raw["event_type"], "event_type")
    if event_type not in EVENT_TYPES:
        _fail("EVENT_TYPE_INVALID", event_type)
    sequence = raw["sequence_no"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        _fail("SEQUENCE_INVALID")
    side = _string(raw["side"], "side").upper()
    if side not in {"LONG", "SHORT"}:
        _fail("SIDE_INVALID")
    payload = _mapping(raw["payload"], "payload")
    _reject_private(payload, "$.payload")
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": _string(raw["event_id"], "event_id", maximum=160),
        "parent_event_id": _string(raw["parent_event_id"], "parent_event_id", maximum=160, allow_empty=True),
        "decision_id": _string(raw["decision_id"], "decision_id", maximum=160),
        "position_id": _string(raw["position_id"], "position_id", maximum=160),
        "strategy_id": _string(raw["strategy_id"], "strategy_id", maximum=120),
        "strategy_source_sha256": _sha(raw["strategy_source_sha256"], "strategy_source_sha256"),
        "method_id": _string(raw["method_id"], "method_id", maximum=120),
        "skill_set": _strings(raw["skill_set"], "skill_set"),
        "team_id": _string(raw["team_id"], "team_id", maximum=80),
        "symbol": _string(raw["symbol"], "symbol", maximum=30).upper(),
        "side": side,
        "market_snapshot_sha256": _sha(raw["market_snapshot_sha256"], "market_snapshot_sha256"),
        "risk_snapshot_sha256": _sha(raw["risk_snapshot_sha256"], "risk_snapshot_sha256"),
        "sequence_no": sequence,
        "event_ts": _timestamp(raw["event_ts"]),
        "idempotency_key": _string(raw["idempotency_key"], "idempotency_key", maximum=200),
        "event_type": event_type,
        "payload": payload,
        "source_ids": _strings(raw["source_ids"], "source_ids", allow_empty=False),
        "authority": normalize_authority(raw["authority"]),
    }
    if event_type == "formal_ledger_joined" and event["authority"]["formal_ledger_write_allowed"] is not True:
        _fail("FORMAL_LEDGER_AUTHORITY_REQUIRED")
    if event_type != "formal_ledger_joined" and event["authority"]["formal_ledger_write_allowed"] is True:
        _fail("FORMAL_LEDGER_AUTHORITY_SCOPE_INVALID")
    event_sha = canonical_sha(event)
    if require_sealed_sha and _sha(raw.get("event_sha256"), "event_sha256") != event_sha:
        _fail("EVENT_SHA_MISMATCH")
    event["event_sha256"] = event_sha
    return event


def default_authority(*, runtime_bound: bool, formal_ledger_write_allowed: bool = False) -> dict[str, Any]:
    return {
        "shadow_only": True,
        "runtime_bound": runtime_bound,
        "formal_ledger_write_allowed": formal_ledger_write_allowed,
        "paper_allowed": False,
        "live_allowed": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
