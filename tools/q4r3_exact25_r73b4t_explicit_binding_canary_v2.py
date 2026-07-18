#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "q4r3_exact25_r73b4t_explicit_binding_canary.py"

spec = importlib.util.spec_from_file_location("r73b4t_base", BASE)
if spec is None or spec.loader is None:
    raise SystemExit("R73B4T_BASE_LOAD_FAILED")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_run = module.run
original_patch_caddy = module.patch_caddy


def run(command: list[str], check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    if command == ["systemctl", "reload", "caddy"]:
        direct = subprocess.run(
            ["caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if direct.returncode == 0:
            return direct
        restart = subprocess.run(
            ["systemctl", "restart", "caddy"],
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if restart.returncode == 0:
            active = subprocess.run(
                ["systemctl", "is-active", "--quiet", "caddy"],
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            if active.returncode == 0:
                return restart
        stderr = (
            "CADDY_DIRECT_RELOAD_FAILED=" + direct.stderr[-500:] +
            "; CADDY_RESTART_FAILED=" + restart.stderr[-500:]
        )
        failed = subprocess.CompletedProcess(command, 1, stdout=direct.stdout + restart.stdout, stderr=stderr)
        if check:
            raise subprocess.CalledProcessError(1, command, output=failed.stdout, stderr=failed.stderr)
        return failed
    return original_run(command, check=check, timeout=timeout)


def fetch_json(url: str) -> tuple[int, dict]:
    separator = "&" if "?" in url else "?"
    probe_url = f"{url}{separator}r73b4t={time.time_ns()}"
    command = [
        "curl", "-sS", "-L", "--max-time", "15",
        "-H", "Cache-Control: no-cache",
        "-w", "\n%{http_code}",
    ]
    if url.startswith("https://alimi.z-os.vip/"):
        command.extend(["--resolve", "alimi.z-os.vip:443:127.0.0.1"])
    command.append(probe_url)
    result = subprocess.run(command, text=True, capture_output=True, timeout=20)
    body, _, code = result.stdout.rpartition("\n")
    try:
        status = int(code or 0)
    except ValueError:
        status = 0
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}
    if result.returncode != 0 and status == 0:
        return 0, {}
    return status, payload if isinstance(payload, dict) else {}


def patch_caddy(text: str) -> tuple[str, int]:
    patched, count = original_patch_caddy(text)
    marker = '        header Content-Type "application/json"'
    cache_header = '        header Cache-Control "no-store, no-cache, must-revalidate"'
    if module.ROUTE_BEGIN in patched and cache_header not in patched:
        patched = patched.replace(marker, marker + "\n" + cache_header, 1)
    return patched, count


module.run = run
module.fetch_json = fetch_json
module.patch_caddy = patch_caddy

if __name__ == "__main__":
    raise SystemExit(module.main())
