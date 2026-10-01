"""Shared source-volume admission and adapters for existing exact25 components.

No source field is relabelled by config alone. This verifies a supplied,
hash-bound input contract; it does not discover or prove missing unit authority.
Unknown canonical BingX volume therefore stays blocked. No execution/FULL.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

from backend.research.rebuild import scalp7_exact25_indicators_v1 as indicators
from backend.research.rebuild import scalp7_exact25_reference_v1 as reference

VERSION = "EXACT25_SHARED_VOLUME_ADMISSION_V1"
INDICATORS = ("bb_revert", "obv_trend", "mfi_rsi_div")
VWAPS = ("anchor_vwap_trend", "vwap_revert")
STRATEGIES = INDICATORS + VWAPS


def requirements(strategy_id: str, volume_basis: str | None = None) -> dict[str, Any]:
    if strategy_id not in STRATEGIES:
        raise ValueError("UNKNOWN_VOLUME_COMPONENT")
    if strategy_id in VWAPS and volume_basis not in (
        "BASE_QUOTE_SUMS",
        "HLC3_BASE_PROXY",
    ):
        raise ValueError("EXPLICIT_VOLUME_BASIS_REQUIRED")
    quote = strategy_id in VWAPS and volume_basis == "BASE_QUOTE_SUMS"
    return {
        "version": VERSION,
        "strategy_id": strategy_id,
        "required_observed_units": ["BASE", "QUOTE"] if quote else ["BASE"],
        "source_schema_and_revision_binding": True,
        "volume_availability": "MAX_PRICE_AND_REQUIRED_VOLUME_FIELD_AVAILABILITY",
        "cumulative_dependency_availability": True,
        "quote_synthesis": False,
        "volume_basis": volume_basis if strategy_id in VWAPS else "OBSERVED_BASE",
        "hlc3_proxy_is_trade_vwap": False,
        "complete_strategy": False,
        "economic_runs": 0,
    }


def _text(value: Any, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("MISSING_VOLUME_BINDING:" + key)
    return value


def _hash(value: Any, key: str) -> str:
    value = _text(value, key)
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("INVALID_VOLUME_BINDING_HASH:" + key)
    if value == "0" * 64:
        raise ValueError("EMPTY_VOLUME_BINDING_HASH:" + key)
    return value


def _number(value: Any, key: str) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_VOLUME_VALUE:" + key)
    try:
        answer = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("INVALID_VOLUME_VALUE:" + key) from exc
    if not math.isfinite(answer):
        raise ValueError("INVALID_VOLUME_VALUE:" + key)
    return answer


def _stamp(value: Any, key: str) -> int:
    result = _number(value, key)
    if result < 0 or result != int(result):
        raise ValueError("INVALID_VOLUME_CLOCK:" + key)
    return int(result)


def binding_digest(binding: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(binding), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _binding(
    symbol: str, frame: pd.DataFrame, binding: Mapping[str, Any], units: list[str]
) -> None:
    if binding.get("schema") != VERSION:
        raise ValueError("SOURCE_VOLUME_BINDING_REQUIRED")
    if frame.attrs.get("volume_units") not in ("BASE", "BASE_AND_QUOTE"):
        raise ValueError("UNPROVEN_CANONICAL_VOLUME_UNITS")
    if binding.get("price_type") not in (None, "last"):
        raise ValueError("SOURCE_PRICE_TYPE_CONFLICT")
    if frame.attrs.get("price_type") not in (None, "last"):
        raise ValueError("SOURCE_PRICE_TYPE_CONFLICT")
    if frame.attrs.get("price_basis") not in (None, "LAST_PRICE"):
        raise ValueError("SOURCE_PRICE_BASIS_CONFLICT")
    for key in ("venue", "product", "base_asset", "quote_asset"):
        _text(binding.get(key), key)
    if binding.get("instrument") != symbol:
        raise ValueError("VOLUME_INSTRUMENT_MISMATCH")
    if binding.get("price_unit") != binding["quote_asset"]:
        raise ValueError("VOLUME_PRICE_DIMENSION_MISMATCH")
    kind = frame.attrs.get("data_kind")
    if kind == "SYNTHETIC_FIXTURE":
        if (
            frame.attrs.get("fixture_label") != "SYNTHETIC_UNIT_TEST_ONLY"
            or binding.get("evidence_kind") != "SYNTHETIC_TEST_ONLY"
        ):
            raise ValueError("VOLUME_FIXTURE_LABEL_REQUIRED")
    elif kind == "GENUINE_RAW_HISTORY":
        if binding.get("evidence_kind") != "HASH_BOUND_SOURCE_SCHEMA":
            raise ValueError("ACTUAL_SCHEMA_VOLUME_AUTHORITY_REQUIRED")
    else:
        raise ValueError("EXPLICIT_VOLUME_DATA_KIND_REQUIRED")
    _text(binding.get("source_unit_authority_locator"), "source_unit_authority_locator")
    for key in (
        "source_revision_sha256",
        "source_schema_sha256",
        "source_unit_authority_sha256",
    ):
        digest = _hash(binding.get(key), key)
        if frame.attrs.get(key) != digest:
            raise ValueError("SOURCE_VOLUME_EVIDENCE_BINDING_MISMATCH:" + key)
    fields = binding.get("fields")
    if not isinstance(fields, Mapping):
        raise ValueError("OBSERVED_VOLUME_FIELDS_REQUIRED")
    used: set[str] = set()
    for unit in units:
        field = fields.get(unit.lower())
        if not isinstance(field, Mapping):
            raise ValueError("MISSING_OBSERVED_" + unit + "_VOLUME")
        name = _text(field.get("value"), "value_field")
        clock = _text(field.get("available"), "available_field")
        if name in used or name == clock:
            raise ValueError("BASE_QUOTE_FIELD_ALIAS_FORBIDDEN")
        used.add(name)
        if name not in frame or clock not in frame:
            raise ValueError("MISSING_SOURCE_VOLUME_COLUMN:" + name)
        asset = binding["base_asset" if unit == "BASE" else "quote_asset"]
        if field.get("unit") != unit or field.get("asset") != asset:
            raise ValueError("OBSERVED_VOLUME_DIMENSION_MISMATCH:" + unit)
        if frame.attrs.get("volume_field_units", {}).get(name) != unit:
            raise ValueError("SOURCE_FIELD_UNIT_BINDING_MISMATCH:" + name)
        if field.get("observed") is not True:
            raise ValueError("SYNTHESIZED_VOLUME_FORBIDDEN:" + unit)


def adapt_volume_frame(
    symbol: str,
    frame: pd.DataFrame,
    binding: Mapping[str, Any],
    strategy_id: str,
    *,
    volume_basis: str | None = None,
) -> pd.DataFrame:
    """Map actual fields, preserve evidence, and join their availability clocks."""
    contract = requirements(strategy_id, volume_basis)
    units = contract["required_observed_units"]
    _binding(symbol, frame, binding, units)
    required = {
        "open_ts_ms",
        "close_ts_ms",
        "available_ts_ms",
        "segment_id",
        "open",
        "high",
        "low",
        "close",
    }
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError("PRICE_CLOCK_FRAME_REQUIRED")
    result = frame.copy(deep=True)
    binding_fields = binding["fields"]
    records = result.to_dict("records")
    available: list[int] = []
    base: list[float] = []
    quote: list[float] = []
    prior: dict[str, Any] | None = None
    for row in records:
        if row.get("price_type") not in (None, "last"):
            raise ValueError("SOURCE_PRICE_TYPE_CONFLICT")
        opening = _stamp(row["open_ts_ms"], "open_ts_ms")
        closing = _stamp(row["close_ts_ms"], "close_ts_ms")
        price_known = _stamp(row["available_ts_ms"], "available_ts_ms")
        if not opening < closing <= price_known:
            raise ValueError("UNAVAILABLE_VOLUME_PRICE_BAR")
        if "volume_unit" in row and str(row["volume_unit"]).upper() != "BASE":
            raise ValueError("MIXED_SOURCE_VOLUME_UNITS:BASE")
        if prior is not None and opening < prior["close"]:
            raise ValueError("NONCHRONOLOGICAL_VOLUME_BARS")
        known = price_known
        values = {}
        for unit in units:
            field = binding_fields[unit.lower()]
            value = _number(row[field["value"]], field["value"])
            clock = _stamp(row[field["available"]], field["available"])
            if value < 0 or clock < closing:
                raise ValueError("NEGATIVE_OR_PREMATURE_" + unit + "_VOLUME")
            label = field.get("unit_field")
            if label is not None and row.get(label) != unit:
                raise ValueError("MIXED_SOURCE_VOLUME_UNITS:" + unit)
            values[unit] = value
            known = max(known, clock)
        if prior is not None and (
            opening == prior["close"] and row["segment_id"] == prior["segment"]
        ):
            known = max(known, prior["known"])
        base.append(values["BASE"])
        if "QUOTE" in values:
            quote.append(values["QUOTE"])
        available.append(known)
        prior = {"close": closing, "segment": row["segment_id"], "known": known}
    result["available_ts_ms"] = available
    result["volume"] = base
    result["volume_base"] = base
    if quote:
        result["volume_quote"] = quote
    else:
        # An existing misleading quote column cannot become admitted evidence.
        result = result.drop(columns=["volume_quote"], errors="ignore")
    result["volume_unit"] = "BASE" if strategy_id in VWAPS else "base"
    result["price_type"] = "last"
    result.attrs = {
        **copy.deepcopy(frame.attrs),
        "volume_adapter_version": VERSION,
        "volume_binding_sha256": binding_digest(binding),
        "volume_component_requirements": contract,
        "volume_fields_synthesized": False,
        "price_type": "last",
        "price_basis": "LAST_PRICE",
    }
    return result


def evaluate_volume_component(
    strategy_id: str,
    frames: dict[str, pd.DataFrame],
    config: dict[str, Any],
    bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Admit common inputs then call existing formulas; no model or economics."""
    if strategy_id not in STRATEGIES:
        raise ValueError("UNKNOWN_VOLUME_COMPONENT")
    outputs = {}
    contracts: dict[str, dict[str, Any] | None] = {}
    for symbol, frame in sorted(frames.items()):
        own = {**config, **config.get("symbol_configs", {}).get(symbol, {})}
        contracts[symbol] = None
        try:
            actual_basis = own.get("volume_basis") if strategy_id in VWAPS else None
            contracts[symbol] = requirements(strategy_id, actual_basis)
            if own.get("price_type") not in (None, "last"):
                raise ValueError("CALLER_PRICE_TYPE_CONFLICT")
            expected = "BASE" if strategy_id in VWAPS else "base"
            if own.get("volume_unit") not in (None, expected):
                raise ValueError("CALLER_VOLUME_UNIT_CONFLICT")
            adapted = adapt_volume_frame(
                symbol,
                frame,
                bindings.get(symbol, {}),
                strategy_id,
                volume_basis=actual_basis,
            )
            own["volume_unit"] = expected
            if strategy_id in VWAPS:
                output = reference.evaluate(strategy_id, {symbol: adapted}, own)
            else:
                own["price_type"] = "last"
                output = indicators.evaluate(strategy_id, {symbol: adapted}, own)
            output["volume_binding_sha256"] = adapted.attrs["volume_binding_sha256"]
        except (ValueError, TypeError, KeyError) as exc:
            output = {
                "status": "BLOCKED_VOLUME_INPUT_CONTRACT",
                "error": str(exc),
                "events": [],
                "intents": [],
                "components": [],
                "complete_strategy": False,
                "economic_runs": 0,
            }
        outputs[symbol] = output
    blocked = sum(
        str(out.get("status", "")).startswith("BLOCKED") for out in outputs.values()
    )
    resolved = list(contracts.values())
    common = resolved[0] if resolved else None
    contract = (
        common
        if common is not None and all(item == common for item in resolved)
        else {
            "version": VERSION,
            "strategy_id": strategy_id,
            "volume_basis": "PER_SYMBOL",
            "scope": "PER_SYMBOL_AFTER_CONFIG_MERGE",
            "per_symbol": contracts,
        }
    )
    return {
        "schema": VERSION,
        "strategy_id": strategy_id,
        "requirements": contract,
        "per_symbol_requirements": contracts,
        "status": (
            "BLOCKED_VOLUME_INPUT_CONTRACT"
            if not outputs or blocked == len(outputs)
            else (
                "MIXED_COMPONENT_AND_BLOCKED_INPUT"
                if blocked
                else "COMPONENT_INPUT_ADMITTED_ECONOMICS_NOT_RUN"
            )
        ),
        "per_symbol": outputs,
        "events": [row for out in outputs.values() for row in out["events"]],
        "intents": [row for out in outputs.values() for row in out["intents"]],
        "components": [row for out in outputs.values() for row in out["components"]],
        "complete_strategy": False,
        "economic_runs": 0,
        "order": "BLOCKED",
        "live": "BLOCKED",
        "promotion": False,
        "new_full_authority": False,
    }


def admit_observed_base_frame(
    symbol: str, frame: pd.DataFrame, binding: Mapping[str, Any]
) -> pd.DataFrame:
    """Admit direct BASE participation for other callers; calculate no indicator."""
    result = adapt_volume_frame(symbol, frame, binding, "obv_trend")
    result.attrs["volume_component_requirements"] = {
        **result.attrs["volume_component_requirements"],
        "strategy_id": "SHARED_OBSERVED_BASE_INPUT_ONLY",
    }
    return result
