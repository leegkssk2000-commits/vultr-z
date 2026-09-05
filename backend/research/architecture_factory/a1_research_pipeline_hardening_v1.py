#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
MECH = ROOT / "backend/research/architecture_factory/a1_mechanism_first_research_latest.json"
YT = ROOT / "backend/research/architecture_factory/a1_youtube_evidence_latest.json"
NAMED = ROOT / "backend/research/architecture_factory/a1_named_channel_gemini_latest.json"
A5 = ROOT / "backend/research/architecture_factory/a1_a5_economic_improvement_latest.json"
TESTS = ROOT / "backend/research/architecture_factory/a1_external_evidence_test_ledger_v1.json"
G5 = ROOT / "backend/research/prep/g5_trendrider_broad30_product_latest.json"
PROVIDER = ROOT / "backend/production/zel_production_external_research_observer_v1.py"
V4 = ROOT / "backend/research/architecture_factory/a1_named_channel_gemini_sweep_v4.py"
V6 = ROOT / "backend/research/architecture_factory/a1_named_channel_gemini_sweep_v6.py"
NAMED_WF = ROOT / ".github/workflows/a1-named-channel-gemini-sweep-v1.yml"
A5_WF = ROOT / ".github/workflows/a1-a5-economic-improvement-v5.yml"
SCHEMA = "zel.a1_research_pipeline_hardening.v1"


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def tokens(text: str) -> Counter[str]:
    words = re.findall(r"[a-z0-9_가-힣]+", str(text).casefold())
    return Counter(words)


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def mechanism_rows(value: Any, path: str = "$") -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        mech = value.get("mechanism")
        if isinstance(mech, str) and mech.strip():
            sid = str(value.get("strategy_id") or value.get("host_strategy_id") or value.get("candidate_id") or "GLOBAL")
            evid = value.get("external_evidence_ids") or value.get("evidence_ids") or []
            if not isinstance(evid, list):
                evid = [evid]
            source_id = str(value.get("id") or value.get("source_id") or value.get("identifier") or value.get("video_id") or "")
            out.append({
                "path": path,
                "strategy_scope": sid,
                "mechanism": " ".join(mech.split()),
                "source_ids": ",".join(sorted({str(x) for x in evid if x} | ({source_id} if source_id else set()))),
            })
        for k, v in value.items():
            out.extend(mechanism_rows(v, f"{path}.{k}"))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.extend(mechanism_rows(v, f"{path}[{i}]"))
    return out


def dedup(rows: list[dict[str, str]], threshold: float = 0.85) -> dict[str, Any]:
    clusters: list[dict[str, Any]] = []
    exact: dict[str, int] = {}
    semantic_collapses = 0
    exact_collapses = 0
    for row in rows:
        norm = " ".join(re.findall(r"[a-z0-9_가-힣]+", row["mechanism"].casefold()))
        fp = hashlib.sha256(norm.encode()).hexdigest()
        if fp in exact:
            exact_collapses += 1
            c = clusters[exact[fp]]
            c["source_ids"] = sorted(set(c["source_ids"]) | set(filter(None, row["source_ids"].split(","))))
            c["member_count"] += 1
            continue
        vec = tokens(norm)
        matched = None
        best = 0.0
        for i, c in enumerate(clusters):
            score = cosine(vec, c["_vec"])
            if score > best:
                best, matched = score, i
        if matched is not None and best > threshold:
            semantic_collapses += 1
            c = clusters[matched]
            c["source_ids"] = sorted(set(c["source_ids"]) | set(filter(None, row["source_ids"].split(","))))
            c["member_count"] += 1
            c["max_collapsed_cosine"] = max(float(c.get("max_collapsed_cosine") or 0.0), best)
            exact[fp] = matched
            continue
        idx = len(clusters)
        exact[fp] = idx
        clusters.append({
            "mechanism_fingerprint_sha256": fp,
            "mechanism": row["mechanism"],
            "strategy_scope": row["strategy_scope"],
            "source_ids": sorted(set(filter(None, row["source_ids"].split(",")))),
            "member_count": 1,
            "max_collapsed_cosine": 0.0,
            "_vec": vec,
        })
    public = []
    for c in clusters:
        x = dict(c); x.pop("_vec", None); public.append(x)
    return {
        "cosine_threshold_strict_gt": threshold,
        "input_mechanism_rows": len(rows),
        "unique_mechanism_clusters": len(public),
        "exact_duplicates_collapsed": exact_collapses,
        "semantic_duplicates_collapsed": semantic_collapses,
        "clusters": public,
    }


def _depth_counts(mech: Mapping[str, Any]) -> dict[str, Any]:
    d = mech.get("depth_retry_guard") or {}
    e = d.get("evidence_counts") or {}
    def obs(key: str) -> int:
        raw = e.get(key) or {}
        return int(raw.get("observed") or 0) if isinstance(raw, Mapping) else 0
    return {
        "unique_documents": obs("unique_documents"),
        "source_families": obs("source_families"),
        "high_tier_docs": obs("high_tier_documents"),
        "crypto_specific_docs": obs("crypto_specific_documents"),
        "official_exchange_docs": obs("official_exchange_documents"),
        "validation_docs": obs("validation_documents"),
        "crypto_derivatives_or_microstructure_docs": obs("crypto_derivatives_or_microstructure_documents"),
        "depth_guard_state": d.get("state"),
        "depth_guard_next": d.get("next"),
    }


def manual_bridge_ci_binding(workflow: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the audit to the current V10 manual/frozen24 CI owner.

    V5 named-axis marker strings disappeared when that workflow was replaced.
    Source-to-test traceability remains a separate required check below.
    Require executable assertion lines in the PR verify job, actual contract
    values, and the manual-only paid boundary; comments cannot satisfy a guard.
    """
    required = {
        "assert c['trend_rider']['historical_union_allowed'] is False",
        "assert c['trend_rider']['historical_metrics_formal_credit'] == 0",
        "assert c['trend_rider']['rr_exit_mutation_allowed'] is False",
        "assert c['trend_rider']['new_fresh_boundary_required'] is True",
        "assert p['automatic_paid_schedule_allowed'] is False",
        "assert p['manual_blocker_scoped_only'] is True",
        "assert p['max_paid_requests_per_manual_invocation'] == 1",
        "assert p['paid_ai_output_is_formal_credit'] is False",
        "assert r['authority_match'] is True, r",
        "assert r['g5_formal_credit_before_fresh'] == 0, r",
        "assert r['rr_exit_mutated'] is False, r",
        "assert r['selection_authority'] is False and r['promotion_authority'] is False, r",
        "assert r['execution_authority']=='NONE' and r['order_authority']=='BLOCKED' and r['live_trade_authority']=='BLOCKED', r",
    }
    verify = workflow.split('  verify:\n', 1)[-1].split('  manual-research:\n', 1)[0]
    assertions = {line.strip() for line in verify.splitlines() if line.lstrip().startswith('assert ')}
    expected = {
        'trend_rider': {'historical_union_allowed': False, 'historical_metrics_formal_credit': 0,
                       'rr_exit_mutation_allowed': False, 'parent_incumbent_mutation_allowed': False,
                       'candidate_freeze_required': True, 'new_fresh_boundary_required': True},
        'paid_ai_policy': {'automatic_paid_schedule_allowed': False, 'default_paid_requests': 0,
                           'manual_blocker_scoped_only': True, 'max_paid_requests_per_manual_invocation': 1,
                           'paid_ai_output_is_formal_credit': False},
        'authorities': {'selection_authority': False, 'promotion_authority': False,
                        'execution_authority': 'NONE', 'order_authority': 'BLOCKED', 'live_trade_authority': 'BLOCKED'},
    }
    mismatch = [group+'.'+key for group, values in expected.items() for key, value in values.items()
                if type((contract.get(group) or {}).get(key)) is not type(value)
                or (contract.get(group) or {}).get(key) != value]
    missing = sorted(required-assertions)
    manual_only = ("  manual-research:\n    if: github.event_name == 'workflow_dispatch'" in workflow
                   and '\n  schedule:' not in workflow and '\n  push:' not in workflow)
    source_bound = ('a1_trend_rider_wr8125_dynamic_trendline_htf_attribution_v2.py --self-test' in verify
                    and "if: github.event_name == 'pull_request'" in verify)
    return {'passed': not missing and not mismatch and manual_only and source_bound,
            'owner': 'A1_TOP5_V10_MANUAL_COST_FROZEN24_CI', 'missing_assertions': missing,
            'contract_mismatches': mismatch, 'manual_only': manual_only, 'source_bound': source_bound,
            'formal_or_economic_credit_granted': False}


def run(output: Path) -> dict[str, Any]:
    mech, yt, named, a5, tests, g5 = map(read, (MECH, YT, NAMED, A5, TESTS, G5))
    provider = PROVIDER.read_text(encoding="utf-8")
    v4 = V4.read_text(encoding="utf-8")
    v6 = V6.read_text(encoding="utf-8")
    nwf = NAMED_WF.read_text(encoding="utf-8")
    awf = A5_WF.read_text(encoding="utf-8")

    capability_safe = all(x in provider for x in ("supportedGenerationMethods", "generateContent", "_list_models"))
    bounded_retry = all(x in v4 for x in ("RETRYABLE_MARKERS", "(0, 3, 8)", "time.sleep(delay)"))
    recursion_fix = all(x in v6 for x in ("_ORIG_V2_NORMALIZE", "V6_SAFE_ORIGINAL_V2_PLUS_V4_BUCKET_METADATA"))
    provider_ci = all(x in nwf for x in ("a1_named_channel_gemini_sweep_v6 --self-test", "v2_v4_recursion_guard", "oembed_prevalidation_enabled"))
    bridge_binding = manual_bridge_ci_binding(awf, read(ROOT / "backend/research/contracts/g5_entry_fusion_rescue_v1.json"))
    bridge_ci = bridge_binding["passed"]

    named_bridge = a5.get("named_channel_executable_bridge") or {}
    prior = a5.get("prior_economic_attempted_axes") or {}
    historically_consumed_named = sorted({axis for rows in prior.values() if isinstance(rows, list) for axis in rows if str(axis).startswith("YTNAMED_")})
    traceable = [x for x in (tests.get("tests") or []) if isinstance(x, Mapping)]
    tested_count = len(traceable)
    dev_pass = sum(1 for x in traceable if str(x.get("disposition") or "").startswith("PASS"))
    falsified = sum(1 for x in traceable if "FALSIFIED" in str(x.get("disposition") or ""))
    children = sum(1 for x in traceable if x.get("prospective_child_created") is True)
    pass_without_child = [x.get("candidate_id") for x in traceable if str(x.get("disposition") or "").startswith("PASS") and x.get("prospective_child_created") is not True]

    rows = mechanism_rows(mech) + mechanism_rows(named)
    novelty = dedup(rows)
    depth = _depth_counts(mech)
    yt_errors = ((yt.get("discovery") or {}).get("search_errors") or [])
    anti_bot = sum(1 for x in yt_errors if "not a bot" in str(x).casefold() or "cookies" in str(x).casefold())

    authority_ok = (
        a5.get("selection_authority") is False and a5.get("promotion_authority") is False
        and a5.get("execution_authority") == "NONE" and a5.get("order_authority") == "BLOCKED"
        and a5.get("live_trade_authority") == "BLOCKED" and int(a5.get("protected_mutations") or 0) == 0
        and g5.get("execution_authority") == "NONE" and g5.get("order_authority") == "BLOCKED"
        and g5.get("live_trade_authority") == "BLOCKED" and int(g5.get("protected_mutations") or 0) == 0
    )
    ready = int(named_bridge.get("eligible_axis_count") or 0)
    source_to_test_ok = ready == 0 or tested_count > 0
    routing_ok = (falsified == 0) or bool(depth.get("depth_guard_next"))
    child_rule_ok = not pass_without_child
    cost_guard = int(a5.get("paid_request_cap") or 0) <= 3 and (a5.get("policy") or {}).get("no_threshold_sweep") is True
    high_view_honest = (yt.get("policy") or {}).get("youtube_requires_verified_view_snapshot_before_acceptance") is True

    retained_residue = {
        "named_channel_ledger_checked_at_utc": named.get("checked_at_utc"),
        "historical_provider_errors_retained": bool((named.get("provider") or {}).get("errors")),
        "owner": "a1_named_channel_gemini_sweep_v6",
        "reason": "Immutable historical provider/discovery errors are retained for audit; active provider capability is determined from current code and CI guards, not stale error strings.",
    }

    checks = {
        "provider_capability_safe": capability_safe,
        "provider_bounded_retry": bounded_retry,
        "provider_recursion_fix_present": recursion_fix,
        "provider_ci_self_test_bound": provider_ci,
        "source_ocean_depth_guard_pass": depth.get("depth_guard_state") == "PASS_RESEARCH_DEPTH_RETRY_GUARD",
        "semantic_novelty_ledger_persistable": novelty["input_mechanism_rows"] > 0 and novelty["unique_mechanism_clusters"] > 0,
        "g4_g5_bridge_ci_bound": bridge_ci,
        "ready_implies_traceable_test": source_to_test_ok,
        "traceable_external_test_present": tested_count > 0,
        "failed_tests_falsified_and_routed": routing_ok,
        "development_pass_requires_child": child_rule_ok,
        "high_view_metadata_guarded": high_view_honest,
        "deep_review_cost_guard_explicit": cost_guard,
        "authorities_and_parents_guarded": authority_ok,
    }
    terminal = all(checks.values())
    state = "RESEARCH_PIPELINE_HARDENED_COMPLETE" if terminal else "HOLD_RESEARCH_PIPELINE_HARDENING_INCOMPLETE"
    out = {
        "schema_version": SCHEMA,
        "state": state,
        "checks": checks,
        "source_ocean": depth,
        "semantic_novelty_ledger": novelty,
        "youtube": {
            "verified_100k_count": int(yt.get("preferred_100k_count") or 0),
            "verified_30k_fallback_count": int(yt.get("fallback_30k_count") or 0),
            "new_reviews": int(yt.get("new_review_count") or 0),
            "discovery_error_count": int((yt.get("discovery") or {}).get("search_error_count") or 0),
            "anti_bot_or_cookie_error_count": anti_bot,
            "degraded_discovery_is_global_blocker": False,
        },
        "bridge_ci_contract": bridge_binding,
        "evidence_bridge": {
            "current_ready_named_axes": ready,
            "current_cycle_attempted_named_axes": int(named_bridge.get("attempted_named_axis_count") or 0),
            "historically_consumed_named_axes": len(historically_consumed_named),
            "historically_consumed_named_axis_ids": historically_consumed_named,
            "traceable_tests": tested_count,
            "development_pass_count": dev_pass,
            "falsified_count": falsified,
            "fresh_children_created_from_external_evidence": children,
            "tests": traceable,
            "source_blocked_axes": [x for x in (named_bridge.get("rejected_mapping_sample") or []) if isinstance(x, Mapping)],
            "route_after_falsification": depth.get("depth_guard_next"),
        },
        "provider_hardening": {
            "model_capability_filter": "models endpoint + generateContent supportedGenerationMethods",
            "retry_policy": "retry retryable 429/500/502/503/504/high-demand/timeout at delays 0s,3s,8s",
            "normalizer_recursion_guard": "V6 safe original-V2 normalizer + bucket metadata",
            "named_pipeline_self_tests_bound_in_ci": provider_ci,
        },
        "cost_and_review_guard": {
            "paid_request_cap": int(a5.get("paid_request_cap") or 0),
            "verified_round_trip_cost_bps": 14.0,
            "threshold_sweep_forbidden": (a5.get("policy") or {}).get("no_threshold_sweep") is True,
            "fresh_oos_required": bool(named_bridge.get("fresh_oos_required_before_promotion")),
        },
        "g5_parent_guard": {
            "strategy_id": g5.get("strategy_id"),
            "stage": g5.get("stage"),
            "state": g5.get("state"),
            "postlock_closed_T": g5.get("postlock_closed_T"),
            "receipt_sha256": g5.get("receipt_sha256"),
            "protected_mutations": g5.get("protected_mutations"),
        },
        "retained_residue": retained_residue,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    out["receipt_sha256"] = sha(out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return out


def self_test() -> int:
    assert abs(cosine(tokens("trend filter ema slope"), tokens("trend filter ema slope")) - 1.0) < 1e-12
    d = dedup([
        {"mechanism":"EMA trend filter","strategy_scope":"x","source_ids":"A","path":"$"},
        {"mechanism":"EMA trend filter","strategy_scope":"x","source_ids":"B","path":"$"},
    ])
    assert d["exact_duplicates_collapsed"] == 1 and d["unique_mechanism_clusters"] == 1
    print("PASS_A1_RESEARCH_PIPELINE_HARDENING_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_research_pipeline_hardening_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({"state": result["state"], "checks": result["checks"], "receipt": result["receipt_sha256"]}, sort_keys=True))
    return 0 if result["state"] == "RESEARCH_PIPELINE_HARDENED_COMPLETE" else 2

if __name__ == "__main__":
    raise SystemExit(main())
