"""Predeclared causal genes and arithmetic on saved common DEV paths only.

No market I/O, policy replay, candidate numbering, or persistence lives here.
The caller freezes this source and the recipe before observing common outcomes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from typing import Any, Mapping, Sequence

GENES = {
    "G1_TRANSITION_FRESHNESS": {"axes": ["transition"], "inputs": ["transition"],
        "predicate": "p_actionable", "structural_b_only_empty": True},
    "G2_HISTORICAL_PRIMARY_QUALITY": {"axes": ["session", "chase"], "inputs": ["session", "chase"],
        "predicate": "session != US OR current_chase_atr <= previous_chase_atr"},
    "G3_ST_GAP_EXPANDING": {"axes": ["st_gap"], "inputs": ["st_gap"],
        "predicate": "current_st_gap_atr > previous_st_gap_atr"},
    "G4_CHASE_COOLING": {"axes": ["chase"], "inputs": ["chase"],
        "predicate": "current_chase_atr <= previous_chase_atr"},
    "G5_ATR_EXPANDING": {"axes": ["volatility"], "inputs": ["volatility"],
        "predicate": "current_atr/current_close > previous_atr/previous_close"},
    "G6_GEOMETRY_ST_GAP_GE_CHASE": {"axes": ["st_gap", "chase"], "inputs": ["st_gap", "chase"],
        "predicate": "current_st_gap_atr >= current_chase_atr"},
}
SOURCE_PROVENANCE = {
    "session_chase": {"path": "backend/research/rebuild/trend_rider_wr80_us_chase_cooling_child_policy_v1.py",
        "sha256": "77a2ab973520d89f0b63d5e201c7114109f98f0b5107c8a6816658f3db05d5ae"},
    "session": {"path": "backend/research/rebuild/trend_rider_transition_freshness_non_us_child_policy_v1.py",
        "sha256": "76f578f57ec5d4f6fda2919d951d6bcc2e39203eed305e8957f52c3aaad43edb"},
    "ordinal_states": {"path": "backend/research/rebuild/a1_trend_rider_wr80_winner_restore_attribution_v1.py",
        "sha256": "d7670ee9509ca70610ef054557a0adc9f44bae75667103af400030636610c9cc"},
}


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def recipe() -> dict[str, Any]:
    """A JSON-safe specification; none of its choices depend on observations."""
    return {"genes": GENES, "source_provenance": SOURCE_PROVENANCE,
            "screen_universe": "B_ACTIONABLE_AND_NOT_P_ACTIONABLE_BEFORE_OCCUPANCY",
            "outcomes": "SAVED_EXECUTED_B_COMMON_PATHS_ONLY; NO_REPLAY",
            "ordinary_retention": "SUM_RETAINED_COMPLETED_WIN_PROFIT/SUM_ALL_B_ONLY_COMPLETED_WIN_PROFIT",
            "top10_retention": "SAME_RATIO_ON_TOP_CEIL_10_PERCENT_B_ONLY_COMPLETED_WINNERS",
            "empty_winner_denominator": "FAIL_CLOSED_NULL",
            "selection_A": "HARD_PASS_THEN_PARETO_THEN_AXES_ASC_TOP1_ASC_DD_ASC_GENE_ID_ASC_MAX2",
            "pareto_dimensions": ["expectancy", "PF", "WR", "negative_DD", "loss_tail",
                                   "ordinary_retention", "top10_retention", "negative_top1"],
            "confirmation_B": "UNCHANGED_A_SURVIVORS_ONLY; RETAIN_A_ORDER; NO_RERANK",
            "u2_semantics": "AND_ONLY; DISJOINT_INPUT_AXES; NO_G1_EMPTY_GENE",
            "forbidden": ["PREENTRY_3BAR_DIRECTIONAL_PERSISTENCE_TRUE", "OPPOSITE_STATE_SWEEP",
                          "NUMERIC_RETUNING", "OUTCOME_FEATURES"],
            "formal_credit": 0, "production_grade": False}


def _number(value: Any) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    return result


def _field(snapshot: Mapping[str, Any], moment: str, field: str) -> float:
    feature = snapshot[f"{moment}_features"]
    value = feature[field] if field in ("atr", "close") else feature["values"][field]
    return _number(value)


def gene_accepts(snapshot: Mapping[str, Any], gene_id: str) -> bool:
    """Reads only signal-time fields. Missing/nonfinite inputs never become cooling."""
    if gene_id not in GENES:
        raise ValueError("UNKNOWN_COMMON_GENE")
    try:
        if gene_id == "G1_TRANSITION_FRESHNESS":
            return snapshot.get("p_actionable") is True
        if gene_id == "G2_HISTORICAL_PRIMARY_QUALITY":
            stamp = int(snapshot["signal_ts"])
            hour = datetime.fromtimestamp(stamp / 1000, tz=timezone.utc).hour
            if hour < 16:
                return True
            return _field(snapshot, "current", "chase_atr") <= _field(snapshot, "prior", "chase_atr")
        if gene_id == "G3_ST_GAP_EXPANDING":
            return _field(snapshot, "current", "st_gap_atr") > _field(snapshot, "prior", "st_gap_atr")
        if gene_id == "G4_CHASE_COOLING":
            return _field(snapshot, "current", "chase_atr") <= _field(snapshot, "prior", "chase_atr")
        if gene_id == "G5_ATR_EXPANDING":
            cc, pc = _field(snapshot, "current", "close"), _field(snapshot, "prior", "close")
            ca, pa = _field(snapshot, "current", "atr"), _field(snapshot, "prior", "atr")
            return cc > 0 and pc > 0 and ca >= 0 and pa >= 0 and ca / cc > pa / pc
        return _field(snapshot, "current", "st_gap_atr") >= _field(snapshot, "current", "chase_atr")
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return False


def union_admission(snapshot: Mapping[str, Any], gene_ids: Sequence[str]) -> str | None:
    """Common engine callback: unconditional P core, AND of fixed B-only genes."""
    if not gene_ids or len(gene_ids) > 2 or len(set(gene_ids)) != len(gene_ids):
        raise ValueError("COMMON_UNION_GENE_COUNT")
    if any(g not in GENES for g in gene_ids):
        raise ValueError("UNKNOWN_COMMON_GENE")
    if len(gene_ids) == 2 and not orthogonal(*gene_ids):
        raise ValueError("COMMON_UNION_GENES_NOT_ORTHOGONAL")
    if snapshot.get("p_actionable") is True:
        return "P_COMMON"
    if snapshot.get("b_actionable") is True and all(gene_accepts(snapshot, g) for g in gene_ids):
        return "B_COMMON"
    return None


def orthogonal(first: str, second: str) -> bool:
    if first not in GENES or second not in GENES:
        raise ValueError("UNKNOWN_COMMON_GENE")
    return (first != second and not any(GENES[g].get("structural_b_only_empty") for g in (first, second))
            and not set(GENES[first]["inputs"]).intersection(GENES[second]["inputs"]))


def _key(row: Mapping[str, Any]) -> tuple[str, int, str]:
    return str(row["symbol"]), int(row["signal_ts"]), str(row["side"])


def _dd(values: Sequence[float]) -> float:
    peak = result = 0.0
    for value in values:
        peak = max(peak, value)
        result = max(result, peak - value)
    return result


def _marked_dd(rows: Sequence[Mapping[str, Any]]) -> float | None:
    if not rows:
        return 0.0
    if any(not row.get("mark_path") for row in rows):
        return None
    increments: dict[int, list[float]] = {}
    for row in rows:
        previous = 0.0
        for point in row["mark_path"]:
            value = _number(point["net_bps"])
            stamp = int(point["ts"])
            increments.setdefault(stamp, []).extend((value, -previous))
            previous = value
    deltas, curve = [], []
    for _, parts in sorted(increments.items()):
        deltas.extend(parts)
        curve.append(math.fsum(deltas))
    return _dd(curve)


def _stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    closed = sorted((r for r in rows if r["status"] == "COMPLETED"),
                    key=lambda r: (r["exit_available_ts"], _key(r)))
    nets = [_number(r["net_bps"]) for r in closed]
    wins, losses = [v for v in nets if v > 0], [v for v in nets if v < 0]
    gp, gl = math.fsum(wins), -math.fsum(losses)
    avg_win = gp / len(wins) if wins else None
    avg_loss = -gl / len(losses) if losses else None
    total, curve, streak, maximum_streak = 0.0, [], 0, 0
    seen_nets = []
    for net in nets:
        seen_nets.append(net)
        total = math.fsum(seen_nets)
        curve.append(total)
        streak = streak + 1 if net < 0 else 0
        maximum_streak = max(maximum_streak, streak)
    tail_n = max(1, math.ceil(len(losses) * 0.1))
    return {"completed_T": len(closed), "open_censored_T": len(rows) - len(closed),
            "wins_T": len(wins), "losses_T": len(losses), "closed_net_bps": total,
            "terminal_net_bps": math.fsum(_number(r["terminal_net_bps"]) for r in rows),
            "expectancy_bps": total / len(closed) if closed else None,
            "WR": len(wins) / len(closed) if closed else None,
            "PF": gp / gl if gl > 0 else None, "PF_infinite": gp > 0 and gl == 0,
            "payoff": avg_win / -avg_loss if wins and losses else None,
            "payoff_infinite": bool(wins) and not losses,
            "avg_win_bps": avg_win, "avg_loss_bps": avg_loss,
            "worst_loss_bps": min(losses) if losses else None,
            "loss_tail_10pct_mean_bps": math.fsum(sorted(losses)[:tail_n]) / tail_n if losses else None,
            "max_loss_streak": maximum_streak,
            "closed_cost2_net_bps": math.fsum(_number(r["cost2_net_bps"]) for r in closed),
            "cost2_terminal_net_bps": math.fsum(_number(r["cost2_terminal_net_bps"]) for r in rows),
            "closed_DD_bps": _dd(curve), "marked_DD_bps": _marked_dd(rows),
            "symbol_hours": math.fsum(_number(r["hold_hours"]) for r in rows),
            "intent_notional_fraction_hours": math.fsum(_number(r["hold_hours"]) *
                _number(r["intent_exposure"]["notional_fraction_of_equity"]) for r in rows),
            "top1_positive_contribution_fraction": max(wins) / gp if wins else None}


def _concentration(rows: Sequence[Mapping[str, Any]], snapshots: Mapping[tuple, Mapping]) -> dict[str, Any]:
    result = {}
    for axis in ("symbol", "day_utc", "regime"):
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            if axis == "symbol":
                value = str(row["symbol"])
            elif axis == "day_utc":
                value = datetime.fromtimestamp(int(row["signal_ts"]) / 1000, tz=timezone.utc).date().isoformat()
            else:
                value = str(snapshots[_key(row)].get("lanes", {}).get("B_COMMON", {}).get("intent", {}).get("regime", "UNAVAILABLE"))
            item = groups.setdefault(value, {"T": 0, "terminal_net_bps": 0.0, "parts": []})
            item["T"] += 1
            item["parts"].append(_number(row["terminal_net_bps"]))
        for item in groups.values():
            item["terminal_net_bps"] = math.fsum(item.pop("parts"))
        result[axis] = groups
    return result


def hard_gate(report: Mapping[str, Any]) -> dict[str, bool]:
    metrics = report["metrics"]
    def above(value: Any, limit: float, strict: bool = False) -> bool:
        return value is not None and (value > limit if strict else value >= limit)
    return {"integrity": report.get("integrity") == "PASS",
            "positive_expectancy": above(metrics["expectancy_bps"], 0.0, True),
            "PF_ge_1": metrics["PF_infinite"] or above(metrics["PF"], 1.0),
            "payoff_ge_1": metrics["payoff_infinite"] or above(metrics["payoff"], 1.0),
            "positive_cost2": above(metrics["closed_cost2_net_bps"], 0.0, True),
            "ordinary_winner_retention_ge_60pct": above(report["ordinary_winner_retention"], 0.60),
            "top10_winner_retention_ge_60pct": above(report["top10_winner_retention"], 0.60)}


def screen(saved_b: Mapping[str, Any], raw_signals: Sequence[Mapping[str, Any]],
           partition: str, gene_id: str) -> dict[str, Any]:
    """Filter saved B paths by preoccupancy B-only admission; never refill holes.

    ``saved_b`` is one common replay result, with campaigns/events and explicit
    partition bounds. Signals may span both partitions; only the bound is used.
    """
    if gene_id not in GENES:
        raise ValueError("UNKNOWN_COMMON_GENE")
    if partition not in ("DEV_A", "DEV_B") or saved_b.get("partition") != partition:
        raise ValueError("COMMON_SCREEN_PARTITION_MISMATCH")
    lo, hi = int(saved_b["start_index"]), int(saved_b["end_exclusive"])
    signals = [s for s in raw_signals if lo <= int(s["signal_index"]) < hi]
    lookup = {_key(s): s for s in signals}
    errors = []
    if len(lookup) != len(signals):
        errors.append("DUPLICATE_SIGNAL_KEY")
    if any(s.get("p_actionable") is True and s.get("b_actionable") is not True for s in signals):
        errors.append("P_NOT_SUBSET_B")
    eligible = {k: s for k, s in lookup.items() if s.get("b_actionable") is True and s.get("p_actionable") is not True}
    admitted = {k for k, s in eligible.items() if gene_accepts(s, gene_id)}
    campaigns = list(saved_b["campaigns"])
    if len({_key(c) for c in campaigns}) != len(campaigns):
        errors.append("DUPLICATE_CAMPAIGN_KEY")
    for campaign in campaigns:
        snap = lookup.get(_key(campaign))
        if (campaign.get("partition") != partition or campaign.get("selected_lane") != "B_COMMON"
                or snap is None or snap.get("b_actionable") is not True):
            errors.append("CAMPAIGN_SIGNAL_LINEAGE")
        elif (campaign.get("snapshot_sha") != snap.get("snapshot_sha")
              or campaign.get("intent_sha") != snap.get("lanes", {}).get("B_COMMON", {}).get("intent_sha")):
            errors.append("CAMPAIGN_HASH_LINEAGE")
        if campaign.get("status") not in ("COMPLETED", "OPEN_CENSORED"):
            raise ValueError("COMMON_SCREEN_CAMPAIGN_STATUS")
    baseline = [c for c in campaigns if _key(c) in eligible]
    selected = [c for c in baseline if _key(c) in admitted]
    rejected = [c for c in baseline if _key(c) not in admitted]
    winners = sorted((c for c in baseline if c["status"] == "COMPLETED" and c["net_bps"] > 0),
                     key=lambda c: (-c["net_bps"], _key(c)))
    top = winners[:max(1, math.ceil(len(winners) * 0.1))]
    def retention(rows: Sequence[Mapping[str, Any]]) -> float | None:
        denominator = math.fsum(_number(c["net_bps"]) for c in rows)
        return math.fsum(_number(c["net_bps"]) for c in rows if _key(c) in admitted) / denominator if denominator > 0 else None
    events = {_key(e): e for e in saved_b.get("events", []) if e.get("side") in ("long", "short")}
    occupied = {k for k in eligible if events.get(k, {}).get("status") == "OWNERSHIP_REJECTED"}
    unfilled = {k for k in eligible if events.get(k, {}).get("status") == "UNFILLED_BOUNDARY_SIGNAL"}
    completed_rejected = [c for c in rejected if c["status"] == "COMPLETED"]
    result = {"schema": "trendrider_common_gene_screen_v1", "partition": partition, "gene_id": gene_id,
              "integrity": "FAIL" if errors else "PASS", "integrity_errors": sorted(set(errors)),
              "causal_decision_fields_only": True, "new_policy_replays": 0,
              "eligible_B_only_signals": len(eligible), "admitted_B_only_signals": len(admitted),
              "rejected_B_only_signals": len(eligible) - len(admitted),
              "occupied_B_only_signals": len(occupied), "admitted_occupied_signals": len(occupied & admitted),
              "unfilled_boundary_B_only_signals": len(unfilled),
              "executed_B_only_T": len(baseline), "admitted_executed_T": len(selected),
              "rejected_executed_T": len(rejected),
              "admitted_keys": [list(k) for k in sorted(admitted)],
              "selected_campaign_keys": [list(_key(c)) for c in selected],
              "ordinary_winner_retention": retention(winners), "top10_winner_retention": retention(top),
              "ordinary_winner_denominator_bps": math.fsum(c["net_bps"] for c in winners),
              "top10_winner_denominator_bps": math.fsum(c["net_bps"] for c in top),
              "removed_losers_T": sum(c["net_bps"] < 0 for c in completed_rejected),
              "removed_loss_bps": -math.fsum(c["net_bps"] for c in completed_rejected if c["net_bps"] < 0),
              "clipped_winners_T": sum(c["net_bps"] > 0 for c in completed_rejected),
              "clipped_winner_bps": math.fsum(c["net_bps"] for c in completed_rejected if c["net_bps"] > 0),
              "P_overlap_signals": sum(s.get("p_actionable") is True for s in signals),
              "P_overlap_filter_applied_T": 0, "new_or_displaced_trades": 0,
              "baseline_metrics": _stats(baseline), "metrics": _stats(selected),
              "concentration": _concentration(selected, lookup),
              "structural_empty_gene": bool(GENES[gene_id].get("structural_b_only_empty")),
              "input_saved_path_sha": digest(saved_b), "input_signal_sha": digest(signals),
              "formal_credit": 0, "production_grade": False}
    result["hard_gates"] = hard_gate(result)
    result["pass"] = all(result["hard_gates"].values())
    result["state"] = ("NO_ADDITIONAL_OPPORTUNITIES_BY_DEFINITION" if result["structural_empty_gene"]
                       else "GENE_HARD_PASS" if result["pass"] else "GENE_HARD_FAIL")
    result["receipt_sha"] = digest(result)
    return result


def _risk_dd(report: Mapping[str, Any]) -> float:
    metrics = report["metrics"]
    return metrics["marked_DD_bps"] if metrics["marked_DD_bps"] is not None else metrics["closed_DD_bps"]


def _pareto_vector(report: Mapping[str, Any]) -> tuple[float, ...]:
    m = report["metrics"]
    return (m["expectancy_bps"], float("inf") if m["PF_infinite"] else m["PF"], m["WR"],
            -_risk_dd(report), m["loss_tail_10pct_mean_bps"] or 0.0,
            report["ordinary_winner_retention"], report["top10_winner_retention"],
            -m["top1_positive_contribution_fraction"])


def select_a(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(reports) > 6 or len({r["gene_id"] for r in reports}) != len(reports):
        raise ValueError("COMMON_SCREEN_COUNT_OR_DUPLICATE")
    if any(r["partition"] != "DEV_A" or r["gene_id"] not in GENES for r in reports):
        raise ValueError("COMMON_SELECTION_A_ONLY")
    passed = [r for r in reports if all(hard_gate(r).values())]
    frontier = []
    for current in passed:
        v = _pareto_vector(current)
        if not any(all(a >= b for a, b in zip(_pareto_vector(other), v)) and
                   any(a > b for a, b in zip(_pareto_vector(other), v)) for other in passed if other is not current):
            frontier.append(current)
    frontier.sort(key=lambda r: (len(GENES[r["gene_id"]]["axes"]),
                                r["metrics"]["top1_positive_contribution_fraction"],
                                _risk_dd(r), r["gene_id"]))
    chosen = [r["gene_id"] for r in frontier[:2]]
    result = {"schema": "trendrider_common_gene_selection_A_v1", "ordered_survivors": chosen,
              "hard_pass_gene_ids": [r["gene_id"] for r in passed],
              "pareto_gene_ids": [r["gene_id"] for r in frontier],
              "selection_data": "DEV_A_ONLY", "DEV_B_outcomes_seen": False,
              "U2_operator": "AND", "U2_orthogonal": len(chosen) == 2 and orthogonal(*chosen),
              "screen_receipts": {r["gene_id"]: r.get("receipt_sha") for r in reports}}
    result["receipt_sha"] = digest(result)
    return result


def confirm_b(selection_a: Mapping[str, Any], reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = list(selection_a["ordered_survivors"])
    if len(ordered) > 2 or len(set(ordered)) != len(ordered):
        raise ValueError("COMMON_FROZEN_SURVIVOR_COUNT")
    mapping = {r["gene_id"]: r for r in reports}
    if len(mapping) != len(reports) or set(mapping) != set(ordered) or any(r["partition"] != "DEV_B" for r in reports):
        raise ValueError("COMMON_CONFIRM_ONLY_FROZEN_A_SURVIVORS")
    kept = [g for g in ordered if all(hard_gate(mapping[g]).values())]
    result = {"schema": "trendrider_common_gene_confirmation_B_v1",
              "frozen_A_order": ordered, "confirmed_A_order": kept,
              "failed_B_gene_ids": [g for g in ordered if g not in kept],
              "best_gene": kept[0] if kept else None,
              "U2_operator": "AND", "U2_orthogonal": len(kept) == 2 and orthogonal(*kept),
              "B_rerank": False, "selection_A_receipt": selection_a.get("receipt_sha"),
              "confirmation_receipts": {g: mapping[g].get("receipt_sha") for g in ordered}}
    result["receipt_sha"] = digest(result)
    return result
