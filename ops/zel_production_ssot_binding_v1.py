from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = "zel.production_ssot_binding.v1"
RECEIPT_SCHEMA = "zel.production_ssot_binding_receipt.v1"
TARGET_ENV = "/etc/zel/production-paper-loop.env"

EXPECTED = {
    "ZEL_DATA_STALE_MS": "ms",
    "ZEL_ACCOUNT_STALE_MS": "ms",
    "ZEL_MAX_DD_DAY_PCT": "pct",
    "ZEL_MAX_DD_TOTAL_PCT": "pct",
    "ZEL_ALPHA_SIGNAL_STALE_MS": "ms",
    "ZEL_PAPER_INITIAL_EQUITY_USDT": "USDT",
    "ZEL_RISK_DAY_TZ": "timezone",
    "ZEL_IMPROVE_MIN_TRADES": "trades",
    "ZEL_IMPROVE_MIN_EXPECTANCY": "score",
    "ZEL_IMPROVE_MIN_PF": "ratio",
    "ZEL_IMPROVE_MIN_NET_PNL": "USDT",
    "ZEL_IMPROVE_MAX_DD_PCT": "pct",
    "ZEL_IMPROVE_MIN_SCORE_GAIN": "score",
    "ZEL_IMPROVE_MAX_DD_REGRESSION_PCT": "pct",
    "ZEL_IMPROVE_ERROR_BUDGET": "count",
}
ORDER = tuple(EXPECTED)
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fail(reason: str) -> None:
    raise RuntimeError(reason)


def as_finite(value: Any, key: str) -> float:
    if isinstance(value, bool):
        fail(f"SSOT_VALUE_BOOLEAN_FORBIDDEN:{key}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"SSOT_VALUE_NUMERIC_INVALID:{key}") from exc
    if not math.isfinite(out):
        fail(f"SSOT_VALUE_NONFINITE:{key}")
    return out


def as_integer(value: Any, key: str) -> int:
    out = as_finite(value, key)
    if not out.is_integer():
        fail(f"SSOT_VALUE_INTEGER_REQUIRED:{key}")
    return int(out)


def validate_value(key: str, value: Any) -> str:
    if key in {"ZEL_DATA_STALE_MS", "ZEL_ACCOUNT_STALE_MS", "ZEL_ALPHA_SIGNAL_STALE_MS"}:
        out = as_integer(value, key)
        if out <= 0:
            fail(f"SSOT_STALE_MS_MUST_BE_POSITIVE:{key}")
        return str(out)

    if key in {"ZEL_MAX_DD_DAY_PCT", "ZEL_MAX_DD_TOTAL_PCT", "ZEL_IMPROVE_MAX_DD_PCT", "ZEL_IMPROVE_MAX_DD_REGRESSION_PCT"}:
        out = as_finite(value, key)
        if out < 0 or out > 100:
            fail(f"SSOT_PERCENT_OUT_OF_RANGE:{key}")
        return format(out, ".15g")

    if key == "ZEL_PAPER_INITIAL_EQUITY_USDT":
        out = as_finite(value, key)
        if out <= 0:
            fail("SSOT_PAPER_EQUITY_MUST_BE_POSITIVE")
        return format(out, ".15g")

    if key == "ZEL_RISK_DAY_TZ":
        if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
            fail("SSOT_RISK_DAY_TZ_INVALID")
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise RuntimeError("SSOT_RISK_DAY_TZ_UNKNOWN") from exc
        return normalized

    if key == "ZEL_IMPROVE_MIN_TRADES":
        out = as_integer(value, key)
        if out < 1:
            fail("SSOT_IMPROVE_MIN_TRADES_MUST_BE_POSITIVE")
        return str(out)

    if key == "ZEL_IMPROVE_ERROR_BUDGET":
        out = as_integer(value, key)
        if out < 0:
            fail("SSOT_IMPROVE_ERROR_BUDGET_NEGATIVE")
        return str(out)

    if key == "ZEL_IMPROVE_MIN_PF":
        out = as_finite(value, key)
        if out < 0:
            fail("SSOT_IMPROVE_MIN_PF_NEGATIVE")
        return format(out, ".15g")

    if key in {"ZEL_IMPROVE_MIN_EXPECTANCY", "ZEL_IMPROVE_MIN_NET_PNL", "ZEL_IMPROVE_MIN_SCORE_GAIN"}:
        return format(as_finite(value, key), ".15g")

    fail(f"SSOT_UNKNOWN_KEY:{key}")
    raise AssertionError


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != SCHEMA:
        fail("SSOT_SCHEMA_INVALID")
    if str(manifest.get("mode") or "").upper() != "PAPER":
        fail("SSOT_NON_PAPER_FORBIDDEN")
    if manifest.get("authority") != "Z_POLICY v3.0 / SSOT":
        fail("SSOT_AUTHORITY_INVALID")
    if manifest.get("target_env_path") != TARGET_ENV:
        fail("SSOT_TARGET_ENV_INVALID")
    if manifest.get("order_authority") != "BLOCKED" or manifest.get("live_trade_authority") != "BLOCKED":
        fail("SSOT_LIVE_OR_ORDER_AUTHORITY_FORBIDDEN")
    if manifest.get("exchange_order_submitted") is not False:
        fail("SSOT_EXCHANGE_SUBMISSION_MUST_BE_FALSE")

    rules = manifest.get("binding_rules")
    if not isinstance(rules, Mapping):
        fail("SSOT_BINDING_RULES_MISSING")
    required_rules = {
        "require_all_15": True,
        "require_source_ref": True,
        "require_source_sha256": True,
        "partial_env_write_allowed": False,
        "atomic_replace_required": True,
        "rollback_required": True,
    }
    for key, expected in required_rules.items():
        if rules.get(key) is not expected:
            fail(f"SSOT_BINDING_RULE_INVALID:{key}")

    bindings = manifest.get("bindings")
    if not isinstance(bindings, Mapping):
        fail("SSOT_BINDINGS_MISSING")
    if set(bindings) != set(EXPECTED):
        missing = sorted(set(EXPECTED) - set(bindings))
        extra = sorted(set(bindings) - set(EXPECTED))
        fail(f"SSOT_BINDING_KEYSET_INVALID:missing={missing}:extra={extra}")

    missing_values: list[str] = []
    normalized: dict[str, str] = {}
    sources: dict[str, dict[str, str]] = {}
    for key in ORDER:
        row = bindings[key]
        if not isinstance(row, Mapping):
            fail(f"SSOT_BINDING_ROW_INVALID:{key}")
        if row.get("unit") != EXPECTED[key]:
            fail(f"SSOT_UNIT_INVALID:{key}")
        value = row.get("value")
        source_ref = row.get("source_ref")
        source_sha = row.get("source_sha256")

        if value is None:
            if source_ref is not None or source_sha is not None:
                fail(f"SSOT_PARTIAL_PROVENANCE_FOR_UNBOUND_VALUE:{key}")
            missing_values.append(key)
            continue

        if not isinstance(source_ref, str) or not source_ref.strip():
            fail(f"SSOT_SOURCE_REF_REQUIRED:{key}")
        if "\n" in source_ref or "\r" in source_ref:
            fail(f"SSOT_SOURCE_REF_INVALID:{key}")
        if not isinstance(source_sha, str) or not HEX64.fullmatch(source_sha):
            fail(f"SSOT_SOURCE_SHA256_INVALID:{key}")

        normalized[key] = validate_value(key, value)
        sources[key] = {
            "source_ref": source_ref.strip(),
            "source_sha256": source_sha.lower(),
        }

    ready = not missing_values
    env_text = None
    if ready:
        env_text = "\n".join(f"{key}={normalized[key]}" for key in ORDER) + "\n"

    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "state": "PASS_SSOT_BINDING_READY" if ready else "HOLD_SSOT_BINDING_INCOMPLETE",
        "ready": ready,
        "required_key_count": len(ORDER),
        "bound_key_count": len(normalized),
        "missing_key_count": len(missing_values),
        "missing_keys": missing_values,
        "normalized_values": normalized,
        "sources": sources,
        "env_sha256": hashlib.sha256(env_text.encode("utf-8")).hexdigest() if env_text is not None else None,
        "target_env_path": TARGET_ENV,
        "env_write_allowed": ready,
        "partial_env_write_allowed": False,
        "exchange_order_submitted": False,
        "live_trade_authority": "BLOCKED",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    if env_text is not None:
        receipt["env_text"] = env_text
    return receipt


def load_json(path: Path) -> dict[str, Any]:
    row = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(row, dict):
        fail("SSOT_MANIFEST_NOT_OBJECT")
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ZEL production SSOT binding manifest")
    parser.add_argument("--manifest", type=Path, default=Path("config/zel_production_ssot_binding_v1.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-out", type=Path, default=None)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    result = validate_manifest(load_json(args.manifest))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    public = dict(result)
    env_text = public.pop("env_text", None)
    args.out.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if env_text is not None and args.env_out is not None:
        args.env_out.parent.mkdir(parents=True, exist_ok=True)
        args.env_out.write_text(env_text, encoding="utf-8")
    elif args.env_out is not None and args.env_out.exists():
        fail("SSOT_INCOMPLETE_MUST_NOT_TOUCH_EXISTING_ENV_OUT")

    print(json.dumps({
        "state": result["state"],
        "ready": result["ready"],
        "bound_key_count": result["bound_key_count"],
        "missing_key_count": result["missing_key_count"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    if args.require_ready and not result["ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
