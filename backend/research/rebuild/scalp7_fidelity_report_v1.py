"""Saved-only source-fidelity comparisons; never generates signals or replays.

All PnL values are realized equal-original-notional trade bps. Event matching
does not infer the PnL of unfilled opportunities. Prior inspected history is not
fresh evidence and this helper cannot promote, route or place orders.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.research.rebuild import scalp7_metrics_v2 as metrics

ROOT = Path(__file__).resolve().parents[3]
REL = Path("research/campaigns/scalp7_20260917/source_fidelity_v1")
COMPARISONS = (("HG", "HG"), ("RSI", "RSI"), ("BREAK", "BREAK"), ("SR", "SRC"))
KEY_FIELDS = ("window_label", "symbol", "side", "signal_ts_ms")
METRIC_CHECKS = (
    "T",
    "Gross_bps",
    "Cost_bps",
    "Net_bps",
    "PF",
    "DD_bps",
    "WR",
    "MaxLossStreak",
)


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unpack(path: Path) -> Any:
    return json.loads(gzip.decompress(path.read_bytes()))


def key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row[k] for k in KEY_FIELDS)


def event_key(value: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(KEY_FIELDS, value))


def indexed(rows: list[dict[str, Any]]) -> dict[tuple[Any, ...], dict[str, Any]]:
    result = {key(r): r for r in rows}
    if len(result) != len(rows):
        raise ValueError("DUPLICATE_OBSERVED_EVENT")
    return result


def strict_rows(
    rows: list[dict[str, Any]], windows: list[dict[str, Any]], partition: str
) -> list[dict[str, Any]]:
    selected = {w["label"]: w for w in windows if w["partition"] == partition}
    return [
        r
        for r in rows
        if r["window_label"] in selected
        and selected[r["window_label"]]["start_ms"]
        <= r["signal_ts_ms"]
        < selected[r["window_label"]]["end_ms"]
        and r["outcome_available_ts_ms"] < selected[r["window_label"]]["end_ms"]
    ]


def verify_arithmetic(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        gross, cost, net = (float(row[k]) for k in ("gross_bps", "cost_bps", "net_bps"))
        if not all(math.isfinite(x) for x in (gross, cost, net)) or cost <= 0:
            raise ValueError("NONFINITE_OR_NONPOSITIVE_AUTHORIZED_COST")
        if not math.isclose(gross - cost, net, abs_tol=1e-7, rel_tol=1e-9):
            raise ValueError("SAVED_NET_ARITHMETIC")
        if (
            not row["signal_ts_ms"]
            <= row["entry_ts_ms"]
            <= row["exit_ts_ms"]
            <= row["outcome_available_ts_ms"]
        ):
            raise ValueError("SAVED_TRADE_CAUSALITY")
        symbol, side = row["symbol"], row["side"]
        entry, final = row["entry_prices"][symbol], row["exit_prices"][symbol]
        if side not in (-1, 1) or not all(
            math.isfinite(x) and x > 0 for x in (entry, final)
        ):
            raise ValueError("SAVED_PRICE_OR_SIDE")
        if "partial_cashflows" in row:
            events = row["partial_cashflows"]
            terminal = row["terminal_fraction_original_notional"]
            if not math.isfinite(terminal) or not 0 <= terminal <= 1:
                raise ValueError("SAVED_PARTIAL_WEIGHT")
            for e in events:
                f, px = e["fraction_original_notional"], e["fill_price"]
                if (
                    not math.isfinite(f)
                    or not 0 < f < 1
                    or not math.isfinite(px)
                    or px <= 0
                ):
                    raise ValueError("SAVED_PARTIAL_VALUE")
                if (
                    not row["entry_ts_ms"]
                    <= e["fill_interval_start_ms"]
                    < e["fill_interval_end_ms"]
                    <= e["observed_at_ms"]
                    <= row["outcome_available_ts_ms"]
                ):
                    raise ValueError("SAVED_PARTIAL_TIME")
            if not math.isclose(
                terminal + sum(e["fraction_original_notional"] for e in events),
                1.0,
                abs_tol=1e-12,
            ):
                raise ValueError("SAVED_PARTIAL_WEIGHT")
            expected = terminal * side * (final / entry - 1) * 10000
            expected += sum(
                e["fraction_original_notional"]
                * side
                * (e["fill_price"] / entry - 1)
                * 10000
                for e in events
            )
            counts["full_cashflow_verified"] += 1
        elif row["signal"].get("partial_fraction"):
            # Legacy HG ledger never saved partial fills; do not manufacture them.
            counts["legacy_partial_gross_not_independently_reconstructable"] += 1
            continue
        else:
            expected = side * (final / entry - 1) * 10000
            counts["unpartial_price_verified"] += 1
        if not math.isclose(expected, gross, abs_tol=1e-7, rel_tol=1e-9):
            raise ValueError("SAVED_GROSS_ARITHMETIC")
    counts["net_cost_verified"] = len(rows)
    return dict(counts)


def summaries(data: dict[str, Any], windows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for partition in ("validation", "rolling"):
        ww = [w for w in windows if w["partition"] == partition]
        rows = strict_rows(data["trades"], windows, partition)
        one = metrics.summarize(rows, ww[0]["start_ms"], ww[-1]["end_ms"])
        two = metrics.summarize(rows, ww[0]["start_ms"], ww[-1]["end_ms"], 2)
        for m in (one, two):
            m["Gross_bps_T"] = m["Gross_bps"] / m["T"] if m["T"] else None
            m["Cost_bps_T"] = m["Cost_bps"] / m["T"] if m["T"] else None
        labels = {w["label"] for w in ww}
        unresolved = [r for r in data["unresolved"] if r["window_label"] in labels]
        raw_count = sum(r["window_label"] in labels for r in data["trades"])
        window_reports = {
            1: metrics.rolling_summary(rows, ww),
            2: metrics.rolling_summary(rows, ww, 2),
        }
        signs = {
            f"cost{multiplier}x": {
                "positive": sum(
                    w["T"] > 0 and w["Net_bps"] > 0 for w in report["windows"]
                ),
                "negative": sum(
                    w["T"] > 0 and w["Net_bps"] < 0 for w in report["windows"]
                ),
                "nonempty_zero": sum(
                    w["T"] > 0 and w["Net_bps"] == 0 for w in report["windows"]
                ),
                "empty": sum(w["T"] == 0 for w in report["windows"]),
            }
            for multiplier, report in window_reports.items()
        }
        result[partition] = {
            "cost1x": one,
            "cost2x": two,
            "windows1x": window_reports[1],
            "windows2x": window_reports[2],
            "window_sign_counts": signs,
            "unresolved_count": len(unresolved),
            "closed_outside_strict_window_count": raw_count - len(rows),
        }
    return result


def net_sum(rows: list[dict[str, Any]]) -> float:
    return math.fsum(float(r["net_bps"]) for r in rows)


def loss_clusters(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["net_bps"] < 0:
            groups[(r["window_label"], r["outcome_available_ts_ms"], r["side"])].append(
                r
            )
    clusters = [
        {
            "window_label": k[0],
            "outcome_available_ts_ms": k[1],
            "side": k[2],
            "T": len(v),
            "symbols": sorted(r["symbol"] for r in v),
            "net_bps": net_sum(v),
            "events": [event_key(key(r)) for r in v],
        }
        for k, v in sorted(groups.items())
        if len({r["symbol"] for r in v}) >= 2
    ]
    return {
        "definition": "At least two distinct symbols with negative realized net at exactly the same outcome-availability timestamp and direction; no inferred intrabar simultaneity",
        "count": len(clusters),
        "net_bps": math.fsum(c["net_bps"] for c in clusters),
        "worst_cluster_bps": min((c["net_bps"] for c in clusters), default=None),
        "clusters": clusters,
    }


def potential_events(
    signals: list[dict[str, Any]], windows: list[dict[str, Any]], partition: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered = sorted(
        enumerate(signals),
        key=lambda item: (
            item[1]["signal_ts_ms"],
            item[1]["identity"],
            item[1]["symbol"],
            item[1].get("side", 0),
        ),
    )
    for w in windows:
        if w["partition"] != partition:
            continue
        seen: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        for source_index, signal in ordered:
            if not w["start_ms"] <= signal["signal_ts_ms"] < w["end_ms"]:
                continue
            event = dict(
                signal, window_label=w["label"], source_signal_index=source_index
            )
            execution_key = (
                signal["identity"],
                signal["symbol"],
                signal["signal_ts_ms"],
            )
            event["duplicate_of_event"] = seen.get(execution_key)
            seen.setdefault(execution_key, key(event))
            rows.append(event)
    return rows


def occupancy(
    data: dict[str, Any],
    signals: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    partition: str,
) -> dict[str, Any]:
    potential = potential_events(signals, windows, partition)
    complete = indexed(strict_rows(data["trades"], windows, partition))
    raw = indexed(data["trades"])
    unfinished = {}
    spans: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in data["trades"]:
        until = r["outcome_available_ts_ms"]
        if r["reason"] == "OPEN_GAP_STOP":
            # Frozen engine conservatively retains ownership through this bar.
            until = max(until, r["exit_ts_ms"] + r["timeframe_min"] * 60_000)
        spans[(r["window_label"], r["symbol"])].append(
            {
                "entry": r["entry_ts_ms"],
                "until": until,
                "key": key(r),
                "unresolved": False,
            }
        )
    ends = {w["label"]: w["end_ms"] for w in windows}
    for r in data["unresolved"]:
        sig = dict(r["position"]["signal"], window_label=r["window_label"])
        k = key(sig)
        if k in unfinished:
            raise ValueError("DUPLICATE_UNRESOLVED_EVENT")
        unfinished[k] = r
        spans[(sig["window_label"], sig["symbol"])].append(
            {
                "entry": r["entry_ts_ms"],
                "until": ends[sig["window_label"]],
                "key": k,
                "unresolved": True,
            }
        )
    events = []
    for s in potential:
        k = key(s)
        blockers = [
            x
            for x in spans[(s["window_label"], s["symbol"])]
            if x["key"] != k and x["entry"] <= s["signal_ts_ms"] < x["until"]
        ]
        if s["duplicate_of_event"] is not None:
            status = "DUPLICATE_SIGNAL_REJECTED"
        elif k in complete:
            status = "COMPLETED_INCLUDED"
        elif k in raw:
            status = "COMPLETED_OUTSIDE_STRICT_WINDOW"
        elif k in unfinished:
            status = "ENTERED_UNRESOLVED_NO_REALIZED_PNL"
        elif blockers:
            status = (
                "BLOCKED_BY_UNRESOLVED_OCCUPANCY"
                if any(b["unresolved"] for b in blockers)
                else "BLOCKED_BY_COMPLETED_POSITION_OCCUPANCY"
            )
        else:
            status = "EMITTED_WITHOUT_SAVED_FILL_OR_OCCUPANCY_BLOCKER"
        events.append(
            {
                **event_key(k),
                "status": status,
                "source_signal_index": s["source_signal_index"],
                "duplicate_of_event": (
                    event_key(s["duplicate_of_event"])
                    if s["duplicate_of_event"] is not None
                    else None
                ),
                "blockers": [event_key(b["key"]) for b in blockers],
            }
        )
    return {
        "definition": "All saved emitted opportunities classified against observed independent-window single-symbol ownership. Source/stop/cost/late/end rejection not inferred when no blocker is saved. Opposite-side positions also own the symbol. OPEN_GAP_STOP owns through modeled stop-bar close under the frozen historical BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY; delayed network availability is not reconstructed.",
        "potential_count": len(potential),
        "unique_engine_event_count": sum(
            s["duplicate_of_event"] is None for s in potential
        ),
        "counts": dict(Counter(e["status"] for e in events)),
        "events": events,
        "counterfactual_pnl": None,
    }


def attribution(
    parent_rows: list[dict[str, Any]],
    child_rows: list[dict[str, Any]],
    parent_occupancy: dict[str, Any],
    child_occupancy: dict[str, Any],
) -> dict[str, Any]:
    p, c = indexed(parent_rows), indexed(child_rows)
    po = {
        key(e): e
        for e in parent_occupancy["events"]
        if e["status"] != "DUPLICATE_SIGNAL_REJECTED"
    }
    co = {
        key(e): e
        for e in child_occupancy["events"]
        if e["status"] != "DUPLICATE_SIGNAL_REJECTED"
    }
    common, missed, added = (
        sorted(p.keys() & c.keys()),
        sorted(p.keys() - c.keys()),
        sorted(c.keys() - p.keys()),
    )
    common_delta = math.fsum(c[k]["net_bps"] - p[k]["net_bps"] for k in common)
    removed_parent_net = math.fsum(p[k]["net_bps"] for k in missed)
    added_child_net = math.fsum(c[k]["net_bps"] for k in added)
    observed_delta = net_sum(child_rows) - net_sum(parent_rows)
    if not math.isclose(
        common_delta - removed_parent_net + added_child_net,
        observed_delta,
        abs_tol=1e-7,
        rel_tol=1e-9,
    ):
        raise ValueError("EVENT_ATTRIBUTION_DOES_NOT_RECONCILE")
    winners, losers = [k for k in p if p[k]["net_bps"] > 0], [
        k for k in p if p[k]["net_bps"] < 0
    ]
    parent_positive = math.fsum(p[k]["net_bps"] for k in winners)
    retained = math.fsum(
        min(p[k]["net_bps"], max(c.get(k, {}).get("net_bps", 0), 0)) for k in winners
    )
    winner_group_delta = math.fsum(
        c.get(k, {}).get("net_bps", 0) - p[k]["net_bps"] for k in winners
    )
    loser_saved = math.fsum(
        c.get(k, {}).get("net_bps", 0) - p[k]["net_bps"] for k in losers
    )

    def omission(
        k: tuple[Any, ...], opposite: dict[tuple[Any, ...], dict[str, Any]]
    ) -> dict[str, Any]:
        event = opposite.get(k)
        return {
            "opposite_potential_status": (
                event["status"] if event else "NO_OPPOSITE_EMITTED_EVENT"
            ),
            "blockers": event["blockers"] if event else [],
        }

    details = [
        {
            **event_key(k),
            "category": "COMMON",
            "parent_net_bps": p[k]["net_bps"],
            "child_net_bps": c[k]["net_bps"],
            "net_delta_bps": c[k]["net_bps"] - p[k]["net_bps"],
        }
        for k in common
    ]
    details.extend(
        {
            **event_key(k),
            "category": "MISSED_PARENT",
            "parent_net_bps": p[k]["net_bps"],
            "child_net_bps": None,
            "observed_total_contribution_bps": -p[k]["net_bps"],
            **omission(k, co),
        }
        for k in missed
    )
    details.extend(
        {
            **event_key(k),
            "category": "ADDED_CHILD",
            "parent_net_bps": None,
            "child_net_bps": c[k]["net_bps"],
            "observed_total_contribution_bps": c[k]["net_bps"],
            **omission(k, po),
        }
        for k in added
    )
    positives = [r for r in child_rows if r["net_bps"] > 0]
    positive_added = [c[k] for k in added if c[k]["net_bps"] > 0]

    def drop_largest(rows: list[dict[str, Any]]) -> dict[str, Any]:
        largest = max(rows, key=lambda r: (r["net_bps"], key(r))) if rows else None
        removed = float(largest["net_bps"]) if largest else 0.0
        return {
            "removed_event": event_key(key(largest)) if largest else None,
            "removed_net_bps": removed,
            "child_net_without_winner_bps": net_sum(child_rows) - removed,
            "parent_net_unchanged_bps": net_sum(parent_rows),
            "delta_vs_unchanged_parent_bps": observed_delta - removed,
            "interpretation": "Observed net sensitivity only; other trades unchanged, no causal replay",
        }

    return {
        "key": list(KEY_FIELDS),
        "common_count": len(common),
        "missed_parent_count": len(missed),
        "added_child_count": len(added),
        "common_net_delta_bps": common_delta,
        "missed_parent_net_bps": removed_parent_net,
        "missed_parent_contribution_bps": -removed_parent_net,
        "added_child_net_bps": added_child_net,
        "total_net_delta_bps": observed_delta,
        "parent_winner_count": len(winners),
        "parent_positive_net_bps": parent_positive,
        "capped_common_parent_winner_profit_retained_bps": retained,
        "parent_winner_profit_retained_ratio": (
            retained / parent_positive if parent_positive else None
        ),
        "parent_winner_group_delta_including_missed_bps": winner_group_delta,
        "parent_loser_count": len(losers),
        "parent_loser_observed_loss_saved_bps": loser_saved,
        "parent_loser_common_delta_bps": math.fsum(
            c[k]["net_bps"] - p[k]["net_bps"] for k in losers if k in c
        ),
        "parent_loser_missed_loss_removed_bps": math.fsum(
            -p[k]["net_bps"] for k in losers if k not in c
        ),
        "winner_retention_definition": "Sum min(parent positive net, max(common child net,0)) / all parent positive net; missed parent winners retain zero.",
        "loss_saved_definition": "Observed child-minus-parent net for all parent-negative event keys, including absent child events as zero observed contribution. This is attribution of two actual ledgers, not imputed unfilled-trade PnL.",
        "largest_child_winner_excluded": drop_largest(positives),
        "largest_added_child_winner_excluded": drop_largest(positive_added),
        "events": details,
    }


def compare(
    parent: dict[str, Any],
    child: dict[str, Any],
    parent_signals: list[dict[str, Any]],
    child_signals: list[dict[str, Any]],
    windows: list[dict[str, Any]],
) -> dict[str, Any]:
    p_summary, c_summary = summaries(parent, windows), summaries(child, windows)
    result = {}
    for partition in ("validation", "rolling"):
        p = strict_rows(parent["trades"], windows, partition)
        c = strict_rows(child["trades"], windows, partition)
        po = occupancy(parent, parent_signals, windows, partition)
        co = occupancy(child, child_signals, windows, partition)
        pm, cm = p_summary[partition]["cost1x"], c_summary[partition]["cost1x"]
        flags = {
            "T": cm["T"] > pm["T"],
            "WR": cm["WR"] is not None and pm["WR"] is not None and cm["WR"] > pm["WR"],
            "Net": cm["Net_bps"] > pm["Net_bps"],
            "DD": cm["DD_bps"] < pm["DD_bps"],
        }
        result[partition] = {
            "parent": p_summary[partition],
            "child": c_summary[partition],
            "delta": {
                "T": cm["T"] - pm["T"],
                "WR_percentage_points": (
                    None
                    if cm["WR_pct"] is None or pm["WR_pct"] is None
                    else cm["WR_pct"] - pm["WR_pct"]
                ),
                "Net_bps": cm["Net_bps"] - pm["Net_bps"],
                "Net_bps_cost2x": c_summary[partition]["cost2x"]["Net_bps"]
                - p_summary[partition]["cost2x"]["Net_bps"],
                "DD_bps": cm["DD_bps"] - pm["DD_bps"],
            },
            "strict_improvements": flags,
            "strict_improvement_count": sum(flags.values()),
            "all_T_WR_Net_DD_strictly_improve": all(flags.values()),
            "attribution": attribution(p, c, po, co),
            "occupancy": {"parent": po, "child": co},
            "same_time_direction_loss_clusters": {
                "parent": loss_clusters(p),
                "child": loss_clusters(c),
            },
        }
    return result


def checked_payload(root: Path, info: dict[str, Any]) -> dict[str, Any]:
    path = root / info["ledger_path"]
    if sha(path) != info["ledger_sha256"]:
        raise ValueError("REPORT_INPUT_LEDGER_HASH_DRIFT")
    payload = unpack(path)
    if len(payload["unresolved"]) != info["unresolved_count"]:
        raise ValueError("REPORT_UNRESOLVED_COUNT_DRIFT")
    identity = info["candidate"]["identity"]
    for row in payload["trades"]:
        if row["identity"] != identity or row["signal"]["identity"] != identity:
            raise ValueError("REPORT_TRADE_IDENTITY")
        for field in ("symbol", "side", "signal_ts_ms", "timeframe_min"):
            if row[field] != row["signal"][field]:
                raise ValueError("REPORT_TRADE_SIGNAL_BINDING")
    for row in payload["unresolved"]:
        if (
            row["identity"] != identity
            or row["position"]["signal"]["identity"] != identity
        ):
            raise ValueError("REPORT_UNRESOLVED_IDENTITY")
    verify_arithmetic(payload["trades"])
    return payload


def assert_saved_summary(info: dict[str, Any], derived: dict[str, Any]) -> None:
    for partition in ("validation", "rolling"):
        for multiplier in (1, 2):
            saved = info.get("summary", {}).get(partition, {}).get(f"cost{multiplier}x")
            if saved is None and partition == "rolling":
                saved = info.get(f"rolling{multiplier}x")
            if saved is None:
                continue
            actual = derived[partition][f"cost{multiplier}x"]
            for field in METRIC_CHECKS:
                if saved[field] != actual[field]:
                    raise ValueError("REPORT_SAVED_SUMMARY_DRIFT:" + field)


def verify_costs(data: dict[str, Any], costs: dict[str, float]) -> None:
    for row in data["trades"]:
        if row["cost_bps"] != costs[row["symbol"]]:
            raise ValueError("REPORT_FROZEN_COST_BINDING")
    for row in data["unresolved"]:
        if row["position"]["cost_bps"] != costs[row["symbol"]]:
            raise ValueError("REPORT_UNRESOLVED_COST_BINDING")


def verify_signal_identity(signals: list[dict[str, Any]], identity: str) -> None:
    if any(s["identity"] != identity for s in signals):
        raise ValueError("REPORT_SIGNAL_IDENTITY")


def verified_original(
    root: Path,
) -> tuple[dict[str, Any], dict[str, float], dict[str, str]]:
    path = (
        root
        / "research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json"
    )
    original = read(path)
    hashes = {str(path.relative_to(root)): sha(path)}
    for group in ("code_hashes", "data_hashes"):
        for relative, expected in original[group].items():
            if sha(root / relative) != expected:
                raise ValueError("REPORT_ORIGINAL_FREEZE_DRIFT:" + relative)
    cost_path = root / original["cost_path"]
    if sha(cost_path) != original["cost_sha256"]:
        raise ValueError("REPORT_COST_SNAPSHOT_DRIFT")
    hashes[str(cost_path.relative_to(root))] = sha(cost_path)
    for tf in (15, 30):
        source = read(
            root / f"research/campaigns/scalp7_20260915/SOURCE_DATA_V2_{tf}M.json"
        )
        if any(
            s["attrs"]["availability_basis"]
            != "BAR_CLOSE_MODEL_NOT_OBSERVED_HISTORICAL_DELIVERY"
            for s in source["symbols"].values()
        ):
            raise ValueError("REPORT_AVAILABILITY_MODEL_UNBOUND")
    return original, read(cost_path)["costs_bps"], hashes


def build_report(root: Path = ROOT) -> dict[str, Any]:
    out = root / REL
    selection_path = out / "BATCH_SELECTION.json"
    selection = read(selection_path)
    original, costs, input_hashes = verified_original(root)
    input_hashes[str(selection_path.relative_to(root))] = sha(selection_path)
    loaded = {}
    windows = None
    for alias in selection["candidates"]:
        info_path = out / "results" / (alias + ".json")
        info = read(info_path)
        if info["candidate"] != selection["candidates"][alias]:
            raise ValueError("REPORT_CANDIDATE_BINDING")
        freeze_path = root / info["freeze_path"]
        if sha(freeze_path) != info["freeze_sha256"]:
            raise ValueError("REPORT_FREEZE_DRIFT")
        frozen = read(freeze_path)
        if (
            frozen["windows"] != original["windows"]
            or frozen["cost_sha256"] != original["cost_sha256"]
        ):
            raise ValueError("REPORT_EXECUTION_CONDITIONS_DRIFT")
        for p, digest in frozen["hashes"].items():
            if sha(root / p) != digest:
                raise ValueError("REPORT_FROZEN_DEPENDENCY_DRIFT:" + p)
        if windows is None:
            windows = frozen["windows"]
        elif windows != frozen["windows"]:
            raise ValueError("REPORT_WINDOW_MISMATCH")
        payload = checked_payload(root, info)
        verify_costs(payload, costs)
        sp = root / info["signal_path"]
        if sha(sp) != info["signals_sha256"]:
            raise ValueError("REPORT_SIGNAL_HASH_DRIFT")
        signals = unpack(sp)
        verify_signal_identity(signals, info["candidate"]["identity"])
        assert_saved_summary(info, summaries(payload, windows))
        loaded[alias] = (info, payload, signals)
        for path in (info_path, freeze_path, root / info["ledger_path"], sp):
            input_hashes[str(path.relative_to(root))] = sha(path)
    if windows is None:
        raise ValueError("REPORT_NO_WINDOWS")
    comparisons = {}
    for name, alias in COMPARISONS:
        child_info, child, child_signals = loaded[alias]
        if name == "SR":
            parent_info, parent, parent_signals = loaded["SRP"]
            parent_source = "NEW_MATCHED_CONTROL_ONE_OF_FIVE_FULL_IDENTITIES"
        else:
            parent_path = root / selection["candidates"][alias]["cached_parent"]
            parent_info = read(parent_path)
            parent = checked_payload(root, parent_info)
            verify_costs(parent, costs)
            parent_signal_path = root / child_info["parent_signals_path"]
            if sha(parent_signal_path) != child_info["parent_signals_sha256"]:
                raise ValueError("REPORT_PARENT_SIGNAL_HASH_DRIFT")
            parent_signals = unpack(parent_signal_path)
            verify_signal_identity(parent_signals, parent_info["candidate"]["identity"])
            parent_source = "EXACT_SAVED_PARENT_NO_ECONOMIC_REPLAY"
            for path in (
                parent_path,
                root / parent_info["ledger_path"],
                parent_signal_path,
            ):
                input_hashes[str(path.relative_to(root))] = sha(path)
        if (
            parent_info["candidate"]["identity"]
            != selection["candidates"][alias]["parent"]
        ):
            raise ValueError("REPORT_PARENT_IDENTITY")
        assert_saved_summary(parent_info, summaries(parent, windows))
        comparisons[name] = {
            "parent_identity": parent_info["candidate"]["identity"],
            "child_identity": child_info["candidate"]["identity"],
            "timeframe_min": selection["candidates"][alias]["tf"],
            "parent_source": parent_source,
            "arithmetic": {
                "parent": verify_arithmetic(parent["trades"]),
                "child": verify_arithmetic(child["trades"]),
            },
            "partitions": compare(
                parent, child, parent_signals, child_signals, windows
            ),
        }
    return {
        "schema": "scalp7.source_fidelity.saved_economic_comparison.v1",
        "scope_key": selection["scope_key"],
        "generator_sha256": sha(
            root / "backend/research/rebuild/scalp7_fidelity_report_v1.py"
        ),
        "input_hashes": input_hashes,
        "windows": windows,
        "new_full_identities": len(loaded),
        "cached_parent_replays": 0,
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "all_four_strict_improvement_count": {
            part: sum(
                c["partitions"][part]["all_T_WR_Net_DD_strictly_improve"]
                for c in comparisons.values()
            )
            for part in ("validation", "rolling")
        },
        "history": "ALREADY_INSPECTED_12M_DEVELOPMENT_DIAGNOSTIC_NOT_FRESH_OR_UNTOUCHED_OOS",
        "fresh_T": 0,
        "account_return": None,
        "mark_to_market_DD": None,
        "behavior_cosine": None,
        "behavior_cosine_state": "NOT_MEASURED_NO_FUSION_AUTHORITY",
        "portfolio": "No new portfolio replay; existing seven-strategy portfolio evidence unchanged.",
        "promotion": False,
        "order": "BLOCKED",
        "live": "BLOCKED",
        "decision": "Observed tradeoffs only; no arbitrary promotion threshold or automatic replacement.",
    }


def number(value: Any, digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Source-fidelity saved economic comparison",
        "",
        "Four parent/child comparisons from five new FULL identities and three exact saved parents. No parent FULL replay. All bps are summed equal-original-notional trade diagnostics; account returns and MTM drawdown are N/A. Historical validation and rolling windows were already inspected. Fresh T = 0; promotion, orders and live remain blocked.",
        "",
    ]
    for partition in ("rolling", "validation"):
        ww = [w for w in report["windows"] if w["partition"] == partition]
        days = (ww[-1]["end_ms"] - ww[0]["start_ms"]) / 86_400_000
        lines.extend(
            [
                f"## {partition.capitalize()} — {days:g} calendar days",
                "",
                "| Pair | T P→C | WR% P→C | Net bps P→C | DD bps P→C | Net 2x P→C | Winner profit retained | Strict gains /4 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for name, value in report["comparisons"].items():
            x = value["partitions"][partition]
            p, c = x["parent"]["cost1x"], x["child"]["cost1x"]
            retain = x["attribution"]["parent_winner_profit_retained_ratio"]
            lines.append(
                f"| {name} | {p['T']}→{c['T']} | {number(p['WR_pct'])}→{number(c['WR_pct'])} | {number(p['Net_bps'])}→{number(c['Net_bps'])} | {number(p['DD_bps'])}→{number(c['DD_bps'])} | {number(x['parent']['cost2x']['Net_bps'])}→{number(x['child']['cost2x']['Net_bps'])} | {number(None if retain is None else retain * 100)}% | {x['strict_improvement_count']} |"
            )
        lines.extend(
            [
                "",
                "Strict gains count T↑, WR↑, Net↑ and realized DD↓. This is descriptive, not a promotion gate.",
                "",
            ]
        )
        for name, value in report["comparisons"].items():
            x = value["partitions"][partition]
            lines.extend(
                [
                    f"### {name}: {value['timeframe_min']}m",
                    "",
                    f"Parent: {value['parent_identity']}. Child: {value['child_identity']}.",
                    "",
                    "| Side | T/day | Gross/T | Cost/T | Net/T | PF | Loss streak | ES5 all trades | Hold p50/p95 min | Unresolved |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for role in ("parent", "child"):
                m = x[role]["cost1x"]
                lines.append(
                    f"| {role} | {number(m['T_per_day'])} | {number(m['Gross_bps_T'])} | {number(m['Cost_bps_T'])} | {number(m['NetExp_bps_T'])} | {number(m['PF'])} | {m['MaxLossStreak']} | {number(m['loss_tail']['expected_shortfall_5pct_all_trades_bps'])} | {number(m['hold_median_min'])}/{number(m['hold_p95_min'])} | {x[role]['unresolved_count']} |"
                )
            a = x["attribution"]
            clusters = x["same_time_direction_loss_clusters"]
            lines.extend(
                [
                    "",
                    f"Net change {number(a['total_net_delta_bps'])} = common-event change {number(a['common_net_delta_bps'])} + removed-parent contribution {number(a['missed_parent_contribution_bps'])} + added-child net {number(a['added_child_net_bps'])}. Event counts common/missed/added: {a['common_count']}/{a['missed_parent_count']}/{a['added_child_count']}.",
                    f"Parent-winner group net change including missed winners: {number(a['parent_winner_group_delta_including_missed_bps'])}; parent-loser observed loss saved: {number(a['parent_loser_observed_loss_saved_bps'])}. Missing events contribute zero actual child PnL; their hypothetical PnL is not estimated.",
                    f"Child-minus-unchanged-parent net after removing the largest child winner: {number(a['largest_child_winner_excluded']['delta_vs_unchanged_parent_bps'])}; after removing the largest added winner: {number(a['largest_added_child_winner_excluded']['delta_vs_unchanged_parent_bps'])}.",
                    f"Exact-time same-direction losing clusters P/C: {clusters['parent']['count']}/{clusters['child']['count']}; worst cluster bps {number(clusters['parent']['worst_cluster_bps'])}/{number(clusters['child']['worst_cluster_bps'])}.",
                    f"Window outcomes positive/negative/nonempty-zero/empty P: {json.dumps(x['parent']['window_sign_counts']['cost1x'], sort_keys=True)}; C: {json.dumps(x['child']['window_sign_counts']['cost1x'], sort_keys=True)}.",
                    f"All emitted opportunity classifications P: {json.dumps(x['occupancy']['parent']['counts'], sort_keys=True)}; C: {json.dumps(x['occupancy']['child']['counts'], sort_keys=True)}.",
                    "",
                ]
            )
    lines.extend(
        [
            "## Evidence limits",
            "",
            "ECONOMIC_COMPARISON.json contains every event attribution, full window/month/symbol metrics, occupancy witnesses, tails, cost stress and exact input hashes. Occupancy classification uses saved real entries and unresolved positions. It does not fabricate outcomes for blocked opportunities.",
            "Legacy HG parent receipts did not retain partial-fill cashflows. Their immutable gross and cost/net arithmetic are preserved; missing partial timing or prices are not reconstructed. New ledgers are independently checked against saved partial and terminal cashflows.",
            "Behavior cosine is not measured; no fusion authority follows. The existing seven-strategy portfolio was not replayed or replaced. Source fidelity is not economic profitability or promotion evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def immutable_write(path: Path, text: str) -> None:
    raw = text.encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("REPORT_IMMUTABLE_CONFLICT:" + str(path))
        return
    with path.open("xb") as handle:
        handle.write(raw)


def artifacts(value: dict[str, Any], root: Path) -> tuple[tuple[Path, str], ...]:
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    return (
        (root / REL / "ECONOMIC_COMPARISON.json", text),
        (root / REL / "ECONOMIC_REPORT.md", markdown(value)),
    )


def status(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": "PASS_SAVED_COMPARISON_NO_ECONOMIC_REPLAY",
        "comparisons": value["comparison_count"],
        "strict_improvement_count": value["all_four_strict_improvement_count"],
    }


def verify(root: Path = ROOT) -> dict[str, Any]:
    value = build_report(root)
    for path, raw in artifacts(value, root):
        if path.read_text() != raw:
            raise ValueError("REPORT_SAVED_VERIFICATION_DRIFT:" + str(path))
    return status(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    args = parser.parse_args()
    if args.command == "verify":
        result = verify()
    else:
        value = build_report()
        for path, raw in artifacts(value, ROOT):
            immutable_write(path, raw)
        result = status(value)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
