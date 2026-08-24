#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import backend.research.architecture_factory.a1_strategy_architecture_factory_v1 as factory_v1
import backend.research.architecture_factory.a1_strategy_architecture_factory_v3 as factory_v3
import backend.research.architecture_factory.a1_strategy_architecture_factory_v4 as factory_v4
from backend.research.architecture_factory.a1_strategy_architecture_factory_v2 import sha

BASE_EVIDENCE = factory_v4.BASE_EVIDENCE
YOUTUBE_EVIDENCE_DEFAULT = factory_v4.YOUTUBE_EVIDENCE_DEFAULT
DIVERSITY_DEFAULT = Path("backend/research/architecture_factory/a1_youtube_diversity_latest.json")
MIN_SOURCES_PER_BUCKET = 2
MIN_CHANNELS_PER_BUCKET = 2


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _youtube_path() -> Path:
    raw = os.environ.get("A1_YOUTUBE_EVIDENCE_PATH", "").strip()
    return Path(raw) if raw else YOUTUBE_EVIDENCE_DEFAULT


def _diversity_path() -> Path:
    raw = os.environ.get("A1_YOUTUBE_DIVERSITY_PATH", "").strip()
    return Path(raw) if raw else DIVERSITY_DEFAULT


def _generic_diversity_source(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    if raw.get("accepted_for_hypothesis_only") is not True or raw.get("direct_video_analysis") is not True:
        return None
    if raw.get("evidence_authority") != "HYPOTHESIS_ONLY_REQUIRES_LOCAL_REPLAY":
        return None
    bucket = str(raw.get("bucket") or "").strip()
    channel = str(raw.get("channel") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not bucket or not channel or not url.startswith("https://"):
        return None
    mechanisms = [dict(x) for x in (raw.get("reproducible_mechanisms") or []) if isinstance(x, Mapping) and str(x.get("mechanism") or "").strip() and str(x.get("local_test_needed") or "").strip()]
    if not mechanisms:
        return None
    claim_parts = [str(x).strip() for x in (raw.get("creator_claims") or []) if str(x).strip()][:3]
    mechanism_text = "; ".join(str(x.get("mechanism") or "") for x in mechanisms[:3])[:1800]
    local_tests = [str(x.get("local_test_needed") or "")[:500] for x in mechanisms[:6]]
    limitations = "; ".join(str(x.get("limitations") or "") for x in mechanisms[:4])[:1800]
    return {
        "id": str(raw.get("id") or ""),
        "tier": "youtube_diversity_quorum_hypothesis",
        "source_type": "YouTube",
        "title": str(raw.get("title") or "")[:500],
        "identifier": str(raw.get("id") or ""),
        "url": url,
        "channel": channel[:300],
        "bucket": bucket,
        "claim": ("; ".join(claim_parts) or mechanism_text)[:1800],
        "mechanism": mechanism_text,
        "entry_time_observables": local_tests,
        "applicable_families": [bucket],
        "reproducibility_notes": "; ".join(local_tests)[:1800],
        "limitations": (limitations + " YouTube diversity evidence is hypothesis-only and requires local deterministic replay.")[:2200],
        "red_flags": [str(x)[:500] for x in (raw.get("marketing_or_unverified") or [])][:12],
        "direct_video_analysis": True,
        "view_snapshot_verified": bool(raw.get("view_count_verified")),
        "view_count_snapshot": raw.get("observed_views") if bool(raw.get("view_count_verified")) else None,
        "claimed_view_count_unverified": raw.get("claimed_view_count_unverified") if not bool(raw.get("view_count_verified")) else None,
        "accepted_for_hypothesis_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "evidence_authority": "HYPOTHESIS_ONLY_REQUIRES_LOCAL_REPLAY",
    }


def merge_diversity(base: Mapping[str, Any], diversity: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    merged = dict(base)
    existing = [dict(x) for x in (base.get("sources") or []) if isinstance(x, Mapping)]
    existing_urls = {str(x.get("url") or "") for x in existing if str(x.get("url") or "")}

    candidates: list[dict[str, Any]] = []
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in diversity.get("factory_sources") or []:
        if not isinstance(raw, Mapping):
            continue
        row = _generic_diversity_source(raw)
        if row is None or row["url"] in existing_urls:
            continue
        by_bucket[str(row["bucket"])].append(row)

    qualified_buckets: list[str] = []
    rejected_buckets: list[str] = []
    for bucket, rows in sorted(by_bucket.items()):
        channels = {str(x.get("channel") or "").strip().lower() for x in rows if str(x.get("channel") or "").strip()}
        if len(rows) >= MIN_SOURCES_PER_BUCKET and len(channels) >= MIN_CHANNELS_PER_BUCKET:
            qualified_buckets.append(bucket)
            candidates.extend(rows)
        else:
            rejected_buckets.append(bucket)

    seen = {str(x.get("id") or "") for x in existing}
    sources = list(existing)
    for row in candidates:
        source_id = str(row.get("id") or "")
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        sources.append(row)
    merged["sources"] = sources

    coverage = dict(base.get("coverage") or {})
    coverage["youtube_diversity_quorum_sources"] = len(candidates)
    coverage["youtube_diversity_qualified_buckets"] = len(qualified_buckets)
    merged["coverage"] = coverage
    policy = dict(base.get("policy") or {})
    policy["youtube_diversity_single_video_authority_forbidden"] = True
    policy["youtube_diversity_min_sources_per_bucket"] = MIN_SOURCES_PER_BUCKET
    policy["youtube_diversity_min_channels_per_bucket"] = MIN_CHANNELS_PER_BUCKET
    policy["youtube_diversity_local_replay_required"] = True
    merged["policy"] = policy
    merged["youtube_diversity_state"] = str(diversity.get("state") or "MISSING")

    summary = {
        "state": str(diversity.get("state") or "MISSING"),
        "factory_source_count": len(candidates),
        "qualified_bucket_count": len(qualified_buckets),
        "qualified_buckets": qualified_buckets,
        "rejected_buckets": rejected_buckets,
        "hypothesis_only": True,
        "factory_blocking": False,
        "view_count_required_for_hypothesis": False,
        "unverified_view_count_treated_as_fact": False,
        "single_video_authority_forbidden": True,
        "local_deterministic_replay_required": True,
        "can_promote_candidate": False,
    }
    return merged, summary


def run(output: Path) -> dict[str, Any]:
    base = _read(BASE_EVIDENCE)
    verified = _read(_youtube_path())
    diversity = _read(_diversity_path())
    merged, verified_summary = factory_v4.merge_evidence(base, verified)
    merged, diversity_summary = merge_diversity(merged, diversity)

    ledger = factory_v1.read_json(factory_v1.LEDGER)
    terminal_targets = factory_v4._terminal_only_targets(ledger, limit=25)
    done_count = int(ledger.get("done_count") or 0)

    with tempfile.TemporaryDirectory(prefix="a1-factory-v5-evidence-") as td:
        merged_path = Path(td) / "merged_evidence.json"
        merged_path.write_text(json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        old_v1_evidence = factory_v1.EVIDENCE
        old_v3_evidence = factory_v3.EVIDENCE
        old_v1_targets = factory_v1.target_rows
        old_v3_targets = factory_v3.target_rows
        try:
            factory_v1.EVIDENCE = merged_path
            factory_v3.EVIDENCE = merged_path
            factory_v1.target_rows = factory_v4._terminal_only_targets
            factory_v3.target_rows = factory_v4._terminal_only_targets
            inner_path = Path(td) / "v3.json"
            result = factory_v3.run(inner_path)
        finally:
            factory_v1.EVIDENCE = old_v1_evidence
            factory_v3.EVIDENCE = old_v3_evidence
            factory_v1.target_rows = old_v1_targets
            factory_v3.target_rows = old_v3_targets

    result = dict(result)
    result["schema_version"] = "zel.a1_strategy_architecture_factory.v5"
    result["youtube_evidence"] = verified_summary
    result["youtube_diversity_evidence"] = diversity_summary
    result["external_evidence_count"] = len(merged.get("sources") or [])
    result["youtube_evidence_factory_blocking"] = False
    result["youtube_can_promote_candidate"] = False
    result["youtube_diversity_can_promote_candidate"] = False
    result["youtube_diversity_single_video_authority_forbidden"] = True
    result["gen2_prep_failure_distribution"] = {
        "generation": int(ledger.get("generation") or 0),
        "done_count": done_count,
        "terminal_count_used": len(terminal_targets),
        "terminal_strategy_ids": [str(x.get("strategy_id")) for x in terminal_targets],
        "unfinished_outcomes_used": False,
        "all_terminal_outcomes_used": len(terminal_targets) == done_count,
        "purpose": "GEN2_PREP_ONLY",
    }
    result["prep_only"] = done_count < 25
    result["fresh_prospective_boundary_created"] = False
    result["heavy_gen2_launch_started"] = False
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = sha(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    base = {"sources": [{"id": "F1", "url": "https://example.com/a", "claim": "base"}], "coverage": {}, "policy": {}}
    diversity = {
        "state": "PASS_YOUTUBE_DIVERSITY_FACTORY_READY",
        "factory_sources": [
            {"id": "YTDIV:1", "bucket": "trend", "url": "https://www.youtube.com/watch?v=1", "channel": "C1", "creator_claims": ["c"], "reproducible_mechanisms": [{"mechanism": "m1", "local_test_needed": "t1", "architecture_layer": "context", "limitations": "l"}], "direct_video_analysis": True, "accepted_for_hypothesis_only": True, "evidence_authority": "HYPOTHESIS_ONLY_REQUIRES_LOCAL_REPLAY", "view_count_verified": False},
            {"id": "YTDIV:2", "bucket": "trend", "url": "https://www.youtube.com/watch?v=2", "channel": "C2", "creator_claims": ["c"], "reproducible_mechanisms": [{"mechanism": "m2", "local_test_needed": "t2", "architecture_layer": "entry", "limitations": "l"}], "direct_video_analysis": True, "accepted_for_hypothesis_only": True, "evidence_authority": "HYPOTHESIS_ONLY_REQUIRES_LOCAL_REPLAY", "view_count_verified": True, "observed_views": 120000},
            {"id": "YTDIV:3", "bucket": "breakout", "url": "https://www.youtube.com/watch?v=3", "channel": "C3", "creator_claims": ["c"], "reproducible_mechanisms": [{"mechanism": "m3", "local_test_needed": "t3", "architecture_layer": "entry", "limitations": "l"}], "direct_video_analysis": True, "accepted_for_hypothesis_only": True, "evidence_authority": "HYPOTHESIS_ONLY_REQUIRES_LOCAL_REPLAY", "view_count_verified": False},
        ],
    }
    merged, summary = merge_diversity(base, diversity)
    ids = [x["id"] for x in merged["sources"]]
    assert ids == ["F1", "YTDIV:1", "YTDIV:2"]
    assert summary["qualified_buckets"] == ["trend"] and summary["factory_source_count"] == 2
    assert summary["can_promote_candidate"] is False and summary["unverified_view_count_treated_as_fact"] is False
    print("PASS_A1_STRATEGY_ARCHITECTURE_FACTORY_V5_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_strategy_architecture_factory_v5.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output)
    print(json.dumps({
        "state": result.get("state"),
        "generated_after_dedup": result.get("generated_after_dedup"),
        "alpha_proof_ready_count": result.get("alpha_proof_ready_count"),
        "youtube": result.get("youtube_evidence"),
        "youtube_diversity": result.get("youtube_diversity_evidence"),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
