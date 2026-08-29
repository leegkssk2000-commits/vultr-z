#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.architecture_factory import a1_strategy_architecture_factory_v1 as factory
from backend.research.architecture_factory import a1_terminal_repair_swarm_v4 as hashutil
from backend.research.architecture_factory import a1_terminal_repair_swarm_v5 as v5
from backend.research.architecture_factory import openai_generator_hardened_v1 as hardened

ROOT = Path(__file__).resolve().parents[3]
V6_CACHE = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v6_latest.json"
SELF = ROOT / "backend/research/architecture_factory/a1_terminal_repair_swarm_v6.py"
HARDENED = ROOT / "backend/research/architecture_factory/openai_generator_hardened_v1.py"


def _install() -> None:
    factory.call_openai_generator = hardened.call_openai_generator
    v5.CACHE = V6_CACHE
    paths = list(v5.CODE_PATHS)
    for path in (SELF, HARDENED):
        if path not in paths:
            paths.append(path)
    v5.CODE_PATHS = paths


def run(output: Path) -> dict[str, Any]:
    _install()
    result = v5.run(output)
    result["openai_output_hardening"] = {
        "state": "ACTIVE_MANUAL_V6",
        "provider": "openai",
        "default_model": hardened.DEFAULT_MODEL,
        "max_output_tokens": hardened.MAX_OUTPUT_TOKENS,
        "max_candidates": hardened.MAX_CANDIDATES,
        "strict_full_json_schema": True,
        "concise_output_contract": True,
        "response_status_checked": True,
        "incomplete_reason_checked": True,
        "request_token_usage_captured_on_success": True,
        "legacy_failure_target": "JSONDecodeError_Unterminated_string_at_approximately_19k_chars",
        "automatic_paid_execution": False,
    }
    roi = result.setdefault("api_roi", {})
    roi["paid_execution_mode"] = "MANUAL_V6_ONLY"
    roi["automatic_paid_execution"] = False
    roi["provider_output_contract_version"] = "OPENAI_GENERATOR_HARDENED_V1"
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = hashutil.sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    _install()
    assert v5.CACHE == V6_CACHE
    assert factory.call_openai_generator is hardened.call_openai_generator
    assert SELF in v5.CODE_PATHS and HARDENED in v5.CODE_PATHS
    assert hardened.self_test() == 0
    print("PASS_A1_TERMINAL_REPAIR_SWARM_V6_MANUAL_HARDENING_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_terminal_repair_swarm_v6.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    roi = result.get("api_roi") or {}
    print(json.dumps({
        "run_mode": result.get("run_mode"),
        "cache_hit": roi.get("cache_hit"),
        "paid_requests": roi.get("paid_request_count"),
        "economic_pass": result.get("development_economic_pass_count"),
        "hardening": result.get("openai_output_hardening"),
        "receipt": result.get("receipt_sha256"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
