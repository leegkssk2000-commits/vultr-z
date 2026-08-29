from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping

from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as base

DEFAULT_MODEL = "gpt-5-mini"
MAX_OUTPUT_TOKENS = 8000
MAX_CANDIDATES = 6

STRING_220 = {"type": "string", "maxLength": 220}
STRING_320 = {"type": "string", "maxLength": 320}
SOURCE_ENUM = ["ohlcv", "volume", "funding", "basis", "open_interest", "l2_order_book", "trade_flow"]

EXECUTABLE_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bar_interval": {"type": "string", "enum": ["5m", "15m", "30m", "1h", "4h", "1d"]},
        "features": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 80},
                    "formula": {"type": "string", "maxLength": 240},
                },
                "required": ["name", "formula"],
                "additionalProperties": False,
            },
        },
        "entry_rule": STRING_320,
        "side_rule": STRING_220,
        "exit_rule": STRING_320,
        "max_hold_bars": {"type": "integer", "minimum": 1, "maximum": 720},
        "entry_timing": STRING_220,
        "cost_model": STRING_220,
        "development_data_rule": STRING_320,
        "parameter_provenance": STRING_320,
    },
    "required": [
        "bar_interval", "features", "entry_rule", "side_rule", "exit_rule",
        "max_hold_bars", "entry_timing", "cost_model", "development_data_rule",
        "parameter_provenance",
    ],
    "additionalProperties": False,
}

CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string", "maxLength": 120},
        "mode": {"type": "string", "enum": ["REPAIR", "NEW_ARCHITECTURE"]},
        "strategy_id": {"type": "string", "maxLength": 120},
        "architecture_family": STRING_220,
        "changed_axis": STRING_220,
        "mechanism": STRING_320,
        "payer": STRING_220,
        "entry_event": STRING_320,
        "direction_rule": STRING_220,
        "native_horizon": STRING_220,
        "regime_owner": STRING_320,
        "invalidation": STRING_320,
        "exit_logic": STRING_320,
        "time_stop_rationale": STRING_220,
        "turnover_cost_budget": STRING_320,
        "required_sources": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {"type": "string", "enum": SOURCE_ENUM},
        },
        "evidence_ids": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 80},
        },
        "expected_move_cost_multiple_target": {"type": "number"},
        "falsification": STRING_320,
        "forbidden_changes": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 120},
        },
        "why_distinct": STRING_320,
        "executable_spec": EXECUTABLE_SPEC_SCHEMA,
    },
    "required": [
        "candidate_id", "mode", "strategy_id", "architecture_family", "changed_axis",
        "mechanism", "payer", "entry_event", "direction_rule", "native_horizon",
        "regime_owner", "invalidation", "exit_logic", "time_stop_rationale",
        "turnover_cost_budget", "required_sources", "evidence_ids",
        "expected_move_cost_multiple_target", "falsification", "forbidden_changes",
        "why_distinct", "executable_spec",
    ],
    "additionalProperties": False,
}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "maxItems": MAX_CANDIDATES,
            "items": CANDIDATE_SCHEMA,
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}


def _usage(payload: Mapping[str, Any]) -> dict[str, str]:
    raw = payload.get("usage")
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = raw.get(key)
        if isinstance(value, (int, float)):
            out[key] = str(int(value))
    return out


def _incomplete_reason(payload: Mapping[str, Any]) -> str:
    raw = payload.get("incomplete_details")
    if isinstance(raw, Mapping):
        return str(raw.get("reason") or "unknown")
    return "unknown"


def _lineage(prompt: str, text: str, payload: Mapping[str, Any], requested_model: str) -> dict[str, str]:
    return {
        "prompt_sha": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "response_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "requested_model": requested_model,
        "response_status": str(payload.get("status") or "unknown"),
        "incomplete_reason": _incomplete_reason(payload),
        "structured_output": "true",
        "strict_schema": "true",
        "output_chars": str(len(text)),
        "max_output_tokens": str(MAX_OUTPUT_TOKENS),
        "max_candidates": str(MAX_CANDIDATES),
        **_usage(payload),
    }


def call_openai_generator(prompt: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    if not key:
        raise RuntimeError("OPENAI_API_KEY_MISSING")

    roi_prompt = (
        "ROI OUTPUT CONTRACT OVERRIDES ANY LARGER COUNT REQUEST: return at most "
        f"{MAX_CANDIDATES} total candidates, prioritized by causal/economic leverage. "
        "Keep prose fields concise and deterministic. Every candidate must include a complete "
        "EXECUTABLE_DSL_V1 executable_spec. Do not spend output on restating the prompt.\n"
        + prompt
    )
    body = {
        "model": model,
        "store": False,
        "instructions": (
            "Return only the requested strategy architecture JSON. No tools or external web. "
            "Use the strict schema; concise fields; no markdown."
        ),
        "input": roi_prompt,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "minimal"},
        "text": {
            "format": {
                "type": "json_schema",
                "name": "a1_architecture_factory_hardened",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            }
        },
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=base.canonical(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:800]
        raise RuntimeError(f"OPENAI_FACTORY_HTTP_{exc.code}:{detail}") from exc

    text = base.extract_openai_text(payload)
    lineage = _lineage(roi_prompt, text, payload, model)
    if str(payload.get("status") or "").lower() == "incomplete":
        raise RuntimeError(
            "OPENAI_FACTORY_INCOMPLETE:"
            f"reason={lineage['incomplete_reason']}:"
            f"input_tokens={lineage.get('input_tokens','unknown')}:"
            f"output_tokens={lineage.get('output_tokens','unknown')}:"
            f"output_chars={lineage['output_chars']}:max_output_tokens={MAX_OUTPUT_TOKENS}"
        )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "OPENAI_FACTORY_JSON_INVALID:"
            f"{exc.msg}:line={exc.lineno}:col={exc.colno}:"
            f"output_tokens={lineage.get('output_tokens','unknown')}:"
            f"output_chars={lineage['output_chars']}:status={lineage['response_status']}"
        ) from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("candidates"), list):
        raise RuntimeError("OPENAI_FACTORY_SCHEMA_OBJECT_REQUIRED")
    return model, parsed, lineage


def self_test() -> int:
    assert MAX_OUTPUT_TOKENS == 8000
    assert MAX_CANDIDATES == 6
    assert RESPONSE_SCHEMA["properties"]["candidates"]["maxItems"] == 6
    fake = {
        "status": "completed",
        "usage": {"input_tokens": 123, "output_tokens": 45, "total_tokens": 168},
    }
    u = _usage(fake)
    assert u == {"input_tokens": "123", "output_tokens": "45", "total_tokens": "168"}
    assert _incomplete_reason({"incomplete_details": {"reason": "max_output_tokens"}}) == "max_output_tokens"
    print("PASS_OPENAI_GENERATOR_HARDENED_V1_SELF_TEST")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
