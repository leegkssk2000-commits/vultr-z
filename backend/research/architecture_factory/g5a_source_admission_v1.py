"""Point-in-time source admission and terminal audit; no provider calls or replay."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from backend.research.alpha_proof import a1_alpha_proof_gate_v1 as alpha
from backend.research.architecture_factory import g5a_alpha_proof_preflight_v1 as preflight
from backend.research.rebuild import g5_clean_runner_v1 as runner

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "backend/research/architecture_factory"
REGISTRY = DIR / "g5a_source_capability_registry_v1.json"
TERMINAL = DIR / "g5a_source_terminal_dispositions_v1.json"
STATE_PATH = "backend/research/rebuild/g5_clean_runner_state_events_v1.jsonl"
AUTH = {"selection_authority": False, "promotion_authority": False, "execution_authority": "NONE",
        "order_authority": "BLOCKED", "live_trade_authority": "BLOCKED", "exchange_order_submitted": False}


def read(path, root=ROOT):
    return json.loads((root / path).read_text())


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(value):
    return {**value, "receipt_sha256": alpha.sha(value)}


def git_data(ref, path, root=ROOT):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=root)


def audit_native_rows(rows):
    failures = []
    if not rows:
        failures.append("EMPTY_HISTORY")
    for key in ("source_timestamp_ms", "collected_at_ms"):
        times = [r.get(key) for r in rows]
        if any(not isinstance(t, int) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
            failures.append("NONMONOTONIC:" + key)
    inversions = sum(r.get("source_timestamp_ms", 0) > r.get("collected_at_ms", 0) for r in rows)
    if inversions:
        failures.append("SOURCE_AFTER_COLLECTION_CLOCK")
    if any(not r.get("source_payload_sha256") or r.get("prospective_only") is not True for r in rows):
        failures.append("SOURCE_LINEAGE_MISSING")
    return {"rows": len(rows), "first_ms": rows[0]["collected_at_ms"] if rows else None,
            "last_ms": rows[-1]["collected_at_ms"] if rows else None,
            "clock_inversions": inversions, "errors": failures, "point_in_time": not failures}


def inventory(*, native_ref, as_of_ms, root=ROOT):
    effective = read("backend/research/rebuild/g5_clean_runner_contract_effective_v1.json", root)
    stale = read("backend/research/rebuild/g5_data_stale_evidence_v1.json", root)
    events = runner.HashChainLog(root / STATE_PATH).records()
    bars = {}
    for event in events:
        if event["status"] != "NEW":
            continue
        p = event["payload"]
        runner.validate_bar(p)
        if p["bar_close_ts"] > int(__import__("datetime").datetime.fromisoformat(event["event_ts"].replace("Z", "+00:00")).timestamp() * 1000):
            raise RuntimeError("SOURCE_LOOKAHEAD")
        key = p["bar_key"]
        if key in bars and bars[key]["source_bar_sha256"] != p["source_bar_sha256"]:
            raise RuntimeError("SOURCE_DUPLICATE_CONFLICT")
        bars[key] = p
    last = max((p["bar_close_ts"] for p in bars.values()), default=0)
    cadence = stale.get("authority_value") if stale.get("authority_created") is True and stale.get("authority_unit") == "ms" else None
    per_symbol_last = {s: max((p["bar_close_ts"] for p in bars.values() if p["symbol"] == s), default=0) for s in effective["source"]["symbols"]}
    fresh = bool(cadence and all(0 <= as_of_ms - t < cadence for t in per_symbol_last.values()))
    observations = {}
    for feature in ("premium_index", "open_interest"):
        streams = []
        for symbol in ("BTCUSDT", "ETHUSDT"):
            path = f"research/data/p3_prospective/{feature}__{symbol}.ndjson"
            raw = git_data(native_ref, path, root)
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            streams.append({"symbol": symbol, "path": path, "source_sha": hashlib.sha256(raw).hexdigest(), **audit_native_rows(rows)})
        observations[feature] = streams
    sources = []
    for name in ("ohlcv", "volume", "funding", "basis", "open_interest", "bbo", "depth", "liquidation_event"):
        source = {"source": name, "available": False, "historical_depth": None, "timestamp_unit": "ms",
                  "closed_bar_rule": "NOT_APPLICABLE_NATIVE_EVENT", "stale_rule": "NO_AUTHORITY_BLOCK_ADMISSION",
                  "missing_rule": "HOLD_NO_IMPUTATION", "duplicate_rule": "REJECT_CONFLICT_NO_EXTRA_CREDIT",
                  "point_in_time": False, "implementation_path": None, "source_sha": None,
                  "proxy": False, "validated": False, "fresh": False, "decision": "BLOCK_SOURCE_NOT_BOUND"}
        if name in ("ohlcv", "volume"):
            source.update(available=bool(bars), historical_depth={"persisted_unique_symbol_bars": len(bars), "first_close_ms": min((p["bar_close_ts"] for p in bars.values()), default=None), "last_close_ms": last,
                          "fetch_capacity_bars_per_symbol": effective["source"]["max_pages"] * effective["source"]["page_limit"], "capacity_is_observed_history": False},
                          closed_bar_rule=effective["source"]["closed_rule"], stale_rule=stale.get("authority_rule"), stale_limit_ms=cadence,
                          point_in_time=True, implementation_path="backend/research/rebuild/g5_clean_runner_v1.py#BingxSourceAdapter",
                          source_sha=file_sha(root / STATE_PATH), validated=bool(bars), fresh=fresh,
                          decision="PASS" if fresh else "HOLD_SOURCE_STALE")
        elif name in ("funding", "basis", "open_interest"):
            feature = "open_interest" if name == "open_interest" else "premium_index"
            streams = observations[feature]
            source.update(available=all(s["rows"] > 0 for s in streams), historical_depth=streams,
                          point_in_time=all(s["point_in_time"] for s in streams),
                          implementation_path="backend/research/p3_prospective_native_feature_collector.py",
                          source_sha=alpha.sha(streams), decision="HOLD_NATIVE_ALIGNMENT_AND_STALE_AUTHORITY")
            if name == "basis":
                source["semantic_scope"] = "RAW_MARK_AND_INDEX_PRICES; DERIVED_BASIS_NOT_ADMITTED"
            if name == "funding":
                source["semantic_scope"] = "OBSERVED_LAST_FUNDING_RATE_STATE; SETTLEMENT_JOIN_REQUIRED"
            if name == "open_interest" and not source["point_in_time"]:
                source["decision"] = "HOLD_POINT_IN_TIME_CLOCK"
        elif name in ("bbo", "depth"):
            source.update(implementation_path="backend/research/rebuild/g5_forward_real_evidence_bridge_v4.py#ExitResearchBingXProvider.depth",
                          source_sha=file_sha(root / "backend/research/rebuild/g5_forward_real_bridge_state_v1.jsonl"),
                          historical_depth="FORWARD_SNAPSHOTS_ONLY_NO_HISTORICAL_BOOK", decision="HOLD_NO_BOUND_PREENTRY_HISTORY")
            bridge_rows = [json.loads(x) for x in (root / "backend/research/rebuild/g5_forward_real_bridge_state_v1.jsonl").read_text().splitlines() if x.strip()]
            source["available"] = any(r["kind"] == "OPENED_PROVENANCE" and r["payload"].get("entry_depth") for r in bridge_rows)
            if name == "bbo":
                path = root / "backend/research/rebuild/g5_trend_rider_bbo_oos_events_v1.jsonl"
                snapshots = [json.loads(x).get("bbo") for x in path.read_text().splitlines() if x.strip()]
                snapshots = [s for s in snapshots if s]
                source.update(available=bool(snapshots) or source["available"], source_sha=file_sha(path),
                              point_in_time=bool(snapshots) and all(s.get("point_in_time") is True and s["observed_at_ms"] >= s["requested_at_ms"] for s in snapshots),
                              historical_depth={"snapshot_count": len(snapshots), "historical_book": False})
        sources.append(source)
    paths = [STATE_PATH, "backend/research/rebuild/g5_clean_runner_contract_effective_v1.json", "backend/research/rebuild/g5_data_stale_evidence_v1.json", "backend/research/rebuild/g5_forward_real_bridge_state_v1.jsonl", "backend/research/p3_prospective_native_feature_collector.py", "backend/research/architecture_factory/g5a_source_admission_v1.py"]
    paths.append("backend/research/rebuild/g5_trend_rider_bbo_oos_events_v1.jsonl")
    stage_path = "backend/research/architecture_factory/g5a_stage_admission_latest_v1.json"
    development = None
    if (root / stage_path).exists():
        from backend.research.architecture_factory.g5a_stage_admission_v1 import require_development
        stage = read(stage_path, root)
        if stage.get("receipt_sha256") != alpha.sha({k:v for k,v in stage.items() if k != "receipt_sha256"}):
            raise RuntimeError("STAGE_ADMISSION_RECEIPT_DRIFT")
        development = require_development(stage, root)
        paths.append(stage_path)
    for row in sources:
        row["G5A_DEVELOPMENT_READY"] = bool(development and row["source"] in development["allowed_sources"])
        row["G5B_FRESH_READY"] = row["decision"] == "PASS" and row["fresh"] is True
        row["PRODUCTION_GRADE_READY"] = False
    return seal({"schema_version": "zel.g5a.source_capability_registry.v1", "as_of_ms": as_of_ms,
                 "native_source_ref": native_ref, "sources": sources, "native_observations": observations,
                 "source_files_sha256": {p: file_sha(root / p) for p in paths},
                 "candidate_generation_sources": [s["source"] for s in sources if s["decision"] == "PASS"],
                 "verified_round_trip_cost_bps": development["reference_round_trip_cost_bps"] if development else None,
                 "candidate_cost_binding": "BOUND" if development else "NOT_BOUND",
                 "development_binding": development, "development_generation_sources": development["allowed_sources"] if development else [],
                 "development_cost_model": "RESEARCH_ONLY_DEVELOPMENT_COST" if development else "NOT_BOUND",
                 "production_cost_lineage": "TRADE_TIME_PROVENANCE_REQUIRED; NO_DEVELOPMENT_CREDIT",
                 "ohlcv_volume_is_directional_flow": False, "wick_is_liquidation": False,
                 "snapshot_book_is_historical_book": False, **AUTH})


def generation_sources(registry, *, now_ms, root=ROOT, stage="G5B_FRESH"):
    if registry.get("receipt_sha256") != alpha.sha({k: v for k, v in registry.items() if k != "receipt_sha256"}):
        raise RuntimeError("SOURCE_CAPABILITY_RECEIPT_DRIFT")
    if stage == "G5A_DEVELOPMENT":
        from backend.research.architecture_factory.g5a_stage_admission_v1 import require_development
        dev = require_development({"development": registry.get("development_binding")}, root)
        return dev["allowed_sources"]
    if stage != "G5B_FRESH":
        raise RuntimeError("UNKNOWN_SOURCE_ADMISSION_STAGE")
    hashes = registry.get("source_files_sha256") or {}
    if not hashes or any(not (root / p).is_file() or file_sha(root / p) != sha for p, sha in hashes.items()):
        raise RuntimeError("SOURCE_CAPABILITY_INPUT_PARITY")
    allowed = []
    for row in registry.get("sources", []):
        if row.get("decision") != "PASS" or not all(row.get(k) is True for k in ("available", "point_in_time", "validated", "fresh")):
            continue
        limit = row.get("stale_limit_ms")
        last = (row.get("historical_depth") or {}).get("last_close_ms")
        if limit and last and 0 <= now_ms - last < limit:
            allowed.append(row["source"])
    if not allowed:
        raise RuntimeError("SOURCE_CAPABILITY_NOT_READY_BEFORE_GENERATION")
    return allowed


def terminalize(registry, root=ROOT):
    factory = read("backend/research/architecture_factory/g5a_alpha_factory_latest.json", root)
    original = factory["next_experiment_candidate"]
    frozen = read("backend/research/architecture_factory/g5a_ma001_alpha_proof_bundle_v1.json", root)
    if original.get("candidate_id") != "MA001" or preflight.build_partial_bundle(original)["candidate"] != frozen["candidate"]:
        raise RuntimeError("MA001_ORIGINAL_IDENTITY_DRIFT")
    diagnostic = [r for r in factory["candidate_guard_diagnostics"] if r["candidate_id"] != "MA001"]
    outcomes = []
    for raw in [original] + diagnostic:
        bundle = frozen if raw["candidate_id"] == "MA001" else preflight.build_partial_bundle(raw)
        proof = alpha.evaluate_bundle(bundle)
        if proof["p0_p6_passed"]:
            raise RuntimeError("EXISTING_GAP_PACKET_UNEXPECTED_PASS")
        blocked = [s for s in raw.get("required_sources", []) if s not in registry["candidate_generation_sources"]]
        decision = "G5A_SOURCE_BLOCKED" if raw["candidate_id"] == "MA001" or blocked else "G5A_ALPHA_PROOF_REJECT"
        reason = "MIXED_OR_UNRESOLVED_SOURCE_SEMANTICS" if raw["candidate_id"] == "MA001" else ("SOURCE_CAPABILITY_NOT_ADMITTED:" + ",".join(blocked) if blocked else "FULL_CANDIDATE_FEATURE_AND_COST_IMPLEMENTATION_NOT_PRESERVED")
        outcomes.append({"candidate_id": raw["candidate_id"], "family": raw["architecture_family"],
                         "source_candidate_sha": raw.get("candidate_sha256"), "audit_projection_sha": alpha.sha(raw),
                         "candidate_identity_complete": raw["candidate_id"] == "MA001", "decision": decision,
                         "first_failed_gate": "P6", "failure_reason": reason, "failure_signature": alpha.sha({"candidate": raw, "reason": reason}),
                         "alpha_proof": proof, "economic_state": "NOT_RUN_ALPHA_PROOF_BLOCKED",
                         "base_net": None, "expectancy": None, "PF": None, "cost2x": None, "purged_OOS": None,
                         "deterministic_replay_authorized": False, "paid_calls": 0})
    return seal({"schema_version": "zel.g5a.source_terminal_dispositions.v1", "registry_receipt_sha": registry["receipt_sha256"],
                 "factory_source_sha": file_sha(root / "backend/research/architecture_factory/g5a_alpha_factory_latest.json"),
                 "original_state": "G5A_SOURCE_BLOCKED_REJECT", "semantic_classification": "MIXED_OR_UNRESOLVED",
                 "classification_basis": {k: original.get(k) for k in ("mechanism", "payer", "entry_event", "invalidation", "evidence_ids")},
                 "cited_evidence_audit": frozen["primary_evidence"], "feature_implementation": "NO_MA001_EXECUTABLE_FEATURE_BINDING",
                 "mutated_in_place": False, "successor_candidate": None, "successor_sha": None,
                 "route_change_candidate": "cand1", "candidates": outcomes,
                 "generation_state": "BLOCKED_SOURCE_OR_IMPLEMENTATION_EVIDENCE",
                 "minimum_one_economic_pass": False, "family_budget_exhausted": False,
                 "max_distinct_candidates_per_family": 3, "dedup_cosine_threshold": 0.85,
                 "fast_kill_order": ["P6", "P1", "P2", "P0", "CHEAP_P3_P4", "P5", "FULL_ECONOMICS"],
                 "same_failure_signature_paid_recall": False, "paid_calls": 0, "estimated_cost_usd": 0,
                 "new_boundary_created": False, "next": "BIND_EXECUTABLE_SOURCE_READY_DISTINCT_CANDIDATE_AND_COST_DATA_BEFORE_RESEARCH",
                 **AUTH})


def main():
    p = argparse.ArgumentParser(); p.add_argument("--native-ref", required=True); p.add_argument("--as-of-ms", type=int)
    p.add_argument("--out-dir", type=Path, default=DIR); a = p.parse_args()
    native = subprocess.check_output(["git", "rev-parse", a.native_ref], cwd=ROOT, text=True).strip()
    registry = inventory(native_ref=native, as_of_ms=a.as_of_ms or time.time_ns() // 1_000_000)
    terminal = terminalize(registry); a.out_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [(REGISTRY.name, registry), (TERMINAL.name, terminal)]:
        (a.out_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"source_registry_sha": registry["receipt_sha256"], "MA001": terminal["original_state"], "generation_state": terminal["generation_state"], "paid_calls": 0}))


if __name__ == "__main__":
    main()
