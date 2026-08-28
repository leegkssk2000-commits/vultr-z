#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_c_grade_pair_nursery_v2 as v2

SCHEMA = "zel.a1.c_grade_pair_nursery.identifier_guard.v1"
_BASE_PROMPT = v2.prompt_v2


def prompt_v2_identifier_guard(
    pairs: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    readiness: Mapping[str, Any],
) -> str:
    return _BASE_PROMPT(pairs, evidence, readiness) + (
        "\nIDENTIFIER_NAMESPACE_CONTRACT=HARD. In every feature formula, entry_rule, side_rule and non-time exit_rule, "
        "every bare identifier MUST be exactly one of: raw evaluator fields open/high/low/close/volume, a replay-ready source field, "
        "an ALLOWED_DSL_FUNCTIONS name, or a feature name declared EARLIER in executable_spec.features. "
        "Conceptual aliases are NOT built-ins. For example vwap_bias, trend_bias, band_signal and momentum_state are forbidden unless "
        "the exact name is first declared as a feature with an evaluator-valid formula. "
        "The evaluator already provides the function vwap(...); vwap_bias is NOT a function or raw field. "
        "If features is empty, rules may contain NO custom identifiers at all. "
        "Before returning JSON, perform a lexical closure check: collect every bare identifier used by formulas/rules and verify it is "
        "raw/replay-ready/function/or previously-declared-feature. If any identifier is unresolved, emit zero candidates for that pair instead of guessing. "
        "INVALID_EXAMPLE={\"features\":[],\"entry_rule\":\"vwap_bias > 0\"}. "
        "VALID_SHAPE_EXAMPLE={\"features\":[{\"name\":\"vwap_bias\",\"formula\":\"close-vwap(96)\"}],\"entry_rule\":\"vwap_bias > 0\"}. "
        "Do not copy the example horizon unless it is structurally/native justified; the example exists only to show identifier declaration order."
    )


def run(output: Path, *, no_ai: bool = False) -> dict[str, Any]:
    old_prompt = v2.prompt_v2
    v2.prompt_v2 = prompt_v2_identifier_guard
    try:
        result = v2.run(output, no_ai=no_ai)
    finally:
        v2.prompt_v2 = old_prompt

    result["identifier_guard_schema"] = SCHEMA
    result["identifier_namespace_contract"] = "RAW_OR_REPLAY_READY_OR_FUNCTION_OR_PREDECLARED_FEATURE_ONLY"
    result["custom_identifier_requires_prior_feature_declaration"] = True
    result["unresolved_identifier_fails_closed"] = True
    result["receipt_sha256"] = v2.v1.stable({k: val for k, val in result.items() if k != "receipt_sha256"})
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    evidence = [{"id": "F1", "claim": "x"}]
    pairs = [{
        "pair_id": "CPAIR__a__X__b__g",
        "host_strategy_id": "a",
        "host_family": "vwap_bb",
        "donor_strategy_id": "b",
        "donor_gene": "g",
        "changed_axis": "C_PAIR__B__G__ONLY",
    }]
    text = prompt_v2_identifier_guard(pairs, evidence, {"ohlcv": {"ready": True}, "volume": {"ready": True}})
    for required in (
        "IDENTIFIER_NAMESPACE_CONTRACT=HARD",
        "vwap_bias",
        "previously-declared-feature",
        "If features is empty",
        "lexical closure check",
    ):
        assert required in text

    base = {
        "candidate_id": "x",
        "required_sources": ["ohlcv", "volume"],
        "executable_spec": {
            "bar_interval": "1h",
            "features": [],
            "entry_rule": "vwap_bias > 0",
            "side_rule": "long",
            "exit_rule": "time_stop",
            "max_hold_bars": 24,
        },
    }
    bad = v2.dsl_preflight(base)
    assert bad["ok"] is False and "UNKNOWN_NAME:vwap_bias" in str(bad["error"])

    good = json.loads(json.dumps(base))
    good["candidate_id"] = "good"
    good["executable_spec"]["features"] = [{"name": "vwap_bias", "formula": "close-vwap(24)"}]
    assert v2.dsl_preflight(good)["ok"] is True
    print("PASS_A1_C_GRADE_PAIR_NURSERY_V2_IDENTIFIER_GUARD_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_c_grade_pair_nursery_v2.json"))
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    r = run(a.out, no_ai=a.no_ai)
    print(json.dumps({
        "state": r["state"],
        "c": r["eligible_c_material_count"],
        "pairs": r["pair_count_this_run"],
        "upgrades": r["c_to_b_upgrade_count"],
        "provider": r["provider"],
        "next": r["next"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())