#!/usr/bin/env python3
"""Read-only audit of pinned stored K/S trade rows; no collector or replay imports."""
from __future__ import annotations
import argparse
import ast
from collections import Counter, defaultdict
from decimal import Decimal, getcontext
import hashlib
import json
import platform
from pathlib import Path
import sys

getcontext().prec = 40
PINNED_SHA = "dd59cdb4fa5d6347cb40f55c8e014ef790c0fe63"
STATE = "backend/research/rebuild/a1_top5_replacement_child_prospective_v2_latest.json"
EXPECTED_STATE_SHA = "32ef0f850d546dea909094bebdf4e4df0d0b5980a66ec2db912859e7503e4d4d"
MONITOR = "research/g5/TOP5_G5A_PHASE1_STATUS_V1.json"
COLLECTOR = "backend/research/rebuild/a1_top5_replacement_child_prospective_v2.py"
SOURCE = "backend/research/rebuild/a1_top5_replacement_child_prospective_v1.py"
CONTRACT = "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
ACCOUNTING = "backend/research/contracts/top5_g5a_fresh_accounting_v1.json"
MONITOR_CODE = "backend/research/rebuild/top5_g5a_phase1_monitor_v1.py"
BOUNDARY = 1789228800000
BAR = 14400000
LANES = {
    "Keltner Reclaim": ("keltner_trend_main", "keltner_replacement_trend_pull_long_4h_h12_v2", 29),
    "Supertrend Momentum": ("supertrend_pullback_main", "supertrend_replacement_highvol_mom_long_4h_h12_v2", 26),
}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def stable(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def read(root, path):
    return json.loads((root / path).read_text())

def native_function(root, filename, name, constants):
    # Compile only the named existing pure function. Never execute collector imports/main.
    tree = ast.parse((root / filename).read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), fn], type_ignores=[])
    ns = dict(constants)
    exec(compile(ast.fix_missing_locations(module), filename, "exec"), ns)
    return ns[name]

def metrics(values):
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    eq = peak = dd = Decimal(0)
    streak = maximum = 0
    for value in values:
        eq += value
        peak = max(eq, peak)
        dd = max(dd, peak - eq)
        streak = streak + 1 if value < 0 else 0
        maximum = max(maximum, streak)
    pos = sum(wins, Decimal(0))
    neg = -sum(losses, Decimal(0))
    return {
        "T": len(values), "wins": len(wins), "losses": len(losses),
        "net_sum_trade_bps": float(eq), "net_per_T_bps": float(eq / len(values)) if values else None,
        "win_rate_pct": 100 * len(wins) / len(values) if values else None,
        "profit_factor": float(pos / neg) if neg else None,
        "payoff": float((pos / len(wins)) / (neg / len(losses))) if wins and losses else None,
        "realized_sequential_trade_bps_drawdown": float(dd),
        "drawdown_kind": "ADDITIVE_EQUAL_NOTIONAL_TRADE_BPS_NOT_ACCOUNT_NAV",
        "account_drawdown_pct": None, "marked_drawdown_bps": None,
        "max_loss_streak": maximum, "worst_trade_bps": float(min(values)) if values else None,
        "worst_three_trades_bps": [float(v) for v in sorted(values)[:3]],
        "top1_positive_contribution_pct": float(max(wins) / pos * 100) if wins else None,
        "large_winner_retention": None, "ordinary_winner_retention": None,
        "winner_retention_reason": "NO_APPROVED_COMPARATOR_OR_WINNER_CLASS_DEFINITION",
    }

def grouped_exit_metrics(rows, values):
    by_exit = defaultdict(Decimal)
    for row, value in zip(rows, values):
        by_exit[row["exit_ts"] + BAR] += value
    ordered = [(ts, by_exit[ts]) for ts in sorted(by_exit)]
    group_stats = metrics([value for _, value in ordered])
    return {
        "exit_group_count": len(ordered),
        "simultaneous_multi_trade_exit_groups": sum(1 for n in Counter(t["exit_ts"] for t in rows).values() if n > 1),
        "realized_exit_group_trade_bps_drawdown": group_stats["realized_sequential_trade_bps_drawdown"],
        "max_consecutive_losing_exit_groups": group_stats["max_loss_streak"],
        "max_grouped_realized_loss_trade_bps": max(0, -float(min(by_exit.values()))) if by_exit else None,
        "same_exit_group_tie_order_invariant": True,
        "grouping": "All trades sharing modeled completion=exit_ts+14400000 summed before equity/streak update; streak unit=exit groups, not trades.",
    }

def validate_rows(rows, child):
    problems = []
    seen = set()
    for t in rows:
        tid = t.get("closed_trade_id")
        if tid in seen:
            problems.append("duplicate_closed_trade_id")
        seen.add(tid)
        if t.get("child_id") != child:
            problems.append("child_id")
        if t.get("side") != "long":
            problems.append("side")
        for f in ("entry_px", "exit_px", "gross_bps", "net_bps", "cost_bps"):
            if f not in t or not Decimal(str(t[f])).is_finite():
                problems.append(f)
        if problems:
            continue
        if Decimal(str(t["cost_bps"])) != Decimal(20):
            problems.append("cost_bps")
        if t["entry_ts"] != t["signal_ts"] + BAR:
            problems.append("entry_ts")
        if t["exit_ts"] != t["entry_ts"] + 11 * BAR:
            problems.append("exit_ts")
        if any(t[f] % BAR for f in ("signal_ts", "entry_ts", "exit_ts")):
            problems.append("bar_alignment")
        payload = {k: t[k] for k in ("child_id", "symbol", "side", "signal_ts", "entry_ts", "exit_ts")}
        if sha(stable(payload)) != tid:
            problems.append("closed_trade_id_digest")
    expected_order = sorted(rows, key=lambda t: (t["exit_ts"], t["signal_ts"], t["symbol"], t["closed_trade_id"]))
    if rows != expected_order:
        problems.append("native_exit_chronological_order")
    return sorted(set(problems))

def audit(root):
    state_raw = (root / STATE).read_bytes()
    if sha(state_raw) != EXPECTED_STATE_SHA:
        raise ValueError("PINNED_STATE_SHA_MISMATCH")
    state = json.loads(state_raw)
    monitor = read(root, MONITOR)
    contract = read(root, CONTRACT)
    native = native_function(root, COLLECTOR, "_metrics", {"EXPECTED_COST_BPS": 20.0})
    monitor_fn = native_function(root, MONITOR_CODE, "replacement_lane", {})
    receipt_digest_ok = sha(stable({k:v for k,v in state.items() if k != "receipt_sha256"})) == state["receipt_sha256"]
    result = {
        "schema": "zel.g5.ks.readonly_arithmetic_witness.v1", "source_commit": PINNED_SHA,
        "input_sha256": {p: sha((root / p).read_bytes()) for p in (STATE, MONITOR, COLLECTOR, SOURCE, CONTRACT, ACCOUNTING, MONITOR_CODE)},
        "environment": {"python": sys.version, "platform": platform.platform(), "decimal_precision": getcontext().prec},
        "input_contract": "Pinned stored individual rows only; no network, new source collection, evaluator, claim or replay. Cost20/40 are fixed model diagnostics, never actual settlement economics.",
        "command": "python research/g5/accounting_witness_20261023/audit_ks.py --repo-root . --output <NEW_OUTSIDE_CHECKOUT>/KS_WITNESS.json",
        "state_receipt_digest_valid": receipt_digest_ok,
        "state_observed_at_utc": state["observed_at_utc"],
        "formal_pass_authority": False, "g5a_rows_reusable_for_g5b": False,
        "tests": [], "lanes": {},
    }
    for name, (lane_id, child, expected_t) in LANES.items():
        lane = state["lanes"][lane_id]
        rows = [t for t in lane["closed_trades"] if t["signal_ts"] >= BOUNDARY]
        problems = validate_rows(rows, child)
        if problems:
            raise ValueError(problems)
        assert len(rows) == expected_t == monitor["lanes"][name]["fresh_closed_T"]
        assert monitor["lanes"][name]["state_sha256"] == EXPECTED_STATE_SHA
        fresh_native = native(rows)
        all_native = native(lane["closed_trades"])
        assert all(abs(all_native[k] - v) <= 1e-8 for k, v in lane["metrics"].items() if isinstance(v,(int,float)))
        gross = [(Decimal(str(t["exit_px"])) / Decimal(str(t["entry_px"])) - 1) * 10000 for t in rows]
        net1 = [g - Decimal(str(t["cost_bps"])) for t,g in zip(rows,gross)]
        net2 = [g - 2*Decimal(str(t["cost_bps"])) for t,g in zip(rows,gross)]
        gross_error = max(abs(float(g)-t["gross_bps"]) for t,g in zip(rows,gross))
        net_error = max(abs(float(n)-t["net_bps"]) for t,n in zip(rows,net1))
        independent1 = metrics(net1)
        assert gross_error < 1e-8 and net_error < 1e-8
        compare = {"net_pnl_bps":"net_sum_trade_bps", "net_expectancy_bps":"net_per_T_bps", "profit_factor":"profit_factor", "drawdown_bps":"realized_sequential_trade_bps_drawdown"}
        assert all(abs(fresh_native[k] - independent1[v]) < 1e-8 for k,v in compare.items())
        summary = lane["source_summary"]
        implied = {s: int((v["last_bar_ts"] - v["first_bar_ts"]) // BAR + 1 - v["closed_bars"]) for s,v in summary.items()}
        complete_by_observation = [t for t in rows if t["exit_ts"] + BAR <= summary[t["symbol"]]["last_bar_ts"] + BAR]
        assert len(complete_by_observation) == len(rows)
        sequential_caveat = "Native order=(exit_ts,signal_ts,symbol,closed_trade_id); sequential DD/MaxLS can depend on ordering within a simultaneous exit group. Separate grouped metrics remove that tie-order dependence."
        scenario1 = {**independent1, "gross_sum_trade_bps": float(sum(gross)), "fixed_model_cost_per_T_bps":20.0, "fixed_model_cost_total_trade_bps":20*len(rows), "grouped_exit":grouped_exit_metrics(rows, net1), "sequential_tie_order_caveat":sequential_caveat}
        scenario2 = {**metrics(net2), "gross_sum_trade_bps":float(sum(gross)), "fixed_model_cost_per_T_bps":40.0, "fixed_model_cost_total_trade_bps":40*len(rows), "grouped_exit":grouped_exit_metrics(rows, net2), "sequential_tie_order_caveat":sequential_caveat}
        result["lanes"][name] = {
            "identity":child, "lane_id":lane_id, "boundary_ms":BOUNDARY, "boundary_utc":"2026-09-12T16:00:00Z",
            "state_path":STATE, "state_sha256":EXPECTED_STATE_SHA, "monitor_digest_match":True,
            "source_commit":PINNED_SHA, "stored_collector_closed_T":lane["closed_T"],
            "monitor_closed_T":expected_t, "verified_stored_fresh_closed_rows_T":len(rows),
            "raw_source_verified_lifecycle_T":None, "production_trade_receipts_verified_T":0,
            "market_completion_under_bar_model_T":len(complete_by_observation),
            "open_T":None, "censored_T":None, "monitor_open_T":0,
            "open_censored_reason":"Collector persists closed rows only; monitor hard-codes fresh_open_T=0, not observed lifecycle evidence.",
            "duplicate_trade_ids":0, "source_gap_count":None, "source_duplicate_count":None,
            "source_summary_implied_missing_bars":implied,
            "source_summary_limitation":"Endpoint counts imply no gap but no archived raw bars/revisions/receipt timestamps or raw SHA are bound to these individual rows.",
            "source_raw_sha256":None, "source_received_ts_ms":None, "source_available_at_ts_ms":None, "observed_latency_ms":None,
            "entry_model":"next 4h bar open", "exit_model":"12th holding bar close; stored exit_ts is bar OPEN, modeled completion=exit_ts+14400000",
            "stop_witness":"NOT_APPLICABLE_NATIVE_TIME_STOP_NO_PRICE_STOP",
            "actual_fee_bps":None, "signed_funding_bps":None, "observed_fills":None,
            "native_actual_cost1x_net_bps":None, "native_actual_cost2x_net_bps":None,
            "native_actual_PF":None, "native_actual_WR_pct":None, "account_DD_pct":None,
            "integrity":"G5_ACCOUNTING_INPUT_BLOCKED", "first_blocker":"source.raw_sha256",
            "additional_blockers":["source.available_at_ts_ms", "source.received_ts_ms", "fee.native_receipt", "funding.signed_settlements", "open_or_censored_lifecycle"],
            "frozen_scenario_only":{"classification":"STORED_ROW_ARITHMETIC_ONLY_NOT_SOURCE_OR_FORMAL_G5_VERIFICATION", "cost1x":scenario1, "cost2x":scenario2, "native_helper_cost1x":fresh_native, "independent_decimal_max_gross_abs_error_bps":gross_error, "independent_decimal_max_net_abs_error_bps":net_error},
            "source_rows":rows,
        }
        result["tests"].append({"name":name+": count, identity, row-ID hash, cost identity, chronological sort, per-symbol completion, stored native metrics and independent Decimal parity", "state":"PASS", "rows":len(rows)})
        bad = dict(rows[0]); bad.pop("cost_bps")
        assert "cost_bps" in validate_rows([bad], child)
        bad = dict(rows[0]); bad["entry_ts"] += BAR
        assert "entry_ts" in validate_rows([bad],child)
        assert "duplicate_closed_trade_id" in validate_rows([rows[0],rows[0]],child)
        assert "native_exit_chronological_order" in validate_rows(list(reversed(rows)), child)
        assert grouped_exit_metrics(rows, net1) == grouped_exit_metrics(list(reversed(rows)), list(reversed(net1)))
        stale_symbol_summary = {key:dict(value) for key,value in summary.items()}
        stale_symbol_summary[rows[-1]["symbol"]]["last_bar_ts"] = rows[-1]["exit_ts"] - BAR
        assert rows[-1]["exit_ts"] + BAR > stale_symbol_summary[rows[-1]["symbol"]]["last_bar_ts"] + BAR
        # This counterexample demonstrates why the monitor's zero is not an observed open count.
        fake = {"lanes":{lane_id:{"child_id":child,"closed_T":0,"closed_trades":[],"open_T":7,"source_summary":{}}}}
        assert monitor_fn(fake,{"lane_id":lane_id,"child_id":child,"boundary_ms":BOUNDARY})["fresh_open_T"] == 0
        result["tests"].append({"name":name+": missing-cost, shifted-entry, duplicate-ID rejection and monitor-open counterexample", "state":"PASS", "fixture_only":True})
    return result

def build(root: Path) -> dict:
    return audit(root)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", "--repo", dest="repo", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    result = audit(args.repo.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n")
    print(json.dumps({"result_path":str(args.output),"sha256":sha(args.output.read_bytes()),"lanes":{k:{"T":v["verified_stored_fresh_closed_rows_T"],"integrity":v["integrity"],"scenario1":v["frozen_scenario_only"]["cost1x"],"scenario2":v["frozen_scenario_only"]["cost2x"]} for k,v in result["lanes"].items()}},sort_keys=True))

if __name__ == "__main__":
    main()
