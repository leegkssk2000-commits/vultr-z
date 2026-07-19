#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAPTURE: dict[str, Any] = {
    "error_class": None,
    "http_code": None,
    "error_fingerprint": None,
    "first_report_latency_ms": None,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("r7a1a5_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify_error(value: Any) -> tuple[str, int | None, str | None]:
    text = str(value or "").strip()
    if not text:
        return "NONE", None, None
    lowered = text.lower()
    code_match = re.search(r"\b(?:http(?:\s+error)?\s*)?(4\d\d|5\d\d)\b", lowered)
    http_code = int(code_match.group(1)) if code_match else None
    if http_code == 409 or "conflict" in lowered:
        error_class = "HTTP_409_CONFLICT"
    elif "timed out" in lowered or "timeout" in lowered:
        error_class = "NETWORK_TIMEOUT"
    elif "permission denied" in lowered or "permissionerror" in lowered:
        error_class = "PERMISSION_ERROR"
    elif "no such file" in lowered or "filenotfound" in lowered or "not a directory" in lowered:
        error_class = "PATH_ERROR"
    elif "json" in lowered or "decode" in lowered:
        error_class = "JSON_ERROR"
    elif http_code is not None or "http error" in lowered:
        error_class = "HTTP_ERROR"
    else:
        error_class = "OTHER_ERROR"
    fingerprint = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return error_class, http_code, fingerprint


def make_wait(base):
    def wait_for_visible_pos_reply(baseline_mtime_ns: int, timeout_seconds: int):
        print(f"ACTION_REQUIRED=SEND_/pos_TO_ZEL_BOT_WITHIN_{timeout_seconds}_SECONDS")
        started = time.monotonic()
        deadline = started + timeout_seconds
        latest: dict[str, Any] = {}
        while time.monotonic() < deadline:
            if not base.unit_active():
                CAPTURE["error_class"] = "UNIT_STOPPED"
                return False, latest, "TARGET_UNIT_STOPPED_DURING_SMOKE"
            try:
                changed = base.REPORT.is_file() and base.REPORT.stat().st_mtime_ns > baseline_mtime_ns
            except Exception:
                changed = False
            if changed:
                latest = base.load_json(base.REPORT)
                if CAPTURE["first_report_latency_ms"] is None:
                    CAPTURE["first_report_latency_ms"] = int((time.monotonic() - started) * 1000)
                status = str(latest.get("status") or "")
                if status.startswith("HOLD_"):
                    error_class, http_code, fingerprint = classify_error(latest.get("error"))
                    CAPTURE["error_class"] = error_class
                    CAPTURE["http_code"] = http_code
                    CAPTURE["error_fingerprint"] = fingerprint
                    return False, latest, "RUNTIME_REPORT_HOLD"
                ok, semantic_blockers = base.report_semantics(latest)
                if not ok:
                    CAPTURE["error_class"] = "SEMANTIC_ERROR"
                    return False, latest, semantic_blockers[0]
                try:
                    sent_count = int(latest.get("sent_count", 0) or 0)
                except Exception:
                    sent_count = 0
                if sent_count >= 1:
                    CAPTURE["error_class"] = "NONE"
                    return True, latest, None
            time.sleep(0.25)
        CAPTURE["error_class"] = "VISIBLE_REPLY_TIMEOUT"
        return False, latest, "VISIBLE_POS_REPLY_TIMEOUT"
    return wait_for_visible_pos_reply


def atomic_json(base, path: Path, payload: dict[str, Any]) -> None:
    base.atomic_json(path, payload, mode=0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--base-runner", required=True)
    parser.add_argument("--base-contract", required=True)
    parser.add_argument("--classification-contract", required=True)
    parser.add_argument("--smoke-timeout", type=int, default=120)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    base = load_module(Path(args.base_runner))
    contract = base.load_json(Path(args.classification_contract))
    out_dir = root / "runtime/exact25_edge_v1/r7a1a5a_runtime_error_classification"
    status_path = out_dir / "status_latest.json"
    report_path = out_dir / "report_latest.md"
    blockers: list[str] = []

    prior = base.load_json(root / "runtime/exact25_edge_v1/r7a1a5_systemd_source_cutover_canary/status_latest.json")
    if contract.get("official_stage") != "R7.A1A5A":
        blockers.append("CLASSIFICATION_CONTRACT_INVALID")
    if prior.get("state") != "HOLD" or "RUNTIME_REPORT_HOLD" not in (prior.get("blockers") or []):
        blockers.append("PRIOR_A1A5_RUNTIME_HOLD_NOT_CONFIRMED")

    base.wait_for_visible_pos_reply = make_wait(base)
    rc_base = 2
    if not blockers:
        previous_argv = list(sys.argv)
        try:
            sys.argv = [
                str(args.base_runner),
                "--root", str(root),
                "--sha", args.sha,
                "--contract", args.base_contract,
                "--smoke-timeout", str(max(30, args.smoke_timeout)),
            ]
            rc_base = int(base.main())
        finally:
            sys.argv = previous_argv

    reproduced = base.load_json(root / "runtime/exact25_edge_v1/r7a1a5_systemd_source_cutover_canary/status_latest.json")
    error_class = str(CAPTURE.get("error_class") or "UNCLASSIFIED")
    if error_class == "UNCLASSIFIED":
        blockers.append("RUNTIME_ERROR_NOT_CLASSIFIED")
    if reproduced.get("state") == "HOLD":
        if reproduced.get("rollback_performed") is not True:
            blockers.append("ROLLBACK_NOT_PERFORMED")
        if int(reproduced.get("rollback_error_count", 0) or 0) != 0:
            blockers.append("ROLLBACK_ERROR_COUNT_NONZERO")
    if reproduced.get("target_unit_active") is not True:
        blockers.append("TARGET_UNIT_NOT_ACTIVE")
    if int(reproduced.get("protected_change_count", 0) or 0) != 0:
        blockers.append("PROTECTED_CHANGE_COUNT_NONZERO")

    next_map = contract.get("next_stage_by_class") if isinstance(contract.get("next_stage_by_class"), dict) else {}
    next_stage = str(next_map.get(error_class) or "R7.A1A5B_RUNTIME_DIAGNOSE")
    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "r7a1a5a_runtime_error_classification_status_v1",
        "official_stage": "R7.A1A5A",
        "generated_at": now_iso(),
        "target_commit": args.sha,
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "mutation_count": reproduced.get("mutation_count"),
        "service_restart_count": reproduced.get("service_restart_count"),
        "classification_written": error_class != "UNCLASSIFIED",
        "runtime_error_class": error_class,
        "runtime_http_code": CAPTURE.get("http_code"),
        "runtime_error_fingerprint": CAPTURE.get("error_fingerprint"),
        "first_report_latency_ms": CAPTURE.get("first_report_latency_ms"),
        "raw_runtime_error_persisted": False,
        "value_exposure_count": 0,
        "underlying_canary_rc": rc_base,
        "underlying_canary_state": reproduced.get("state"),
        "rollback_performed": reproduced.get("rollback_performed"),
        "rollback_error_count": reproduced.get("rollback_error_count"),
        "target_unit_active": reproduced.get("target_unit_active"),
        "protected_change_count": reproduced.get("protected_change_count"),
        "next_stage": next_stage,
    }
    atomic_json(base, status_path, payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join([
            "# R7.A1A5A Runtime Error Classification",
            "",
            f"- state: `{state}`",
            f"- blockers: `{blockers}`",
            f"- runtime error class: `{error_class}`",
            f"- HTTP code: `{CAPTURE.get('http_code')}`",
            f"- first report latency ms: `{CAPTURE.get('first_report_latency_ms')}`",
            f"- underlying canary state: `{reproduced.get('state')}`",
            f"- rollback performed: `{reproduced.get('rollback_performed')}`",
            f"- rollback errors: `{reproduced.get('rollback_error_count')}`",
            f"- next: `{next_stage}`",
            "",
            "The raw runtime error, credential, and chat identifier are not persisted or printed.",
        ]) + "\n",
        encoding="utf-8",
    )
    report_path.chmod(0o600)

    print("R7A1A5A_RUNTIME_ERROR_CLASSIFICATION_COMPLETE")
    print(f"STATE={state}")
    print(f"BLOCKER_COUNT={len(blockers)}")
    print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
    print(f"RUNTIME_ERROR_CLASS={error_class}")
    print(f"RUNTIME_HTTP_CODE={CAPTURE.get('http_code')}")
    print(f"FIRST_REPORT_LATENCY_MS={CAPTURE.get('first_report_latency_ms')}")
    print("RAW_RUNTIME_ERROR_PERSISTED=false")
    print("VALUE_EXPOSURE_COUNT=0")
    print(f"UNDERLYING_CANARY_STATE={reproduced.get('state')}")
    print(f"ROLLBACK_PERFORMED={str(reproduced.get('rollback_performed')).lower()}")
    print(f"ROLLBACK_ERROR_COUNT={reproduced.get('rollback_error_count')}")
    print(f"TARGET_UNIT_ACTIVE={str(reproduced.get('target_unit_active')).lower()}")
    print(f"PROTECTED_CHANGE_COUNT={reproduced.get('protected_change_count')}")
    print(f"NEXT_STAGE={next_stage}")
    print(f"EVIDENCE_JSON={status_path}")
    print(f"EVIDENCE_REPORT={report_path}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
