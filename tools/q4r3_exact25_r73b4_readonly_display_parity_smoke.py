#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import q4r3_exact25_r73b4_metric_helpers as metrics

MAX_BYTES = 2_000_000
TELEGRAM_UNIT = "zel-q4r3-telegram-pos-adapter-v2.service"


def command(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else ""


def unit_info(unit: str) -> dict[str, str]:
    return {"unit": unit,
            "active": command(["systemctl", "show", unit, "-p", "ActiveState", "--value"]),
            "fragment": command(["systemctl", "show", unit, "-p", "FragmentPath", "--value"]),
            "exec_start": command(["systemctl", "show", unit, "-p", "ExecStart", "--value"])}


def read_small(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def source_path(info: dict[str, str]) -> Path | None:
    for value in re.findall(r"(/[A-Za-z0-9_./-]+\.(?:py|sh|js))", info["exec_start"]):
        path = Path(value)
        if path.is_file():
            return path
    return None


def referenced_paths(text: str) -> list[Path]:
    output: list[Path] = []
    for value in re.findall(r"(/home/z/z/[A-Za-z0-9_./-]+)", text):
        path = Path(value.rstrip(".,);]'\""))
        if path not in output:
            output.append(path)
    return output


def choose_artifact(source: str, ledger: Path) -> tuple[str, str, int]:
    candidates: list[tuple[int, int, Path, str]] = []
    for path in referenced_paths(source):
        if path == ledger:
            continue
        text = read_small(path)
        if not text:
            continue
        lowered = text.lower()
        score = sum(1 for token in ("closed", "winrate", "pnl", "trace", "position_id") if token in lowered)
        if score >= 3:
            candidates.append((score, path.stat().st_mtime_ns, path, text))
    candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))
    if not candidates:
        return "", "", 0
    return str(candidates[0][2]), candidates[0][3], len(candidates)


def fetch_view(urls: list[str]) -> tuple[str, str, list[str]]:
    errors: list[str] = []
    for url in urls:
        args = ["curl", "-fsSL", "--max-time", "12"]
        if "127.0.0.1" in url:
            args.extend(["-H", "Host: alimi.vip"])
        result = subprocess.run(args + [url], text=True, capture_output=True, check=False, timeout=15)
        if result.returncode == 0 and result.stdout:
            return url, result.stdout[:MAX_BYTES], errors
        errors.append(f"{url}:curl={result.returncode}")
    return "", "", errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--parent-status", type=Path, required=True)
    parser.add_argument("--parent-validation", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    parent = json.loads(args.parent_status.read_text(encoding="utf-8"))
    validation = json.loads(args.parent_validation.read_text(encoding="utf-8"))
    blockers: list[str] = []
    if parent.get("state") != "PASS" or parent.get("cleanup_applied") is not True:
        blockers.append("R73B3_STATUS_INVALID")
    if validation.get("state") != "PASS" or validation.get("receipt_verified") is not True:
        blockers.append("R73B3_VALIDATION_INVALID")

    units = [unit_info(unit) for unit in contract["required_units"]]
    active_count = sum(1 for item in units if item["active"] == "active")
    if active_count != len(units):
        blockers.append("REQUIRED_UNIT_NOT_ACTIVE")

    canonical = metrics.ledger_metrics(args.ledger)
    if canonical["closed_count"] <= 0 or not canonical["latest_trace_id"]:
        blockers.append("FORMAL_LEDGER_METRICS_INCOMPLETE")

    view_url, view_text, view_errors = fetch_view(contract["view_urls"])
    view_metrics = metrics.text_metrics(view_text)
    view_problems = metrics.parity(canonical, view_metrics, view_text)
    if not view_url:
        blockers.append("ALIMI_VIEW_UNREACHABLE")
    elif view_problems:
        blockers.append("ALIMI_VIEW_PARITY_MISMATCH")

    adapter = next(item for item in units if item["unit"] == TELEGRAM_UNIT)
    fragment_text = read_small(Path(adapter["fragment"])) if adapter["fragment"] else ""
    source = source_path(adapter)
    source_text = read_small(source) if source else ""
    combined = fragment_text + "\n" + source_text
    command_bindings = {value: value in combined for value in contract["required_telegram_commands"]}
    if not source_text or not all(command_bindings.values()):
        blockers.append("TELEGRAM_COMMAND_BINDING_INCOMPLETE")
    forbidden_hits = [value for value in contract["forbidden_markers"] if value.lower() in combined.lower()]
    artifact_path, artifact_text, candidate_count = choose_artifact(source_text, args.ledger)
    artifact_metrics = metrics.text_metrics(artifact_text)
    telegram_problems = metrics.parity(canonical, artifact_metrics, artifact_text)
    if not artifact_path:
        blockers.append("TELEGRAM_RENDER_ARTIFACT_MISSING")
    elif telegram_problems:
        blockers.append("TELEGRAM_ARTIFACT_PARITY_MISMATCH")
    forbidden_hits.extend(value for value in contract["forbidden_markers"] if value.lower() in artifact_text.lower())
    if forbidden_hits:
        blockers.append("ACTIVE_STATIC_LOCK_MARKER_FOUND")

    payload: dict[str, Any] = {
        "schema": "q4r3_exact25_r73b4_readonly_display_parity_smoke_status_v1",
        "state": "PASS" if not blockers else "HOLD", "blockers": sorted(set(blockers)),
        "blocker_count": len(set(blockers)), "read_only": True, "mutation_count": 0,
        "required_unit_count": len(units), "active_required_unit_count": active_count,
        "canonical_metrics": canonical, "view_url": view_url, "view_metrics": view_metrics,
        "view_problems": view_problems, "view_parity_ready": bool(view_url) and not view_problems,
        "view_read_errors": view_errors, "telegram_source_path": str(source or ""),
        "telegram_command_bindings": command_bindings, "telegram_artifact_path": artifact_path,
        "telegram_artifact_metrics": artifact_metrics, "telegram_candidate_count": candidate_count,
        "telegram_problems": telegram_problems, "telegram_parity_ready": bool(artifact_path) and not telegram_problems,
        "forbidden_marker_count": len(set(forbidden_hits)),
        "user_visible_confirmation_required": not blockers, "next_stage": contract["next_stage"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("state", "blocker_count", "active_required_unit_count",
          "view_parity_ready", "telegram_parity_ready", "forbidden_marker_count")}, sort_keys=True))
    return 0 if payload["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
