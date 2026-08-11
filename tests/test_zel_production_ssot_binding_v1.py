import copy

import pytest

from ops.zel_production_ssot_binding_v1 import EXPECTED, validate_manifest


SHA = "a" * 64


def manifest():
    return {
        "schema_version": "zel.production_ssot_binding.v1",
        "state": "HOLD_UNBOUND",
        "mode": "PAPER",
        "authority": "Z_POLICY v3.0 / SSOT",
        "target_env_path": "/etc/zel/production-paper-loop.env",
        "bindings": {
            key: {"value": None, "unit": unit, "source_ref": None, "source_sha256": None}
            for key, unit in EXPECTED.items()
        },
        "binding_rules": {
            "require_all_15": True,
            "require_source_ref": True,
            "require_source_sha256": True,
            "partial_env_write_allowed": False,
            "atomic_replace_required": True,
            "rollback_required": True,
        },
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def complete_values():
    return {
        "ZEL_DATA_STALE_MS": 1000,
        "ZEL_ACCOUNT_STALE_MS": 1000,
        "ZEL_MAX_DD_DAY_PCT": 1.0,
        "ZEL_MAX_DD_TOTAL_PCT": 2.0,
        "ZEL_ALPHA_SIGNAL_STALE_MS": 1000,
        "ZEL_PAPER_INITIAL_EQUITY_USDT": 1000.0,
        "ZEL_RISK_DAY_TZ": "UTC",
        "ZEL_IMPROVE_MIN_TRADES": 10,
        "ZEL_IMPROVE_MIN_EXPECTANCY": 0.01,
        "ZEL_IMPROVE_MIN_PF": 1.1,
        "ZEL_IMPROVE_MIN_NET_PNL": 1.0,
        "ZEL_IMPROVE_MAX_DD_PCT": 5.0,
        "ZEL_IMPROVE_MIN_SCORE_GAIN": 0.1,
        "ZEL_IMPROVE_MAX_DD_REGRESSION_PCT": 1.0,
        "ZEL_IMPROVE_ERROR_BUDGET": 0,
    }


def bind_all(row):
    for key, value in complete_values().items():
        row["bindings"][key].update(
            value=value,
            source_ref=f"ssot:test/{key}",
            source_sha256=SHA,
        )
    return row


def test_all_null_is_valid_hold_and_renders_no_env():
    result = validate_manifest(manifest())
    assert result["state"] == "HOLD_SSOT_BINDING_INCOMPLETE"
    assert result["ready"] is False
    assert result["bound_key_count"] == 0
    assert result["missing_key_count"] == 15
    assert result["env_write_allowed"] is False
    assert "env_text" not in result
    assert result["exchange_order_submitted"] is False


def test_complete_binding_renders_exact_15_line_env():
    result = validate_manifest(bind_all(manifest()))
    assert result["state"] == "PASS_SSOT_BINDING_READY"
    assert result["ready"] is True
    assert result["bound_key_count"] == 15
    lines = result["env_text"].strip().splitlines()
    assert len(lines) == 15
    assert lines[0] == "ZEL_DATA_STALE_MS=1000"
    assert lines[-1] == "ZEL_IMPROVE_ERROR_BUDGET=0"
    assert result["env_sha256"]


def test_partial_provenance_for_null_value_fails_closed():
    row = manifest()
    row["bindings"]["ZEL_DATA_STALE_MS"]["source_ref"] = "ssot:test"
    with pytest.raises(RuntimeError, match="PARTIAL_PROVENANCE"):
        validate_manifest(row)


def test_bound_value_requires_source_hash_and_ref():
    row = manifest()
    row["bindings"]["ZEL_DATA_STALE_MS"]["value"] = 1000
    with pytest.raises(RuntimeError, match="SOURCE_REF_REQUIRED"):
        validate_manifest(row)
    row["bindings"]["ZEL_DATA_STALE_MS"]["source_ref"] = "ssot:test"
    with pytest.raises(RuntimeError, match="SOURCE_SHA256_INVALID"):
        validate_manifest(row)


def test_keyset_and_unit_are_exact():
    row = manifest()
    row["bindings"]["EXTRA"] = {"value": None, "unit": "x", "source_ref": None, "source_sha256": None}
    with pytest.raises(RuntimeError, match="KEYSET_INVALID"):
        validate_manifest(row)
    row = manifest()
    row["bindings"]["ZEL_DATA_STALE_MS"]["unit"] = "seconds"
    with pytest.raises(RuntimeError, match="UNIT_INVALID"):
        validate_manifest(row)


def test_invalid_timezone_and_percent_fail_closed():
    row = bind_all(manifest())
    row["bindings"]["ZEL_RISK_DAY_TZ"]["value"] = "Not/AZone"
    with pytest.raises(RuntimeError, match="TZ_UNKNOWN"):
        validate_manifest(row)
    row = bind_all(manifest())
    row["bindings"]["ZEL_MAX_DD_DAY_PCT"]["value"] = 101
    with pytest.raises(RuntimeError, match="PERCENT_OUT_OF_RANGE"):
        validate_manifest(row)


def test_live_or_order_authority_cannot_be_opened_by_manifest():
    for field in ("order_authority", "live_trade_authority"):
        row = copy.deepcopy(manifest())
        row[field] = "OPEN"
        with pytest.raises(RuntimeError, match="AUTHORITY_FORBIDDEN"):
            validate_manifest(row)
