from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "zel.paper_canary.day.v1"
BERLIN = ZoneInfo("Europe/Berlin")
PRIVATE_TOKENS = {"api_key", "apikey", "secret", "credential", "password", "private_key", "access_token", "refresh_token"}
DAILY_FIELDS = {
    "canary_id", "berlin_date", "period_start_ms", "period_end_ms", "observed_at_ms",
    "environment_kind", "source_ref", "source_sha256", "private_api_receipt_sha256",
    "oms_receipt_sha256", "shadow_receipt_sha256", "formal_ledger_sha256", "display_sha256",
    "closed_positions", "coverage_minutes", "lifecycle_mismatch_count", "ledger_mismatch_count",
    "display_mismatch_count", "duplicate_order_count", "orphan_order_count",
    "unreconciled_position_count", "threshold_breach_count", "fee_delta_bps",
    "slippage_delta_bps", "funding_delta_bps", "latency_p95_ms",
    "shadow_paper_net_delta_r", "source_authority_verified", "fixture_only",
}
POLICY_FIELDS = {
    "policy_ref", "policy_sha256", "minimum_calendar_days", "minimum_closed_positions",
    "minimum_daily_coverage_minutes", "maximum_fee_delta_bps", "maximum_slippage_delta_bps",
    "maximum_funding_delta_bps", "maximum_latency_p95_ms", "maximum_shadow_paper_net_delta_r",
}


class PaperCanaryError(ValueError):
    pass


def _fail(code: str, detail: str = "") -> None:
    raise PaperCanaryError(f"{code}:{detail}" if detail else code)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("OBJECT_REQUIRED", name)
    return dict(value)


def _string(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("STRING_REQUIRED", name)
    result = value.strip()
    if len(result) > maximum:
        _fail("STRING_TOO_LONG", name)
    return result


def _sha(value: Any, name: str) -> str:
    result = _string(value, name, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        _fail("SHA256_REQUIRED", name)
    return result


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail("INT_REQUIRED", name)
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("NUMBER_REQUIRED", name)
    result = float(value)
    if not math.isfinite(result):
        _fail("NUMBER_NOT_FINITE", name)
    return result


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


def normalize_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, "policy")
    missing = sorted(POLICY_FIELDS - set(raw))
    if missing:
        _fail("POLICY_FIELDS_MISSING", ",".join(missing))
    policy = {
        "policy_ref": _string(raw["policy_ref"], "policy_ref"),
        "policy_sha256": _sha(raw["policy_sha256"], "policy_sha256"),
        "minimum_calendar_days": _int(raw["minimum_calendar_days"], "minimum_calendar_days", 30),
        "minimum_closed_positions": _int(raw["minimum_closed_positions"], "minimum_closed_positions", 1),
        "minimum_daily_coverage_minutes": _int(raw["minimum_daily_coverage_minutes"], "minimum_daily_coverage_minutes", 1),
        "maximum_fee_delta_bps": _number(raw["maximum_fee_delta_bps"], "maximum_fee_delta_bps"),
        "maximum_slippage_delta_bps": _number(raw["maximum_slippage_delta_bps"], "maximum_slippage_delta_bps"),
        "maximum_funding_delta_bps": _number(raw["maximum_funding_delta_bps"], "maximum_funding_delta_bps"),
        "maximum_latency_p95_ms": _number(raw["maximum_latency_p95_ms"], "maximum_latency_p95_ms"),
        "maximum_shadow_paper_net_delta_r": _number(raw["maximum_shadow_paper_net_delta_r"], "maximum_shadow_paper_net_delta_r"),
    }
    if policy["minimum_calendar_days"] < 30:
        _fail("PAPER_DAYS_BELOW_30")
    return policy


def normalize_day(value: Mapping[str, Any], *, now_ms: int) -> dict[str, Any]:
    raw = _mapping(value, "day")
    _reject_private(raw)
    missing = sorted(DAILY_FIELDS - set(raw))
    if missing:
        _fail("DAY_FIELDS_MISSING", ",".join(missing))
    start = _int(raw["period_start_ms"], "period_start_ms", 1)
    end = _int(raw["period_end_ms"], "period_end_ms", 1)
    observed = _int(raw["observed_at_ms"], "observed_at_ms", 1)
    if not start < end <= observed <= now_ms + 300_000:
        _fail("DAY_TIME_ORDER_INVALID")
    local_start = datetime.fromtimestamp(start / 1000, tz=BERLIN)
    local_end = datetime.fromtimestamp((end - 1) / 1000, tz=BERLIN)
    date_text = _string(raw["berlin_date"], "berlin_date", maximum=10)
    if local_start.date().isoformat() != date_text or local_end.date().isoformat() != date_text:
        _fail("BERLIN_DATE_PERIOD_MISMATCH", date_text)
    if _string(raw["environment_kind"], "environment_kind", maximum=40) != "VPS_RUNTIME":
        _fail("VPS_RUNTIME_EVIDENCE_REQUIRED")
    source_ref = _string(raw["source_ref"], "source_ref")
    if not source_ref.startswith("runtime:"):
        _fail("RUNTIME_SOURCE_REF_REQUIRED")
    if raw["source_authority_verified"] is not True:
        _fail("SOURCE_AUTHORITY_NOT_VERIFIED")
    if not isinstance(raw["fixture_only"], bool):
        _fail("BOOL_REQUIRED", "fixture_only")
    counts = {
        key: _int(raw[key], key)
        for key in (
            "closed_positions", "coverage_minutes", "lifecycle_mismatch_count", "ledger_mismatch_count",
            "display_mismatch_count", "duplicate_order_count", "orphan_order_count",
            "unreconciled_position_count", "threshold_breach_count",
        )
    }
    metrics = {
        key: _number(raw[key], key)
        for key in (
            "fee_delta_bps", "slippage_delta_bps", "funding_delta_bps",
            "latency_p95_ms", "shadow_paper_net_delta_r",
        )
    }
    day = {
        "schema_version": SCHEMA_VERSION,
        "canary_id": _string(raw["canary_id"], "canary_id"),
        "berlin_date": date_text,
        "period_start_ms": start,
        "period_end_ms": end,
        "observed_at_ms": observed,
        "environment_kind": "VPS_RUNTIME",
        "source_ref": source_ref,
        "source_sha256": _sha(raw["source_sha256"], "source_sha256"),
        "private_api_receipt_sha256": _sha(raw["private_api_receipt_sha256"], "private_api_receipt_sha256"),
        "oms_receipt_sha256": _sha(raw["oms_receipt_sha256"], "oms_receipt_sha256"),
        "shadow_receipt_sha256": _sha(raw["shadow_receipt_sha256"], "shadow_receipt_sha256"),
        "formal_ledger_sha256": _sha(raw["formal_ledger_sha256"], "formal_ledger_sha256"),
        "display_sha256": _sha(raw["display_sha256"], "display_sha256"),
        **counts,
        **metrics,
        "source_authority_verified": True,
        "fixture_only": raw["fixture_only"],
        "paper_only": True,
        "live_allowed": False,
        "capital_scale_allowed": False,
        "order_authority": "PAPER_CANARY_ONLY",
    }
    day["day_payload_sha256"] = canonical_sha(day)
    return day


def normalize_drill(value: Mapping[str, Any], *, now_ms: int) -> dict[str, Any]:
    raw = _mapping(value, "drill")
    _reject_private(raw)
    required = {"canary_id", "drill_id", "drill_type", "passed", "occurred_at_ms", "evidence_sha256", "source_ref"}
    missing = sorted(required - set(raw))
    if missing:
        _fail("DRILL_FIELDS_MISSING", ",".join(missing))
    drill_type = _string(raw["drill_type"], "drill_type", maximum=30).upper()
    if drill_type not in {"RESTART_RECOVERY", "ROLLBACK"}:
        _fail("DRILL_TYPE_INVALID", drill_type)
    if raw["passed"] is not True:
        _fail("DRILL_MUST_PASS", drill_type)
    occurred = _int(raw["occurred_at_ms"], "occurred_at_ms", 1)
    if occurred > now_ms + 300_000:
        _fail("DRILL_FUTURE_TIMESTAMP")
    source_ref = _string(raw["source_ref"], "drill.source_ref")
    if not source_ref.startswith("runtime:"):
        _fail("RUNTIME_SOURCE_REF_REQUIRED")
    drill = {
        "schema_version": "zel.paper_canary.drill.v1",
        "canary_id": _string(raw["canary_id"], "canary_id"),
        "drill_id": _string(raw["drill_id"], "drill_id"),
        "drill_type": drill_type,
        "passed": True,
        "occurred_at_ms": occurred,
        "evidence_sha256": _sha(raw["evidence_sha256"], "evidence_sha256"),
        "source_ref": source_ref,
    }
    drill["drill_sha256"] = canonical_sha(drill)
    return drill
