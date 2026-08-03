from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

VERSION = "ZEL_STRATEGY_TERMINAL_DISPOSITION_V1"
SCHEMA = "zel.strategy.terminal_disposition.receipt.v1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify(policy: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    strategy_id = str(row.get("strategy_id") or "")
    pending = policy.get("pending_active_research") or {}
    metrics = (
        row.get("closed_metrics_including_funding_estimate")
        if isinstance(row.get("closed_metrics_including_funding_estimate"), dict)
        else {}
    )
    windows = row.get("by_window") if isinstance(row.get("by_window"), dict) else {}
    close_count = int(row.get("close_count") or 0)
    signal_count = int(row.get("signal_count") or 0)
    valid_entry_count = int(row.get("valid_entry_count") or 0)
    error_count = int(row.get("error_count") or 0)
    censored = int(row.get("censored_open_at_window_end") or 0)
    claim_tier = str(row.get("claim_tier") or "")
    failure = str(row.get("failure_fingerprint") or "")
    net_r = number(metrics.get("net_R"))
    pf = number(metrics.get("profit_factor"))
    expectancy = number(metrics.get("expectancy_R"))
    source_mismatch = bool(
        row.get("source_mismatch")
        or row.get("quarantined")
        or str(row.get("source_owner_state") or "").startswith("HOLD")
    )

    checks: dict[str, Any] = {
        "close_count": close_count,
        "signal_count": signal_count,
        "valid_entry_count": valid_entry_count,
        "error_count": error_count,
        "censored_open_count": censored,
        "net_R": net_r,
        "profit_factor": pf,
        "expectancy_R": expectancy,
        "required_windows_present": all(
            key in windows for key in policy["survivor_gate"]["required_windows"]
        ),
        "all_present_windows_positive": bool(windows) and all(
            (number(value.get("net_R")) or 0.0) > 0.0
            for value in windows.values()
            if isinstance(value, dict)
        ),
        "payoff_ratio_available": number(metrics.get("payoff_ratio")) is not None,
        "retention_available": number(row.get("retention_pct")) is not None,
        "source_owner_parity_available": row.get("source_owner_parity") is not None,
        "cost_lineage_available": row.get("cost_lineage_complete") is not None,
    }

    reason: str
    subtype: str | None = None
    if source_mismatch:
        disposition = "QUARANTINE_SOURCE_MISMATCH"
        reason = "source-owner mismatch or quarantine marker"
    elif strategy_id in pending:
        disposition = "PENDING_ACTIVE_RESEARCH"
        reason = "active exact research run has not produced a terminal artifact"
    elif close_count == 0 and signal_count == 0:
        disposition = "ZERO_SIGNAL_REPAIR"
        subtype = "NO_SIGNAL"
        reason = "zero closed trades and zero strategy signals"
    elif close_count == 0 and valid_entry_count == 0:
        disposition = "ZERO_SIGNAL_REPAIR"
        subtype = "SIGNAL_WITHOUT_VALID_ENTRY"
        reason = "signals existed but no valid entry survived the current gate"
    elif close_count == 0:
        disposition = "LOW_SAMPLE_REPAIR"
        subtype = "VALID_ENTRY_WITHOUT_CLOSE"
        reason = "valid entries existed but no terminal closed sample was produced"
    elif claim_tier == "ZERO_TRADES_HOLD":
        disposition = "ZERO_SIGNAL_REPAIR"
        reason = "terminal receipt classifies the strategy as zero-trade hold"
    elif claim_tier == "LOW_SAMPLE_HOLD":
        disposition = "LOW_SAMPLE_REPAIR"
        reason = "terminal receipt classifies the strategy as low-sample hold"
    else:
        full_economic = (
            net_r is not None and net_r > 0.0
            and pf is not None and pf >= 1.0
            and expectancy is not None and expectancy > 0.0
            and error_count == 0
            and censored == 0
            and checks["required_windows_present"]
            and checks["all_present_windows_positive"]
            and checks["payoff_ratio_available"]
            and checks["retention_available"]
            and checks["source_owner_parity_available"]
            and checks["cost_lineage_available"]
        )
        if full_economic:
            disposition = "SURVIVOR_CANDIDATE"
            reason = "all absolute economic, durability and lineage gates are present and positive"
        elif net_r is not None and net_r > 0.0:
            disposition = "RESERVE_CANDIDATE"
            reason = "final economics are positive but one or more sample, window or lineage gates are incomplete"
        elif claim_tier in {"COMPONENT_RESEARCH_REVIEW", "INTEGRATED_RESEARCH_REVIEW"}:
            disposition = "MATERIAL_ONLY"
            reason = "final economics are negative but the component retains bounded research value"
        else:
            disposition = "REJECT_CURRENT_EPOCH"
            reason = "final economics are non-positive and no active repair authority remains"

    return {
        "strategy_id": strategy_id,
        "disposition": disposition,
        "subtype": subtype,
        "reason": reason,
        "claim_tier": claim_tier,
        "failure_fingerprint": failure,
        "active_research_prs": list(pending.get(strategy_id) or []),
        "checks": checks,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }


def self_test() -> int:
    policy = {
        "pending_active_research": {"pending": [1]},
        "survivor_gate": {"required_windows": ["1m_w1", "1m_w2", "1m_w3"]},
    }
    zero = {"strategy_id": "zero", "close_count": 0, "signal_count": 0}
    assert classify(policy, zero)["disposition"] == "ZERO_SIGNAL_REPAIR"
    pending = {"strategy_id": "pending", "close_count": 10}
    assert classify(policy, pending)["disposition"] == "PENDING_ACTIVE_RESEARCH"
    negative = {
        "strategy_id": "negative",
        "close_count": 10,
        "claim_tier": "COMPONENT_RESEARCH_REVIEW",
        "closed_metrics_including_funding_estimate": {
            "net_R": -1.0, "profit_factor": 0.8, "expectancy_R": -0.1
        },
    }
    assert classify(policy, negative)["disposition"] == "MATERIAL_ONLY"
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.policy or not args.terminal or not args.out:
        parser.error("--policy, --terminal and --out are required")
    policy = read_json(args.policy)
    terminal = read_json(args.terminal)
    replay = terminal.get("replay") if isinstance(terminal.get("replay"), dict) else {}
    scorecards = terminal.get("scorecards") if isinstance(terminal.get("scorecards"), list) else []
    expected = int(policy["expected_strategy_count"])
    if len(scorecards) != expected:
        raise RuntimeError(f"STRATEGY_COUNT_MISMATCH:{len(scorecards)}:{expected}")
    if int(replay.get("closed_trade_count") or 0) != int(policy["expected_terminal_trade_count"]):
        raise RuntimeError("TERMINAL_TRADE_COUNT_MISMATCH")
    if int(replay.get("error_count") or 0) != 0:
        raise RuntimeError("TERMINAL_ERROR_COUNT_NONZERO")
    if int(replay.get("censored_open_at_window_end") or 0) != 0:
        raise RuntimeError("TERMINAL_CENSORED_OPEN_NONZERO")

    rows = [classify(policy, row) for row in scorecards if isinstance(row, dict)]
    rows.sort(key=lambda row: row["strategy_id"])
    allowed = set(policy["allowed_dispositions"])
    unknown = sorted({row["disposition"] for row in rows} - allowed)
    if unknown:
        raise RuntimeError("UNKNOWN_DISPOSITION:" + ",".join(unknown))
    counts = dict(sorted(Counter(row["disposition"] for row in rows).items()))
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_PROVISIONAL_25_STRATEGY_DISPOSITION",
        "terminal_receipt_sha256": terminal.get("receipt_sha256"),
        "terminal_generated_at": terminal.get("generated_at"),
        "strategy_count": len(rows),
        "closed_trade_count": replay.get("closed_trade_count"),
        "counts": counts,
        "pending_strategy_ids": [
            row["strategy_id"] for row in rows
            if row["disposition"] == "PENDING_ACTIVE_RESEARCH"
        ],
        "terminal_strategy_ids": [
            row["strategy_id"] for row in rows
            if row["disposition"] != "PENDING_ACTIVE_RESEARCH"
        ],
        "strategies": rows,
        "final": False,
        "final_blocker": "ACTIVE_RESEARCH_ARTIFACTS_559_560_562_AND_ALPHA_NOT_TERMINAL",
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": receipt["state"], "counts": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
