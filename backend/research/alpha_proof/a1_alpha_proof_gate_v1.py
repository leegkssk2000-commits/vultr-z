#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "zel.a1_alpha_proof_gate.v1"
PASS_STATE = "PASS_ALPHA_PROOF_READY_FOR_FRESH_PROSPECTIVE"
HOLD_STATE = "HOLD_ALPHA_PROOF"
PARAMETER_PROVENANCE = {
    "SOURCE_DERIVED",
    "MARKET_STRUCTURE_DERIVED",
    "DEVELOPMENT_SELECTED",
    "PURE_DESIGN_PRIOR",
}
PASS_DECISIONS = {"PASS", "PASS_TO_REPLAY", "PASS_TO_PREREGISTER"}
REQUIRED_CONTROL_KINDS = {
    "direction_flip",
    "time_shift_placebo",
    "delayed_entry",
    "regime_permutation",
}
AUTHORITY = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def _bool(value: Any) -> bool:
    return value is True


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fail(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _gate(name: str, passed: bool, failures: list[dict[str, str]], evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"gate": name, "passed": bool(passed), "failures": failures, "evidence": dict(evidence or {})}


def evaluate_p0(bundle: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    evidence = bundle.get("primary_evidence")
    if not isinstance(evidence, Mapping):
        return _gate("P0_PRIMARY_EVIDENCE", False, [_fail("P0_EVIDENCE_MISSING", "primary_evidence object is required")])
    supports = evidence.get("supports")
    if not isinstance(supports, list):
        return _gate("P0_PRIMARY_EVIDENCE", False, [_fail("P0_SUPPORTS_MISSING", "primary_evidence.supports list is required")])
    valid: list[dict[str, Any]] = []
    independent = set()
    primary_count = 0
    native_count = 0
    for row in supports:
        if not isinstance(row, Mapping):
            continue
        kind = str(row.get("kind") or "")
        independent_key = str(row.get("independent_key") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        if kind not in {"PRIMARY", "NATIVE_EMPIRICAL"} or not independent_key or not source_id:
            continue
        if not _bool(row.get("supports_mechanism")):
            continue
        independent.add(independent_key)
        primary_count += int(kind == "PRIMARY")
        native_count += int(kind == "NATIVE_EMPIRICAL")
        valid.append(dict(row))
    if len(independent) < 2:
        failures.append(_fail("P0_INDEPENDENCE_INSUFFICIENT", "at least two independent mechanistic supports are required"))
    if not (primary_count >= 2 or (primary_count >= 1 and native_count >= 1)):
        failures.append(_fail("P0_SUPPORT_MIX_INSUFFICIENT", "require >=2 primary supports or >=1 primary + >=1 native empirical validation"))
    return _gate("P0_PRIMARY_EVIDENCE", not failures, failures, {"valid_support_count": len(valid), "primary_count": primary_count, "native_count": native_count, "independent_count": len(independent)})


def evaluate_p1(bundle: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    fmap = bundle.get("feature_causal_map")
    if not isinstance(fmap, Mapping):
        return _gate("P1_FEATURE_CAUSAL_MAP", False, [_fail("P1_MAP_MISSING", "feature_causal_map object is required")])
    features = fmap.get("features")
    if not isinstance(features, list) or not features:
        failures.append(_fail("P1_FEATURES_MISSING", "at least one entry-time feature with causal role is required"))
        features = []
    names = set()
    for row in features:
        if not isinstance(row, Mapping):
            failures.append(_fail("P1_FEATURE_INVALID", "feature row must be an object")); continue
        name = str(row.get("name") or "").strip()
        if not name:
            failures.append(_fail("P1_FEATURE_NAME_MISSING", "feature name is required")); continue
        if name in names:
            failures.append(_fail("P1_DUPLICATE_FEATURE", name))
        names.add(name)
        for key in ("mechanism", "observable", "direction", "invalidation"):
            if not str(row.get(key) or "").strip():
                failures.append(_fail("P1_CAUSAL_FIELD_MISSING", f"{name}:{key}"))
        if row.get("entry_time_observable") is not True:
            failures.append(_fail("P1_NOT_ENTRY_TIME_OBSERVABLE", name))
    redundant = fmap.get("redundant_pairs") or []
    if redundant:
        failures.append(_fail("P1_REDUNDANT_FEATURE_STACK", canonical(redundant)[:500]))
    if fmap.get("ablation_plan_complete") is not True:
        failures.append(_fail("P1_ABLATION_PLAN_INCOMPLETE", "feature_causal_map.ablation_plan_complete must be true"))
    return _gate("P1_FEATURE_CAUSAL_MAP", not failures, failures, {"feature_count": len(names)})


def evaluate_p2(bundle: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    inv = bundle.get("parameter_provenance")
    if not isinstance(inv, Mapping):
        return _gate("P2_NUMERIC_PARAMETER_PROVENANCE", False, [_fail("P2_INVENTORY_MISSING", "parameter_provenance object is required")])
    if inv.get("numeric_parameter_inventory_complete") is not True:
        failures.append(_fail("P2_INVENTORY_INCOMPLETE", "every numeric constant must be inventoried"))
    params = inv.get("parameters")
    if not isinstance(params, list):
        params = []
        failures.append(_fail("P2_PARAMETERS_MISSING", "parameter_provenance.parameters list is required"))
    names = set()
    for row in params:
        if not isinstance(row, Mapping):
            failures.append(_fail("P2_PARAMETER_INVALID", "parameter row must be object")); continue
        name = str(row.get("name") or "").strip()
        provenance = str(row.get("provenance") or "")
        if not name or name in names:
            failures.append(_fail("P2_PARAMETER_NAME_INVALID", name or "<missing>"))
        names.add(name)
        if provenance not in PARAMETER_PROVENANCE:
            failures.append(_fail("P2_PROVENANCE_INVALID", f"{name}:{provenance}")); continue
        if not str(row.get("source_or_test_sha") or "").strip():
            failures.append(_fail("P2_PROVENANCE_SHA_MISSING", name))
        if provenance == "PURE_DESIGN_PRIOR":
            if not str(row.get("development_justification_sha") or "").strip():
                failures.append(_fail("P2_PURE_DESIGN_PRIOR_UNJUSTIFIED", name))
        if row.get("selected_using_holdout") is True:
            failures.append(_fail("P2_HOLDOUT_SELECTED_PARAMETER", name))
    return _gate("P2_NUMERIC_PARAMETER_PROVENANCE", not failures, failures, {"parameter_count": len(params), "provenance_types": sorted({str(x.get('provenance') or '') for x in params if isinstance(x, Mapping)})})


def evaluate_p3(bundle: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    dev = bundle.get("development_feasibility")
    if not isinstance(dev, Mapping):
        return _gate("P3_EMPIRICAL_MOVE_VS_COST", False, [_fail("P3_DEVELOPMENT_RECEIPT_MISSING", "development_feasibility object is required")])
    if dev.get("separated_from_prospective_holdout") is not True:
        failures.append(_fail("P3_NOT_SEPARATED_FROM_HOLDOUT", "development window must be separated"))
    if dev.get("holdout_outcomes_used") is not False:
        failures.append(_fail("P3_HOLDOUT_LEAKAGE", "holdout outcomes must not be used"))
    if not str(dev.get("development_data_sha") or "").strip():
        failures.append(_fail("P3_DATA_SHA_MISSING", "development_data_sha required"))
    metrics = dev.get("metrics")
    if not isinstance(metrics, Mapping):
        metrics = {}
        failures.append(_fail("P3_METRICS_MISSING", "signal-conditioned development metrics required"))
    for key in ("event_count", "completed_trades", "forward_move_bps_median", "mfe_bps_median", "mae_bps_median", "gross_expectancy_bps", "realistic_cost_bps", "event_rate_per_day"):
        if not _numeric(metrics.get(key)):
            failures.append(_fail("P3_METRIC_MISSING", key))
    source = str(dev.get("launch_gate_source") or "")
    if not source.startswith("SSOT:"):
        failures.append(_fail("P3_LAUNCH_GATE_SOURCE_NOT_SSOT", source or "<missing>"))
    if dev.get("launch_gate_pass") is not True:
        failures.append(_fail("P3_DEVELOPMENT_FEASIBILITY_FAIL", "SSOT development launch gate did not pass"))
    return _gate("P3_EMPIRICAL_MOVE_VS_COST", not failures, failures, {"launch_gate_source": source, "metrics": dict(metrics)})


def evaluate_p4(bundle: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    controls = bundle.get("negative_controls_and_ablation")
    if not isinstance(controls, Mapping):
        return _gate("P4_NEGATIVE_CONTROLS_ABLATION", False, [_fail("P4_CONTROLS_MISSING", "negative_controls_and_ablation object is required")])
    rows = controls.get("controls")
    if not isinstance(rows, list):
        rows = []
        failures.append(_fail("P4_CONTROL_LIST_MISSING", "controls list required"))
    seen = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        kind = str(row.get("kind") or "")
        if kind:
            seen.add(kind)
        applicable = row.get("applicable") is not False
        if applicable and row.get("passed") is not True:
            failures.append(_fail("P4_CONTROL_FAIL", kind or "<unknown>"))
        if not applicable and not str(row.get("not_applicable_reason") or "").strip():
            failures.append(_fail("P4_NOT_APPLICABLE_UNJUSTIFIED", kind or "<unknown>"))
    missing = sorted(REQUIRED_CONTROL_KINDS - seen)
    if missing:
        failures.append(_fail("P4_REQUIRED_CONTROL_MISSING", ",".join(missing)))
    feature_map = bundle.get("feature_causal_map") or {}
    feature_names = {str(x.get("name")) for x in (feature_map.get("features") or []) if isinstance(x, Mapping) and x.get("name")}
    ablations = controls.get("feature_ablations")
    if not isinstance(ablations, list):
        ablations = []
    ablated = set()
    for row in ablations:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("feature") or "")
        if name:
            ablated.add(name)
        if row.get("applicable") is not False and row.get("passed") is not True:
            failures.append(_fail("P4_ABLATION_FAIL", name or "<unknown>"))
    if feature_names - ablated:
        failures.append(_fail("P4_FEATURE_ABLATION_MISSING", ",".join(sorted(feature_names - ablated))))
    if controls.get("holdout_outcomes_used") is not False:
        failures.append(_fail("P4_HOLDOUT_LEAKAGE", "controls/ablations must use development-only data"))
    return _gate("P4_NEGATIVE_CONTROLS_ABLATION", not failures, failures, {"controls_seen": sorted(seen), "ablated_features": sorted(ablated)})


def evaluate_p5(bundle: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    review = bundle.get("multi_ai_adversarial_review")
    if not isinstance(review, Mapping):
        return _gate("P5_MULTI_AI_ADVERSARIAL_REVIEW", False, [_fail("P5_REVIEW_MISSING", "multi_ai_adversarial_review object is required")])
    if not str(review.get("controller_review_sha") or "").strip():
        failures.append(_fail("P5_CONTROLLER_REVIEW_MISSING", "ChatGPT/controller review SHA required"))
    rows = review.get("provider_reviews")
    if not isinstance(rows, list):
        rows = []
        failures.append(_fail("P5_PROVIDER_REVIEWS_MISSING", "provider_reviews list required"))
    passes = 0
    providers = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        provider = str(row.get("provider") or "").strip().lower()
        decision = str(row.get("decision") or "")
        if not provider or provider in providers:
            continue
        providers.add(provider)
        if row.get("successful") is True and decision in PASS_DECISIONS:
            passes += 1
        if row.get("successful") is True and decision == "REJECT":
            failures.append(_fail("P5_PROVIDER_REJECT", provider))
        if decision == "HOLD" and row.get("resolved_by_evidence") is not True:
            failures.append(_fail("P5_UNRESOLVED_HOLD", provider))
        if row.get("successful") is True:
            for key in ("model", "input_sha", "prompt_sha", "response_sha"):
                if not str(row.get(key) or "").strip():
                    failures.append(_fail("P5_LINEAGE_MISSING", f"{provider}:{key}"))
    if passes < 2:
        failures.append(_fail("P5_INDEPENDENT_PASS_INSUFFICIENT", str(passes)))
    return _gate("P5_MULTI_AI_ADVERSARIAL_REVIEW", not failures, failures, {"independent_provider_passes": passes, "providers": sorted(providers)})


def evaluate_p6(bundle: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    reality = bundle.get("source_implementation_reality")
    candidate = bundle.get("candidate") if isinstance(bundle.get("candidate"), Mapping) else {}
    if not isinstance(reality, Mapping):
        return _gate("P6_SOURCE_IMPLEMENTATION_REALITY", False, [_fail("P6_REALITY_MISSING", "source_implementation_reality object is required")])
    required = {str(x) for x in (candidate.get("required_sources") or [])}
    rows = reality.get("sources")
    if not isinstance(rows, list):
        rows = []
        failures.append(_fail("P6_SOURCE_LIST_MISSING", "sources list required"))
    available = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "")
        if not name:
            continue
        if row.get("available") is True:
            available.add(name)
        if row.get("proxy") is True and not (row.get("proxy_declared") is True and row.get("proxy_validated") is True):
            failures.append(_fail("P6_UNVALIDATED_PROXY", name))
        if row.get("fresh") is not True:
            failures.append(_fail("P6_STALE_SOURCE", name))
        if not str(row.get("source_sha") or "").strip():
            failures.append(_fail("P6_SOURCE_SHA_MISSING", name))
    if required - available:
        failures.append(_fail("P6_REQUIRED_SOURCE_UNAVAILABLE", ",".join(sorted(required - available))))
    for key in ("duplicate_count", "leakage_count", "timestamp_order_error_count", "integrity_defect_count"):
        if int(reality.get(key) or 0) != 0:
            failures.append(_fail("P6_INTEGRITY_FAIL", f"{key}={reality.get(key)}"))
    if not _numeric(reality.get("verified_round_trip_cost_bps")):
        failures.append(_fail("P6_COST_AUTHORITY_MISSING", "verified_round_trip_cost_bps required"))
    if not str(reality.get("cost_authority_sha") or "").strip():
        failures.append(_fail("P6_COST_AUTHORITY_SHA_MISSING", "cost_authority_sha required"))
    return _gate("P6_SOURCE_IMPLEMENTATION_REALITY", not failures, failures, {"required_sources": sorted(required), "available_sources": sorted(available), "verified_round_trip_cost_bps": reality.get("verified_round_trip_cost_bps")})


def evaluate_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    candidate = bundle.get("candidate")
    if not isinstance(candidate, Mapping):
        candidate = {}
    candidate_sha = str(candidate.get("candidate_sha256") or "")
    computed_candidate_sha = sha({k: v for k, v in candidate.items() if k != "candidate_sha256"}) if candidate else ""
    identity_failures: list[dict[str, str]] = []
    if not candidate_sha:
        identity_failures.append(_fail("CANDIDATE_SHA_MISSING", "candidate.candidate_sha256 required"))
    elif candidate_sha != computed_candidate_sha:
        identity_failures.append(_fail("CANDIDATE_SHA_MISMATCH", f"declared={candidate_sha} computed={computed_candidate_sha}"))
    if candidate.get("research_only") is False:
        identity_failures.append(_fail("CANDIDATE_AUTHORITY_INVALID", "research_only cannot be false"))
    gates = [
        _gate("P-IDENTITY", not identity_failures, identity_failures, {"candidate_sha256": candidate_sha}),
        evaluate_p0(bundle),
        evaluate_p1(bundle),
        evaluate_p2(bundle),
        evaluate_p3(bundle),
        evaluate_p4(bundle),
        evaluate_p5(bundle),
        evaluate_p6(bundle),
    ]
    all_pass = all(g["passed"] for g in gates)
    result = {
        "schema_version": SCHEMA_VERSION,
        "state": PASS_STATE if all_pass else HOLD_STATE,
        "candidate_id": candidate.get("candidate_id"),
        "candidate_sha256": candidate_sha,
        "gates": gates,
        "p0_p6_passed": all_pass,
        "fresh_prospective_boundary_required": all_pass,
        "fresh_policy_config_source_sha_required": all_pass,
        "heavy_launch_allowed": False,
        "launch_authority_note": "PASS_ALPHA_PROOF only authorizes creation of a new frozen fresh prospective contract. It never itself launches, selects, promotes, or trades.",
        **AUTHORITY,
    }
    result["receipt_sha256"] = sha(result)
    return result


def assert_receipt(receipt: Mapping[str, Any], candidate_sha: str) -> None:
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("ALPHA_PROOF_SCHEMA_MISMATCH")
    if receipt.get("state") != PASS_STATE or receipt.get("p0_p6_passed") is not True:
        raise RuntimeError("ALPHA_PROOF_NOT_PASS")
    if str(receipt.get("candidate_sha256") or "") != candidate_sha:
        raise RuntimeError("ALPHA_PROOF_CANDIDATE_SHA_MISMATCH")
    if receipt.get("selection_authority") is not False or receipt.get("promotion_authority") is not False:
        raise RuntimeError("ALPHA_PROOF_AUTHORITY_INVALID")
    if receipt.get("execution_authority") != "NONE" or receipt.get("order_authority") != "BLOCKED" or receipt.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("ALPHA_PROOF_EXECUTION_AUTHORITY_INVALID")
    if int(receipt.get("protected_mutations") or 0) != 0:
        raise RuntimeError("ALPHA_PROOF_PROTECTED_MUTATION")


def _fixture_bundle() -> dict[str, Any]:
    candidate_core = {
        "candidate_id": "fixture:new_arch",
        "mode": "NEW_ARCHITECTURE",
        "strategy_id": "NEW",
        "architecture_family": "basis_dislocation_unwind_fixture",
        "changed_axis": "basis_dislocation_state",
        "mechanism": "temporary perp basis dislocation mean reverts when positioning pressure relaxes",
        "payer": "crowded leveraged perp positioning",
        "entry_event": "entry-time basis+OI dislocation",
        "native_horizon": "1h-4h",
        "required_sources": ["ohlcv", "basis", "open_interest", "funding"],
        "evidence_ids": ["P1", "P2"],
        "research_only": True,
    }
    candidate = {**candidate_core, "candidate_sha256": sha(candidate_core)}
    return {
        "candidate": candidate,
        "primary_evidence": {"supports": [
            {"kind": "PRIMARY", "source_id": "doi:one", "independent_key": "authors:one", "supports_mechanism": True},
            {"kind": "PRIMARY", "source_id": "ssrn:two", "independent_key": "authors:two", "supports_mechanism": True},
        ]},
        "feature_causal_map": {"features": [
            {"name": "basis_z", "mechanism": "dislocation", "observable": "basis", "direction": "fade extreme", "invalidation": "dislocation expands", "entry_time_observable": True},
            {"name": "oi_change", "mechanism": "crowding", "observable": "open_interest", "direction": "confirm crowding", "invalidation": "OI normalizes", "entry_time_observable": True},
        ], "redundant_pairs": [], "ablation_plan_complete": True},
        "parameter_provenance": {"numeric_parameter_inventory_complete": True, "parameters": [
            {"name": "lookback", "value": 48, "provenance": "DEVELOPMENT_SELECTED", "source_or_test_sha": "devsha", "selected_using_holdout": False},
            {"name": "horizon", "value": 4, "provenance": "MARKET_STRUCTURE_DERIVED", "source_or_test_sha": "sourcesha", "selected_using_holdout": False},
        ]},
        "development_feasibility": {"separated_from_prospective_holdout": True, "holdout_outcomes_used": False, "development_data_sha": "devdata", "launch_gate_source": "SSOT:A1_ALPHA_PROOF_DEV_MIN_V1", "launch_gate_pass": True, "metrics": {"event_count": 80, "completed_trades": 60, "forward_move_bps_median": 42.0, "mfe_bps_median": 55.0, "mae_bps_median": 20.0, "gross_expectancy_bps": 18.0, "realistic_cost_bps": 14.0, "event_rate_per_day": 3.0}},
        "negative_controls_and_ablation": {"holdout_outcomes_used": False, "controls": [
            {"kind": "direction_flip", "applicable": True, "passed": True},
            {"kind": "time_shift_placebo", "applicable": True, "passed": True},
            {"kind": "delayed_entry", "applicable": True, "passed": True},
            {"kind": "regime_permutation", "applicable": True, "passed": True},
        ], "feature_ablations": [
            {"feature": "basis_z", "applicable": True, "passed": True},
            {"feature": "oi_change", "applicable": True, "passed": True},
        ]},
        "multi_ai_adversarial_review": {"controller_review_sha": "controller", "provider_reviews": [
            {"provider": "openai", "successful": True, "decision": "PASS_TO_REPLAY", "model": "gpt", "input_sha": "i1", "prompt_sha": "p1", "response_sha": "r1"},
            {"provider": "groq", "successful": True, "decision": "PASS_TO_REPLAY", "model": "groq", "input_sha": "i2", "prompt_sha": "p2", "response_sha": "r2"},
            {"provider": "workers_ai", "successful": True, "decision": "PASS", "model": "workers", "input_sha": "i3", "prompt_sha": "p3", "response_sha": "r3"},
        ]},
        "source_implementation_reality": {"sources": [
            {"name": "ohlcv", "available": True, "fresh": True, "source_sha": "s1", "proxy": False},
            {"name": "basis", "available": True, "fresh": True, "source_sha": "s2", "proxy": False},
            {"name": "open_interest", "available": True, "fresh": True, "source_sha": "s3", "proxy": False},
            {"name": "funding", "available": True, "fresh": True, "source_sha": "s4", "proxy": False},
        ], "duplicate_count": 0, "leakage_count": 0, "timestamp_order_error_count": 0, "integrity_defect_count": 0, "verified_round_trip_cost_bps": 14.0, "cost_authority_sha": "costsha"},
    }


def self_test() -> int:
    good = _fixture_bundle()
    passed = evaluate_bundle(good)
    assert passed["state"] == PASS_STATE, passed
    assert_receipt(passed, good["candidate"]["candidate_sha256"])
    bad = json.loads(json.dumps(good))
    bad["parameter_provenance"]["parameters"][0] = {"name": "lookback", "value": 48, "provenance": "PURE_DESIGN_PRIOR", "source_or_test_sha": "design", "selected_using_holdout": False}
    held = evaluate_bundle(bad)
    assert held["state"] == HOLD_STATE
    assert any(f["code"] == "P2_PURE_DESIGN_PRIOR_UNJUSTIFIED" for g in held["gates"] for f in g["failures"])
    print("PASS_A1_ALPHA_PROOF_GATE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path)
    ap.add_argument("--output", type=Path, default=Path("out/a1_alpha_proof_gate_v1.json"))
    ap.add_argument("--assert-receipt", type=Path)
    ap.add_argument("--candidate-sha")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.assert_receipt:
        if not args.candidate_sha:
            raise SystemExit("--candidate-sha required with --assert-receipt")
        assert_receipt(read_json(args.assert_receipt), args.candidate_sha)
        print("PASS_A1_ALPHA_PROOF_RECEIPT_ASSERT")
        return 0
    if not args.bundle:
        raise SystemExit("--bundle is required")
    result = evaluate_bundle(read_json(args.bundle))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(canonical({"state": result["state"], "candidate_id": result["candidate_id"], "candidate_sha256": result["candidate_sha256"], "failed_gates": [g["gate"] for g in result["gates"] if not g["passed"]], "receipt_sha256": result["receipt_sha256"]}))
    return 0 if result["state"] == PASS_STATE else 2


if __name__ == "__main__":
    raise SystemExit(main())
