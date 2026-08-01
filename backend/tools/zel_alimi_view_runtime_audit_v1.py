from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PUBLIC_URLS = (
    "https://alimi.z-os.vip/",
    "https://alimi.z-os.vip/view/",
    "https://alimi.z-os.vip/api/view_contract_latest.json",
)
WEB_ROOTS = (
    Path("/var/www/z-os-alimi"),
    Path("/var/www/z-os-app"),
    Path("/var/www/z-os-web"),
    Path("/home/z/z/frontend"),
    Path("/home/z/z"),
)
MARKERS = (
    "TradingView",
    "tradingview",
    "lightweight-charts",
    "createChart",
    "addCandlestickSeries",
    "candlestick",
    "view_contract_latest.json",
    "shadow_aggregate_snapshot",
)


def run(command: list[str], timeout: int = 20) -> dict[str, Any]:
    completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-20000:],
        "stderr": completed.stderr[-4000:],
    }


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def curl_snapshot(url: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["curl", "-L", "--silent", "--show-error", "--max-time", "20", "--write-out", "\n__HTTP__%{http_code} %{content_type} %{time_total}", url],
        text=False,
        capture_output=True,
        timeout=30,
        check=False,
    )
    raw = completed.stdout
    marker = b"\n__HTTP__"
    body, meta = (raw.rsplit(marker, 1) + [b""])[:2] if marker in raw else (raw, b"")
    text = body.decode("utf-8", errors="replace")
    result: dict[str, Any] = {
        "url": url,
        "returncode": completed.returncode,
        "meta": meta.decode(errors="replace").strip(),
        "bytes": len(body),
        "sha256": sha256(body),
        "marker_hits": {m: (m.lower() in text.lower()) for m in MARKERS},
        "title": None,
        "json_state": None,
        "json_keys": [],
    }
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if title:
        result["title"] = re.sub(r"\s+", " ", title.group(1)).strip()[:200]
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            result["json_state"] = payload.get("state") or payload.get("status") or payload.get("mode")
            result["json_keys"] = sorted(payload.keys())[:200]
            result["json_summary"] = {
                key: payload.get(key)
                for key in (
                    "state", "status", "mode", "runtime_active", "paper_enabled", "live_enabled",
                    "order_authority", "execution_authority", "closed_count", "closed", "pnl_r",
                    "rows", "candidate", "writer_count", "configured_writers", "active_writers",
                    "generated_at", "updated_at", "timestamp", "age_ms", "age_sec",
                )
                if key in payload
            }
    except Exception:
        pass
    return result


def file_inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = time.time()
    for root in WEB_ROOTS:
        if not root.exists():
            continue
        count = 0
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "venv", "__pycache__", "backup", "backups"}]
            for name in files:
                if count >= 4000:
                    break
                path = Path(current) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size > 5_000_000:
                    continue
                suffix = path.suffix.lower()
                if suffix not in {".html", ".js", ".css", ".json", ".py", ".conf", ".service", ".yml", ".yaml"}:
                    continue
                try:
                    text = path.read_text(errors="ignore")
                except OSError:
                    continue
                hits = [m for m in MARKERS if m.lower() in text.lower()]
                if hits:
                    rows.append({
                        "path": str(path),
                        "bytes": stat.st_size,
                        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                        "age_sec": round(now - stat.st_mtime, 3),
                        "markers": hits,
                        "sha256": sha256(path.read_bytes()),
                    })
                count += 1
            if count >= 4000:
                break
    rows.sort(key=lambda row: row["path"])
    return rows[:500]


def systemd_inventory() -> list[dict[str, Any]]:
    names = run(["bash", "-lc", "systemctl list-unit-files --type=service --no-legend | awk '{print $1}' | grep -Ei 'zel|alimi|view|telegram|caddy' | head -n 120"])["stdout"].splitlines()
    rows = []
    for name in names:
        name = name.strip()
        if not name:
            continue
        show = run(["systemctl", "show", name, "--property=Id,ActiveState,SubState,MainPID,NRestarts,ExecStart,FragmentPath,WorkingDirectory"], timeout=10)
        props = {}
        for line in show["stdout"].splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        rows.append(props)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    public = [curl_snapshot(url) for url in PUBLIC_URLS]
    files = file_inventory()
    systemd = systemd_inventory()
    processes = run(["bash", "-lc", "ps -eo pid,lstart,cmd --sort=pid | grep -Ei 'zel|alimi|view|telegram|caddy|gunicorn|uvicorn' | grep -v grep | head -n 200"])
    listeners = run(["bash", "-lc", "ss -ltnp 2>/dev/null | head -n 200"])
    caddy = run(["bash", "-lc", "test -f /etc/caddy/Caddyfile && sed -n '1,260p' /etc/caddy/Caddyfile || true"])

    view = next((item for item in public if item["url"].endswith("view_contract_latest.json")), {})
    html_pages = [item for item in public if not item["url"].endswith(".json")]
    tradingview_live = any(
        item.get("marker_hits", {}).get("TradingView")
        or item.get("marker_hits", {}).get("tradingview")
        or item.get("marker_hits", {}).get("lightweight-charts")
        or item.get("marker_hits", {}).get("createChart")
        for item in html_pages
    )
    tradingview_source = any(
        any(marker in row["markers"] for marker in ("TradingView", "tradingview", "lightweight-charts", "createChart", "addCandlestickSeries"))
        for row in files
    )
    unbound_surface = False
    zero_surface = False
    stale_surface = False
    for item in public:
        if item.get("bytes", 0) == 0 or not str(item.get("meta", "")).startswith("200"):
            unbound_surface = True
        summary = item.get("json_summary") or {}
        if summary.get("closed_count") == 0 or summary.get("closed") == 0 or summary.get("rows") == 0:
            zero_surface = True
        for key in ("age_ms", "age_sec"):
            value = summary.get(key)
            if isinstance(value, (int, float)) and value > (300_000 if key == "age_ms" else 300):
                stale_surface = True

    issues = []
    if not tradingview_live:
        issues.append("TRADINGVIEW_NOT_RENDERED_ON_LIVE_SURFACE")
    if tradingview_source and not tradingview_live:
        issues.append("TRADINGVIEW_SOURCE_PRESENT_BUT_NOT_DEPLOYED_OR_NOT_BOUND")
    if unbound_surface:
        issues.append("PUBLIC_ENDPOINT_OR_BODY_UNAVAILABLE")
    if zero_surface:
        issues.append("ZERO_OR_EMPTY_DISPLAY_STATE_PRESENT")
    if stale_surface:
        issues.append("DISPLAY_STALE_OVER_300S")
    if not view.get("json_keys"):
        issues.append("VIEW_CONTRACT_NOT_PARSEABLE_JSON")

    output = {
        "schema_version": "zel.alimi.view.runtime.audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_READ_ONLY_AUDIT_COMPLETE",
        "read_only": True,
        "public_surfaces": public,
        "deployed_marker_files": files,
        "systemd": systemd,
        "processes": processes["stdout"],
        "listeners": listeners["stdout"],
        "caddy_excerpt": caddy["stdout"],
        "findings": {
            "tradingview_live": tradingview_live,
            "tradingview_source_present": tradingview_source,
            "issue_count": len(issues),
            "issues": issues,
        },
        "safety": {
            "runtime_mutated": False,
            "service_mutated": False,
            "frontend_mutated": False,
            "canonical_mutated": False,
            "paper_enabled": False,
            "live_enabled": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        },
    }
    Path(args.out).write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"state": output["state"], "issues": issues, "tradingview_live": tradingview_live, "tradingview_source_present": tradingview_source}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
