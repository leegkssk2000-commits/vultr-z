from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_EXACT25_IDENTITY_INDICATOR_AUDIT_V1"
SCHEMA = "zel.exact25.identity_indicator.audit.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def strategy_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    metrics = row.get("closed_metrics_including_funding_estimate")
    if not isinstance(metrics, Mapping):
        metrics = row.get("closed_metrics_ex_funding")
    if not isinstance(metrics, Mapping):
        metrics = {}
    return {
        "trade_count": int(row.get("close_count") or metrics.get("sample_count") or 0),
        "net_R": number(metrics.get("net_R")),
        "profit_factor": number(metrics.get("profit_factor")),
        "max_drawdown_R": number(metrics.get("max_drawdown_R")),
        "win_rate_pct": number(metrics.get("win_rate_pct")),
        "signal_count": int(row.get("signal_count") or 0),
        "valid_entry_count": int(row.get("valid_entry_count") or 0),
        "failure_fingerprint": row.get("failure_fingerprint"),
        "claim_tier": row.get("claim_tier"),
    }


def authority_for(strategy_id: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    override = (policy.get("authority_overrides") or {}).get(strategy_id)
    if isinstance(override, Mapping):
        return dict(override)
    return dict(policy["default_authority"])


def validate_optimizer_authority(
    strategy_id: str,
    authority: Mapping[str, Any],
    optimizer_policy: Mapping[str, Any] | None,
) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if authority.get("mode") != "SEALED_RESEARCH_AUTHORITY":
        return True, blockers
    if optimizer_policy is None:
        return False, ["SEALED_RESEARCH_OPTIMIZER_POLICY_MISSING"]
    if optimizer_policy.get("strategy_id") != strategy_id:
        blockers.append("OPTIMIZER_STRATEGY_ID_MISMATCH")
    candidate = optimizer_policy.get("authority")
    if not isinstance(candidate, Mapping):
        blockers.append("OPTIMIZER_AUTHORITY_OBJECT_MISSING")
        return False, blockers
    expected_pairs = {
        "profit_control": authority.get("profit_control"),
        "robust_control": authority.get("robust_control"),
        "payoff_reference": authority.get("payoff_reference"),
        "alpha_code_ref": authority.get("required_source_ref"),
        "baseline_artifact_run_id": authority.get("required_baseline_run_id"),
        "multiobjective_run_id": authority.get("required_multiobjective_run_id"),
    }
    for key, expected in expected_pairs.items():
        if str(candidate.get(key)) != str(expected):
            blockers.append(f"OPTIMIZER_AUTHORITY_MISMATCH:{key}")
    if candidate.get("raw_canonical_exact25_is_diagnostic_only") is not True:
        blockers.append("RAW_EXACT25_DIAGNOSTIC_BOUNDARY_MISSING")
    return not blockers, blockers


def compatible_axes(row: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    sample = int(row["metrics"]["trade_count"])
    if sample == 0:
        return []
    if row.get("authority_mode") == "SEALED_RESEARCH_AUTHORITY":
        return []
    history = (policy.get("strategy_axis_history") or {}).get(str(row.get("strategy_id")), {})
    tested = set(history.get("tested_axis_ids") or []) if isinstance(history, Mapping) else set()
    return [
        dict(axis)
        for axis in policy.get("indicator_axes", [])
        if isinstance(axis, Mapping) and str(axis.get("axis_id")) not in tested
    ]


def queue_priority(row: Mapping[str, Any]) -> tuple[float, int, str]:
    metrics = row["metrics"]
    net = number(metrics.get("net_R"))
    sample = int(metrics.get("trade_count") or 0)
    return (net, -sample, str(row["strategy_id"]))


def run_audit(
    policy: Mapping[str, Any],
    terminal: Mapping[str, Any],
    optimizer_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    expected = policy["terminal_authority"]
    checkpoint = terminal.get("checkpoint") if isinstance(terminal.get("checkpoint"), Mapping) else {}
    fields = checkpoint.get("input_fingerprint_fields") if isinstance(checkpoint.get("input_fingerprint_fields"), Mapping) else {}
    replay = terminal.get("replay") if isinstance(terminal.get("replay"), Mapping) else {}
    scorecards = [row for row in terminal.get("scorecards", []) if isinstance(row, Mapping)]

    global_checks = {
        "terminal_schema": terminal.get("schema_version") == expected["expected_schema_version"],
        "strategy_count": int(replay.get("strategy_count_completed") or 0) == int(expected["expected_strategy_count"]),
        "scorecard_count": len(scorecards) == int(expected["expected_strategy_count"]),
        "closed_trade_count": int(replay.get("closed_trade_count") or 0) == int(expected["expected_closed_trade_count"]),
        "error_count": int(replay.get("error_count") or 0) == int(expected["expected_error_count"]),
        "censored_open_count": int(replay.get("censored_open_at_window_end") or 0) == int(expected["expected_censored_open_count"]),
        "owner_manifest_sha256": fields.get("owner_manifest_sha256") == expected["owner_manifest_sha256"],
        "strategy_tree_sha256": fields.get("strategy_tree_sha256") == expected["strategy_tree_sha256"],
        "producer_sha256": fields.get("producer_sha256") == expected["producer_sha256"],
        "execution_authority": terminal.get("execution_authority") == "NONE",
        "order_authority": terminal.get("order_authority") == "BLOCKED",
        "promotion_authority": terminal.get("promotion_authority") is False,
    }

    ids = [str(row.get("strategy_id") or "") for row in scorecards]
    duplicate_ids = sorted({value for value in ids if value and ids.count(value) > 1})
    rows: list[dict[str, Any]] = []
    quarantined: list[str] = []
    owner_groups: dict[str, list[str]] = {}
    for raw in scorecards:
        strategy_id = str(raw.get("strategy_id") or "")
        owner_sha = str(raw.get("owner_sha256") or "")
        authority = authority_for(strategy_id, policy)
        blockers: list[str] = []
        if not strategy_id:
            blockers.append("STRATEGY_ID_MISSING")
        if strategy_id in duplicate_ids:
            blockers.append("STRATEGY_ID_DUPLICATE")
        if not HEX64.fullmatch(owner_sha):
            blockers.append("OWNER_SHA256_INVALID")
        authority_ok, authority_blockers = validate_optimizer_authority(
            strategy_id, authority, optimizer_policy if strategy_id == "alpha_combo" else None
        )
        if not authority_ok:
            blockers.extend(authority_blockers)
        if owner_sha:
            owner_groups.setdefault(owner_sha, []).append(strategy_id)
        metrics = strategy_metrics(raw)
        identity = {
            "strategy_id": strategy_id,
            "owner_sha256": owner_sha,
            "owner_manifest_sha256": fields.get("owner_manifest_sha256"),
            "strategy_tree_sha256": fields.get("strategy_tree_sha256"),
            "producer_sha256": fields.get("producer_sha256"),
            "authority_mode": authority.get("mode"),
            "optimizer_profile": authority.get("optimizer_profile"),
        }
        state = "PASS_STRATEGY_IDENTITY_BOUND" if not blockers else policy["identity_rules"]["quarantine_state"]
        if blockers:
            quarantined.append(strategy_id or "<missing>")
        row = {
            **identity,
            "identity_sha256": stable_sha(identity),
            "metrics": metrics,
            "authority": authority,
            "state": state,
            "blockers": blockers,
            "optimizer_eligible": not blockers and metrics["trade_count"] > 0,
        }
        row["compatible_axes"] = [axis["axis_id"] for axis in compatible_axes(row, policy)] if row["optimizer_eligible"] else []
        rows.append(row)

    shared_owner_groups = [
        {"owner_sha256": owner, "strategy_ids": sorted(values)}
        for owner, values in sorted(owner_groups.items())
        if len(values) > 1
    ]
    trade_sum = sum(int(row["metrics"]["trade_count"]) for row in rows)
    global_checks["scorecard_trade_sum"] = trade_sum == int(expected["expected_closed_trade_count"])
    global_checks["unique_strategy_ids"] = len(set(ids)) == int(expected["expected_strategy_count"]) and not duplicate_ids
    global_checks["all_owner_sha256_present"] = all(HEX64.fullmatch(str(row["owner_sha256"])) for row in rows)
    global_checks["no_quarantine"] = not quarantined

    eligible = sorted([row for row in rows if row["optimizer_eligible"]], key=queue_priority)
    queue: list[dict[str, Any]] = []
    for index, row in enumerate(eligible):
        axes = row["compatible_axes"]
        if not axes:
            continue
        axis_id = axes[int(stable_sha({"strategy_id": row["strategy_id"], "index": index})[:8], 16) % len(axes)]
        queue.append({
            "priority": len(queue) + 1,
            "strategy_id": row["strategy_id"],
            "identity_sha256": row["identity_sha256"],
            "authority_mode": row["authority_mode"],
            "optimizer_profile": row["optimizer_profile"],
            "axis_id": axis_id,
            "operation": "ADD_OR_REMOVE_FILTER",
            "one_axis_only": True,
            "w1_select_then_freeze_w2_w3": True,
            "exact_source_replay_required": True,
            "state": "READY_FOR_GEMINI_DESIGN_AND_RED_TEAM",
        })

    state = "PASS_EXACT25_IDENTITY_AND_INDICATOR_QUEUE_READY" if all(global_checks.values()) else "HOLD_EXACT25_IDENTITY_OR_AUTHORITY_MISMATCH"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "global_checks": global_checks,
        "strategy_count": len(rows),
        "trade_count": trade_sum,
        "quarantined_strategy_ids": sorted(quarantined),
        "shared_owner_sha_groups_for_review": shared_owner_groups,
        "strategies": sorted(rows, key=lambda row: row["strategy_id"]),
        "experiment_queue": queue,
        "indicator_axis_count": len(policy.get("indicator_axes", [])),
        "one_axis_per_epoch": policy["queue_rules"]["one_strategy_one_axis_per_epoch"],
        "gemini_freeform_axis_forbidden": policy["queue_rules"]["gemini_freeform_axis_forbidden"],
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "RUN_GEMINI_DESIGN_RED_TEAM_THEN_BUILD_ONE_AXIS_CHILD_REPLAY" if state.startswith("PASS") else "QUARANTINE_MISMATCHES_AND_REPAIR_IDENTITY_FIRST",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test(policy: Mapping[str, Any]) -> int:
    scorecards = []
    for index in range(25):
        strategy_id = "alpha_combo" if index == 0 else f"strategy_{index:02d}"
        scorecards.append({
            "strategy_id": strategy_id,
            "owner_sha256": hashlib.sha256(strategy_id.encode()).hexdigest(),
            "close_count": 1 if index < 24 else 1927,
            "signal_count": 10,
            "valid_entry_count": 1,
            "failure_fingerprint": "NEGATIVE_OR_UNSTABLE_OOS_EDGE",
            "claim_tier": "COMPONENT_RESEARCH_REVIEW",
            "closed_metrics_including_funding_estimate": {
                "sample_count": 1 if index < 24 else 1927,
                "net_R": -1.0,
                "profit_factor": 0.5,
                "max_drawdown_R": 2.0,
                "win_rate_pct": 40.0,
            },
        })
    terminal = {
        "schema_version": policy["terminal_authority"]["expected_schema_version"],
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "promotion_authority": False,
        "checkpoint": {"input_fingerprint_fields": {
            "owner_manifest_sha256": policy["terminal_authority"]["owner_manifest_sha256"],
            "strategy_tree_sha256": policy["terminal_authority"]["strategy_tree_sha256"],
            "producer_sha256": policy["terminal_authority"]["producer_sha256"],
        }},
        "replay": {
            "strategy_count_completed": 25,
            "closed_trade_count": 1951,
            "error_count": 0,
            "censored_open_at_window_end": 0,
        },
        "scorecards": scorecards,
    }
    optimizer = {
        "strategy_id": "alpha_combo",
        "authority": {
            "profit_control": "TIME54",
            "robust_control": "TIME60",
            "payoff_reference": "STOP065_PROFIT_CONTROL",
            "alpha_code_ref": "r7a4d-strategy11-alpha-primary-w1-multiobjective-v1",
            "baseline_artifact_run_id": "30252022416",
            "multiobjective_run_id": "30345463070",
            "raw_canonical_exact25_is_diagnostic_only": True,
        },
    }
    result = run_audit(policy, terminal, optimizer)
    assert result["state"] == "PASS_EXACT25_IDENTITY_AND_INDICATOR_QUEUE_READY", result
    assert result["quarantined_strategy_ids"] == []
    assert len(result["strategies"]) == 25
    assert len(result["experiment_queue"]) == 24
    assert result["indicator_axis_count"] >= 15
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--optimizer-policy", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    policy = read_json(args.policy)
    if args.self_test:
        return self_test(policy)
    if args.terminal is None or args.out is None:
        parser.error("--terminal and --out are required")
    optimizer = read_json(args.optimizer_policy) if args.optimizer_policy else None
    receipt = run_audit(policy, read_json(args.terminal), optimizer)
    write_json(args.out / "latest.json", receipt)
    print(json.dumps({
        "state": receipt["state"],
        "strategy_count": receipt["strategy_count"],
        "quarantine_count": len(receipt["quarantined_strategy_ids"]),
        "queue_count": len(receipt["experiment_queue"]),
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0 if receipt["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
