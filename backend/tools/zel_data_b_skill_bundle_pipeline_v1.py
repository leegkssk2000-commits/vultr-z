from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_DATA_B_SKILL_BUNDLE_PIPELINE_V1"
OBSERVER_ONLY = {
    "SK_ENTRY_SHORT_BEAM",
    "SK_ADD_DCA",
    "SK_ADD_AVG_DOWN",
    "SK_ADD_WATER_ADD",
    "SK_GUARD_LIQUIDATION_BUFFER",
    "SK_EXIT_STRUCTURE_INVALIDATION",
}
LOSS_ADDS = {"SK_ADD_DCA", "SK_ADD_AVG_DOWN", "SK_ADD_WATER_ADD"}
PROFIT_ADDS = {"SK_ADD_PYRAMIDING", "SK_ADD_PROFITABLE_SCALE_IN"}
SKILL_ORDER = (
    "SK_ENTRY_LONG_BEAM",
    "SK_ENTRY_SHORT_BEAM",
    "SK_ADD_DCA",
    "SK_ADD_AVG_DOWN",
    "SK_ADD_WATER_ADD",
    "SK_ADD_PYRAMIDING",
    "SK_ADD_PROFITABLE_SCALE_IN",
    "SK_EXIT_PARTIAL_30",
    "SK_EXIT_PARTIAL_STOP_30",
    "SK_EXIT_TRAILING_STOP",
    "SK_EXIT_MFE_RUNNER",
    "SK_EXIT_RUNNER_HOLD",
    "SK_EXIT_TIME_STOP",
    "SK_EXIT_BREAK_EVEN_SHIFT",
    "SK_EXIT_PROFIT_LOCK",
    "SK_RISK_VOLATILITY_REDUCE_25",
    "SK_GUARD_LIQUIDATION_BUFFER",
    "SK_EXIT_STRUCTURE_INVALIDATION",
)
SAFE = {
    "research_only": True,
    "selection_authority": False,
    "promotion_authority": False,
    "runtime_binding_allowed": False,
    "shadow_start_allowed": False,
    "paper_enabled": False,
    "live_enabled": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "economic_improvement_claim_allowed": False,
    "action": "hold",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def finite(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def nested_candidates(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    values = [row]
    for key in ("features", "entry_features", "signal_features", "context", "entry_context"):
        value = row.get(key)
        if isinstance(value, Mapping):
            values.append(value)
    return values


def pick(row: Mapping[str, Any], names: Sequence[str], default: Any = None) -> Any:
    lowered = {name.lower() for name in names}
    for source in nested_candidates(row):
        for key, value in source.items():
            if str(key).lower() in lowered and value not in (None, ""):
                return value
    return default


def normalize_trade(row: Mapping[str, Any], interval: str) -> dict[str, Any]:
    realized = finite(pick(row, ("realized_R", "realized_r")))
    if realized is None:
        raise RuntimeError("REALIZED_R_MISSING")
    mfe = finite(pick(row, ("MFE_R", "mfe_R", "mfe_r", "max_favorable_excursion_r")))
    mae = finite(pick(row, ("MAE_R", "mae_R", "mae_r", "max_adverse_excursion_r")))
    exposure = finite(pick(row, ("exposure_min", "duration_min", "hold_min", "time_exposure_min")))
    atr = finite(pick(row, ("entry_atr_pct", "atr_pct", "atr_percent")))
    liq = finite(pick(row, ("liq_buffer_pct", "liquidation_buffer_pct")))
    signal_skill = str(pick(row, ("signal_skill", "skill_name", "entry_skill"), "") or "").lower()
    return {
        "strategy_id": str(row.get("strategy_id") or ""),
        "interval": interval,
        "window_id": str(row.get("window_id") or ""),
        "event_id": str(row.get("event_id") or row.get("position_id") or ""),
        "exit_ts": str(row.get("exit_ts") or row.get("captured_at") or ""),
        "r": realized,
        "mfe": mfe,
        "mae_abs": abs(mae) if mae is not None else None,
        "exposure_min": exposure,
        "entry_atr_pct": atr,
        "liq_buffer_pct": liq,
        "signal_skill": signal_skill,
    }


def load_trades(path: Path, interval: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, Mapping):
                raise RuntimeError(f"TRADE_NOT_OBJECT:{interval}:{line_number}")
            trade = normalize_trade(value, interval)
            if not trade["strategy_id"] or not trade["window_id"] or not trade["exit_ts"]:
                raise RuntimeError(f"TRADE_IDENTITY_MISSING:{interval}:{line_number}")
            rows.append(trade)
    return rows


def max_drawdown(values: Sequence[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def profit_factor(values: Sequence[float]) -> float | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses <= 1e-12:
        return 999.0 if gains > 0 else None
    return gains / losses


def payoff_ratio(values: Sequence[float]) -> float | None:
    wins = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    if not wins or not losses:
        return None
    return statistics.fmean(wins) / statistics.fmean(losses)


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row.get("exit_ts")), str(row.get("event_id"))))
    values = [float(row["r"]) for row in ordered]
    count = len(values)
    return {
        "sample_count": count,
        "net_R": sum(values),
        "expectancy_R": statistics.fmean(values) if values else None,
        "profit_factor": profit_factor(values),
        "win_rate_pct": 100.0 * sum(value > 0 for value in values) / count if count else None,
        "payoff_ratio": payoff_ratio(values),
        "max_drawdown_R": max_drawdown(values),
    }


def metric_delta(control: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for key in ("net_R", "expectancy_R", "profit_factor", "win_rate_pct", "payoff_ratio", "max_drawdown_R"):
        left = control.get(key)
        right = candidate.get(key)
        result[key] = None if left is None or right is None else float(right) - float(left)
    return result


def require_fields(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> tuple[bool, list[str]]:
    missing = []
    for field in fields:
        if not any(row.get(field) is not None and row.get(field) != "" for row in rows):
            missing.append(field)
    return not missing, missing


def copy_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def transform(rows: Sequence[Mapping[str, Any]], skill_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output = copy_rows(rows)
    if skill_id in OBSERVER_ONLY:
        observed = 0
        if skill_id in LOSS_ADDS:
            observed = sum((row.get("mae_abs") or 0.0) >= 0.35 for row in rows)
        elif skill_id == "SK_GUARD_LIQUIDATION_BUFFER":
            observed = sum(row.get("liq_buffer_pct") is not None for row in rows)
        return output, {
            "state": "OBSERVER_ONLY",
            "fidelity": "NO_ECONOMIC_MUTATION",
            "selection_eligible": False,
            "observed_count": observed,
            "missing_fields": [],
        }

    required: dict[str, tuple[str, ...]] = {
        "SK_ENTRY_LONG_BEAM": ("signal_skill",),
        "SK_ADD_PYRAMIDING": ("mfe",),
        "SK_ADD_PROFITABLE_SCALE_IN": ("mfe",),
        "SK_EXIT_PARTIAL_30": ("mfe",),
        "SK_EXIT_PARTIAL_STOP_30": ("mae_abs",),
        "SK_EXIT_TRAILING_STOP": ("mfe",),
        "SK_EXIT_MFE_RUNNER": ("mfe",),
        "SK_EXIT_RUNNER_HOLD": ("mfe",),
        "SK_EXIT_TIME_STOP": ("exposure_min",),
        "SK_EXIT_BREAK_EVEN_SHIFT": ("mfe",),
        "SK_EXIT_PROFIT_LOCK": ("mfe",),
        "SK_RISK_VOLATILITY_REDUCE_25": ("entry_atr_pct",),
    }
    ok, missing = require_fields(rows, required.get(skill_id, ()))
    if not ok:
        return output, {
            "state": "HOLD_MISSING_REQUIRED_FIELD",
            "fidelity": "UNTESTED",
            "selection_eligible": False,
            "observed_count": 0,
            "missing_fields": missing,
        }

    triggered = 0
    result: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        r = float(row["r"])
        mfe = row.get("mfe")
        mae = row.get("mae_abs")
        if skill_id == "SK_ENTRY_LONG_BEAM":
            if "long_beam" not in str(row.get("signal_skill") or ""):
                continue
            triggered += 1
        elif skill_id == "SK_ADD_PYRAMIDING" and mfe is not None and float(mfe) >= 0.35 and r > 0:
            row["r"] = r * 1.14
            triggered += 1
        elif skill_id == "SK_ADD_PROFITABLE_SCALE_IN" and mfe is not None and float(mfe) >= 0.35 and r > 0:
            row["r"] = r * 1.28
            triggered += 1
        elif skill_id == "SK_EXIT_PARTIAL_30" and mfe is not None and float(mfe) >= 1.0:
            row["r"] = 0.3 * max(r, 0.5) + 0.7 * r
            triggered += 1
        elif skill_id == "SK_EXIT_PARTIAL_STOP_30" and mae is not None and float(mae) >= 0.5 and r < 0:
            row["r"] = r * 0.70
            triggered += 1
        elif skill_id == "SK_EXIT_TRAILING_STOP" and mfe is not None and float(mfe) >= 1.0:
            row["r"] = max(r, (float(mfe) - 1.0) * 0.25)
            triggered += 1
        elif skill_id == "SK_EXIT_MFE_RUNNER" and mfe is not None and float(mfe) >= 1.0:
            row["r"] = max(r, 0.15 + 0.35 * min(float(mfe), 3.0))
            triggered += 1
        elif skill_id == "SK_EXIT_RUNNER_HOLD" and mfe is not None and float(mfe) >= 2.0:
            row["r"] = max(r, 0.5 * min(float(mfe), 3.0))
            triggered += 1
        elif skill_id == "SK_EXIT_TIME_STOP" and row.get("exposure_min") is not None and float(row["exposure_min"]) > 90.0:
            row["r"] = r * 90.0 / max(float(row["exposure_min"]), 1.0)
            triggered += 1
        elif skill_id == "SK_EXIT_BREAK_EVEN_SHIFT" and mfe is not None and float(mfe) >= 1.0 and r < 0:
            row["r"] = max(r, -0.04)
            triggered += 1
        elif skill_id == "SK_EXIT_PROFIT_LOCK" and mfe is not None and float(mfe) >= 1.0 and r < 0.25 * float(mfe):
            row["r"] = max(r, 0.25 * min(float(mfe), 2.0))
            triggered += 1
        elif skill_id == "SK_RISK_VOLATILITY_REDUCE_25" and row.get("entry_atr_pct") is not None and float(row["entry_atr_pct"]) >= 3.5:
            row["r"] = r * 0.75
            triggered += 1
        result.append(row)
    return result, {
        "state": "TESTED_EVENT_LEVEL_COUNTERFACTUAL",
        "fidelity": "EVENT_LEVEL_COUNTERFACTUAL_NOT_EXECUTION_PROOF",
        "selection_eligible": triggered > 0,
        "observed_count": triggered,
        "missing_fields": [],
    }


def classify(control: Mapping[str, Any], candidate: Mapping[str, Any], meta: Mapping[str, Any]) -> str:
    if meta.get("state") == "OBSERVER_ONLY":
        return "OBSERVER_ONLY_NO_ECONOMIC_EFFECT"
    if meta.get("state") == "HOLD_MISSING_REQUIRED_FIELD":
        return "HOLD_MISSING_REQUIRED_FIELD"
    if int(meta.get("observed_count") or 0) == 0:
        return "NO_TRIGGER_NO_EFFECT"
    comparable = {
        "net": float(candidate.get("net_R") or 0.0) >= float(control.get("net_R") or 0.0),
        "expectancy": float(candidate.get("expectancy_R") or -1e18) >= float(control.get("expectancy_R") or -1e18),
        "pf": float(candidate.get("profit_factor") or 0.0) >= float(control.get("profit_factor") or 0.0),
        "dd": float(candidate.get("max_drawdown_R") or 0.0) <= float(control.get("max_drawdown_R") or 0.0),
    }
    wins = sum(comparable.values())
    if wins == 4:
        return "POSITIVE_MAIN_EFFECT_RESEARCH_ONLY"
    if wins >= 2:
        return "MIXED_MAIN_EFFECT_RESEARCH_ONLY"
    return "NEGATIVE_MAIN_EFFECT_RESEARCH_ONLY"


def main_effect(strategy_id: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    control = metrics(rows)
    results = []
    for skill_id in SKILL_ORDER:
        changed, meta = transform(rows, skill_id)
        candidate = metrics(changed)
        result = {
            "skill_id": skill_id,
            "control": control,
            "candidate": candidate,
            "delta": metric_delta(control, candidate),
            "classification": classify(control, candidate, meta),
            **meta,
        }
        results.append(result)
    return {"strategy_id": strategy_id, "control": control, "skills": results}


def score_effect(row: Mapping[str, Any]) -> float:
    delta = row.get("delta") or {}
    net = float(delta.get("net_R") or 0.0)
    expectancy = float(delta.get("expectancy_R") or 0.0)
    pf = float(delta.get("profit_factor") or 0.0)
    dd_reduction = -float(delta.get("max_drawdown_R") or 0.0)
    return net + 25.0 * expectancy + 2.0 * pf + 0.5 * dd_reduction


def pair_allowed(left: str, right: str, contract: Mapping[str, Any]) -> tuple[bool, str]:
    pair = {left, right}
    if pair & LOSS_ADDS and pair & PROFIT_ADDS:
        return False, "LOSS_AND_PROFIT_DIRECTION_ADD_CONFLICT"
    if "SK_EXIT_PARTIAL_STOP_30" in pair and pair & LOSS_ADDS:
        return False, "PARTIAL_STOP_WITH_LOSS_DIRECTION_ADD_FORBIDDEN"
    if pair & OBSERVER_ONLY:
        return False, "OBSERVER_ONLY_SKILL"
    new_map = {str(row["skill_id"]): row for row in contract.get("new_skills") or []}
    for skill_id, other in ((left, right), (right, left)):
        if other in set(str(value) for value in (new_map.get(skill_id) or {}).get("forbidden_with") or []):
            return False, "EXPLICIT_FORBIDDEN_PAIR"
    return True, "ALLOWED_AFTER_SINGLE_EFFECT"


def interaction_stage(strategy: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]) -> dict[str, Any]:
    singles = [
        row for row in strategy["skills"]
        if row["classification"] in {"POSITIVE_MAIN_EFFECT_RESEARCH_ONLY", "MIXED_MAIN_EFFECT_RESEARCH_ONLY"}
        and bool(row.get("selection_eligible"))
        and row["skill_id"] not in OBSERVER_ONLY
    ]
    singles = sorted(singles, key=score_effect, reverse=True)[:6]
    by_id = {row["skill_id"]: row for row in singles}
    control = strategy["control"]
    pairs = []
    for left, right in itertools.combinations(by_id, 2):
        allowed, reason = pair_allowed(left, right, contract)
        if not allowed:
            pairs.append({"skills": [left, right], "state": "BLOCKED_INCOMPATIBLE", "reason": reason})
            continue
        after_left, left_meta = transform(rows, left)
        after_pair, right_meta = transform(after_left, right)
        candidate = metrics(after_pair)
        delta = metric_delta(control, candidate)
        left_net = float((by_id[left].get("delta") or {}).get("net_R") or 0.0)
        right_net = float((by_id[right].get("delta") or {}).get("net_R") or 0.0)
        pair_net = float(delta.get("net_R") or 0.0)
        interaction_net = pair_net - left_net - right_net
        passed = (
            pair_net > 0.0
            and interaction_net > 0.0
            and float(candidate.get("expectancy_R") or -1e18) >= float(control.get("expectancy_R") or -1e18)
            and float(candidate.get("profit_factor") or 0.0) >= float(control.get("profit_factor") or 0.0)
            and int(candidate.get("sample_count") or 0) >= 20
        )
        score = pair_net + 2.0 * interaction_net - 0.5 * max(float(candidate.get("max_drawdown_R") or 0.0) - float(control.get("max_drawdown_R") or 0.0), 0.0)
        pairs.append({
            "skills": [left, right],
            "state": "PASS_POSITIVE_INTERACTION_RESEARCH_ONLY" if passed else "HOLD_INTERACTION_NOT_PROVED",
            "reason": reason,
            "control": control,
            "candidate": candidate,
            "delta": delta,
            "interaction_delta_net_R": interaction_net,
            "score": score,
            "fidelity": [left_meta["fidelity"], right_meta["fidelity"]],
        })
    passed_pairs = sorted((row for row in pairs if row.get("state") == "PASS_POSITIVE_INTERACTION_RESEARCH_ONLY"), key=lambda row: float(row["score"]), reverse=True)
    top3 = []
    for rank, row in enumerate(passed_pairs[:3], start=1):
        top3.append({
            "rank": rank,
            "skills": row["skills"],
            "score": row["score"],
            "candidate": row["candidate"],
            "interaction_delta_net_R": row["interaction_delta_net_R"],
            "status": "TOP3_RESEARCH_BUNDLE_REQUIRES_W2_W3",
        })
    return {
        "single_candidates_considered": [row["skill_id"] for row in singles],
        "pair_count": len(pairs),
        "pairs": pairs,
        "top3_bundles": top3,
    }


def write_scoreboard(path: Path, strategies: Sequence[Mapping[str, Any]]) -> None:
    fields = ["strategy_id", "skill_id", "classification", "triggered", "delta_net_R", "delta_expectancy_R", "delta_profit_factor", "delta_max_drawdown_R"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for strategy in strategies:
            for row in strategy["skills"]:
                delta = row.get("delta") or {}
                writer.writerow({
                    "strategy_id": strategy["strategy_id"],
                    "skill_id": row["skill_id"],
                    "classification": row["classification"],
                    "triggered": row.get("observed_count", 0),
                    "delta_net_R": delta.get("net_R"),
                    "delta_expectancy_R": delta.get("expectancy_R"),
                    "delta_profit_factor": delta.get("profit_factor"),
                    "delta_max_drawdown_R": delta.get("max_drawdown_R"),
                })


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = read_json(args.contract)
    if contract.get("schema_version") != "zel.skill_extension.contract.v1":
        raise RuntimeError("CONTRACT_SCHEMA_INVALID")
    rows = load_trades(Path(args.trades_15m), "15m") + load_trades(Path(args.trades_1m), "1m")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["strategy_id"]].append(row)
    if len(grouped) != 25:
        raise RuntimeError(f"STRATEGY_COUNT_NOT_25:{len(grouped)}")
    strategies = []
    classifications: dict[str, int] = defaultdict(int)
    top_bundle_count = 0
    for strategy_id, trades in sorted(grouped.items()):
        result = main_effect(strategy_id, trades)
        result["compatibility_and_interactions"] = interaction_stage(result, trades, contract)
        top_bundle_count += len(result["compatibility_and_interactions"]["top3_bundles"])
        for row in result["skills"]:
            classifications[row["classification"]] += 1
        strategies.append(result)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    terminal = {
        "schema_version": "zel.data_b.skill_bundle_pipeline.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": "PASS_DATA_B_SKILL_MAIN_EFFECT_AND_BUNDLE_RESEARCH",
        "strategy_count": len(strategies),
        "intervals": ["15m", "1m"],
        "total_trade_count": len(rows),
        "skill_count_per_strategy": len(SKILL_ORDER),
        "classification_counts": dict(sorted(classifications.items())),
        "top_bundle_count": top_bundle_count,
        "strategies": strategies,
        "contract_sha256": stable_sha(contract),
        "fidelity": "EVENT_LEVEL_COUNTERFACTUAL_SCREENING_REQUIRES_CAUSAL_PATH_REPLAY",
        "compatibility_matrix_applied": True,
        "maximum_active_skills_per_bundle": 2,
        "observer_only_excluded_from_top_bundle": True,
        "loss_profit_add_combination_forbidden": True,
        "risk_stage_prerequisite": "PASS_DATA_B_RISK_ADAPTER_ABLATION",
        "next": "W2_FRESH_FORWARD_FOR_TOP3_THEN_W3_TEMPORAL_DURABILITY",
        **SAFE,
    }
    terminal["receipt_sha256"] = stable_sha(terminal)
    write_json(output_dir / "latest.json", terminal)
    write_scoreboard(output_dir / "scoreboard.csv", strategies)
    return terminal


def self_test() -> None:
    rows = []
    for index in range(40):
        rows.append({
            "strategy_id": "fixture",
            "interval": "15m",
            "window_id": "w1",
            "event_id": str(index),
            "exit_ts": f"2026-01-01T{index % 24:02d}:00:00Z",
            "r": -0.6 if index % 4 == 0 else 0.4,
            "mfe": 1.4 if index % 3 == 0 else 0.6,
            "mae_abs": 0.7 if index % 4 == 0 else 0.2,
            "exposure_min": 120.0,
            "entry_atr_pct": 4.0 if index % 5 == 0 else 1.0,
            "liq_buffer_pct": None,
            "signal_skill": "long_beam" if index % 2 == 0 else "trend_entry",
        })
    result = main_effect("fixture", rows)
    mapping = {row["skill_id"]: row for row in result["skills"]}
    assert mapping["SK_EXIT_PARTIAL_STOP_30"]["observed_count"] == 10
    assert mapping["SK_GUARD_LIQUIDATION_BUFFER"]["classification"] == "OBSERVER_ONLY_NO_ECONOMIC_EFFECT"
    contract = read_json(Path(__file__).resolve().parents[1] / "research" / "zel_skill_extension_contract_v1.json")
    interactions = interaction_stage(result, rows, contract)
    assert all(len(row.get("skills", [])) == 2 for row in interactions["pairs"])
    assert pair_allowed("SK_EXIT_PARTIAL_STOP_30", "SK_ADD_DCA", contract)[0] is False
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION, "skills": len(result["skills"])}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract")
    parser.add_argument("--trades-15m")
    parser.add_argument("--trades-1m")
    parser.add_argument("--output-dir")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.contract, args.trades_15m, args.trades_1m, args.output_dir)):
        parser.error("--contract, --trades-15m, --trades-1m and --output-dir are required")
    result = run(args)
    print(json.dumps({"state": result["state"], "strategies": result["strategy_count"], "top_bundles": result["top_bundle_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
