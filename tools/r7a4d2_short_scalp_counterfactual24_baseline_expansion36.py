#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCALP_CANDIDATE_COUNT = 4
SCALP_CELL_COUNT = 24
BASELINE_TARGETS = {
    "ETHUSDT": 12,
    "SOLUSDT": 12,
    "BTCUSDT": 4,
    "LINKUSDT": 4,
    "XRPUSDT": 4,
}
BASELINE_TARGET_COUNT = sum(BASELINE_TARGETS.values())
TOL = 1e-9


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def rounded(value: Any, digits: int = 10) -> float:
    return round(finite(value), digits)


def digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_symbol(value: Any) -> str:
    text = "".join(character for character in str(value or "").upper() if character.isalnum())
    aliases = {
        "BTCUSDTPERP": "BTCUSDT",
        "ETHUSDTPERP": "ETHUSDT",
        "SOLUSDTPERP": "SOLUSDT",
        "LINKUSDTPERP": "LINKUSDT",
        "XRPUSDTPERP": "XRPUSDT",
    }
    return aliases.get(text, text)


def positive_pf(value: Any, threshold: float) -> bool:
    return value == "Infinity" or (isinstance(value, (int, float)) and finite(value) > threshold)


def trade_r_values(trade: dict[str, Any]) -> tuple[float, float, float, float]:
    risk_pct = max(finite(trade.get("raw_r_distance_pct")), 1e-12)
    gross_r = finite(trade.get("gross_pnl_pct")) / risk_pct
    net_r = finite(trade.get("net_pnl_pct")) / risk_pct
    mfe_r = finite(trade.get("mfe_pct")) / risk_pct
    mae_r = abs(finite(trade.get("mae_pct"))) / risk_pct
    return gross_r, net_r, mfe_r, mae_r


def ratio_or_label(numerator: float, denominator: float) -> float | str:
    if denominator > 0:
        return round(numerator / denominator, 10)
    return "Infinity" if numerator > 0 else 0.0


def realized_rr_metrics(trades: list[dict[str, Any]], cells: list[dict[str, Any]]) -> dict[str, Any]:
    gross_rs: list[float] = []
    net_rs: list[float] = []
    mfe_rs: list[float] = []
    mae_rs: list[float] = []
    capture: list[float] = []
    for trade in trades:
        gross_r, net_r, mfe_r, mae_r = trade_r_values(trade)
        gross_rs.append(gross_r)
        net_rs.append(net_r)
        mfe_rs.append(mfe_r)
        mae_rs.append(mae_r)
        if gross_r > 0 and mfe_r > 1e-12:
            capture.append(gross_r / mfe_r)

    gross_wins = [value for value in gross_rs if value > 0]
    gross_losses = [abs(value) for value in gross_rs if value < 0]
    net_wins = [value for value in net_rs if value > 0]
    net_losses = [abs(value) for value in net_rs if value < 0]
    net_profit = sum(net_wins)
    net_loss = sum(net_losses)
    exits = Counter(str(trade.get("exit_reason") or "") for trade in trades)
    cost_axis: dict[str, float] = defaultdict(float)
    perturb_axis: dict[str, float] = defaultdict(float)
    for cell in cells:
        cost_axis[str(cell.get("cost_profile") or "")] += finite(cell.get("net_pnl_pct"))
        perturb_axis[str(cell.get("perturbation") or "")] += finite(cell.get("net_pnl_pct"))

    trade_count = len(trades)
    return {
        "trade_count": trade_count,
        "win_count": len(net_wins),
        "loss_count": len(net_losses),
        "flat_count": trade_count - len(net_wins) - len(net_losses),
        "win_rate_pct": round(len(net_wins) / trade_count * 100.0, 10) if trade_count else 0.0,
        "gross_average_win_r": round(statistics.fmean(gross_wins), 10) if gross_wins else 0.0,
        "gross_average_loss_r_abs": round(statistics.fmean(gross_losses), 10) if gross_losses else 0.0,
        "gross_realized_payoff_ratio": ratio_or_label(
            statistics.fmean(gross_wins) if gross_wins else 0.0,
            statistics.fmean(gross_losses) if gross_losses else 0.0,
        ),
        "net_average_win_r": round(statistics.fmean(net_wins), 10) if net_wins else 0.0,
        "net_average_loss_r_abs": round(statistics.fmean(net_losses), 10) if net_losses else 0.0,
        "net_realized_payoff_ratio": ratio_or_label(
            statistics.fmean(net_wins) if net_wins else 0.0,
            statistics.fmean(net_losses) if net_losses else 0.0,
        ),
        "profit_factor": ratio_or_label(net_profit, net_loss),
        "expectancy_r": round(statistics.fmean(net_rs), 10) if net_rs else 0.0,
        "net_r_sum": round(sum(net_rs), 10),
        "gross_r_sum": round(sum(gross_rs), 10),
        "max_realized_loss_r_abs": round(max(net_losses, default=0.0), 10),
        "take_profit_rate_pct": round(exits.get("take_profit", 0) / trade_count * 100.0, 10) if trade_count else 0.0,
        "stop_rate_pct": round((exits.get("stop", 0) + exits.get("stop_collision", 0)) / trade_count * 100.0, 10) if trade_count else 0.0,
        "segment_end_rate_pct": round(exits.get("segment_end", 0) / trade_count * 100.0, 10) if trade_count else 0.0,
        "exit_histogram": dict(sorted(exits.items())),
        "mean_mfe_r": round(statistics.fmean(mfe_rs), 10) if mfe_rs else 0.0,
        "mean_mae_r": round(statistics.fmean(mae_rs), 10) if mae_rs else 0.0,
        "mfe_capture_ratio": round(statistics.fmean(capture), 10) if capture else 0.0,
        "cost_profile_net_return_pct": {key: round(value, 10) for key, value in sorted(cost_axis.items())},
        "perturbation_net_return_pct": {key: round(value, 10) for key, value in sorted(perturb_axis.items())},
        "worst_cost_axis_net_return_pct": round(min(cost_axis.values()), 10) if cost_axis else 0.0,
        "worst_perturbation_axis_net_return_pct": round(min(perturb_axis.values()), 10) if perturb_axis else 0.0,
    }


def candidate_metrics(candidate_id: str, cells: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in cells if str(row.get("candidate_id") or "") == candidate_id]
    trades = [row["trade"] for row in rows if isinstance(row.get("trade"), dict)]
    return {
        "candidate_id": candidate_id,
        "cell_count": len(rows),
        "closed_trade_cell_count": len(trades),
        "invalid_geometry_count": sum(int(row.get("invalid_geometry_count") or 0) for row in rows),
        "target_reproduction_count": sum(int(row.get("target_match_count") or 0) for row in rows),
        "status_histogram": dict(sorted(Counter(str(row.get("status") or "") for row in rows).items())),
        "metrics": realized_rr_metrics(trades, rows),
    }


def economic_gate(metrics: dict[str, Any], invalid: int, closed: int, target: int) -> bool:
    payoff = metrics.get("net_realized_payoff_ratio")
    return (
        closed == target
        and invalid == 0
        and positive_pf(metrics.get("profit_factor"), 1.25)
        and finite(metrics.get("expectancy_r")) > 0.15
        and (payoff == "Infinity" or finite(payoff) > 1.5)
        and finite(metrics.get("max_realized_loss_r_abs")) <= 0.75 + 1e-7
        and finite(metrics.get("worst_cost_axis_net_return_pct")) > 0
        and finite(metrics.get("worst_perturbation_axis_net_return_pct")) > 0
    )


def s_grade_observer_gate(metrics: dict[str, Any], independent_count: int, unique_segments: int) -> bool:
    payoff = metrics.get("net_realized_payoff_ratio")
    return (
        independent_count >= 12
        and unique_segments >= 10
        and positive_pf(metrics.get("profit_factor"), 1.75)
        and finite(metrics.get("expectancy_r")) > 0.5
        and (payoff == "Infinity" or finite(payoff) > 2.0)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--stress-runner", required=True)
    parser.add_argument("--discovery-runner", required=True)
    parser.add_argument("--expansion-helper", required=True)
    parser.add_argument("--a4c-contract", required=True)
    parser.add_argument("--a4d-contract", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    stress_runner = load_module(Path(args.stress_runner).resolve(), "r7a4d2_scalp_counterfactual_runner")
    discovery_runner = load_module(Path(args.discovery_runner).resolve(), "r7a4d2_baseline_expansion_runner")
    expansion_helper = load_module(Path(args.expansion_helper).resolve(), "r7a4d2_baseline_expansion_helpers")
    a4c_contract = load_json(Path(args.a4c_contract).resolve())
    a4d_contract = load_json(Path(args.a4d_contract).resolve())
    a4d_contract["indicator_preroll_bars"] = 320

    counter_plan_path = root / "runtime/r7a4d2_short_selective_chart_gate_geometry_counterfactual_plan/counterfactual_plan_v1.json"
    diagnose_path = root / "runtime/r7a4d2_short_chart_causal_cluster_diagnose/causal_cluster_diagnose_v1.json"
    stress168_path = root / "runtime/r7a4d2_short_expanded_candidate_stress_168/stress168_proof_v1.json"
    expanded_plan_path = root / "runtime/r7a4d2_short_candidate_repair_expanded_stress_plan/expanded_stress_plan_v1.json"
    short_plan_path = root / "runtime/r7a4d2_short_execution_harness_plan/short_execution_harness_plan_v1.json"
    selected_manifest_path = root / str(a4d_contract["selected_manifest_path"])
    frozen_manifest_path = root / str(a4c_contract["frozen_manifest_path"])
    registry_path = root / str(a4d_contract["registry_path"])

    counter_plan = load_json(counter_plan_path)
    diagnose = load_json(diagnose_path)
    stress168 = load_json(stress168_path)
    expanded_plan = load_json(expanded_plan_path)
    short_plan = load_json(short_plan_path)
    selected_manifest = load_json(selected_manifest_path)
    frozen_manifest = load_json(frozen_manifest_path)
    registry = load_json(registry_path)

    blockers: list[str] = []
    if counter_plan.get("state") != "PASS_SHORT_SELECTIVE_CHART_GATE_AND_GEOMETRY_COUNTERFACTUAL_PLAN" or int(counter_plan.get("blocker_count", -1)) != 0:
        blockers.append("COUNTERFACTUAL_PLAN_INVALID")
    if counter_plan.get("next_stage") != "R7.A4D2_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36":
        blockers.append("COUNTERFACTUAL_NEXT_STAGE_MISMATCH")
    universe = counter_plan.get("universe_state") if isinstance(counter_plan.get("universe_state"), dict) else {}
    if int(universe.get("canonical_strategy_universe_count", -1)) != 25 or int(universe.get("short_target_strategy_universe_count", -1)) != 12:
        blockers.append("STRATEGY_UNIVERSE_SHAPE_INVALID")
    if diagnose.get("state") != "PASS_SHORT_CHART_CAUSAL_CLUSTER_DIAGNOSE" or int(diagnose.get("blocker_count", -1)) != 0:
        blockers.append("CAUSAL_DIAGNOSE_INVALID")
    if stress168.get("state") != "PASS_SHORT_EXPANDED_CANDIDATE_STRESS_168" or int(stress168.get("failed_cell_count", -1)) != 0:
        blockers.append("STRESS168_INVALID")
    if expanded_plan.get("state") != "PASS_SHORT_CANDIDATE_REPAIR_AND_EXPANDED_STRESS_PLAN" or int(expanded_plan.get("expanded_candidate_count", -1)) != 28:
        blockers.append("EXPANDED_PLAN_INVALID")
    if short_plan.get("state") != "PASS_SHORT_EXECUTION_HARNESS_PLAN":
        blockers.append("SHORT_PLAN_INVALID")
    if selected_manifest.get("state") != "PASS" or frozen_manifest.get("state") != "PASS":
        blockers.append("FROZEN_MARKET_LINEAGE_INVALID")

    watchlist = [row for row in counter_plan.get("scalp_counterfactual", {}).get("watchlist", []) if isinstance(row, dict)]
    if len(watchlist) != SCALP_CANDIDATE_COUNT or int(counter_plan.get("scalp_counterfactual", {}).get("execution_cell_count", -1)) != SCALP_CELL_COUNT:
        blockers.append("SCALP_WATCHLIST_SHAPE_INVALID")
    expanded_candidates = [row for row in expanded_plan.get("expanded_stress_candidates", []) if isinstance(row, dict)]
    candidate_by_id = {str(row.get("candidate_id") or ""): row for row in expanded_candidates}
    watch_ids = [str(row.get("candidate_id") or "") for row in watchlist]
    if len(set(watch_ids)) != SCALP_CANDIDATE_COUNT or any(candidate_id not in candidate_by_id for candidate_id in watch_ids):
        blockers.append("SCALP_WATCHLIST_CANDIDATE_PARITY_FAILED")

    entries = {str(row.get("strategy_id") or ""): row for row in registry.get("entries", []) if isinstance(row, dict)}
    target_ids = sorted(str(item) for item in short_plan.get("short_target_strategy_ids", []))
    costs = {str(row.get("id") or ""): row for row in a4d_contract.get("cost_profiles", []) if isinstance(row, dict)}
    perturbations = {str(row.get("id") or ""): row for row in a4d_contract.get("perturbations", []) if isinstance(row, dict)}
    if len(entries) != 25 or len(target_ids) != 12 or len(costs) != 3 or len(perturbations) != 2:
        blockers.append(f"EXECUTION_MATRIX_SHAPE_INVALID:{len(entries)}:{len(target_ids)}:{len(costs)}:{len(perturbations)}")

    canonical_paths = [registry_path, root / "backend/strategy25/canonical_strategy25_config_v1.json"]
    bindings_stress: dict[str, tuple[type[Any], str]] = {}
    bindings_discovery: dict[str, tuple[type[Any], str]] = {}
    source_registry_parity = True
    sys.path.insert(0, str(root))
    try:
        for strategy_id, entry in sorted(entries.items()):
            engine = entry.get("canonical_engine") if isinstance(entry.get("canonical_engine"), dict) else {}
            repo_path = stress_runner.safe_repo_path(str(engine.get("implementation_path") or ""))
            source_path = root / repo_path
            canonical_paths.append(source_path)
            if stress_runner.sha256_file(source_path) != str(engine.get("source_sha256") or ""):
                source_registry_parity = False
                blockers.append(f"SOURCE_REGISTRY_SHA_MISMATCH:{strategy_id}")
                continue
            if strategy_id == "scalp_snap":
                module = stress_runner.load_module(root, repo_path, "scalp_snap_cf24")
                bindings_stress[strategy_id] = stress_runner.resolve_callable(module, str(engine.get("callable") or ""))
            if strategy_id == "grid_rebalance":
                module = discovery_runner.load_module(root, repo_path, "grid_rebalance_expand36")
                bindings_discovery[strategy_id] = discovery_runner.resolve_callable(module, str(engine.get("callable") or ""))
    finally:
        sys.path.remove(str(root))

    category_inputs = frozen_manifest.get("category_inputs") if isinstance(frozen_manifest.get("category_inputs"), dict) else {}
    market_entries = [row for row in category_inputs.get("market_data", []) if isinstance(row, dict)]
    if not market_entries:
        blockers.append("FROZEN_MARKET_ENTRY_ZERO")

    protected_inputs = [
        counter_plan_path,
        diagnose_path,
        stress168_path,
        expanded_plan_path,
        short_plan_path,
        selected_manifest_path,
        frozen_manifest_path,
    ]
    for row in expanded_candidates:
        try:
            protected_inputs.append(root / stress_runner.safe_repo_path(str(row.get("source_path") or "")))
        except Exception as exc:
            blockers.append(f"EXPANDED_SOURCE_PATH_INVALID:{type(exc).__name__}:{exc}")
    protected_inputs = list(dict.fromkeys(canonical_paths + protected_inputs))
    before = stress_runner.snapshot(protected_inputs)

    side_effect_attempts: list[str] = []
    failures: list[dict[str, Any]] = []
    scalp_cells: list[dict[str, Any]] = []
    frame_cache: dict[str, Any] = {}
    sample_cache: dict[tuple[str, int, int], Any] = {}

    base_stress_contract = dict(a4d_contract)
    base_stress_contract.update({
        "short_execution_enabled": True,
        "short_target_strategy_ids": target_ids,
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
        "short_observer_target_enabled": True,
    })

    if not blockers:
        sys.path.insert(0, str(root))
        try:
            with stress_runner.side_effect_guard(side_effect_attempts):
                progress = 0
                owner, method_name = bindings_stress["scalp_snap"]
                for watch in watchlist:
                    candidate_id = str(watch["candidate_id"])
                    candidate = candidate_by_id[candidate_id]
                    source_path = stress_runner.safe_repo_path(str(candidate["source_path"]))
                    market_path = root / source_path
                    if stress_runner.sha256_file(market_path) != str(candidate.get("source_sha256") or ""):
                        failures.append({"scope": "scalp", "candidate_id": candidate_id, "error": "CANDIDATE_SOURCE_SHA_MISMATCH"})
                        continue
                    frame = frame_cache.get(source_path)
                    if frame is None:
                        frame = stress_runner.load_market_frame(market_path)
                        frame_cache[source_path] = frame
                    start = int(candidate["start_row"])
                    stop = int(candidate["end_row_exclusive"])
                    sample_key = (source_path, start, stop)
                    sample = sample_cache.get(sample_key)
                    if sample is None:
                        sample = stress_runner.select_segment_with_preroll(frame, start, stop, 320, 320)
                        sample_cache[sample_key] = sample
                    arm = str(watch.get("arm") or "")
                    for cost_id, cost in sorted(costs.items()):
                        for perturbation_id, perturbation in sorted(perturbations.items()):
                            scenario_id = digest_text(f"scalp-cf24:{candidate_id}:{arm}:{cost_id}:{perturbation_id}")[:24]
                            scenario = {
                                "scenario_id": scenario_id,
                                "strategy_id": "scalp_snap",
                                "segment_id": str(candidate["segment_id"]),
                                "regime": str(candidate["regime"]),
                                "fold": -3,
                                "cost_profile": cost_id,
                                "perturbation": perturbation_id,
                            }
                            contract = dict(base_stress_contract)
                            contract.update({
                                "short_observer_target_scenario_id": scenario_id,
                                "short_observer_target_strategy_id": "scalp_snap",
                                "short_observer_target_bar_index": int(candidate["bar_index"]),
                                "short_fill_rebase_enabled": arm == "FILL_REBASED_GEOMETRY",
                            })
                            try:
                                result = stress_runner.simulate_scenario(
                                    scenario, sample, owner, method_name, cost, perturbation, contract
                                )
                                trades = [row for row in result.get("short_trade_detail", []) if isinstance(row, dict)]
                                match_count = int(result.get("short_observer_target_match_count") or 0)
                                invalid = int(result.get("short_invalid_geometry_count") or 0)
                                if match_count > 1 or len(trades) > 1:
                                    raise ValueError(f"TARGET_MULTIPLICITY_INVALID:{match_count}:{len(trades)}")
                                if trades:
                                    status = "CLOSED_TRADE"
                                elif match_count == 0:
                                    status = "SIGNAL_NOT_REPRODUCED"
                                elif invalid:
                                    status = "INVALID_GEOMETRY"
                                else:
                                    status = "NO_CLOSED_TRADE"
                                trade = trades[0] if trades else None
                                scalp_cells.append({
                                    "candidate_id": candidate_id,
                                    "arm": arm,
                                    "segment_id": str(candidate["segment_id"]),
                                    "source_path": source_path,
                                    "bar_index": int(candidate["bar_index"]),
                                    "cost_profile": cost_id,
                                    "perturbation": perturbation_id,
                                    "status": status,
                                    "target_match_count": match_count,
                                    "invalid_geometry_count": invalid,
                                    "net_pnl_pct": finite(trade.get("net_pnl_pct")) if trade else 0.0,
                                    "trade": trade,
                                })
                            except Exception as exc:
                                failures.append({
                                    "scope": "scalp",
                                    "candidate_id": candidate_id,
                                    "cost_profile": cost_id,
                                    "perturbation": perturbation_id,
                                    "error": f"{type(exc).__name__}:{exc}",
                                })
                            progress += 1
                            if progress % 6 == 0:
                                print(f"A4D2_SCALP_CF_PROGRESS={progress}/24 FAILED={len(failures)}")
        except Exception as exc:
            blockers.append(f"SCALP_COUNTERFACTUAL_REPLAY_FAILED:{type(exc).__name__}:{exc}")
        finally:
            sys.path.remove(str(root))

    scalp_candidate_results = [candidate_metrics(candidate_id, scalp_cells) for candidate_id in watch_ids]
    scalp_trades = [row["trade"] for row in scalp_cells if isinstance(row.get("trade"), dict)]
    scalp_metrics = realized_rr_metrics(scalp_trades, scalp_cells)
    scalp_invalid = sum(int(row.get("invalid_geometry_count") or 0) for row in scalp_cells)
    scalp_closed = len(scalp_trades)
    scalp_target_matches = sum(int(row.get("target_match_count") or 0) for row in scalp_cells)
    scalp_economic_pass = economic_gate(scalp_metrics, scalp_invalid, scalp_closed, SCALP_CELL_COUNT)
    scalp_s_grade_pass = s_grade_observer_gate(scalp_metrics, SCALP_CANDIDATE_COUNT, len({str(candidate_by_id[cid].get("segment_id") or "") for cid in watch_ids}))

    prior_cells = [row for row in stress168.get("cells", []) if isinstance(row, dict) and str(row.get("candidate_id") or "") in set(watch_ids)]
    prior_candidate_results = [candidate_metrics(candidate_id, prior_cells) for candidate_id in watch_ids]
    prior_by_id = {row["candidate_id"]: row for row in prior_candidate_results}
    delta_results: list[dict[str, Any]] = []
    for current in scalp_candidate_results:
        prior = prior_by_id.get(current["candidate_id"], {})
        delta_results.append({
            "candidate_id": current["candidate_id"],
            "arm": next((str(row.get("arm") or "") for row in watchlist if str(row.get("candidate_id") or "") == current["candidate_id"]), ""),
            "closed_trade_delta": int(current.get("closed_trade_cell_count", 0)) - int(prior.get("closed_trade_cell_count", 0)),
            "invalid_geometry_delta": int(current.get("invalid_geometry_count", 0)) - int(prior.get("invalid_geometry_count", 0)),
            "net_r_sum_delta": rounded(current.get("metrics", {}).get("net_r_sum")) - rounded(prior.get("metrics", {}).get("net_r_sum")),
            "expectancy_r_delta": rounded(current.get("metrics", {}).get("expectancy_r")) - rounded(prior.get("metrics", {}).get("expectancy_r")),
        })

    all_segments: list[dict[str, Any]] = []
    rejected_market: list[dict[str, Any]] = []
    discovery_frame_cache: dict[str, Any] = {}
    skipped_preroll = 0
    if not blockers:
        try:
            all_segments, rejected_market, discovery_frame_cache, skipped_preroll = expansion_helper.build_all_segments(
                root,
                discovery_runner,
                market_entries,
                max(int(a4c_contract.get("minimum_source_rows", 640)), 640),
            )
        except Exception as exc:
            blockers.append(f"BASELINE_SEGMENT_BUILD_FAILED:{type(exc).__name__}:{exc}")

    prior_intervals = [row for row in selected_manifest.get("selected_segments", []) if isinstance(row, dict)]
    prior_intervals.extend(expanded_candidates)
    unselected = [row for row in all_segments if not expansion_helper.overlaps_selected(row, prior_intervals)]
    eligible_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for segment in unselected:
        symbol = normalize_symbol(segment.get("symbol"))
        if symbol in BASELINE_TARGETS and expansion_helper.regime_match(segment, "trend_down", 0.25):
            eligible_by_symbol[symbol].append(segment)
    for symbol in eligible_by_symbol:
        eligible_by_symbol[symbol].sort(key=lambda row: expansion_helper.regime_sort_key(row, "trend_down"))

    discovery_contract = dict(a4d_contract)
    discovery_contract.update({
        "allowed_intents": ["hold", "block"],
        "indicator_preroll_bars": 320,
        "short_execution_enabled": True,
        "short_target_strategy_ids": target_ids,
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
    })
    baseline_candidates: list[dict[str, Any]] = []
    baseline_scan_results: list[dict[str, Any]] = []
    if not blockers:
        sys.path.insert(0, str(root))
        try:
            with discovery_runner.side_effect_guard(side_effect_attempts):
                owner, method_name = bindings_discovery["grid_rebalance"]
                scan_progress = 0
                for symbol, target in BASELINE_TARGETS.items():
                    selected_for_symbol: list[dict[str, Any]] = []
                    scanned = 0
                    discovered_count = 0
                    for segment in eligible_by_symbol.get(symbol, []):
                        if len(selected_for_symbol) >= target:
                            break
                        scanned += 1
                        repo_path = str(segment["source_path"])
                        frame = discovery_frame_cache[repo_path]
                        sample = discovery_runner.select_segment_with_preroll(
                            frame,
                            int(segment["start_row"]),
                            int(segment["end_row_exclusive"]),
                            320,
                            320,
                        )
                        scenario_id = digest_text(f"baseline-expand36:{symbol}:{segment['segment_id']}")[:24]
                        scenario = {
                            "scenario_id": scenario_id,
                            "strategy_id": "grid_rebalance",
                            "segment_id": str(segment["segment_id"]),
                            "regime": "trend_down",
                            "fold": -4,
                            "cost_profile": "cost_profile_0",
                            "perturbation": "perturbation_0",
                        }
                        try:
                            result = discovery_runner.simulate_scenario(
                                scenario,
                                sample,
                                owner,
                                method_name,
                                costs["cost_profile_0"],
                                perturbations["perturbation_0"],
                                discovery_contract,
                            )
                            if int(result.get("short_closed_trade_count") or 0) != 0:
                                raise ValueError("TRACE_ONLY_SHORT_TRADE_DETECTED")
                            trace = [
                                row for row in result.get("short_candidate_trace", [])
                                if isinstance(row, dict)
                                and row.get("strategy_id") == "grid_rebalance"
                                and row.get("regime") == "trend_down"
                                and row.get("legacy_action") == "enter"
                                and row.get("candidate_state") == "FLAT_ENTER"
                            ]
                            trace.sort(key=lambda row: int(row.get("bar_index", -1)))
                            if trace:
                                discovered_count += len(trace)
                                row = trace[0]
                                candidate_id = ":".join((scenario_id, "grid_rebalance", str(int(row.get("bar_index", -1)))))
                                candidate = {
                                    "candidate_id": candidate_id,
                                    "bucket": "baseline_trend_down_cluster_expansion",
                                    "strategy_id": "grid_rebalance",
                                    "regime": "trend_down",
                                    "scenario_id": scenario_id,
                                    "segment_id": str(segment["segment_id"]),
                                    "source_path": repo_path,
                                    "source_sha256": str(segment["source_sha256"]),
                                    "symbol": symbol,
                                    "timeframe": segment.get("timeframe"),
                                    "start_row": int(segment["start_row"]),
                                    "end_row_exclusive": int(segment["end_row_exclusive"]),
                                    "start_timestamp": str(segment["start_timestamp"]),
                                    "end_timestamp": str(segment["end_timestamp"]),
                                    "segment_metrics": segment["metrics"],
                                    "bar_index": int(row.get("bar_index", -1)),
                                    "evaluation_index": int(row.get("evaluation_index", -1)),
                                    "legacy_reason": str(row.get("legacy_reason") or ""),
                                    "target_qty": finite(row.get("target_qty")),
                                    "discovery_only": True,
                                    "performance_based_selection": False,
                                }
                                selected_for_symbol.append(candidate)
                                baseline_candidates.append(candidate)
                        except Exception as exc:
                            failures.append({
                                "scope": "baseline_expansion",
                                "symbol": symbol,
                                "segment_id": segment.get("segment_id"),
                                "error": f"{type(exc).__name__}:{exc}",
                            })
                        scan_progress += 1
                        if scan_progress % 12 == 0:
                            print(f"A4D2_BASELINE_EXPANSION_PROGRESS={scan_progress} SELECTED={len(baseline_candidates)}/36 FAILED={len(failures)}")
                    baseline_scan_results.append({
                        "symbol": symbol,
                        "target_segment_count": target,
                        "eligible_segment_count": len(eligible_by_symbol.get(symbol, [])),
                        "scanned_segment_count": scanned,
                        "discovered_flat_enter_count": discovered_count,
                        "selected_candidate_count": len(selected_for_symbol),
                        "selected_unique_segment_count": len({row["segment_id"] for row in selected_for_symbol}),
                        "selected_candidates": selected_for_symbol,
                    })
        except Exception as exc:
            blockers.append(f"BASELINE_EXPANSION_SCAN_FAILED:{type(exc).__name__}:{exc}")
        finally:
            sys.path.remove(str(root))

    baseline_counts = Counter(str(row.get("symbol") or "") for row in baseline_candidates)
    baseline_expansion_ready = len(baseline_candidates) == BASELINE_TARGET_COUNT and all(
        baseline_counts.get(symbol, 0) == target for symbol, target in BASELINE_TARGETS.items()
    )
    coverage_flags = [
        f"{symbol}_TARGET_SHORTFALL:{baseline_counts.get(symbol, 0)}:{target}"
        for symbol, target in BASELINE_TARGETS.items()
        if baseline_counts.get(symbol, 0) != target
    ]

    after = stress_runner.snapshot(protected_inputs)
    mutation_paths = sorted(path for path in before if before[path] != after[path])
    if len(scalp_cells) != SCALP_CELL_COUNT:
        blockers.append(f"SCALP_CELL_COUNT_INVALID:{len(scalp_cells)}")
    if scalp_target_matches != SCALP_CELL_COUNT:
        blockers.append(f"SCALP_TARGET_REPRODUCTION_INVALID:{scalp_target_matches}")
    if failures:
        blockers.append(f"COUNTERFACTUAL_OR_EXPANSION_FAILURE:{len(failures)}")
    if mutation_paths:
        blockers.append("CANONICAL_OR_PROOF_MUTATION_DETECTED")
    if side_effect_attempts:
        blockers.append(f"SIDE_EFFECT_ATTEMPT:{len(side_effect_attempts)}")
    if not source_registry_parity:
        blockers.append("SOURCE_REGISTRY_PARITY_FAILED")
    blockers = list(dict.fromkeys(blockers))

    state = "PASS_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36" if not blockers else "HOLD_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36_INPUT"
    if blockers:
        next_stage = "R7.A4D2_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36"
    elif baseline_expansion_ready:
        next_stage = "R7.A4D2_SHORT_BASELINE_CLUSTER_EXPANSION_STRESS_216_AND_SCALP_COUNTERFACTUAL_CLOSURE"
    else:
        next_stage = "R7.A4D2_SHORT_BASELINE_CLUSTER_MARKET_COVERAGE_EXPANSION"

    evidence = {
        "schema": "r7a4d2_short_scalp_geometry_counterfactual24_baseline_expansion36_v1",
        "official_stage": "R7.A4D2_SHORT_SCALP_GEOMETRY_COUNTERFACTUAL_24_AND_BASELINE_CLUSTER_EXPANSION_36",
        "state": state,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "strategy_universe_state": universe,
        "nominal_loss_cap_r": 0.75,
        "nominal_full_tp_r": 2.5,
        "nominal_gross_payoff_ratio": round(2.5 / 0.75, 10),
        "realized_payoff_ratio_audit_required": True,
        "scalp_counterfactual": {
            "candidate_count": SCALP_CANDIDATE_COUNT,
            "target_cell_count": SCALP_CELL_COUNT,
            "completed_cell_count": len(scalp_cells),
            "closed_trade_cell_count": scalp_closed,
            "target_reproduction_count": scalp_target_matches,
            "invalid_geometry_count": scalp_invalid,
            "economic_gate_pass": scalp_economic_pass,
            "s_grade_observer_gate_pass": scalp_s_grade_pass,
            "metrics": scalp_metrics,
            "candidate_results": scalp_candidate_results,
            "prior_raw_candidate_results": prior_candidate_results,
            "counterfactual_deltas": delta_results,
            "cells": scalp_cells,
        },
        "baseline_cluster_expansion": {
            "target_segment_count": BASELINE_TARGET_COUNT,
            "selected_candidate_count": len(baseline_candidates),
            "target_counts": BASELINE_TARGETS,
            "selected_counts": dict(sorted(baseline_counts.items())),
            "expansion_ready": baseline_expansion_ready,
            "coverage_flags": coverage_flags,
            "market_source_count": len(market_entries),
            "rejected_market_source_count": len(rejected_market),
            "rejected_market_sources": rejected_market,
            "all_preroll_eligible_segment_count": len(all_segments),
            "unselected_disjoint_segment_count": len(unselected),
            "skipped_preroll_segment_count": skipped_preroll,
            "selection_uses_future_performance": False,
            "grid_strategy_quarantine_retained": True,
            "scan_results": baseline_scan_results,
            "selected_candidates": baseline_candidates,
            "candidate_manifest_sha256": canonical_hash(baseline_candidates),
        },
        "source_registry_parity": source_registry_parity,
        "mutation_path_count": len(mutation_paths),
        "mutation_paths": mutation_paths,
        "side_effect_attempt_count": len(side_effect_attempts),
        "failure_count": len(failures),
        "failures": failures,
        "strategy_mutation_allowed": False,
        "registry_mutation_allowed": False,
        "admission_expansion_allowed": False,
        "shadow_start_allowed": False,
        "full_3600_reexecution_allowed": False,
        "event_replay_2880_allowed": False,
        "next_stage": next_stage,
    }
    output_dir = root / "runtime/r7a4d2_short_scalp_counterfactual24_baseline_expansion36"
    stress_runner.atomic_json(output_dir / "counterfactual_expansion_proof_v1.json", evidence)

    print("STATE=" + state)
    print("BLOCKER_COUNT=" + str(len(blockers)))
    print("SHORT_TARGET_STRATEGY_UNIVERSE_COUNT=" + str(universe.get("short_target_strategy_universe_count", 0)))
    print("ACTIVE_REPAIR_STRATEGY_COUNT=" + str(universe.get("active_repair_strategy_count", 0)))
    print("SCALP_COUNTERFACTUAL_COMPLETED_CELL_COUNT=" + str(len(scalp_cells)))
    print("SCALP_COUNTERFACTUAL_CLOSED_TRADE_COUNT=" + str(scalp_closed))
    print("SCALP_INVALID_GEOMETRY_COUNT=" + str(scalp_invalid))
    print("SCALP_ECONOMIC_GATE_PASS=" + str(scalp_economic_pass).lower())
    print("SCALP_S_GRADE_OBSERVER_GATE_PASS=" + str(scalp_s_grade_pass).lower())
    print("SCALP_REALIZED_RR_METRICS=" + json.dumps(scalp_metrics, ensure_ascii=False, sort_keys=True))
    print("SCALP_COUNTERFACTUAL_DELTAS=" + json.dumps(delta_results, ensure_ascii=False, sort_keys=True))
    print("BASELINE_CLUSTER_EXPANSION_TARGET_COUNT=36")
    print("BASELINE_CLUSTER_EXPANSION_SELECTED_COUNT=" + str(len(baseline_candidates)))
    print("BASELINE_CLUSTER_EXPANSION_SELECTED_COUNTS=" + json.dumps(dict(sorted(baseline_counts.items())), sort_keys=True))
    print("BASELINE_CLUSTER_EXPANSION_READY=" + str(baseline_expansion_ready).lower())
    print("BASELINE_COVERAGE_FLAGS=" + json.dumps(coverage_flags, ensure_ascii=False))
    print("SOURCE_REGISTRY_PARITY=" + str(source_registry_parity).lower())
    print("MUTATION_PATH_COUNT=" + str(len(mutation_paths)))
    print("SIDE_EFFECT_ATTEMPT_COUNT=" + str(len(side_effect_attempts)))
    print("FAILURE_COUNT=" + str(len(failures)))
    print("BLOCKERS=" + json.dumps(blockers, ensure_ascii=False))
    print("PROOF_JSON=" + str(output_dir / "counterfactual_expansion_proof_v1.json"))
    print("NEXT_STAGE=" + next_stage)
    print("RC=" + ("0" if not blockers else "2"))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
