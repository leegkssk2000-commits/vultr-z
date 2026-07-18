#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "q4r3_exact25_r73b4t_explicit_binding_canary.py"

spec = importlib.util.spec_from_file_location("r73b4t_base", BASE)
if spec is None or spec.loader is None:
    raise SystemExit("R73B4T_BASE_LOAD_FAILED")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_run = module.run


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


module.run = run

if __name__ == "__main__":
    raise SystemExit(module.main())
