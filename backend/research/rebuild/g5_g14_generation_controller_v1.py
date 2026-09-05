#!/usr/bin/env python3
"""Deterministic fail-closed G5 -> G6 gate controller.

Creates no trading/economic authority. Runtime evidence is allowed to evolve
under schema/content validation; only terminal acceptance is exact-blob pinned.
G6 unlocks only after an explicit, independently reviewed G5 terminal PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
REBUILD = ROOT / "backend" / "research" / "rebuild"
OUT = REBUILD / "g5_g14_generation_controller_receipt_v1.json"

STAGES = [
    "CONTRACT_VALID",
    "AUTHORITY_INPUTS_PRESENT",
    "AUTHORITY_BINDING_POLICY_VALID",
    "CLEAN_RUNNER_SHADOW_PASS",
    "TELEMETRY_COMPLETE",
    "DATA_STALE_AUTHORITY_VALID",
    "CUTOVER_AND_POST_CUTOVER_READY",
    "GENUINE_ECONOMIC_T_PRESENT",
    "G5_TERMINAL_PASS",
]

RUNTIME_PIN_POLICIES = {
    "RUNTIME_MUTABLE_SCHEMA_AND_INTERNAL_INTEGRITY",
    "APPENDABLE_EVIDENCE_SCHEMA_AND_ROW_INTEGRITY",
}
EXACT_PIN_POLICY = "EXACT_GIT_BLOB"
UNLOCK_RULE = "LANE_LOCAL_G5B_G6_G7_THROUGH_G8_GLOBAL_FROM_G9"
INDEPENDENCE_FIELDS = ("N_raw", "N_effective", "unique_signal_days", "unique_symbols", "regime_count", "largest_same_window_cluster")


def independence_audit_passes(audit: Any) -> bool:
    if not isinstance(audit, dict) or audit.get("validated") is not True:
        return False
    if not audit.get("source_sha256") or not audit.get("cluster_method"):
        return False
    if any(not numeric(audit.get(k)) or not math.isfinite(audit[k]) or audit[k] < 0 for k in INDEPENDENCE_FIELDS):
        return False
    n = audit["N_raw"]
    if any(audit[k] > n for k in INDEPENDENCE_FIELDS[1:]):
        return False
    if any(not isinstance(audit[k], int) for k in INDEPENDENCE_FIELDS if k != "N_effective"):
        return False
    if n > 0 and any(audit[k] <= 0 for k in INDEPENDENCE_FIELDS[1:]):
        return False
    # The largest correlated cluster can contribute at most one independent T.
    if n > 0 and audit["N_effective"] > n - audit["largest_same_window_cluster"] + 1:
        return False
    return True


def lane_terminal_errors(terminal: Any, *, lane_identity: dict[str, Any], stage: str,
                         gate: dict[str, Any], reviewed_blob_sha: str | None,
                         observed_blob_sha: str | None) -> list[str]:
    if not isinstance(terminal, dict):
        return ["EXPLICIT_TERMINAL_RECEIPT_MISSING"]
    errors = []
    if not reviewed_blob_sha or observed_blob_sha != reviewed_blob_sha:
        errors.append("TERMINAL_REVIEW_PIN_MISSING_OR_DRIFT")
    if terminal.get("stage") != stage or gate.get("stage") != stage:
        errors.append("TERMINAL_STAGE_MISMATCH")
    for key in ("lane_id", "candidate_id", "boundary_id"):
        if not lane_identity.get(key) or terminal.get(key) != lane_identity[key]:
            errors.append("TERMINAL_IDENTITY_MISMATCH:" + key)
    if not gate or not terminal_receipt_passes(terminal, gate):
        errors.append("FROZEN_TERMINAL_GATE_NOT_PASS")
    if not independence_audit_passes(terminal.get("independence_audit")):
        errors.append("INDEPENDENCE_AUDIT_MISSING_OR_INVALID")
    return errors


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 1
    rows: list[dict[str, Any]] = []
    errors = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], 1
    for raw in lines:
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            errors += 1
            continue
        if isinstance(item, dict):
            rows.append(item)
        else:
            errors += 1
    return rows, errors


def git_blob_sha_bytes(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def git_blob_sha(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return git_blob_sha_bytes(path.read_bytes())
    except OSError:
        return None


def numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def finish(
    *,
    state: str,
    next_action: str,
    completed: list[str],
    failed_gate: str | None,
    observed_hashes: dict[str, str | None],
    manifest: dict[str, Any],
    genuine_rows: int = 0,
) -> dict[str, Any]:
    fingerprint = hashlib.sha256(
        json.dumps(observed_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    terminal = state == "G5_TERMINAL_PASS"
    return {
        "schema_version": "zel.g5_g14.generation_controller_receipt.v3",
        "controller_mode": "DETERMINISTIC_NO_PAID_AI_FAIL_CLOSED",
        "current_generation": 5,
        "state": state,
        "completed_stages": completed,
        "completed_stage_count": len(completed),
        "next_gate": failed_gate,
        "next_action": next_action,
        "g5_terminal_pass": terminal,
        "g6_allowed": terminal and bool(manifest.get("lane_identity")),
        "lane_identity": manifest.get("lane_identity"),
        "unlock_scope": "SAME_LANE_ONLY",
        "g6_stage": "TRADE_METHOD_STANDALONE",
        "g5_responsibility": "EDGE_QUALIFICATION",
        "g5_rr_formal_credit_allowed": False,
        "g6_fresh_formal_credit_required": True,
        "fresh_credit_granted": False,
        "strategy_mutated": False,
        "rr_mutated": False,
        "authority_created_by_controller": False,
        "cutover_automatic": False,
        "genuine_economic_rows": genuine_rows,
        "source_master_commit": manifest.get("source_master_commit"),
        "observed_blob_shas": observed_hashes,
        "input_fingerprint": fingerprint,
        "selection_authority": False, "promotion_authority": False,
        "execution_authority": "NONE", "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED", "exchange_order_submitted": False,
    }


def terminal_receipt_passes(terminal: dict[str, Any], gate: dict[str, Any]) -> bool:
    if terminal.get("schema_version") != gate.get("required_schema_version"):
        return False
    if terminal.get("state") != gate.get("required_state"):
        return False
    for key in gate.get("required_true", []):
        if terminal.get(key) is not True:
            return False
    for key in gate.get("required_false", []):
        if terminal.get(key) is not False:
            return False

    integrity = terminal.get("integrity")
    if not isinstance(integrity, dict):
        return False
    for key, expected in gate.get("integrity_equals", {}).items():
        if integrity.get(key) != expected:
            return False

    limits = gate.get("economic_window_thresholds", {})
    windows = terminal.get("windows")
    if not isinstance(windows, dict):
        return False
    checks = (
        ("net_r", "net_r_gt", lambda a, b: a > b),
        ("pf", "pf_gte", lambda a, b: a >= b),
        ("expectancy", "expectancy_gt", lambda a, b: a > b),
        ("payoff", "payoff_gte", lambda a, b: a >= b),
        ("retention_pct", "retention_pct_gte", lambda a, b: a >= b),
    )
    for window in ("W1", "W2", "W3"):
        metric = windows.get(window)
        if not isinstance(metric, dict):
            return False
        for metric_key, limit_key, comparator in checks:
            value = metric.get(metric_key)
            limit = limits.get(limit_key)
            if not numeric(value) or not numeric(limit) or not comparator(value, limit):
                return False
    return True


def validate_binding_policies(
    specs: dict[str, Any],
    required: tuple[str, ...],
    observed_hashes: dict[str, str | None],
) -> list[str]:
    errors: list[str] = []
    for name in required:
        spec = specs.get(name, {})
        policy = spec.get("pin_policy")
        if policy in RUNTIME_PIN_POLICIES:
            continue
        if policy == EXACT_PIN_POLICY:
            expected = spec.get("blob_sha")
            if not expected or observed_hashes.get(name) != expected:
                errors.append(name)
            continue
        errors.append(name)
    return errors


def evaluate(
    *,
    contract: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    records: dict[str, dict[str, Any] | None],
    ledger_rows: list[dict[str, Any]],
    ledger_parse_errors: int,
    observed_hashes: dict[str, str | None],
    terminal: dict[str, Any] | None,
    terminal_blob_sha: str | None,
) -> dict[str, Any]:
    contract = contract or {}
    manifest = manifest or {}
    completed: list[str] = []

    if (
        contract.get("schema_version") != "zel.g5_g14.shared_validation_contract.v2"
        or manifest.get("schema_version") != "zel.g5_g14.shared_validation_manifest.v3"
        or contract.get("generation_unlock_rule") != UNLOCK_RULE
        or contract.get("cutover", {}).get("automatic") is not False
        or contract.get("shared_invariants", {}).get("fresh_credit_fail_closed") is not True
    ):
        return finish(
            state="HARD_FAIL_CONTRACT_OR_MANIFEST",
            next_action="repair_contract_or_manifest_only",
            completed=completed,
            failed_gate=STAGES[0],
            observed_hashes=observed_hashes,
            manifest=manifest,
        )
    completed.append(STAGES[0])

    specs = manifest.get("authority_files", {})
    required = ("shadow", "telemetry", "data_stale", "cutover", "economic_ledger")
    if any(name not in specs for name in required):
        return finish(
            state="HARD_FAIL_MANIFEST",
            next_action="repair_manifest_only",
            completed=completed,
            failed_gate=STAGES[1],
            observed_hashes=observed_hashes,
            manifest=manifest,
        )

    for name in ("shadow", "telemetry", "data_stale", "cutover"):
        rec = records.get(name)
        if not isinstance(rec, dict) or rec.get("schema_version") != specs[name].get("schema_version"):
            return finish(
                state="HARD_FAIL_AUTHORITY_INPUT",
                next_action=f"restore_exact_{name}_authority",
                completed=completed,
                failed_gate=STAGES[1],
                observed_hashes=observed_hashes,
                manifest=manifest,
            )
    ledger_schema = specs["economic_ledger"].get("schema_version")
    ledger_schema_error = any(row.get("schema_version") != ledger_schema for row in ledger_rows)
    if observed_hashes.get("economic_ledger") is None or ledger_parse_errors or ledger_schema_error:
        return finish(
            state="HARD_FAIL_ECONOMIC_LEDGER",
            next_action="repair_economic_ledger_integrity",
            completed=completed,
            failed_gate=STAGES[1],
            observed_hashes=observed_hashes,
            manifest=manifest,
        )
    completed.append(STAGES[1])

    binding_errors = validate_binding_policies(specs, required, observed_hashes)
    if binding_errors:
        return finish(
            state="HARD_FAIL_AUTHORITY_BINDING_POLICY",
            next_action="repair_authority_binding_policy:" + ",".join(sorted(binding_errors)),
            completed=completed,
            failed_gate=STAGES[2],
            observed_hashes=observed_hashes,
            manifest=manifest,
        )
    completed.append(STAGES[2])

    shadow = records["shadow"] or {}
    if not (
        shadow.get("state") == "CLEAN_RUNNER_SHADOW_PASS"
        and shadow.get("shadow_3bar_pass") is True
        and shadow.get("source_parity") is True
        and shadow.get("child_parity") is True
        and shadow.get("duplicate") == 0
        and shadow.get("lookahead") == 0
    ):
        return finish(
            state="WAIT_CLEAN_RUNNER_SHADOW_PASS",
            next_action="continue_clean_runner_shadow_no_credit",
            completed=completed,
            failed_gate=STAGES[3],
            observed_hashes=observed_hashes,
            manifest=manifest,
        )
    completed.append(STAGES[3])

    telemetry = records["telemetry"] or {}
    complete_tuples = telemetry.get("complete_tuples")
    if not (
        telemetry.get("missing_tuples") == 0
        and isinstance(complete_tuples, int)
        and not isinstance(complete_tuples, bool)
        and complete_tuples > 0
    ):
        return finish(
            state="WAIT_COMPLETE_TELEMETRY",
            next_action="collect_complete_telemetry_no_credit",
            completed=completed,
            failed_gate=STAGES[4],
            observed_hashes=observed_hashes,
            manifest=manifest,
        )
    completed.append(STAGES[4])

    stale = records["data_stale"] or {}
    authority_value = stale.get("authority_value")
    stale_ok = (
        stale.get("authority_created") is True
        and stale.get("data_stale_authority_allowed") is True
        and numeric(authority_value)
        and authority_value > 0
        and stale.get("authority_unit") == "ms"
        and stale.get("timestamp_integrity") == "PASS"
    )
    if not stale_ok:
        return finish(
            state="WAIT_DATA_STALE_AUTHORITY",
            next_action=stale.get(
                "next", "collect_real_labeled_failure_evidence_before_threshold_surface"
            ),
            completed=completed,
            failed_gate=STAGES[5],
            observed_hashes=observed_hashes,
            manifest=manifest,
        )
    completed.append(STAGES[5])

    cutover = records["cutover"] or {}
    if not (
        cutover.get("automatic_cutover") is False
        and cutover.get("executed") is True
        and cutover.get("clean_runner_authority") is True
        and cutover.get("production_ready") is True
        and shadow.get("post_cutover_3bar_pass") is True
    ):
        return finish(
            state="WAIT_CUTOVER_OR_POST_CUTOVER_3BAR",
            next_action="manual_cutover_then_collect_3_post_cutover_genuine_bars",
            completed=completed,
            failed_gate=STAGES[6],
            observed_hashes=observed_hashes,
            manifest=manifest,
        )
    completed.append(STAGES[6])

    proxy_rows_do_not_count = contract.get("genuine_economic_t", {}).get("proxy_rows_do_not_count") is True
    genuine_rows = sum(
        1
        for row in ledger_rows
        if row.get("production_grade") is True
        and (not proxy_rows_do_not_count or "PROXY" not in str(row.get("economic_origin", "")).upper())
        and (not manifest.get("lane_identity") or all(row.get(k) == v for k, v in manifest["lane_identity"].items()))
    )
    min_rows = int(contract.get("genuine_economic_t", {}).get("min_production_grade_rows", 1))
    if genuine_rows < min_rows:
        return finish(
            state="WAIT_GENUINE_ECONOMIC_T",
            next_action="accumulate_production_grade_genuine_economic_T",
            completed=completed,
            failed_gate=STAGES[7],
            observed_hashes=observed_hashes,
            manifest=manifest,
            genuine_rows=genuine_rows,
        )
    completed.append(STAGES[7])

    terminal_spec = manifest.get("terminal_receipt", {})
    pinned_terminal_sha = terminal_spec.get("blob_sha")
    if terminal is None:
        return finish(
            state="WAIT_G5_TERMINAL_RECEIPT",
            next_action="run_independent_OOS_walk_forward_stress_validation",
            completed=completed,
            failed_gate=STAGES[8],
            observed_hashes=observed_hashes,
            manifest=manifest,
            genuine_rows=genuine_rows,
        )
    if terminal_spec.get("pin_policy") != "EXACT_GIT_BLOB_AFTER_INDEPENDENT_REVIEW":
        return finish(
            state="HARD_FAIL_G5_TERMINAL_PIN_POLICY",
            next_action="restore_exact_terminal_pin_policy",
            completed=completed,
            failed_gate=STAGES[8],
            observed_hashes=observed_hashes,
            manifest=manifest,
            genuine_rows=genuine_rows,
        )
    if not pinned_terminal_sha:
        return finish(
            state="WAIT_G5_TERMINAL_RECEIPT_PIN",
            next_action="review_and_pin_terminal_receipt_blob_sha",
            completed=completed,
            failed_gate=STAGES[8],
            observed_hashes=observed_hashes,
            manifest=manifest,
            genuine_rows=genuine_rows,
        )
    if terminal_blob_sha != pinned_terminal_sha:
        return finish(
            state="HARD_FAIL_G5_TERMINAL_SHA_DRIFT",
            next_action="reject_unpinned_terminal_receipt",
            completed=completed,
            failed_gate=STAGES[8],
            observed_hashes=observed_hashes,
            manifest=manifest,
            genuine_rows=genuine_rows,
        )
    if not terminal_receipt_passes(terminal, contract.get("g5_terminal_gate", {})):
        return finish(
            state="WAIT_G5_TERMINAL_PASS",
            next_action="record_G5_FAIL_or_continue_only_approved_validation_axis",
            completed=completed,
            failed_gate=STAGES[8],
            observed_hashes=observed_hashes,
            manifest=manifest,
            genuine_rows=genuine_rows,
        )

    lane_errors = lane_terminal_errors(
        terminal, lane_identity=manifest.get("lane_identity") or {}, stage="G5B",
        gate=contract.get("g5_terminal_gate", {}), reviewed_blob_sha=pinned_terminal_sha,
        observed_blob_sha=terminal_blob_sha,
    )
    if lane_errors:
        return finish(state="WAIT_LANE_BOUND_G5B_TERMINAL", next_action=";".join(lane_errors),
                      completed=completed, failed_gate=STAGES[8], observed_hashes=observed_hashes,
                      manifest=manifest, genuine_rows=genuine_rows)

    completed.append(STAGES[8])
    return finish(
        state="G5_TERMINAL_PASS",
        next_action="enter_G6_trade_method_standalone_with_fresh_candidate_freeze_boundary",
        completed=completed,
        failed_gate=None,
        observed_hashes=observed_hashes,
        manifest=manifest,
        genuine_rows=genuine_rows,
    )


def evaluate_lanes(inputs_by_lane: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Each lane consumes its own frozen identity, terminal pin and ledger slice."""
    results = {}
    for lane, inputs in inputs_by_lane.items():
        if inputs.get("manifest", {}).get("lane_identity", {}).get("lane_id") != lane:
            results[lane] = {"state": "HARD_FAIL_LANE_IDENTITY", "g6_allowed": False}
        else:
            results[lane] = evaluate(**inputs)
    return results


def derive(root: Path = ROOT) -> dict[str, Any]:
    rebuild = root / "backend" / "research" / "rebuild"
    contract = read_json(rebuild / "g5_g14_shared_validation_contract_v1.json")
    manifest = read_json(rebuild / "g5_g14_shared_validation_manifest_v1.json") or {}

    records: dict[str, dict[str, Any] | None] = {}
    observed_hashes: dict[str, str | None] = {}
    ledger_rows: list[dict[str, Any]] = []
    ledger_errors = 0

    for name, spec in manifest.get("authority_files", {}).items():
        path = root / spec.get("path", "")
        observed_hashes[name] = git_blob_sha(path)
        if name == "economic_ledger":
            ledger_rows, ledger_errors = read_jsonl(path)
        else:
            records[name] = read_json(path)

    terminal_spec = manifest.get("terminal_receipt", {})
    terminal_path = root / terminal_spec.get(
        "path", "backend/research/rebuild/g5_independent_validation_terminal_receipt_v1.json"
    )
    terminal = read_json(terminal_path)
    terminal_blob_sha = git_blob_sha(terminal_path)

    return evaluate(
        contract=contract,
        manifest=manifest,
        records=records,
        ledger_rows=ledger_rows,
        ledger_parse_errors=ledger_errors,
        observed_hashes=observed_hashes,
        terminal=terminal,
        terminal_blob_sha=terminal_blob_sha,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    receipt = derive()
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.write:
        OUT.write_text(text, encoding="utf-8")
    print(text, end="")
    return 1 if receipt["state"].startswith("HARD_FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
