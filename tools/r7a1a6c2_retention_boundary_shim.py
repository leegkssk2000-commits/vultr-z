#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_IMPORT_FAILED_{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


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
            if str(key).lower() in keys and child is not None:
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


def unique_nested(value: Any, keys: set[str]) -> tuple[Any, ...]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in keys:
                candidate = normalized_scalar(child)
                if candidate not in found:
                    found.append(candidate)
            for candidate in unique_nested(child, keys):
                if candidate not in found:
                    found.append(candidate)
    elif isinstance(value, list):
        for child in value:
            for candidate in unique_nested(child, keys):
                if candidate not in found:
                    found.append(candidate)
    return tuple(sorted(found, key=lambda item: str(item)))


def semantic_subset(payload: dict[str, Any], parity: Any) -> dict[str, Any]:
    configured, _active = parity.writer_counts(payload)
    return {
        "order_authority": unique_nested(payload, {"order_authority"}),
        "execution_authority": unique_nested(payload, {"execution_authority"}),
        "real_order_enabled": unique_nested(payload, {"real_order_enabled"}),
        "configured_writer_count": configured,
        "closed": normalized_scalar(first_nested(payload, {"closed", "closed_count", "shadow_closed"})),
        "pnl_r": normalized_scalar(first_nested(payload, {"pnl_r", "net_r", "shadow_pnl_r"})),
    }


def safe_subset(value: dict[str, Any]) -> bool:
    return (
        value.get("order_authority") == ("blocked",)
        and value.get("execution_authority") == ("none",)
        and value.get("real_order_enabled") == (False,)
        and value.get("configured_writer_count") == 7
    )


def semantic_surface_equal(http_payload: dict[str, Any], file_payload: dict[str, Any], parity: Any) -> bool:
    if not http_payload or not file_payload:
        return False
    left = semantic_subset(http_payload, parity)
    right = semantic_subset(file_payload, parity)
    return safe_subset(left) and safe_subset(right) and left == right


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--router-runner", required=True)
    parser.add_argument("--source-shim", required=True)
    parser.add_argument("--source-cutover-runner", required=True)
    parser.add_argument("--parity-helper", required=True)
    parser.add_argument("--source-contract", required=True)
    parser.add_argument("--router-contract", required=True)
    parser.add_argument("--boundary-contract", required=True)
    parser.add_argument("--command-timeout", type=int, default=120)
    args = parser.parse_args()

    boundary = load_json(Path(args.boundary_contract))
    if boundary.get("official_stage") != "R7.A1A6C2":
        print("R7A1A6C2_RETENTION_BOUNDARY_FAILED")
        print('BLOCKERS=["BOUNDARY_CONTRACT_INVALID"]')
        return 2

    root = Path(args.root).resolve()
    router = load_module("r7a1a6a_router", Path(args.router_runner))
    source_shim = load_module("r7a1a6a2_source_shim", Path(args.source_shim))
    original_loader = router.load_module

    router.critical_views_equal = semantic_surface_equal

    def patched_loader(name: str, path: Path):
        module = original_loader(name, path)
        if name == "r7a1a5_base":
            current_source = source_shim.select_current_source(module.process_cmdline())
            module.LEGACY_SOURCE = current_source
            gate_state = source_shim.install_first_gate_recovery(module, root)
            module._r7a1a6c2_gate_state = gate_state
            print(f"CURRENT_EXEC_SOURCE={current_source}")
        return module

    router.load_module = patched_loader
    previous_argv = list(sys.argv)
    try:
        sys.argv = [
            args.router_runner,
            "--root", str(root),
            "--sha", args.sha,
            "--source-cutover-runner", args.source_cutover_runner,
            "--parity-helper", args.parity_helper,
            "--source-contract", args.source_contract,
            "--router-contract", args.router_contract,
            "--command-timeout", str(max(30, args.command_timeout)),
        ]
        print("RETENTION_BOUNDARY=TELEGRAM_COMMAND_SOURCE_SAFETY")
        print("VOLATILE_ACTIVE_WRITER_EXCLUDED=true")
        print("POST_CUTOVER_EXACT_PARITY_GATE=R7.A1A6C_VERIFY")
        return int(router.main())
    finally:
        sys.argv = previous_argv


if __name__ == "__main__":
    raise SystemExit(main())
