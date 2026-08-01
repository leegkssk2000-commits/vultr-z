from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URLS = {
    "alimi": "https://alimi.z-os.vip/",
    "view": "https://alimi.z-os.vip/view/",
    "contract": "https://alimi.z-os.vip/api/view_contract_latest.json",
    "tv_observe": "https://alimi.z-os.vip/api/tv/observe",
}
ACTIVE_ROOTS = (
    Path("/var/www/z-os-alimi"),
    Path("/home/z/z/frontend"),
    Path("/home/z/z/backend"),
    Path("/home/z/z"),
)
EXCLUDED_NAMES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".cache",
    ".deploy_backups", "backup", "backups", "rollback", "rollbacks",
    "archive", "archives", "snapshot", "snapshots", "quarantine", "frozen", "freeze",
}
CHART_MARKERS = (
    "TradingView", "tradingview", "lightweight-charts", "createChart",
    "addCandlestickSeries", "candlestick", "/api/tv/observe",
)


def command(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    return p.returncode, p.stdout[-30000:], p.stderr[-5000:]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch(url: str) -> dict[str, Any]:
    p = subprocess.run(
        ["curl", "-L", "--silent", "--show-error", "--max-time", "20",
         "--write-out", "\n__META__%{http_code}|%{content_type}|%{time_total}", url],
        capture_output=True, timeout=30, check=False,
    )
    raw = p.stdout
    marker = b"\n__META__"
    if marker in raw:
        body, meta = raw.rsplit(marker, 1)
    else:
        body, meta = raw, b""
    text = body.decode(errors="replace")
    out: dict[str, Any] = {
        "url": url,
        "returncode": p.returncode,
        "meta": meta.decode(errors="replace"),
        "bytes": len(body),
        "sha256": digest(body),
        "chart_markers": [m for m in CHART_MARKERS if m.lower() in text.lower()],
        "ui_words": {
            word: len(re.findall(rf"\b{re.escape(word)}\b", text, re.I))
            for word in ("unbound", "standby", "pending", "blocked", "hold", "running", "shadow", "paper", "live")
        },
    }
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if title:
        out["title"] = re.sub(r"\s+", " ", title.group(1)).strip()[:160]
    try:
        payload = json.loads(text)
        out["json"] = payload if isinstance(payload, dict) else None
    except Exception:
        out["json"] = None
    return out


def excluded(directory: str) -> bool:
    low = directory.lower()
    return directory in EXCLUDED_NAMES or any(token in low for token in ("backup", "rollback", "archive", "quarantine", "snapshot", "frozen"))


def active_chart_files() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    visited: set[str] = set()
    now = time.time()
    for root in ACTIVE_ROOTS:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not excluded(d)]
            for name in files:
                path = Path(current) / name
                try:
                    resolved = str(path.resolve())
                    if resolved in visited:
                        continue
                    visited.add(resolved)
                    stat = path.stat()
                    if stat.st_size > 4_000_000 or path.suffix.lower() not in {".html", ".js", ".jsx", ".ts", ".tsx", ".css", ".py", ".json"}:
                        continue
                    text = path.read_text(errors="ignore")
                except OSError:
                    continue
                hits = [m for m in CHART_MARKERS if m.lower() in text.lower()]
                if hits:
                    rows.append({
                        "path": str(path), "markers": hits, "bytes": stat.st_size,
                        "age_sec": round(now - stat.st_mtime, 3), "sha256": digest(path.read_bytes()),
                    })
    return sorted(rows, key=lambda r: r["path"])[:200]


def caddy_analysis() -> dict[str, Any]:
    path = Path("/etc/caddy/Caddyfile")
    text = path.read_text(errors="ignore") if path.exists() else ""
    start = text.find("alimi.z-os.vip")
    block = ""
    if start >= 0:
        brace = text.find("{", start)
        depth = 0
        end = len(text)
        for i in range(brace, len(text)):
            if text[i] == "{": depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        block = text[start:end]
    generic = block.find("\n    handle {")
    tv = block.find("handle /api/tv/observe")
    contract = block.find("handle /api/view_contract_latest.json")
    return {
        "path": str(path),
        "exists": path.exists(),
        "alimi_block_sha256": digest(block.encode()) if block else None,
        "view_contract_route_present": contract >= 0,
        "tv_observe_route_present": tv >= 0,
        "generic_handle_index": generic,
        "tv_observe_index": tv,
        "tv_route_shadowed_by_generic_handle": generic >= 0 and tv > generic,
        "excerpt": block[:12000],
    }


def flatten(value: Any, prefix: str = "", depth: int = 0) -> list[tuple[str, Any]]:
    if depth > 6:
        return []
    rows: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(flatten(child, path, depth + 1))
    elif isinstance(value, list):
        rows.append((prefix, f"LIST[{len(value)}]"))
    elif isinstance(value, (str, int, float, bool)) or value is None:
        rows.append((prefix, value))
    return rows


def contract_summary(payload: Any) -> dict[str, Any]:
    rows = flatten(payload) if isinstance(payload, dict) else []
    selected = {}
    modes: set[str] = set()
    for path, value in rows:
        low = path.lower()
        if any(token in low for token in ("mode", "candidate", "status", "state", "closed", "pnl", "writer", "runtime", "paper", "live", "order_authority", "execution_authority", "generated", "updated", "age")):
            selected[path] = value
        if isinstance(value, str) and value.lower() in {"shadow", "paper", "paper_only", "live", "backtest", "disabled"}:
            modes.add(value.lower())
    zero_paths = [path for path, value in rows if value in (0, 0.0, "0", "0R", "0.00%") and any(t in path.lower() for t in ("closed", "pnl", "rows", "writer", "win", "ev"))]
    return {
        "parseable": isinstance(payload, dict),
        "selected": dict(list(selected.items())[:180]),
        "mode_values": sorted(modes),
        "zero_metric_paths": zero_paths[:100],
    }


def systemd_summary() -> list[dict[str, Any]]:
    _, stdout, _ = command(["bash", "-lc", "systemctl list-unit-files --type=service --no-legend | awk '{print $1}' | grep -Ei 'zel|alimi|view|telegram|caddy' | head -n 100"])
    rows = []
    for unit in stdout.splitlines():
        unit = unit.strip()
        if not unit:
            continue
        _, show, _ = command(["systemctl", "show", unit, "--property=Id,ActiveState,SubState,MainPID,NRestarts,ExecStart,FragmentPath,WorkingDirectory"], 10)
        row = {}
        for line in show.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                row[k] = v
        rows.append(row)
    return rows


def main() -> int:
    surfaces = {name: fetch(url) for name, url in URLS.items()}
    files = active_chart_files()
    caddy = caddy_analysis()
    contract = contract_summary(surfaces["contract"].get("json"))
    main_chart = bool(surfaces["alimi"]["chart_markers"])
    view_chart = bool(surfaces["view"]["chart_markers"])
    active_source = bool(files)
    issues = []
    if not main_chart and not view_chart:
        issues.append("TRADINGVIEW_NOT_RENDERED")
    if not active_source:
        issues.append("NO_ACTIVE_TRADINGVIEW_SOURCE_FOUND")
    if caddy["tv_route_shadowed_by_generic_handle"]:
        issues.append("CADDY_TV_OBSERVER_ROUTE_SHADOWED")
    if surfaces["tv_observe"]["meta"].split("|", 1)[0] != "200":
        issues.append("TV_OBSERVER_ENDPOINT_NOT_200")
    if not contract["parseable"]:
        issues.append("VIEW_CONTRACT_NOT_PARSEABLE")
    if contract["zero_metric_paths"]:
        issues.append("ZERO_DISPLAY_METRICS_PRESENT")
    if len(contract["mode_values"]) > 1:
        issues.append("MULTI_MODE_VALUES_REQUIRE_EXPLICIT_SCOPE")

    result = {
        "schema_version": "zel.alimi.view.runtime.audit.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": "PASS_READ_ONLY_AUDIT_COMPLETE",
        "surfaces": {name: {k: v for k, v in data.items() if k != "json"} for name, data in surfaces.items()},
        "contract": contract,
        "active_chart_files": files,
        "caddy": caddy,
        "systemd": systemd_summary(),
        "findings": {
            "issues": issues,
            "issue_count": len(issues),
            "tradingview_live_main": main_chart,
            "tradingview_live_view": view_chart,
            "active_tradingview_source_present": active_source,
        },
        "safety": {
            "read_only": True, "runtime_mutated": False, "frontend_mutated": False,
            "service_mutated": False, "canonical_mutated": False,
            "execution_authority": "NONE", "order_authority": "BLOCKED", "action": "hold",
        },
    }
    out = Path("/tmp/zel_alimi_view_runtime_audit_v2.json")
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["findings"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
