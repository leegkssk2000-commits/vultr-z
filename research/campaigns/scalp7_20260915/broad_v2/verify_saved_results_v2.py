"""Independent arithmetic audit of saved campaign artifacts; never replays signals."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any

DAY = 86_400_000


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-6)


def numbers(
    rows: list[dict[str, Any]], start: int, end: int, mult: float
) -> dict[str, Any]:
    keep = [
        r
        for r in rows
        if start <= r["signal_ts_ms"] < end and r["outcome_available_ts_ms"] < end
    ]
    keep.sort(
        key=lambda r: (
            r["outcome_available_ts_ms"],
            r["exit_ts_ms"],
            r["symbol"],
            r["identity"],
            r["signal_ts_ms"],
        )
    )
    net = [r["gross_bps"] - mult * r["cost_bps"] for r in keep]
    win = sum(n for n in net if n > 0)
    loss = -sum(n for n in net if n < 0)
    peak = equity = dd = 0.0
    streak = maxls = 0
    cohorts: dict[int, float] = defaultdict(float)
    for r, n in zip(keep, net):
        cohorts[r["outcome_available_ts_ms"]] += n
        streak = streak + 1 if n < 0 else 0
        maxls = max(maxls, streak)
    for timestamp in sorted(cohorts):
        equity += cohorts[timestamp]
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {
        "T": len(keep),
        "T_per_day": len(keep) / ((end - start) / DAY),
        "WR": sum(n > 0 for n in net) / len(keep) if keep else None,
        "Gross_bps": sum(r["gross_bps"] for r in keep),
        "Cost_bps": sum(mult * r["cost_bps"] for r in keep),
        "Net_bps": sum(net),
        "NetExp_bps_T": sum(net) / len(keep) if keep else None,
        "PF": win / loss if loss else None,
        "DD_bps": dd,
        "MaxLossStreak": maxls,
    }


def audit(repo: Path) -> dict[str, Any]:
    report = repo / "research/campaigns/scalp7_20260915/broad_rebuild_v2"
    contract = json.loads((report / "CAMPAIGN_PREREGISTERED_V2.json").read_text())
    specs = contract["candidates"]
    identities = [s["identity"] for s in specs]
    assert len(identities) == len(set(identities)) == 21
    repair_path = report / "SOURCE_BINDING_REPAIR_PREREG_V2.json"
    repair = json.loads(repair_path.read_text()) if repair_path.exists() else None
    repaired_ids = {r["identity"] for r in repair["candidates"]} if repair else set()
    directories = {
        identity: ("results_binding_repair" if identity in repaired_ids else "results")
        for identity in identities
    }
    missing = [
        identity
        for identity in identities
        if not (report / directories[identity] / (identity + ".json")).exists()
    ]
    if missing:
        return {
            "state": "WAIT_SAVED_RESULTS",
            "complete": 21 - len(missing),
            "missing": missing,
            "new_economic_replays": 0,
        }
    errors = []
    final_path = report / "CAMPAIGN_FINAL_RESULTS_V2.json"
    if not final_path.exists():
        return {
            "state": "WAIT_SAVED_RESULTS",
            "complete": 21,
            "missing": ["CAMPAIGN_FINAL_RESULTS_V2.json"],
            "new_economic_replays": 0,
        }
    final = json.loads(final_path.read_text())
    if set(final["rows"]) != set(identities):
        errors.append("FINAL_IDENTITY_COHORT")
    if final.get("original_freeze_sha256") != sha(
        report / "CAMPAIGN_PREREGISTERED_V2.json"
    ):
        errors.append("FINAL_ORIGINAL_FREEZE_BINDING")
    if repair and final.get("repair_freeze_sha256") != sha(repair_path):
        errors.append("FINAL_REPAIR_FREEZE_BINDING")
    if final.get("scope_key") != contract["scope_key"]:
        errors.append("FINAL_SCOPE_BINDING")
    if any(
        final.get(key) != "BLOCKED" for key in ("order_authority", "live_authority")
    ):
        errors.append("FINAL_AUTHORITY_DRIFT")
    if repair:
        preserved = {
            identity
            for identity, row in repair["preserved_prior"].items()
            if row["state"] == "VALID_PRESERVED_NO_REPLAY"
        }
        invalid = {
            identity
            for identity, row in repair["preserved_prior"].items()
            if row["state"].startswith("INVALID_")
        }
        if (
            len(repaired_ids) != 17
            or len(preserved) != 4
            or preserved & repaired_ids
            or preserved | repaired_ids != set(identities)
            or repair["max_executions"] != 17
        ):
            errors.append("REPAIR_FOUR_PLUS_SEVENTEEN_COHORT")
        if set(final.get("preserved_positive_no_replay", [])) != preserved:
            errors.append("FINAL_PRESERVED_IDENTITIES")
        if set(final.get("zero_fill_binding_attempts_not_performance", [])) != invalid:
            errors.append("FINAL_INVALID_ATTEMPT_EXCLUSIONS")
        for identity, prior in repair["preserved_prior"].items():
            if sha(repo / prior["path"]) != prior["sha256"]:
                errors.append("PRESERVED_PRIOR_RECEIPT_HASH:" + identity)
            prior_path = repo / prior["ledger_path"]
            if sha(prior_path) != prior["ledger_sha256"]:
                errors.append("PRESERVED_PRIOR_LEDGER_HASH:" + identity)
            prior_payload = json.loads(gzip.decompress(prior_path.read_bytes()))
            if len(prior_payload["trades"]) != prior["economic_fill_count"]:
                errors.append("PRESERVED_PRIOR_RAW_FILL_COUNT:" + identity)
            if identity in invalid and (
                prior_payload["trades"] or prior_payload["unresolved"]
            ):
                errors.append("INVALID_ATTEMPT_HAS_ECONOMIC_POSITION:" + identity)
    output = {}
    windows = {w["label"]: w for w in contract["windows"]}
    for group in ("code_hashes", "data_hashes"):
        for name, expected in contract[group].items():
            if sha(repo / name) != expected:
                errors.append("FROZEN_SOURCE_CHANGED:" + name)
    if repair:
        if repair["original_freeze_sha256"] != sha(
            report / "CAMPAIGN_PREREGISTERED_V2.json"
        ):
            errors.append("REPAIR_ORIGINAL_FREEZE_BINDING")
        for name, expected in repair["code_hashes"].items():
            if sha(repo / name) != expected:
                errors.append("REPAIR_SOURCE_CHANGED:" + name)
    cost_path = repo / contract["cost_path"]
    if sha(cost_path) != contract["cost_sha256"]:
        errors.append("FROZEN_COST_CHANGED")
    costs = json.loads(cost_path.read_text())["costs_bps"]
    for spec in specs:
        identity = spec["identity"]
        path = report / directories[identity] / (identity + ".json")
        evidence = json.loads(path.read_text())
        if final["rows"].get(identity) != evidence:
            errors.append("FINAL_INDIVIDUAL_RECEIPT_BINDING:" + identity)
        if evidence["candidate"] != spec:
            errors.append("CANDIDATE_FREEZE_BINDING:" + identity)
        if [row["window"] for row in evidence["window_receipts"]] != contract[
            "windows"
        ]:
            errors.append("WINDOW_FREEZE_BINDING:" + identity)
        ledger_path = repo / evidence["ledger_path"]
        if sha(ledger_path) != evidence["ledger_sha256"]:
            errors.append("LEDGER_HASH:" + identity)
        payload = json.loads(gzip.decompress(ledger_path.read_bytes()))
        rows = payload["trades"]
        if evidence["window_receipts"] != payload["window_receipts"]:
            errors.append("WINDOW_RECEIPT_DISAGREEMENT:" + identity)
        if len(payload["unresolved"]) != evidence["unresolved_count"]:
            errors.append("UNRESOLVED_COUNT:" + identity)
        seen = set()
        end_excluded = 0
        multi_fill = []
        for row in rows:
            window = windows[row["window_label"]]
            key = (row["identity"], row["symbol"], row["signal_ts_ms"])
            if key in seen:
                errors.append("DUPLICATE_TRADE:" + identity)
            seen.add(key)
            if row["identity"] != identity or row["partition"] != window["partition"]:
                errors.append("ROW_IDENTITY_PARTITION:" + identity)
            if (
                not window["start_ms"]
                <= row["signal_ts_ms"]
                <= row["entry_ts_ms"]
                <= row["exit_ts_ms"]
                <= row["outcome_available_ts_ms"]
                <= window["end_ms"]
            ):
                errors.append("ROW_CAUSAL_WINDOW:" + identity)
            if row["signal_ts_ms"] >= window["end_ms"]:
                errors.append("SIGNAL_END_INCLUSION:" + identity)
            end_excluded += row["outcome_available_ts_ms"] == window["end_ms"]
            if not close(row["net_bps"], row["gross_bps"] - row["cost_bps"]):
                errors.append("NET_COST_RECONCILIATION:" + identity)
            legs = row["signal"].get("legs")
            expected_cost = (
                sum(float(leg["weight"]) * costs[leg["symbol"]] for leg in legs)
                if legs
                else costs[row["symbol"]]
            )
            if not close(row["cost_bps"], expected_cost):
                errors.append("FROZEN_COST_DEBIT:" + identity)
            if legs:
                pair_gross = sum(
                    float(leg["weight"])
                    * int(leg["side"])
                    * (
                        row["exit_prices"][leg["symbol"]]
                        / row["entry_prices"][leg["symbol"]]
                        - 1
                    )
                    * 10000
                    for leg in legs
                )
                if not close(pair_gross, row["gross_bps"]):
                    errors.append("PAIR_GROSS_RECONCILIATION:" + identity)
            if not legs:
                symbol = row["symbol"]
                terminal = (
                    row["side"]
                    * (row["exit_prices"][symbol] / row["entry_prices"][symbol] - 1)
                    * 10000
                )
                if "partial_cashflows" in row:
                    partial = sum(
                        float(event["fraction_original_notional"])
                        * row["side"]
                        * (float(event["fill_price"]) / row["entry_prices"][symbol] - 1)
                        * 10000
                        for event in row["partial_cashflows"]
                    )
                    fraction = 1 - sum(
                        float(event["fraction_original_notional"])
                        for event in row["partial_cashflows"]
                    )
                    if not close(
                        fraction, row["terminal_fraction_original_notional"]
                    ) or not close(partial + fraction * terminal, row["gross_bps"]):
                        errors.append(
                            "SERIALIZED_PARTIAL_CASHFLOW_RECONCILIATION:" + identity
                        )
                elif not close(terminal, row["gross_bps"]):
                    multi_fill.append(
                        {
                            "symbol": symbol,
                            "signal_ts_ms": row["signal_ts_ms"],
                            "difference_bps": row["gross_bps"] - terminal,
                        }
                    )
        for receipt in evidence["window_receipts"]:
            window = receipt["window"]
            selected = [r for r in rows if r["window_label"] == window["label"]]
            for mult in (1, 2):
                expected = numbers(selected, window["start_ms"], window["end_ms"], mult)
                actual = receipt["cost" + str(mult) + "x"]
                for key, value in expected.items():
                    if not close(value, actual[key]):
                        errors.append(
                            f"WINDOW_METRIC:{identity}:{window['label']}:{mult}:{key}"
                        )
        rolling_windows = [
            w for w in contract["windows"] if w["partition"] == "rolling"
        ]
        rolling_rows = [
            r
            for r in rows
            if r["partition"] == "rolling"
            and r["outcome_available_ts_ms"] < windows[r["window_label"]]["end_ms"]
        ]
        for mult in (1, 2):
            expected = numbers(
                rolling_rows,
                rolling_windows[0]["start_ms"],
                contract["raw_history_end_ms"],
                mult,
            )
            for key, value in expected.items():
                if not close(value, evidence["rolling" + str(mult) + "x"][key]):
                    errors.append(f"POOLED_METRIC:{identity}:{mult}:{key}")
            positive = sum(
                numbers(
                    [r for r in rolling_rows if r["window_label"] == w["label"]],
                    w["start_ms"],
                    w["end_ms"],
                    mult,
                )["Net_bps"]
                > 0
                for w in rolling_windows
            )
            ratio = positive / len(rolling_windows)
            if not close(
                ratio,
                evidence["rolling_windows" + str(mult) + "x"][
                    "rolling_positive_window_ratio"
                ],
            ):
                errors.append("ROLLING_RATIO:" + identity)
        if not close(
            evidence["rolling2x"]["Net_bps"],
            evidence["rolling1x"]["Net_bps"] - evidence["rolling1x"]["Cost_bps"],
        ):
            errors.append("STRESS_RECONCILIATION:" + identity)
        output[identity] = {
            "evidence_sha256": sha(path),
            "ledger_sha256": sha(ledger_path),
            "saved_rows": len(rows),
            "rolling_rows": len(rolling_rows),
            "exact_window_end_outcomes_excluded": end_excluded,
            "unresolved_count": len(payload["unresolved"]),
            "partial_cashflow_not_serialized_count": len(multi_fill),
            "rolling1x": evidence["rolling1x"],
            "rolling2x": evidence["rolling2x"],
        }
    deltas = []
    for spec in specs:
        if spec["identity"] == spec["parent"]:
            continue
        child = output[spec["identity"]]["rolling1x"]
        parent = output[spec["parent"]]["rolling1x"]
        delta = {
            key: (
                child[key] - parent[key]
                if child[key] is not None and parent[key] is not None
                else None
            )
            for key in (
                "T",
                "T_per_day",
                "WR",
                "Net_bps",
                "NetExp_bps_T",
                "PF",
                "DD_bps",
                "MaxLossStreak",
            )
        }
        joint = bool(
            child["T"] >= parent["T"]
            and child["WR"] is not None
            and parent["WR"] is not None
            and child["WR"] >= parent["WR"]
            and child["Net_bps"] > parent["Net_bps"]
            and child["DD_bps"] <= parent["DD_bps"]
        )
        deltas.append(
            {
                "identity": spec["identity"],
                "parent": spec["parent"],
                "kind": spec["kind"],
                "delta": delta,
                "joint_T_WR_Net_DD_improvement": joint,
            }
        )
    return {
        "schema": "zel.scalp7.saved_results_independent_arithmetic.v2",
        "state": (
            "PASS_SAVED_ARITHMETIC_WITH_DISCLOSED_LIMITATIONS"
            if not errors
            else "FAIL_SAVED_ARITHMETIC"
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "freeze_sha256": sha(report / "CAMPAIGN_PREREGISTERED_V2.json"),
        "repair_freeze_sha256": sha(repair_path) if repair else None,
        "final_results_sha256": sha(final_path),
        "repair_old_zero_fills_excluded": (
            [
                identity
                for identity, prior in repair["preserved_prior"].items()
                if prior["state"].startswith("INVALID_")
            ]
            if repair
            else []
        ),
        "identities": 21,
        "errors": errors,
        "candidates": output,
        "parent_deltas": deltas,
        "joint_T_WR_Net_DD_count": sum(
            d["joint_T_WR_Net_DD_improvement"] for d in deltas
        ),
        "joint_top7_child_count": sum(
            d["joint_T_WR_Net_DD_improvement"]
            for d in deltas
            if d["kind"] != "material_round1"
        ),
        "joint_material_child_count": sum(
            d["joint_T_WR_Net_DD_improvement"]
            for d in deltas
            if d["kind"] == "material_round1"
        ),
        "criteria": "T>=parent, WR>=parent, Net>parent, realizedDD<=parent; fixed sharedrolling windows; notpromotion",
        "limitations": [
            "PnL/DD are summed equal-notional tradebps; notaccountpercent ormark-to-market drawdown",
            "MR continuousshadow opportunity stream can suppress independentwindowboundary entries; notexactparentcadence",
            "behaviorcosine original-notional occupancy ignores partialexit reduction; sharedcalendarzero buckets included",
            "original4 multi-fillgross cannotbe fullyrebuilt fromterminal prices alone; repaired17 partialcashflows independentlyreconciled",
            "allrolling strategydefinitions formed after historicalinspection; genuinefresh supportstillrequired",
            "concentration positive-profit denominator is sumpositive trades; monthlynegative totals separatelyretained",
        ],
        "economic_replays": 0,
        "historical_parameter_retunes": 0,
        "promotion_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.repo)
    if result["state"] == "WAIT_SAVED_RESULTS":
        print(json.dumps({"state": result["state"], "complete": result["complete"]}))
        return 3
    if args.output:
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "state",
                    "identities",
                    "errors",
                    "joint_T_WR_Net_DD_count",
                    "joint_top7_child_count",
                    "joint_material_child_count",
                )
            }
        )
    )
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
