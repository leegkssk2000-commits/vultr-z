#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v5 = load("r73b4_v5", HERE / "q4r3_exact25_r73b4_readonly_display_parity_smoke_v5.py")
base = v5.base
collector = v5.collector
metrics = base.metrics
discovery = base.discovery
DIAGNOSTICS: dict[str, Any] = {}


def metric_score(text: str) -> int:
    parsed = metrics.text_metrics(text)
    return sum(key in parsed for key in ("closed_count", "winrate_pct", "total_r", "latest_trace_id"))


def fetch_url(url: str) -> tuple[str, str]:
    command = ["curl", "-fsSL", "--max-time", "3"]
    if "127.0.0.1" in url or "localhost" in url:
        command.extend(["-H", "Host: alimi.vip"])
    try:
        result = subprocess.run(command + [url], text=True, capture_output=True, check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", type(exc).__name__
    if result.returncode == 0 and result.stdout:
        return result.stdout[:collector.MAX_BYTES], ""
    return "", f"curl={result.returncode}"


def local_http_bases() -> list[str]:
    try:
        result = subprocess.run(["ss", "-ltnH"], text=True, capture_output=True, check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    ports: list[int] = []
    for match in re.findall(r"(?:127\.0\.0\.1|0\.0\.0\.0|\*|\[::\]):([0-9]{2,5})", result.stdout):
        port = int(match)
        if port in {80, 443, 2019} or port in ports:
            continue
        ports.append(port)
    preferred = [port for port in (8000, 8787, 8792, 8799) if port in ports]
    preferred.extend(port for port in ports if port not in preferred)
    return [f"http://127.0.0.1:{port}" for port in preferred[:8]]


def endpoint_candidates(page_url: str, page_text: str) -> tuple[list[str], list[str]]:
    parsed = urlparse(page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    assets: list[str] = []
    endpoints: list[str] = []

    for value in re.findall(r"(?:src|href)=[\"']([^\"']+)[\"']", page_text, flags=re.I):
        absolute = urljoin(page_url, value)
        if absolute not in assets and re.search(r"\.(?:js|json)(?:\?|$)", absolute, flags=re.I):
            assets.append(absolute)

    def add_endpoint(value: str, base_url: str) -> None:
        if not value or value.startswith(("javascript:", "data:")):
            return
        absolute = urljoin(base_url, value)
        if absolute not in endpoints:
            endpoints.append(absolute)

    route_pattern = r"[\"']((?:https?://[^\"']+|/[^\"']*)(?:api|view|status|summary|pnl|closed|truth|shadow|ledger)[^\"']*)[\"']"
    for value in re.findall(route_pattern, page_text, flags=re.I):
        add_endpoint(value, page_url)

    for asset in assets[:20]:
        text, _ = fetch_url(asset)
        if not text:
            continue
        for value in re.findall(route_pattern, text, flags=re.I):
            add_endpoint(value, asset)
        for value in re.findall(r"(?:fetch|axios\.(?:get|post))\s*\(\s*[\"']([^\"']+)[\"']", text, flags=re.I):
            add_endpoint(value, asset)

    common = (
        "/api/view", "/api/status", "/api/summary", "/api/shadow",
        "/api/pnl", "/api/closed", "/api/truth", "/view.json", "/status.json",
    )
    bases = ([origin] if origin else []) + local_http_bases()
    for base_url in bases:
        for route in common:
            add_endpoint(base_url + route, base_url + "/")
    return assets, endpoints


def resolve_view(urls: list[str]) -> tuple[str, str, list[str]]:
    page_url, page_text, errors = v5.fetch_view(urls)
    attempts: list[dict[str, Any]] = []
    if page_url and metric_score(page_text) >= 3:
        DIAGNOSTICS.update({"view_binding_mode": "DIRECT_METRIC_PAGE", "view_metric_source": page_url})
        return page_url, page_text, errors

    assets: list[str] = []
    endpoints: list[str] = []
    if page_url and page_text:
        assets, endpoints = endpoint_candidates(page_url, page_text)
    best: tuple[int, str, str] = (0, "", "")
    for endpoint in endpoints[:60]:
        text, error = fetch_url(endpoint)
        score = metric_score(text) if text else 0
        attempts.append({"url": endpoint, "score": score, "error": error})
        if score > best[0]:
            best = (score, endpoint, text)
        if score == 4:
            break
    DIAGNOSTICS.update({
        "view_binding_mode": "DISCOVERED_METRIC_ENDPOINT" if best[0] >= 3 else "METRIC_SOURCE_UNRESOLVED",
        "view_page_url": page_url,
        "view_asset_urls": assets[:20],
        "view_endpoint_attempts": attempts[:60],
        "view_metric_source": best[1],
    })
    if best[0] >= 3:
        return best[1], best[2], errors
    return page_url, page_text, errors


def choose_composite_artifact(source_text: str, ledger: Path) -> tuple[str, str, int]:
    context = base.CONTEXTS.get(base.TELEGRAM_UNIT, {})
    info = context.get("info", {}) if isinstance(context.get("info"), dict) else {}
    combined = str(context.get("combined", source_text))
    env = context.get("environment", {}) if isinstance(context.get("environment"), dict) else {}
    working_value = str(info.get("working_directory", ""))
    working = Path(working_value) if working_value.startswith("/") else None
    source = context.get("source") if isinstance(context.get("source"), Path) else None
    paths = discovery.candidate_paths(
        combined, root=Path("/home/z/z"), working_directory=working,
        source_parent=source.parent if source else None, env=env,
    )
    rows: list[tuple[int, int, Path, dict[str, Any]]] = []
    for path in paths:
        if path == ledger:
            continue
        text = collector.read_small(path)
        parsed = metrics.text_metrics(text) if text else {}
        if not parsed:
            continue
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = 0
        rows.append((len(parsed), mtime, path, parsed))

    selected: dict[str, tuple[int, int, str, Any]] = {}
    for score, mtime, path, parsed in rows:
        for key, value in parsed.items():
            candidate = (mtime, score, str(path), value)
            if key not in selected or candidate[:2] > selected[key][:2]:
                selected[key] = candidate
    merged = {key: value[3] for key, value in selected.items()}
    used_paths = sorted({value[2] for value in selected.values()})
    complete = all(key in merged for key in ("closed_count", "winrate_pct", "total_r", "latest_trace_id"))
    explicit_ledger = discovery.explicit_ledger_binding(combined, ledger)
    DIAGNOSTICS.update({
        "telegram_binding_mode": "COMPOSITE_REFERENCED_ARTIFACTS" if complete else ("DIRECT_LEDGER" if explicit_ledger else "UNRESOLVED"),
        "telegram_candidate_paths": [str(path) for path in paths[:100]],
        "telegram_metric_paths": used_paths,
        "telegram_merged_metrics": merged,
        "telegram_explicit_ledger_binding": explicit_ledger,
        "telegram_view_fallback_forbidden": True,
    })
    if complete:
        return "COMPOSITE:" + "|".join(used_paths), json.dumps(merged, sort_keys=True), len(rows)
    if explicit_ledger:
        canonical = metrics.ledger_metrics(ledger)
        return "DIRECT_LEDGER:" + str(ledger), json.dumps(canonical, sort_keys=True), 1
    return "", "", len(rows)


def output_path() -> Path | None:
    try:
        return Path(sys.argv[sys.argv.index("--output") + 1])
    except (ValueError, IndexError):
        return None


collector.fetch_view = resolve_view
collector.choose_artifact = choose_composite_artifact


if __name__ == "__main__":
    result = int(collector.main())
    path = output_path()
    if path and path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        inherited = payload.get("binding_discovery", {})
        if isinstance(inherited, dict):
            inherited.update(DIAGNOSTICS)
            payload["binding_discovery"] = inherited
        else:
            payload["binding_discovery"] = DIAGNOSTICS
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    raise SystemExit(result)
