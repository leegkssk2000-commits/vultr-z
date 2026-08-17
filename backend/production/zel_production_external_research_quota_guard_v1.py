from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production import zel_production_external_research_observer_v1 as core
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_external_research_quota_guard.v2"
QUOTA_STATES = {
    "HOLD_EXTERNAL_RESEARCH_QUOTA_EXHAUSTED",
    "HOLD_EXTERNAL_RESEARCH_QUOTA_COOLDOWN",
}
QUOTA_MARKERS = (
    "http_429",
    "http 429",
    "resource_exhausted",
    "quota",
    "rate limit",
    "rate_limit",
    "too many requests",
)
_RETRY_SECONDS = re.compile(r"(?:retry(?:delay)?|retry in)[^0-9]{0,40}(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def is_quota_error(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in QUOTA_MARKERS)


def quota_class(value: Any) -> str:
    text = str(value or "").lower()
    if not is_quota_error(text):
        return "NOT_QUOTA"
    if "prepayment credits are depleted" in text or "prepay" in text and "deplet" in text:
        return "PREPAY_DEPLETED"
    if "enable billing" in text or "set up billing" in text:
        return "BILLING_REQUIRED"
    if "free_tier" in text and ("limit: 0" in text or '"quotavalue":"0"' in text or "quotavalue': '0" in text):
        return "FREE_TIER_ZERO_LIMIT"
    if "perday" in text or "per_day" in text or "per day" in text or "requestsperday" in text or "tokensperday" in text:
        return "DAILY_QUOTA"
    if "spend" in text and ("10 minute" in text or "10-minute" in text or "10m" in text):
        return "SPEND_WINDOW"
    if "perminute" in text or "per_minute" in text or "per minute" in text or "persecond" in text or "per_second" in text:
        return "TRANSIENT_RATE_LIMIT"
    if "rate_limit_exceeded" in text or "requests per minute" in text or "tokens per minute" in text:
        return "TRANSIENT_RATE_LIMIT"
    if "retry in" in text or "retrydelay" in text:
        return "TRANSIENT_RATE_LIMIT"
    return "GENERIC_QUOTA"


def retry_delay_ms(value: Any) -> int | None:
    text = str(value or "")
    match = _RETRY_SECONDS.search(text)
    if not match:
        return None
    try:
        seconds = float(match.group(1))
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return int(seconds * 1000)


def recovery_policy(cfg: Mapping[str, Any], error: Any) -> dict[str, Any]:
    klass = quota_class(error)
    parsed_retry_ms = retry_delay_ms(error)
    fallback_ms = int(cfg["cooldown_ms"])

    if klass == "TRANSIENT_RATE_LIMIT":
        cooldown_ms = max(60_000, (parsed_retry_ms or 60_000) + 5_000)
        cooldown_ms = min(cooldown_ms, 15 * 60_000)
        source = "ERROR_RETRY_DELAY_OR_TRANSIENT_BACKOFF"
        manual = False
    elif klass == "SPEND_WINDOW":
        cooldown_ms = max(11 * 60_000, (parsed_retry_ms or 0) + 5_000)
        source = "GEMINI_SPEND_WINDOW_BACKOFF"
        manual = False
    elif klass in {"BILLING_REQUIRED", "PREPAY_DEPLETED", "FREE_TIER_ZERO_LIMIT"}:
        cooldown_ms = 2 * 60 * 60_000
        source = "BILLING_OR_PREPAY_RECHECK"
        manual = True
    elif klass == "DAILY_QUOTA":
        cooldown_ms = fallback_ms
        source = "DAILY_QUOTA_FALLBACK_COOLDOWN"
        manual = False
    else:
        cooldown_ms = fallback_ms
        source = "POLICY_FALLBACK_COOLDOWN"
        manual = False

    return {
        "quota_class": klass,
        "cooldown_ms": int(cooldown_ms),
        "quota_retry_source": source,
        "quota_manual_action_required": manual,
        "parsed_retry_delay_ms": parsed_retry_ms,
    }


def current_context_sha(cfg: Mapping[str, Any]) -> str:
    progress = read_json(Path(str(cfg["progress_path"])))
    next_hypothesis = read_json(Path(str(cfg["next_hypothesis_path"])))
    factory = read_json(Path(str(cfg["factory_path"])))
    registry = read_json(Path(str(cfg["manual_video_registry_path"])))
    context = core.build_research_context(
        cfg,
        progress=progress,
        next_hypothesis=next_hypothesis,
        factory=factory,
        manual_video_registry=registry,
    )
    return stable_sha(context)


def quota_failure_at(previous: Mapping[str, Any], now_ms: int) -> int:
    explicit = core._finite_int(previous.get("quota_failure_at_ms"), 0)
    if explicit > 0:
        return explicit
    updated = core._finite_int(previous.get("updated_at_ms"), 0)
    return updated if updated > 0 else now_ms


def build_quota_hold(
    cfg: Mapping[str, Any],
    previous: Mapping[str, Any],
    *,
    state: str,
    now_ms: int,
    context_sha: str,
) -> dict[str, Any]:
    failure_at = quota_failure_at(previous, now_ms)
    policy = recovery_policy(cfg, previous.get("error_code"))
    retry_after = failure_at + int(policy["cooldown_ms"])
    out = dict(previous)
    out.update(
        {
            "schema_version": core.SCHEMA,
            "state": state,
            "action": "hold",
            "context_sha256": context_sha,
            "quota_failure_at_ms": failure_at,
            "quota_retry_after_ms": retry_after,
            "quota_remaining_ms": max(0, retry_after - now_ms),
            "quota_call_suppressed": state == "HOLD_EXTERNAL_RESEARCH_QUOTA_COOLDOWN",
            "quota_guard_schema_version": SCHEMA,
            "quota_class": policy["quota_class"],
            "quota_retry_source": policy["quota_retry_source"],
            "quota_manual_action_required": policy["quota_manual_action_required"],
            "quota_parsed_retry_delay_ms": policy["parsed_retry_delay_ms"],
            "quota_effective_cooldown_ms": policy["cooldown_ms"],
            "ai_call_made": False if state == "HOLD_EXTERNAL_RESEARCH_QUOTA_COOLDOWN" else previous.get("ai_call_made", True),
            "ai_call_succeeded": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "source_code_mutation_applied": False,
            "self_modification_applied": False,
            "external_content_instruction_authority": False,
            "updated_at_ms": now_ms,
        }
    )
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out


def persist(cfg: Mapping[str, Any], evidence: Mapping[str, Any]) -> None:
    output_path = Path(str(cfg["output_path"]))
    atomic_json_write(output_path, dict(evidence))
    factory = read_json(Path(str(cfg["factory_path"])))
    derived = core.build_context_factory(factory, evidence)
    if derived is not None:
        atomic_json_write(Path(str(cfg["context_factory_output_path"])), derived)


def run_guard(policy_path: Path, *, now_ms: int | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    cfg = core.validate_policy(json.loads(policy_path.read_text(encoding="utf-8")))
    output_path = Path(str(cfg["output_path"]))
    previous = read_json(output_path)
    context_sha = current_context_sha(cfg)

    if isinstance(previous, Mapping):
        previous_state = str(previous.get("state") or "")
        previous_error = previous.get("error_code")
        quota_known = previous_state in QUOTA_STATES or is_quota_error(previous_error)
        if quota_known:
            failure_at = quota_failure_at(previous, now)
            policy = recovery_policy(cfg, previous_error)
            retry_after = failure_at + int(policy["cooldown_ms"])
            if now < retry_after:
                held = build_quota_hold(
                    cfg,
                    previous,
                    state="HOLD_EXTERNAL_RESEARCH_QUOTA_COOLDOWN",
                    now_ms=now,
                    context_sha=context_sha,
                )
                persist(cfg, held)
                return {
                    "state": held["state"],
                    "ai_call_executed": False,
                    "quota_class": held.get("quota_class"),
                    "quota_retry_source": held.get("quota_retry_source"),
                    "quota_manual_action_required": held.get("quota_manual_action_required"),
                    "quota_failure_at_ms": held["quota_failure_at_ms"],
                    "quota_retry_after_ms": held["quota_retry_after_ms"],
                    "quota_remaining_ms": held["quota_remaining_ms"],
                    "context_factory_written": True,
                    "receipt_sha256": held["receipt_sha256"],
                }

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        rc = core.main(["--policy", str(policy_path)])
    if rc != 0:
        raise RuntimeError(f"EXTERNAL_RESEARCH_CORE_NONZERO:{rc}")

    result = read_json(output_path)
    if not isinstance(result, Mapping):
        raise RuntimeError("EXTERNAL_RESEARCH_CORE_OUTPUT_MISSING")
    if result.get("state") == "HOLD_EXTERNAL_RESEARCH_CALL_FAILED" and is_quota_error(result.get("error_code")):
        classified = build_quota_hold(
            cfg,
            result,
            state="HOLD_EXTERNAL_RESEARCH_QUOTA_EXHAUSTED",
            now_ms=now,
            context_sha=context_sha,
        )
        persist(cfg, classified)
        result = classified

    return {
        "state": result.get("state"),
        "ai_call_executed": True,
        "quota_class": result.get("quota_class"),
        "quota_retry_source": result.get("quota_retry_source"),
        "quota_manual_action_required": result.get("quota_manual_action_required"),
        "quota_failure_at_ms": result.get("quota_failure_at_ms"),
        "quota_retry_after_ms": result.get("quota_retry_after_ms"),
        "quota_remaining_ms": result.get("quota_remaining_ms"),
        "context_factory_written": Path(str(cfg["context_factory_output_path"])).is_file(),
        "receipt_sha256": result.get("receipt_sha256"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Guard Gemini external research with quota-aware recovery")
    ap.add_argument("--policy", type=Path, default=core.DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    print(json.dumps(run_guard(ns.policy), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())