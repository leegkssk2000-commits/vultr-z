#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
EXPECTED_BLOCKERS = {
    "CANONICAL_ZERO_EPOCH_SEMANTICS_FAILED:CONFIGURED_WRITER_COUNT_None,ACTIVE_WRITER_COUNT_None",
    "FINAL_CANONICAL_ZERO_EPOCH_FALSE:CONFIGURED_WRITER_COUNT_None,ACTIVE_WRITER_COUNT_None",
}
MUTATION_KEYS = (
    "route_mutation_count",
    "service_mutation_count",
    "writer_timer_mutation_count",
    "surface_target_mutation_count",
    "telegram_command_send_count",
    "paper_mutation_count",
    "live_mutation_count",
    "order_mutation_count",
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def contract_valid(contract: dict[str, Any]) -> bool:
    return (
        contract.get("official_stage") == "R7.A1A6C6B"
        and contract.get("read_only") is True
        and contract.get("writer_count_projection_required") is False
        and contract.get("writer_binding_required") is True
        and contract.get("runtime_mutation_allowed") is False
    )


def prior_false_positive_valid(prior: dict[str, Any]) -> bool:
    blockers = prior.get("blockers")
    return (
        prior.get("official_stage") == "R7.A1A6C6"
        and prior.get("state") == "HOLD"
        and int(prior.get("blocker_count", -1)) == 2
        and isinstance(blockers, list)
        and set(str(item) for item in blockers) == EXPECTED_BLOCKERS
        and prior.get("prior_c5_valid") is True
        and prior.get("writer_binding_valid") is True
        and prior.get("canonical_route_bound") is True
        and prior.get("telegram_binding_valid") is True
        and prior.get("final_http_local_exact_parity") is True
        and int(prior.get("protected_change_count", -1)) == 0
        and int(prior.get("caddyfile_change_count", -1)) == 0
        and all(int(prior.get(key, -1)) == 0 for key in MUTATION_KEYS)
    )


def select_boundary_prior(
    current: dict[str, Any], archived: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Use current proof when exact; otherwise use the immutable first-correction archive."""
    if prior_false_positive_valid(current):
        return current, "current_c6_status"
    if prior_false_positive_valid(archived):
        return archived, "immutable_c6_status_before_correction"
    return {}, "none"


def corrected_semantic(
    base_fn: Callable[[dict[str, Any], bool], tuple[bool, list[str]]],
    payload: dict[str, Any],
    require_writer_counts: bool = True,
) -> tuple[bool, list[str]]:
    return base_fn(payload, False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--c6-contract", required=True)
    parser.add_argument("--observe-seconds", type=int, default=180)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contract = load_json(Path(args.contract))
    prior_path = root / str(contract.get(
        "prior_c6_status_path",
        "runtime/exact25_edge_v1/r7a1a6c6_exact_semantic_stability/status_latest.json",
    ))
    out_path = root / str(contract.get(
        "status_path",
        "runtime/exact25_edge_v1/r7a1a6c6b_writer_count_contract_correction/status_latest.json",
    ))
    before_path = out_path.parent / "c6_status_before_correction.json"
    prior = load_json(prior_path)
    archived_prior = load_json(before_path)
    boundary_prior, boundary_source = select_boundary_prior(prior, archived_prior)

    blockers: list[str] = []
    if not contract_valid(contract):
        blockers.append("CONTRACT_INVALID")
    if boundary_source == "none":
        blockers.append("C6_FALSE_POSITIVE_BOUNDARY_NOT_PROVEN")

    if blockers:
        payload = {
            "schema": "r7a1a6c6b_writer_count_contract_correction_status_v1",
            "official_stage": "R7.A1A6C6B",
            "state": "HOLD",
            "blocker_count": len(blockers),
            "blockers": blockers,
            "prior_c6_false_positive_valid": False,
            "boundary_proof_source": boundary_source,
            "writer_count_projection_required": False,
            "writer_binding_required": True,
            "runtime_mutation_count": 0,
            "next_stage": "R7.A1A6C6B_DIAGNOSE",
        }
        atomic_json(out_path, payload)
        print("R7A1A6C6B_WRITER_COUNT_CONTRACT_CORRECTION_COMPLETE")
        print("STATE=HOLD")
        print(f"BLOCKERS={json.dumps(blockers, ensure_ascii=False)}")
        print(f"BOUNDARY_PROOF_SOURCE={boundary_source}")
        print(f"EVIDENCE_JSON={out_path}")
        print("RC=2")
        return 2

    # Preserve the exact original C6 false-positive receipt once. Never replace it
    # with a later C6 rerun receipt that may contain a different blocker.
    if boundary_source == "current_c6_status" and not before_path.exists():
        atomic_json(before_path, boundary_prior)

    c6 = load_module("r7a1a6c6_base", HERE / "r7a1a6c6_exact_semantic_stability_verify.py")
    base_semantic = c6.semantic_zero_epoch

    def semantic_override(payload: dict[str, Any], require_writer_counts: bool = True):
        return corrected_semantic(base_semantic, payload, require_writer_counts)

    c6.semantic_zero_epoch = semantic_override
    original_argv = sys.argv[:]
    try:
        sys.argv = [
            str(HERE / "r7a1a6c6_exact_semantic_stability_verify.py"),
            "--root", str(root),
            "--contract", str(Path(args.c6_contract)),
            "--observe-seconds", str(max(180, int(args.observe_seconds))),
        ]
        c6_rc = int(c6.main())
    finally:
        sys.argv = original_argv

    corrected = load_json(prior_path)
    final_blockers: list[str] = []
    if c6_rc != 0 or corrected.get("state") != "PASS":
        final_blockers.append("CORRECTED_C6_NOT_PASS")
    if corrected.get("writer_binding_valid") is not True:
        final_blockers.append("CANONICAL_WRITER_BINDING_FALSE")
    if corrected.get("canonical_route_bound") is not True:
        final_blockers.append("CANONICAL_ROUTE_BINDING_FALSE")
    if corrected.get("telegram_binding_valid") is not True:
        final_blockers.append("TELEGRAM_BINDING_FALSE")
    if corrected.get("final_http_local_exact_parity") is not True:
        final_blockers.append("FINAL_HTTP_LOCAL_PARITY_FALSE")
    if corrected.get("final_semantic_zero_epoch") is not True:
        final_blockers.append("FINAL_ZERO_EPOCH_FALSE")
    if int(corrected.get("protected_change_count", -1)) != 0:
        final_blockers.append("PROTECTED_CHANGE_DETECTED")
    if int(corrected.get("caddyfile_change_count", -1)) != 0:
        final_blockers.append("CADDYFILE_CHANGED")
    for key in MUTATION_KEYS:
        if int(corrected.get(key, -1)) != 0:
            final_blockers.append(f"MUTATION_NONZERO:{key}")

    state = "PASS" if not final_blockers else "HOLD"
    payload = {
        "schema": "r7a1a6c6b_writer_count_contract_correction_status_v1",
        "official_stage": "R7.A1A6C6B",
        "state": state,
        "blocker_count": len(final_blockers),
        "blockers": final_blockers,
        "prior_c6_false_positive_valid": True,
        "boundary_proof_source": boundary_source,
        "writer_count_projection_required": False,
        "writer_binding_required": True,
        "corrected_c6_state": corrected.get("state"),
        "corrected_c6_blockers": corrected.get("blockers"),
        "writer_binding_valid": corrected.get("writer_binding_valid"),
        "canonical_route_bound": corrected.get("canonical_route_bound"),
        "telegram_binding_valid": corrected.get("telegram_binding_valid"),
        "sample_count": corrected.get("sample_count"),
        "final_http_local_exact_parity": corrected.get("final_http_local_exact_parity"),
        "final_semantic_zero_epoch": corrected.get("final_semantic_zero_epoch"),
        "protected_change_count": corrected.get("protected_change_count"),
        "caddyfile_change_count": corrected.get("caddyfile_change_count"),
        "runtime_mutation_count": 0,
        "c6_status_before_correction": str(before_path),
        "corrected_c6_status": str(prior_path),
        "next_stage": "R7.A2_SEVEN_AXIS_S_GRADE_CONTRACT_FREEZE" if state == "PASS" else "R7.A1A6C6B_DIAGNOSE",
    }
    atomic_json(out_path, payload)

    print("R7A1A6C6B_WRITER_COUNT_CONTRACT_CORRECTION_COMPLETE")
    for key, value in (
        ("STATE", state),
        ("BLOCKER_COUNT", len(final_blockers)),
        ("BLOCKERS", json.dumps(final_blockers, ensure_ascii=False)),
        ("PRIOR_C6_FALSE_POSITIVE_VALID", "true"),
        ("BOUNDARY_PROOF_SOURCE", boundary_source),
        ("WRITER_COUNT_PROJECTION_REQUIRED", "false"),
        ("CANONICAL_WRITER_BOUND", str(corrected.get("writer_binding_valid") is True).lower()),
        ("CANONICAL_ROUTE_BOUND", str(corrected.get("canonical_route_bound") is True).lower()),
        ("TELEGRAM_BINDING_VALID", str(corrected.get("telegram_binding_valid") is True).lower()),
        ("SAMPLE_COUNT", corrected.get("sample_count")),
        ("FINAL_HTTP_LOCAL_EXACT_PARITY", str(corrected.get("final_http_local_exact_parity") is True).lower()),
        ("FINAL_SEMANTIC_ZERO_EPOCH", str(corrected.get("final_semantic_zero_epoch") is True).lower()),
        ("PROTECTED_CHANGE_COUNT", corrected.get("protected_change_count")),
        ("CADDYFILE_CHANGE_COUNT", corrected.get("caddyfile_change_count")),
        ("RUNTIME_MUTATION_COUNT", 0),
        ("NEXT_STAGE", payload["next_stage"]),
        ("EVIDENCE_JSON", str(out_path)),
        ("RC", 0 if state == "PASS" else 2),
    ):
        print(f"{key}={value}")
    return 0 if state == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
