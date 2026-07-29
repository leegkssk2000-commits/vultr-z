from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

VERSION = "R7A4D_STRATEGY11_CAUSE_AWARE_ROTATION_L090_V1"
AXIS_ORDER = (
    "ENTRY_CONTEXT_GATE", "CANDLE_STRUCTURE_GATE", "TREND_REGIME_GATE",
    "VOLATILITY_GATE", "VOLUME_FLOW_GATE", "MOMENTUM_GATE", "SESSION_GATE",
    "SYMBOL_EXCLUSION", "STOP", "TARGET", "BREAKEVEN", "PARTIAL",
    "MFE_TRAILING", "TIME_STOP",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True, allow_nan=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def profile(root: Path, alias: str) -> dict[str, Any]:
    matches = [p for p in root.rglob(f"{alias}.json") if "profiles" in p.parts]
    if len(matches) != 1:
        raise RuntimeError(f"PROFILE_RESOLUTION_FAILED:{alias}:{len(matches)}")
    return read_json(matches[0])


def classify_feature(feature: str) -> str:
    value = feature.lower()
    if any(token in value for token in ("rejection", "sweep", "fvg", "directional_close", "candle")):
        return "CANDLE_STRUCTURE_GATE"
    if any(token in value for token in ("volume", "obv", "mfi")):
        return "VOLUME_FLOW_GATE"
    if any(token in value for token in ("rsi", "cci", "stoch", "macd", "momentum")):
        return "MOMENTUM_GATE"
    if any(token in value for token in ("atr", "squeeze", "bb_", "boll", "keltner", "volatility")):
        return "VOLATILITY_GATE"
    if any(token in value for token in ("no_late", "session", "active_")):
        return "SESSION_GATE"
    if any(token in value for token in ("trend", "ema", "adx", "htf", "supertrend")):
        return "TREND_REGIME_GATE"
    return "ENTRY_CONTEXT_GATE"


def metric(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def summarize_variant(variant: dict[str, Any]) -> dict[str, Any]:
    ladder = variant.get("ladder_check") or {}
    return {
        "variant_id": variant.get("variant_id"),
        "axis": (variant.get("candidate_config") or {}).get("axis"),
        "trade_count": int(variant.get("trade_count") or 0),
        "retention_pct": metric(ladder.get("trade_retention_pct")),
        "net_return_pct_sum": metric(variant.get("net_return_pct_sum")),
        "net_profit_factor": metric(variant.get("net_profit_factor")),
        "payoff_ratio": variant.get("payoff_ratio"),
        "max_drawdown_pct": metric(variant.get("max_drawdown_pct")),
        "positive_fresh_windows": int(variant.get("positive_fresh_windows") or 0),
        "improved_primary_metrics": int(ladder.get("improved_primary_metrics") or 0),
        "average_loss_nonworse": bool(ladder.get("average_loss_nonworse")),
        "normal_worst_net_loss_R": ladder.get("normal_worst_net_loss_R"),
        "stress_worst_net_loss_R": ladder.get("stress_worst_net_loss_R"),
        "research_pass": bool(ladder.get("research_pass")),
    }


def classify_failure(final_row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    control = summarize_variant(final_row["variants"][0])
    candidates = [summarize_variant(v) for v in final_row["variants"][1:]]
    nonzero = [v for v in candidates if v["trade_count"] > 0]
    zero_count = sum(v["trade_count"] == 0 for v in candidates)
    near_pass = [v for v in nonzero if v["net_return_pct_sum"] > 0 and v["net_profit_factor"] > 1]
    near_breakeven = [
        v for v in nonzero
        if v["retention_pct"] >= 80
        and v["net_return_pct_sum"] > -0.50
        and v["net_profit_factor"] >= 0.85
        and v["positive_fresh_windows"] >= 1
    ]
    retained_negative = [v for v in nonzero if v["retention_pct"] >= 50 and v["net_return_pct_sum"] <= 0]

    if near_pass:
        fingerprint = "NEAR_PASS_LOSS_SHAPE"
    elif near_breakeven:
        fingerprint = "NEAR_BREAKEVEN_ECONOMICS"
    elif candidates and zero_count / len(candidates) >= 0.5:
        fingerprint = "GATE_OVERFILTER_ZERO_TRADES"
    elif retained_negative:
        fingerprint = "RETAINED_BUT_NEGATIVE_EDGE"
    else:
        fingerprint = "SPARSE_OR_UNRESOLVED_EDGE"

    return fingerprint, {
        "fingerprint": fingerprint,
        "control": control,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "zero_trade_candidate_count": zero_count,
        "nonzero_candidate_count": len(nonzero),
        "near_pass_candidate_ids": [v["variant_id"] for v in near_pass],
        "near_breakeven_candidate_ids": [v["variant_id"] for v in near_breakeven],
        "retained_negative_candidate_ids": [v["variant_id"] for v in retained_negative],
    }


def priority_for(fingerprint: str) -> tuple[str, ...]:
    if fingerprint == "NEAR_PASS_LOSS_SHAPE":
        return ("STOP", "BREAKEVEN", "MFE_TRAILING", "TIME_STOP", "PARTIAL", "TARGET",
                "MOMENTUM_GATE", "SESSION_GATE", "SYMBOL_EXCLUSION")
    if fingerprint == "NEAR_BREAKEVEN_ECONOMICS":
        return ("TARGET", "PARTIAL", "MFE_TRAILING", "TIME_STOP", "STOP", "BREAKEVEN",
                "MOMENTUM_GATE", "SESSION_GATE", "SYMBOL_EXCLUSION")
    if fingerprint == "GATE_OVERFILTER_ZERO_TRADES":
        return ("STOP", "TARGET", "BREAKEVEN", "PARTIAL", "MFE_TRAILING", "TIME_STOP",
                "MOMENTUM_GATE", "SESSION_GATE", "SYMBOL_EXCLUSION",
                "ENTRY_CONTEXT_GATE", "CANDLE_STRUCTURE_GATE", "TREND_REGIME_GATE",
                "VOLATILITY_GATE", "VOLUME_FLOW_GATE")
    if fingerprint == "RETAINED_BUT_NEGATIVE_EDGE":
        return ("MOMENTUM_GATE", "SESSION_GATE", "SYMBOL_EXCLUSION", "TARGET", "PARTIAL",
                "MFE_TRAILING", "TIME_STOP", "STOP", "BREAKEVEN")
    return AXIS_ORDER


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-plan-root", required=True)
    parser.add_argument("--prior-final-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--generation", type=int, default=7)
    args = parser.parse_args()

    original_root = Path(args.original_plan_root).resolve()
    prior_root = Path(args.prior_final_root).resolve()
    out = Path(args.out).resolve()
    original = read_json(original_root / "plan.json")
    prior_final = read_json(prior_root / "final.json")
    prior_ledger = read_json(prior_root / "search_ledger.json")

    if original.get("state") != "PASS_MULTIMODAL_L090_PLAN":
        raise RuntimeError("ORIGINAL_PLAN_NOT_PASS")
    if prior_final.get("state") != "PASS_MULTIMODAL_L090_REPLAY_COMPLETE":
        raise RuntimeError("PRIOR_FINAL_NOT_PASS")
    if int(prior_final.get("l090_candidate_count") or 0) != 0:
        raise RuntimeError("L090_QUEUE_NOT_EMPTY_USE_L085_PATH")

    original_rows = {str(row["strategy_id"]): row for row in original["rows"]}
    ledger_rows = {str(row["strategy_id"]): row for row in prior_ledger["rows"]}
    final_rows = {str(row["strategy_id"]): row for row in prior_final["rows"]}

    plan_rows: list[dict[str, Any]] = []
    next_ledger: list[dict[str, Any]] = []
    cause_rows: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []

    for strategy_id in sorted(original_rows):
        base = original_rows[strategy_id]
        alias = str(base["strategy_alias"])
        strategy_profile = profile(original_root, alias)
        catalog = strategy_profile.get("candidate_catalog")
        if not isinstance(catalog, dict):
            raise RuntimeError(f"CATALOG_MISSING:{strategy_id}")
        family = strategy_profile.get("family") or "unknown"
        old = ledger_rows[strategy_id]
        final_row = final_rows[strategy_id]
        fingerprint, cause = classify_failure(final_row)
        priority = priority_for(fingerprint)
        priority_rank = {axis: idx for idx, axis in enumerate(priority)}

        tested_ids = set(map(str, old.get("tested_candidate_ids", [])))
        tested_ids.update(map(str, old.get("selected_candidate_ids", [])))
        tested_features = set(map(str, old.get("tested_features", [])))
        axis_counts = {str(k): int(v) for k, v in (old.get("axis_generation_count") or {}).items()}
        for axis in old.get("tested_axes", []) or []:
            axis = str(axis)
            axis_counts[axis] = max(1, axis_counts.get(axis, 0))
        for axis in old.get("selected_axes", []) or []:
            axis = str(axis)
            axis_counts[axis] = min(2, axis_counts.get(axis, 0) + 1)
        for variant in final_row.get("variants", [])[1:]:
            spec = variant.get("candidate_config") or {}
            for feature in (spec.get("gate") or {}).get("required", []) or []:
                tested_features.add(str(feature))

        pool: list[tuple[int, int, str, str, dict[str, Any]]] = []
        seen_features: set[tuple[str, str]] = set()
        for raw in catalog.values():
            for feature in (raw.get("gate") or {}).get("required", []) or []:
                feature = str(feature)
                axis = classify_feature(feature)
                key = (axis, feature)
                if key in seen_features or feature in tested_features or axis_counts.get(axis, 0) >= 1:
                    continue
                seen_features.add(key)
                cid = "SF__" + feature.upper().replace("-", "_").replace(".", "_")
                spec = {
                    "axis": axis,
                    "kind": "GATE",
                    "gate": {
                        "gate_id": cid[4:],
                        "family": family,
                        "description": "cause-aware single-feature semantic-axis probe",
                        "required": [feature],
                        "forbidden": [],
                    },
                }
                pool.append((priority_rank.get(axis, len(priority) + AXIS_ORDER.index(axis)), AXIS_ORDER.index(axis), axis, cid, spec))

        for candidate_id, raw_spec in catalog.items():
            candidate_id = str(candidate_id)
            spec = dict(raw_spec)
            axis = str(spec.get("axis") or "UNKNOWN")
            if spec.get("kind") == "GATE" or candidate_id in tested_ids or axis_counts.get(axis, 0) >= 1:
                continue
            rank = priority_rank.get(axis, len(priority) + (AXIS_ORDER.index(axis) if axis in AXIS_ORDER else 99))
            pool.append((rank, AXIS_ORDER.index(axis) if axis in AXIS_ORDER else 99, axis, candidate_id, spec))

        pool.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
        selected: list[tuple[str, str, dict[str, Any]]] = []
        selected_axes: set[str] = set()
        for _, _, axis, candidate_id, spec in pool:
            if axis in selected_axes:
                continue
            selected.append((candidate_id, axis, spec))
            selected_axes.add(axis)
            if len(selected) == 2:
                break
        if not selected:
            incomplete.append({"strategy_id": strategy_id, "reason": "NO_UNTESTED_CAUSAL_AXIS", "fingerprint": fingerprint})
            continue

        candidate_ids = [row[0] for row in selected]
        candidate_specs = {cid: spec for cid, _, spec in selected}
        selection_rationale = {
            "failure_fingerprint": fingerprint,
            "axis_priority": list(priority),
            "selected_axes": [row[1] for row in selected],
            "why": (
                "Preserve control entries and test untested exit/risk axes after gate over-filtering."
                if fingerprint == "GATE_OVERFILTER_ZERO_TRADES"
                else "Repair the dominant generation-six failure mode with distinct untested bounded axes."
            ),
        }
        plan_rows.append({
            "strategy_id": strategy_id,
            "strategy_alias": alias,
            "candidate_ids": candidate_ids,
            "candidate_specs": candidate_specs,
            "generation": args.generation,
            "failure_fingerprint": fingerprint,
            "cause_summary": cause,
            "selection_rationale": selection_rationale,
            "evidence_lanes": [
                "IMMUTABLE_F1_F2_F3", "GENERATION6_FILTERED_REPLAY", "SEARCH_LEDGER",
                "DETERMINISTIC_CAUSE_ANALYSIS", "GROQ_RED_TEAM", "WORKERS_AI_GUARD",
            ],
            "single_axis_reason": "Each candidate modifies one untested causal axis selected from the prior failure fingerprint.",
            "falsification_test": "Must beat NO_CHANGE under parity, retention, L090 loss, economics, DD and positive-window gates.",
            "priority": int(base.get("priority") or 999),
            "promotion_authority": False,
        })

        tested_axes = set(map(str, old.get("tested_axes", [])))
        tested_axes.update(map(str, old.get("selected_axes", [])))
        available_axes = {axis for _, _, axis, _, _ in pool}
        next_ledger.append({
            "strategy_id": strategy_id,
            "incumbent_candidate_sha": stable_sha(final_row["variants"][0]["candidate_config"]),
            "tested_candidate_ids": sorted(tested_ids),
            "tested_features": sorted(tested_features),
            "tested_axes": sorted(tested_axes),
            "axis_generation_count": axis_counts,
            "selected_candidate_ids": candidate_ids,
            "selected_axes": [row[1] for row in selected],
            "selected_features": [row[2].get("gate", {}).get("required", [None])[0] for row in selected],
            "remaining_axes": sorted(available_axes - selected_axes, key=lambda a: priority_rank.get(a, 999)),
            "next_axis": next((a for a in priority if a in available_axes - selected_axes), "WAIT_NEW_EVIDENCE"),
            "failure_fingerprint": fingerprint,
            "cause_summary_sha256": stable_sha(cause),
            "prior_final_sha256": stable_sha(prior_final),
            "prior_ledger_sha256": stable_sha(prior_ledger),
            "new_data_epoch": False,
            "w1_epoch": False,
            "sealed_epoch": False,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        })
        cause_rows.append({"strategy_id": strategy_id, **cause, "selected_candidate_ids": candidate_ids, "selected_axes": [row[1] for row in selected]})

    if incomplete:
        raise RuntimeError("CAUSE_AWARE_POOL_INCOMPLETE:" + json.dumps(incomplete, sort_keys=True))

    plan_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    next_ledger.sort(key=lambda row: row["strategy_id"])
    cause_rows.sort(key=lambda row: row["strategy_id"])
    fingerprints = Counter(row["fingerprint"] for row in cause_rows)

    plan = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_CAUSE_AWARE_AXIS_ROTATION_PLAN",
        "capability_marker": "CAUSE_AWARE_DISTINCT_AXIS_ROTATION_L090",
        "strategy_count": len(plan_rows),
        "candidate_count": sum(len(row["candidate_ids"]) for row in plan_rows),
        "generation": args.generation,
        "rows": plan_rows,
        "prior_final_sha256": stable_sha(prior_final),
        "same_strategy_axis_data_generation_limit": 2,
        "private_code_sent": False,
        "account_data_sent": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "promotion_authority": False,
        "next": "AI_PRE_REVIEW_THEN_ISOLATED_REPLAY_L090",
    }
    ledger = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_SEARCH_LEDGER",
        "strategy_count": len(next_ledger),
        "axis_order": list(AXIS_ORDER),
        "rows": next_ledger,
        "duplicate_strategy_axis_data_runs": 0,
        "promotion_authority": False,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    cause_analysis = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_GENERATION6_FAILURE_CAUSE_ANALYSIS",
        "strategy_count": len(cause_rows),
        "candidate_count_observed": sum(row["candidate_count"] for row in cause_rows),
        "fingerprint_counts": dict(sorted(fingerprints.items())),
        "rows": cause_rows,
        "global_findings": {
            "dominant_failure": "ENTRY_GATES_OVER_FILTERED_TO_ZERO_TRADES",
            "zero_trade_candidates": sum(row["zero_trade_candidate_count"] for row in cause_rows),
            "nonzero_candidates": sum(row["nonzero_candidate_count"] for row in cause_rows),
            "action": "ROTATE_ZERO_TRADE_STRATEGIES_TO_UNTESTED_EXIT_RISK_AXES_BEFORE_MORE_ENTRY_GATES",
        },
        "promotion_authority": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    atomic_json(out / "plan.json", plan)
    atomic_json(out / "search_ledger.json", ledger)
    atomic_json(out / "cause_analysis.json", cause_analysis)
    print(json.dumps({"state": plan["state"], "strategies": len(plan_rows), "candidates": plan["candidate_count"], "fingerprints": cause_analysis["fingerprint_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
