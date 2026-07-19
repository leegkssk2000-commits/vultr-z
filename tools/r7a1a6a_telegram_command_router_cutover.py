#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COMMAND_CONTRACT = {
    "/pos": ("POS", "ZEL POS"),
    "/pnl": ("PNL", "ZEL PNL"),
    "/view": ("VIEW", "ZEL VIEW"),
}
CAPTURE: dict[str, Any] = {
    "command_results": [],
    "alimi_view_http_status": 0,
    "alimi_view_critical_parity": False,
    "configured_writer_count": None,
    "active_writer_count": None,
    "endpoint_mode": "none",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_IMPORT_FAILED_{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized_scalar(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return float(text.rstrip("Rr%"))
        except Exception:
            return text
    return value


def first_nested(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys:
                return child
        for child in value.values():
            found = first_nested(child, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = first_nested(child, keys)
            if found is not None:
                return found
    return None


def all_nested(value: Any, keys: set[str]) -> tuple[Any, ...]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys:
                found.append(normalized_scalar(child))
            found.extend(all_nested(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.extend(all_nested(child, keys))
    return tuple(sorted(found, key=lambda item: str(item)))


def critical_view_subset(payload: dict[str, Any], parity) -> dict[str, Any]:
    configured, active = parity.writer_counts(payload)
    return {
        "order_authority": all_nested(payload, {"order_authority"}),
        "execution_authority": all_nested(payload, {"execution_authority"}),
        "real_order_enabled": all_nested(payload, {"real_order_enabled"}),
        "configured_writer_count": configured,
        "active_writer_count": active,
        "closed": normalized_scalar(first_nested(payload, {"closed", "closed_count", "shadow_closed"})),
        "pnl_r": normalized_scalar(first_nested(payload, {"pnl_r", "net_r", "shadow_pnl_r"})),
    }


def critical_views_equal(http_payload: dict[str, Any], file_payload: dict[str, Any], parity) -> bool:
    if not http_payload or not file_payload:
        return False
    left = critical_view_subset(http_payload, parity)
    right = critical_view_subset(file_payload, parity)
    required = (
        bool(left["order_authority"]),
        bool(left["execution_authority"]),
        bool(left["real_order_enabled"]),
        left["configured_writer_count"] is not None,
    )
    return all(required) and left == right


def make_distinct_command_smoke(base, parity, timeout_seconds: int):
    def wait_for_visible_pos_reply(_baseline_mtime_ns: int, _base_timeout: int):
        latest: dict[str, Any] = {}
        for command, (expected_kind, expected_title) in COMMAND_CONTRACT.items():
            try:
                baseline = base.REPORT.stat().st_mtime_ns if base.REPORT.is_file() else 0
            except Exception:
                baseline = 0
            print(f"ACTION_REQUIRED=SEND_{command}_TO_ZEL_BOT_WITHIN_{timeout_seconds}_SECONDS")
            started = time.monotonic()
            deadline = started + timeout_seconds
            passed = False
            error: str | None = None
            while time.monotonic() < deadline:
                if not base.unit_active():
                    error = "TARGET_UNIT_STOPPED_DURING_COMMAND_SMOKE"
                    break
                try:
                    changed = base.REPORT.is_file() and base.REPORT.stat().st_mtime_ns > baseline
                except Exception:
                    changed = False
                if changed:
                    latest = base.load_json(base.REPORT)
                    if str(latest.get("status") or "").startswith("HOLD_"):
                        error = "RUNTIME_REPORT_HOLD"
                        break
                    semantic_ok, semantic_blockers = base.report_semantics(latest)
                    if not semantic_ok:
                        error = semantic_blockers[0]
                        break
                    if (
                        latest.get("last_command") == command
                        and latest.get("last_response_kind") == expected_kind
                        and latest.get("last_response_title") == expected_title
                        and int(latest.get("sent_count", 0) or 0) >= 1
                    ):
                        passed = True
                        break
                time.sleep(0.25)
            if not passed and error is None:
                error = "COMMAND_RESPONSE_TIMEOUT"
            CAPTURE["command_results"].append({
                "command": command,
                "expected_kind": expected_kind,
                "expected_title": expected_title,
                "pass": passed,
                "error": error,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "observed_kind": latest.get("last_response_kind"),
                "observed_title": latest.get("last_response_title"),
            })
            if not passed:
                return False, latest, f"COMMAND_{command[1:].upper()}_{error}"

        http_status, http_payload, endpoint_mode = parity.fetch_view_endpoint()
        file_payload = parity.load_json(parity.VIEW_FILE)
        configured, active = parity.writer_counts(http_payload)
        critical_parity = critical_views_equal(http_payload, file_payload, parity)
        CAPTURE["alimi_view_http_status"] = http_status
        CAPTURE["alimi_view_critical_parity"] = critical_parity
        CAPTURE["configured_writer_count"] = configured
        CAPTURE["active_writer_count"] = active
        CAPTURE["endpoint_mode"] = endpoint_mode
        if http_status != 200:
            return False, latest, f"ALIMI_VIEW_HTTP_STATUS_{http_status}"
        if not critical_parity:
            return False, latest, "ALIMI_VIEW_CRITICAL_PARITY_FAILED"
        if configured != 7:
            return False, latest, f"VIEW_CONFIGURED_WRITER_COUNT_{configured}"
        return True, latest, None

    return wait_for_visible_pos_reply


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--source-cutover-runner", required=True)
    parser.add_argument("--parity-helper", required=True)
    parser.add_argument("--source-contract", required=True)
    parser.add_argument("--router-contract", required=True)
    parser.add_argument("--command-timeout", type=int, default=90)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    base = load_module("r7a1a5_base", Path(args.source_cutover_runner))
    parity = load_module("r7a1a6_parity", Path(args.parity_helper))
    contract = base.load_json(Path(args.router_contract))
    blockers: list[str] = []

    if contract.get("official_stage") != "R7.A1A6A":
        blockers.append("ROUTER_CONTRACT_INVALID")
    previous = base.load_json(root / "runtime/exact25_edge_v1/r7a1a5_systemd_source_cutover_canary/status_latest.json")
    if previous.get("state") != "PASS":
        blockers.append("PRIOR_R7A1A5_NOT_PASS")

    base.wait_for_visible_pos_reply = make_distinct_command_smoke(base, parity, max(30, args.command_timeout))
    source_rc = 2
    if not blockers:
        previous_argv = list(sys.argv)
        try:
            sys.argv = [
                str(args.source_cutover_runner),
                "--root", str(root),
                "--sha", args.sha,
                "--contract", args.source_contract,
                "--smoke-timeout", str(max(30, args.command_timeout)),
            ]
            source_rc = int(base.main())
        finally:
            sys.argv = previous_argv

    source_status = base.load_json(root / "runtime/exact25_edge_v1/r7a1a5_systemd_source_cutover_canary/status_latest.json")
    command_results = list(CAPTURE.get("command_results") or [])
    command_pass_count = sum(1 for item in command_results if item.get("pass") is True)
    distinct_kinds = {item.get("observed_kind") for item in command_results if item.get("pass") is True}

    if source_status.get("state") != "PASS" or source_rc != 0:
        blockers.append("SOURCE_CUTOVER_NOT_PASS")
    if command_pass_count != 3:
        blockers.append(f"COMMAND_SMOKE_PASS_COUNT_{command_pass_count}")
    if len(distinct_kinds) != 3:
        blockers.append(f"DISTINCT_RESPONSE_KIND_COUNT_{len(distinct_kinds)}")
    if CAPTURE.get("alimi_view_http_status") != 200:
        blockers.append(f"ALIMI_VIEW_HTTP_STATUS_{CAPTURE.get('alimi_view_http_status')}")
    if CAPTURE.get("alimi_view_critical_parity") is not True:
        blockers.append("ALIMI_VIEW_CRITICAL_PARITY_FAILED")
    if CAPTURE.get("configured_writer_count") != 7:
        blockers.append(f"CONFIGURED_WRITER_COUNT_{CAPTURE.get('configured_writer_count')}")
    if source_status.get("target_unit_active") is not True:
        blockers.append("TARGET_UNIT_NOT_ACTIVE")
    if int(source_status.get("protected_change_count", 0) or 0) != 0:
        blockers.append("PROTECTED_CHANGE_COUNT_NONZERO")
    if source_status.get("rollback_performed") is True and source_status.get("state") == "PASS":
        blockers.append("UNEXPECTED_ROLLBACK_ON_PASS")

    state = "PASS" if not blockers else "HOLD"
    next_stage = "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE" if state == "PASS" else "R7.A1A6A_DIAGNOSE"
    out_dir = root / "runtime/exact25_edge_v1/r7a1a6a_telegram_command_router_cutover"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    payload = {
        "schema": "r7a1a6a_telegram_command_router_cutover_status_v1",
        "official_stage": "R7.A1A6A",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "source_cutover_state": source_status.get("state"),
        "source_cutover_rc": source_rc,
        "release_path": source_status.get("release_path"),
        "release_file_sha_matches_git": source_status.get("release_file_sha_matches_git"),
        "target_unit_active": source_status.get("target_unit_active"),
        "target_process_release_path_bound": source_status.get("target_process_release_path_bound"),
        "target_process_environment_key_count": source_status.get("target_process_environment_key_count"),
        "runtime_report_status": source_status.get("runtime_report_status"),
        "command_smoke_pass_count": command_pass_count,
        "distinct_response_kind_count": len(distinct_kinds),
        "command_results": command_results,
        "alimi_view_http_status": CAPTURE.get("alimi_view_http_status"),
        "alimi_view_endpoint_mode": CAPTURE.get("endpoint_mode"),
        "alimi_view_critical_parity": CAPTURE.get("alimi_view_critical_parity"),
        "configured_writer_count": CAPTURE.get("configured_writer_count"),
        "active_writer_count": CAPTURE.get("active_writer_count"),
        "protected_change_count": source_status.get("protected_change_count"),
        "rollback_performed": source_status.get("rollback_performed"),
        "rollback_error_count": source_status.get("rollback_error_count"),
        "value_exposure_count": 0,
        "paper_mutation_count": 0,
        "live_mutation_count": 0,
        "order_mutation_count": 0,
        "next_stage": next_stage,
    }
    base.atomic_json(status_path, payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A6A Telegram Command Router Cutover",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- source cutover: `{source_status.get('state')}`",
            f"- command pass count: `{command_pass_count}`",
            f"- distinct response kinds: `{len(distinct_kinds)}`",
            f"- ALIMI HTTP status: `{CAPTURE.get('alimi_view_http_status')}`",
            f"- ALIMI critical parity: `{CAPTURE.get('alimi_view_critical_parity')}`",
            f"- Writers configured/active: `{CAPTURE.get('configured_writer_count')}/{CAPTURE.get('active_writer_count')}`",
            f"- rollback: `{source_status.get('rollback_performed')}`",
            f"- next: `{next_stage}`",
            "",
            "Telegram /view is a bot command. The web ALIMI view is validated separately as a read-only parity surface.",
        ]) + "\n",
        encoding="utf-8",
    )
    os.chmod(report_path, 0o600)

    print("R7A1A6A_TELEGRAM_COMMAND_ROUTER_CUTOVER_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"SOURCE_CUTOVER_STATE={source_status.get('state')}")
    print(f"RELEASE_FILE_SHA_MATCHES_GIT={str(source_status.get('release_file_sha_matches_git')).lower()}")
    print(f"TARGET_UNIT_ACTIVE={str(source_status.get('target_unit_active')).lower()}")
    print(f"TARGET_PROCESS_RELEASE_PATH_BOUND={str(source_status.get('target_process_release_path_bound')).lower()}")
    print(f"TARGET_PROCESS_ENVIRONMENT_KEY_COUNT={source_status.get('target_process_environment_key_count')}")
    print(f"RUNTIME_REPORT_STATUS={source_status.get('runtime_report_status')}")
    print(f"COMMAND_SMOKE_PASS_COUNT={command_pass_count}")
    print(f"DISTINCT_RESPONSE_KIND_COUNT={len(distinct_kinds)}")
    print(f"ALIMI_VIEW_HTTP_STATUS={CAPTURE.get('alimi_view_http_status')}")
    print(f"ALIMI_VIEW_CRITICAL_PARITY={str(CAPTURE.get('alimi_view_critical_parity')).lower()}")
    print(f"CONFIGURED_WRITER_COUNT={CAPTURE.get('configured_writer_count')}")
    print(f"ACTIVE_WRITER_COUNT={CAPTURE.get('active_writer_count')}")
    print(f"PROTECTED_CHANGE_COUNT={source_status.get('protected_change_count')}")
    print(f"ROLLBACK_PERFORMED={str(source_status.get('rollback_performed')).lower()}")
    print("VALUE_EXPOSURE_COUNT=0")
    print("PAPER_MUTATION_COUNT=0")
    print("LIVE_MUTATION_COUNT=0")
    print("ORDER_MUTATION_COUNT=0")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
