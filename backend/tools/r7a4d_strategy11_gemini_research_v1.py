from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping


PREFERRED_MODELS = (
    "models/gemini-3.6-flash",
    "models/gemini-3.5-flash",
    "models/gemini-3.5-flash-lite",
    "models/gemini-3.1-flash-lite",
    "models/gemini-3-flash-preview",
)
PROMPT_VERSION = "S11_GEMINI_MULTI_SOURCE_V1"


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def stable_sha(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def run(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def search_videos(query: str, limit: int) -> list[dict[str, Any]]:
    result = run(["yt-dlp", "--dump-single-json", "--skip-download", f"ytsearch{limit}:{query}"], timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"YTDLP_SEARCH_FAILED:{result.stderr[-1000:]}")
    payload = json.loads(result.stdout)
    rows: list[dict[str, Any]] = []
    for entry in payload.get("entries", []):
        if not isinstance(entry, Mapping):
            continue
        video_id = str(entry.get("id") or "")
        if not video_id:
            continue
        rows.append({
            "id": video_id,
            "url": str(entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"),
            "title": str(entry.get("title") or ""),
            "channel": str(entry.get("channel") or entry.get("uploader") or ""),
            "channel_id": str(entry.get("channel_id") or entry.get("uploader_id") or ""),
            "upload_date": entry.get("upload_date"),
            "view_count": int(entry.get("view_count") or 0),
            "duration": int(entry.get("duration") or 0),
            "description": str(entry.get("description") or "")[:2000],
        })
    return rows


def keyword_relevance(row: Mapping[str, Any], query: str) -> float:
    words = {word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2}
    text = f"{row.get('title', '')} {row.get('description', '')}".lower()
    hits = sum(word in text for word in words)
    return min(5.0, hits / max(1, len(words)) * 5.0)


def preselect(rows: list[dict[str, Any]], query: str, minimum: int, independent_channels: int) -> list[dict[str, Any]]:
    candidates = []
    max_views = max((row["view_count"] for row in rows), default=1)
    for row in rows:
        if row["duration"] and row["duration"] < 180:
            continue
        relevance = keyword_relevance(row, query)
        view_score = math.log1p(row["view_count"]) / max(1e-12, math.log1p(max_views)) * 5.0
        item = dict(row)
        item["pre_score"] = relevance * 0.55 + view_score * 0.45
        item["view_score"] = view_score
        item["relevance_pre"] = relevance
        candidates.append(item)
    candidates.sort(key=lambda row: (row["pre_score"], row["view_count"]), reverse=True)
    selected: list[dict[str, Any]] = []
    channel_counts: dict[str, int] = {}
    for row in candidates:
        channel = row["channel_id"] or row["channel"] or row["id"]
        if channel_counts.get(channel, 0) >= 1 and len({item["channel_id"] or item["channel"] for item in selected}) < independent_channels:
            continue
        selected.append(row)
        channel_counts[channel] = channel_counts.get(channel, 0) + 1
        if len(selected) >= max(minimum, 6):
            break
    return selected


def strip_vtt(text: str) -> str:
    lines: list[str] = []
    prior = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit() or line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and line != prior:
            lines.append(line)
            prior = line
    return "\n".join(lines)


def transcript_for(row: Mapping[str, Any], directory: Path) -> str:
    template = str(directory / f"{row['id']}.%(ext)s")
    run([
        "yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-langs", "en.*,ko.*", "--sub-format", "vtt", "-o", template, str(row["url"]),
    ], timeout=300)
    files = sorted(directory.glob(f"{row['id']}*.vtt"), key=lambda path: path.stat().st_size, reverse=True)
    if not files:
        return ""
    return strip_vtt(files[0].read_text(encoding="utf-8", errors="replace"))[:40000]


def list_models(key: str) -> list[str]:
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": key},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    eligible = []
    for row in payload.get("models", []):
        if "generateContent" in row.get("supportedGenerationMethods", []) and row.get("name"):
            eligible.append(str(row["name"]))
    ordered = [model for model in PREFERRED_MODELS if model in eligible]
    ordered.extend(model for model in eligible if model not in ordered and "flash" in model.lower())
    return ordered


def call_gemini(key: str, models: list[str], prompt: str) -> tuple[str, str]:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            "temperature": 0.15,
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    errors: list[str] = []
    for model in models:
        try:
            request = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                data=body,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                generated = json.load(response)
            texts = []
            for candidate in generated.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if isinstance(part.get("text"), str):
                        texts.append(part["text"])
            text = "\n".join(texts).strip()
            if not text:
                raise RuntimeError("EMPTY_GEMINI_RESPONSE")
            return model, text
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{model}:HTTP_{exc.code}:{detail[:500]}")
        except Exception as exc:
            errors.append(f"{model}:{type(exc).__name__}:{exc}")
    raise RuntimeError("GEMINI_ALL_MODELS_FAILED:" + "|".join(errors))


def topic_for(row: Mapping[str, Any]) -> str:
    pf = row.get("net_profit_factor_adjusted")
    payoff = row.get("payoff_ratio_adjusted")
    dd = row.get("max_drawdown_pct")
    if isinstance(dd, (int, float)) and dd > 2.0:
        return "crypto trading drawdown reduction regime filter stop loss backtest"
    if isinstance(payoff, (int, float)) and payoff < 1.2:
        return "crypto trading improve payoff ratio partial take profit trailing stop MFE MAE backtest"
    if isinstance(pf, (int, float)) and pf < 1.2:
        return "crypto trading profit factor entry filter transaction costs robust backtest"
    return "crypto trading MFE MAE exit optimization walk forward robust backtest"


def build_prompt(strategy: Mapping[str, Any], sources: list[dict[str, Any]]) -> str:
    public_sources = []
    for source in sources:
        public_sources.append({
            "url": source["url"],
            "title": source["title"],
            "channel": source["channel"],
            "upload_date": source["upload_date"],
            "view_count": source["view_count"],
            "description": source["description"],
            "transcript": source.get("transcript", ""),
        })
    schema = {
        "status": "PASS|HOLD",
        "source_assessments": [{
            "url": "...", "relevance": 0, "evidence_quality": 0,
            "methodology_transparency": 0, "independence": 0, "recency": 0,
            "conflict_of_interest": 0, "decision": "USE|REJECT_SOURCE", "reason": "..."
        }],
        "cross_source_matrix": [{
            "claim": "...", "supporting_sources": ["..."], "contradicting_sources": ["..."],
            "evidence_strength": "LOW|MEDIUM|HIGH", "applicability_to_our_strategy": "...",
            "required_internal_test": "..."
        }],
        "hypotheses": [{
            "label": "HYPOTHESIS_EXTERNAL", "change_type": "stop|target|BE|partial|trailing|time_stop|feature_gate|regime_whitelist|NO_CHANGE",
            "single_cause_change": "...", "why": "...", "overfit_risk": "...", "falsification_test": "..."
        }],
        "recommended_order": ["NO_CHANGE", "alternative_1", "alternative_2"]
    }
    return (
        "You are a skeptical quantitative research reviewer. Compare multiple independent public videos; never accept a single video as authority. "
        "Reject marketing, hidden samples, lookahead, repainting, omitted costs, and unsupported returns. Official/reproducible evidence outranks popularity. "
        "The internal strategy is anonymized and no private code or account data is provided. Return JSON only matching the requested schema. "
        "Produce at most two single-cause modification hypotheses plus a NO_CHANGE control. Every external idea remains HYPOTHESIS_EXTERNAL until internal fresh/holdback testing.\n\n"
        f"PROMPT_VERSION={PROMPT_VERSION}\n"
        f"INTERNAL_METRICS={json.dumps(strategy, ensure_ascii=False, sort_keys=True)}\n"
        f"PUBLIC_SOURCES={json.dumps(public_sources, ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-summary", required=True)
    parser.add_argument("--candidate-queue", required=True)
    parser.add_argument("--ssot", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    gate = strict_json(Path(args.gate_summary))
    queue = strict_json(Path(args.candidate_queue))
    ssot = strict_json(Path(args.ssot))
    out = Path(args.out).resolve()
    blockers: list[str] = []
    if gate.get("data_adequacy_pass") is not True or gate.get("gemini_allowed") is not True:
        blockers.append("DATA_ADEQUACY_NOT_PASS")
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        blockers.append("GEMINI_API_KEY_MISSING")
    candidates = [row for row in queue.get("rows", []) if isinstance(row, Mapping)]
    if not candidates:
        blockers.append("CANDIDATE_QUEUE_EMPTY")
    if blockers:
        atomic_json(out / "summary.json", {
            "schema_version": "1.0", "state": "HOLD", "GEMINI_USED": False,
            "free_only": True, "blockers": blockers, "execution_allowed": False,
        })
        return 0

    models = list_models(key)
    if not models:
        blockers.append("NO_FREE_FLASH_MODEL")
    results: list[dict[str, Any]] = []
    video_root = out / "video_cache"
    video_root.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        strategy_id = str(candidate["strategy_id"])
        query = topic_for(candidate)
        found = search_videos(query, 12)
        selected = preselect(
            found, query,
            int(ssot["gemini"]["minimum_videos_per_topic"]),
            int(ssot["gemini"]["minimum_independent_channels"]),
        )
        channels = {row["channel_id"] or row["channel"] for row in selected}
        if len(selected) < int(ssot["gemini"]["minimum_videos_per_topic"]) or len(channels) < int(ssot["gemini"]["minimum_independent_channels"]):
            results.append({"strategy_id": strategy_id, "state": "HOLD", "blockers": ["INSUFFICIENT_INDEPENDENT_VIDEO_SOURCES"], "query": query, "sources": selected})
            continue
        for row in selected:
            row["transcript"] = transcript_for(row, video_root)
        usable = [row for row in selected if row.get("transcript")]
        if len(usable) < int(ssot["gemini"]["minimum_videos_per_topic"]):
            results.append({"strategy_id": strategy_id, "state": "HOLD", "blockers": ["TRANSCRIPTS_LT_MINIMUM"], "query": query, "sources": selected})
            continue
        prompt = build_prompt(candidate, usable)
        model, response_text = call_gemini(key, models, prompt)
        try:
            response = json.loads(response_text)
        except json.JSONDecodeError:
            response = {"status": "HOLD", "raw_response": response_text[:20000], "blockers": ["GEMINI_NON_JSON"]}
        source_audit = [{key: row.get(key) for key in ("url", "title", "channel", "channel_id", "upload_date", "view_count", "duration", "view_score", "relevance_pre")} for row in usable]
        item = {
            "strategy_id": strategy_id,
            "state": "PASS" if response.get("status") == "PASS" else "HOLD",
            "query": query,
            "public_urls": [row["url"] for row in usable],
            "source_audit": source_audit,
            "actual_model": model,
            "free_only": True,
            "prompt_version": PROMPT_VERSION,
            "input_artifact_sha256": stable_sha({"candidate": candidate, "sources": source_audit}),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
            "response": response,
        }
        atomic_json(out / strategy_id / "analysis.json", item)
        results.append(item)

    state = "PASS" if results and all(row.get("state") == "PASS" for row in results) else "HOLD"
    repair_rows = []
    for row in results:
        response = row.get("response") if isinstance(row.get("response"), Mapping) else {}
        hypotheses = [item for item in response.get("hypotheses", []) if isinstance(item, Mapping)]
        repair_rows.append({"strategy_id": row["strategy_id"], "state": row["state"], "hypotheses": hypotheses[:3]})
    atomic_json(out / "repair_queue.json", {
        "schema_version": "1.0", "state": state,
        "authority": "GEMINI_HYPOTHESES_ONLY_NO_STRATEGY_MUTATION",
        "rows": repair_rows, "execution_allowed": False,
    })
    atomic_json(out / "summary.json", {
        "schema_version": "1.0", "state": state, "GEMINI_USED": True,
        "result_status": state, "free_only": True, "candidate_count": len(results),
        "results": [{"strategy_id": row["strategy_id"], "state": row["state"], "actual_model": row.get("actual_model"), "public_urls": row.get("public_urls", [])} for row in results],
        "blockers": blockers, "canonical_mutated": False, "execution_allowed": False,
        "next": "CREATE_ISOLATED_SINGLE_CAUSE_REPAIR_CHILD" if state == "PASS" else "HOLD_EXTERNAL_RESEARCH",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
