from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import zel_alpha_unattended_champion_v2 as v2

VERSION = "ZEL_ALPHA_UNATTENDED_CHAMPION_V3"
SCHEMA = "zel.alpha.unattended_champion.receipt.v3"


def require_identity(path: Path) -> dict[str, Any]:
    receipt = v2.read_json(path)
    if receipt.get("state") != "PASS_EXACT25_IDENTITY_AND_INDICATOR_QUEUE_READY":
        raise RuntimeError("EXACT25_IDENTITY_PREFLIGHT_NOT_PASS")
    if int(receipt.get("strategy_count") or 0) != 25:
        raise RuntimeError("EXACT25_IDENTITY_STRATEGY_COUNT_MISMATCH")
    if int(receipt.get("trade_count") or 0) != 1951:
        raise RuntimeError("EXACT25_IDENTITY_TRADE_COUNT_MISMATCH")
    if receipt.get("quarantined_strategy_ids"):
        raise RuntimeError("EXACT25_IDENTITY_QUARANTINE_NONEMPTY")
    alpha = next(
        (row for row in receipt.get("strategies", []) if row.get("strategy_id") == "alpha_combo"),
        None,
    )
    if not isinstance(alpha, dict):
        raise RuntimeError("ALPHA_IDENTITY_ROW_MISSING")
    if alpha.get("authority_mode") != "SEALED_RESEARCH_AUTHORITY":
        raise RuntimeError("ALPHA_AUTHORITY_MODE_MISMATCH")
    if alpha.get("optimizer_profile") != "ALPHA_TIME54_TIME60_STOP065":
        raise RuntimeError("ALPHA_OPTIMIZER_PROFILE_MISMATCH")
    authority = alpha.get("authority") if isinstance(alpha.get("authority"), dict) else {}
    if authority.get("raw_exact25_optimizer_forbidden") is not True:
        raise RuntimeError("RAW_EXACT25_ALPHA_BOUNDARY_MISSING")
    return receipt


def validate_restored_state(candidate: dict[str, Any], fingerprint: str) -> dict[str, Any]:
    if candidate.get("schema_version") != v2.STATE_SCHEMA:
        raise RuntimeError("RESTORED_STATE_SCHEMA_MISMATCH")
    if candidate.get("data_fingerprint") != fingerprint:
        raise RuntimeError("RESTORED_STATE_FINGERPRINT_MISMATCH")
    expected = str(candidate.get("receipt_sha256") or "")
    material = {key: value for key, value in candidate.items() if key != "receipt_sha256"}
    actual = v2.stable_sha(material)
    if not expected or expected != actual:
        raise RuntimeError("RESTORED_STATE_RECEIPT_SHA256_MISMATCH")
    if candidate.get("selection_authority") is not False:
        raise RuntimeError("RESTORED_STATE_SELECTION_AUTHORITY_INVALID")
    if candidate.get("promotion_authority") is not False:
        raise RuntimeError("RESTORED_STATE_PROMOTION_AUTHORITY_INVALID")
    if candidate.get("execution_authority") != "NONE":
        raise RuntimeError("RESTORED_STATE_EXECUTION_AUTHORITY_INVALID")
    if candidate.get("order_authority") != "BLOCKED":
        raise RuntimeError("RESTORED_STATE_ORDER_AUTHORITY_INVALID")
    if candidate.get("action") != "hold":
        raise RuntimeError("RESTORED_STATE_ACTION_INVALID")
    return candidate


def safety_fields(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity_receipt_sha256": identity.get("receipt_sha256"),
        "identity_preflight_state": identity.get("state"),
        "raw_canonical_exact25_used_as_control": False,
        "time54_time60_authority_restored": True,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "shadow_start_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def terminal_receipt(
    previous: dict[str, Any],
    fingerprint: str,
    identity: dict[str, Any],
) -> dict[str, Any]:
    champion = previous.get("champion_found") is True
    converged = previous.get("converged") is True
    state = (
        "PASS_ALPHA_CHAMPION_ALREADY_SEALED_FOR_RESEARCH_HOLDBACK"
        if champion
        else "WAIT_NEW_DATA_FINGERPRINT_ALPHA_CHAMPION_NOT_FOUND"
    )
    next_step = (
        "WAIT_SEALED_HOLDBACK_AND_NEW_FORWARD_CONFIRMATION"
        if champion
        else "WAIT_NEW_IMMUTABLE_DATA_THEN_RESET_SEARCH"
    )
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": "alpha_combo",
        "data_fingerprint": fingerprint,
        "champion": previous.get("best_metrics") if champion else None,
        "champion_config": previous.get("best_config") if champion else None,
        "champion_found": champion,
        "converged": converged,
        "next": next_step,
        **safety_fields(identity),
    }
    receipt["receipt_sha256"] = v2.stable_sha(receipt)
    return receipt


def self_test() -> int:
    identity = {
        "state": "PASS_EXACT25_IDENTITY_AND_INDICATOR_QUEUE_READY",
        "strategy_count": 25,
        "trade_count": 1951,
        "quarantined_strategy_ids": [],
        "receipt_sha256": "a" * 64,
        "strategies": [{
            "strategy_id": "alpha_combo",
            "authority_mode": "SEALED_RESEARCH_AUTHORITY",
            "optimizer_profile": "ALPHA_TIME54_TIME60_STOP065",
            "authority": {"raw_exact25_optimizer_forbidden": True},
        }],
    }
    temp = Path("/tmp/zel-alpha-v3-identity-self-test.json")
    v2.write_json(temp, identity)
    loaded = require_identity(temp)
    fingerprint = "b" * 64
    state = {
        "schema_version": v2.STATE_SCHEMA,
        "data_fingerprint": fingerprint,
        "champion_found": False,
        "converged": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    state["receipt_sha256"] = v2.stable_sha(state)
    validated = validate_restored_state(state, fingerprint)
    receipt = terminal_receipt(validated, fingerprint, loaded)
    assert receipt["state"] == "WAIT_NEW_DATA_FINGERPRINT_ALPHA_CHAMPION_NOT_FOUND"
    assert receipt["canonical_mutated"] is False
    assert receipt["raw_canonical_exact25_used_as_control"] is False
    corrupted = dict(state)
    corrupted["converged"] = False
    try:
        validate_restored_state(corrupted, fingerprint)
    except RuntimeError as exc:
        assert str(exc) == "RESTORED_STATE_RECEIPT_SHA256_MISMATCH"
    else:
        raise AssertionError("CORRUPTED_STATE_ACCEPTED")
    temp.unlink(missing_ok=True)
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-receipt", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--alpha-root", type=Path)
    parser.add_argument("--baseline-summary", type=Path)
    parser.add_argument("--multiobjective-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--previous-state", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.identity_receipt,
        args.policy,
        args.alpha_root,
        args.baseline_summary,
        args.multiobjective_root,
        args.data_root,
        args.out,
    )
    if any(value is None for value in required):
        parser.error("all runtime paths except previous-state are required")

    identity = require_identity(args.identity_receipt.resolve())
    fingerprint = v2.fingerprint(
        data_root=args.data_root.resolve(),
        baseline_path=args.baseline_summary.resolve(),
        authority_root=args.multiobjective_root.resolve(),
        policy_path=args.policy.resolve(),
    )
    previous: dict[str, Any] | None = None
    if args.previous_state and args.previous_state.is_file():
        candidate = v2.read_json(args.previous_state)
        previous = validate_restored_state(candidate, fingerprint)
    args.out.resolve().mkdir(parents=True, exist_ok=True)
    if previous and (
        previous.get("champion_found") is True or previous.get("converged") is True
    ):
        receipt = terminal_receipt(previous, fingerprint, identity)
        v2.write_json(args.out.resolve() / "latest.json", receipt)
        v2.write_json(args.out.resolve() / "state.json", previous)
        print(json.dumps({
            "state": receipt["state"],
            "champion_found": receipt["champion_found"],
            "converged": receipt["converged"],
        }, sort_keys=True))
        return 0

    forwarded = [
        "zel_alpha_unattended_champion_v2.py",
        "--policy", str(args.policy),
        "--alpha-root", str(args.alpha_root),
        "--baseline-summary", str(args.baseline_summary),
        "--multiobjective-root", str(args.multiobjective_root),
        "--data-root", str(args.data_root),
        "--out", str(args.out),
    ]
    if args.previous_state and args.previous_state.is_file():
        forwarded += ["--previous-state", str(args.previous_state)]
    old_argv = sys.argv
    try:
        sys.argv = forwarded
        code = v2.main()
    finally:
        sys.argv = old_argv
    if code != 0:
        return code
    receipt_path = args.out.resolve() / "latest.json"
    receipt = v2.read_json(receipt_path)
    receipt["schema_version"] = SCHEMA
    receipt["version"] = VERSION
    receipt.update(safety_fields(identity))
    receipt["receipt_sha256"] = v2.stable_sha({
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    })
    v2.write_json(receipt_path, receipt)
    print(json.dumps({
        "state": receipt.get("state"),
        "identity_preflight_state": receipt.get("identity_preflight_state"),
        "champion_found": receipt.get("champion_found"),
        "converged": receipt.get("converged"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
