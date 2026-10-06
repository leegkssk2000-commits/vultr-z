"""Issue 1377 saved-ledger audit and pre-result candidate freeze.

This command never loads market bars and never replays an opportunity.  It
verifies the immutable Keltner/MR ledgers, explains the saved cost transition,
and writes the first deliverable plus the one allowed non-K candidate contract.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "research/campaigns/scalp7_20261006/issue1377_keltner_orthogonal_v1"
K_PATH = ROOT / (
    "research/campaigns/scalp7_20260915/broad_rebuild_v2/results/"
    "scalp7_keltner_hg_parent_utc30m_v2.trades.json.gz"
)
K_SHA256 = "8863caa8231282fbd7dfd5660811b74e007c018c9cdafdaa52c24830cddfd989"
MR_PATH = ROOT / (
    "research/campaigns/scalp7_20260915/broad_rebuild_v2/results_binding_repair/"
    "mr_cross_sectional_v1_30m_causal_control_v2.trades.json.gz"
)
MR_SHA256 = "9fb5cc0f15a1d95d2ca03f6f69c9c25c36addff45b5fbf010533a1c6f2d6e82d"
DEV_START_MS = 1_768_262_400_000  # 2026-01-13T00:00:00Z
DEV_END_MS = 1_781_654_400_000  # 2026-06-17T00:00:00Z


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def load(path: Path, expected: str) -> dict[str, Any]:
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"LEDGER_SHA256_MISMATCH:{path}:{actual}")
    with gzip.open(path, "rt") as handle:
        return json.load(handle)


def trade_id(row: dict[str, Any]) -> str:
    return f"{row['symbol']}:{row['signal_ts_ms']}:{row['side']}"


def stats(rows: list[dict[str, Any]], key: str) -> dict[str, float] | None:
    values = [float(row[key]) for row in rows]
    if not values:
        return None
    return {
        "min": min(values),
        "median": median(values),
        "mean": mean(values),
        "max": max(values),
    }


def counts(rows: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows).items()))


def summarize(rows: list[dict[str, Any]], multiplier: float) -> dict[str, Any]:
    nets = [float(row["gross_bps"]) - multiplier * float(row["cost_bps"]) for row in rows]
    wins = [value for value in nets if value > 0]
    losses = [-value for value in nets if value < 0]
    return {
        "T": len(rows),
        "Gross_bps": sum(float(row["gross_bps"]) for row in rows),
        "Cost_bps": multiplier * sum(float(row["cost_bps"]) for row in rows),
        "Net_bps": sum(nets),
        "Net_bps_T": sum(nets) / len(nets) if nets else None,
        "WR": len(wins) / len(nets) if nets else None,
        "PF": sum(wins) / sum(losses) if losses else None,
    }


def build() -> dict[str, Any]:
    k_payload = load(K_PATH, K_SHA256)
    k_rows = [row for row in k_payload["trades"] if row["partition"] == "rolling"]
    if len(k_rows) != 109:
        raise ValueError(f"KELTNER_ROLLING_COUNT_NOT_109:{len(k_rows)}")
    for row in k_rows:
        row["net2_bps"] = float(row["gross_bps"]) - 2.0 * float(row["cost_bps"])
        row["active_at_entry"] = sum(
            1
            for other in k_rows
            if other is not row
            and int(other["entry_ts_ms"]) <= int(row["entry_ts_ms"]) < int(other["exit_ts_ms"])
        )
    original_losses = [row for row in k_rows if float(row["net_bps"]) <= 0]
    transitions = [
        row for row in k_rows if float(row["net_bps"]) > 0 and row["net2_bps"] <= 0
    ]
    cost2_winners = [row for row in k_rows if row["net2_bps"] > 0]
    if (len(original_losses), len(transitions), len(cost2_winners)) != (44, 27, 38):
        raise ValueError("KELTNER_44_27_38_PARTITION_MISMATCH")
    positive_1x = sorted(
        (row for row in k_rows if float(row["net_bps"]) > 0),
        key=lambda row: float(row["net_bps"]),
        reverse=True,
    )
    descriptive_big = positive_1x[:7]
    transition_rows = []
    for row in transitions:
        transition_rows.append(
            {
                "trade_id": trade_id(row),
                "entry_observables": {
                    "symbol": row["symbol"],
                    "signal_ts_ms": row["signal_ts_ms"],
                    "side": row["side"],
                    "regime": row["regime"],
                    "segment_id": row["signal"]["segment_id"],
                    "frozen_cost_bps": row["cost_bps"],
                    "active_other_positions_at_entry": row["active_at_entry"],
                    "event_trace": row["signal"]["meta"]["event_trace"],
                },
                "posthoc_outcome": {
                    "reason": row["reason"],
                    "gross_bps": row["gross_bps"],
                    "net1_bps": row["net_bps"],
                    "net2_bps": row["net2_bps"],
                    "hold_bars": row["hold_bars"],
                    "mfe_R": row["mfe_R"],
                    "mae_R": row["mae_R"],
                },
            }
        )

    mr_payload = load(MR_PATH, MR_SHA256)
    mr_dev = [
        row
        for row in mr_payload["trades"]
        if DEV_START_MS <= int(row["signal_ts_ms"]) < DEV_END_MS
        and int(row["outcome_available_ts_ms"]) < DEV_END_MS
    ]
    for row in mr_dev:
        meta = row["signal"]["meta"]
        row["observed_contraction_bps"] = (
            float(meta["previous_spread6h"]) - float(meta["signal_spread6h"])
        ) * 10_000.0
        row["cost2_hurdle_bps"] = 2.0 * float(row["cost_bps"])
    mr_contract = {
        "schema": "zel.issue1377.non_k_candidate_contract.v1",
        "identity": "mr_cross_sectional_contraction_cost2_gate_30m_v1",
        "parent": "mr_cross_sectional_v1_30m_causal_control_v2",
        "classification": "DEVELOPMENT_ONLY_NOT_FRESH_NOT_OOS",
        "changed_axis": "ENTRY_QUALITY_OBSERVED_FIRST_CONTRACTION_VS_EXACT_PAIR_COST2",
        "rule": (
            "After the frozen parent same-extremes 6h >=3% first-contraction setup, "
            "admit only when (previous_spread6h-signal_spread6h)*10000 is at least "
            "2*(0.5*laggard_cost_bps+0.5*leader_cost_bps)."
        ),
        "unchanged": {
            "timeframe_min": 30,
            "lookback_bars": 12,
            "stretch": 0.03,
            "entry": "NEXT_COMMON_30M_OPEN",
            "exit": "PARENT_TIME_8BAR_NEXT_OPEN",
            "occupancy": "ONE_PAIR_GLOBALLY_UNTIL_EXIT",
            "leg_weights": "0.5_LONG_LAGGARD_0.5_SHORT_LEADER",
        },
        "development_window": {
            "start_ms": DEV_START_MS,
            "end_ms_exclusive": DEV_END_MS,
            "end_incomplete": "EXCLUDE_UNRESOLVED_NO_LATER_H_PERIOD_EXIT",
        },
        "cost_views": [1.0, 2.0],
        "outcome_blind_threshold": "EXACT_DIMENSIONALLY_MATCHED_COST2_NOT_FITTED_MULTIPLE",
        "prior_failure_nonduplication": [
            "not 3h lookback",
            "not half-spread exit",
            "not concurrent pairs",
            "not pair/month/symbol deletion",
            "not cost discount",
        ],
        "source_ledgers": {"mr_sha256": MR_SHA256, "keltner_sha256": K_SHA256},
        "issue": 1377,
        "approval_comments": [6026088150, 6026095138],
    }
    mr_contract["rule_sha256"] = digest(mr_contract)

    return {
        "schema": "zel.issue1377.first_deliverable.v1",
        "issue": 1377,
        "market_replays": 0,
        "full_consumed": 0,
        "keltner": {
            "ledger_sha256": K_SHA256,
            "rolling_count": len(k_rows),
            "accounting_1x": summarize(k_rows, 1.0),
            "accounting_2x": summarize(k_rows, 2.0),
            "classes": {
                "original_1x_losses": len(original_losses),
                "positive_1x_to_nonpositive_2x": len(transitions),
                "positive_2x_survivors": len(cost2_winners),
            },
            "transition_summary": {
                "reason": counts(transitions, "reason"),
                "symbol": counts(transitions, "symbol"),
                "regime": counts(transitions, "regime"),
                "side": counts(transitions, "side"),
                "active_other_positions_at_entry": counts(transitions, "active_at_entry"),
                "net1_bps": stats(transitions, "net_bps"),
                "net2_bps": stats(transitions, "net2_bps"),
                "hold_bars": stats(transitions, "hold_bars"),
                "mfe_R": stats(transitions, "mfe_R"),
                "mae_R": stats(transitions, "mae_R"),
                "exact_fee_be_plus_2bps_count": sum(
                    1 for row in transitions if 1.999 <= float(row["net_bps"]) <= 2.001
                ),
            },
            "transition_trades": transition_rows,
            "descriptive_top_1x_winners": [
                {
                    "trade_id": trade_id(row),
                    "net1_bps": row["net_bps"],
                    "net2_bps": row["net2_bps"],
                    "reason": row["reason"],
                    "active_other_positions_at_entry": row["active_at_entry"],
                }
                for row in descriptive_big
            ],
            "candidate_disposition": "NO_K_CHILD_SELECTED",
            "reason": (
                "23/27 crossings are exact approximately +2bps fee-BE outcomes and the "
                "remaining four are two scratch, one max-hold, and one partial/stop outcome. "
                "The saved entry observables do not isolate them without also hitting large "
                "winners; the direct fix is forbidden BE/SL/TP or cost-number retuning."
            ),
        },
        "non_k_selection": {
            "selected": mr_contract["identity"],
            "parent_ledger_sha256": MR_SHA256,
            "parent_development_saved_rows": len(mr_dev),
            "parent_development_saved_accounting_1x": summarize(mr_dev, 1.0),
            "parent_development_saved_accounting_2x": summarize(mr_dev, 2.0),
            "bilateral_cost_bps_1x": stats(mr_dev, "cost_bps"),
            "observed_contraction_bps": stats(mr_dev, "observed_contraction_bps"),
            "hold_bars": stats(mr_dev, "hold_bars"),
            "rejections": [
                {"identity": "mr_fast3h_half_spread_v2", "reason": "KNOWN_NEGATIVE_REPACKAGING"},
                {"identity": "mr_concurrent_pairs_v3", "reason": "KNOWN_NEGATIVE_OCCUPANCY_REPACKAGING"},
                {"lane": "break_15m", "reason": "CURRENT_FAILURE_REPLAY_FORBIDDEN"},
                {"lane": "supertrend_30m", "reason": "CURRENT_FAILURE_REPLAY_FORBIDDEN"},
                {"lane": "micro_edge15m", "reason": "INPUT_NOT_READY_L2_OFI_RECEIPT_FILL_MODEL"},
                {"lane": "trend_rider_a1", "reason": "OTHER_OWNER_CONCENTRATION_HOLD_HANDOFF_ONLY"},
            ],
            "contract": mr_contract,
        },
        "lane_table": [
            {"lane": "Keltner", "state": "PARENT_POSITIVE_COST_FRAGILE", "work": "109T_SAVED_AUDIT_COMPLETE_NO_CHILD"},
            {"lane": "Squeeze", "state": "ISSUE1358_2T_DEVELOPMENT_SURVIVOR_NOT_G5", "work": "NO_RERUN"},
            {"lane": "Trend Rider", "state": "SCALP7_15M_FAIL_A1_261T_CONCENTRATION_HOLD", "work": "OTHER_OWNER_LEDGER_HANDOFF_ONLY"},
            {"lane": "Cross-sectional MR", "state": "1X_WEAK_POSITIVE_2X_NEGATIVE", "work": "ONE_COST_COVERED_ENTRY_CHILD_SELECTED"},
            {"lane": "Break 15m", "state": "ANCHORED_RETEST_RECLAIM_FAIL", "work": "NO_PARENT_REPLAY"},
            {"lane": "Supertrend 30m", "state": "NATIVE_IMPULSE_PULLBACK_FAIL", "work": "NO_PARAMETER_SWEEP"},
            {"lane": "Micro EDGE15m", "state": "SOURCE_EXECUTION_HOLD", "work": "REAL_L2_OFI_RECEIPT_CONSUMER_REQUIRED"},
        ],
        "issue1361_claim_unchanged": "4a12d6101e8391653dc8a13cc5c0ec3881a3b2bc",
        "safety": {"live": "BLOCKED", "paper": "BLOCKED", "promotion": False},
    }


def markdown(value: dict[str, Any]) -> str:
    k = value["keltner"]
    n = value["non_k_selection"]
    lines = [
        "# Issue 1377 first deliverable",
        "",
        "Saved-ledger audit only: no market replay, FULL consumption, order, Paper/Live, or promotion.",
        "",
        "## Keltner cost transition",
        "",
        "| Class | Trades | Meaning |",
        "|---|---:|---|",
        f"| Original 1x loss | {k['classes']['original_1x_losses']} | Non-positive before stress |",
        f"| 1x positive -> 2x non-positive | {k['classes']['positive_1x_to_nonpositive_2x']} | Cost crossing |",
        f"| 2x positive survivor | {k['classes']['positive_2x_survivors']} | Same fills remain positive |",
        "",
        f"The 27 crossings are {k['transition_summary']['reason']}; "
        f"{k['transition_summary']['exact_fee_be_plus_2bps_count']} finish at approximately +2bps under 1x cost. "
        "The descriptive top seven 1x winners all remain positive at 2x. K child: **not selected**.",
        "",
        "## Non-K selection",
        "",
        f"Selected `{n['selected']}`. It keeps the parent 6h/3%/next-open/8-bar/single-pair lifecycle and changes only entry admission: completed-bar first-contraction bps must cover the exact frozen bilateral 2x cost. Rule SHA256: `{n['contract']['rule_sha256']}`.",
        "",
        "## Seven lanes",
        "",
        "| Lane | State | Current work |",
        "|---|---|---|",
    ]
    lines.extend(f"| {row['lane']} | {row['state']} | {row['work']} |" for row in value["lane_table"])
    lines.extend(["", "Economic result: not run yet.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("write", "verify"))
    args = parser.parse_args()
    value = build()
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    report = markdown(value)
    OUT.mkdir(parents=True, exist_ok=True)
    targets = {OUT / "FIRST_DELIVERABLE.json": payload, OUT / "REPORT.md": report}
    if args.action == "write":
        for path, content in targets.items():
            if path.exists() and path.read_text() != content:
                raise ValueError(f"IMMUTABLE_OUTPUT_CONFLICT:{path}")
            path.write_text(content)
    else:
        for path, content in targets.items():
            if not path.exists() or path.read_text() != content:
                raise ValueError(f"SAVED_AUDIT_MISMATCH:{path}")
    print(json.dumps({"state": "PASS", "action": args.action, "rule_sha256": value["non_k_selection"]["contract"]["rule_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
