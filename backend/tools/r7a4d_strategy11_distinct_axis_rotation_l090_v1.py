from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_DISTINCT_AXIS_ROTATION_L090_V1"
AXIS_ORDER = (
    "ENTRY_CONTEXT_GATE",
    "CANDLE_STRUCTURE_GATE",
    "TREND_REGIME_GATE",
    "VOLATILITY_GATE",
    "VOLUME_FLOW_GATE",
    "MOMENTUM_GATE",
    "SESSION_GATE",
    "SYMBOL_EXCLUSION",
    "STOP",
    "TARGET",
    "BREAKEVEN",
    "PARTIAL",
    "MFE_TRAILING",
    "TIME_STOP",
)


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def find_profile(root: Path, alias: str) -> Path:
    matches = list(root.rglob(f"{alias}.json"))
    matches = [path for path in matches if "profiles" in path.parts]
    if len(matches) != 1:
        raise RuntimeError(f"PROFILE_RESOLUTION_FAILED:{alias}:{len(matches)}")
    return matches[0]


def axis_rank(axis: str) -> int:
    try:
        return AXIS_ORDER.index(axis)
    except ValueError:
        return len(AXIS_ORDER) + 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-plan-root", required=True)
    parser.add_argument("--prior-final", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    plan_root = Path(args.prior_plan_root).resolve()
    prior_plan = strict_json(plan_root / "plan.json")
    prior_final = strict_json(Path(args.prior_final).resolve())
    out = Path(args.out).resolve()

    if prior_plan.get("state") != "PASS_MULTIMODAL_L090_PLAN":
        raise RuntimeError("PRIOR_PLAN_NOT_PASS")
    if prior_final.get("state") != "PASS_MULTIMODAL_L090_REPLAY_COMPLETE":
        raise RuntimeError("PRIOR_REPLAY_NOT_PASS")
    if int(prior_final.get("strategy_count") or 0) != 22:
        raise RuntimeError("PRIOR_STRATEGY_COUNT_MISMATCH")

    final_by_strategy = {str(row["strategy_id"]): row for row in prior_final["rows"]}
    next_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []

    for prior_row in prior_plan["rows"]:
        sid = str(prior_row["strategy_id"])
        alias = str(prior_row["strategy_alias"])
        profile = strict_json(find_profile(plan_root, alias))
        catalog = profile.get("candidate_catalog")
        if not isinstance(catalog, Mapping):
            raise RuntimeError(f"CATALOG_MISSING:{sid}")

        replay_row = final_by_strategy[sid]
        tested_ids = [str(value) for value in replay_row.get("tested_candidate_ids", [])]
        tested_axes = {
            str(prior_row.get("candidate_specs", {}).get(cid, {}).get("axis"))
            for cid in tested_ids
            if prior_row.get("candidate_specs", {}).get(cid)
        }
        tested_axes.discard("None")

        remaining = []
        for cid, raw_spec in catalog.items():
            cid_s = str(cid)
            spec = dict(raw_spec)
            axis = str(spec.get("axis") or "UNKNOWN")
            if cid_s in tested_ids or axis in tested_axes:
                continue
            remaining.append((axis_rank(axis), axis, cid_s, spec))
        remaining.sort(key=lambda row: (row[0], row[1], row[2]))

        selected: list[tuple[str, str, dict[str, Any]]] = []
        selected_axes: set[str] = set()
        for _, axis, cid, spec in remaining:
            if axis in selected_axes:
                continue
            selected.append((cid, axis, spec))
            selected_axes.add(axis)
            if len(selected) == 2:
                break
        if len(selected) < 2:
            for _, axis, cid, spec in remaining:
                if any(cid == existing[0] for existing in selected):
                    continue
                selected.append((cid, axis, spec))
                if len(selected) == 2:
                    break
        if len(selected) != 2:
            raise RuntimeError(f"DISTINCT_AXIS_CANDIDATES_LT_2:{sid}:{len(selected)}")

        candidate_ids = [row[0] for row in selected]
        candidate_specs = {cid: spec for cid, _, spec in selected}
        next_rows.append({
            "strategy_id": sid,
            "strategy_alias": alias,
            "candidate_ids": candidate_ids,
            "candidate_specs": candidate_specs,
            "evidence_lanes": [
                "PRIOR_MULTIMODAL_DASHBOARD",
                "PRIOR_GEMINI_DIRECT_VIDEO",
                "PRIOR_RED_TEAM",
                "PRIOR_ISOLATED_REPLAY",
                "DISTINCT_AXIS_ROTATION",
            ],
            "single_axis_reason": "Prior generation produced no L090 candidate; rotate to two previously untested causal axes.",
            "expected_metric_effect": {},
            "falsification_test": "Candidate must dominate NO_CHANGE under parity, retention, loss, DD, economic and positive-window gates.",
            "priority": int(prior_row.get("priority") or 999),
            "generation": 2,
            "promotion_authority": False,
        })
        ledger_rows.append({
            "strategy_id": sid,
            "incumbent_candidate_sha": stable_sha(replay_row["variants"][0]["candidate_config"]),
            "tested_candidate_ids": tested_ids,
            "tested_axes": sorted(tested_axes),
            "axis_generation_count": {axis: 1 for axis in sorted(tested_axes)},
            "selected_candidate_ids": candidate_ids,
            "selected_axes": [row[1] for row in selected],
            "remaining_axes": sorted({axis for _, axis, _, _ in remaining} - selected_axes, key=axis_rank),
            "next_axis": min((axis for _, axis, _, _ in remaining if axis not in selected_axes), key=axis_rank, default="WAIT_NEW_EVIDENCE"),
            "prior_plan_sha256": stable_sha(prior_plan),
            "prior_replay_sha256": stable_sha(replay_row),
            "new_data_epoch": False,
            "w1_epoch": False,
            "sealed_epoch": False,
            "promotion_authority": False,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
        })

    next_rows.sort(key=lambda row: (row["priority"], row["strategy_id"]))
    ledger_rows.sort(key=lambda row: row["strategy_id"])
    plan = {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": "DISTINCT_AXIS_ROTATION_L090",
        "state": "PASS_DISTINCT_AXIS_ROTATION_PLAN",
        "strategy_count": len(next_rows),
        "candidate_count": sum(len(row["candidate_ids"]) for row in next_rows),
        "generation": 2,
        "rows": next_rows,
        "prior_plan_sha256": stable_sha(prior_plan),
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
        "next": "ISOLATED_REPLAY_DISTINCT_AXES_L090",
    }
    ledger = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_SEARCH_LEDGER",
        "strategy_count": len(ledger_rows),
        "axis_order": list(AXIS_ORDER),
        "rows": ledger_rows,
        "duplicate_strategy_axis_data_runs": 0,
        "promotion_authority": False,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    atomic_json(out / "plan.json", plan)
    atomic_json(out / "search_ledger.json", ledger)
    print(json.dumps({"state": plan["state"], "strategies": len(next_rows), "candidates": plan["candidate_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
