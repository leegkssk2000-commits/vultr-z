"""Saved-only economics for the two approved G4 hypotheses.

This module cannot generate signals, replay a strategy or change authorities.
Trade bps are equal-original-notional diagnostics, never account returns.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from typing import Any

from backend.research.rebuild import scalp7_fidelity_report_v1 as saved

ROOT = Path(__file__).resolve().parents[3]
REL = Path("research/campaigns/scalp7_20260920/economic_development_v1")
MODULE = "backend/research/rebuild/scalp7_economic_report_v1.py"
PAIRS = {
    "SQUEEZE": ("SQ0", "SQ2", "origin_fire_ts_ms"),
    "RIDER": ("R15", "R30", "compression_origin_ts_ms"),
}
SCOPE = "G4_SCALP7_MATERIAL20_ECONOMIC_DEVELOPMENT_AFTER_PR1340_V1"


def relative_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("REPORT_UNSAFE_RELATIVE_PATH")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("REPORT_PATH_OUTSIDE_ROOT")
    return root / path


def causal_key(row: dict[str, Any], field: str) -> tuple[Any, ...] | None:
    origin = row["signal"].get("meta", {}).get(field)
    if origin is None:
        return None
    if (
        isinstance(origin, bool)
        or not isinstance(origin, int)
        or origin < 0
        or origin > row["signal_ts_ms"]
    ):
        raise ValueError("REPORT_NONCAUSAL_ORIGIN_METADATA")
    return row["window_label"], row["symbol"], row["side"], origin


def origin_object(value: tuple[Any, ...], field: str) -> dict[str, Any]:
    return dict(zip(("window_label", "symbol", "side", field), value))


def same_opportunity(
    parent: list[dict[str, Any]],
    child: list[dict[str, Any]],
    origin_field: str,
) -> dict[str, Any]:
    """Match only an explicit causal origin with one observed trade per side."""
    saved.indexed(parent)
    saved.indexed(child)
    groups: dict[str, dict[tuple[Any, ...], list[dict[str, Any]]]] = {}
    missing: dict[str, list[dict[str, Any]]] = {}
    for role, rows in (("parent", parent), ("child", child)):
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        missing[role] = []
        for row in rows:
            origin = causal_key(row, origin_field)
            if origin is None:
                missing[role].append(row)
            else:
                grouped[origin].append(row)
        groups[role] = grouped
    pg, cg = groups["parent"], groups["child"]
    pairs = []
    unmatched: dict[str, list[dict[str, Any]]] = {
        role: list(rows) for role, rows in missing.items()
    }
    ambiguous = []
    parent_only = child_only = 0
    for origin in sorted(pg.keys() | cg.keys()):
        p, c = pg.get(origin, []), cg.get(origin, [])
        if len(p) == len(c) == 1:
            pr, cr = p[0], c[0]
            pairs.append(
                {
                    "origin": origin_object(origin, origin_field),
                    "parent_event": saved.event_key(saved.key(pr)),
                    "child_event": saved.event_key(saved.key(cr)),
                    "signal_shift_min": (cr["signal_ts_ms"] - pr["signal_ts_ms"])
                    / 60_000,
                    "entry_shift_min": (cr["entry_ts_ms"] - pr["entry_ts_ms"]) / 60_000,
                    "exit_shift_min": (cr["exit_ts_ms"] - pr["exit_ts_ms"]) / 60_000,
                    "parent_net_bps": pr["net_bps"],
                    "child_net_bps": cr["net_bps"],
                    "net_delta_bps": cr["net_bps"] - pr["net_bps"],
                }
            )
        else:
            unmatched["parent"].extend(p)
            unmatched["child"].extend(c)
            if len(p) > 1 or len(c) > 1:
                ambiguous.append(
                    {
                        "origin": origin_object(origin, origin_field),
                        "parent_events": [saved.event_key(saved.key(r)) for r in p],
                        "child_events": [saved.event_key(saved.key(r)) for r in c],
                    }
                )
            elif p:
                parent_only += 1
            elif c:
                child_only += 1
    matched_delta = math.fsum(x["net_delta_bps"] for x in pairs)
    removed = -saved.net_sum(unmatched["parent"])
    added = saved.net_sum(unmatched["child"])
    delta = saved.net_sum(child) - saved.net_sum(parent)
    if not math.isclose(matched_delta + removed + added, delta, abs_tol=1e-7):
        raise ValueError("REPORT_ORIGIN_ATTRIBUTION_RECONCILIATION")
    winners = [r for r in parent if r["net_bps"] > 0]
    positive = saved.net_sum(winners)
    matched_child = {
        tuple(x["parent_event"][f] for f in saved.KEY_FIELDS): x["child_net_bps"]
        for x in pairs
    }
    retained = math.fsum(
        min(r["net_bps"], max(matched_child.get(saved.key(r), 0.0), 0.0))
        for r in winners
    )
    winner_delta = math.fsum(
        matched_child.get(saved.key(r), 0.0) - r["net_bps"] for r in winners
    )
    losers_saved = math.fsum(
        matched_child.get(saved.key(r), 0.0) - r["net_bps"]
        for r in parent
        if r["net_bps"] < 0
    )
    return {
        "origin_field": origin_field,
        "definition": "Same independent window, symbol, direction and saved causal setup origin; exactly one completed trade on each side. No nearest-time matching.",
        "matched_count": len(pairs),
        "same_signal_timestamp_count": sum(x["signal_shift_min"] == 0 for x in pairs),
        "time_shifted_signal_count": sum(x["signal_shift_min"] != 0 for x in pairs),
        "time_shifted_entry_count": sum(x["entry_shift_min"] != 0 for x in pairs),
        "parent_only_known_origin_count": parent_only,
        "child_only_known_origin_count": child_only,
        "missing_origin_count": {r: len(x) for r, x in missing.items()},
        "ambiguous_origin_group_count": len(ambiguous),
        "ambiguous_origins": ambiguous,
        "matched_net_delta_bps": matched_delta,
        "unmatched_parent_observed_contribution_bps": removed,
        "unmatched_child_observed_net_bps": added,
        "total_net_delta_bps": delta,
        "parent_winner_profit_retained_ratio": (
            retained / positive if positive else None
        ),
        "capped_parent_winner_profit_retained_bps": retained,
        "parent_winner_group_delta_including_unmatched_bps": winner_delta,
        "parent_loser_observed_loss_saved_bps": losers_saved,
        "unmatched_interpretation": "Unmatched means no uniquely paired completed observation, not an independent new opportunity or hypothetical zero-PnL trade. Missing and ambiguous origins remain unknown. Unresolved and occupancy observations are reported separately.",
        "pairs": pairs,
        "unmatched_events": {
            r: [saved.event_key(saved.key(x)) for x in rows]
            for r, rows in unmatched.items()
        },
    }


def successors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Save the next actual entry per window/symbol, without causal inference."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["window_label"], row["symbol"])].append(row)
    result = []
    for values in groups.values():
        values.sort(key=lambda r: (r["entry_ts_ms"], r["signal_ts_ms"], r["side"]))
        for current, nxt in zip(values, values[1:]):
            result.append(
                {
                    "event": saved.event_key(saved.key(current)),
                    "next_event": saved.event_key(saved.key(nxt)),
                    "release_to_next_entry_min": (
                        nxt["entry_ts_ms"] - current["outcome_available_ts_ms"]
                    )
                    / 60_000,
                    "next_net_bps": nxt["net_bps"],
                }
            )
    return result


def signal_stream(
    parent: list[dict[str, Any]],
    child: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    """Join full saved signals before assigning independent economic windows."""
    groups: dict[str, dict[tuple[Any, ...], list[dict[str, Any]]]] = {}
    missing: Counter[str] = Counter()
    for role, signals in (("parent", parent), ("child", child)):
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for signal in signals:
            origin = causal_key(
                dict(signal, signal=signal, window_label="FULL_STREAM"), field
            )
            if origin is None:
                missing[role] += 1
                continue
            memberships = [
                w["label"]
                for w in windows
                if w["start_ms"] <= signal["signal_ts_ms"] < w["end_ms"]
            ]
            if len(memberships) > 1:
                raise ValueError("REPORT_OVERLAPPING_WINDOWS")
            grouped[origin[1:]].append(
                {
                    "symbol": signal["symbol"],
                    "side": signal["side"],
                    "signal_ts_ms": signal["signal_ts_ms"],
                    "window_label": memberships[0] if memberships else None,
                }
            )
        groups[role] = grouped
    pg, cg = groups["parent"], groups["child"]
    events = []
    for origin in sorted(pg.keys() | cg.keys()):
        p, c = pg.get(origin, []), cg.get(origin, [])
        if len(p) == len(c) == 1:
            if p[0]["window_label"] != c[0]["window_label"]:
                state = "SAME_ORIGIN_WINDOW_BOUNDARY_SHIFT"
            elif p[0]["signal_ts_ms"] != c[0]["signal_ts_ms"]:
                state = "SAME_ORIGIN_SIGNAL_TIME_SHIFT"
            else:
                state = "SAME_ORIGIN_SAME_SIGNAL_TIME"
        elif len(p) > 1 or len(c) > 1:
            state = "AMBIGUOUS_ORIGIN_NO_FORCED_PAIRING"
        else:
            state = (
                "PARENT_ONLY_SAVED_SIGNAL_ORIGIN"
                if p
                else "CHILD_ONLY_SAVED_SIGNAL_ORIGIN"
            )
        events.append(
            {
                "origin": dict(zip(("symbol", "side", field), origin)),
                "state": state,
                "parent": p,
                "child": c,
            }
        )
    return {
        "definition": "Origin join across full saved signal streams first; window labels assigned afterward. Boundary shifts never pool PnL or count as proven independent opportunities.",
        "missing_origin_signal_count": dict(missing),
        "counts": dict(Counter(e["state"] for e in events)),
        "events": events,
    }


def boundary_diagnostics(
    rows: list[dict[str, Any]],
    unmatched_events: list[dict[str, Any]],
    opposite_signals: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    field: str,
) -> dict[str, Any]:
    by_event = saved.indexed(rows)
    by_origin: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for signal in opposite_signals:
        origin = causal_key(
            dict(signal, signal=signal, window_label="FULL_STREAM"), field
        )
        if origin is not None:
            by_origin[origin[1:]].append(signal)
    window_map = {w["label"]: w for w in windows}
    events = []
    for event in unmatched_events:
        row = by_event[saved.key(event)]
        origin = causal_key(row, field)
        counterpart = by_origin.get(origin[1:], []) if origin else []
        w = window_map[row["window_label"]]
        inside = [
            s for s in counterpart if w["start_ms"] <= s["signal_ts_ms"] < w["end_ms"]
        ]
        state = (
            "ORIGIN_MISSING_UNKNOWN"
            if origin is None
            else (
                "SAME_ORIGIN_SIGNAL_INSIDE_WINDOW_NO_UNIQUE_COMPLETED_MATCH"
                if inside
                else (
                    "SAME_ORIGIN_SIGNAL_OUTSIDE_THIS_WINDOW"
                    if counterpart
                    else "NO_OPPOSITE_SAVED_SIGNAL_ORIGIN"
                )
            )
        )
        events.append(
            {
                **event,
                "state": state,
                "opposite_signal_timestamps": [s["signal_ts_ms"] for s in counterpart],
                "counterfactual_pnl": None,
            }
        )
    return {
        "counts": dict(Counter(e["state"] for e in events)),
        "events": events,
    }


def compare(
    parent: dict[str, Any],
    child: dict[str, Any],
    parent_signals: list[dict[str, Any]],
    child_signals: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    origin_field: str,
) -> dict[str, Any]:
    stream = signal_stream(parent_signals, child_signals, windows, origin_field)
    result = saved.compare(parent, child, parent_signals, child_signals, windows)
    for partition, value in result.items():
        p = saved.strict_rows(parent["trades"], windows, partition)
        c = saved.strict_rows(child["trades"], windows, partition)
        value["same_opportunity"] = same_opportunity(p, c, origin_field)
        labels = {w["label"] for w in windows if w["partition"] == partition}
        events = [
            e
            for e in stream["events"]
            if any(
                s["window_label"] in labels
                for role in ("parent", "child")
                for s in e[role]
            )
        ]
        value["signal_opportunity_stream"] = {
            **stream,
            "events": events,
            "counts": dict(Counter(e["state"] for e in events)),
            "partition_membership": "Either side's emitted signal is in this partition; cross-boundary counterpart remains visible without moving its PnL.",
        }
        value["unmatched_fill_diagnostics"] = {
            "parent": boundary_diagnostics(
                p,
                value["same_opportunity"]["unmatched_events"]["parent"],
                child_signals,
                windows,
                origin_field,
            ),
            "child": boundary_diagnostics(
                c,
                value["same_opportunity"]["unmatched_events"]["child"],
                parent_signals,
                windows,
                origin_field,
            ),
        }
        value["successor_observations"] = {
            "definition": "Chronological observed completed entries per window/symbol; descriptive succession does not establish that an earlier changed trade caused the next trade.",
            "parent": successors(p),
            "child": successors(c),
        }
        value["unresolved_unknowns"] = {
            role: [
                {
                    "event": saved.event_key(
                        saved.key(
                            dict(
                                r["position"]["signal"], window_label=r["window_label"]
                            )
                        )
                    ),
                    "entry_ts_ms": r["entry_ts_ms"],
                    "origin": r["position"]["signal"].get("meta", {}).get(origin_field),
                    "hypothetical_net_bps": None,
                }
                for r in data["unresolved"]
                if r["window_label"]
                in {w["label"] for w in windows if w["partition"] == partition}
            ]
            for role, data in (("parent", parent), ("child", child))
        }
    return result


def load_identity(
    root: Path,
    alias: str,
    spec: dict[str, Any],
    original: dict[str, Any],
    costs: dict[str, float],
    input_hashes: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    info_path = root / REL / "results" / (alias + ".json")
    info = saved.read(info_path)
    if info["candidate"] != spec:
        raise ValueError("REPORT_CANDIDATE_BINDING")
    paths = {
        field: relative_path(root, info[field])
        for field in ("freeze_path", "ledger_path", "signal_path")
    }
    for field, digest in (
        ("freeze_path", "freeze_sha256"),
        ("ledger_path", "ledger_sha256"),
        ("signal_path", "signals_sha256"),
    ):
        if saved.sha(paths[field]) != info[digest]:
            raise ValueError("REPORT_INPUT_HASH_DRIFT:" + field)
    frozen = saved.read(paths["freeze_path"])
    if (
        frozen["windows"] != original["windows"]
        or frozen["cost_sha256"] != original["cost_sha256"]
    ):
        raise ValueError("REPORT_EXECUTION_CONDITIONS_DRIFT")
    for relative, digest in frozen["hashes"].items():
        if saved.sha(relative_path(root, relative)) != digest:
            raise ValueError("REPORT_FROZEN_DEPENDENCY_DRIFT:" + relative)
    payload = saved.checked_payload(root, info)
    if payload["window_receipts"] != info["window_receipts"]:
        raise ValueError("REPORT_WINDOW_RECEIPT_BINDING")
    signals = saved.unpack(paths["signal_path"])
    saved.verify_signal_identity(signals, spec["identity"])
    saved.verify_costs(payload, costs)
    derived = saved.summaries(payload, frozen["windows"])
    if not info.get("summary"):
        raise ValueError("REPORT_SUMMARY_MISSING")
    saved.assert_saved_summary(info, derived)
    for path in (info_path, *paths.values()):
        input_hashes[str(path.relative_to(root))] = saved.sha(path)
    return info, payload, signals


def build_report(root: Path = ROOT, pair: str = "ALL") -> dict[str, Any]:
    if pair not in (*PAIRS, "ALL"):
        raise ValueError("REPORT_UNKNOWN_PAIR")
    names = tuple(PAIRS) if pair == "ALL" else (pair,)
    selection_path = root / REL / "BATCH_SELECTION.json"
    selection = saved.read(selection_path)
    if selection["scope_key"] != SCOPE or set(selection["candidates"]) != {
        "SQ0",
        "SQ2",
        "R15",
        "R30",
    }:
        raise ValueError("REPORT_APPROVED_SCOPE_BINDING")
    original, costs, input_hashes = saved.verified_original(root)
    input_hashes[str(selection_path.relative_to(root))] = saved.sha(selection_path)
    comparisons = {}
    loaded: set[str] = set()
    for name in names:
        pa, ca, origin = PAIRS[name]
        pi, p, ps = load_identity(
            root, pa, selection["candidates"][pa], original, costs, input_hashes
        )
        ci, c, cs = load_identity(
            root, ca, selection["candidates"][ca], original, costs, input_hashes
        )
        loaded.update((pa, ca))
        comparisons[name] = {
            "parent_alias": pa,
            "child_alias": ca,
            "parent_identity": pi["candidate"]["identity"],
            "child_identity": ci["candidate"]["identity"],
            "parent_candidate": pi["candidate"],
            "child_candidate": ci["candidate"],
            "parent_freeze_sha256": pi["freeze_sha256"],
            "child_freeze_sha256": ci["freeze_sha256"],
            "interpretation": (
                "Matched completed30m Squeeze context with first-fire versus second-upward-attempt 15m entry."
                if name == "SQUEEZE"
                else "Same new Rider entry architecture; 15m versus completed30m structural exit. Neither is the cached old Rider parent."
            ),
            "parent_source": "NEW_MATCHED_CONTROL_COUNTS_IN_FOUR_FULL_BUDGET",
            "arithmetic": {
                "parent": saved.verify_arithmetic(p["trades"]),
                "child": saved.verify_arithmetic(c["trades"]),
            },
            "partitions": compare(p, c, ps, cs, original["windows"], origin),
        }
    return {
        "schema": "scalp7.economic_development.saved_comparison.v1",
        "scope_key": SCOPE,
        "pair": pair,
        "generator_sha256": saved.sha(root / MODULE),
        "input_hashes": input_hashes,
        "windows": original["windows"],
        "approved_hypotheses": 2,
        "approved_new_identity_cap": 4,
        "approved_full_run_cap": 4,
        "loaded_full_identities": sorted(loaded),
        "cached_parent_replays": 0,
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "state": (
            "BATCH_SAVED_COMPARISONS_COMPLETE"
            if pair == "ALL"
            else "PARTIAL_SAVED_COMPARISON"
        ),
        "all_four_strict_improvement_count": {
            part: sum(
                v["partitions"][part]["all_T_WR_Net_DD_strictly_improve"]
                for v in comparisons.values()
            )
            for part in ("validation", "rolling")
        },
        "history": "ALREADY_INSPECTED_12M_DEVELOPMENT_NOT_FRESH_OR_UNTOUCHED_OOS",
        "fresh_T": 0,
        "account_return": None,
        "mark_to_market_DD": None,
        "behavior_cosine": None,
        "portfolio": "No new seven-lane portfolio replay or adoption.",
        "promotion": False,
        "B_promotions": 0,
        "A_promotions": 0,
        "fusion": "BLOCKED",
        "order": "BLOCKED",
        "live": "BLOCKED",
        "G4_complete": False,
    }


def markdown(value: dict[str, Any]) -> str:
    n = saved.number
    lines = [
        "# G4 selected-batch saved economic comparison",
        "",
        "All PnL and DD values below are summed equal-original-notional trade bps, not account returns. Validation and rolling are separate already-inspected development history. Fresh T=0; formal promotion, fusion, orders and LIVE remain BLOCKED. This batch does not complete G4.",
        "",
    ]
    for name, pair in value["comparisons"].items():
        lines.extend(
            [
                f"## {name}",
                "",
                pair["interpretation"],
                "",
                f"Parent: {pair['parent_identity']} (freeze {pair['parent_freeze_sha256']}). Child: {pair['child_identity']} (freeze {pair['child_freeze_sha256']}).",
                "",
            ]
        )
        for partition in ("rolling", "validation"):
            x = pair["partitions"][partition]
            lines.extend(
                [
                    f"### {partition}",
                    "",
                    "| Side | T | T/day | WR % | Gross | Net 1x | Net/T | PF | DD | MaxLS | Net 2x |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for role in ("parent", "child"):
                m = x[role]["cost1x"]
                lines.append(
                    f"| {role} | {m['T']} | {n(m['T_per_day'])} | {n(m['WR_pct'])} | {n(m['Gross_bps'])} | {n(m['Net_bps'])} | {n(m['NetExp_bps_T'])} | {n(m['PF'], 3)} | {n(m['DD_bps'])} | {m['MaxLossStreak']} | {n(x[role]['cost2x']['Net_bps'])} |"
                )
            lines.extend(
                [
                    "",
                    "| Side | ES5 all trades | Hold median/p95 min | Positive/all windows | Month/symbol/session positive-profit concentration | Largest winner share | Unresolved |",
                    "|---|---:|---:|---:|---|---:|---:|",
                ]
            )
            for role in ("parent", "child"):
                m, w = x[role]["cost1x"], x[role]["windows1x"]
                concentrations = "/".join(
                    n(m["concentration"][axis]["largest_positive_profit_share"], 4)
                    for axis in ("month", "symbol", "session")
                )
                lines.append(
                    f"| {role} | {n(m['loss_tail']['expected_shortfall_5pct_all_trades_bps'])} | {n(m['hold_median_min'])}/{n(m['hold_p95_min'])} | {w['positive_window_count']}/{w['window_count']} | {concentrations} | {n(m['largest_winner_contribution'], 4)} | {x[role]['unresolved_count']} |"
                )
            a, o = x["attribution"], x["same_opportunity"]
            lines.extend(
                [
                    "",
                    f"Exact-event common/missed/added: {a['common_count']}/{a['missed_parent_count']}/{a['added_child_count']}; total Net delta {n(a['total_net_delta_bps'])} = common {n(a['common_net_delta_bps'])} + removed-parent contribution {n(a['missed_parent_contribution_bps'])} + added-child {n(a['added_child_net_bps'])}.",
                    f"Exact-event capped parent-winner profit retained {n(a['parent_winner_profit_retained_ratio'], 4)}; winner-group delta {n(a['parent_winner_group_delta_including_missed_bps'])}; parent-loser observed loss saved {n(a['parent_loser_observed_loss_saved_bps'])}.",
                    f"Explicit same-opportunity matches {o['matched_count']}, signal-time shifts {o['time_shifted_signal_count']}, entry-time shifts {o['time_shifted_entry_count']}; unmatched completed known origins P/C {o['parent_only_known_origin_count']}/{o['child_only_known_origin_count']}; ambiguous groups {o['ambiguous_origin_group_count']}; missing origins {json.dumps(o['missing_origin_count'], sort_keys=True)}.",
                    f"Full-stream causal-origin signal classifications touching this partition: {json.dumps(x['signal_opportunity_stream']['counts'], sort_keys=True)}. Unmatched completed-fill evidence P: {json.dumps(x['unmatched_fill_diagnostics']['parent']['counts'], sort_keys=True)}; C: {json.dumps(x['unmatched_fill_diagnostics']['child']['counts'], sort_keys=True)}.",
                    f"Same-opportunity capped parent-winner profit retained {n(o['parent_winner_profit_retained_ratio'], 4)}; winner-group delta {n(o['parent_winner_group_delta_including_unmatched_bps'])}; parent-loser observed loss saved {n(o['parent_loser_observed_loss_saved_bps'])}.",
                    f"Net delta excluding largest child winner {n(a['largest_child_winner_excluded']['delta_vs_unchanged_parent_bps'])}. Strict descriptive improvements T/WR/Net/DD: {json.dumps(x['strict_improvements'], sort_keys=True)}; this is not a promotion gate.",
                    f"Saved opportunity status P: {json.dumps(x['occupancy']['parent']['counts'], sort_keys=True)}; C: {json.dumps(x['occupancy']['child']['counts'], sort_keys=True)}.",
                    "",
                ]
            )
    lines.extend(
        [
            "## Evidence limits",
            "",
            "The JSON includes cost1x/cost2x full metrics, window outcomes, month/symbol/session distributions, exact event attribution, causal-origin time shifts, occupancy blockers, observed successor entries and unresolved positions. Cost2x uses the identical saved fills with twice the frozen cost; it is not a new replay.",
            "An exact-time event match need not mean the same setup. A missing exact event may be a time shift of the same causal origin. Origins match only when the metadata provides one unique completed trade on both sides; missing/ambiguous origins stay unpaired. Unmatched contributions reconcile observed ledgers and do not impute hypothetical fills or profits. Capped winner retention treats unpaired observed contribution as zero, not proof that an unresolved opportunity finally loses.",
            "Successor timing and occupancy witnesses are descriptive. No MFE, recovery, rejected signal or unfilled opportunity is converted into realizable profit. Closed outcomes at/after a window end are excluded, and unresolved ownership remains explicit. No fresh boundary, service, live authority or promotion changed.",
            "",
        ]
    )
    return "\n".join(lines)


def artifacts(value: dict[str, Any], root: Path) -> tuple[tuple[Path, str], ...]:
    prefix = "ECONOMIC" if value["pair"] == "ALL" else value["pair"]
    return (
        (
            root / REL / (prefix + "_COMPARISON.json"),
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
        ),
        (root / REL / (prefix + "_REPORT.md"), markdown(value)),
    )


def status(value: dict[str, Any]) -> dict[str, Any]:
    compact = {}
    for name, pair in value["comparisons"].items():
        x = pair["partitions"]["rolling"]
        compact[name] = {
            role: {
                f: x[role]["cost1x"][f]
                for f in (
                    "T",
                    "WR_pct",
                    "Net_bps",
                    "NetExp_bps_T",
                    "PF",
                    "DD_bps",
                    "MaxLossStreak",
                )
            }
            for role in ("parent", "child")
        }
        compact[name]["winner_profit_retained_ratio"] = x["same_opportunity"][
            "parent_winner_profit_retained_ratio"
        ]
    return {
        "state": "PASS_SAVED_COMPARISON_NO_ECONOMIC_REPLAY",
        "pair": value["pair"],
        "comparisons": value["comparison_count"],
        "rolling": compact,
    }


def verify(root: Path = ROOT, pair: str = "ALL") -> dict[str, Any]:
    value = build_report(root, pair)
    for path, raw in artifacts(value, root):
        if path.read_text() != raw:
            raise ValueError("REPORT_SAVED_VERIFICATION_DRIFT:" + str(path))
    return status(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--pair", choices=(*PAIRS, "ALL"), default="ALL")
    args = parser.parse_args()
    if args.command == "verify":
        result = verify(pair=args.pair)
    else:
        value = build_report(pair=args.pair)
        for path, raw in artifacts(value, ROOT):
            saved.immutable_write(path, raw)
        result = status(value)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
