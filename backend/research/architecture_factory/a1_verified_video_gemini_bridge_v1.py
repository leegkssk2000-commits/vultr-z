#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_external_research_observer_v1 import call_gemini_video, video_prompt

REGISTRY = Path("backend/research/zel_manual_video_registry_v1.json")
OBSERVER_POLICY = Path("config/zel_production_external_research_observer_v1.json")
DEFAULT_EXISTING = Path("backend/research/architecture_factory/a1_youtube_evidence_latest.json")
PREFERRED_VIEW_FLOOR = 100_000
FALLBACK_VIEW_FLOOR = 30_000
MAX_VIDEO_REVIEWS = 2


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return row if isinstance(row, dict) else {}


def _canonical(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(v: Any) -> str:
    raw = v if isinstance(v, str) else _canonical(v)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _video_id(url: str) -> str:
    if "youtu.be/" in url:
        return url.split("youtu.be/", 1)[1].split("?", 1)[0].strip()
    if "v=" in url:
        return url.split("v=", 1)[1].split("&", 1)[0].strip()
    return _sha(url)[:12]


def _ranked_verified(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    verified_at = str(registry.get("verified_at") or "")
    rows: list[dict[str, Any]] = []
    for raw in registry.get("sources") or []:
        if not isinstance(raw, Mapping):
            continue
        url = str(raw.get("url") or "").strip()
        views = int(raw.get("observed_views") or 0)
        if not url.startswith("https://") or views < FALLBACK_VIEW_FLOOR:
            continue
        rows.append({
            "url": url,
            "video_id": _video_id(url),
            "title": str(raw.get("title") or "")[:500],
            "channel": str(raw.get("channel") or "")[:300],
            "observed_views": views,
            "topics": [str(x)[:160] for x in (raw.get("topics") or [])][:12],
            "view_count_verified": True,
            "view_count_verified_at": verified_at,
        })
    rows.sort(key=lambda x: (int(x["observed_views"]) >= PREFERRED_VIEW_FLOOR, int(x["observed_views"])), reverse=True)
    return rows


def _convert(video: Mapping[str, Any], model: str, raw: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    status = str(raw.get("status") or "").upper()
    mechanisms = [dict(x) for x in (raw.get("reproducible_mechanisms") or []) if isinstance(x, Mapping)]
    accepted = status == "USE" and bool(mechanisms)
    creator_claims = [str(x) for x in (raw.get("creator_claims") or []) if str(x).strip()][:6]
    lessons = [str(x) for x in (raw.get("architecture_lessons") or []) if str(x).strip()][:6]
    failures = [str(x) for x in (raw.get("failure_modes") or []) if str(x).strip()][:8]
    marketing = [str(x) for x in (raw.get("marketing_or_unverified") or []) if str(x).strip()][:8]
    mechanism_text = "; ".join(str(x.get("mechanism") or "").strip() for x in mechanisms if str(x.get("mechanism") or "").strip())
    local_tests = [str(x.get("local_test_needed") or "").strip() for x in mechanisms if str(x.get("local_test_needed") or "").strip()]
    limits = [str(x.get("limitations") or "").strip() for x in mechanisms if str(x.get("limitations") or "").strip()]
    response_sha = _sha(raw)
    review = {
        "video_id": video.get("video_id"),
        "reviewed_at_utc": _now(),
        "accepted": accepted,
        "reason": "DIRECT_GEMINI_PUBLIC_YOUTUBE_ANALYSIS" if accepted else "DIRECT_GEMINI_REJECTED_SOURCE",
        "view_count_snapshot": int(video.get("observed_views") or 0),
        "view_count_verified_at": video.get("view_count_verified_at"),
        "gemini_model": model,
        "gemini_response_sha": response_sha,
        "status": status,
    }
    if not accepted:
        return None, review
    source = {
        "id": f"YT:{video.get('video_id')}",
        "tier": "high_view_technical_youtube",
        "source_type": "YouTube",
        "title": str(video.get("title") or ""),
        "identifier": f"YouTube:{video.get('video_id')}",
        "url": str(video.get("url") or ""),
        "channel": str(video.get("channel") or ""),
        "upload_date": "",
        "view_count_snapshot": int(video.get("observed_views") or 0),
        "view_snapshot_at_utc": str(video.get("view_count_verified_at") or ""),
        "view_floor_class": "PREFERRED_100K" if int(video.get("observed_views") or 0) >= PREFERRED_VIEW_FLOOR else "FALLBACK_30K",
        "view_snapshot_verified": True,
        "claim": "; ".join(creator_claims + lessons)[:1800],
        "mechanism": mechanism_text[:1800],
        "entry_time_observables": local_tests[:12],
        "applicable_families": list(video.get("topics") or [])[:12],
        "reproducibility_notes": "; ".join(local_tests)[:1800],
        "limitations": ("; ".join(limits + marketing) + "; High-view YouTube material is hypothesis-only and never proves alpha or profitability.")[:2200],
        "red_flags": (failures + marketing)[:12],
        "transcript_sha256": None,
        "direct_video_analysis": True,
        "gemini_lineage": {
            "model": model,
            "response_sha": response_sha,
            "input_sha": _sha({"url": video.get("url"), "view_count": video.get("observed_views"), "verified_at": video.get("view_count_verified_at")}),
        },
        "accepted_for_hypothesis_only": True,
        "selection_authority": False,
        "promotion_authority": False,
    }
    return source, review


def run(output: Path, existing_path: Path = DEFAULT_EXISTING) -> dict[str, Any]:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    registry = _read(REGISTRY)
    policy = _read(OBSERVER_POLICY)
    existing = _read(existing_path)
    existing_sources = [dict(x) for x in (existing.get("sources") or []) if isinstance(x, Mapping)]
    existing_reviews = [dict(x) for x in (existing.get("reviews") or []) if isinstance(x, Mapping)]
    source_by_id = {str(x.get("id") or ""): x for x in existing_sources if str(x.get("id") or "")}
    review_by_video = {str(x.get("video_id") or ""): x for x in existing_reviews if str(x.get("video_id") or "")}
    candidates = _ranked_verified(registry)
    models = [str(x) for x in (policy.get("models") or []) if str(x).strip()]
    blockers: list[str] = []
    reviewed_now = 0

    if not key:
        blockers.append("GEMINI_API_KEY_MISSING")
    elif not models:
        blockers.append("OBSERVER_MODEL_LIST_MISSING")
    else:
        context = {"current_progress": {}, "parallel_next_hypotheses": {"families": []}}
        for video in candidates:
            if reviewed_now >= MAX_VIDEO_REVIEWS:
                break
            source_id = f"YT:{video['video_id']}"
            if source_id in source_by_id:
                continue
            reviewed_now += 1
            prompt = video_prompt(video, context)
            try:
                model, raw = call_gemini_video(key, models, prompt, str(video["url"]), int(policy.get("video_max_output_tokens") or 4096))
                source, review = _convert(video, model, raw)
                review_by_video[str(video["video_id"])] = review
                if source is not None:
                    source_by_id[source_id] = source
            except Exception as exc:
                blockers.append(f"DIRECT_VIDEO_FAILED:{video['video_id']}:{type(exc).__name__}:{str(exc)[:400]}")
                review_by_video[str(video["video_id"])] = {
                    "video_id": video["video_id"],
                    "reviewed_at_utc": _now(),
                    "accepted": False,
                    "reason": "DIRECT_GEMINI_VIDEO_CALL_FAILED",
                    "view_count_snapshot": int(video["observed_views"]),
                    "error": f"{type(exc).__name__}:{str(exc)[:500]}",
                }

    sources = sorted(source_by_id.values(), key=lambda x: int(x.get("view_count_snapshot") or 0), reverse=True)[:8]
    reviews = sorted(review_by_video.values(), key=lambda x: str(x.get("reviewed_at_utc") or ""), reverse=True)[:80]
    state = "PASS_YOUTUBE_EVIDENCE_READY" if sources else ("HOLD_YOUTUBE_DIRECT_GEMINI_BLOCKED" if blockers else "HOLD_YOUTUBE_NO_VERIFIED_TECHNICAL_ITEM")
    result: dict[str, Any] = {
        "schema_version": "zel.a1_youtube_evidence_sweep.v1",
        "checked_at_utc": _now(),
        "state": state,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "heavy_slot_consumed": False,
        "gen1_boundary_mutated": False,
        "sealed_holdout_outcomes_exposed": False,
        "factory_blocking": False,
        "policy": {
            "youtube_requires_verified_view_snapshot_before_acceptance": True,
            "preferred_view_floor": PREFERRED_VIEW_FLOOR,
            "fallback_view_floor": FALLBACK_VIEW_FLOOR,
            "technical_transcript_required": False,
            "direct_gemini_public_video_allowed": True,
            "gemini_summary_required": True,
            "hypothesis_only": True,
            "promotion_from_video_forbidden": True,
        },
        "queries": [],
        "discovery": {
            "mode": "VERIFIED_MANUAL_REGISTRY_DIRECT_GEMINI",
            "eligible_unique": len(candidates),
            "reviewed_now": reviewed_now,
            "search_error_count": 0,
            "search_errors": [],
            "blockers": blockers[:8],
        },
        "sources": sources,
        "reviews": reviews,
        "accepted_count": len(sources),
        "preferred_100k_count": sum(1 for x in sources if int(x.get("view_count_snapshot") or 0) >= PREFERRED_VIEW_FLOOR),
        "fallback_30k_count": sum(1 for x in sources if FALLBACK_VIEW_FLOOR <= int(x.get("view_count_snapshot") or 0) < PREFERRED_VIEW_FLOOR),
        "new_review_count": reviewed_now,
    }
    result["receipt_sha256"] = _sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    rows = _ranked_verified({"verified_at": "2026-01-01T00:00:00Z", "sources": [
        {"url": "https://www.youtube.com/watch?v=a", "title": "a", "channel": "c", "observed_views": 40000, "topics": []},
        {"url": "https://www.youtube.com/watch?v=b", "title": "b", "channel": "c", "observed_views": 200000, "topics": []},
        {"url": "https://www.youtube.com/watch?v=c", "title": "c", "channel": "c", "observed_views": 20000, "topics": []},
    ]})
    assert [x["video_id"] for x in rows] == ["b", "a"]
    raw = {"status": "USE", "creator_claims": ["claim"], "reproducible_mechanisms": [{"mechanism": "m", "local_test_needed": "t", "limitations": "l"}], "failure_modes": [], "architecture_lessons": ["lesson"], "marketing_or_unverified": []}
    source, review = _convert(rows[0], "model-x", raw)
    assert source is not None and source["accepted_for_hypothesis_only"] is True
    assert review["accepted"] is True
    print("PASS_A1_VERIFIED_VIDEO_GEMINI_BRIDGE_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_youtube_evidence_direct_v1.json"))
    ap.add_argument("--existing", type=Path, default=DEFAULT_EXISTING)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output, args.existing)
    print(json.dumps({"state": result["state"], "accepted": result["accepted_count"], "preferred100k": result["preferred_100k_count"], "fallback30k": result["fallback_30k_count"], "reviewed_now": result["discovery"]["reviewed_now"], "blockers": result["discovery"]["blockers"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
