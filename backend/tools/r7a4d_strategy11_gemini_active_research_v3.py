from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import statistics
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
V2_PATH = ROOT / "backend/tools/r7a4d_strategy11_gemini_direct_video_v2.py"
PIPELINE_VERSION = "R7A4D_STRATEGY11_GEMINI_ACTIVE_RESEARCH_V3"
PROMPT_VERSION = "S11_GEMINI_ACTIVE_RESEARCH_MULTIMODAL_V3"
FORBIDDEN_KEY = re.compile(r"(api.?key|secret|token|password|credential|cookie|authorization|account|email|phone|address|order.?id|position.?id|client.?id|private.?key)", re.I)
STRATEGIES = {
    "alpha_combo": "A",
    "turtle_trend": "B",
    "ema_ribbon_scalp": "C",
}
METRIC_KEYS = {
    "state", "classification", "strategy_id", "variant_id", "blockers", "diagnosis", "next",
    "trade_count", "win_count", "loss_count", "win_rate_pct", "net_return_pct_sum",
    "net_profit_factor", "payoff_ratio", "max_drawdown_pct", "positive_windows_pct",
    "avg_win_R", "avg_loss_R", "worst_net_loss_R", "normal_worst_net_loss_R",
    "loss_cap_breach_count", "delta_net_pct_points", "delta_profit_factor",
    "delta_payoff_ratio", "trade_retention_pct", "pass_to_sealed", "winner",
    "sealed_holdback_read", "stress_loss_cap_pass", "normal_loss_cap_pass",
}


def load_v2() -> Any:
    spec = importlib.util.spec_from_file_location("s11_gemini_direct_video_v2", V2_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("V2_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v2 = load_v2()


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<depth-limit>"
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if FORBIDDEN_KEY.search(key_s):
                continue
            if key_s in METRIC_KEYS or depth <= 2:
                out[key_s] = sanitize(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [sanitize(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, str):
        value = re.sub(r"[A-Za-z]:\\[^\s]+|/(?:home|root|mnt|tmp)/[^\s]+", "<path-redacted>", value)
        value = re.sub(r"\b[A-Fa-f0-9]{40,64}\b", "<sha-redacted>", value)
        return value[:4000]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:1000]


def iter_json(root: Path) -> Iterable[tuple[Path, Any]]:
    for path in sorted(root.rglob("*.json")):
        try:
            if path.stat().st_size > 5_000_000:
                continue
            yield path, strict_json(path)
        except Exception:
            continue


def find_strategy_docs(roots: Sequence[Path], strategy_id: str) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for root in roots:
        for path, payload in iter_json(root):
            text = f"{path.as_posix()} {json.dumps(payload, ensure_ascii=False)[:20000]}"
            if strategy_id not in text:
                continue
            if isinstance(payload, Mapping):
                docs.append({"source_name": path.name, "source_path_sha": hashlib.sha256(path.as_posix().encode()).hexdigest(), "payload": sanitize(payload)})
    return docs[:60]


def trade_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(payload, Mapping):
        if isinstance(payload.get("trades"), list):
            candidates.extend(payload["trades"])
        for value in payload.values():
            if isinstance(value, Mapping) and isinstance(value.get("trades"), list):
                candidates.extend(value["trades"])
    return [dict(row) for row in candidates if isinstance(row, Mapping)]


def collect_trades(roots: Sequence[Path], strategy_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        for path, payload in iter_json(root):
            if strategy_id not in path.as_posix() and strategy_id not in json.dumps(payload, ensure_ascii=False)[:2000]:
                continue
            for row in trade_rows_from_payload(payload):
                key = stable_sha({k: row.get(k) for k in ("symbol", "window_id", "entry_ts", "exit_ts", "entry_time", "exit_time", "net_return_pct", "net_R")})
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    return rows[:5000]


def number(row: Mapping[str, Any], keys: Sequence[str]) -> float | None:
    for key in keys:
        value = row.get(key)
        if finite(value):
            return float(value)
    return None


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
    return values[index]


def trade_cluster(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net_values: list[float] = []
    mfe_values: list[float] = []
    mae_values: list[float] = []
    bars_values: list[float] = []
    favorable_then_loss = Counter()
    exit_reasons = Counter()
    symbols = Counter()
    windows = Counter()
    regimes = Counter()
    for row in trades:
        net = number(row, ("net_R", "net_reference_R", "pnl_r", "net_return_R"))
        if net is None:
            net_pct = number(row, ("net_return_pct", "pnl_pct"))
            risk_pct = number(row, ("risk_pct", "reference_risk_pct"))
            if net_pct is not None and risk_pct not in (None, 0.0):
                net = net_pct / risk_pct
        mfe = number(row, ("mfe_R", "mfe_r", "max_favorable_excursion_R"))
        mae = number(row, ("mae_R", "mae_r", "max_adverse_excursion_R"))
        bars = number(row, ("bars_held", "holding_bars", "duration_bars"))
        if net is not None:
            net_values.append(net)
        if mfe is not None:
            mfe_values.append(mfe)
        if mae is not None:
            mae_values.append(mae)
        if bars is not None:
            bars_values.append(bars)
        if net is not None and net < 0 and mfe is not None:
            for threshold in (0.25, 0.5, 0.75, 1.0, 1.5):
                if mfe >= threshold:
                    favorable_then_loss[f"mfe_ge_{threshold}R"] += 1
        exit_reasons[str(row.get("exit_reason") or row.get("reason") or "unknown")] += 1
        symbols[str(row.get("symbol") or "unknown")] += 1
        windows[str(row.get("window_id") or row.get("window") or "unknown")] += 1
        regimes[str(row.get("regime") or "unknown")] += 1
    losses = [x for x in net_values if x < 0]
    wins = [x for x in net_values if x > 0]
    return {
        "trade_count": len(trades),
        "net_R_count": len(net_values),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (len(wins) / len(net_values) * 100.0) if net_values else None,
        "avg_win_R": statistics.mean(wins) if wins else None,
        "avg_loss_R": statistics.mean(losses) if losses else None,
        "worst_loss_R": min(losses) if losses else None,
        "mfe_R_p50": quantile(mfe_values, 0.5),
        "mfe_R_p75": quantile(mfe_values, 0.75),
        "mae_R_p50": quantile(mae_values, 0.5),
        "mae_R_p75": quantile(mae_values, 0.75),
        "bars_held_p50": quantile(bars_values, 0.5),
        "bars_held_p90": quantile(bars_values, 0.9),
        "favorable_then_loss": dict(favorable_then_loss),
        "exit_reason_counts": dict(exit_reasons.most_common(12)),
        "symbol_counts": dict(symbols.most_common(12)),
        "window_counts": dict(windows.most_common(12)),
        "regime_counts": dict(regimes.most_common(12)),
    }


def fetch_json(url: str, *, timeout: int = 45, headers: Mapping[str, str] | None = None) -> Any:
    req = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def arxiv_search(query: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    url = f"https://export.arxiv.org/api/query?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Strategy11Research/3.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        root = ET.fromstring(response.read())
    ns = {"a": "http://www.w3.org/2005/Atom"}
    rows: list[dict[str, Any]] = []
    for entry in root.findall("a:entry", ns):
        title = " ".join((entry.findtext("a:title", default="", namespaces=ns)).split())
        summary = " ".join((entry.findtext("a:summary", default="", namespaces=ns)).split())
        published = entry.findtext("a:published", default="", namespaces=ns)
        link = entry.findtext("a:id", default="", namespaces=ns)
        authors = [node.findtext("a:name", default="", namespaces=ns) for node in entry.findall("a:author", ns)]
        if title:
            rows.append({"kind": "arxiv", "title": title, "abstract": summary[:5000], "published": published, "url": link, "authors": authors[:8]})
    return rows


def crossref_search(query: str, limit: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"query.title": query, "rows": limit, "select": "DOI,title,abstract,published,URL,is-referenced-by-count,type"})
    url = f"https://api.crossref.org/works?{params}"
    payload = fetch_json(url, timeout=45, headers={"User-Agent": "Strategy11Research/3.0 (mailto:noreply@example.invalid)"})
    rows: list[dict[str, Any]] = []
    for item in payload.get("message", {}).get("items", []):
        title_list = item.get("title") if isinstance(item.get("title"), list) else []
        title = str(title_list[0]) if title_list else ""
        abstract = re.sub(r"<[^>]+>", " ", str(item.get("abstract") or ""))
        abstract = " ".join(abstract.split())
        if not title:
            continue
        rows.append({
            "kind": "crossref",
            "title": title,
            "abstract": abstract[:5000],
            "url": item.get("URL"),
            "doi": item.get("DOI"),
            "citation_count": int(item.get("is-referenced-by-count") or 0),
            "type": item.get("type"),
        })
    return rows


def collect_literature(policy: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    queries = policy.get("literature_queries") if isinstance(policy.get("literature_queries"), list) else []
    limit = int(policy.get("papers_per_query") or 4)
    for query in queries:
        query_s = str(query)
        try:
            rows.extend(arxiv_search(query_s, limit))
        except Exception as exc:
            errors.append(f"ARXIV:{query_s}:{type(exc).__name__}:{exc}")
        try:
            rows.extend(crossref_search(query_s, limit))
        except Exception as exc:
            errors.append(f"CROSSREF:{query_s}:{type(exc).__name__}:{exc}")
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = re.sub(r"\W+", "", str(row.get("title") or "").lower())[:160]
        if not key:
            continue
        prior = dedup.get(key)
        if prior is None or int(row.get("citation_count") or 0) > int(prior.get("citation_count") or 0):
            dedup[key] = row
    ordered = sorted(dedup.values(), key=lambda row: (int(row.get("citation_count") or 0), len(str(row.get("abstract") or ""))), reverse=True)
    return ordered[: int(policy.get("max_literature_sources") or 24)], errors


def get_variants(docs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for doc in docs:
        payload = doc.get("payload")
        if not isinstance(payload, Mapping):
            continue
        rows = payload.get("variants")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, Mapping):
                    variants.append(dict(row))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in variants:
        key = str(row.get("variant_id") or stable_sha(row))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[:30]


def create_charts(out: Path, alias: str, variants: list[dict[str, Any]], trades: list[dict[str, Any]]) -> list[Path]:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []
    paths: list[Path] = []
    chart_dir = out / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    if variants:
        labels = [str(row.get("variant_id") or f"v{i}")[:24] for i, row in enumerate(variants[:8])]
        metrics = ["net_return_pct_sum", "net_profit_factor", "payoff_ratio", "max_drawdown_pct"]
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        for ax, metric in zip(axes.ravel(), metrics):
            vals = [float(row.get(metric)) if finite(row.get(metric)) else 0.0 for row in variants[:8]]
            ax.bar(range(len(labels)), vals)
            ax.set_title(metric)
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=7)
            ax.grid(axis="y", alpha=0.25)
        fig.suptitle(f"Strategy {alias}: candidate metrics")
        fig.tight_layout()
        path = chart_dir / f"{alias}_variant_metrics.png"
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(path)
    points: list[tuple[float, float, float]] = []
    for row in trades:
        mfe = number(row, ("mfe_R", "mfe_r", "max_favorable_excursion_R"))
        mae = number(row, ("mae_R", "mae_r", "max_adverse_excursion_R"))
        net = number(row, ("net_R", "net_reference_R", "pnl_r"))
        if mfe is not None and mae is not None and net is not None:
            points.append((mfe, mae, net))
    if points:
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.scatter([x for x, _, _ in points], [y for _, y, _ in points], c=[1 if z > 0 else 0 for _, _, z in points], alpha=0.7)
        ax.axvline(0.5, linestyle="--", linewidth=1)
        ax.axvline(1.0, linestyle="--", linewidth=1)
        ax.set_xlabel("MFE (R)")
        ax.set_ylabel("MAE (R)")
        ax.set_title(f"Strategy {alias}: trade excursion map")
        ax.grid(alpha=0.25)
        path = chart_dir / f"{alias}_mfe_mae.png"
        fig.tight_layout()
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(path)
    return paths


def parse_gemini_text(generated: Mapping[str, Any]) -> str:
    texts: list[str] = []
    for candidate in generated.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if isinstance(part.get("text"), str):
                texts.append(part["text"])
    text = "\n".join(texts).strip()
    if not text:
        raise RuntimeError("EMPTY_GEMINI_RESPONSE")
    return text


def call_gemini(key: str, models: Sequence[str], parts: list[dict[str, Any]], *, max_tokens: int = 16384) -> tuple[str, str]:
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    errors: list[str] = []
    for model in models:
        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                data=body,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=900) as response:
                generated = json.load(response)
            return model, parse_gemini_text(generated)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{model}:HTTP_{exc.code}:{detail[:1000]}")
        except Exception as exc:
            errors.append(f"{model}:{type(exc).__name__}:{exc}")
    raise RuntimeError("GEMINI_ALL_MODELS_FAILED:" + "|".join(errors))


def image_part(path: Path) -> dict[str, Any]:
    return {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(path.read_bytes()).decode("ascii")}}


def json_response(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
        return dict(payload) if isinstance(payload, Mapping) else {"status": "HOLD", "blockers": ["NON_OBJECT_JSON"]}
    except json.JSONDecodeError:
        return {"status": "HOLD", "blockers": ["GEMINI_NON_JSON"], "raw_response": text[:30000]}


def source_prompt(videos: list[dict[str, Any]], papers: list[dict[str, Any]], prior: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "source_assessments": [{"source_id": "V1|P1", "decision": "USE|REJECT_SOURCE", "quality": 0, "methodology": 0, "relevance": 0, "reason": "..."}],
        "claim_matrix": [{"claim": "...", "support": ["V1"], "contradict": ["P1"], "strength": "LOW|MEDIUM|HIGH", "limitations": ["..."]}],
        "coverage_gaps": ["..."],
        "usable_principles": [{"principle": "...", "scope": "...", "required_internal_test": "..."}],
    }
    video_meta = [{"source_id": f"V{i+1}", **sanitize(row)} for i, row in enumerate(videos)]
    paper_meta = [{"source_id": f"P{i+1}", **sanitize(row)} for i, row in enumerate(papers)]
    return (
        "You are the source-audit layer for a quantitative trading research pipeline. Analyze every attached public YouTube video and the supplied paper metadata/abstracts. "
        "Popularity is only discovery priority. Reject marketing, tiny samples, lookahead, repainting, missing costs, non-reproducible rules, and duplicated claims. "
        "Identify agreements and contradictions. Do not propose strategy changes yet. Return strict JSON only.\n\n"
        f"PROMPT_VERSION={PROMPT_VERSION}\n"
        f"VIDEO_METADATA={json.dumps(video_meta, ensure_ascii=False, sort_keys=True)}\n"
        f"LITERATURE_METADATA={json.dumps(paper_meta, ensure_ascii=False, sort_keys=True)}\n"
        f"PRIOR_RESEARCH_SUMMARY={json.dumps(sanitize(prior), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def strategy_prompt(alias: str, profile: Mapping[str, Any], source_review: Mapping[str, Any], prior_queue: Sequence[Mapping[str, Any]]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "strategy_alias": alias,
        "failure_clusters": [{"cluster": "...", "evidence": ["..."], "causal_confidence": 0, "winner_contamination_risk": "LOW|MEDIUM|HIGH"}],
        "chart_observations": [{"observation": "...", "supports": "...", "does_not_prove": "..."}],
        "candidate_hypotheses": [{
            "label": "HYPOTHESIS_EXTERNAL",
            "change_type": "stop|target|BE|partial|trailing|time_stop|feature_gate|regime_whitelist|exit_selector|NO_CHANGE",
            "single_cause_change": "...",
            "bounded_parameter_space": ["..."],
            "why_distinct_from_prior_attempts": "...",
            "expected_metric_effect": "...",
            "falsification_test": "...",
            "overfit_risk": "LOW|MEDIUM|HIGH",
            "priority": 1,
        }],
        "recommended_action": "TEST|KEEP_CONTROL|WAIT_FRESH_DATA",
    }
    return (
        "You are the multimodal failure-analysis layer for one anonymized quantitative strategy. Analyze the attached internal charts and anonymized evidence together with the audited external principles. "
        "Do not infer private code. Separate observation from causality. Do not repeat a previously tested axis unless a new causal mechanism is demonstrated. "
        "Produce NO_CHANGE plus at most two genuinely distinct single-cause hypotheses. No multi-axis changes, no arbitrary parameter sweeps, no performance claims. Return strict JSON only.\n\n"
        f"PROMPT_VERSION={PROMPT_VERSION}\n"
        f"STRATEGY_ALIAS={alias}\n"
        f"ANONYMIZED_PROFILE={json.dumps(sanitize(profile), ensure_ascii=False, sort_keys=True)}\n"
        f"AUDITED_EXTERNAL_PRINCIPLES={json.dumps(sanitize(source_review), ensure_ascii=False, sort_keys=True)}\n"
        f"PRIOR_HYPOTHESES={json.dumps(sanitize(list(prior_queue)), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def red_team_prompt(analyses: Mapping[str, Any], source_review: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    schema = {
        "status": "PASS|HOLD",
        "rejected_hypotheses": [{"strategy_alias": "A", "single_cause_change": "...", "reason": "duplicate|unsupported|overfit|winner_contamination|multi_axis"}],
        "approved_queue": [{
            "strategy_alias": "A", "label": "HYPOTHESIS_EXTERNAL", "change_type": "...", "single_cause_change": "...",
            "bounded_parameter_space": ["..."], "required_replay": ["selection", "validation", "holdout", "fresh_non_overlap", "cost_stress", "new_sealed"],
            "falsification_test": "...", "priority": 1,
        }],
        "hold_reasons": [{"strategy_alias": "C", "reason": "...", "reopen_condition": "..."}],
    }
    return (
        "You are the independent red-team adjudicator. Review source audit and three strategy analyses. Reject duplicated axes, weak evidence, parameter mining, hidden multi-axis changes, winner contamination, and hypotheses that cannot be falsified. "
        "Approve at most two hypotheses per strategy and no more than three active hypotheses globally. Every approved item remains HYPOTHESIS_EXTERNAL and must be tested internally. Return strict JSON only.\n\n"
        f"PROMPT_VERSION={PROMPT_VERSION}\n"
        f"SOURCE_REVIEW={json.dumps(sanitize(source_review), ensure_ascii=False, sort_keys=True)}\n"
        f"STRATEGY_ANALYSES={json.dumps(sanitize(analyses), ensure_ascii=False, sort_keys=True)}\n"
        f"RESEARCH_POLICY={json.dumps(sanitize(policy), ensure_ascii=False, sort_keys=True)}\n"
        f"OUTPUT_SCHEMA={json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--prior-gemini", required=True)
    parser.add_argument("--alpha-root", required=True)
    parser.add_argument("--turtle-root", required=True)
    parser.add_argument("--ema-root", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out = Path(args.out).resolve()
    policy = strict_json(Path(args.policy))
    registry = strict_json(Path(args.registry))
    prior = strict_json(Path(args.prior_gemini))
    roots = {
        "alpha_combo": [Path(args.alpha_root).resolve(), Path(args.evidence_root).resolve()],
        "turtle_trend": [Path(args.turtle_root).resolve(), Path(args.evidence_root).resolve()],
        "ema_ribbon_scalp": [Path(args.ema_root).resolve(), Path(args.evidence_root).resolve()],
    }
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    blockers: list[str] = []
    if not key:
        blockers.append("GEMINI_API_KEY_MISSING")
    if prior.get("GEMINI_USED") is not True:
        blockers.append("PRIOR_GEMINI_AUTHORITY_NOT_USED")
    videos = [dict(row) for row in registry.get("sources", []) if isinstance(row, Mapping)]
    channels = {str(row.get("channel") or "") for row in videos if row.get("channel")}
    if len(videos) < int(policy["source_policy"]["minimum_public_videos"]):
        blockers.append("PUBLIC_VIDEO_SOURCE_COUNT_LOW")
    if len(channels) < int(policy["source_policy"]["minimum_independent_channels"]):
        blockers.append("PUBLIC_VIDEO_CHANNEL_COUNT_LOW")
    if blockers:
        atomic_json(out / "summary.json", {"schema_version": "3.0", "pipeline_version": PIPELINE_VERSION, "state": "HOLD", "GEMINI_USED": False, "free_only": True, "blockers": blockers, "execution_allowed": False})
        return 0

    papers, collector_errors = collect_literature(policy["source_policy"])
    source_catalog = {
        "schema_version": "3.0",
        "videos": videos,
        "literature": papers,
        "collector_errors": collector_errors,
        "video_count": len(videos),
        "independent_channel_count": len(channels),
        "literature_count": len(papers),
    }
    atomic_json(out / "source_catalog.json", source_catalog)

    profiles: dict[str, dict[str, Any]] = {}
    chart_paths: dict[str, list[Path]] = {}
    for strategy_id, alias in STRATEGIES.items():
        docs = find_strategy_docs(roots[strategy_id], strategy_id)
        trades = collect_trades(roots[strategy_id], strategy_id)
        variants = get_variants(docs)
        profile = {
            "strategy_alias": alias,
            "document_count": len(docs),
            "documents": docs[:20],
            "trade_cluster": trade_cluster(trades),
            "prior_research_rows": [row for row in (strict_json(Path(args.prior_gemini)).get("response", {}).get("strategy_reviews", []) if isinstance(strict_json(Path(args.prior_gemini)).get("response"), Mapping) else []) if isinstance(row, Mapping) and row.get("strategy_alias") == alias],
        }
        profiles[alias] = profile
        atomic_json(out / "profiles" / f"{alias}.json", profile)
        chart_paths[alias] = create_charts(out, alias, variants, trades)

    models = v2.list_models(key)
    if not models:
        raise RuntimeError("NO_FREE_FLASH_MODEL")
    call_audit: list[dict[str, Any]] = []

    source_parts: list[dict[str, Any]] = [{"text": source_prompt(videos, papers, prior)}]
    source_parts.extend({"file_data": {"file_uri": row["url"]}} for row in videos)
    model, text = call_gemini(key, models, source_parts)
    source_review = json_response(text)
    atomic_json(out / "source_review.json", source_review)
    call_audit.append({"stage": "SOURCE_REVIEW", "model": model, "video_attachments": len(videos), "image_attachments": 0, "prompt_sha256": hashlib.sha256(source_parts[0]["text"].encode()).hexdigest(), "response_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": source_review.get("status")})

    strategy_analyses: dict[str, Any] = {}
    prior_queue = strict_json(Path(args.prior_gemini).with_name("repair_queue.json")) if Path(args.prior_gemini).with_name("repair_queue.json").exists() else {"rows": []}
    for alias in ("A", "B", "C"):
        parts: list[dict[str, Any]] = [{"text": strategy_prompt(alias, profiles[alias], source_review, [row for row in prior_queue.get("rows", []) if isinstance(row, Mapping) and STRATEGIES.get(str(row.get("strategy_id"))) == alias])}]
        parts.extend(image_part(path) for path in chart_paths[alias][:2])
        model, text = call_gemini(key, models, parts)
        response = json_response(text)
        strategy_analyses[alias] = response
        atomic_json(out / "strategy_analysis" / f"{alias}.json", response)
        call_audit.append({"stage": f"STRATEGY_{alias}", "model": model, "video_attachments": 0, "image_attachments": len(parts) - 1, "prompt_sha256": hashlib.sha256(parts[0]["text"].encode()).hexdigest(), "response_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": response.get("status")})

    red_prompt = red_team_prompt(strategy_analyses, source_review, policy)
    model, text = call_gemini(key, models, [{"text": red_prompt}])
    red_team = json_response(text)
    atomic_json(out / "red_team.json", red_team)
    call_audit.append({"stage": "RED_TEAM", "model": model, "video_attachments": 0, "image_attachments": 0, "prompt_sha256": hashlib.sha256(red_prompt.encode()).hexdigest(), "response_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": red_team.get("status")})

    approved = [row for row in red_team.get("approved_queue", []) if isinstance(row, Mapping)]
    alias_to_strategy = {alias: sid for sid, alias in STRATEGIES.items()}
    queue = []
    for row in approved[: int(policy["execution_policy"]["max_active_hypotheses_global"])]:
        alias = str(row.get("strategy_alias") or "")
        queue.append({"strategy_id": alias_to_strategy.get(alias, alias), **dict(row), "authority": "GEMINI_HYPOTHESIS_ONLY", "execution_allowed": False})
    atomic_json(out / "repair_queue.json", {"schema_version": "3.0", "state": "PASS" if queue else "HOLD", "rows": queue, "execution_allowed": False})

    summary = {
        "schema_version": "3.0",
        "pipeline_version": PIPELINE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "state": "PASS" if source_review.get("status") == "PASS" and red_team.get("status") == "PASS" else "HOLD",
        "GEMINI_USED": True,
        "free_only": True,
        "gemini_call_count": len(call_audit),
        "video_analysis_call_count": sum(1 for row in call_audit if row["video_attachments"] > 0),
        "video_attachment_count": sum(int(row["video_attachments"]) for row in call_audit),
        "image_analysis_call_count": sum(1 for row in call_audit if row["image_attachments"] > 0),
        "image_attachment_count": sum(int(row["image_attachments"]) for row in call_audit),
        "public_video_count": len(videos),
        "independent_channel_count": len(channels),
        "literature_count": len(papers),
        "collector_errors": collector_errors,
        "models_used": sorted({row["model"] for row in call_audit}),
        "call_audit": call_audit,
        "approved_hypothesis_count": len(queue),
        "approved_strategies": sorted({row.get("strategy_id") for row in queue}),
        "input_artifact_sha256": stable_sha({"profiles": profiles, "videos": videos, "papers": papers, "prior": sanitize(prior)}),
        "public_urls": [row["url"] for row in videos] + [str(row.get("url") or "") for row in papers if row.get("url")],
        "private_code_sent": False,
        "account_data_sent": False,
        "exchange_credentials_sent": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "execution_allowed": False,
        "next": "CREATE_RESEARCH_DERIVED_SINGLE_CAUSE_CHILD" if queue else "WAIT_NEW_CAUSAL_EVIDENCE",
    }
    atomic_json(out / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
