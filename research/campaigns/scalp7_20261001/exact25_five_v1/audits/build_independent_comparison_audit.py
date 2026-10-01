#!/usr/bin/env python3
"""Audit report arithmetic using already verified saved fills, one raw file at a time."""
import gc
import gzip
import hashlib
import json
import runpy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
CAMPAIGN = ROOT / "research/campaigns/scalp7_20261001/exact25_five_v1"
HELPER = ROOT / "scripts/verify_scalp7_exact25_five_arithmetic_v1.py"
core = runpy.run_path(str(HELPER))
D, number, Audit = core["D"], core["number"], core["Audit"]
check = Audit()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dd_interval(curve, initial, start, end):
    rows = [r for r in curve if start <= r["ts_ms"] < end]
    if not rows:
        return None
    prior = [r for r in curve if r["ts_ms"] < start]
    peak = number(prior[-1]["equity_usdt"]) if prior else number(initial)
    largest = D(0)
    for row in rows:
        value = number(row["equity_usdt"])
        peak = max(peak, value)
        if peak > 0:
            largest = max(largest, D(100) * (peak - value) / peak)
    return largest


def setup_map(executions, mode):
    answer = {}
    for execution in executions:
        order = execution.get("order")
        if not order:
            continue
        key = (order["symbol"], order["side"])
        key += (
            (order["setup_ts_ms"],)
            if mode == "SETUP_CLOCK"
            else (order["session_end_ms"], order["reference_edge"])
        )
        episode = order["position_episode_id"]
        if episode in answer:
            raise ValueError("DUPLICATE_SETUP_EPISODE")
        answer[episode] = key
    return answer


def qlinear(values, numerator, denominator=100):
    if not values:
        return None
    ordered = sorted(values)
    offset = D(len(ordered) - 1) * D(numerator) / D(denominator)
    low = int(offset)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (offset - D(low))


def compare_tree(prefix, saved, expected):
    if isinstance(expected, dict):
        for key, value in expected.items():
            compare_tree(
                prefix + "." + key,
                saved.get(key) if isinstance(saved, dict) else None,
                value,
            )
        if prefix.endswith(".groups"):
            check.equal(prefix + ".keys", sorted(saved or {}), sorted(expected))
    else:
        check.equal(prefix, saved, expected)


def grouped_risk(items, nets, axis):
    groups = {}
    positive_total = sum((max(D(0), n) for n in nets), D(0))
    for e, net in zip(items, nets):
        if axis == "month":
            label = datetime.fromtimestamp(
                e["outcome_available_ts_ms"] / 1000, timezone.utc
            ).strftime("%Y-%m")
        elif axis == "session":
            hour = datetime.fromtimestamp(e["entry_ts_ms"] / 1000, timezone.utc).hour
            label = ("UTC_00_08", "UTC_08_16", "UTC_16_24")[hour // 8]
        else:
            label = e["symbol"]
        g = groups.setdefault(
            label,
            {"T": 0, "net_reference_usdt": D(0), "positive_trade_profit_usdt": D(0)},
        )
        g["T"] += 1
        g["net_reference_usdt"] += net
        g["positive_trade_profit_usdt"] += max(D(0), net)
    for g in groups.values():
        g["trade_count_share_pct"] = D(100) * g["T"] / len(items)
        g["positive_profit_share_pct"] = (
            D(100) * g["positive_trade_profit_usdt"] / positive_total
            if positive_total
            else None
        )
    return {
        "groups": groups,
        "largest_trade_count_share_pct": max(
            (g["trade_count_share_pct"] for g in groups.values()), default=None
        ),
        "largest_positive_profit_share_pct": max(
            (
                g["positive_profit_share_pct"]
                for g in groups.values()
                if g["positive_profit_share_pct"] is not None
            ),
            default=None,
        ),
    }


def risk_stats(items, start, end, complete):
    nets = [e["net_reference_usdt"] for e in items]
    losing = sorted(n for n in nets if n < 0)
    count_loss, count_all = (len(losing) + 19) // 20, (len(nets) + 19) // 20
    holds = [D(e["exit_ts_ms"] - e["entry_ts_ms"]) / D(60000) for e in items]
    positive = [n for n in nets if n > 0]
    return {
        "start_ts_ms": start,
        "end_ts_ms": end,
        "complete_window": complete,
        "T_resolved": len(items),
        "T_per_day_resolved": D(len(items)) * D(86400000) / D(end - start),
        "loss_tail": {
            "worst_trade_usdt": min(nets) if nets else None,
            "worst_5pct_losing_trades_mean_usdt": (
                sum(losing[:count_loss], D(0)) / count_loss if count_loss else None
            ),
            "worst_5pct_losing_trade_count": count_loss,
            "expected_shortfall_5pct_all_trades_usdt": (
                sum(sorted(nets)[:count_all], D(0)) / count_all if count_all else None
            ),
            "all_trade_tail_count": count_all,
        },
        "hold_mean_min": sum(holds, D(0)) / len(holds) if holds else None,
        "hold_median_min": qlinear(holds, 50),
        "hold_p95_min": qlinear(holds, 95),
        "largest_winner_contribution_pct": (
            D(100) * max(positive) / sum(positive, D(0)) if positive else None
        ),
        "concentration": {
            axis: grouped_risk(items, nets, axis)
            for axis in ("month", "symbol", "session")
        },
    }


def main():
    report_path = CAMPAIGN / "ECONOMIC_COMPARISON.json"
    report = json.loads(report_path.read_text())
    sources, compact, audit_paths = {}, {}, []
    for label, item in report["results"].items():
        audit_path = CAMPAIGN / "audits" / (label + "_ARITHMETIC.json")
        audit = json.loads(audit_path.read_text())
        check.equal(label + ".audit_pass", audit["status"], "PASS")
        check.equal(
            label + ".verifier_sha", audit["inputs"]["verifier_sha256"], sha(HELPER)
        )
        check.equal(
            label + ".source_sha",
            audit["inputs"]["result_sha256"],
            item["source_file_sha256"],
        )
        source = ROOT / item["source_file"]
        stored_bytes = source.read_bytes()
        raw_bytes = (
            gzip.decompress(stored_bytes) if source.suffix == ".gz" else stored_bytes
        )
        check.equal(
            label + ".actual_raw_sha",
            hashlib.sha256(raw_bytes).hexdigest(),
            item["source_file_sha256"],
        )
        raw = json.loads(raw_bytes)
        del raw_bytes, stored_bytes
        binding = json.loads((ROOT / item["freeze_path"]).read_text())
        sources[label] = item["source_file_sha256"]
        audit_paths.append(str(audit_path.relative_to(ROOT)))
        small = {
            "binding": binding,
            "scenarios": {},
            "executions": [
                {"order": e["order"]}
                for e in raw["execution"]["executions"]
                if e.get("order")
            ],
        }
        unknown = [
            e
            for e in raw["execution"]["executions"]
            if e.get("state", e.get("status")) == "UNRESOLVED"
            or e.get("unresolved") is True
        ]
        for multiplier in (1, 2):
            scenario = str(multiplier) + "x"
            independent = audit["cost_scenarios"][scenario]
            saved = raw["cost_scenarios"][scenario]
            episodes = core["rebuild_episodes"](raw["execution"]["ledger"], multiplier)
            small["scenarios"][scenario] = {
                "episodes": episodes,
                "windows": independent["windows"],
            }
            check.equal(
                label + "." + scenario + ".window_count",
                len(item["saved_windows"][scenario]),
                len(independent["windows"]),
            )
            for i, window in enumerate(independent["windows"]):
                for key, value in window.items():
                    if key not in {
                        "cost_resolved_reference_usdt",
                        "unknown_affected_count",
                    }:
                        check.equal(
                            f"{label}.{scenario}.window[{i}].{key}",
                            item["saved_windows"][scenario][i].get(key),
                            value,
                        )
            summary = item["account_curve_summary"][scenario]
            account_curve = (
                saved["account"]["valuation"]["curve"] if saved["account"] else []
            )
            full_account = (
                bool(account_curve)
                and not unknown
                and "PREFIX_ONLY" not in saved["account_status"]
                and account_curve[-1]["ts_ms"] >= binding["windows"][-1]["end_ts_ms"]
            )
            measured_dd = independent["sampled_account_max_dd_pct"]
            check.equal(
                label + "." + scenario + ".full_available",
                summary["full_period_available"],
                full_account,
            )
            check.equal(
                label + "." + scenario + ".full_dd",
                summary["full_sampled_DD_pct"],
                measured_dd if full_account else None,
            )
            check.equal(
                label + "." + scenario + ".prefix_dd",
                summary["prefix_sampled_DD_pct"],
                measured_dd if not full_account else None,
            )
            rolling = [w for w in binding["windows"] if w["kind"] == "ROLLING"]
            start, end = min(w["start_ts_ms"] for w in rolling), max(
                w["end_ts_ms"] for w in rolling
            )
            pool = [
                e
                for e in episodes
                if e["closed"]
                and start <= e["entry_ts_ms"] < end
                and e["outcome_available_ts_ms"] < end
            ]
            values = core["cohort_stats"](pool)
            values["cost_resolved_usdt"] = values.pop("cost_resolved_reference_usdt")
            crossing = [
                e
                for e in episodes
                if start <= e["entry_ts_ms"] < end
                and (not e["closed"] or e["outcome_available_ts_ms"] >= end)
            ]
            carry = [
                e
                for e in episodes
                if e["entry_ts_ms"] < start
                and (not e["closed"] or e["outcome_available_ts_ms"] >= start)
            ]
            affected = [e for e in unknown if e.get("unresolved_from_ts_ms", 0) < end]
            complete = not (crossing or carry or affected)
            later = [
                e["episode_id"]
                for e in pool
                if any(
                    w["start_ts_ms"] <= e["entry_ts_ms"] < w["end_ts_ms"]
                    and e["outcome_available_ts_ms"] >= w["end_ts_ms"]
                    for w in rolling
                )
            ]
            curve = saved["account"]["valuation"]["curve"] if saved["account"] else []
            prefix_dd = dd_interval(curve, binding["initial_cash_usdt"], start, end)
            full_pool_curve = complete and not unknown and prefix_dd is not None
            values["T_per_day_resolved"] = D(len(pool)) * D(86400000) / D(end - start)
            values.update(
                {
                    "cross_boundary_or_open_count": len(crossing),
                    "carry_in_count": len(carry),
                    "affected_unknown_execution_count": len(affected),
                    "complete_window": complete,
                    "actual_historical_net_usdt": None,
                    "funding_status": "UNKNOWN_NOT_ZERO",
                    "net_complete_reference_usdt": (
                        values["net_resolved_reference_usdt"] if complete else None
                    ),
                    "DD_pct": prefix_dd if full_pool_curve else None,
                    "prefix_sampled_account_DD_pct": (
                        prefix_dd if not full_pool_curve else None
                    ),
                    "later_window_resolved_episode_count": len(later),
                    "later_window_resolved_episode_ids": later,
                    "sum_saved_rolling_window_T_resolved": sum(
                        w["T_resolved"]
                        for w in independent["windows"]
                        if w["kind"] == "ROLLING"
                    ),
                }
            )
            for key, value in values.items():
                check.equal(
                    f"{label}.{scenario}.pooled.{key}",
                    item["pooled_rolling_resolved"][scenario].get(key),
                    value,
                )
            risk_saved = item["descriptive_risk"][scenario]
            window_risk = {w["name"]: w for w in risk_saved["windows"]}
            check.equal(
                f"{label}.{scenario}.risk.window_names",
                sorted(window_risk),
                sorted(w["name"] for w in independent["windows"]),
            )
            for w in independent["windows"]:
                selected = [
                    e
                    for e in episodes
                    if e["closed"]
                    and w["start_ts_ms"] <= e["entry_ts_ms"] < w["end_ts_ms"]
                    and e["outcome_available_ts_ms"] < w["end_ts_ms"]
                ]
                expected_risk = risk_stats(
                    selected,
                    w["start_ts_ms"],
                    w["end_ts_ms"],
                    w["complete_window"],
                )
                compare_tree(
                    f"{label}.{scenario}.risk.{w['name']}",
                    window_risk[w["name"]],
                    expected_risk,
                )
            compare_tree(
                f"{label}.{scenario}.risk.pooled",
                risk_saved["pooled_rolling"],
                risk_stats(pool, start, end, complete),
            )
        compact[label] = small
        del raw, saved, curve, episodes, pool, unknown, account_curve
        gc.collect()

    for pair_name, pair in report["matched_comparisons"].items():
        parent_label, child_label = pair_name.split("_vs_")
        parent, child = compact[parent_label], compact[child_label]
        mode = (
            "SETUP_CLOCK"
            if pair["axis"] == "SUPERTREND_TRAILING_ONLY"
            else "FIXED_DAY_REFERENCE"
        )
        setup = {
            k: setup_map(v["executions"], mode)
            for k, v in ((parent_label, parent), (child_label, child))
        }
        for scenario, rows in pair["cost_scenarios"].items():
            pwin = {w["name"]: w for w in parent["scenarios"][scenario]["windows"]}
            cwin = {w["name"]: w for w in child["scenarios"][scenario]["windows"]}
            for row in rows:
                name = row["name"]
                p, c = pwin[name], cwin[name]
                complete = p["complete_window"] and c["complete_window"]
                check.equal(
                    f"{pair_name}.{scenario}.{name}.complete",
                    row["complete_pair_window"],
                    complete,
                )
                for metric, triplet in row["metrics"].items():
                    a, b = p[metric], c[metric]
                    expected = {
                        "parent": a,
                        "child": b,
                        "delta": (
                            number(b) - number(a)
                            if a is not None and b is not None
                            else None
                        ),
                    }
                    for key, value in expected.items():
                        check.equal(
                            f"{pair_name}.{scenario}.{name}.{metric}.{key}",
                            triplet[key],
                            value,
                        )
                if not complete:
                    check.equal(
                        f"{pair_name}.{scenario}.{name}.winner_unknown",
                        row["winner_damage"],
                        None,
                    )
                    continue
                matched = {}
                for label, data in ((parent_label, parent), (child_label, child)):
                    mapping = {}
                    for e in data["scenarios"][scenario]["episodes"]:
                        if (
                            e["closed"]
                            and p["start_ts_ms"] <= e["entry_ts_ms"] < p["end_ts_ms"]
                            and e["outcome_available_ts_ms"] < p["end_ts_ms"]
                        ):
                            key = setup[label][e["episode_id"]]
                            if key in mapping:
                                raise ValueError("DUPLICATE_SAME_SETUP")
                            mapping[key] = e["net_reference_usdt"]
                    matched[label] = mapping
                winners = {k: v for k, v in matched[parent_label].items() if v > 0}
                observed = matched[child_label]
                parent_gain = sum(winners.values(), D(0))
                child_values = [observed.get(k, D(0)) for k in winners]
                child_gain = sum(child_values, D(0))
                damage = {
                    "matching_basis": mode,
                    "parent_winners": len(winners),
                    "child_positive_same_setup": sum(v > 0 for v in child_values),
                    "child_negative_same_setup": sum(v < 0 for v in child_values),
                    "child_zero_same_setup": sum(
                        observed[k] == 0 for k in winners if k in observed
                    ),
                    "child_absent_same_setup": sum(k not in observed for k in winners),
                    "parent_winner_net_usdt": parent_gain,
                    "child_net_on_parent_winning_setups_usdt": child_gain,
                    "winner_net_delta_usdt": child_gain - parent_gain,
                    "positive_winner_profit_retention_pct": (
                        D(100)
                        * sum((max(D(0), v) for v in child_values), D(0))
                        / parent_gain
                        if parent_gain
                        else None
                    ),
                    "not_an_identical_entry_claim": mode == "FIXED_DAY_REFERENCE",
                }
                for key, value in damage.items():
                    check.equal(
                        f"{pair_name}.{scenario}.{name}.winner.{key}",
                        row["winner_damage"].get(key),
                        value,
                    )

    check.equal("report.result_count", report["results_count"], len(sources))
    check.equal("report.full_runs", report["additional_full_runs_by_report"], 0)
    check.equal("report.g4_complete", report["g4_complete"], False)
    check.equal("report.original25_complete", report["original25_complete"], False)
    output = {
        "scope_key": report["scope_key"],
        "status": "PASS" if check.error_count == 0 else "FAIL",
        "market_data_loaded": False,
        "new_full_runs": 0,
        "source_result_sha256": sources,
        "economic_comparison_sha256": sha(report_path),
        "checks": [
            "Per-result independent Decimal audits bound to raw SHA and verifier SHA",
            "Report original windows and pooled rolling tied to independently rebuilt episodes",
            "Sampled prefix DD and unavailable complete metrics preserved",
            "Matched pair metric deltas and complete-window winner damage recalculated",
            "Incomplete-window winner damage remains null",
            "T/day, loss-tail denominators, hold quantiles and month/symbol/session concentration independently recalculated",
        ],
        "check_count": check.checks,
        "error_count": check.error_count,
        "errors": check.errors,
        "per_result_audit_paths": audit_paths,
        "recipe_path": str(Path(__file__).relative_to(ROOT)),
        "recipe_sha256": sha(Path(__file__)),
        "completed_saved_results": report["completed_saved_results"],
        "missing_results": report["missing_results"],
        "coverage_status": (
            "COMPLETE_FIVE_SAVED_RESULTS"
            if len(sources) == 5
            else "PARTIAL_SAVED_RESULTS"
        ),
    }
    destination = CAMPAIGN / "audits/INDEPENDENT_ECONOMIC_AUDIT.json"
    destination.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=core["serial"]) + "\n"
    )
    print(
        json.dumps(
            {
                "status": output["status"],
                "checks": check.checks,
                "errors": check.error_count,
                "completed": len(sources),
                "output": str(destination),
            }
        )
    )
    return 0 if check.error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
