#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


c5 = load_module("r7a1a6c5_base", HERE / "r7a1a6c5_minimal_single_owner_route_correction.py")
a1 = load_module("r7a1a6_base", HERE / "r7a1a6_deployment_parity_command_smoke.py")
ROUTE_BEGIN = c5.ROUTE_BEGIN
ROUTE_END = c5.ROUTE_END
fingerprint = c5.fingerprint


def contract_valid(contract: dict[str, Any]) -> bool:
    return (
        contract.get("official_stage") == "R7.A1A6C6"
        and contract.get("read_only") is True
        and contract.get("route_mutation_allowed") is False
        and contract.get("service_mutation_allowed") is False
        and contract.get("writer_timer_mutation_allowed") is False
        and contract.get("surface_target_mutation_allowed") is False
        and contract.get("telegram_command_required") is False
    )


def prior_valid(prior: dict[str, Any]) -> bool:
    return (
        prior.get("official_stage") == "R7.A1A6C5"
        and prior.get("state") == "PASS"
        and int(prior.get("blocker_count", -1)) == 0
        and prior.get("writer_binding_valid") is True
        and prior.get("canonical_route_bound") is True
        and prior.get("final_http_local_exact_parity") is True
        and int(prior.get("protected_change_count", -1)) == 0
        and prior.get("rollback_performed") is False
    )


def numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def semantic_zero_epoch(payload: dict[str, Any], require_writer_counts: bool = True) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    closed_keys = [key for key in ("closed", "closed_count", "shadow_closed") if key in payload]
    pnl_keys = [key for key in ("pnl_r", "net_r", "shadow_pnl_r") if key in payload]
    row_keys = [key for key in ("rows", "recent_rows", "row_count") if key in payload]
    if not closed_keys:
        blockers.append("CLOSED_FIELD_MISSING")
    if not pnl_keys:
        blockers.append("PNL_FIELD_MISSING")
    if not row_keys:
        blockers.append("ROW_FIELD_MISSING")
    for key in closed_keys + pnl_keys:
        value = numeric(payload.get(key))
        if value is None:
            blockers.append(f"{key.upper()}_NON_NUMERIC")
        elif value != 0.0:
            blockers.append(f"{key.upper()}_NOT_ZERO:{value}")
    for key in row_keys:
        value = payload.get(key)
        if isinstance(value, list):
            if value:
                blockers.append(f"{key.upper()}_NOT_EMPTY:{len(value)}")
        else:
            value_num = numeric(value)
            if value_num is None:
                blockers.append(f"{key.upper()}_INVALID")
            elif value_num != 0.0:
                blockers.append(f"{key.upper()}_NOT_ZERO:{value_num}")
    for key, expected in (("order_authority", "blocked"), ("execution_authority", "none")):
        if payload.get(key) != expected:
            blockers.append(f"{key.upper()}_{str(payload.get(key)).upper()}")
    if payload.get("real_order_enabled") is not False:
        blockers.append("REAL_ORDER_ENABLED_NOT_FALSE")
    if require_writer_counts:
        configured, active = a1.writer_counts(payload)
        if configured != 7:
            blockers.append(f"CONFIGURED_WRITER_COUNT_{configured}")
        if active != 0:
            blockers.append(f"ACTIVE_WRITER_COUNT_{active}")
    return not blockers, blockers


def route_binding(text: str, canonical: str, legacy: str) -> tuple[bool, dict[str, Any], list[str]]:
    blockers: list[str] = []
    begin_count, end_count = text.count(ROUTE_BEGIN), text.count(ROUTE_END)
    block = ""
    if begin_count != 1 or end_count != 1:
        blockers.append(f"ROUTE_MARKER_COUNT_INVALID:{begin_count}:{end_count}")
    else:
        left = text.index(ROUTE_BEGIN)
        right = text.index(ROUTE_END, left) + len(ROUTE_END)
        block = text[left:right]
        if "/api/view_contract_latest.json" not in block:
            blockers.append("VIEW_ROUTE_PATH_MISSING")
        if block.count(canonical) != 1:
            blockers.append(f"CANONICAL_REWRITE_COUNT_{block.count(canonical)}")
        if legacy in block:
            blockers.append("LEGACY_REWRITE_STILL_BOUND")
    evidence = {
        "marker_begin_count": begin_count,
        "marker_end_count": end_count,
        "canonical_rewrite_count": block.count(canonical),
        "legacy_rewrite_count": block.count(legacy),
    }
    return not blockers, evidence, blockers


def telegram_binding(contract: dict[str, Any]) -> tuple[bool, dict[str, Any], list[str]]:
    blockers: list[str] = []
    cmdline = a1.process_cmdline()
    environment = a1.process_environment()
    source = Path(str(contract["telegram_source"]))
    source_text = source.read_text(encoding="utf-8", errors="replace") if source.is_file() else ""
    if not a1.unit_active():
        blockers.append("TELEGRAM_UNIT_NOT_ACTIVE")
    if str(source) not in cmdline:
        blockers.append("TELEGRAM_EXECSTART_SOURCE_MISMATCH")
    if not str(source).startswith(str(contract["telegram_release_prefix"])):
        blockers.append("TELEGRAM_SOURCE_NOT_RELEASE_PINNED")
    if str(contract["legacy_telegram_source"]) in cmdline:
        blockers.append("LEGACY_TELEGRAM_SOURCE_EXECUTING")
    missing_commands = [cmd for cmd in contract["required_commands"] if cmd not in source_text]
    if missing_commands:
        blockers.append("TELEGRAM_COMMAND_LITERALS_MISSING:" + ",".join(missing_commands))
    if str(contract["telegram_status_path"]) not in source_text:
        blockers.append("TELEGRAM_STATUS_BINDING_MISSING")
    missing_env = [key for key in contract["required_environment_keys"] if key not in environment]
    if missing_env:
        blockers.append("TELEGRAM_ENV_KEYS_MISSING:" + ",".join(missing_env))
    evidence = {
        "unit_active": a1.unit_active(),
        "main_pid": a1.main_pid(),
        "source": str(source),
        "source_sha256": a1.sha256_file(source),
        "execstart_source_match": str(source) in cmdline,
        "legacy_source_executing": str(contract["legacy_telegram_source"]) in cmdline,
        "missing_commands": missing_commands,
        "required_environment_key_count": len(contract["required_environment_keys"]),
        "environment_key_presence_count": len(contract["required_environment_keys"]) - len(missing_env),
    }
    return not blockers, evidence, blockers


def exact_sample(canonical: Path, endpoint: str, retries: int = 4) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    for attempt in range(1, retries + 1):
        before = c5.fingerprint(canonical)
        status, body, headers = c5.fetch_http(endpoint)
        local_raw = canonical.read_bytes() if canonical.is_file() else b""
        after = c5.fingerprint(canonical)
        try:
            parsed = json.loads(local_raw.decode("utf-8"))
            payload = parsed if isinstance(parsed, dict) else {}
        except Exception:
            payload = {}
        exact = status == 200 and bool(local_raw) and body == local_raw
        stable = before == after
        attempts.append({
            "attempt": attempt,
            "http_status": status,
            "http_size": len(body),
            "http_sha256": c5.sha_bytes(body) if body else None,
            "local_size": len(local_raw),
            "local_sha256": c5.sha_bytes(local_raw) if local_raw else None,
            "exact_parity": exact,
            "stable_read_window": stable,
            "cache_control": headers.get("cache-control"),
        })
        if exact:
            return True, {"attempts": attempts, "selected_attempt": attempt}, payload
        if stable:
            break
        time.sleep(0.05)
    return False, {"attempts": attempts, "selected_attempt": None}, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--observe-seconds", type=int)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    contract = c5.load_json(Path(args.contract))
    blockers: list[str] = []
    if not contract_valid(contract):
        blockers.append("CONTRACT_INVALID")
    prior = c5.load_json(Path(contract.get("prior_status_path", "")))
    if not prior_valid(prior):
        blockers.append("C5_PASS_NOT_VALID")

    canonical = Path(contract.get("canonical_view", ""))
    trace = Path(contract.get("canonical_trace", ""))
    telegram_status = Path(contract.get("telegram_status_path", ""))
    caddyfile = Path(contract.get("caddyfile", ""))
    protected = tuple(Path(value) for value in contract.get("protected_paths", []))
    missing = [str(path) for path in (canonical, trace, telegram_status, caddyfile, *protected) if not path.is_file()]
    if missing:
        blockers.append("REQUIRED_FILE_MISSING:" + ",".join(missing))

    protected_before = c5.snapshot(protected)
    caddy_before = c5.fingerprint(caddyfile)
    writer_ok, writer_evidence, writer_blockers = c5.writer_binding(contract) if contract_valid(contract) else (False, {}, [])
    telegram_ok, telegram_evidence, telegram_blockers = telegram_binding(contract) if contract_valid(contract) else (False, {}, [])
    blockers.extend(writer_blockers + telegram_blockers)
    route_ok, route_evidence, route_blockers = route_binding(
        caddyfile.read_text(encoding="utf-8", errors="replace") if caddyfile.is_file() else "",
        str(contract.get("canonical_rewrite", "")),
        str(contract.get("legacy_rewrite", "")),
    )
    blockers.extend(route_blockers)

    observe_seconds = max(int(contract.get("minimum_observe_seconds", 180)), int(args.observe_seconds or contract.get("observe_seconds", 180)))
    poll_seconds = float(contract.get("poll_seconds", 2.0))
    samples: list[dict[str, Any]] = []
    view_changes = trace_changes = 0
    last_view, last_trace = c5.fingerprint(canonical), c5.fingerprint(trace)

    if not blockers:
        deadline = time.monotonic() + observe_seconds
        while time.monotonic() < deadline:
            parity, parity_detail, view = exact_sample(canonical, str(contract["endpoint"]))
            semantic_ok, semantic_blockers = semantic_zero_epoch(view, True)
            telegram_semantic_ok, telegram_semantic_blockers = semantic_zero_epoch(c5.load_json(telegram_status), False)
            route_sample_ok, _, route_sample_blockers = route_binding(
                caddyfile.read_text(encoding="utf-8", errors="replace"),
                str(contract["canonical_rewrite"]),
                str(contract["legacy_rewrite"]),
            )
            current_view, current_trace = c5.fingerprint(canonical), c5.fingerprint(trace)
            view_changes += int(current_view != last_view)
            trace_changes += int(current_trace != last_trace)
            last_view, last_trace = current_view, current_trace
            samples.append({
                "ts": c5.now_iso(),
                "exact_parity": parity,
                "semantic_zero_epoch": semantic_ok,
                "semantic_blockers": semantic_blockers,
                "telegram_zero_epoch": telegram_semantic_ok,
                "telegram_semantic_blockers": telegram_semantic_blockers,
                "route_bound": route_sample_ok,
                "route_blockers": route_sample_blockers,
                "parity_detail": parity_detail,
            })
            if not parity:
                blockers.append("HTTP_CANONICAL_EXACT_PARITY_FAILED")
                break
            if not semantic_ok:
                blockers.append("CANONICAL_ZERO_EPOCH_SEMANTICS_FAILED:" + ",".join(semantic_blockers))
                break
            if not telegram_semantic_ok:
                blockers.append("TELEGRAM_ZERO_EPOCH_SEMANTICS_FAILED:" + ",".join(telegram_semantic_blockers))
                break
            if not route_sample_ok:
                blockers.append("CANONICAL_ROUTE_DRIFT:" + ",".join(route_sample_blockers))
                break
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(poll_seconds, remaining))

    writer_final_ok, writer_final_evidence, writer_final_blockers = c5.writer_binding(contract) if contract_valid(contract) else (False, {}, [])
    telegram_final_ok, telegram_final_evidence, telegram_final_blockers = telegram_binding(contract) if contract_valid(contract) else (False, {}, [])
    blockers.extend("FINAL_" + item for item in writer_final_blockers + telegram_final_blockers)
    protected_changes = c5.diff(protected_before, c5.snapshot(protected))
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_DETECTED")
    caddy_changed = caddy_before != c5.fingerprint(caddyfile)
    if caddy_changed:
        blockers.append("CADDYFILE_CHANGED_DURING_READ_ONLY_VERIFY")
    final_parity, final_detail, final_view = exact_sample(canonical, str(contract.get("endpoint", "")))
    final_semantic_ok, final_semantic_blockers = semantic_zero_epoch(final_view, True)
    if not final_parity:
        blockers.append("FINAL_HTTP_CANONICAL_EXACT_PARITY_FALSE")
    if not final_semantic_ok:
        blockers.append("FINAL_CANONICAL_ZERO_EPOCH_FALSE:" + ",".join(final_semantic_blockers))

    blockers = list(dict.fromkeys(blockers))
    state = "PASS" if not blockers else "HOLD"
    status_path = root / contract.get("status_path", "runtime/exact25_edge_v1/r7a1a6c6_exact_semantic_stability/status_latest.json")
    payload = {
        "schema": "r7a1a6c6_exact_semantic_stability_verify_status_v1",
        "official_stage": "R7.A1A6C6",
        "generated_at": c5.now_iso(),
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "prior_c5_valid": prior_valid(prior),
        "read_only": True,
        "writer_binding_valid": writer_ok and writer_final_ok,
        "writer_binding_initial": writer_evidence,
        "writer_binding_final": writer_final_evidence,
        "telegram_binding_valid": telegram_ok and telegram_final_ok,
        "telegram_binding_initial": telegram_evidence,
        "telegram_binding_final": telegram_final_evidence,
        "canonical_route_bound": route_ok,
        "route_evidence": route_evidence,
        "observe_seconds": observe_seconds,
        "sample_count": len(samples),
        "samples": samples[-200:],
        "canonical_view_change_count": view_changes,
        "canonical_trace_change_count": trace_changes,
        "final_http_local_exact_parity": final_parity,
        "final_parity_detail": final_detail,
        "final_semantic_zero_epoch": final_semantic_ok,
        "final_semantic_blockers": final_semantic_blockers,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "caddyfile_change_count": int(caddy_changed),
        "route_mutation_count": 0,
        "service_mutation_count": 0,
        "writer_timer_mutation_count": 0,
        "surface_target_mutation_count": 0,
        "telegram_command_send_count": 0,
        "paper_mutation_count": 0,
        "live_mutation_count": 0,
        "order_mutation_count": 0,
        "next_stage": "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE" if state == "PASS" else "R7.A1A6C6_DIAGNOSE",
    }
    c5.atomic_json(status_path, payload)
    print("R7A1A6C6_EXACT_SEMANTIC_STABILITY_VERIFY_COMPLETE")
    for key, value in (
        ("STATE", state), ("BLOCKER_COUNT", len(blockers)), ("BLOCKERS", json.dumps(blockers, ensure_ascii=False)),
        ("PRIOR_C5_VALID", str(prior_valid(prior)).lower()), ("READ_ONLY", "true"),
        ("CANONICAL_WRITER_BOUND", str(writer_ok and writer_final_ok).lower()),
        ("CANONICAL_ROUTE_BOUND", str(route_ok).lower()),
        ("TELEGRAM_BINDING_VALID", str(telegram_ok and telegram_final_ok).lower()),
        ("OBSERVE_SECONDS", observe_seconds), ("SAMPLE_COUNT", len(samples)),
        ("CANONICAL_VIEW_CHANGE_COUNT", view_changes), ("CANONICAL_TRACE_CHANGE_COUNT", trace_changes),
        ("FINAL_HTTP_LOCAL_EXACT_PARITY", str(final_parity).lower()),
        ("FINAL_SEMANTIC_ZERO_EPOCH", str(final_semantic_ok).lower()),
        ("PROTECTED_CHANGE_COUNT", len(protected_changes)), ("CADDYFILE_CHANGE_COUNT", int(caddy_changed)),
        ("ROUTE_MUTATION_COUNT", 0), ("SERVICE_MUTATION_COUNT", 0), ("WRITER_TIMER_MUTATION_COUNT", 0),
        ("TELEGRAM_COMMAND_SEND_COUNT", 0), ("PAPER_MUTATION_COUNT", 0), ("LIVE_MUTATION_COUNT", 0),
        ("ORDER_MUTATION_COUNT", 0), ("NEXT_STAGE", payload["next_stage"]),
        ("EVIDENCE_JSON", str(status_path)), ("RC", 0 if state == "PASS" else 2),
    ):
        print(f"{key}={value}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
