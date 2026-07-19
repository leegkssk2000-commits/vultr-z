#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROUTE_BEGIN = "# Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_BEGIN"
ROUTE_END = "# Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_END"


@dataclass(frozen=True)
class Fingerprint:
    path: str
    exists: bool
    inode: int | None
    mtime_ns: int | None
    size: int | None
    sha256: str | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fingerprint(path: Path) -> Fingerprint:
    try:
        st = path.stat()
        raw = path.read_bytes() if path.is_file() else b""
        return Fingerprint(str(path), True, int(st.st_ino), int(st.st_mtime_ns), int(st.st_size), sha_bytes(raw))
    except OSError:
        return Fingerprint(str(path), False, None, None, None, None)


def snapshot(paths: tuple[Path, ...]) -> dict[str, Fingerprint]:
    return {str(path): fingerprint(path) for path in paths}


def diff(before: dict[str, Fingerprint], after: dict[str, Fingerprint]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        left, right = before.get(key), after.get(key)
        if left != right:
            rows.append({"path": key, "before": asdict(left) if left else None, "after": asdict(right) if right else None})
    return rows


def atomic_bytes(path: Path, raw: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    atomic_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), mode)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def contract_valid(contract: dict[str, Any]) -> bool:
    return (
        contract.get("official_stage") == "R7.A1A6C5"
        and contract.get("route_mutation_allowed") is True
        and contract.get("service_mutation_allowed") is False
        and contract.get("writer_timer_mutation_allowed") is False
        and contract.get("rollback_required") is True
    )


def prior_valid(prior: dict[str, Any]) -> bool:
    return (
        prior.get("official_stage") == "R7.A1A6C4"
        and prior.get("state") == "DIAGNOSED"
        and int(prior.get("blocker_count", -1)) == 0
        and prior.get("writer_narrowed") is True
        and int(prior.get("writer_proof_count", 0)) >= 1
        and int(prior.get("http_origin_exact_match_count", 0)) >= 1
        and int(prior.get("protected_change_count", -1)) == 0
    )


def patch_caddy(text: str, legacy_rewrite: str, canonical_rewrite: str) -> tuple[str, int]:
    begin = text.count(ROUTE_BEGIN)
    end = text.count(ROUTE_END)
    if begin != 1 or end != 1:
        raise RuntimeError(f"ROUTE_MARKER_COUNT_INVALID:{begin}:{end}")
    left = text.index(ROUTE_BEGIN)
    right = text.index(ROUTE_END, left) + len(ROUTE_END)
    block = text[left:right]
    if "/api/view_contract_latest.json" not in block:
        raise RuntimeError("VIEW_ROUTE_PATH_MISSING_IN_MARKED_BLOCK")
    if block.count(legacy_rewrite) != 1:
        if block.count(canonical_rewrite) == 1 and legacy_rewrite not in block:
            return text, 0
        raise RuntimeError(f"LEGACY_REWRITE_COUNT_INVALID:{block.count(legacy_rewrite)}")
    patched_block = block.replace(legacy_rewrite, canonical_rewrite, 1)
    return text[:left] + patched_block + text[right:], 1


def fetch_http(url: str) -> tuple[int, bytes, dict[str, str]]:
    attempts = (
        ["curl", "-kfsS", "--max-time", "12", "--resolve", "alimi.z-os.vip:443:127.0.0.1", "-D", "-", "-w", "\n__STATUS__%{http_code}", url],
        ["curl", "-fsS", "--max-time", "12", "-H", "Host: alimi.z-os.vip", "-D", "-", "-w", "\n__STATUS__%{http_code}", "http://127.0.0.1/api/view_contract_latest.json"],
    )
    for command in attempts:
        proc = run(command, 20)
        if proc.returncode != 0:
            continue
        raw = proc.stdout.encode("utf-8", errors="replace")
        marker = b"\n__STATUS__"
        if marker not in raw:
            continue
        response, _, tail = raw.rpartition(marker)
        try:
            status = int(tail.strip())
        except ValueError:
            status = 0
        split = response.find(b"\r\n\r\n")
        if split < 0:
            split = response.find(b"\n\n")
            sep = 2
        else:
            sep = 4
        if split < 0:
            continue
        header_raw, body = response[:split], response[split + sep :]
        headers: dict[str, str] = {}
        for line in header_raw.decode("utf-8", errors="replace").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        if status:
            return status, body, headers
    return 0, b"", {}


def semantic_zero_epoch(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []

    def number(key: str) -> float | None:
        value = payload.get(key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    for key in ("closed", "closed_count"):
        value = number(key)
        if value is not None and value != 0.0:
            blockers.append(f"{key.upper()}_NOT_ZERO:{value}")
    for key in ("pnl_r", "net_r"):
        value = number(key)
        if value is not None and value != 0.0:
            blockers.append(f"{key.upper()}_NOT_ZERO:{value}")
    rows = payload.get("rows")
    if isinstance(rows, list) and rows:
        blockers.append(f"ROWS_NOT_EMPTY:{len(rows)}")
    recent = payload.get("recent_rows")
    if isinstance(recent, list) and recent:
        blockers.append(f"RECENT_ROWS_NOT_EMPTY:{len(recent)}")
    elif isinstance(recent, (int, float)) and float(recent) != 0.0:
        blockers.append(f"RECENT_ROWS_NOT_ZERO:{recent}")
    for key, expected in (("order_authority", "blocked"), ("execution_authority", "none")):
        value = payload.get(key)
        if value is not None and value != expected:
            blockers.append(f"{key.upper()}_{value}")
    if payload.get("real_order_enabled") not in (None, False):
        blockers.append("REAL_ORDER_ENABLED_NOT_FALSE")
    return not blockers, blockers


def writer_binding(contract: dict[str, Any]) -> tuple[bool, dict[str, Any], list[str]]:
    blockers: list[str] = []
    timer = str(contract["canonical_writer_timer"])
    service = str(contract["canonical_writer_service"])
    script = Path(contract["canonical_writer_script"])
    timer_state = run(["systemctl", "is-active", timer], 15)
    service_show = run(["systemctl", "show", service, "-p", "ExecStart", "-p", "FragmentPath", "-p", "ActiveState", "-p", "SubState"], 20)
    source = script.read_text(encoding="utf-8", errors="replace") if script.is_file() else ""
    if timer_state.returncode != 0 or timer_state.stdout.strip() != "active":
        blockers.append("CANONICAL_WRITER_TIMER_NOT_ACTIVE")
    if service_show.returncode != 0 or str(script) not in service_show.stdout:
        blockers.append("CANONICAL_WRITER_SERVICE_EXECSTART_MISMATCH")
    required_names = [Path(x).name for x in contract["canonical_writer_outputs"]]
    missing_names = [name for name in required_names if name not in source]
    if missing_names:
        blockers.append("CANONICAL_WRITER_OUTPUT_REFERENCES_MISSING:" + ",".join(missing_names))
    return not blockers, {
        "timer": timer,
        "timer_active": timer_state.stdout.strip(),
        "service": service,
        "service_show": service_show.stdout[-4000:],
        "script": str(script),
        "script_sha256": sha_bytes(script.read_bytes()) if script.is_file() else None,
        "required_output_names": required_names,
        "missing_output_names": missing_names,
    }, blockers


def caddy_reload(caddyfile: Path) -> tuple[bool, dict[str, Any]]:
    validate = run(["caddy", "validate", "--config", str(caddyfile), "--adapter", "caddyfile"], 30)
    if validate.returncode != 0:
        return False, {"validate_rc": validate.returncode, "validate_stderr": validate.stderr[-2000:]}
    reload_result = run(["caddy", "reload", "--config", str(caddyfile), "--adapter", "caddyfile"], 30)
    return reload_result.returncode == 0, {
        "validate_rc": validate.returncode,
        "validate_stdout": validate.stdout[-2000:],
        "reload_rc": reload_result.returncode,
        "reload_stdout": reload_result.stdout[-2000:],
        "reload_stderr": reload_result.stderr[-2000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--observe-seconds", type=int)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    blockers: list[str] = []
    if not contract_valid(contract):
        blockers.append("CONTRACT_INVALID")
    prior = load_json(Path(contract.get("prior_status_path", "")))
    if not prior_valid(prior):
        blockers.append("C4_DIAGNOSIS_NOT_VALID")
    if not args.apply:
        blockers.append("APPLY_FLAG_REQUIRED")

    caddyfile = Path(contract.get("caddyfile", "/etc/caddy/Caddyfile"))
    canonical = Path(contract.get("canonical_view", "/var/www/z-os-alimi/api/view_contract_latest.json"))
    trace = Path(contract.get("canonical_trace", "/var/www/z-os-alimi/api/q4r3_recent_ledger_trace_latest.json"))
    protected = tuple(Path(x) for x in contract.get("protected_paths", []))
    protected_before = snapshot(protected)
    writer_ok, writer_evidence, writer_blockers = writer_binding(contract) if contract_valid(contract) else (False, {}, [])
    blockers.extend(writer_blockers)

    original = caddyfile.read_bytes() if caddyfile.is_file() else b""
    original_mode = caddyfile.stat().st_mode & 0o777 if caddyfile.is_file() else 0o644
    backup_dir = root / contract.get("backup_dir", "runtime/exact25_edge_v1/r7a1a6c5_single_owner_route_correction/backups") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    status_path = root / contract.get("status_path", "runtime/exact25_edge_v1/r7a1a6c5_single_owner_route_correction/status_latest.json")
    rollback_performed = False
    rollback_errors: list[str] = []
    route_patch_count = 0
    reload_evidence: dict[str, Any] = {}
    parity_samples: list[dict[str, Any]] = []
    canonical_change_count = 0
    trace_change_count = 0

    if not caddyfile.is_file():
        blockers.append("CADDYFILE_MISSING")
    if not canonical.is_file():
        blockers.append("CANONICAL_VIEW_MISSING")
    if not trace.is_file():
        blockers.append("CANONICAL_TRACE_MISSING")

    if not blockers:
        try:
            patched_text, route_patch_count = patch_caddy(
                original.decode("utf-8"),
                str(contract["legacy_rewrite"]),
                str(contract["canonical_rewrite"]),
            )
            backup_dir.mkdir(parents=True, exist_ok=False)
            os.chmod(backup_dir, 0o700)
            (backup_dir / "Caddyfile.before").write_bytes(original)
            os.chmod(backup_dir / "Caddyfile.before", 0o600)
            atomic_bytes(caddyfile, patched_text.encode(), original_mode)
            reload_ok, reload_evidence = caddy_reload(caddyfile)
            if not reload_ok:
                raise RuntimeError("CADDY_RELOAD_FAILED")

            observe_seconds = max(int(contract.get("minimum_observe_seconds", 120)), int(args.observe_seconds or contract.get("observe_seconds", 120)))
            deadline = time.monotonic() + observe_seconds
            last_view = fingerprint(canonical)
            last_trace = fingerprint(trace)
            while time.monotonic() < deadline:
                time.sleep(float(contract.get("poll_seconds", 1.0)))
                current_view = fingerprint(canonical)
                current_trace = fingerprint(trace)
                canonical_change_count += int(current_view != last_view)
                trace_change_count += int(current_trace != last_trace)
                last_view, last_trace = current_view, current_trace
                status, body, headers = fetch_http(str(contract["endpoint"]))
                local_raw = canonical.read_bytes() if canonical.is_file() else b""
                try:
                    payload = json.loads(local_raw.decode("utf-8"))
                    payload = payload if isinstance(payload, dict) else {}
                except Exception:
                    payload = {}
                semantic_ok, semantic_blockers = semantic_zero_epoch(payload)
                parity = status == 200 and bool(local_raw) and body == local_raw
                parity_samples.append({
                    "ts": now_iso(),
                    "http_status": status,
                    "http_size": len(body),
                    "http_sha256": sha_bytes(body) if body else None,
                    "local_size": len(local_raw),
                    "local_sha256": sha_bytes(local_raw) if local_raw else None,
                    "exact_parity": parity,
                    "semantic_zero_epoch": semantic_ok,
                    "semantic_blockers": semantic_blockers,
                    "cache_control": headers.get("cache-control"),
                })
                if not parity:
                    raise RuntimeError("HTTP_CANONICAL_EXACT_PARITY_FAILED")
                if not semantic_ok:
                    raise RuntimeError("CANONICAL_ZERO_EPOCH_SEMANTICS_FAILED:" + ",".join(semantic_blockers))

        except Exception as exc:
            blockers.append(f"CORRECTION_FAILED:{type(exc).__name__}:{exc}")
            try:
                atomic_bytes(caddyfile, original, original_mode)
                rollback_ok, rollback_reload = caddy_reload(caddyfile)
                reload_evidence["rollback"] = rollback_reload
                rollback_performed = True
                if not rollback_ok:
                    rollback_errors.append("CADDY_ROLLBACK_RELOAD_FAILED")
            except Exception as rollback_exc:
                rollback_errors.append(f"{type(rollback_exc).__name__}:{rollback_exc}")

    protected_after = snapshot(protected)
    protected_changes = diff(protected_before, protected_after)
    if protected_changes:
        blockers.append("PROTECTED_CHANGE_DETECTED")
    if rollback_errors:
        blockers.append("ROLLBACK_FAILED")

    final_status, final_body, _ = fetch_http(str(contract.get("endpoint", "")))
    final_local = canonical.read_bytes() if canonical.is_file() else b""
    final_parity = final_status == 200 and bool(final_local) and final_body == final_local
    final_text = caddyfile.read_text(encoding="utf-8", errors="replace") if caddyfile.is_file() else ""
    marker_left = final_text.find(ROUTE_BEGIN)
    marker_right = final_text.find(ROUTE_END, marker_left) if marker_left >= 0 else -1
    route_block = final_text[marker_left:marker_right + len(ROUTE_END)] if marker_left >= 0 and marker_right >= 0 else ""
    canonical_route_bound = str(contract.get("canonical_rewrite", "")) in route_block and str(contract.get("legacy_rewrite", "")) not in route_block
    if not blockers and not final_parity:
        blockers.append("FINAL_HTTP_CANONICAL_PARITY_FALSE")
    if not blockers and not canonical_route_bound:
        blockers.append("FINAL_CANONICAL_ROUTE_NOT_BOUND")

    state = "PASS" if not blockers else "HOLD"
    payload = {
        "schema": "r7a1a6c5_minimal_single_owner_route_correction_status_v1",
        "official_stage": "R7.A1A6C5",
        "generated_at": now_iso(),
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "prior_c4_valid": prior_valid(prior),
        "writer_binding": writer_evidence,
        "writer_binding_valid": writer_ok,
        "route_patch_count": route_patch_count,
        "canonical_route_bound": canonical_route_bound,
        "caddy_reload_evidence": reload_evidence,
        "backup_dir": str(backup_dir) if backup_dir.exists() else None,
        "rollback_performed": rollback_performed,
        "rollback_errors": rollback_errors,
        "observe_seconds": max(int(contract.get("minimum_observe_seconds", 120)), int(args.observe_seconds or contract.get("observe_seconds", 120))),
        "canonical_view_change_count": canonical_change_count,
        "canonical_trace_change_count": trace_change_count,
        "parity_sample_count": len(parity_samples),
        "parity_samples": parity_samples[-300:],
        "final_http_status": final_status,
        "final_http_local_exact_parity": final_parity,
        "protected_change_count": len(protected_changes),
        "protected_changes": protected_changes,
        "paper_mutation_count": 0,
        "live_mutation_count": 0,
        "order_mutation_count": 0,
        "writer_timer_mutation_count": 0,
        "service_restart_count": 0,
        "route_reload_count": 1 if reload_evidence.get("reload_rc") == 0 else 0,
        "next_stage": "R7.A1A6C6_EXACT_SEMANTIC_STABILITY_VERIFY" if state == "PASS" else "R7.A1A6C5_ROLLBACK_REVIEW",
    }
    atomic_json(status_path, payload)

    print("R7A1A6C5_MINIMAL_SINGLE_OWNER_ROUTE_CORRECTION_COMPLETE")
    for key, value in (
        ("STATE", state),
        ("BLOCKER_COUNT", len(blockers)),
        ("BLOCKERS", json.dumps(blockers, ensure_ascii=False)),
        ("PRIOR_C4_VALID", str(prior_valid(prior)).lower()),
        ("CANONICAL_WRITER_BOUND", str(writer_ok).lower()),
        ("ROUTE_PATCH_COUNT", route_patch_count),
        ("CANONICAL_ROUTE_BOUND", str(canonical_route_bound).lower()),
        ("CANONICAL_VIEW_CHANGE_COUNT", canonical_change_count),
        ("CANONICAL_TRACE_CHANGE_COUNT", trace_change_count),
        ("PARITY_SAMPLE_COUNT", len(parity_samples)),
        ("FINAL_HTTP_STATUS", final_status),
        ("FINAL_HTTP_LOCAL_EXACT_PARITY", str(final_parity).lower()),
        ("PROTECTED_CHANGE_COUNT", len(protected_changes)),
        ("ROLLBACK_PERFORMED", str(rollback_performed).lower()),
        ("WRITER_TIMER_MUTATION_COUNT", 0),
        ("PAPER_MUTATION_COUNT", 0),
        ("LIVE_MUTATION_COUNT", 0),
        ("ORDER_MUTATION_COUNT", 0),
        ("NEXT_STAGE", payload["next_stage"]),
        ("EVIDENCE_JSON", str(status_path)),
        ("RC", 0 if state == "PASS" else 2),
    ):
        print(f"{key}={value}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
