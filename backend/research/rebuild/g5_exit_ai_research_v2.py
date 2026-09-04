#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
from pathlib import Path
from typing import Any

from backend.research.rebuild import g5_exit_ai_research_v1 as base

CACHEABLE_STATES = {
    "PASS_SOURCE_GROUNDED_EXIT_MECHANISM_RESEARCH",
    "HOLD_PAID_AI_PROVIDER_ERROR",
    "HOLD_GROUNDING_SOURCES_INSUFFICIENT",
}


def _tracked_run(*, failure_path: Path, current_path: Path, output: Path, allow_network: bool, force_retry: bool) -> dict[str, Any]:
    failure = base.read(failure_path)
    sig = base.failure_signature(failure)
    sig_sha = base.stable(sig)
    current = base.maybe_read(current_path)
    if (
        not force_retry
        and isinstance(current, dict)
        and current.get("failure_signature_sha256") == sig_sha
        and str(current.get("state") or "") in CACHEABLE_STATES
    ):
        result = dict(current)
        result["cache_hit"] = True
        result["cached_same_failure_signature"] = True
        result["provider_call_this_run"] = False
        result["paid_recall_blocked"] = True
        result["force_retry"] = False
        result.pop("receipt_sha256", None)
        result["receipt_sha256"] = base.stable(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        return result

    attempts: list[dict[str, Any]] = []
    original = base.urllib.request.urlopen

    def tracked_urlopen(req: Any, *args: Any, **kwargs: Any):
        url = str(getattr(req, "full_url", ""))
        model = ""
        if "/models/" in url and ":generateContent" in url:
            model = url.split("/models/", 1)[1].split(":generateContent", 1)[0]
        trace: dict[str, Any] = {
            "request_no": len(attempts) + 1,
            "model": model or None,
            "url_family": "generativelanguage.googleapis.com/models/*:generateContent",
            "http_status": None,
            "outcome": "PENDING",
        }
        attempts.append(trace)
        try:
            response = original(req, *args, **kwargs)
            trace["http_status"] = int(getattr(response, "status", 200) or 200)
            trace["outcome"] = "HTTP_SUCCESS"
            return response
        except urllib.error.HTTPError as exc:
            trace["http_status"] = int(exc.code)
            trace["outcome"] = "HTTP_ERROR"
            trace["retryable"] = int(exc.code) in {429, 500, 502, 503, 504}
            raise
        except Exception as exc:
            trace["outcome"] = "TRANSPORT_OR_CLIENT_ERROR"
            trace["error_type"] = type(exc).__name__
            raise

    base.urllib.request.urlopen = tracked_urlopen
    try:
        result = base.run(
            failure_path=failure_path,
            current_path=current_path,
            output=output,
            allow_network=allow_network,
        )
    finally:
        base.urllib.request.urlopen = original

    provider = dict(result.get("provider") or {})
    provider.setdefault("provider", "gemini")
    provider["request_count"] = len(attempts)
    provider["attempts"] = attempts
    provider.setdefault("source_count", 0)
    provider.setdefault("sources", [])
    provider.setdefault("web_search_queries", [])
    usage = dict(provider.get("usage") or {})
    usage.setdefault("input_tokens", 0)
    usage.setdefault("output_tokens", 0)
    usage.setdefault("total_tokens", 0)
    usage.setdefault("estimated_cost_eur", None)
    usage.setdefault("cost_authority_missing", True)
    provider["usage"] = usage
    result["provider"] = provider
    result["force_retry"] = bool(force_retry)
    result["paid_recall_blocked"] = False
    result["request_level_attempt_telemetry_complete"] = len(attempts) == int(provider.get("request_count") or 0)
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = base.stable(result)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert "HOLD_PAID_AI_PROVIDER_ERROR" in CACHEABLE_STATES
    assert "PASS_SOURCE_GROUNDED_EXIT_MECHANISM_RESEARCH" in CACHEABLE_STATES
    failure = {
        "state": "FAIL",
        "strategy_id": "trend_rider",
        "lane_id": "x",
        "validation_T": 6,
        "candidate": {"net_pnl_bps": -10},
        "native_control": {"net_pnl_bps": -5},
        "frozen_nominal_rr": 20,
        "frozen_sl_r": 3,
        "frozen_tp_r": 60,
        "strict_checks": {},
        "next": "route",
    }
    assert base.stable(base.failure_signature(failure))
    print("PASS_G5_EXIT_AI_RESEARCH_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--failure", type=Path, default=base.FAILURE)
    ap.add_argument("--current", type=Path, default=base.CURRENT)
    ap.add_argument("--output", type=Path, default=Path("out/g5_exit_ai_research_latest.json"))
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--force-retry", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = _tracked_run(
        failure_path=args.failure,
        current_path=args.current,
        output=args.output,
        allow_network=not args.no_network,
        force_retry=args.force_retry,
    )
    p = r.get("provider") or {}
    print(json.dumps({
        "state": r.get("state"),
        "provider_call": r.get("provider_call_this_run"),
        "request_count": p.get("request_count"),
        "source_count": p.get("source_count"),
        "cache_hit": r.get("cache_hit"),
        "paid_recall_blocked": r.get("paid_recall_blocked"),
        "force_retry": r.get("force_retry"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
