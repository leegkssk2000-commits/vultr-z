from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from backend.production import zel_production_external_research_observer_v1 as core
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_external_research_quota_guard.v3"
GENERIC_DIAGNOSTIC_VERSION = "quota-diagnostic-v1"
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
    "perminute",
    "per_minute",
    "per day",
    "perday",
    "per_day",
    "free_tier",
    "prepayment credits are depleted",
    "enable billing",
    "set up billing",
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
        cooldown_ms = min(fallback_ms, 15 * 60_000)
        source = "GENERIC_QUOTA_RECLASSIFY_BACKOFF"
        manual = False

    return {
        "quota_class": klass,
        "cooldown_ms": int(cooldown_ms),
        "quota_retry_source": source,
        "quota_manual_action_required": manual,
        "parsed_retry_delay_ms": parsed_retry_ms,
    }


def _safe_http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")[:8000]
    except Exception:  # noqa: BLE001
        raw = ""
    retry_after = ""
    try:
        retry_after = str(exc.headers.get("Retry-After") or "").strip()
    except Exception:  # noqa: BLE001
        retry_after = ""

    pieces = [f"HTTP_{int(exc.code)}"]
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}

    error = payload.get("error") if isinstance(payload, Mapping) else None
    if isinstance(error, Mapping):
        status = str(error.get("status") or "").strip()
        message = str(error.get("message") or "").strip()
        if status:
            pieces.append(status[:120])
        if message:
            pieces.append(message[:1600])
        for detail in error.get("details") or []:
            if not isinstance(detail, Mapping):
                continue
            dtype = str(detail.get("@type") or "")
            if dtype.endswith("RetryInfo") and detail.get("retryDelay"):
                pieces.append(f"retryDelay={str(detail.get('retryDelay'))[:80]}")
            reason = str(detail.get("reason") or "").strip()
            if reason:
                pieces.append(f"reason={reason[:160]}")
            metadata = detail.get("metadata")
            if isinstance(metadata, Mapping):
                for key in (
                    "quota_metric",
                    "quota_limit",
                    "quota_limit_value",
                    "quota_location",
                    "service",
                ):
                    if metadata.get(key) is not None:
                        pieces.append(f"{key}={str(metadata.get(key))[:240]}")
    elif raw:
        sanitized = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_API_KEY]", raw)
        sanitized = re.sub(r"(?i)(x-goog-api-key|api[_-]?key)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", sanitized)
        pieces.append(sanitized[:1600])

    if retry_after:
        pieces.append(f"Retry-After={retry_after[:80]}")
    return "|".join(x for x in pieces if x)[:4000]


def generic_quota_diagnostic(cfg: Mapping[str, Any]) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "DIAGNOSTIC_GEMINI_API_KEY_MISSING"

    preferred = [str(x) for x in (cfg.get("models") or []) if str(x).strip()]
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": api_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        return _safe_http_error_detail(exc)
    except Exception as exc:  # noqa: BLE001
        return f"DIAGNOSTIC_MODEL_LIST_{type(exc).__name__}:{str(exc)[:500]}"

    eligible = [
        str(row.get("name"))
        for row in payload.get("models") or []
        if isinstance(row, Mapping)
        and row.get("name")
        and "generateContent" in (row.get("supportedGenerationMethods") or [])
    ]
    ordered = [x for x in preferred if x in eligible]
    ordered.extend(x for x in eligible if x not in ordered and "flash" in x.lower())
    if not ordered:
        return "DIAGNOSTIC_NO_ELIGIBLE_MODEL"

    model = ordered[0]
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": "quota diagnostic; reply OK"}]}],
            "generationConfig": {"maxOutputTokens": 8, "temperature": 0},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
        data=body,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            json.load(response)
        return "DIAGNOSTIC_GENERATE_OK"
    except urllib.error.HTTPError as exc:
        return _safe_http_error_detail(exc)
    except Exception as exc:  # noqa: BLE001
        return f"DIAGNOSTIC_GENERATE_{type(exc).__name__}:{str(exc)[:500]}"


def _enrich_generic_quota(
    cfg: Mapping[str, Any],
    previous: Mapping[str, Any],
    *,
    now_ms: int,
) -> tuple[dict[str, Any], bool]:
    out = dict(previous)
    diagnostic = generic_quota_diagnostic(cfg)
    out["quota_diagnostic_version"] = GENERIC_DIAGNOSTIC_VERSION
    out["quota_diagnostic_at_ms"] = now_ms
    out["quota_diagnostic_error_code"] = diagnostic[:4000]
    klass = quota_class(diagnostic)
    if klass != "NOT_QUOTA":
        prior = str(previous.get("error_code") or "")
        out["error_code"] = f"{prior}|DIAGNOSTIC:{diagnostic}"[:6000]
    recovered = diagnostic == "DIAGNOSTIC_GENERATE_OK"
    return out, recovered


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
        diagnostic_recovered = False
        if quota_known:
            initial_policy = recovery_policy(cfg, previous_error)
            if (
                initial_policy["quota_class"] == "GENERIC_QUOTA"
                and previous.get("quota_diagnostic_version") != GENERIC_DIAGNOSTIC_VERSION
            ):
                previous, diagnostic_recovered = _enrich_generic_quota(cfg, previous, now_ms=now)
                previous_error = previous.get("error_code")
            if not diagnostic_recovered:
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
                        "quota_diagnostic_version": held.get("quota_diagnostic_version"),
                        "quota_diagnostic_error_code": held.get("quota_diagnostic_error_code"),
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
        enriched = dict(result)
        if recovery_policy(cfg, result.get("error_code"))["quota_class"] == "GENERIC_QUOTA":
            enriched, _ = _enrich_generic_quota(cfg, result, now_ms=now)
        classified = build_quota_hold(
            cfg,
            enriched,
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
        "quota_diagnostic_version": result.get("quota_diagnostic_version"),
        "quota_diagnostic_error_code": result.get("quota_diagnostic_error_code"),
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
