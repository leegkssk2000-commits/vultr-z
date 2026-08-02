from __future__ import annotations

from pathlib import Path

PATH = Path("backend/tools/zel_strategy_loss_attribution_gemini_v1.py")
text = PATH.read_text(encoding="utf-8")

old = "import os\nimport statistics\n"
new = "import os\nimport re\nimport statistics\n"
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)

start = text.index("def call_gemini(\n")
end = text.index("\ndef global_prompt(", start)
replacement = r'''def list_gemini_models(api_key: str, preferred: Sequence[str]) -> list[str]:
    request = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": api_key},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    eligible = [
        str(row["name"])
        for row in payload.get("models", [])
        if row.get("name") and "generateContent" in row.get("supportedGenerationMethods", [])
    ]
    ordered = [model for model in preferred if model in eligible]
    ordered.extend(
        model
        for model in eligible
        if model not in ordered and "flash" in model.lower()
    )
    return ordered


def retry_delay_seconds(detail: str) -> float:
    matches = re.findall(r'"retryDelay"\s*:\s*"([0-9.]+)s"', detail)
    if not matches:
        return 0.0
    return max(float(value) for value in matches)


def call_gemini(
    api_key: str,
    models: Sequence[str],
    prompt: str,
    max_output_tokens: int,
    temperature: float,
) -> tuple[str, dict[str, Any]]:
    available = list_gemini_models(api_key, models)
    if not available:
        raise RuntimeError("NO_ELIGIBLE_GEMINI_FLASH_MODEL")
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": max_output_tokens,
                "temperature": temperature,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }
    ).encode("utf-8")
    errors: list[str] = []
    permanently_unavailable: set[str] = set()
    for attempt in range(3):
        retry_after = 0.0
        attempted = 0
        for model in available:
            if model in permanently_unavailable:
                continue
            attempted += 1
            try:
                request = urllib.request.Request(
                    f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent",
                    data=body,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=900) as response:
                    generated = json.load(response)
                return model, parse_json_response(parse_gemini_text(generated))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:2000]
                errors.append(f"{model}:HTTP_{exc.code}:{detail[:800]}")
                retry_after = max(retry_after, retry_delay_seconds(detail))
                if exc.code in {400, 404} or '"limit": "0"' in detail:
                    permanently_unavailable.add(model)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{model}:{type(exc).__name__}:{exc}")
        if attempt < 2 and attempted:
            time.sleep(min(75.0, max(8.0 * (attempt + 1), retry_after + 2.0)))
    raise RuntimeError("GEMINI_ALL_MODELS_FAILED:" + "|".join(errors[-16:]))


def metric_slice(value: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "trade_count",
        "net_R",
        "gross_loss_R",
        "profit_factor",
        "max_drawdown_R",
        "win_rate_pct",
        "average_MFE_R",
        "average_MAE_R",
        "average_exposure_min",
    )
    return {key: value.get(key) for key in keys}


def top_metric_groups(groups: Mapping[str, Any], limit: int = 4) -> dict[str, Any]:
    ranked = sorted(
        (
            (str(name), value)
            for name, value in groups.items()
            if isinstance(value, Mapping)
        ),
        key=lambda item: float(item[1].get("gross_loss_R") or 0.0),
        reverse=True,
    )
    return {name: metric_slice(value) for name, value in ranked[:limit]}


def compact_filter_screen(screen: Mapping[str, Any]) -> dict[str, Any]:
    candidates = []
    for row in screen.get("candidates", []):
        if not isinstance(row, Mapping) or row.get("state") != "PASS_NONOVERLAP_FILTER_CANDIDATE":
            continue
        windows: dict[str, Any] = {}
        for window, evidence in (row.get("window_evaluations") or {}).items():
            if not isinstance(evidence, Mapping) or evidence.get("state") != "PASS_EVALUATED":
                continue
            delta = evidence.get("delta") or {}
            windows[str(window)] = {
                "delta_net_R": delta.get("delta_net_R"),
                "delta_max_drawdown_R": delta.get("delta_max_drawdown_R"),
                "delta_profit_factor": delta.get("delta_profit_factor"),
                "trade_retention_pct": delta.get("trade_retention_pct"),
            }
        candidates.append(
            {
                "axis": row.get("axis"),
                "excluded_value": row.get("excluded_value"),
                "selection_delta": row.get("selection_delta"),
                "windows": windows,
            }
        )
        if len(candidates) >= 4:
            break
    return {
        "selection_window": screen.get("selection_window"),
        "oos_pass_count": screen.get("oos_pass_count"),
        "top_oos_candidates": candidates,
    }


def compact_profile(strategy: Mapping[str, Any]) -> dict[str, Any]:
    clusters = strategy.get("loss_clusters") or {}
    ranked_clusters = sorted(
        (
            (str(name), value)
            for name, value in clusters.items()
            if isinstance(value, Mapping)
        ),
        key=lambda item: float(item[1].get("gross_loss_R") or 0.0),
        reverse=True,
    )[:5]
    return {
        "alias": strategy["alias"],
        "overall": metric_slice(strategy["overall"]),
        "by_window": {
            str(name): metric_slice(value)
            for name, value in strategy["by_window"].items()
            if isinstance(value, Mapping)
        },
        "top_symbols": top_metric_groups(strategy["by_symbol"]),
        "by_side": top_metric_groups(strategy["by_side"], limit=3),
        "by_regime": top_metric_groups(strategy["by_regime"], limit=4),
        "by_hour_bucket": top_metric_groups(strategy["by_hour_bucket"], limit=4),
        "chronological_quartiles": {
            str(name): metric_slice(value)
            for name, value in strategy["chronological_quartiles"].items()
            if isinstance(value, Mapping)
        },
        "top_loss_clusters": {name: value for name, value in ranked_clusters},
        "filter_screen": compact_filter_screen(strategy["filter_screen"]),
        "loss_contribution_pct": strategy["loss_contribution_pct"],
        "net_loss_contribution_pct": strategy["net_loss_contribution_pct"],
    }

'''
text = text[:start] + replacement + text[end:]

PATH.write_text(text, encoding="utf-8")
print("PASS_CURRENT_GEMINI_ROUTER_AND_COMPACT_PAYLOAD_PATCH")
