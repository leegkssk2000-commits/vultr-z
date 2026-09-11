"""One-shot exact Squeeze G5A qualification on existing provenance only.

This successor has no independent canonical OOS: almost all of that partition
was used to develop candidate82.  The actual unchanged alpha owner is called
once to record the qualification rejection.  No market data is decoded, no
economic producer is run, and no boundary/collector/runtime can be mutated.
Verification checks saved bytes and arithmetic only; it never repeats gates.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha

ROOT = Path(__file__).resolve().parents[3]
SCOPE = "SQUEEZE_CONTINUATION_G5B_ACTIVATION_AFTER_PR1269_V1"
PRIOR = "research/development_evidence/SQUEEZE_CONTINUATION_BENCHMARK_SPRINT_AFTER_PR1266_V1/"
PARENT = "research/development_evidence/C70_TM_PARTIAL_CAPACITY_REUSE_AFTER_PR1260_V1/"
OUT = "research/development_evidence/" + SCOPE + "/G5A_QUALIFICATION.json"
ATTEMPT = "research/development_evidence/" + SCOPE + "/G5A_QUALIFICATION_ATTEMPT.json"
SPEC = "research/development_evidence/" + SCOPE + "/SPEC.json"
ALPHA = "backend/research/alpha_proof/a1_alpha_proof_gate_v1.py"
ADMISSION = "backend/research/architecture_factory/g5a_stage_admission_latest_v1.json"
CONTRACT = "backend/research/contracts/g5a_stage_source_cost_contract_v1.json"
MANIFEST = "research/data/g5a_stage_v1/development_manifest.json"
SELF = "backend/research/rebuild/squeeze_g5a_qualification_v1.py"
REPORTS = ("base_replay", "realistic_cost", "cost2x", "purged_oos",
           "chronological_split", "symbol_decomposition", "regime_decomposition",
           "parameter_neighbor_stability", "negative_controls")
EXPECTED = {
    "strategy_name": "Squeeze Continuation v1",
    "candidate_id": "C70_TM_CAPREUSE_V1",
    "candidate_ordinal": 82,
    "strategy_digest": "5c63d3a69e1398dd1fae1076c9e8bdc29b8252a3188ac6b6a79571b363b22a16",
    "parent_merge": "73b1277b218a1f178e424790271aa161d8ee9365",
    "code_sha": "57e687ddda322c8ee347ad8f7e32a92a1328b918",
    "entry_sha": "0b11cfe382c202b8df1affd054e2ce1bc7e805f1d6132aaf9069219c4532fc82",
    "exit_sha": "673f353408884a8d2510185c1544bcd2afab9fa1448eff25ccfebeffd552fc91",
}
AUTH = dict(runtime_registered=False, activation_id=None, cohort_id=None,
            boundary_ms=None, boundary_utc=None, fresh_collection_started=False,
            formal_fresh_T=0, open_T=0, preboundary_formal_credit=0,
            historical_backfill=False, selection_authority=False,
            promotion_authority=False, execution_authority="NONE",
            order_authority="BLOCKED", live_trade_authority="BLOCKED",
            g6_allowed=False, economic_replays=0, new_candidates=0,
            qualification_economic_replay_started=False)


def sha(value):
    return alpha.sha(value)


def seal(value):
    return {**deepcopy(value), "receipt_sha256": sha(value)}


def verify_seal(value):
    if not isinstance(value, dict) or value.get("receipt_sha256") != sha({
            k: v for k, v in value.items() if k != "receipt_sha256"}):
        raise ValueError("QUALIFICATION_RECEIPT_HASH")


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_path(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("INPUT_PATH_ESCAPE:" + str(relative))
    return path


def interval_overlap(left, right, interval_ms):
    """Frozen half-open calendars only, no source prices or chosen windows."""
    if (type(interval_ms) is not int or interval_ms <= 0 or
            any(type(x) is not int for x in (*left, *right)) or
            len(left) != 2 or len(right) != 2 or
            left[0] >= left[1] or right[0] >= right[1]):
        raise ValueError("INVALID_FROZEN_INTERVAL")
    if any(x % interval_ms for x in (*left, *right)):
        raise ValueError("INTERVAL_NOT_BAR_ALIGNED")
    start, end = max(left[0], right[0]), min(left[1], right[1])
    duration = max(0, end - start)
    total = (left[1] - left[0]) // interval_ms
    return dict(canonical_interval=list(left), used_interval=list(right),
                intersection=None if not duration else [start, end],
                overlap_ms=duration, overlap_bars=duration // interval_ms,
                canonical_bars=total,
                overlap_percent=100.0 * duration / (left[1] - left[0]))


def load_inputs(root=ROOT):
    """Finite metadata whitelist and byte hashes; never decode OHLCV/results."""
    paths = (PRIOR + "ARCHITECTURE_SEAL.json", PRIOR + "G5B_HANDOFF.json",
             PRIOR + "CHALLENGE_WINDOW_SEALED.json", PARENT + "SPEC.json",
             ADMISSION, CONTRACT, SPEC)
    documents, pins = {}, {}
    for relative in paths:
        path = bound_path(root, relative)
        documents[relative] = json.loads(path.read_text())
        pins[relative] = file_sha(path)
    architecture = documents[paths[0]]
    authorization = documents[SPEC]
    required_authorization = dict(scope_key=SCOPE, authorization_issue=1270,
        exact_candidate=EXPECTED["candidate_id"], candidate_ordinal=82,
        strategy_digest=EXPECTED["strategy_digest"], qualification_attempts_authorized=1,
        new_candidates_authorized=0, parameter_or_window_changes_authorized=0,
        paid_AI_calls_authorized=0, retries_authorized=0,
        qualification_economics_in_CI=False, stop_on_g5a_or_parity_failure=True)
    for key, expected in required_authorization.items():
        if type(authorization.get(key)) is not type(expected) or authorization.get(key) != expected:
            raise ValueError("QUALIFICATION_SCOPE_AUTHORITY:" + key)
    identity = architecture["identity"]
    handoff = documents[paths[1]]
    if (architecture["strategy_digest"] != EXPECTED["strategy_digest"] or
            sha(identity) != EXPECTED["strategy_digest"]):
        raise ValueError("EXACT_STRATEGY_DIGEST_MISMATCH")
    for key in ("strategy_name", "candidate_id", "candidate_ordinal", "strategy_digest",
                "code_sha", "entry_sha", "exit_sha"):
        if handoff.get(key) != EXPECTED[key]:
            raise ValueError("EXACT_HANDOFF_IDENTITY:" + key)
    if (identity["parent_exact_merge_sha"] != EXPECTED["parent_merge"] or
            identity["implementation_rule"] != EXPECTED["candidate_id"] or
            identity["parent_spec_sha256"] != pins[PARENT + "SPEC.json"] or
            handoff["architecture_seal_sha256"] != pins[paths[0]]):
        raise ValueError("EXACT_PARENT_BINDING_MISMATCH")
    # Full transitive implementation pins are preserved exactly, including
    # original non-runtime evidence owners. No old owner is rewritten here.
    additional = {**identity["implementation_files_sha256"],
                  **identity["benchmark_source_receipts_sha256"],
                  identity["parent_source_binding_path"]:
                  identity["parent_source_binding_sha256"]}
    for relative, expected in additional.items():
        digest = file_sha(bound_path(root, relative))
        if digest != expected:
            raise ValueError("EXACT_PARENT_SOURCE_DRIFT:" + relative)
        pins[relative] = digest
    for key, parts in (("entry_sha", ("chart_mechanism", "m1_er_range", "c63_daily_ema21", "c63_c70_trader_management")),
                       ("exit_sha", ("c70_tm_capreuse", "c63_c70_trader_management"))):
        selected = {p: v for p, v in identity["implementation_files_sha256"].items()
                    if any(part in p for part in parts)}
        if sha(selected) != EXPECTED[key]:
            raise ValueError("EXACT_COMPONENT_DIGEST:" + key)
    if identity["mechanism_sha"] != sha(identity["exact_rules"]):
        raise ValueError("EXACT_MECHANISM_DIGEST")
    admission, contract = documents[ADMISSION], documents[CONTRACT]
    verify_seal(admission)
    verify_seal(admission["development"])
    verify_seal(contract)
    for relative, expected in admission["development"]["source_files_sha256"].items():
        digest = file_sha(bound_path(root, relative))
        if digest != expected:
            raise ValueError("CANONICAL_SOURCE_COST_DRIFT:" + relative)
        pins[relative] = digest
    for relative in (ALPHA, SELF, "backend/research/rebuild/g5b_operational_terminal_v1.py",
                     "backend/research/rebuild/step7_candidate_contract_v1.py"):
        pins[relative] = file_sha(bound_path(root, relative))
    # Presence is recorded separately; a saved missing file is not fabricated.
    manifest = bound_path(root, MANIFEST)
    manifest_status = dict(path=MANIFEST, exists=manifest.is_file(),
                           sha256=file_sha(manifest) if manifest.is_file() else None,
                           contents_decoded=False, authenticity_verified=False)
    if manifest.is_file():
        pins[MANIFEST] = manifest_status["sha256"]
    return documents, pins, manifest_status


def candidate_from_architecture(architecture):
    # The original strategy_digest remains untouched. The gate's candidate SHA
    # is the hash of this explicit binding wrapper, never a replacement digest.
    value = dict(candidate_id=EXPECTED["candidate_id"], research_only=True,
                 required_sources=["native_4h_OHLCV"],
                 strategy_digest=EXPECTED["strategy_digest"],
                 candidate_ordinal=EXPECTED["candidate_ordinal"],
                 frozen_architecture_identity=architecture["identity"])
    return {**value, "candidate_sha256": sha(value)}


def feature_map(identity):
    rules = identity["exact_rules"]
    descriptions = (
        ("original_m1_squeeze_setup", "Completed native M1 squeeze setup", "Completed 4h OHLCV only",
         "long next executable open", "Original setup expiry or fixed floor invalidates"),
        ("c63_er_or_range_eligibility", "Original ER/range eligibility retains squeeze continuation",
         "Completed 4h efficiency ratio and prior fixed setup range", "original eligibility only",
         "Original ER/range predicate false"),
        ("daily21_or_sma5_range_escape", rules["entry"]["rule"],
         "Completed UTC daily EMA21/SMA5 and completed 4h strict range escape",
         "daily21 eligible OR original nonfalling SMA5 range escape", "Both original alternatives false"),
    )
    return dict(features=[dict(name=n, mechanism=m, observable=o, direction=d,
                              invalidation=i, entry_time_observable=True,
                              source_owner_functions=rules["entry"]["authoritative_functions"],
                              source_entry_sha=EXPECTED["entry_sha"],
                              ablation="remove_" + n, ablation_executed=False)
                          for n, m, o, d, i in descriptions],
                redundant_pairs=[], ablation_plan_complete=True,
                plan_scope="FEATURE_MAP_ONLY_NO_ABLATION_EXECUTION_OR_AUTHORITY",
                lifecycle_is_not_additional_entry_feature=True)


def build_bundle(documents, pins, manifest_status, overlap):
    architecture = documents[PRIOR + "ARCHITECTURE_SEAL.json"]
    candidate = candidate_from_architecture(architecture)
    development = documents[ADMISSION]["development"]
    features = feature_map(architecture["identity"])
    return dict(
        candidate=candidate,
        primary_evidence=dict(supports=[],
            stored_source_receipts_sha256=architecture["identity"]["benchmark_source_receipts_sha256"],
            limitation="Stored benchmark references are real, but no reviewed exact-candidate P0 support/methodological bundle is supplied; references are not automatically mechanistic PASS."),
        feature_causal_map=features,
        parameter_provenance=dict(numeric_parameter_inventory_complete=False, parameters=[],
            frozen_rule_source_sha=pins[PRIOR + "ARCHITECTURE_SEAL.json"],
            limitation="No exhaustive exact-candidate transitive numeric inventory with individual provenance and development-justification receipts exists in the bound inputs."),
        development_feasibility=dict(separated_from_prospective_holdout=False,
            holdout_outcomes_used=overlap["overlap_bars"] > 0,
            development_data_sha=development["dataset_sha256"],
            metrics={k: None for k in ("event_count", "completed_trades", "forward_move_bps_median",
                "mfe_bps_median", "mae_bps_median", "gross_expectancy_bps", "realistic_cost_bps", "event_rate_per_day")},
            launch_gate_source="SSOT:backend/research/rebuild/g5b_operational_terminal_v1.py:freeze_boundary",
            launch_gate_pass=False,
            limitation="No formal exact-v1 economic replay; reused DEV metrics are not substituted for canonical qualification."),
        negative_controls_and_ablation=dict(
            controls=[dict(kind=k, applicable=True, passed=False,
                           status="NO_EXACT_CANONICAL_QUALIFICATION_EXECUTION")
                      for k in sorted(alpha.REQUIRED_CONTROL_KINDS)],
            feature_ablations=[dict(feature=f["name"], applicable=True, passed=False,
                                   status="NO_EXACT_CANONICAL_QUALIFICATION_EXECUTION")
                              for f in features["features"]], holdout_outcomes_used=None),
        multi_ai_adversarial_review=dict(controller_review_sha=None, provider_reviews=[],
            limitation="No matching independent provider receipts supplied; subagent reviews cannot substitute for distinct providers."),
        source_implementation_reality=dict(admission_stage="G5A_DEVELOPMENT",
            immutable_history_verified=False, split_frozen_before_outcomes=False,
            development_cost_model_bound=False,
            development_data_sha=development["dataset_sha256"], formal_production_credit=0,
            sources=[dict(name="native_4h_OHLCV", available=manifest_status["exists"],
                proxy=False, historical_immutable=False, semantic_valid=False,
                source_sha=development["dataset_sha256"],
                limitation="Original general history metadata does not attest an unexposed candidate82 canonical OOS.")],
            duplicate_count=None, leakage_count=None, timestamp_order_error_count=None,
            integrity_defect_count=None, verified_round_trip_cost_bps=None,
            cost_authority_sha=development["receipt_sha256"],
            known_canonical_cost_authority=documents[CONTRACT]["cost_authority_path"],
            snapshot_dev_costs_are_production_grade=False,
            null_integrity_counts_are_not_zero_proof=True))


def _qualification(root=ROOT, *, issued_at_ms):
    """Root sole owner calls only behind qualify_once's exclusive attempt file."""
    if type(issued_at_ms) is not int or issued_at_ms <= 0:
        raise ValueError("QUALIFICATION_TIMESTAMP_REQUIRED")
    documents, pins, manifest_status = load_inputs(root)
    development = documents[ADMISSION]["development"]
    contract = documents[CONTRACT]
    parent = documents[PARENT + "SPEC.json"]
    used = parent["periods"]["SEEN2026"]
    overlap = interval_overlap(development["splits"]["purged_OOS"],
                               [used["start_ms"], used["runoff_end_ms"]],
                               contract["source_interval_ms"])
    # This is a provenance-rejection successor, not a generic fallback runner.
    # If its known premise changes, no new window/route/experiment is invented.
    if overlap["overlap_bars"] <= 0:
        raise ValueError("CANONICAL_EXPOSURE_PREMISE_CHANGED_NO_AUTOMATIC_QUALIFICATION")
    bundle = build_bundle(documents, pins, manifest_status, overlap)
    proof = alpha.evaluate_bundle(bundle)
    if proof["p0_p6_passed"]:
        raise ValueError("UNEXPECTED_ALPHA_PASS_FOR_UNQUALIFIED_SOURCE")
    candidate_sha = bundle["candidate"]["candidate_sha256"]
    blockers = ["CANONICAL_PURGED_OOS_ALREADY_USED_FOR_CANDIDATE82_DEVELOPMENT",
                "EXACT_CANDIDATE_INDEPENDENT_NINE_REPORT_PRODUCER_RECEIPTS_ABSENT",
                "CANONICAL_26_BAR_EMBARGO_NOT_VALIDATED_FOR_UNBOUNDED_RUNNER"]
    if not manifest_status["exists"]:
        blockers.append("CANONICAL_DATASET_MANIFEST_MISSING_IN_CHECKOUT")
    reports = {name: dict(complete=False, receipt_sha256=None,
                         candidate_sha256=candidate_sha,
                         strategy_digest=EXPECTED["strategy_digest"],
                         data_sha=development["dataset_sha256"],
                         cost_sha=development["receipt_sha256"],
                         status="NOT_RUN_PROVENANCE_GATE_REJECT", metrics=None,
                         actual_producer_execution=False,
                         blocker="CANONICAL_PURGED_OOS_ALREADY_USED" if name == "purged_oos"
                         else "NO_INDEPENDENT_EXACT_CANDIDATE_EXECUTION_RECEIPT")
               for name in REPORTS}
    economics = seal(dict(state="G5A_FAIL_NO_G5B_ACTIVATION", candidate_sha256=candidate_sha,
        strategy_digest=EXPECTED["strategy_digest"], alpha_proof_receipt_sha=proof["receipt_sha256"],
        reports=reports, net_expectancy_bps=None, profit_factor=None, cost2x_net_bps=None,
        purged_oos_pass=False, negative_controls_superior=None, no_leakage=None,
        no_cherry_pick=False, duplicate=None, economic_replays=0))
    return seal(dict(schema_version="zel.squeeze.g5a.qualification.v1", scope_key=SCOPE,
        issue=1270, issued_at_ms=issued_at_ms, qualification_attempt=1,
        qualification_spec_sha256=pins[SPEC],
        state="G5A_FAIL_NO_G5B_ACTIVATION",
        verdict="BLOCKED_CANONICAL_PURGED_OOS_ALREADY_USED_FOR_CANDIDATE82_DEVELOPMENT",
        qualification_kind="FORMAL_PROVENANCE_GATE_EVALUATED_NO_ECONOMIC_REPLAY",
        original_identity=EXPECTED, candidate_sha256=candidate_sha,
        original_strategy_digest_preserved=True, source_files_sha256=pins,
        candidate_data_cost_binding=dict(candidate_sha256=candidate_sha,
            strategy_digest=EXPECTED["strategy_digest"], data_sha=development["dataset_sha256"],
            cost_sha=development["receipt_sha256"], alpha_proof_receipt_sha=proof["receipt_sha256"]),
        canonical_partitions=development["splits"], canonical_source_contract_sha=contract["receipt_sha256"],
        canonical_cost_sha=development["receipt_sha256"],
        canonical_cost_model=development["development_cost_model"],
        canonical_manifest=manifest_status, used_dev_oos_overlap=overlap,
        prior_unused_window_status=documents[PRIOR + "CHALLENGE_WINDOW_SEALED.json"]["reason"],
        canonical_26_bar_embargo_scope=contract["split"]["embargo_rule"],
        exact_unbounded_runner_purge_authority=None,
        alpha_bundle=bundle, alpha_bundle_sha256=sha(bundle), alpha_owner_result=proof,
        alpha_call_receipt=seal(dict(owner_path=ALPHA, owner_file_sha256=pins[ALPHA],
            input_bundle_sha256=sha(bundle), output_receipt_sha256=proof["receipt_sha256"],
            calls=1, economic_replays=0)),
        p0_p6={g["gate"].split("_", 1)[0]: "PASS" if g["passed"] else "FAIL"
               for g in proof["gates"] if g["gate"] != "P-IDENTITY"},
        p0_p6_passed=False, caller_integrity_exact_zero_pass=False,
        report_complete_count=0, report_total=9, report_hash_parity=False,
        report_envelope_identity_parity=True, economics=economics,
        blockers=blockers, market_data_rows_decoded=0, provider_calls=0,
        boundary_constructor_called=False, collector_started=False, **AUTH))


def _exclusive_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False) + "\n").encode()
    # O_EXCL prevents two callers from authorizing a second qualification.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def qualify_once(root=ROOT, *, issued_at_ms=None):
    """One explicit call. Any started attempt consumes this successor's slot."""
    output, attempt = bound_path(root, OUT), bound_path(root, ATTEMPT)
    if output.exists() or attempt.exists():
        raise ValueError("QUALIFICATION_ALREADY_ISSUED_OR_STARTED_NO_RETRY")
    issued_at_ms = time.time_ns() // 1_000_000 if issued_at_ms is None else issued_at_ms
    ticket = seal(dict(scope_key=SCOPE, issue=1270, qualification_attempt=1,
                       state="RESERVED_BEFORE_PROVENANCE_GATE", issued_at_ms=issued_at_ms,
                       strategy_digest=EXPECTED["strategy_digest"], economic_replays=0))
    try:
        _exclusive_json(attempt, ticket)
    except FileExistsError:
        raise ValueError("QUALIFICATION_ALREADY_ISSUED_OR_STARTED_NO_RETRY") from None
    result = _qualification(root, issued_at_ms=issued_at_ms)
    result.pop("receipt_sha256")
    result["attempt_receipt_sha256"] = ticket["receipt_sha256"]
    result = seal(result)
    _exclusive_json(output, result)
    return result


def verify_only(root=ROOT):
    """Saved evidence verification only: no alpha call or qualification replay."""
    result = json.loads(bound_path(root, OUT).read_text())
    verify_seal(result)
    attempt = json.loads(bound_path(root, ATTEMPT).read_text())
    verify_seal(attempt)
    if (attempt["receipt_sha256"] != result["attempt_receipt_sha256"] or
            attempt["issued_at_ms"] != result["issued_at_ms"] or
            attempt["strategy_digest"] != EXPECTED["strategy_digest"] or
            result.get("original_identity") != EXPECTED or result.get("scope_key") != SCOPE or
            result.get("state") != "G5A_FAIL_NO_G5B_ACTIVATION"):
        raise ValueError("QUALIFICATION_IDENTITY_OR_ATTEMPT_DRIFT")
    for relative, expected in result["source_files_sha256"].items():
        if file_sha(bound_path(root, relative)) != expected:
            raise ValueError("QUALIFICATION_SOURCE_BYTES_DRIFT:" + relative)
    missing = result["canonical_manifest"]
    if not missing["exists"] and bound_path(root, missing["path"]).exists():
        raise ValueError("QUALIFICATION_MANIFEST_PRESENCE_CHANGED")
    for key, expected in AUTH.items():
        if type(result.get(key)) is not type(expected) or result.get(key) != expected:
            raise ValueError("QUALIFICATION_AUTHORITY_DRIFT:" + key)
    proof, economics = result["alpha_owner_result"], result["economics"]
    verify_seal(proof)
    verify_seal(economics)
    call = result["alpha_call_receipt"]
    verify_seal(call)
    if (call.get("calls") != 1 or call.get("economic_replays") != 0 or
            call.get("owner_path") != ALPHA or
            call.get("owner_file_sha256") != result["source_files_sha256"][ALPHA] or
            call.get("input_bundle_sha256") != sha(result["alpha_bundle"]) or
            result["alpha_bundle_sha256"] != sha(result["alpha_bundle"]) or
            call.get("output_receipt_sha256") != proof["receipt_sha256"]):
        raise ValueError("QUALIFICATION_ALPHA_CALL_BINDING")
    candidate = result["alpha_bundle"]["candidate"]
    if sha({k: v for k, v in candidate.items() if k != "candidate_sha256"}) != result["candidate_sha256"]:
        raise ValueError("QUALIFICATION_CANDIDATE_HASH")
    if (proof["candidate_sha256"] != result["candidate_sha256"] or
            economics["candidate_sha256"] != result["candidate_sha256"] or
            economics["alpha_proof_receipt_sha"] != proof["receipt_sha256"] or
            proof["p0_p6_passed"] is not False or result["p0_p6_passed"] is not False):
        raise ValueError("QUALIFICATION_ALPHA_ECONOMICS_PARITY")
    states = {g["gate"].split("_", 1)[0]: "PASS" if g["passed"] else "FAIL"
              for g in proof["gates"] if g["gate"] != "P-IDENTITY"}
    if states != result["p0_p6"] or set(states) != {"P" + str(i) for i in range(7)}:
        raise ValueError("QUALIFICATION_GATE_STATUS_PARITY")
    reports = economics["reports"]
    if set(reports) != set(REPORTS) or result["report_complete_count"] != 0 or result["report_hash_parity"] is not False:
        raise ValueError("QUALIFICATION_REPORT_INCOMPLETE_PARITY")
    for name, report in reports.items():
        if (report["complete"] is not False or report["receipt_sha256"] is not None or
                report["metrics"] is not None or report["actual_producer_execution"] is not False or
                report["candidate_sha256"] != result["candidate_sha256"] or
                report["data_sha"] != result["candidate_data_cost_binding"]["data_sha"] or
                report["cost_sha"] != result["candidate_data_cost_binding"]["cost_sha"]):
            raise ValueError("QUALIFICATION_FALSE_REPORT_COMPLETION:" + name)
    for key in ("net_expectancy_bps", "profit_factor", "cost2x_net_bps", "duplicate",
                "negative_controls_superior", "no_leakage"):
        if economics[key] is not None:
            raise ValueError("QUALIFICATION_UNEXECUTED_METRIC:" + key)
    overlap = result["used_dev_oos_overlap"]
    contract = json.loads(bound_path(root, CONTRACT).read_text())
    admission = json.loads(bound_path(root, ADMISSION).read_text())
    parent = json.loads(bound_path(root, PARENT + "SPEC.json").read_text())
    canonical = admission["development"]
    used = parent["periods"]["SEEN2026"]
    recomputed = interval_overlap(canonical["splits"]["purged_OOS"],
                                  [used["start_ms"], used["runoff_end_ms"]],
                                  contract["source_interval_ms"])
    if overlap != recomputed or overlap["overlap_bars"] <= 0:
        raise ValueError("QUALIFICATION_EXPOSURE_ARITHMETIC")
    if (result["canonical_partitions"] != canonical["splits"] or
            result["candidate_data_cost_binding"]["data_sha"] != canonical["dataset_sha256"] or
            result["candidate_data_cost_binding"]["cost_sha"] != canonical["receipt_sha256"] or
            result["qualification_spec_sha256"] != result["source_files_sha256"][SPEC]):
        raise ValueError("QUALIFICATION_SOURCE_IDENTITY_BINDING")
    architecture = json.loads(bound_path(root, PRIOR + "ARCHITECTURE_SEAL.json").read_text())
    if candidate["frozen_architecture_identity"] != architecture["identity"]:
        raise ValueError("QUALIFICATION_CANDIDATE_ARCHITECTURE_BINDING")
    return dict(status="PASS_SAVED_QUALIFICATION_REJECTION_VERIFIED",
                qualification_reexecuted=False, economics_reexecuted=False,
                receipt_sha256=result["receipt_sha256"], p0_p6=result["p0_p6"],
                report_complete_count=0, runtime_registered=False,
                boundary_ms=None, fresh_collection_started=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--qualify-once", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    result = qualify_once(args.root) if args.qualify_once else verify_only(args.root)
    print(json.dumps({k: result[k] for k in ("state", "status", "p0_p6", "report_complete_count",
          "runtime_registered", "boundary_ms", "fresh_collection_started", "receipt_sha256")
          if k in result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
