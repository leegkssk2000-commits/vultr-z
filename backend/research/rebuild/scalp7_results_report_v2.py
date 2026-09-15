"""Derive comparisons from saved Scalp7 fills; never run signal economics."""

from __future__ import annotations

import gzip
import itertools
import json
import sqlite3
from typing import Any

from backend.research.rebuild import scalp7_campaign_v2 as campaign

REPORT = campaign.REPORT


def load_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    path = campaign.ROOT / evidence["ledger_path"]
    if campaign.sha(path) != evidence["ledger_sha256"]:
        raise ValueError("SAVED_LEDGER_HASH_MISMATCH")
    return json.loads(gzip.decompress(path.read_bytes()))


def complete_rolling(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ends = {
        row["window"]["label"]: row["window"]["end_ms"]
        for row in payload["window_receipts"]
    }
    return [
        row
        for row in payload["trades"]
        if row["partition"] == "rolling"
        and row["outcome_available_ts_ms"] < ends[row["window_label"]]
    ]


def delta(child: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "T",
        "T_per_day",
        "WR_pct",
        "Gross_bps",
        "Net_bps",
        "NetExp_bps_T",
        "PF",
        "DD_bps",
        "MaxLossStreak",
        "largest_winner_contribution",
    )
    result = {
        key: (
            child[key] - parent[key]
            if child[key] is not None and parent[key] is not None
            else None
        )
        for key in keys
    }
    ctail = child["loss_tail"]["expected_shortfall_5pct_all_trades_bps"]
    ptail = parent["loss_tail"]["expected_shortfall_5pct_all_trades_bps"]
    result["ES5_bps"] = (
        ctail - ptail if ctail is not None and ptail is not None else None
    )
    result["strict_T_WR_Net_DD_all_improved"] = bool(
        result["T"] > 0
        and result["WR_pct"] is not None
        and result["WR_pct"] > 0
        and result["Net_bps"] > 0
        and result["DD_bps"] < 0
    )
    result["T_WR_DD_nonworse_Net_improved"] = bool(
        result["T"] >= 0
        and result["WR_pct"] is not None
        and result["WR_pct"] >= 0
        and result["Net_bps"] > 0
        and result["DD_bps"] <= 0
    )
    return result


def main() -> int:
    binding = campaign.module("scalp7_campaign_binding_repair_v2")
    binding.verify_saved()
    full = json.loads((REPORT / "CAMPAIGN_FINAL_RESULTS_V2.json").read_text())
    contract = campaign.verify_freeze()
    metrics = campaign.module("scalp7_metrics_v2")
    portfolio = campaign.module("scalp7_portfolio_v2")
    payloads = {identity: load_payload(row) for identity, row in full["rows"].items()}
    rolling = {
        identity: complete_rolling(payload) for identity, payload in payloads.items()
    }
    all_specs = {row["identity"]: row for row in contract["candidates"]}
    comparisons = {}
    for identity, row in full["rows"].items():
        parent = row["candidate"]["parent"]
        if parent != identity:
            comparisons[identity] = {
                "parent": parent,
                "cost1x": delta(row["rolling1x"], full["rows"][parent]["rolling1x"]),
                "cost2x": delta(row["rolling2x"], full["rows"][parent]["rolling2x"]),
            }
    primary = {
        all_specs[identity]["lane"]: identity
        for identity in contract["primary_identities"]
        if identity in all_specs
    }
    primary["micro_edge"] = campaign.module("scalp7_micro_decision_v2").IDENTITY
    rolling_windows = [
        row for row in contract["windows"] if row["partition"] == "rolling"
    ]
    start, end = rolling_windows[0]["start_ms"], campaign.END
    portfolio_reports = {}
    for mode in ("equal7", "adaptive"):
        outputs = []
        allocated_rows = []
        for window in contract["windows"]:
            input_rows: list[dict[str, Any]] = []
            for identity in primary.values():
                if identity not in payloads:
                    continue
                payload = payloads[identity]
                input_rows.extend(
                    row
                    for row in payload["trades"]
                    if row["window_label"] == window["label"]
                )
                input_rows.extend(
                    row
                    for row in payload["unresolved"]
                    if row["window_label"] == window["label"]
                )
            # The missing minute is only diagnosed after the expected source bar
            # fails completion. This is a modeled history clock, never fresh.
            gaps = []
            gap_ms = 1_771_014_720_000
            for lane, identity in primary.items():
                if identity not in all_specs:
                    continue
                width = all_specs[identity]["tf"] * 60_000
                observed = (gap_ms // width + 1) * width
                if window["start_ms"] <= observed < window["end_ms"]:
                    gaps.append({"identity": identity, "observed_ts_ms": observed})
            output = portfolio.route(
                input_rows,
                primary,
                window["start_ms"],
                window["end_ms"],
                mode=mode,
                source_gap_events=gaps,
            )
            output["window_label"] = window["label"]
            output["partition"] = window["partition"]
            outputs.append(output)
            if window["partition"] == "rolling":
                allocated_rows.extend(output["allocated_rows"])
        path = REPORT / ("PORTFOLIO_" + mode.upper() + "_V2.json.gz")
        path.write_bytes(
            gzip.compress(
                json.dumps(outputs, sort_keys=True, allow_nan=False).encode(), mtime=0
            )
        )
        portfolio_reports[mode] = {
            "cost1x": metrics.summarize(allocated_rows, start, end),
            "cost2x": metrics.summarize(allocated_rows, start, end, 2),
            "rolling_windows1x": metrics.rolling_summary(
                allocated_rows, rolling_windows
            ),
            "source": str(path.relative_to(campaign.ROOT)),
            "sha256": campaign.sha(path),
            "open_allocation_count_by_window": {
                row["window_label"]: row["open_allocation_count"] for row in outputs
            },
            "peak_gross_weight": max(row["peak_gross_weight"] for row in outputs),
            "same_time_valid_signal_only": True,
            "interpretation": "independently flat research windows; closed reference-cost economics, not mark-to-market or continuous account performance; routing is restricted to saved standalone filled plus unresolved opportunity positions, not the complete raw valid-signal pool",
        }
    materials = {}
    material_specs = [
        row for row in contract["candidates"] if row["kind"] == "material_round1"
    ]
    peer_cosines = {}
    for left, right in itertools.combinations(material_specs, 2):
        a, b = left["identity"], right["identity"]
        peer_cosines[a + "|" + b] = metrics.behavior_cosine(
            rolling[a], rolling[b], start, end
        )
    for row in material_specs:
        identity, parent = row["identity"], row["parent"]
        metric = full["rows"][identity]["rolling1x"]
        change = comparisons[identity]["cost1x"]
        materials[identity] = {
            "grade": "C",
            "parent": parent,
            "child": identity,
            "round": 1,
            "max_authorized_rounds": 3,
            "cost1x": metric,
            "cost2x": full["rows"][identity]["rolling2x"],
            "marginal_change": change,
            "parent_behavior_cosine": metrics.behavior_cosine(
                rolling[parent], rolling[identity], start, end
            ),
            "peer_behavior_cosines": {
                key: value
                for key, value in peer_cosines.items()
                if identity in key.split("|")
            },
            "standalone_positive1x": bool(
                metric["Net_bps"] > 0 and metric["PF"] is not None and metric["PF"] > 1
            ),
            "fresh_T": 0,
            "B_promotion": False,
            "A_promotion": False,
            "promotion_blockers": [
                "GENUINE_FRESH_VALIDATION_NOT_COMPLETE",
                "SSOT_SUFFICIENT_SAMPLE_NUMERIC_BOUNDARY_UNBOUND",
            ],
            "rounds2_3": "NOT_FROZEN_NOT_EXECUTED_NO_GRID_OR_FORCED_FUSION",
        }
    result = {
        "schema": "zel.scalp7.final_comparison.v2",
        "scope_key": campaign.SCOPE,
        "table_basis": "ROLLING_ONLY_PARAMETER_OOS_HISTORY_INSPECTED_245_CALENDAR_DAYS",
        "start_ms": start,
        "end_ms": end,
        "rows": full["rows"],
        "comparisons": comparisons,
        "primary_ids": primary,
        "portfolio": portfolio_reports,
        "materials": materials,
        "material_peer_cosines": peer_cosines,
        "strict_joint_improvement_count": sum(
            row["cost1x"]["strict_T_WR_Net_DD_all_improved"]
            for row in comparisons.values()
        ),
        "nonworse_joint_improvement_count": sum(
            row["cost1x"]["T_WR_DD_nonworse_Net_improved"]
            for row in comparisons.values()
        ),
        "C_to_B": 0,
        "B_to_A": 0,
        "BxB_allowed": False,
        "fresh": "SEPARATE_OBSERVED_PRODUCER_AND_PAPER_LEDGER_REQUIRED",
        "original_zero_fill_binding_attempts": full[
            "zero_fill_binding_attempts_not_performance"
        ],
        "risk_limits": "NOT_BOUND_TO_ACCOUNT_OR_LIVE_AUTHORITY",
        "order_authority": "BLOCKED",
        "live_authority": "BLOCKED",
    }
    campaign.write_json(REPORT / "FINAL_COMPARISON_V2.json", result)
    with sqlite3.connect(campaign.RUNTIME / "campaign.sqlite3") as database:
        database.row_factory = sqlite3.Row
        export = {
            table: [dict(row) for row in database.execute("SELECT * FROM " + table)]
            for table in ("scopes", "claims", "events")
        }
    campaign.write_json(REPORT / "EXECUTION_REGISTRY_EXPORT_V2.json", export)
    print(
        json.dumps(
            {
                "comparisons": len(comparisons),
                "joint4": result["strict_joint_improvement_count"],
                "portfolio": {
                    key: value["cost1x"] for key, value in portfolio_reports.items()
                },
                "C_to_B": 0,
                "BxB_allowed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
