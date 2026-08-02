from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_RETIREMENT_CONSENSUS_ADJUDICATOR_V1"
SCHEMA = "zel.grid_retirement_consensus.receipt.v1"
RETIRE = "RETIRE_GRID_REBALANCE"


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def stable_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reconstruction", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    reconstruction = read_object(args.reconstruction)
    review = read_object(args.review)
    if reconstruction.get("state") != "PASS_GRID_ENTRY_REGIME_RECONSTRUCTED":
        raise RuntimeError("RECONSTRUCTION_NOT_PASS")
    if int(review.get("gemini_call_count") or 0) != 3:
        raise RuntimeError("GEMINI_CALL_COUNT_MISMATCH")

    auditor = review.get("auditor") if isinstance(review.get("auditor"), Mapping) else {}
    designer = review.get("designer") if isinstance(review.get("designer"), Mapping) else {}
    red_team = review.get("red_team") if isinstance(review.get("red_team"), Mapping) else {}
    decisions = {
        "auditor": str(auditor.get("recommended_next_test") or ""),
        "designer": str(designer.get("proposal") or ""),
        "red_team": str(red_team.get("decision") or ""),
    }
    statuses = {
        "auditor": str(auditor.get("status") or ""),
        "designer": str(designer.get("status") or ""),
        "red_team": str(red_team.get("status") or ""),
    }

    regime_metrics = reconstruction.get("reconstructed_regime_metrics")
    window_metrics = reconstruction.get("reconstructed_regime_window_metrics")
    if not isinstance(regime_metrics, Mapping) or not isinstance(window_metrics, Mapping):
        raise RuntimeError("REGIME_METRICS_MISSING")

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, actual: Any, expected: Any) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "actual": actual,
                "expected": expected,
            }
        )

    check(
        "three_way_retirement_decision",
        all(value == RETIRE for value in decisions.values()),
        decisions,
        RETIRE,
    )
    check(
        "safe_hold_or_pass_status",
        all(value in {"HOLD", "PASS"} for value in statuses.values()),
        statuses,
        ["HOLD", "PASS"],
    )
    check(
        "legacy_exit_neutral_rejected",
        review.get("legacy_exit_neutral_rejected") is True
        and auditor.get("legacy_exit_neutral_rejected") is True
        and red_team.get("legacy_exit_neutral_rejected") is True,
        {
            "review": review.get("legacy_exit_neutral_rejected"),
            "auditor": auditor.get("legacy_exit_neutral_rejected"),
            "red_team": red_team.get("legacy_exit_neutral_rejected"),
        },
        True,
    )

    aggregate_evidence: dict[str, Any] = {}
    for regime in ("range", "trend_long", "trend_short"):
        value = regime_metrics.get(regime)
        if not isinstance(value, Mapping):
            aggregate_evidence[regime] = None
            check(f"{regime}_metrics_present", False, None, "mapping")
            continue
        net_r = finite(value.get("net_R"))
        profit_factor = finite(value.get("profit_factor"))
        trade_count = int(value.get("trade_count") or 0)
        aggregate_evidence[regime] = {
            "trade_count": trade_count,
            "net_R": net_r,
            "profit_factor": profit_factor,
            "max_drawdown_R": finite(value.get("max_drawdown_R")),
        }
        check(
            f"{regime}_aggregate_negative",
            net_r is not None and net_r < 0,
            net_r,
            "<0R",
        )
        check(
            f"{regime}_profit_factor_below_one",
            profit_factor is not None and profit_factor < 1.0,
            profit_factor,
            "<1.0",
        )

    trend_window_evidence: dict[str, Any] = {}
    for regime in ("trend_long", "trend_short"):
        trend_window_evidence[regime] = {}
        for window in ("1m_w1", "1m_w2", "1m_w3"):
            value = window_metrics.get(f"{regime}|{window}")
            net_r = finite(value.get("net_R")) if isinstance(value, Mapping) else None
            trade_count = int(value.get("trade_count") or 0) if isinstance(value, Mapping) else 0
            trend_window_evidence[regime][window] = {
                "trade_count": trade_count,
                "net_R": net_r,
            }
            check(
                f"{regime}_{window}_negative",
                trade_count > 0 and net_r is not None and net_r < 0,
                trend_window_evidence[regime][window],
                "trade_count>0 and net_R<0R",
            )

    unanimous = all(row["passed"] for row in checks)
    blockers = [row["name"] for row in checks if not row["passed"]]
    state = (
        "PASS_GRID_REBALANCE_RETIREMENT_CONSENSUS"
        if unanimous
        else "HOLD_GRID_REBALANCE_RETIREMENT_NOT_PROVED"
    )
    decision = RETIRE if unanimous else "NEED_MORE_CAUSAL_EVIDENCE"
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": "grid_rebalance",
        "decision": decision,
        "three_way_unanimous": unanimous,
        "decision_trace": decisions,
        "status_trace": statuses,
        "aggregate_evidence": aggregate_evidence,
        "trend_window_evidence": trend_window_evidence,
        "checks": checks,
        "blockers": blockers,
        "retirement_scope": "RESEARCH_CANDIDATE_AND_FUTURE_REGIME_TUNING_ONLY",
        "canonical_strategy_status": "PRESERVE_FAIL_CLOSED_INACTIVE",
        "source_deleted": False,
        "production_applied": False,
        "next_research_allowed_for_grid_rebalance": False,
        "legacy_exit_neutral_filter_retired": True,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": (
            "MOVE_TO_EMA_RIBBON_INTRATRADE_PATH_REPLAY"
            if unanimous
            else "RESOLVE_RETIREMENT_EVIDENCE_BLOCKERS"
        ),
        "upstream_reconstruction_receipt_sha256": reconstruction.get("receipt_sha256"),
        "upstream_gemini_review_receipt_sha256": review.get("receipt_sha256"),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "state": state,
                "decision": decision,
                "unanimous": unanimous,
                "blockers": blockers,
                "next": receipt["next"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
