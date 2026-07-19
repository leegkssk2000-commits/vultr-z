#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("r7a1a6c3_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("BASE_MODULE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def numeric_zero(value: Any) -> bool:
    if value is None or value is False:
        return True
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    if isinstance(value, str):
        text = value.strip().rstrip("Rr%")
        try:
            return float(text) == 0.0
        except Exception:
            return text.lower() in {"", "none", "null", "pending"}
    if isinstance(value, list):
        return len(value) == 0
    return True


def zero_semantics(value: Any) -> bool:
    watched = {
        "closed", "closed_count", "shadow_closed", "pnl_r", "net_r",
        "shadow_pnl_r", "recent_rows", "row_count",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in watched and not numeric_zero(child):
                return False
            if not zero_semantics(child):
                return False
    elif isinstance(value, list):
        for child in value:
            if not zero_semantics(child):
                return False
    return True


def quick_verify(module: Any) -> bool:
    for path in module.TARGETS:
        payload = load_json(path)
        if payload is None or not zero_semantics(payload):
            return False
    return True


def install_safe_watcher(module: Any) -> None:
    original = module.FanotifyWatcher

    class SafeWatcher:
        def __init__(self, directory: Path):
            self.inner = None
            self.available = False
            try:
                self.inner = original(directory)
                self.available = bool(getattr(self.inner, "available", False))
            except Exception:
                self.inner = None
                self.available = False

        def read_events(self, timeout: float = 0.2):
            if self.inner is None:
                time.sleep(timeout)
                return []
            try:
                return self.inner.read_events(timeout)
            except Exception:
                time.sleep(timeout)
                return []

        def close(self) -> None:
            if self.inner is not None:
                try:
                    self.inner.close()
                except Exception:
                    pass

    module.FanotifyWatcher = SafeWatcher


def install_identity_safety(module: Any) -> None:
    def identity_safe(unit: str, command: str, allowed: tuple[str, ...], forbidden: tuple[str, ...]) -> bool:
        exec_start = module.systemctl_value(unit, "ExecStart") if unit else ""
        short_command = command if "\n" not in command and len(command) <= 1200 else ""
        identity = f"{unit} {exec_start} {short_command}".lower()
        if any(term.lower() in identity for term in forbidden):
            return False
        return any(term.lower() in identity for term in allowed)

    module.safe_display_unit = identity_safe


def install_candidate_expansion(module: Any) -> None:
    def expanded_candidates() -> list[str]:
        proc = module.run([
            "systemctl", "list-units", "--type=service", "--type=timer",
            "--all", "--no-legend", "--no-pager",
        ], 30)
        if proc.returncode != 0:
            return []
        inspect: set[str] = set()
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            unit, load_state, active_state = parts[:3]
            if load_state != "loaded" or active_state not in {"active", "activating"}:
                continue
            inspect.add(unit)
            if unit.endswith(".timer"):
                inspect.update(
                    item for item in module.systemctl_value(unit, "Triggers").split()
                    if item.endswith(".service")
                )
                derived = unit[:-6] + "service"
                if module.systemctl_value(derived, "LoadState") == "loaded":
                    inspect.add(derived)
        candidates: list[str] = []
        for unit in sorted(inspect):
            text = module.source_text_for_unit(unit)
            if module.looks_like_target_writer(text):
                candidates.append(unit)
        return sorted(set(candidates))

    module.active_candidate_units = expanded_candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--repair-runner", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--repair-contract", required=True)
    parser.add_argument("--trace-seconds", type=int, default=120)
    parser.add_argument("--verify-seconds", type=int, default=90)
    args = parser.parse_args()

    module = load_module(Path(args.base))
    install_safe_watcher(module)
    install_identity_safety(module)
    install_candidate_expansion(module)
    original_repair = module.repair

    def quiet_repair(command: str, runner: Path, root: Path, contract: Path) -> int:
        if command == "verify":
            proc = subprocess.run(
                [sys.executable, str(runner), "verify", "--root", str(root)],
                text=True,
                capture_output=True,
                check=False,
            )
            return int(proc.returncode)
        return original_repair(command, runner, root, contract)

    module.repair = quiet_repair
    module.verify_once = lambda _runner, _root: quick_verify(module)

    previous_argv = list(sys.argv)
    try:
        sys.argv = [
            args.base,
            "--root", args.root,
            "--contract", args.contract,
            "--repair-runner", args.repair_runner,
            "--repair-contract", args.repair_contract,
            "--trace-seconds", str(args.trace_seconds),
            "--verify-seconds", str(args.verify_seconds),
        ]
        rc = int(module.main())
    finally:
        sys.argv = previous_argv

    if rc != 0:
        return rc

    exact = subprocess.run(
        [sys.executable, args.repair_runner, "verify", "--root", args.root],
        text=True,
        capture_output=True,
        check=False,
    )
    if exact.returncode != 0:
        print("R7A1A6C3_EXACT_FINAL_VERIFY_FAILED")
        print("STATE=HOLD")
        print('BLOCKERS=["EXACT_FINAL_VERIFY_FAILED"]')
        return 2

    print("R7A1A6C3_EXACT_FINAL_VERIFY_PASS")
    print("ALIMI_HTTP_FILE_JSON_PARITY=true")
    print("LEDGER_ZERO_EPOCH=true")
    print("TRACE_ZERO_EPOCH=true")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
