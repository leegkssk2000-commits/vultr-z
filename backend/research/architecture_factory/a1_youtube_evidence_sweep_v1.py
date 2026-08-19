#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.research.architecture_factory.gemini_provider_v1 import _call, _extract_json

SCHEMA_VERSION = "zel.a1_youtube_evidence_sweep.v1"
PREFERRED_VIEW_FLOOR = 100_000
FALLBACK_VIEW_FLOOR = 30_000
DEFAULT_SEARCH_LIMIT = 4
DEFAULT_MAX_GEMINI_REVIEWS = 3
DEFAULT_MAX_ACCEPTED = 8
REVIEW_TTL_DAYS = 14
SNAPSHOT_REFRESH_DAYS = 7

DEFAULT_QUERIES = [
    "bitcoin futures order flow trading strategy",
    "crypto funding open interest basis trading strategy",
    "bitcoin breakout momentum trading strategy",
    "bitcoin mean reversion liquidity sweep trading strategy",
    "professional crypto trader risk management strategy",
]

VIDEO_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "accept": {"type": "BOOLEAN"},
        "technical_relevance": {"type": "STRING"},
        "claim": {"type": "STRING"},
        "mechanism": {"type": "STRING"},
        "entry_time_observables": {"type": "ARRAY", "items": {"type": "STRING"}},
        "applicable_families": {"type": "ARRAY", "items": {"type": "STRING"}},
        "reproducibility_notes": {"type": "STRING"},
        "limitations": {"type": "STRING"},
        "red_flags": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": [
        "accept",
        "technical_relevance",
        "claim",
        "mechanism",
        "entry_time_observables",
        "applicable_families",
        "reproducibility_notes",
        "limitations",
        "red_flags",
    ],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(v: Any) -> str:
    raw = v if isinstance(v, str) else _canonical(v)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_error(text: str) -> str:
    text = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", str(text or ""))
    return " ".join(text.strip().split())[-900:]


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _age_days(value: Any) -> float | None:
    dt = _parse_dt(value)
    if dt is None:
        return None
    return max(0.0, (_now() - dt).total_seconds() / 86400.0)


def _queries() -> list[str]:
    raw = os.environ.get("YOUTUBE_EVIDENCE_QUERIES_JSON", "").strip()
    if raw:
        try:
            rows = json.loads(raw)
            if isinstance(rows, list):
                out = [str(x).strip() for x in rows if str(x).strip()]
                if out:
                    return out[:12]
        except json.JSONDecodeError:
            pass
    return list(DEFAULT_QUERIES)


def _run_command(args: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        return 124, str(exc.stdout or ""), str(exc.stderr or "") + " timeout"


def _video_url(row: Mapping[str, Any]) -> str:
    url = str(row.get("webpage_url") or row.get("url") or "").strip()
    vid = str(row.get("id") or "").strip()
    if url.startswith("http"):
        return url
    return f"https://www.youtube.com/watch?v={vid}" if vid else ""


def _search(query: str, limit: int) -> tuple[list[dict[str, Any]], str | None]:
    rc, stdout, stderr = _run_command(
        [
            "yt-dlp",
            "--dump-json",
            "--skip-download",
            "--no-warnings",
            "--ignore-errors",
            "--extractor-retries",
            "2",
            f"ytsearch{int(limit)}:{query}",
        ],
        timeout=150,
    )
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("id"):
            rows.append(row)
    error = None if rows else _safe_error(stderr or f"yt-dlp rc={rc}")
    return rows, error


def _metadata(row: Mapping[str, Any], query: str) -> dict[str, Any]:
    return {
        "video_id": str(row.get("id") or ""),
        "url": _video_url(row),
        "title": str(row.get("title") or "")[:500],
        "channel": str(row.get("channel") or row.get("uploader") or "")[:300],
        "channel_id": str(row.get("channel_id") or row.get("uploader_id") or "")[:200],
        "view_count": int(row.get("view_count") or 0),
        "duration_sec": int(row.get("duration") or 0),
        "upload_date": str(row.get("upload_date") or ""),
        "live_status": str(row.get("live_status") or ""),
        "query": query,
        "description": str(row.get("description") or "")[:4000],
    }


def _eligible(meta: Mapping[str, Any]) -> bool:
    if int(meta.get("view_count") or 0) < FALLBACK_VIEW_FLOOR:
        return False
    if str(meta.get("live_status") or "") in {"is_live", "is_upcoming"}:
        return False
    duration = int(meta.get("duration_sec") or 0)
    if duration and (duration < 180 or duration > 14_400):
        return False
    return bool(meta.get("video_id") and meta.get("url"))


def _strip_vtt(text: str) -> str:
    out: list[str] = []
    prev = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"&(?:nbsp|amp|lt|gt);", " ", line)
        line = " ".join(line.split())
        if not line or line == prev or re.fullmatch(r"\d+", line):
            continue
        out.append(line)
        prev = line
    return "\n".join(out).strip()


def _extract_transcript(meta: Mapping[str, Any], root: Path) -> tuple[str, str | None]:
    video_id = str(meta["video_id"])
    outtmpl = str(root / "%(id)s.%(ext)s")
    rc, _, stderr = _run_command(
        [
            "yt-dlp",
            "--skip-download",
            "--no-warnings",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,ko.*,de.*",
            "--sub-format",
            "vtt",
            "--extractor-retries",
            "2",
            "--output",
            outtmpl,
            str(meta["url"]),
        ],
        timeout=180,
    )
    texts: list[str] = []
    for path in sorted(root.glob(f"{video_id}*.vtt")):
        try:
            cleaned = _strip_vtt(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if cleaned:
            texts.append(cleaned)
    transcript = max(texts, key=len) if texts else ""
    if len(transcript) < 800:
        return "", _safe_error(stderr or f"subtitle_missing rc={rc}")
    return transcript, None


def _clip_transcript(text: str, max_chars: int = 48_000) -> str:
    if len(text) <= max_chars:
        return text
    chunk = max_chars // 3
    middle = max(0, len(text) // 2 - chunk // 2)
    return text[:chunk] + "\n[...MIDDLE SAMPLE...]\n" + text[middle:middle + chunk] + "\n[...END SAMPLE...]\n" + text[-chunk:]


def _gemini_review(meta: Mapping[str, Any], transcript: str) -> tuple[dict[str, Any], dict[str, str]]:
    prompt = (
        "Review this high-view YouTube trading video as a HYPOTHESIS SOURCE ONLY for a crypto systematic-strategy research pipeline. "
        "Reject marketing-only, discretionary-only, unverifiable PnL claims, indicator stacking without mechanism, or content with no reproducible entry-time observable. "
        "If technically useful, extract one concise falsifiable mechanism, entry-time observables, applicable strategy families, reproducibility notes and limitations. "
        "Do not claim profitability, do not adopt numeric parameters as truth, and do not use or infer sealed holdout outcomes.\n"
        f"METADATA={_canonical({k: meta.get(k) for k in ('video_id','title','channel','view_count','upload_date','duration_sec','query')})}\n"
        "TRANSCRIPT=\n" + _clip_transcript(transcript)
    )
    model, text, lineage = _call(
        prompt,
        system_instruction="You are a skeptical multilingual quantitative-trading video reviewer. Return JSON only.",
        max_output_tokens=2200,
        temperature=0.0,
        response_schema=VIDEO_REVIEW_SCHEMA,
    )
    value = _extract_json(text)
    value["accept"] = bool(value.get("accept"))
    lineage = {"model": model, **lineage}
    return value, lineage


def _review_recent(review: Mapping[str, Any]) -> bool:
    age = _age_days(review.get("reviewed_at_utc"))
    return age is not None and age < REVIEW_TTL_DAYS


def _source_recent(source: Mapping[str, Any]) -> bool:
    age = _age_days(source.get("view_snapshot_at_utc"))
    return age is not None and age < SNAPSHOT_REFRESH_DAYS


def _source_from_review(meta: Mapping[str, Any], review: Mapping[str, Any], lineage: Mapping[str, str], transcript: str) -> dict[str, Any]:
    video_id = str(meta["video_id"])
    views = int(meta.get("view_count") or 0)
    return {
        "id": f"YT:{video_id}",
        "tier": "high_view_technical_youtube",
        "source_type": "YouTube",
        "title": str(meta.get("title") or ""),
        "identifier": f"YouTube:{video_id}",
        "url": str(meta.get("url") or ""),
        "channel": str(meta.get("channel") or ""),
        "upload_date": str(meta.get("upload_date") or ""),
        "view_count_snapshot": views,
        "view_snapshot_at_utc": _iso(),
        "view_floor_class": "PREFERRED_100K" if views >= PREFERRED_VIEW_FLOOR else "FALLBACK_30K",
        "view_snapshot_verified": True,
        "claim": str(review.get("claim") or "")[:1800],
        "mechanism": str(review.get("mechanism") or "")[:1800],
        "entry_time_observables": [str(x)[:500] for x in (review.get("entry_time_observables") or [])][:12],
        "applicable_families": [str(x)[:160] for x in (review.get("applicable_families") or [])][:12],
        "reproducibility_notes": str(review.get("reproducibility_notes") or "")[:1800],
        "limitations": (str(review.get("limitations") or "") + " High-view YouTube material is hypothesis-only and never proves alpha or profitability.")[:2200],
        "red_flags": [str(x)[:500] for x in (review.get("red_flags") or [])][:12],
        "transcript_sha256": _sha(transcript),
        "gemini_lineage": dict(lineage),
        "accepted_for_hypothesis_only": True,
        "selection_authority": False,
        "promotion_authority": False,
    }


def run(output: Path, existing_path: Path | None = None) -> dict[str, Any]:
    existing = _read_json(existing_path)
    existing_sources = [dict(x) for x in (existing.get("sources") or []) if isinstance(x, Mapping)]
    existing_reviews = [dict(x) for x in (existing.get("reviews") or []) if isinstance(x, Mapping)]
    source_by_video = {str(x.get("identifier") or "").removeprefix("YouTube:"): x for x in existing_sources}
    review_by_video = {str(x.get("video_id") or ""): x for x in existing_reviews}

    discovered: dict[str, dict[str, Any]] = {}
    search_errors: list[str] = []
    for query in _queries():
        rows, error = _search(query, int(os.environ.get("YOUTUBE_SEARCH_LIMIT", DEFAULT_SEARCH_LIMIT)))
        if error:
            search_errors.append(f"{query}:{error}")
        for row in rows:
            meta = _metadata(row, query)
            if _eligible(meta):
                prev = discovered.get(str(meta["video_id"]))
                if prev is None or int(meta.get("view_count") or 0) > int(prev.get("view_count") or 0):
                    discovered[str(meta["video_id"])] = meta

    ranked = sorted(
        discovered.values(),
        key=lambda x: (int(x.get("view_count") or 0) >= PREFERRED_VIEW_FLOOR, int(x.get("view_count") or 0)),
        reverse=True,
    )
    max_reviews = int(os.environ.get("YOUTUBE_MAX_GEMINI_REVIEWS", DEFAULT_MAX_GEMINI_REVIEWS))
    reviewed_now = 0
    new_reviews: list[dict[str, Any]] = []
    accepted_by_video = {k: dict(v) for k, v in source_by_video.items() if k}
    review_cache = {k: dict(v) for k, v in review_by_video.items() if k}
    blockers: list[str] = []

    for meta in ranked:
        video_id = str(meta["video_id"])
        cached_source = accepted_by_video.get(video_id)
        if cached_source and _source_recent(cached_source):
            continue
        cached_review = review_cache.get(video_id)
        if cached_review and _review_recent(cached_review) and not bool(cached_review.get("accepted")):
            continue
        if reviewed_now >= max_reviews:
            break
        reviewed_now += 1
        with tempfile.TemporaryDirectory(prefix=f"a1-yt-{video_id}-") as td:
            transcript, transcript_error = _extract_transcript(meta, Path(td))
        if transcript_error:
            row = {
                "video_id": video_id,
                "reviewed_at_utc": _iso(),
                "accepted": False,
                "reason": "TRANSCRIPT_UNAVAILABLE",
                "view_count_snapshot": int(meta.get("view_count") or 0),
                "error": transcript_error,
            }
            review_cache[video_id] = row
            new_reviews.append(row)
            continue
        try:
            review, lineage = _gemini_review(meta, transcript)
        except Exception as exc:
            blockers.append(f"GEMINI_REVIEW_FAILED:{video_id}:{_safe_error(str(exc))}")
            row = {
                "video_id": video_id,
                "reviewed_at_utc": _iso(),
                "accepted": False,
                "reason": "GEMINI_REVIEW_FAILED",
                "view_count_snapshot": int(meta.get("view_count") or 0),
                "error": _safe_error(str(exc)),
            }
            review_cache[video_id] = row
            new_reviews.append(row)
            continue
        accepted = bool(review.get("accept"))
        row = {
            "video_id": video_id,
            "reviewed_at_utc": _iso(),
            "accepted": accepted,
            "reason": str(review.get("technical_relevance") or "")[:1400],
            "view_count_snapshot": int(meta.get("view_count") or 0),
            "transcript_sha256": _sha(transcript),
            "gemini_model": lineage.get("model", ""),
            "gemini_response_sha": lineage.get("response_sha", ""),
        }
        review_cache[video_id] = row
        new_reviews.append(row)
        if accepted:
            accepted_by_video[video_id] = _source_from_review(meta, review, lineage, transcript)

    sources = sorted(
        accepted_by_video.values(),
        key=lambda x: int(x.get("view_count_snapshot") or 0),
        reverse=True,
    )[: int(os.environ.get("YOUTUBE_MAX_ACCEPTED", DEFAULT_MAX_ACCEPTED))]
    reviews = sorted(review_cache.values(), key=lambda x: str(x.get("reviewed_at_utc") or ""), reverse=True)[:80]

    yt_dlp_missing = any("No such file or directory" in e or "yt-dlp" in e and "not found" in e.lower() for e in search_errors)
    if sources:
        state = "PASS_YOUTUBE_EVIDENCE_READY"
    elif yt_dlp_missing:
        state = "HOLD_YOUTUBE_TOOL_MISSING"
    elif search_errors and not discovered:
        state = "HOLD_YOUTUBE_DISCOVERY_BLOCKED"
    elif blockers:
        state = "HOLD_YOUTUBE_GEMINI_REVIEW_BLOCKED"
    else:
        state = "HOLD_YOUTUBE_NO_VERIFIED_TECHNICAL_ITEM"

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "checked_at_utc": _iso(),
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
            "technical_transcript_required": True,
            "gemini_summary_required": True,
            "hypothesis_only": True,
            "promotion_from_video_forbidden": True,
            "review_ttl_days": REVIEW_TTL_DAYS,
            "snapshot_refresh_days": SNAPSHOT_REFRESH_DAYS,
        },
        "queries": _queries(),
        "discovery": {
            "eligible_unique": len(ranked),
            "reviewed_now": reviewed_now,
            "search_error_count": len(search_errors),
            "search_errors": search_errors[:8],
            "blockers": blockers[:8],
        },
        "sources": sources,
        "reviews": reviews,
        "accepted_count": len(sources),
        "preferred_100k_count": sum(1 for x in sources if int(x.get("view_count_snapshot") or 0) >= PREFERRED_VIEW_FLOOR),
        "fallback_30k_count": sum(1 for x in sources if FALLBACK_VIEW_FLOOR <= int(x.get("view_count_snapshot") or 0) < PREFERRED_VIEW_FLOOR),
        "new_review_count": len(new_reviews),
    }
    result["receipt_sha256"] = _sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert _eligible({"video_id": "x", "url": "https://x", "view_count": 100_000, "duration_sec": 600, "live_status": "not_live"})
    assert not _eligible({"video_id": "x", "url": "https://x", "view_count": 29_999, "duration_sec": 600, "live_status": "not_live"})
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhello\n00:00:02.000 --> 00:00:03.000\nhello\nworld"
    assert _strip_vtt(vtt) == "hello\nworld"
    clipped = _clip_transcript("a" * 60_000, 9_000)
    assert len(clipped) < 10_000 and "MIDDLE SAMPLE" in clipped
    assert VIDEO_REVIEW_SCHEMA["required"][0] == "accept"
    print("PASS_A1_YOUTUBE_EVIDENCE_SWEEP_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_youtube_evidence_sweep_v1.json"))
    ap.add_argument("--existing", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output, args.existing)
    print(json.dumps({
        "state": result["state"],
        "accepted_count": result["accepted_count"],
        "preferred_100k_count": result["preferred_100k_count"],
        "fallback_30k_count": result["fallback_30k_count"],
        "eligible_unique": result["discovery"]["eligible_unique"],
        "reviewed_now": result["discovery"]["reviewed_now"],
        "factory_blocking": result["factory_blocking"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
