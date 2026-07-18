#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

RENDER_TERMS = (
    "last_close", "recent_rows", "last12", "winrate", "wr", "ev",
    "status_path", "source_path", "telegram_status_latest.json", "/pos"
)
VIEW_TERMS = (
    "WRITERS 7", "writer_count", "configured_writer_count", "active_writer_count",
    "writer_registry", "writers", "team lane", "q4r3_shadow_closed_ledger_latest.json"
)
STALE_VALUE_TOKENS = (
    "53.613052", "7.25", "37.209", "0.459302", "SL_TOUCH_CLOSED",
    "q4r3_shadow_closed_ledger_latest.json"
)


def run(command: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return payload


def fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    probe = f"{url}{'&' if '?' in url else '?'}r73b4u2={time.time_ns()}"
    command = [
        "curl", "-sS", "-L", "--max-time", "15",
        "-H", "Cache-Control: no-cache", "-w", "\n%{http_code}"
    ]
    if url.startswith("https://alimi.z-os.vip/"):
        command.extend(["--resolve", "alimi.z-os.vip:443:127.0.0.1"])
    command.append(probe)
    result = run(command)
    body, _, raw_code = result.stdout.rpartition("\n")
    try:
        code = int(raw_code or 0)
    except ValueError:
        code = 0
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}
    return code, payload if isinstance(payload, dict) else {}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)
    path.chmod(0o644)


def numbered_hits(text: str, terms: tuple[str, ...], context: int = 1) -> list[dict[str, Any]]:
    lines = text.splitlines()
    hit_lines: set[int] = set()
    lowered_terms = tuple(term.lower() for term in terms)
    for index, line in enumerate(lines, start=1):
        low = line.lower()
        if any(term in low for term in lowered_terms):
            for target in range(max(1, index - context), min(len(lines), index + context) + 1):
                hit_lines.add(target)
    return [{"line": line_no, "text": lines[line_no - 1][:500]} for line_no in sorted(hit_lines)]


def json_path_literals(text: str) -> list[str]:
    values = re.findall(r"['\"]([^'\"]+\.json(?:l)?)['\"]", text)
    return sorted(dict.fromkeys(values))


def exec_source(unit: str, fallback: Path) -> tuple[Path, str, str]:
    show = run(["systemctl", "show", unit, "-p", "ExecStart", "-p", "FragmentPath", "-p", "MainPID"])
    raw = show.stdout
    candidates: list[Path] = []
    for token in re.findall(r"(?:path=)?(/[^ ;{}]+\.py)", raw):
        candidates.append(Path(token))
    for line in raw.splitlines():
        if line.startswith("ExecStart="):
            try:
                for token in shlex.split(line.split("=", 1)[1]):
                    if token.startswith("/") and token.endswith(".py"):
                        candidates.append(Path(token))
            except ValueError:
                pass
    candidates.append(fallback)
    for path in candidates:
        if path.is_file():
            return path, raw, sha256(path)
    return fallback, raw, "missing"


def metric(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def writer_map(payload: dict[str, Any]) -> dict[str, str]:
    rows = payload.get("writers")
    if not isinstance(rows, list):
        rows = payload.get("writer_registry")
    result: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                result[str(row.get("writer_id", ""))] = str(row.get("strategy", ""))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(args.contract)
    parent_path = Path(contract["parent_status"])
    telegram_artifact_path = Path(contract["canonical_telegram_artifact"])
    view_index = Path(contract["view_index"])
    telegram_fallback = Path(contract["telegram_source_fallback"])
    unit = str(contract["telegram_unit"])

    blockers: list[str] = []
    warnings: list[str] = []
    if not parent_path.is_file():
        blockers.append("PARENT_STATUS_MISSING")
    if not telegram_artifact_path.is_file():
        blockers.append("CANONICAL_TELEGRAM_ARTIFACT_MISSING")
    if blockers:
        payload = {"state": "HOLD", "blockers": blockers, "blocker_count": len(blockers), "mutation_count": 0}
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2

    parent = read_json(parent_path)
    telegram_artifact = read_json(telegram_artifact_path)
    endpoint_code, endpoint = fetch_json(str(contract["canonical_alimi_endpoint"]))
    source_path, unit_show, source_sha = exec_source(unit, telegram_fallback)
    source_found = source_path.is_file()
    source_text = source_path.read_text(encoding="utf-8", errors="replace") if source_found else ""
    view_found = view_index.is_file()
    view_text = view_index.read_text(encoding="utf-8", errors="replace") if view_found else ""

    if parent.get("state") != "PASS" or parent.get("rollback_performed") is not False:
        blockers.append("B4U_PARENT_NOT_STABLE_PASS")
    canonical_closed = int(metric(telegram_artifact, "closed_count", "closed", default=-1))
    canonical_recent_rows = int(metric(telegram_artifact, "recent_rows", "rows", default=-1))
    canonical_pnl = float(metric(telegram_artifact, "pnl_r", "net_r", default=-1.0))
    canonical_writer_count = int(metric(telegram_artifact, "writer_count", "configured_writer_count", default=-1))
    canonical_active_writer_count = int(metric(telegram_artifact, "active_writer_count", default=-1))
    expected_writer_map = {str(k): str(v) for k, v in contract["expected_writer_registry"].items()}
    actual_writer_map = writer_map(telegram_artifact)

    if (canonical_closed, canonical_recent_rows, canonical_pnl) != (0, 0, 0.0):
        blockers.append("CANONICAL_TELEGRAM_ARTIFACT_NOT_ZERO")
    if canonical_writer_count != 7 or canonical_active_writer_count != 0 or actual_writer_map != expected_writer_map:
        blockers.append("CANONICAL_WRITERS7_INVALID")
    if not source_found:
        blockers.append("TELEGRAM_SOURCE_NOT_FOUND")
    if not view_found:
        blockers.append("VIEW_INDEX_NOT_FOUND")
    if endpoint_code != 200:
        warnings.append(f"ALIMI_ENDPOINT_HTTP_{endpoint_code}")

    source_hits = numbered_hits(source_text, RENDER_TERMS, context=2)
    view_hits = numbered_hits(view_text, VIEW_TERMS, context=2)
    source_json_paths = json_path_literals(source_text)
    canonical_path = str(telegram_artifact_path)
    secondary_json_paths = [path for path in source_json_paths if path != canonical_path]
    stale_literal_hits = [token for token in STALE_VALUE_TOKENS if token.lower() in source_text.lower()]
    fallback_expression_count = len(re.findall(r"\.get\([^\n]+\bor\b|\bor\s+[^\n]+\.get\(", source_text))
    render_term_count = sum(source_text.lower().count(term.lower()) for term in RENDER_TERMS)

    telegram_split_source_suspected = bool(
        render_term_count and (
            secondary_json_paths or fallback_expression_count or
            any("last_close" in item["text"].lower() for item in source_hits)
        )
    )
    view_registry_binding_present = "writer_registry" in view_text or re.search(r"\bwriters\b", view_text, re.I) is not None
    view_uses_flat_writer_count = "writer_count" in view_text
    view_projection_gap = view_uses_flat_writer_count and not view_registry_binding_present
    view_legacy_ledger_label = "q4r3_shadow_closed_ledger_latest.json" in view_text

    if render_term_count == 0:
        blockers.append("TELEGRAM_RENDER_TERMS_NOT_FOUND")
    if not telegram_split_source_suspected:
        warnings.append("SPLIT_SOURCE_NOT_PROVEN_FROM_STATIC_SOURCE")
    if not view_projection_gap:
        warnings.append("VIEW_WRITERS7_GAP_NOT_PROVEN_FROM_STATIC_SOURCE")

    next_stages: list[str] = []
    if telegram_split_source_suspected:
        next_stages.append(contract["next_stage_on_split_source"])
    if view_projection_gap or view_legacy_ledger_label:
        next_stages.append(contract["next_stage_on_view_projection_gap"])
    if not next_stages:
        next_stages.append("R7.3B4U2_RUNTIME_MESSAGE_CAPTURE_REQUIRED")

    payload = {
        "schema": "q4r3_exact25_r73b4u2_rendered_surface_diagnosis_status_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "warnings": warnings,
        "warning_count": len(warnings),
        "mutation_count": 0,
        "parent_state": parent.get("state"),
        "parent_rollback_performed": parent.get("rollback_performed"),
        "canonical": {
            "telegram_artifact": str(telegram_artifact_path),
            "telegram_artifact_sha256": sha256(telegram_artifact_path),
            "closed_count": canonical_closed,
            "recent_rows": canonical_recent_rows,
            "pnl_r": canonical_pnl,
            "writer_count": canonical_writer_count,
            "active_writer_count": canonical_active_writer_count,
            "writer_registry": actual_writer_map,
            "alimi_endpoint_http": endpoint_code,
            "alimi_closed_count": metric(endpoint, "closed_count", "closed"),
            "alimi_rows": metric(endpoint, "rows", "recent_rows"),
        },
        "telegram_renderer": {
            "unit": unit,
            "unit_show": unit_show[-4000:],
            "source_path": str(source_path),
            "source_found": source_found,
            "source_sha256": source_sha,
            "render_term_count": render_term_count,
            "fallback_expression_count": fallback_expression_count,
            "json_paths": source_json_paths,
            "secondary_json_paths": secondary_json_paths,
            "stale_literal_hits": stale_literal_hits,
            "split_source_suspected": telegram_split_source_suspected,
            "relevant_lines": source_hits[:160],
        },
        "view_renderer": {
            "index_path": str(view_index),
            "index_found": view_found,
            "index_sha256": sha256(view_index) if view_found else "missing",
            "flat_writer_count_used": view_uses_flat_writer_count,
            "writer_registry_binding_present": view_registry_binding_present,
            "writers7_projection_gap": view_projection_gap,
            "legacy_ledger_label_present": view_legacy_ledger_label,
            "relevant_lines": view_hits[:160],
        },
        "diagnosis": {
            "artifact_parity_passed_but_rendered_message_not_validated": True,
            "telegram_bottom_residue_class": "FORMATTER_SECONDARY_FALLBACK_OR_CACHED_FIELD",
            "telegram_absolute_path_class": "FORMATTER_DIAGNOSTIC_PATH_ECHO",
            "writers7_class": "CONFIGURED_REGISTRY_7_ACTIVE_0",
        },
        "next_stages": next_stages,
    }
    atomic_json(args.status, payload)
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": payload["blocker_count"],
        "warning_count": payload["warning_count"],
        "telegram_split_source_suspected": telegram_split_source_suspected,
        "telegram_secondary_json_path_count": len(secondary_json_paths),
        "telegram_fallback_expression_count": fallback_expression_count,
        "view_writers7_projection_gap": view_projection_gap,
        "view_legacy_ledger_label": view_legacy_ledger_label,
        "next_stages": next_stages,
        "status": str(args.status),
    }, sort_keys=True))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
