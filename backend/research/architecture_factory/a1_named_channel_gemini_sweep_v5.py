#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production import zel_production_external_research_observer_v1 as ext
from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v1 as base
from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v2 as v2
from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v3 as v3
from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v4 as v4

SCHEMA = "zel.a1.named_channel_gemini_sweep.v5"
TRANSCRIPT_MAX_CHARS = v4.TRANSCRIPT_MAX_CHARS


def _channel_matches_name(target: str, actual: str, aliases: Sequence[str] = ()) -> bool:
    a = base._norm(actual)
    if not a:
        return False
    for raw in [target, *aliases]:
        t = base._norm(raw)
        if t and (t == a or t in a or a in t):
            return True
    return False


def _oembed_verify(candidate: Mapping[str, Any]) -> dict[str, Any]:
    video_id = str(candidate.get("video_id") or "")
    if not v2._valid_id(video_id):
        raise RuntimeError("OEMBED_VIDEO_ID_INVALID")
    watch = f"https://www.youtube.com/watch?v={video_id}"
    endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": watch, "format": "json"})
    req = urllib.request.Request(endpoint, headers={"User-Agent": "Mozilla/5.0 ZELResearch/1.0"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in {400, 404}:
            raise RuntimeError(f"OEMBED_VIDEO_NOT_PUBLIC:{exc.code}") from exc
        raise RuntimeError(f"OEMBED_TRANSIENT_HTTP_{exc.code}") from exc
    actual = str(payload.get("author_name") or "").strip()
    target = str(candidate.get("target_channel") or "").strip()
    aliases = [str(x) for x in (candidate.get("target_aliases") or [])]
    return {
        "verified": True,
        "video_id": video_id,
        "url": watch,
        "title": str(payload.get("title") or "").strip(),
        "actual_channel": actual,
        "channel_identity_matches_target": _channel_matches_name(target, actual, aliases),
        "source": "youtube_oembed",
    }


def _vtt_to_text(raw: str) -> str:
    out: list[str] = []
    previous = ""
    for line in raw.splitlines():
        s = line.strip()
        if not s or s == "WEBVTT" or s.startswith(("Kind:", "Language:", "NOTE")) or "-->" in s:
            continue
        if re.fullmatch(r"\d+", s):
            continue
        s = re.sub(r"<[^>]+>", "", s)
        s = html.unescape(s)
        s = " ".join(s.split()).strip()
        if not s or s == previous:
            continue
        previous = s
        out.append(s)
    return " ".join(out).strip()


def _fetch_transcript_ytdlp(video_id: str) -> dict[str, Any]:
    if not v2._valid_id(video_id):
        raise RuntimeError("YTDLP_VIDEO_ID_INVALID")
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="zel_ytdlp_subs_") as td:
        template = str(Path(td) / "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,ko.*,de.*",
            "--sub-format",
            "vtt",
            "--socket-timeout",
            "20",
            "--retries",
            "1",
            "--quiet",
            "--no-warnings",
            "-o",
            template,
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
        files = sorted(Path(td).glob("*.vtt"), key=lambda p: p.stat().st_size, reverse=True)
        if proc.returncode != 0 and not files:
            err = " ".join((proc.stderr or proc.stdout or "").split())[:700]
            raise RuntimeError(f"YTDLP_SUBTITLE_FAILED:rc={proc.returncode}:{err}")
        text = ""
        chosen = ""
        for path in files:
            candidate = _vtt_to_text(path.read_text(encoding="utf-8", errors="replace"))
            if len(candidate) > len(text):
                text, chosen = candidate, path.name
        if not text:
            raise RuntimeError("YTDLP_SUBTITLE_EMPTY")
        return {
            "text": text[:TRANSCRIPT_MAX_CHARS],
            "language_code": chosen.split(".")[-2] if "." in chosen else "unknown",
            "is_generated": None,
            "char_count_total": len(text),
            "char_count_used": min(len(text), TRANSCRIPT_MAX_CHARS),
            "truncated": len(text) > TRANSCRIPT_MAX_CHARS,
            "source": "yt_dlp_vtt_captions",
        }


def _fetch_transcript_multiroute(video_id: str) -> dict[str, Any]:
    errors: list[str] = []
    try:
        return v4._fetch_transcript(video_id)
    except Exception as exc:
        errors.append(f"YOUTUBE_TRANSCRIPT_API:{type(exc).__name__}:{exc}")
    try:
        return _fetch_transcript_ytdlp(video_id)
    except Exception as exc:
        errors.append(f"YTDLP:{type(exc).__name__}:{exc}")
    raise RuntimeError("MULTIROUTE_TRANSCRIPT_UNAVAILABLE:" + "|".join(errors[-2:]))


def _grounded_recovery_prompt(original_prompt: str, candidate: Mapping[str, Any], oembed: Mapping[str, Any] | None, transcript_error: str) -> str:
    schema = dict(base.VIDEO_SCHEMA)
    schema.update(
        {
            "evidence_mode": "SEARCH_GROUNDED_TEXTUAL_EVIDENCE|INSUFFICIENT_EVIDENCE",
            "exact_video_id": "exact 11-character target video id",
            "evidence_basis": ["indexed caption/transcript/creator description/search-grounded textual evidence actually used"],
            "evidence_urls": ["public URL used as textual evidence"],
            "content_specific_facts": ["facts attributable to the video's textual/indexed content, not title/thumbnail inference"],
        }
    )
    return (
        original_prompt
        + "\nSEARCH_GROUNDED_RECOVERY_OVERRIDE: Direct Gemini YouTube attachment and direct caption retrieval were unavailable. "
        "Use Google Search ONLY to recover textual/indexed evidence for the EXACT video id and URL below. Acceptable evidence is indexed captions/transcript, creator description, creator article/post that explicitly corresponds to this exact video, or search-grounded textual coverage that exposes the video's actual technical content. "
        "ABSOLUTELY FORBIDDEN: inferring a strategy from the title, thumbnail, channel reputation, generic knowledge, or similarly named videos. "
        "If content-specific textual evidence for this exact video is insufficient, return status=REJECT_SOURCE and evidence_mode=INSUFFICIENT_EVIDENCE with zero reproducible_mechanisms. "
        "Do not copy creator profitability/win-rate thresholds into strategy parameters. Mechanisms remain hypothesis-only and require local replay plus fresh/OOS. Return strict JSON only.\n"
        f"EXACT_CANDIDATE={json.dumps(dict(candidate), ensure_ascii=False, sort_keys=True)}\n"
        f"OEMBED_VERIFICATION={json.dumps(dict(oembed or {}), ensure_ascii=False, sort_keys=True)}\n"
        f"DIRECT_TRANSCRIPT_ERROR={json.dumps(base._trim(transcript_error, 1000), ensure_ascii=False)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def _validate_grounded_recovery(raw: Mapping[str, Any], grounding: Sequence[Mapping[str, Any]], candidate: Mapping[str, Any]) -> None:
    if str(raw.get("evidence_mode") or "") != "SEARCH_GROUNDED_TEXTUAL_EVIDENCE":
        raise RuntimeError("GROUNDED_RECOVERY_EVIDENCE_MODE_INVALID")
    if str(raw.get("exact_video_id") or "") != str(candidate.get("video_id") or ""):
        raise RuntimeError("GROUNDED_RECOVERY_VIDEO_ID_MISMATCH")
    if str(raw.get("status") or "").upper() != "USE":
        raise RuntimeError("GROUNDED_RECOVERY_NOT_USE")
    mechanisms = [x for x in (raw.get("reproducible_mechanisms") or []) if isinstance(x, Mapping)]
    facts = [str(x).strip() for x in (raw.get("content_specific_facts") or []) if str(x).strip()]
    basis = [str(x).strip().casefold() for x in (raw.get("evidence_basis") or []) if str(x).strip()]
    if not mechanisms or len(facts) < 1 or not grounding:
        raise RuntimeError("GROUNDED_RECOVERY_SUPPORT_INSUFFICIENT")
    forbidden_only = all(any(token in x for token in ("title", "thumbnail", "generic")) for x in basis) if basis else True
    if forbidden_only:
        raise RuntimeError("GROUNDED_RECOVERY_FORBIDDEN_EVIDENCE_BASIS")


def _channel_metrics(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out = v4._channel_metrics(result)
    for name, row in out.items():
        accepted = [
            x for x in (result.get("accepted_sources") or [])
            if isinstance(x, Mapping) and str(x.get("target_channel") or "") == name
        ]
        row["search_grounded_recovery_accepted"] = sum(
            1 for x in accepted if str(x.get("analysis_mode") or "") == "search_grounded_video_recovery"
        )
        row["multiroute_transcript_accepted"] = sum(
            1 for x in accepted if str(x.get("analysis_mode") or "") == "transcript_text_fallback"
        )
    return out


def run(output: Path, existing_path: Path = base.DEFAULT_EXISTING) -> dict[str, Any]:
    old_prompt, old_norm = v2._search_prompt, v2._normalize_search
    old_search, old_video = base.call_gemini_search, base.call_gemini_video
    recovery_meta: dict[str, dict[str, Any]] = {}
    oembed_checked: set[str] = set()
    oembed_hard_rejected: set[str] = set()
    transcript_attempted: set[str] = set()
    transcript_success: set[str] = set()
    transcript_failed: set[str] = set()
    grounded_attempted: set[str] = set()
    grounded_success: set[str] = set()
    grounded_failed: set[str] = set()

    def video_with_multiroute_recovery(api_key: str, models: Sequence[str], prompt: str, youtube_url: str, max_output_tokens: int):
        candidate = v4._candidate_from_prompt(prompt)
        video_id = str(candidate.get("video_id") or "") or str(v2._video_id(youtube_url) or "")
        if not v2._valid_id(video_id):
            raise RuntimeError("VIDEO_ID_INVALID_BEFORE_PROVIDER")

        oembed: dict[str, Any] | None = None
        oembed_checked.add(video_id)
        try:
            oembed = _oembed_verify(candidate)
            if oembed.get("actual_channel"):
                candidate["search_channel"] = oembed["actual_channel"]
            if oembed.get("title"):
                candidate["title"] = oembed["title"]
            if oembed.get("channel_identity_matches_target") is not True:
                return "youtube_oembed", {
                    "status": "REJECT_CHANNEL_MISMATCH",
                    "actual_channel": oembed.get("actual_channel"),
                    "channel_identity_matches_target": False,
                    "concise_video_summary": "",
                    "creator_claims": [],
                    "reproducible_mechanisms": [],
                    "marketing_or_nonreproducible": [],
                }
        except Exception as exc:
            if "OEMBED_VIDEO_NOT_PUBLIC" in str(exc):
                oembed_hard_rejected.add(video_id)
                return "youtube_oembed", {
                    "status": "REJECT_SOURCE",
                    "actual_channel": "",
                    "channel_identity_matches_target": False,
                    "concise_video_summary": "",
                    "creator_claims": [],
                    "reproducible_mechanisms": [],
                    "marketing_or_nonreproducible": ["video id is not publicly resolvable through YouTube oEmbed"],
                }

        try:
            return v4._retry(old_video, api_key, models, prompt, youtube_url, max_output_tokens)
        except Exception as direct_exc:
            transcript_attempted.add(video_id)
            transcript_exc: Exception | None = None
            try:
                transcript = _fetch_transcript_multiroute(video_id)
                fallback_prompt = v4._transcript_prompt(prompt, candidate, transcript)
                model, raw = v4._retry(v4._call_gemini_text, api_key, models, fallback_prompt, max_output_tokens)
                metadata_channel_match = bool((oembed or {}).get("channel_identity_matches_target")) or v4._channel_match(candidate)
                raw["actual_channel"] = str((oembed or {}).get("actual_channel") or candidate.get("search_channel") or "")
                raw["channel_identity_matches_target"] = metadata_channel_match
                if not metadata_channel_match:
                    raw["status"] = "REJECT_CHANNEL_MISMATCH"
                transcript_success.add(video_id)
                recovery_meta[video_id] = {
                    "analysis_mode": "transcript_text_fallback",
                    "transcript_source": transcript.get("source"),
                    "transcript_language": transcript.get("language_code"),
                    "transcript_is_generated": transcript.get("is_generated"),
                    "transcript_char_count_total": transcript.get("char_count_total"),
                    "transcript_char_count_used": transcript.get("char_count_used"),
                    "transcript_truncated": transcript.get("truncated"),
                    "direct_video_error": base._trim(str(direct_exc), 900),
                    "channel_identity_verified_by_oembed": bool(oembed),
                    "gemini_text_model": model,
                }
                return model, raw
            except Exception as exc:
                transcript_exc = exc
                transcript_failed.add(video_id)

            grounded_attempted.add(video_id)
            try:
                gp = _grounded_recovery_prompt(prompt, candidate, oembed, str(transcript_exc))
                model, raw, grounding = v4._retry(old_search, api_key, models, gp, max_output_tokens)
                _validate_grounded_recovery(raw, grounding, candidate)
                metadata_channel_match = bool((oembed or {}).get("channel_identity_matches_target")) or v4._channel_match(candidate)
                raw["actual_channel"] = str((oembed or {}).get("actual_channel") or candidate.get("search_channel") or "")
                raw["channel_identity_matches_target"] = metadata_channel_match
                if not metadata_channel_match:
                    raw["status"] = "REJECT_CHANNEL_MISMATCH"
                grounded_success.add(video_id)
                recovery_meta[video_id] = {
                    "analysis_mode": "search_grounded_video_recovery",
                    "direct_video_error": base._trim(str(direct_exc), 900),
                    "transcript_error": base._trim(str(transcript_exc), 900),
                    "channel_identity_verified_by_oembed": bool(oembed),
                    "gemini_search_model": model,
                    "grounding_source_count": len(grounding),
                    "grounding_sources": list(grounding)[:12],
                    "evidence_basis": list(raw.get("evidence_basis") or [])[:12],
                    "evidence_urls": list(raw.get("evidence_urls") or [])[:12],
                    "content_specific_facts": list(raw.get("content_specific_facts") or [])[:12],
                }
                return model, raw
            except Exception as grounded_exc:
                grounded_failed.add(video_id)
                raise RuntimeError(
                    "ALL_VIDEO_EVIDENCE_ROUTES_FAILED:"
                    + base._trim(str(direct_exc), 450)
                    + "|TRANSCRIPT:"
                    + base._trim(str(transcript_exc), 550)
                    + "|GROUNDED:"
                    + base._trim(str(grounded_exc), 650)
                ) from grounded_exc

    try:
        v2._search_prompt = v4._search_prompt
        v2._normalize_search = v4._normalize_search
        base.call_gemini_search = lambda *a, **k: v4._retry(old_search, *a, **k)
        base.call_gemini_video = video_with_multiroute_recovery
        result = v3.run(output, existing_path)
    finally:
        v2._search_prompt, v2._normalize_search = old_prompt, old_norm
        base.call_gemini_search, base.call_gemini_video = old_search, old_video

    for src in result.get("accepted_sources") or []:
        if not isinstance(src, dict):
            continue
        video_id = str(src.get("video_id") or "")
        meta = recovery_meta.get(video_id)
        if not meta:
            continue
        mode = str(meta.get("analysis_mode") or "")
        src["analysis_mode"] = mode
        src["direct_video_analysis"] = False
        src["channel_identity_verified_by_direct_analysis"] = False
        if mode == "transcript_text_fallback":
            src["tier"] = "named_channel_transcript_gemini_hypothesis"
            src["transcript_text_analysis"] = True
        elif mode == "search_grounded_video_recovery":
            src["tier"] = "named_channel_search_grounded_gemini_hypothesis"
            src["search_grounded_textual_analysis"] = True
        src.update(meta)

    reviews = result.get("reviews")
    if isinstance(reviews, dict):
        for video_id, meta in recovery_meta.items():
            row = reviews.get(video_id)
            if isinstance(row, dict):
                row.update(meta)

    cm = _channel_metrics(result)
    result["schema_version"] = SCHEMA
    result["provider_retry_policy"] = "OEMBED_PREVALIDATE__DIRECT_VIDEO__YOUTUBE_TRANSCRIPT_API__YTDLP_CAPTIONS__GEMINI_SEARCH_GROUNDED_TEXT__RETRY_429_5XX_TIMEOUT"
    result["video_evidence_recovery_policy"] = {
        "oembed_prevalidation_enabled": True,
        "direct_video_first_after_prevalidation": True,
        "youtube_transcript_api_enabled": True,
        "yt_dlp_caption_fallback_enabled": True,
        "search_grounded_textual_fallback_enabled": True,
        "title_thumbnail_rule_inference_forbidden": True,
        "generic_same_topic_substitution_forbidden": True,
        "creator_threshold_import_forbidden": True,
        "local_replay_required": True,
        "fresh_oos_required": True,
        "selection_authority": False,
        "promotion_authority": False,
    }
    result["channel_utilization"] = cm
    result.setdefault("metrics", {})["oembed_checked_now"] = len(oembed_checked)
    result["metrics"]["oembed_hard_rejected_now"] = len(oembed_hard_rejected)
    result["metrics"]["transcript_fallback_attempted_now"] = len(transcript_attempted)
    result["metrics"]["transcript_fallback_success_now"] = len(transcript_success)
    result["metrics"]["transcript_fallback_failed_now"] = len(transcript_failed)
    result["metrics"]["search_grounded_recovery_attempted_now"] = len(grounded_attempted)
    result["metrics"]["search_grounded_recovery_success_now"] = len(grounded_success)
    result["metrics"]["search_grounded_recovery_failed_now"] = len(grounded_failed)
    result["metrics"]["search_grounded_recovery_accepted_total"] = sum(x["search_grounded_recovery_accepted"] for x in cm.values())
    result["metrics"]["multiroute_transcript_accepted_total"] = sum(x["multiroute_transcript_accepted"] for x in cm.values())
    result["receipt_sha256"] = base._sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    candidate = {
        "video_id": "dQw4w9WgXcQ",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "target_channel": "Trader DNA",
        "target_aliases": ["Trader DNA"],
        "search_channel": "Trader DNA",
    }
    gp = _grounded_recovery_prompt("CANDIDATE={}", candidate, {"verified": True}, "blocked")
    assert "ABSOLUTELY FORBIDDEN" in gp and "SEARCH_GROUNDED_TEXTUAL_EVIDENCE" in gp
    fake_raw = {
        "status": "USE",
        "evidence_mode": "SEARCH_GROUNDED_TEXTUAL_EVIDENCE",
        "exact_video_id": "dQw4w9WgXcQ",
        "evidence_basis": ["indexed transcript"],
        "content_specific_facts": ["specific content"],
        "reproducible_mechanisms": [{"mechanism": "m", "local_test_needed": "t"}],
    }
    _validate_grounded_recovery(fake_raw, [{"url": "https://example.com", "title": "x"}], candidate)
    assert _vtt_to_text("WEBVTT\n\n00:00.000 --> 00:01.000\nhello\n00:01.000 --> 00:02.000\nhello\n00:02.000 --> 00:03.000\nworld") == "hello world"
    assert _channel_matches_name("Trading Notes", "Trading Notes")
    print("PASS_A1_NAMED_CHANNEL_GEMINI_SWEEP_V5_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_named_channel_gemini_latest.json"))
    ap.add_argument("--existing", type=Path, default=base.DEFAULT_EXISTING)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output, args.existing)
    print(json.dumps({"state": r["state"], **r["metrics"], "errors": r["provider"]["errors"][:3]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
