from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_ALIMI_BINDING_READ_ONLY_AUDIT_V2"
OUTPUT = Path("/tmp/zel_alimi_binding_read_only_audit_v2.json")
STATIC_ROOTS = (
    Path("/var/www"),
    Path("/srv/www"),
    Path("/opt/z-os-alimi"),
    Path("/home/z/z/frontend"),
    Path("/home/z/z/web"),
    Path("/home/z/z/alimi"),
    Path("/home/z/z/backend"),
)
CONFIG_PATHS = (
    Path("/etc/caddy/Caddyfile"),
    Path("/etc/nginx/nginx.conf"),
)
CONFIG_GLOBS = (
    "/etc/nginx/sites-enabled/*",
    "/etc/nginx/conf.d/*",
)
EXCLUDED = {".git", "node_modules", "__pycache__", "backup", "backups", "archive", "archives", "quarantine"}
TOKENS = (
    "ZEL", "ALIMI", "STRATEGY QUEUE", "ZEL CONTROL", "PERFORMANCE EDGE",
    "RUNTIME STATUS", "WRITERS", "NEXT POSITION",
)
COMPONENTS = {
    "queue": ("STRATEGY QUEUE", "QUEUE"),
    "lico": ("LICO",),
    "team_bots": ("LBOT", "MBOT", "OBOT", "SBOT"),
    "zbot": ("ZBOT",),
    "zico": ("ZICO",),
    "zlice": ("ZLICE",),
    "performance": ("PERFORMANCE", "WIN RATE", "WINRATE"),
    "rank": ("RANK", "RANKING"),
    "recent_trace": ("RECENT", "TRACE", "LEDGER"),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_run(args: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        completed = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-4000:],
        }
    except Exception as exc:
        return {"returncode": None, "error": f"{type(exc).__name__}:{exc}"}


def config_files() -> list[Path]:
    rows = [path for path in CONFIG_PATHS if path.is_file()]
    import glob
    for pattern in CONFIG_GLOBS:
        rows.extend(Path(item) for item in glob.glob(pattern) if Path(item).is_file())
    return sorted(set(rows))


def roots_from_config() -> tuple[list[Path], list[dict[str, Any]]]:
    roots: list[Path] = []
    evidence: list[dict[str, Any]] = []
    for path in config_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            evidence.append({"config_sha256": sha_text(str(path)), "error": type(exc).__name__})
            continue
        candidates = []
        for pattern in (
            r"(?m)^\s*root\s+\*?\s*(/[A-Za-z0-9._/-]+)",
            r"(?m)^\s*root\s+(?:html\s+)?(/[A-Za-z0-9._/-]+)",
        ):
            candidates.extend(re.findall(pattern, text))
        accepted = []
        for value in candidates:
            root = Path(value)
            if value.startswith(("/var/www", "/srv", "/opt", "/home/z")):
                roots.append(root)
                accepted.append(sha_text(str(root.resolve(strict=False))))
        evidence.append({
            "config_sha256": sha_text(str(path)),
            "accepted_root_sha256": sorted(set(accepted)),
        })
    return sorted(set(roots)), evidence


def candidate_score(path: Path, text: str) -> tuple[int, list[str]]:
    upper = text.upper()
    matched = [token for token in TOKENS if token in upper]
    score = len(matched) * 10
    name = path.name.lower()
    if name in {"index.html", "alimi.html", "view.html"}:
        score += 5
    if "alimi" in str(path).lower():
        score += 5
    return score, matched


def discover_html(max_files: int = 20000, max_bytes: int = 3_000_000) -> dict[str, Any]:
    dynamic_roots, config_evidence = roots_from_config()
    roots = []
    for root in [*dynamic_roots, *STATIC_ROOTS]:
        resolved = root.resolve(strict=False)
        if resolved not in roots and root.is_dir():
            roots.append(resolved)
    scanned = 0
    candidates: list[dict[str, Any]] = []
    for root in roots:
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in EXCLUDED and not name.startswith(".")]
            for name in files:
                if scanned >= max_files:
                    break
                if not name.lower().endswith((".html", ".htm")):
                    continue
                scanned += 1
                path = Path(current) / name
                try:
                    size = path.stat().st_size
                    if size <= 0 or size > max_bytes:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                score, matched = candidate_score(path, text)
                if score >= 20:
                    candidates.append({
                        "path": str(path),
                        "path_sha256": sha_text(str(path.resolve(strict=False))),
                        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "size_bytes": size,
                        "score": score,
                        "matched_tokens": matched,
                        "text": text,
                    })
            if scanned >= max_files:
                break
        if scanned >= max_files:
            break
    candidates.sort(key=lambda row: (-row["score"], row["path"]))
    return {
        "roots_scanned_sha256": [sha_text(str(root)) for root in roots],
        "config_evidence": config_evidence,
        "scanned_html_files": scanned,
        "scan_limit_reached": scanned >= max_files,
        "candidates": candidates,
    }


def component_states(text: str | None) -> dict[str, dict[str, Any]]:
    if text is None:
        return {
            name: {"state": "UNPROVED_NO_ACTIVE_HTML", "matched": []}
            for name in COMPONENTS
        }
    upper = text.upper()
    result: dict[str, dict[str, Any]] = {}
    for name, tokens in COMPONENTS.items():
        matched = [token for token in tokens if token in upper]
        result[name] = {
            "state": "PRESENT_SOURCE_SURFACE" if matched else "MISSING_FROM_ACTIVE_HTML",
            "matched": matched,
        }
    return result


def audit() -> dict[str, Any]:
    discovery = discover_html()
    candidates = discovery.pop("candidates")
    active = candidates[0] if candidates else None
    text = active.pop("text") if active else None
    endpoint = safe_run([
        "curl", "-fsSL", "--max-time", "8", "-o", "/dev/null", "-w", "%{http_code}",
        "https://alimi.z-os.vip/",
    ])
    services = safe_run([
        "systemctl", "list-units", "--type=service", "--all", "--no-pager", "--plain",
        "--no-legend",
    ])
    timers = safe_run([
        "systemctl", "list-timers", "--all", "--no-pager", "--plain", "--no-legend",
    ])
    if active:
        state = "PASS_READ_ONLY_ALIMI_BINDING_AUDIT_V2"
        errors: list[str] = []
        active_html = {key: value for key, value in active.items() if key != "path"}
        active_html["path_disclosed"] = False
    else:
        state = "HOLD_ACTIVE_ALIMI_HTML_NOT_FOUND"
        errors = ["ACTIVE_ALIMI_HTML_NOT_FOUND"]
        active_html = None
    return {
        "schema_version": "zel.alimi.binding_read_only_audit.v2",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "active_html": active_html,
        "discovery": discovery,
        "candidate_count": len(candidates),
        "components": component_states(text),
        "public_endpoint": {
            "http_code": (endpoint.get("stdout") or "").strip(),
            "returncode": endpoint.get("returncode"),
            "reachable": endpoint.get("returncode") == 0,
        },
        "service_inventory": {
            "returncode": services.get("returncode"),
            "alimi_lines_sha256": sha_text("\n".join(
                line for line in (services.get("stdout") or "").splitlines()
                if any(token in line.lower() for token in ("alimi", "zel", "z-os"))
            )),
        },
        "timer_inventory": {
            "returncode": timers.get("returncode"),
            "alimi_lines_sha256": sha_text("\n".join(
                line for line in (timers.get("stdout") or "").splitlines()
                if any(token in line.lower() for token in ("alimi", "zel", "z-os"))
            )),
        },
        "policy": {
            "account_balance_semantics": "REAL_BINGX_LIVE_ACCOUNT_BALANCE_READ_ONLY",
            "view_mutation_allowed": False,
            "frontend_mutation_allowed": False,
        },
        "errors": errors,
        "safety": {
            "read_only": True,
            "frontend_mutated": False,
            "view_mutated": False,
            "runtime_mutated": False,
            "service_mutated": False,
            "canonical_strategy_mutated": False,
            "formal_ledger_mutated": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        },
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def main() -> int:
    payload = audit()
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "candidate_count": payload["candidate_count"],
        "errors": payload["errors"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
