#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

ROUTE_BEGIN = "# Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_BEGIN"
ROUTE_END = "# Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_END"
NEW_TELEGRAM_SOURCE = "/home/z/z/runtime/exact25_edge_v1/display_adapter/telegram_status_latest.json"


def run(command: list[str], check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check, timeout=timeout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_text(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(text, encoding="utf-8")
        if mode is not None:
            tmp.chmod(mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    result = run(["curl", "-fsSL", "--max-time", "15", "-w", "\n%{http_code}", url], check=False, timeout=20)
    if result.returncode != 0:
        return 0, {}
    body, _, code = result.stdout.rpartition("\n")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return int(code or 0), {}
    return int(code or 0), payload if isinstance(payload, dict) else {}


def locate_telegram_template(source_text: str) -> Path | None:
    candidates: list[Path] = []
    for value in re.findall(r"['\"]([^'\"]*telegram_pos_status_latest\.json)['\"]", source_text):
        path = Path(value)
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend([
                Path("/home/z/z") / path,
                Path("/var/www/z-os-alimi") / path,
                Path("/var/www/z-os-alimi/view") / path,
                Path("/usr/local/bin") / path,
            ])
    candidates.extend([
        Path("/var/www/z-os-alimi/telegram_pos_status_latest.json"),
        Path("/var/www/z-os-alimi/view/telegram_pos_status_latest.json"),
        Path("/home/z/z/q4r3_telegram_pos_status_latest.json"),
        Path("/home/z/z/telegram_pos_status_latest.json"),
        Path("/usr/local/bin/q4r3_telegram_pos_status_latest.json"),
        Path("/usr/local/bin/telegram_pos_status_latest.json"),
    ])
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return path
        except (OSError, json.JSONDecodeError):
            continue
    return None


def patch_caddy(text: str) -> tuple[str, int]:
    if ROUTE_BEGIN in text:
        return text, 0
    site_start = text.find("alimi.z-os.vip {")
    if site_start < 0:
        raise RuntimeError("ALIMI_SITE_BLOCK_MISSING")
    anchor = "    handle_path /api/* {"
    anchor_at = text.find(anchor, site_start)
    if anchor_at < 0:
        raise RuntimeError("ALIMI_GENERIC_API_ANCHOR_MISSING")
    route = "\n".join([
        "    " + ROUTE_BEGIN,
        "    handle /api/view_contract_latest.json {",
        "        root * /var/www/z-os-alimi/api",
        "        rewrite * /q4r3_exact25_shadow_view_contract_latest.json",
        "        header Content-Type \"application/json\"",
        "        file_server",
        "    }",
        "    " + ROUTE_END,
        "",
    ])
    return text[:anchor_at] + route + text[anchor_at:], 1


def patch_telegram_source(text: str) -> tuple[str, int]:
    pattern = re.compile(r"(?P<q>['\"])(?P<path>[^'\"]*telegram_pos_status_latest\.json)(?P=q)")
    replacement_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replacement_count
        replacement_count += 1
        quote = match.group("q")
        return f"{quote}{NEW_TELEGRAM_SOURCE}{quote}"

    patched = pattern.sub(replace, text)
    if replacement_count == 0:
        raise RuntimeError("TELEGRAM_STATUS_LITERAL_NOT_FOUND")
    return patched, replacement_count


def unit_text(snapshot: Path, alimi_template: Path, telegram_template: Path,
              alimi_output: Path, telegram_output: Path) -> str:
    return "\n".join([
        "[Unit]",
        "Description=ZEL Q4R3 Exact25 single-source display adapter",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=oneshot",
        "ExecStart=/usr/local/bin/zel_q4r3_exact25_display_adapter.py "
        f"--snapshot {snapshot} --alimi-template {alimi_template} "
        f"--telegram-template {telegram_template} --alimi-output {alimi_output} "
        f"--telegram-output {telegram_output}",
        "User=root",
        "Group=root",
        "UMask=0022",
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=full",
        "ReadWritePaths=/home/z/z/runtime/exact25_edge_v1/display_adapter /var/www/z-os-alimi/api",
        "",
    ])


def path_unit_text(snapshot: Path) -> str:
    return "\n".join([
        "[Unit]",
        "Description=Watch Exact25 Shadow aggregate snapshot",
        "",
        "[Path]",
        f"PathChanged={snapshot}",
        "Unit=zel-q4r3-exact25-display-adapter.service",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])


def restore_file(path: Path, backup: Path | None, existed: bool) -> None:
    if existed and backup and backup.exists():
        shutil.copy2(backup, path)
    elif not existed:
        path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--adapter-source", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    snapshot = Path(contract["source_snapshot"])
    parent_status = Path(contract["parent_status"])
    caddy = Path(contract["caddy_path"])
    telegram_source = Path(contract["telegram_source"])
    adapter_target = Path(contract["adapter_script"])
    runtime = Path(contract["adapter_runtime"])
    alimi_output = Path(contract["alimi_output"])
    telegram_output = Path(contract["telegram_output"])
    service_file = Path("/etc/systemd/system") / contract["display_service"]
    path_file = Path("/etc/systemd/system") / contract["display_path_unit"]
    alimi_template = runtime / "templates/alimi_legacy_schema_template.json"
    telegram_template = runtime / "templates/telegram_legacy_schema_template.json"
    backup_root = runtime / "rollback/r73b4t"
    backup_root.mkdir(parents=True, exist_ok=True)
    blockers: list[str] = []
    mutations: list[str] = []
    rollback_performed = False

    required = [snapshot, parent_status, caddy, telegram_source, args.adapter_source]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        blockers.append("REQUIRED_INPUT_MISSING:" + ",".join(missing))
    if blockers:
        atomic_json(args.status, {"state": "HOLD", "blockers": blockers, "mutation_count": 0})
        return 2

    snap = json.loads(snapshot.read_text(encoding="utf-8"))
    parent = json.loads(parent_status.read_text(encoding="utf-8"))
    if snap.get("sample_count") != 0 or snap.get("closed_count") != 0:
        blockers.append("SNAPSHOT_NOT_ZERO_EPOCH")
    if snap.get("runtime_active") is not False or snap.get("formal_ledger_bound") is not False:
        blockers.append("SNAPSHOT_AUTHORITY_INVALID")
    if parent.get("state") != "PASS" or parent.get("mutation_count") != 0:
        blockers.append("R73B4S3_PARENT_INVALID")
    if blockers:
        atomic_json(args.status, {"state": "HOLD", "blockers": blockers, "mutation_count": 0})
        return 2

    ledger = Path("/home/z/z/runtime/exact25_edge_v1/formal_exact5_measurement/forward_r_ledger.jsonl")
    ledger_before = sha256(ledger) if ledger.is_file() else ""
    backup_map: dict[Path, tuple[Path | None, bool]] = {}
    for path in (caddy, telegram_source, adapter_target, service_file, path_file, alimi_output, telegram_output):
        existed = path.exists()
        backup = backup_root / path.as_posix().lstrip("/") if existed else None
        if existed and backup:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        backup_map[path] = (backup, existed)

    try:
        endpoint_status, endpoint_payload = fetch_json(contract["alimi_endpoint"])
        if endpoint_status != 200 or not endpoint_payload:
            raise RuntimeError("ALIMI_TEMPLATE_FETCH_FAILED")
        atomic_json(alimi_template, endpoint_payload)
        source_text = telegram_source.read_text(encoding="utf-8")
        source_template = locate_telegram_template(source_text)
        if source_template is None:
            raise RuntimeError("TELEGRAM_TEMPLATE_NOT_FOUND")
        shutil.copy2(source_template, telegram_template)

        shutil.copy2(args.adapter_source, adapter_target)
        adapter_target.chmod(0o755)
        mutations.append("DISPLAY_ADAPTER_INSTALLED")

        adapter_run = run([
            str(adapter_target), "--snapshot", str(snapshot),
            "--alimi-template", str(alimi_template), "--telegram-template", str(telegram_template),
            "--alimi-output", str(alimi_output), "--telegram-output", str(telegram_output),
        ], check=False)
        if adapter_run.returncode != 0:
            raise RuntimeError("DISPLAY_ADAPTER_INITIAL_RUN_FAILED:" + adapter_run.stderr[-300:])
        mutations.extend(["ALIMI_ZERO_OUTPUT_WRITTEN", "TELEGRAM_ZERO_OUTPUT_WRITTEN"])

        caddy_patched, route_count = patch_caddy(caddy.read_text(encoding="utf-8"))
        atomic_text(caddy, caddy_patched)
        mutations.append("CADDY_EXACT_ROUTE_PATCHED")
        validation = run(["caddy", "validate", "--config", str(caddy)], check=False)
        if validation.returncode != 0:
            raise RuntimeError("CADDY_VALIDATE_FAILED:" + validation.stderr[-300:])

        telegram_patched, replacement_count = patch_telegram_source(source_text)
        atomic_text(telegram_source, telegram_patched, 0o755)
        mutations.append("TELEGRAM_SOURCE_DIRECTLY_REWIRED")

        atomic_text(service_file, unit_text(snapshot, alimi_template, telegram_template, alimi_output, telegram_output))
        atomic_text(path_file, path_unit_text(snapshot))
        mutations.extend(["DISPLAY_SERVICE_INSTALLED", "DISPLAY_PATH_UNIT_INSTALLED"])
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", contract["display_path_unit"]])
        run(["systemctl", "start", contract["display_service"]])
        run(["systemctl", "reload", "caddy"])
        run(["systemctl", "restart", contract["telegram_unit"]])
        mutations.extend(["DISPLAY_PATH_ENABLED", "CADDY_RELOADED", "TELEGRAM_RESTARTED"])

        time.sleep(2)
        http_status, endpoint = fetch_json(contract["alimi_endpoint"])
        telegram = json.loads(telegram_output.read_text(encoding="utf-8"))
        if http_status != 200:
            raise RuntimeError("ALIMI_ENDPOINT_NOT_200")
        if int(endpoint.get("closed_count", -1)) != 0 or float(endpoint.get("pnl_r", -1.0)) != 0.0:
            raise RuntimeError("ALIMI_ZERO_EPOCH_PARITY_FAILED")
        if int(telegram.get("closed_count", -1)) != 0 or float(telegram.get("pnl_r", -1.0)) != 0.0:
            raise RuntimeError("TELEGRAM_ZERO_EPOCH_PARITY_FAILED")
        live_source = telegram_source.read_text(encoding="utf-8")
        if NEW_TELEGRAM_SOURCE not in live_source:
            raise RuntimeError("TELEGRAM_NEW_SOURCE_MISSING")
        stale_literals = re.findall(r"['\"]([^'\"]*telegram_pos_status_latest\.json)['\"]", live_source)
        if stale_literals:
            raise RuntimeError("TELEGRAM_STALE_SOURCE_STILL_ACTIVE")
        if ledger_before and sha256(ledger) != ledger_before:
            raise RuntimeError("FORMAL_LEDGER_CHANGED")

        payload = {
            "schema": "q4r3_exact25_r73b4t_explicit_binding_canary_status_v1",
            "state": "PASS",
            "blockers": [],
            "blocker_count": 0,
            "mutation_count": len(mutations),
            "mutations": mutations,
            "rollback_performed": False,
            "rollback_ready_count": 4,
            "alimi_route_insert_count": route_count,
            "telegram_source_replacement_count": replacement_count,
            "endpoint_http_status": http_status,
            "endpoint_closed_count": endpoint.get("closed_count"),
            "endpoint_pnl_r": endpoint.get("pnl_r"),
            "telegram_closed_count": telegram.get("closed_count"),
            "telegram_pnl_r": telegram.get("pnl_r"),
            "display_source": telegram.get("display_source"),
            "formal_ledger_change_count": 0,
            "runtime_active": False,
            "next_stage": contract["next_stage"],
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    except Exception as exc:
        blockers.append(str(exc))
        rollback_performed = True
        run(["systemctl", "disable", "--now", contract["display_path_unit"]], check=False)
        for path, (backup, existed) in backup_map.items():
            try:
                restore_file(path, backup, existed)
            except OSError:
                blockers.append(f"ROLLBACK_FILE_FAILED:{path}")
        run(["systemctl", "daemon-reload"], check=False)
        run(["caddy", "validate", "--config", str(caddy)], check=False)
        run(["systemctl", "reload", "caddy"], check=False)
        run(["systemctl", "restart", contract["telegram_unit"]], check=False)
        payload = {
            "schema": "q4r3_exact25_r73b4t_explicit_binding_canary_status_v1",
            "state": "HOLD",
            "blockers": blockers,
            "blocker_count": len(blockers),
            "mutation_count": len(mutations),
            "mutations": mutations,
            "rollback_performed": rollback_performed,
            "rollback_ready_count": 4,
            "runtime_active": False,
            "next_stage": "R7.3B4T_DIAGNOSE",
        }
        atomic_json(args.status, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
