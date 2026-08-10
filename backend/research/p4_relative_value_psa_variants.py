#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import p4_relative_value_psa_base as base

V1 = "RV_PSA_V1_EXIT_Z1_CARRY_CUT_V1"
V2 = "RV_PSA_V2_MAX24H_CARRY_CAP_V1"
PAIR = ("BTCUSDT", "ETHUSDT")


@dataclass
class PairPos:
    direction: int
    entry_i: int
    entry_ts: int
    btc_entry: float
    eth_entry: float
    entry_z: float


def validate_plan(plan: dict[str, Any], parent: dict[str, Any]) -> None:
    if plan.get("state") != "FROZEN_BEFORE_VARIANT_REPLAY":
        raise SystemExit("HOLD_VARIANT_PLAN_STATE")
    if plan.get("family") != "relative_value_psa" or plan.get("predeclared_before_any_variant_replay") is not True:
        raise SystemExit("HOLD_VARIANT_PLAN_NOT_PREDECLARED")
    ids = [x.get("candidate_id") for x in plan.get("variants", [])]
    if ids != [V1, V2]:
        raise SystemExit(f"HOLD_VARIANT_IDS:{ids}")
    if parent.get("state") != "FAIL_P4_W2_NET_PAIR_EDGE_WITH_POSITIVE_FORWARD_GROSS":
        raise SystemExit(f"HOLD_PARENT_STATE:{parent.get('state')}")
    if parent.get("candidate_id") != plan.get("parent_candidate_id"):
        raise SystemExit("HOLD_PARENT_ID_MISMATCH")
    if parent.get("W3_untouched") is not True:
        raise SystemExit("HOLD_PARENT_W3_NOT_UNTOUCHED")
    shared = plan.get("shared", {})
    if shared.get("pair") != list(PAIR) or shared.get("timeframe") != "15m":
        raise SystemExit("HOLD_PAIR_DRIFT")
    if int(shared.get("rolling_window_bars", -1)) != 672 or float(shared.get("entry_abs_z", -1)) != 2.0:
        raise SystemExit("HOLD_ENTRY_OR_SPREAD_DRIFT")
    if shared.get("fill") != "both_legs_next_bar_open" or shared.get("same_bar_fill") is not False:
        raise SystemExit("HOLD_FILL_DRIFT")
    if any(shared.get(k) is not None for k in ("stop_loss", "take_profit", "trailing_overlay")):
        raise SystemExit("HOLD_UNDECLARED_OVERLAY")
    if shared.get("entry_parameter_selection_performed") is not False:
        raise SystemExit("HOLD_ENTRY_SELECTION_DRIFT")
    if plan.get("maximum_variants_per_family_respected") is not True:
        raise SystemExit("HOLD_VARIANT_LIMIT")
    if plan.get("execution_authority") != "NONE" or plan.get("order_authority") != "BLOCKED":
        raise SystemExit("HOLD_AUTHORITY")


def replay_variant(
    btc: list[dict[str, float]],
    eth: list[dict[str, float]],
    window: int,
    entry_abs_z: float,
    candidate_id: str,
) -> dict[str, Any]:
    spread = [math.log(float(b["close"])) - math.log(float(e["close"])) for b, e in zip(btc, eth)]
    pos: PairPos | None = None
    pending_entry: tuple[int, float] | None = None
    pending_exit: str | None = None
    trades: list[dict[str, Any]] = []
    entry_signals = 0
    exit_signals = 0
    time_cap_exit_signals = 0
    exposure_bars = 0
    sum_x = sum(spread[:window])
    sum_x2 = sum(x * x for x in spread[:window])

    for i in range(window, len(spread)):
        if pending_exit is not None and pos is not None:
            btc_exit = float(btc[i]["open"])
            eth_exit = float(eth[i]["open"])
            btc_leg = pos.direction * (btc_exit / pos.btc_entry - 1.0)
            eth_leg = -pos.direction * (eth_exit / pos.eth_entry - 1.0)
            trades.append({
                "direction": "LONG_BTC_SHORT_ETH" if pos.direction == 1 else "SHORT_BTC_LONG_ETH",
                "entry_ts": pos.entry_ts,
                "exit_ts": int(btc[i]["timestamp_ms"]),
                "entry_z": pos.entry_z,
                "btc_entry": pos.btc_entry,
                "eth_entry": pos.eth_entry,
                "btc_exit": btc_exit,
                "eth_exit": eth_exit,
                "bars_held": i - pos.entry_i,
                "exit_reason": pending_exit,
                "gross_return": 0.5 * (btc_leg + eth_leg),
            })
            pos = None
            pending_exit = None

        if pending_entry is not None and pos is None:
            direction, z = pending_entry
            pos = PairPos(
                direction=direction,
                entry_i=i,
                entry_ts=int(btc[i]["timestamp_ms"]),
                btc_entry=float(btc[i]["open"]),
                eth_entry=float(eth[i]["open"]),
                entry_z=z,
            )
            pending_entry = None

        if pos is not None:
            exposure_bars += 1

        n = float(window)
        mean = sum_x / n
        var = max(sum_x2 / n - mean * mean, 0.0)
        std = math.sqrt(var)
        z = (spread[i] - mean) / std if std > 1e-12 else 0.0

        if i + 1 < len(spread):
            if pos is None and pending_entry is None:
                if z >= entry_abs_z:
                    pending_entry = (-1, z)
                    entry_signals += 1
                elif z <= -entry_abs_z:
                    pending_entry = (1, z)
                    entry_signals += 1
            elif pos is not None and pending_exit is None:
                reason: str | None = None
                if candidate_id == V1:
                    if (pos.direction == -1 and z <= 1.0) or (pos.direction == 1 and z >= -1.0):
                        reason = "Z1_REVERSION_ZONE"
                elif candidate_id == V2:
                    zero_cross = (pos.direction == -1 and z <= 0.0) or (pos.direction == 1 and z >= 0.0)
                    reached_24h = (i - pos.entry_i + 1) >= 96
                    if zero_cross:
                        reason = "ZERO_CROSS"
                    elif reached_24h:
                        reason = "MAX_24H"
                        time_cap_exit_signals += 1
                else:
                    raise SystemExit(f"HOLD_UNKNOWN_VARIANT:{candidate_id}")
                if reason is not None:
                    pending_exit = reason
                    exit_signals += 1

        old = spread[i - window]
        new = spread[i]
        sum_x += new - old
        sum_x2 += new * new - old * old

    direction_counts = {
        "LONG_BTC_SHORT_ETH": sum(1 for t in trades if t["direction"] == "LONG_BTC_SHORT_ETH"),
        "SHORT_BTC_LONG_ETH": sum(1 for t in trades if t["direction"] == "SHORT_BTC_LONG_ETH"),
    }
    exit_reason_counts: dict[str, int] = {}
    for t in trades:
        exit_reason_counts[t["exit_reason"]] = exit_reason_counts.get(t["exit_reason"], 0) + 1
    return {
        "entry_signal_count": entry_signals,
        "exit_signal_count": exit_signals,
        "time_cap_exit_signal_count": time_cap_exit_signals,
        "closed_pair_trades": len(trades),
        "direction_counts": direction_counts,
        "exit_reason_counts": exit_reason_counts,
        "open_position_at_end": pos is not None or pending_entry is not None,
        "exposure_fraction": exposure_bars / len(spread),
        "trades": trades,
    }


def evaluate_window(
    data_root: Path,
    manifest: dict[str, Any],
    window_id: str,
    plan: dict[str, Any],
    candidate_id: str,
    cost_env: dict[str, float],
) -> dict[str, Any]:
    btc, eth, parity = base.load_pair(data_root, manifest, window_id)
    rr = replay_variant(
        btc,
        eth,
        int(plan["shared"]["rolling_window_bars"]),
        float(plan["shared"]["entry_abs_z"]),
        candidate_id,
    )
    gross = base.metrics([float(t["gross_return"]) for t in rr["trades"]])
    net_rets, applied = base.apply_cost(rr["trades"], cost_env)
    net = base.metrics(net_rets)
    gate = plan["methodology"]["variant_development_pass_requires_each_window_independently"]
    passed = bool(
        net["trade_count"] >= int(gate["minimum_closed_pair_trades"])
        and net["compound_return"] > 0
        and (net["expectancy_per_trade"] or 0.0) > 0
    )
    return {
        "window": window_id,
        "pair_source_parity": parity,
        "entry_signal_count": rr["entry_signal_count"],
        "exit_signal_count": rr["exit_signal_count"],
        "time_cap_exit_signal_count": rr["time_cap_exit_signal_count"],
        "closed_pair_trades": rr["closed_pair_trades"],
        "direction_counts": rr["direction_counts"],
        "exit_reason_counts": rr["exit_reason_counts"],
        "open_position_at_end": rr["open_position_at_end"],
        "exposure_fraction": rr["exposure_fraction"],
        "aggregate_gross": gross,
        "aggregate_net": net,
        "cost_applied": applied,
        "window_net_gate_pass": passed,
    }


def evaluate_final_w3(
    data_root: Path,
    manifest: dict[str, Any],
    plan: dict[str, Any],
    candidate_id: str,
    cost_env: dict[str, float],
) -> dict[str, Any]:
    window_id = plan["data"]["W3"]
    btc, eth, parity = base.load_pair(data_root, manifest, window_id)
    rr = replay_variant(
        btc,
        eth,
        int(plan["shared"]["rolling_window_bars"]),
        float(plan["shared"]["entry_abs_z"]),
        candidate_id,
    )
    gross = base.metrics([float(t["gross_return"]) for t in rr["trades"]])
    net_rets, applied = base.apply_cost(rr["trades"], cost_env)
    net = base.metrics(net_rets)
    gate = plan["methodology"]["W3_final_gate"]
    passed = bool(
        net["trade_count"] >= int(gate["minimum_closed_pair_trades"])
        and net["compound_return"] > 0
        and (net["expectancy_per_trade"] or 0.0) > 0
    )
    return {
        "window": window_id,
        "candidate_id": candidate_id,
        "pair_source_parity": parity,
        "entry_signal_count": rr["entry_signal_count"],
        "exit_signal_count": rr["exit_signal_count"],
        "time_cap_exit_signal_count": rr["time_cap_exit_signal_count"],
        "closed_pair_trades": rr["closed_pair_trades"],
        "direction_counts": rr["direction_counts"],
        "exit_reason_counts": rr["exit_reason_counts"],
        "open_position_at_end": rr["open_position_at_end"],
        "exposure_fraction": rr["exposure_fraction"],
        "aggregate_gross": gross,
        "aggregate_net": net,
        "cost_applied": applied,
        "W3_net_gate_pass": passed,
    }


def candidate_development(
    data_root: Path,
    manifest: dict[str, Any],
    plan: dict[str, Any],
    candidate_id: str,
    cost_env: dict[str, float],
) -> dict[str, Any]:
    windows = [
        evaluate_window(data_root, manifest, plan["data"]["W1"], plan, candidate_id, cost_env),
        evaluate_window(data_root, manifest, plan["data"]["W2"], plan, candidate_id, cost_env),
    ]
    dev_pass = all(w["window_net_gate_pass"] for w in windows)
    min_net_expectancy = min(float(w["aggregate_net"]["expectancy_per_trade"] or -1e9) for w in windows)
    max_net_dd = max(float(w["aggregate_net"]["max_drawdown"] or 0.0) for w in windows)
    mean_funding = sum(float(w["cost_applied"]["mean_funding_pair_cost_pct"]) for w in windows) / len(windows)
    return {
        "candidate_id": candidate_id,
        "development_windows": windows,
        "development_pass": dev_pass,
        "selection_metrics": {
            "min_W1_W2_net_expectancy": min_net_expectancy,
            "max_W1_W2_net_drawdown": max_net_dd,
            "mean_pair_funding_cost_pct_across_W1_W2": mean_funding,
        },
    }


def select_candidate(rows: list[dict[str, Any]]) -> str | None:
    passing = [x for x in rows if x["development_pass"]]
    if not passing:
        return None
    passing.sort(
        key=lambda x: (
            -float(x["selection_metrics"]["min_W1_W2_net_expectancy"]),
            float(x["selection_metrics"]["max_W1_W2_net_drawdown"]),
            float(x["selection_metrics"]["mean_pair_funding_cost_pct_across_W1_W2"]),
            str(x["candidate_id"]),
        )
    )
    return str(passing[0]["candidate_id"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("development", "w3_final"), required=True)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--parent-terminal", type=Path, required=True)
    ap.add_argument("--cost-model", type=Path, required=True)
    ap.add_argument("--development-receipt", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ns = ap.parse_args()

    plan = json.loads(ns.plan.read_text())
    parent = json.loads(ns.parent_terminal.read_text())
    validate_plan(plan, parent)
    manifest = base.load_manifest(ns.manifest)
    cost_raw = json.loads(ns.cost_model.read_text())
    base.require_cost(cost_raw)
    cost_env = base.cost_envelope(cost_raw)

    if ns.mode == "development":
        rows = [candidate_development(ns.data_root, manifest, plan, cid, cost_env) for cid in (V1, V2)]
        selected = select_candidate(rows)
        passing_ids = [x["candidate_id"] for x in rows if x["development_pass"]]
        receipt: dict[str, Any] = {
            "schema_version": "zel.p4.relative_value_psa_variants.development.v1",
            "state": "PASS_P4_VARIANT_DEVELOPMENT_W3_CANDIDATE" if selected else "FAIL_P4_VARIANT_DEVELOPMENT_NET_EDGE",
            "mode": "development",
            "family": "relative_value_psa",
            "parent_candidate_id": plan["parent_candidate_id"],
            "variants_predeclared_before_replay": True,
            "W1_and_W2_are_development": True,
            "candidate_rows": rows,
            "development_passing_candidates": passing_ids,
            "selected_for_W3": selected,
            "selection_rule": plan["methodology"]["multiple_development_pass"],
            "W3_access_authorized": selected is not None,
            "W3_untouched": True,
            "cost_source": {
                "receipt_sha256": cost_raw["receipt_sha256"],
                "observed_at": cost_raw.get("observed_at"),
                "source_tier": cost_raw["source_tier"],
                "calibration_mode": cost_raw["calibration_mode"],
                "envelope": cost_env,
            },
            "DD_gate_resolved": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold" if selected else "route_change",
        }
    else:
        if ns.development_receipt is None or not ns.development_receipt.is_file():
            raise SystemExit("HOLD_DEVELOPMENT_RECEIPT_REQUIRED")
        dev = json.loads(ns.development_receipt.read_text())
        if dev.get("state") != "PASS_P4_VARIANT_DEVELOPMENT_W3_CANDIDATE" or dev.get("W3_access_authorized") is not True:
            raise SystemExit(f"HOLD_W3_NOT_AUTHORIZED:{dev.get('state')}")
        selected = dev.get("selected_for_W3")
        if selected not in (V1, V2):
            raise SystemExit(f"HOLD_SELECTED_VARIANT:{selected}")
        final = evaluate_final_w3(ns.data_root, manifest, plan, str(selected), cost_env)
        passed = bool(final["W3_net_gate_pass"])
        receipt = {
            "schema_version": "zel.p4.relative_value_psa_variants.w3_final.v1",
            "state": "PASS_P4_W3_FINAL_NET_EDGE_HOLD_DD_SSOT" if passed else "FAIL_P4_W3_FINAL_NET_EDGE",
            "mode": "w3_final",
            "family": "relative_value_psa",
            "selected_candidate_id": selected,
            "selection_was_completed_before_W3": True,
            "development_receipt_sha256": dev.get("receipt_sha256"),
            "W3_final": final,
            "W3_evaluated_once_for_selected_variant": True,
            "cost_source": {
                "receipt_sha256": cost_raw["receipt_sha256"],
                "observed_at": cost_raw.get("observed_at"),
                "source_tier": cost_raw["source_tier"],
                "calibration_mode": cost_raw["calibration_mode"],
                "envelope": cost_env,
            },
            "DD_gate_required_next": passed,
            "DD_gate_resolved": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold" if passed else "route_change",
        }

    receipt["receipt_sha256"] = base.canonical_sha(receipt)
    ns.out.parent.mkdir(parents=True, exist_ok=True)
    ns.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(receipt["state"])
    if ns.mode == "development":
        for row in receipt["candidate_rows"]:
            compact = {
                "candidate_id": row["candidate_id"],
                "development_pass": row["development_pass"],
                "selection_metrics": row["selection_metrics"],
                "windows": [
                    {
                        "window": w["window"],
                        "trades": w["aggregate_net"]["trade_count"],
                        "gross_compound": w["aggregate_gross"]["compound_return"],
                        "net_compound": w["aggregate_net"]["compound_return"],
                        "net_expectancy": w["aggregate_net"]["expectancy_per_trade"],
                        "net_pf": w["aggregate_net"]["profit_factor"],
                        "net_wr": w["aggregate_net"]["win_rate"],
                        "net_dd": w["aggregate_net"]["max_drawdown"],
                        "mean_funding_cost_pct": w["cost_applied"]["mean_funding_pair_cost_pct"],
                        "gate_pass": w["window_net_gate_pass"],
                    }
                    for w in row["development_windows"]
                ],
            }
            print(json.dumps(compact, sort_keys=True))
        print(json.dumps({"selected_for_W3": receipt["selected_for_W3"], "W3_access_authorized": receipt["W3_access_authorized"]}, sort_keys=True))
    else:
        f = receipt["W3_final"]
        print(json.dumps({
            "selected_candidate_id": receipt["selected_candidate_id"],
            "trades": f["aggregate_net"]["trade_count"],
            "gross_compound": f["aggregate_gross"]["compound_return"],
            "net_compound": f["aggregate_net"]["compound_return"],
            "net_expectancy": f["aggregate_net"]["expectancy_per_trade"],
            "net_pf": f["aggregate_net"]["profit_factor"],
            "net_wr": f["aggregate_net"]["win_rate"],
            "net_dd": f["aggregate_net"]["max_drawdown"],
            "mean_funding_cost_pct": f["cost_applied"]["mean_funding_pair_cost_pct"],
            "gate_pass": f["W3_net_gate_pass"],
        }, sort_keys=True))


if __name__ == "__main__":
    main()
