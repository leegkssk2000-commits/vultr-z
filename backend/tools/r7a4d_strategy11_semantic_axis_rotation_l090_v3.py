from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

VERSION = "R7A4D_STRATEGY11_SEMANTIC_AXIS_ROTATION_L090_V3"
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


def axis_rank(axis: str) -> int:
    try:
        return AXIS_ORDER.index(axis)
    except ValueError:
        return len(AXIS_ORDER) + 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-plan-root", required=True)
    parser.add_argument("--prior-final-root", required=True)
    parser.add_argument("--out", required=True)
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
    incomplete: list[dict[str, Any]] = []

    for strategy_id in sorted(original_rows):
        base = original_rows[strategy_id]
        alias = str(base["strategy_alias"])
        strategy_profile = profile(original_root, alias)
        catalog = strategy_profile.get("candidate_catalog")
        if not isinstance(catalog, dict):
            raise RuntimeError(f"CATALOG_MISSING:{strategy_id}")
        family = strategy_profile.get("family") or next(
            (
                spec.get("gate", {}).get("family")
                for spec in catalog.values()
                if spec.get("kind") == "GATE"
            ),
            "unknown",
        )

        old = ledger_rows[strategy_id]
        tested_ids = set(map(str, old.get("tested_candidate_ids", [])))
        tested_ids.update(map(str, old.get("selected_candidate_ids", [])))
        axis_counts = {
            str(axis): int(count)
            for axis, count in (old.get("axis_generation_count") or {}).items()
            if str(axis) != "ENTRY_CONTEXT_GATE"
        }
        tested_features: set[str] = set()
        for candidate_id in tested_ids:
            spec = catalog.get(candidate_id) or {}
            for feature in spec.get("gate", {}).get("required", []) or []:
                feature = str(feature)
                tested_features.add(feature)
                semantic_axis = classify_feature(feature)
                axis_counts[semantic_axis] = min(2, axis_counts.get(semantic_axis, 0) + 1)

        pool: list[tuple[int, str, str, dict[str, Any]]] = []
        seen_features: set[tuple[str, str]] = set()
        for spec in catalog.values():
            for feature in spec.get("gate", {}).get("required", []) or []:
                feature = str(feature)
                semantic_axis = classify_feature(feature)
                key = (semantic_axis, feature)
                if key in seen_features or feature in tested_features or axis_counts.get(semantic_axis, 0) >= 2:
                    continue
                seen_features.add(key)
                candidate_id = "SF__" + feature.upper().replace("-", "_").replace(".", "_")
                candidate_spec = {
                    "axis": semantic_axis,
                    "kind": "GATE",
                    "gate": {
                        "gate_id": candidate_id[4:],
                        "family": family,
                        "description": "single-feature semantic-axis probe",
                        "required": [feature],
                        "forbidden": [],
                    },
                }
                pool.append((axis_rank(semantic_axis), semantic_axis, candidate_id, candidate_spec))

        for candidate_id, raw_spec in catalog.items():
            candidate_id = str(candidate_id)
            spec = dict(raw_spec)
            axis = str(spec.get("axis") or "UNKNOWN")
            if spec.get("kind") == "GATE" or candidate_id in tested_ids or axis_counts.get(axis, 0) >= 2:
                continue
            pool.append((axis_rank(axis), axis, candidate_id, spec))

        pool.sort(key=lambda row: (row[0], row[1], row[2]))
        selected: list[tuple[str, str, dict[str, Any]]] = []
        selected_axes: set[str] = set()
        for _, axis, candidate_id, spec in pool:
            if axis in selected_axes:
                continue
            selected.append((candidate_id, axis, spec))
            selected_axes.add(axis)
            if len(selected) == 2:
                break
        if len(selected) < 2:
            incomplete.append({
                "strategy_id": strategy_id,
                "reason": "LT2_UNTESTED_SEMANTIC_AXES",
                "available": [(axis, candidate_id) for _, axis, candidate_id, _ in pool],
            })
            continue

        candidate_ids = [row[0] for row in selected]
        candidate_specs = {candidate_id: spec for candidate_id, _, spec in selected}
        plan_rows.append({
            "strategy_id": strategy_id,
            "strategy_alias": alias,
            "candidate_ids": candidate_ids,
            "candidate_specs": candidate_specs,
            "generation": 4,
            "evidence_lanes": [
                "PRIOR_MULTIMODAL_DASHBOARD", "PRIOR_GEMINI_DIRECT_VIDEO", "PRIOR_RED_TEAM",
                "GENERATION1_REPLAY", "GENERATION2_REPLAY", "GENERATION3_REPLAY",
                "SEMANTIC_SINGLE_FEATURE_ROTATION",
            ],
            "single_axis_reason": (
                "Prior catalog collapsed heterogeneous indicator families into ENTRY_CONTEXT_GATE; "
                "use one already-supported feature per semantic causal axis."
            ),
            "falsification_test": (
                "Candidate must dominate NO_CHANGE under parity, retention, loss, DD, economics "
                "and positive-window gates."
            ),
            "priority": int(base.get("priority") or 999),
            "promotion_authority": False,
        })

        tested_axes = set(map(str, old.get("tested_axes", [])))
        tested_axes.update(map(str, old.get("selected_axes", [])))
        next_ledger.append({
            "strategy_id": strategy_id,
            "incumbent_candidate_sha": stable_sha(final_rows[strategy_id]["variants"][0]["candidate_config"]),
            "tested_candidate_ids": sorted(tested_ids),
            "tested_features": sorted(tested_features),
            "tested_axes": sorted(tested_axes),
            "axis_generation_count": axis_counts,
            "selected_candidate_ids": candidate_ids,
            "selected_axes": [row[1] for row in selected],
            "selected_features": [
                row[2].get("gate", {}).get("required", [None])[0]
                for row in selected
            ],
            "remaining_axes": sorted(
                {axis for _, axis, _, _ in pool} - selected_axes,
                key=axis_rank,
            ),
            "next_axis": min(
                (axis for _, axis, _, _ in pool if axis not in selected_axes),
                key=axis_rank,
                default="WAIT_NEW_EVIDENCE",
            ),
            "prior_final_sha256": stable_sha(prior_final),
            "prior_ledger_sha256": stable_sha(prior_ledger),
            "new_data_epoch": False,
            "w1_epoch": False,
            "sealed_epoch": False,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        })

    if incomplete:
        raise RuntimeError("SEMANTIC_POOL_INCOMPLETE:" + json.dumps(incomplete, sort_keys=True))

    plan_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    next_ledger.sort(key=lambda row: row["strategy_id"])
    plan = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_SEMANTIC_AXIS_ROTATION_PLAN",
        "capability_marker": "SEMANTIC_DISTINCT_AXIS_ROTATION_L090",
        "strategy_count": len(plan_rows),
        "candidate_count": sum(len(row["candidate_ids"]) for row in plan_rows),
        "generation": 4,
        "rows": plan_rows,
        "prior_final_sha256": stable_sha(prior_final),
        "single_feature_only": True,
        "same_strategy_axis_data_generation_limit": 2,
        "private_code_sent": False,
        "account_data_sent": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
        "promotion_authority": False,
        "next": "ISOLATED_REPLAY_SEMANTIC_DISTINCT_AXES_L090",
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
    atomic_json(out / "plan.json", plan)
    atomic_json(out / "search_ledger.json", ledger)
    print(json.dumps({
        "state": plan["state"],
        "strategies": len(plan_rows),
        "candidates": plan["candidate_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
