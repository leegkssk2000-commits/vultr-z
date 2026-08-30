#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import _validate_side
from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as child_eval
from backend.research.rebuild import a1_top5_fixed_rr_payoff_shadow_v1 as ranking_source
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import metrics

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_top5_entry_transplant_replay_v1.json"
TOP5 = ROOT / "backend/research/rebuild/a1_top5_latest_only_ssot_v1.json"
V2_FREEZE = ROOT / "backend/research/contracts/a1_top5_replacement_child_freeze_v2.json"
HARDENING = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
P16 = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
BREAK9 = ROOT / "backend/research/rebuild/a1_break_and_continue_production_main_v1.json"
KELTNER12 = ROOT / "backend/research/rebuild/a1_keltner_58pct_research_incumbent_v1.json"
SUPER11 = ROOT / "backend/research/rebuild/a1_supertrend_5455_research_incumbent_v1.json"
LATEST = ROOT / "backend/research/rebuild/a1_top5_entry_transplant_replay_latest.json"
SCHEMA = "zel.a1.top5.entry_transplant_replay.receipt.v1"
INTERVAL_MS = 14_400_000

AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "UNKNOWN"


def utc(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def trade_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (str(row.get("symbol") or ""), int(row.get("signal_ts") or 0), int(row.get("entry_ts") or 0), str(row.get("side") or ""))


def compact_trade(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(row.get("symbol") or ""),
        "signal_ts": int(row.get("signal_ts") or 0),
        "entry_ts": int(row.get("entry_ts") or 0),
        "exit_ts": int(row.get("exit_ts") or 0),
        "side": str(row.get("side") or ""),
        "reason": str(row.get("reason") or ""),
        "gross_bps": float(row.get("gross_bps") or 0.0),
        "net_bps": float(row.get("net_bps") or 0.0),
        "realized_cost_bps": None if row.get("realized_cost_bps") is None else float(row["realized_cost_bps"]),
    }


def _require_finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        raise RuntimeError(f"NONFINITE:{label}")
    if not math.isfinite(out):
        raise RuntimeError(f"NONFINITE:{label}")
    return out


def validate_trade_rows(rows: Sequence[Mapping[str, Any]], lane_id: str, expected_t: int) -> None:
    if len(rows) != expected_t:
        raise RuntimeError(f"PARENT_T_MISMATCH:{lane_id}:{len(rows)}:{expected_t}")
    keys = [trade_key(x) for x in rows]
    if len(keys) != len(set(keys)):
        raise RuntimeError(f"DUPLICATE_PARENT_TRADE:{lane_id}")
    for i, row in enumerate(rows):
        signal_ts = int(row.get("signal_ts") or 0)
        entry_ts = int(row.get("entry_ts") or 0)
        exit_ts = int(row.get("exit_ts") or 0)
        if not signal_ts or not entry_ts or not exit_ts or not (signal_ts <= entry_ts <= exit_ts):
            raise RuntimeError(f"PARENT_TIMESTAMP_ORDER:{lane_id}:{i}")
        _require_finite(row.get("gross_bps"), f"{lane_id}:{i}:gross_bps")
        _require_finite(row.get("net_bps"), f"{lane_id}:{i}:net_bps")


def select_semantic(source: Mapping[str, Any], descriptor: Mapping[str, Any], lane_id: str) -> list[dict[str, Any]]:
    rows = [dict(x) for x in source.get("trades") or [] if isinstance(x, Mapping)]
    by = {trade_key(x): x for x in rows}
    wanted = [tuple(x) for x in descriptor.get("semantic_trade_keys") or []]
    missing = [x for x in wanted if x not in by]
    if missing:
        raise RuntimeError(f"SEMANTIC_PARENT_KEY_MISSING:{lane_id}:{missing[:2]}")
    return [dict(by[x]) for x in wanted]


def assert_top5(contract: Mapping[str, Any], top5: Mapping[str, Any]) -> list[dict[str, Any]]:
    expected = [dict(x) for x in contract.get("expected_parent_lanes") or []]
    actual = [dict(x) for x in top5.get("top5") or [] if isinstance(x, Mapping)]
    if len(expected) != 5 or len(actual) != 5:
        raise RuntimeError("EXACT_TOP5_REQUIRED")
    for exp, row in zip(expected, actual):
        if int(row.get("rank") or 0) != int(exp["rank"]):
            raise RuntimeError("TOP5_RANK_DRIFT")
        if str(row.get("lane_id") or "") != str(exp["lane_id"]) or str(row.get("strategy_id") or "") != str(exp["strategy_id"]):
            raise RuntimeError(f"TOP5_IDENTITY_DRIFT:{exp['lane_id']}")
        if row.get("frozen_parent"):
            actual_t = int((row.get("frozen_parent") or {}).get("T") or 0)
        else:
            actual_t = int((row.get("current") or {}).get("T") or 0)
        if actual_t != int(exp["frozen_T"]):
            raise RuntimeError(f"TOP5_FROZEN_T_DRIFT:{exp['lane_id']}:{actual_t}")
    return expected


def parent_sets(
    contract: Mapping[str, Any], top5: Mapping[str, Any], trend30: Mapping[str, Any], a4: Mapping[str, Mapping[str, Any]], break_source: Mapping[str, Any]
) -> list[dict[str, Any]]:
    expected = assert_top5(contract, top5)
    p16 = [dict(x) for x in read(P16).get("trades") or []]
    broad30 = [dict(x) for x in trend30.get("trades") or []]
    break9 = [dict(x) for x in read(BREAK9).get("trades") or []]
    source_break_keys = {trade_key(x) for x in break_source.get("trades") or [] if isinstance(x, Mapping)}
    if not {trade_key(x) for x in break9}.issubset(source_break_keys):
        raise RuntimeError("BREAK9_NOT_SUBSET_OF_IMMUTABLE_SOURCE")
    k12 = select_semantic(a4["keltner_trend"], read(KELTNER12), "keltner_trend_main")
    s11 = select_semantic(a4["supertrend_pullback"], read(SUPER11), "supertrend_pullback_main")
    rows_by_lane = {
        "trend_rider_primary_wr8125": p16,
        "trend_rider_broad_wr7000": broad30,
        "break_and_continue_main": break9,
        "keltner_trend_main": k12,
        "supertrend_pullback_main": s11,
    }
    source_lineage = {
        "trend_rider_primary_wr8125": {"path": str(P16.relative_to(ROOT)), "receipt_sha256": read(P16).get("receipt_sha256")},
        "trend_rider_broad_wr7000": {"artifact_receipt_sha256": trend30.get("receipt_sha256"), "artifact_id": 9446790894},
        "break_and_continue_main": {"path": str(BREAK9.relative_to(ROOT)), "receipt_sha256": read(BREAK9).get("receipt_sha256"), "artifact_id": 9603011773},
        "keltner_trend_main": {"path": str(KELTNER12.relative_to(ROOT)), "receipt_sha256": read(KELTNER12).get("receipt_sha256"), "artifact_id": 9614562185},
        "supertrend_pullback_main": {"path": str(SUPER11.relative_to(ROOT)), "receipt_sha256": read(SUPER11).get("receipt_sha256"), "artifact_id": 9614562185},
    }
    out: list[dict[str, Any]] = []
    for exp in expected:
        lane_id = str(exp["lane_id"])
        rows = rows_by_lane[lane_id]
        validate_trade_rows(rows, lane_id, int(exp["frozen_T"]))
        out.append({
            **exp,
            "rows": rows,
            "source_lineage": source_lineage[lane_id],
            "parent_trade_identity_sha256": stable([trade_key(x) for x in rows]),
            "parent_payload_sha256": stable([compact_trade(x) for x in rows]),
            "rr_exit_contract_sha256": stable([
                {
                    "key": trade_key(x),
                    "intent_geometry": x.get("intent_geometry"),
                    "exit_ts": int(x.get("exit_ts") or 0),
                    "exit": x.get("exit"),
                    "reason": x.get("reason"),
                    "gross_bps": float(x.get("gross_bps") or 0.0),
                    "net_bps": float(x.get("net_bps") or 0.0),
                    "realized_cost_bps": x.get("realized_cost_bps"),
                }
                for x in rows
            ]),
        })
    return out


def architectures(contract: Mapping[str, Any], freeze: Mapping[str, Any]) -> list[dict[str, Any]]:
    if freeze.get("schema_version") != "zel.a1.top5.replacement_child_freeze.v2":
        raise RuntimeError("V2_FREEZE_SCHEMA_DRIFT")
    rows = [dict(x) for x in freeze.get("children") or [] if isinstance(x, Mapping)]
    if len(rows) != int(contract.get("expected_architecture_count") or 0):
        raise RuntimeError("V2_ARCHITECTURE_COUNT_DRIFT")
    out = []
    for row in rows:
        spec = row.get("executable_spec")
        if not isinstance(spec, Mapping) or str(spec.get("bar_interval")) != "4h":
            raise RuntimeError("V2_EXECUTABLE_4H_SPEC_REQUIRED")
        if not str(spec.get("entry_rule") or "") or not list(spec.get("features") or []):
            raise RuntimeError("V2_EXECUTABLE_RULE_REQUIRED")
        out.append({
            "architecture_id": str(row.get("child_id") or ""),
            "architecture_family": str(row.get("architecture_family") or ""),
            "source_lane_id": str(row.get("lane_id") or ""),
            "spec": dict(spec),
            "architecture_revision_sha256": stable({
                "architecture_family": row.get("architecture_family"),
                "alpha_dsl_identical_to_v1": row.get("alpha_dsl_identical_to_v1"),
                "executable_spec": spec,
            }),
        })
    if len({x["architecture_id"] for x in out}) != 3:
        raise RuntimeError("V2_ARCHITECTURE_ID_DUPLICATE")
    return out


def available_bar_index(rows: Sequence[Mapping[str, Any]], signal_ts: int) -> int | None:
    opens = [int(x["ts"]) for x in rows]
    i = bisect.bisect_right(opens, int(signal_ts) - INTERVAL_MS) - 1
    return i if i >= 0 else None


def architecture_accepts(row: Mapping[str, Any], bars: list[dict[str, float]], engine: Any, spec: Mapping[str, Any]) -> tuple[bool, int | None]:
    idx = available_bar_index(bars, int(row["signal_ts"]))
    if idx is None or idx < 50:
        return False, idx
    side_rule = str(spec.get("side_rule") or "")
    if side_rule == "long" and str(row.get("side")) != "long":
        return False, idx
    if side_rule == "short" and str(row.get("side")) != "short":
        return False, idx
    try:
        return bool(engine.eval(str(spec["entry_rule"]), idx)), idx
    except (TypeError, ZeroDivisionError, ValueError):
        return False, idx


def metric_plus(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = metrics(rows)
    vals = [float(x["net_bps"]) for x in rows]
    out.update({
        "wins": sum(1 for x in vals if x > 0),
        "losses": sum(1 for x in vals if x < 0),
        "profit_factor_unbounded": bool(vals and any(x > 0 for x in vals) and not any(x < 0 for x in vals)),
        "realized_cost_bps_sum": sum(float(x.get("realized_cost_bps") or 0.0) for x in rows),
    })
    return out


def delta(child: Mapping[str, Any], parent: Mapping[str, Any], key: str) -> float | None:
    if child.get(key) is None or parent.get(key) is None:
        return None
    return float(child[key]) - float(parent[key])


def cell_eligibility(cell: Mapping[str, Any], rule: Mapping[str, Any]) -> tuple[bool, dict[str, bool], list[str]]:
    m = cell["metrics"]
    base = cell["parent_metrics"]
    pf = m.get("profit_factor")
    payoff = m.get("payoff")
    improvements = {
        "net_pnl_bps": float(m.get("net_pnl_bps") or 0.0) > float(base.get("net_pnl_bps") or 0.0),
        "net_expectancy_bps": float(m.get("net_expectancy_bps") or -1e30) > float(base.get("net_expectancy_bps") or -1e30),
        "profit_factor": pf is not None and base.get("profit_factor") is not None and float(pf) > float(base["profit_factor"]),
        "drawdown_bps": float(m.get("drawdown_bps") or 0.0) < float(base.get("drawdown_bps") or 0.0),
    }
    checks = {
        "sample_minimum": int(m.get("trades") or 0) >= int(rule["minimum_closed_T"]),
        "retention_minimum": float(cell.get("retention_pct") or 0.0) >= float(rule["minimum_retention_pct"]),
        "net_pnl_positive": float(m.get("net_pnl_bps") or 0.0) > float(rule["minimum_net_pnl_bps_exclusive"]),
        "net_expectancy_positive": m.get("net_expectancy_bps") is not None and float(m["net_expectancy_bps"]) > float(rule["minimum_net_expectancy_bps_exclusive"]),
        "profit_factor_minimum": pf is not None and float(pf) >= float(rule["minimum_profit_factor"]),
        "payoff_minimum": payoff is not None and float(payoff) >= float(rule["minimum_payoff_ratio"]),
        "win_rate_harm_maximum": float(cell.get("win_rate_harm_pp") or 0.0) <= float(rule["maximum_win_rate_harm_pp"]),
        "economic_improvement": any(improvements.values()),
    }
    failed = [k for k, v in checks.items() if not v]
    return not failed, checks, failed


def evaluate(
    parents: list[dict[str, Any]], archs: list[dict[str, Any]], bars_by_symbol: Mapping[str, list[dict[str, float]]], contract: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    cells: list[dict[str, Any]] = []
    selection_rule = contract["selection_rule"]
    engines: dict[tuple[str, str], Any] = {}
    for arch in archs:
        spec = arch["spec"]
        for symbol, bars in bars_by_symbol.items():
            _, engine = child_eval._features(bars, spec)
            engine.validate(str(spec["entry_rule"]))
            _validate_side(str(spec.get("side_rule") or ""), engine)
            engines[(arch["architecture_id"], symbol)] = engine

    for parent in parents:
        base_rows = [dict(x) for x in parent["rows"]]
        base_m = metric_plus(base_rows)
        base_keys = [trade_key(x) for x in base_rows]
        for arch in archs:
            accepted: list[dict[str, Any]] = []
            rejected: list[dict[str, Any]] = []
            feature_bar_refs: list[dict[str, Any]] = []
            for row in base_rows:
                symbol = str(row["symbol"])
                bars = bars_by_symbol[symbol]
                ok, idx = architecture_accepts(row, bars, engines[(arch["architecture_id"], symbol)], arch["spec"])
                ref = None if idx is None or idx < 0 else int(bars[idx]["ts"])
                feature_bar_refs.append({"trade_key": trade_key(row), "feature_bar_open_ts": ref})
                (accepted if ok else rejected).append(dict(row))
            if any(compact_trade(x) != compact_trade(y) for x, y in zip(accepted, [x for x in base_rows if trade_key(x) in {trade_key(a) for a in accepted}])):
                raise RuntimeError("PARENT_PAYLOAD_MUTATION_DETECTED")
            accepted_keys = [trade_key(x) for x in accepted]
            if len(accepted_keys) != len(set(accepted_keys)) or not set(accepted_keys).issubset(set(base_keys)):
                raise RuntimeError("CELL_TRADE_IDENTITY_INVALID")
            m = metric_plus(accepted)
            rejected_wins = sum(1 for x in rejected if float(x["net_bps"]) > 0)
            rejected_losses = sum(1 for x in rejected if float(x["net_bps"]) < 0)
            retention = len(accepted) / len(base_rows) * 100.0
            wr_harm = 0.0 if m.get("win_rate") is None else max(0.0, (float(base_m["win_rate"]) - float(m["win_rate"])) * 100.0)
            row = {
                "experiment_id": stable({"parent": parent["lane_id"], "architecture": arch["architecture_id"], "contract": file_sha(CONTRACT)})[:24],
                "parent_rank": int(parent["rank"]),
                "parent_lane_id": parent["lane_id"],
                "parent_strategy_id": parent["strategy_id"],
                "parent_revision_sha256": parent["parent_payload_sha256"],
                "parent_trade_identity_sha256": parent["parent_trade_identity_sha256"],
                "parent_rr_exit_contract_sha256": parent["rr_exit_contract_sha256"],
                "architecture_id": arch["architecture_id"],
                "architecture_family": arch["architecture_family"],
                "architecture_revision_sha256": arch["architecture_revision_sha256"],
                "parent_metrics": base_m,
                "metrics": m,
                "retention_pct": retention,
                "rejected_T": len(rejected),
                "rejected_wins": rejected_wins,
                "rejected_losses": rejected_losses,
                "rejection_loss_precision": (rejected_losses / len(rejected)) if rejected else None,
                "win_rate_harm_pp": wr_harm,
                "delta_vs_parent": {k: delta(m, base_m, k) for k in ("net_pnl_bps", "net_expectancy_bps", "profit_factor", "payoff", "win_rate", "drawdown_bps")},
                "accepted_trade_keys": [list(x) for x in accepted_keys],
                "rejected_trade_keys": [list(trade_key(x)) for x in rejected],
                "feature_bar_refs_sha256": stable(feature_bar_refs),
                "native_parent_payload_preserved": True,
                "new_trade_admission": False,
                "parent_exit_mutated": False,
                "cost_rededucted": False,
            }
            eligible, checks, failed = cell_eligibility(row, selection_rule)
            row["selection_checks"] = checks
            row["failed_selection_checks"] = failed
            row["eligible"] = eligible
            row["score"] = ranking_source.score(m, m.get("payoff")) if eligible else None
            cells.append(row)

    if len(cells) != int(contract["expected_cell_count"]):
        raise RuntimeError(f"CELL_COUNT_DRIFT:{len(cells)}")
    eligible_cells = [x for x in cells if x["eligible"]]
    eligible_cells.sort(key=lambda x: (
        -float(x["score"]),
        -float(x["metrics"]["net_pnl_bps"]),
        float(x["metrics"]["drawdown_bps"]),
        -float(x["retention_pct"]),
        int(x["parent_rank"]),
        str(x["architecture_id"]),
    ))
    winner = dict(eligible_cells[0]) if eligible_cells else None
    ranked = sorted(cells, key=lambda x: (
        not bool(x["eligible"]),
        -(float(x["score"]) if x["score"] is not None else -1e30),
        -float(x["metrics"]["net_pnl_bps"]),
        float(x["metrics"]["drawdown_bps"]),
        -float(x["retention_pct"]),
        int(x["parent_rank"]),
        str(x["architecture_id"]),
    ))
    for i, row in enumerate(ranked, 1):
        row["rank"] = i
        row["decision"] = "WINNER_FOR_FRESH_G4_CANDIDATE_ONLY" if winner and row["experiment_id"] == winner["experiment_id"] else ("ELIGIBLE_NOT_SELECTED" if row["eligible"] else "REPLAY_REJECT")
    return ranked, winner


def run(trend30_path: Path, a4_dir: Path, break_dir: Path, output: Path, *, bars_override: Mapping[str, list[dict[str, float]]] | None = None) -> dict[str, Any]:
    contract, top5, freeze, hardening = read(CONTRACT), read(TOP5), read(V2_FREEZE), read(HARDENING)
    if contract.get("schema_version") != "zel.a1.top5.entry_transplant_replay.contract.v1" or contract.get("state") != "PREREGISTERED_TOP5_X_V2_ENTRY_TRANSPLANT_REPLAY":
        raise RuntimeError("TRANSPLANT_CONTRACT_INVALID")
    if float((hardening.get("survivor_gate") or {}).get("minimum_retention_pct") or -1) != float(contract["selection_rule"]["minimum_retention_pct"]):
        raise RuntimeError("RETENTION_POLICY_DRIFT")
    trend30 = read(trend30_path)
    a4 = {"keltner_trend": read(a4_dir / "keltner_trend_exact_parent.json"), "supertrend_pullback": read(a4_dir / "supertrend_pullback_exact_parent.json")}
    break_source = read(break_dir / "break_and_continue_exact_parent.json")
    parents = parent_sets(contract, top5, trend30, a4, break_source)
    archs = architectures(contract, freeze)
    all_parent_rows = [x for parent in parents for x in parent["rows"]]
    min_signal = min(int(x["signal_ts"]) for x in all_parent_rows)
    max_signal = max(int(x["signal_ts"]) for x in all_parent_rows)
    symbols = sorted({str(x["symbol"]) for x in all_parent_rows})
    bars_by_symbol = dict(bars_override or {})
    if not bars_by_symbol:
        bars_by_symbol = {symbol: child_eval._bars(symbol, "4h", min_signal, max_signal + INTERVAL_MS) for symbol in symbols}
    if set(bars_by_symbol) != set(symbols):
        raise RuntimeError(f"BAR_SYMBOL_SET_DRIFT:{sorted(bars_by_symbol)}:{symbols}")
    source_summary: dict[str, Any] = {}
    for symbol in symbols:
        rows = bars_by_symbol[symbol]
        if len(rows) < 60:
            raise RuntimeError(f"INSUFFICIENT_4H_HISTORY:{symbol}:{len(rows)}")
        ts = [int(x["ts"]) for x in rows]
        if ts != sorted(ts) or len(ts) != len(set(ts)):
            raise RuntimeError(f"BAR_ORDER_OR_DUPLICATE:{symbol}")
        used = [x for x in rows if int(x["ts"]) + INTERVAL_MS <= max_signal]
        source_summary[symbol] = {
            "closed_4h_bars": len(rows),
            "first_open_ts": ts[0],
            "last_open_ts": ts[-1],
            "used_through_parent_signal_sha256": stable(used),
        }
    cells, winner = evaluate(parents, archs, bars_by_symbol, contract)
    accepted_hashes = {stable(x["accepted_trade_keys"]) for x in cells}
    architecture_effect_observed = len(accepted_hashes) > 1
    integrity = {
        "state": "PASS" if len(cells) == 15 and architecture_effect_observed else "FAIL",
        "cell_count": len(cells),
        "expected_cell_count": 15,
        "all_parent_payloads_preserved": all(x["native_parent_payload_preserved"] for x in cells),
        "all_parent_exits_unchanged": all(not x["parent_exit_mutated"] for x in cells),
        "cost_rededuction_count": sum(1 for x in cells if x["cost_rededucted"]),
        "new_trade_admission_count": sum(1 for x in cells if x["new_trade_admission"]),
        "architecture_effect_observed": architecture_effect_observed,
        "distinct_accepted_identity_sets": len(accepted_hashes),
        "future_bar_access_count": 0,
        "duplicate_trade_count": 0,
        "nan_or_inf_count": 0,
        "partial_winner_allowed": False,
    }
    if integrity["state"] != "PASS":
        winner = None
    deterministic_payload = {
        "contract_sha256": file_sha(CONTRACT),
        "top5_sha256": file_sha(TOP5),
        "v2_freeze_sha256": file_sha(V2_FREEZE),
        "hardening_sha256": file_sha(HARDENING),
        "parents": [{k: x[k] for k in ("rank", "lane_id", "strategy_id", "frozen_T", "parent_trade_identity_sha256", "parent_payload_sha256", "rr_exit_contract_sha256", "source_lineage")} for x in parents],
        "architectures": [{k: x[k] for k in ("architecture_id", "architecture_family", "architecture_revision_sha256")} for x in archs],
        "data_boundary": {"minimum_parent_signal_ts": min_signal, "maximum_parent_signal_ts": max_signal},
        "source_summary": source_summary,
        "cells": cells,
        "winner_experiment_id": winner.get("experiment_id") if winner else None,
        "integrity": integrity,
    }
    state = "PASS_15_CELL_REPLAY_WINNER_FROZEN_FOR_G4_CANDIDATE_ONLY" if winner else ("FAIL_15_CELL_REPLAY_INTEGRITY" if integrity["state"] != "PASS" else "FALSIFIED_NO_ELIGIBLE_TRANSPLANT_WINNER")
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_master_sha": git_head(),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "contract_sha256": file_sha(CONTRACT),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": file_sha(Path(__file__).resolve()),
        "top5_path": str(TOP5.relative_to(ROOT)),
        "top5_sha256": file_sha(TOP5),
        "v2_freeze_path": str(V2_FREEZE.relative_to(ROOT)),
        "v2_freeze_sha256": file_sha(V2_FREEZE),
        "hardening_path": str(HARDENING.relative_to(ROOT)),
        "hardening_sha256": file_sha(HARDENING),
        "data_boundary": {
            "minimum_parent_signal_ts": min_signal,
            "minimum_parent_signal_utc": utc(min_signal),
            "maximum_parent_signal_ts": max_signal,
            "maximum_parent_signal_utc": utc(max_signal),
            "latest_feature_bar_must_close_not_after_parent_signal": True,
        },
        "parent_count": len(parents),
        "architecture_count": len(archs),
        "cell_count": len(cells),
        "eligible_cell_count": sum(1 for x in cells if x["eligible"]),
        "parents": deterministic_payload["parents"],
        "architectures": deterministic_payload["architectures"],
        "selection_rule": contract["selection_rule"],
        "cells": cells,
        "winner": winner,
        "historical_replay_is_g4_pass": False,
        "winner_requires_fresh_g4_activation": bool(winner),
        "integrity": integrity,
        "source_summary": source_summary,
        "deterministic_result_sha256": stable(deterministic_payload),
        **AUTH,
    }
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k not in {"receipt_sha256", "observed_at_utc"}})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert available_bar_index([{"ts": 0}, {"ts": INTERVAL_MS}], INTERVAL_MS) == 0
    assert available_bar_index([{"ts": 0}, {"ts": INTERVAL_MS}], 2 * INTERVAL_MS) == 1
    row = {
        "parent_metrics": {"net_pnl_bps": 100, "net_expectancy_bps": 10, "profit_factor": 1.2, "drawdown_bps": 50},
        "metrics": {"trades": 6, "net_pnl_bps": 120, "net_expectancy_bps": 20, "profit_factor": 1.5, "payoff": 2, "drawdown_bps": 40},
        "retention_pct": 60,
        "win_rate_harm_pp": 5,
    }
    ok, checks, failed = cell_eligibility(row, read(CONTRACT)["selection_rule"])
    assert ok and all(checks.values()) and not failed
    bad = json.loads(json.dumps(row)); bad["retention_pct"] = 59.99
    assert cell_eligibility(bad, read(CONTRACT)["selection_rule"])[0] is False
    c = read(CONTRACT)
    assert c["expected_cell_count"] == 15 and c["transplant_semantics"]["parent_exit_unchanged"] is True
    print("PASS_A1_TOP5_ENTRY_TRANSPLANT_REPLAY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trend30-source", type=Path)
    ap.add_argument("--a4-source-dir", type=Path)
    ap.add_argument("--break-source-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_top5_entry_transplant_replay_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if None in (args.trend30_source, args.a4_source_dir, args.break_source_dir):
        raise SystemExit("--trend30-source --a4-source-dir --break-source-dir required")
    result = run(args.trend30_source, args.a4_source_dir, args.break_source_dir, args.out)
    print(json.dumps({
        "state": result["state"],
        "cell_count": result["cell_count"],
        "eligible_cell_count": result["eligible_cell_count"],
        "winner": None if result["winner"] is None else {
            "parent_lane_id": result["winner"]["parent_lane_id"],
            "architecture_id": result["winner"]["architecture_id"],
            "T": result["winner"]["metrics"]["trades"],
            "net_pnl_bps": result["winner"]["metrics"]["net_pnl_bps"],
            "score": result["winner"]["score"],
        },
        "deterministic_result_sha256": result["deterministic_result_sha256"],
    }, sort_keys=True))
    return 0 if result["integrity"]["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
