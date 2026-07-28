from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_DISTINCT_AXIS_ROTATION_L090_V2"
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


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
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


def axis_rank(axis: str) -> int:
    try:
        return AXIS_ORDER.index(axis)
    except ValueError:
        return len(AXIS_ORDER) + 1


def profile(root: Path, alias: str) -> dict[str, Any]:
    matches = [p for p in root.rglob(f"{alias}.json") if "profiles" in p.parts]
    if len(matches) != 1:
        raise RuntimeError(f"PROFILE_RESOLUTION_FAILED:{alias}:{len(matches)}")
    return read_json(matches[0])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--original-plan-root", required=True)
    ap.add_argument("--prior-final-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    original_root = Path(args.original_plan_root).resolve()
    prior_root = Path(args.prior_final_root).resolve()
    out = Path(args.out).resolve()
    original = read_json(original_root / "plan.json")
    prior_final = read_json(prior_root / "final.json")
    prior_plan = read_json(prior_root / "generation2_plan.json")
    prior_ledger = read_json(prior_root / "search_ledger.json")

    if original.get("state") != "PASS_MULTIMODAL_L090_PLAN":
        raise RuntimeError("ORIGINAL_PLAN_NOT_PASS")
    if prior_final.get("state") != "PASS_MULTIMODAL_L090_REPLAY_COMPLETE":
        raise RuntimeError("PRIOR_FINAL_NOT_PASS")
    if int(prior_final.get("l090_candidate_count") or 0) != 0:
        raise RuntimeError("L090_QUEUE_NOT_EMPTY_USE_L085_PATH")

    original_rows = {str(r["strategy_id"]): r for r in original["rows"]}
    generation2_rows = {str(r["strategy_id"]): r for r in prior_plan["rows"]}
    ledger_rows = {str(r["strategy_id"]): r for r in prior_ledger["rows"]}
    final_rows = {str(r["strategy_id"]): r for r in prior_final["rows"]}
    plan_rows: list[dict[str, Any]] = []
    next_ledger: list[dict[str, Any]] = []

    for sid in sorted(original_rows):
        base = original_rows[sid]
        alias = str(base["strategy_alias"])
        catalog = profile(original_root, alias).get("candidate_catalog")
        if not isinstance(catalog, Mapping):
            raise RuntimeError(f"CATALOG_MISSING:{sid}")
        old = ledger_rows[sid]
        tested_ids = set(map(str, old.get("tested_candidate_ids", [])))
        tested_ids.update(map(str, old.get("selected_candidate_ids", [])))
        tested_axes = set(map(str, old.get("tested_axes", [])))
        tested_axes.update(map(str, old.get("selected_axes", [])))

        remaining: list[tuple[int, str, str, dict[str, Any]]] = []
        for cid, raw in catalog.items():
            cid_s = str(cid)
            spec = dict(raw)
            axis = str(spec.get("axis") or "UNKNOWN")
            if cid_s in tested_ids or axis in tested_axes:
                continue
            remaining.append((axis_rank(axis), axis, cid_s, spec))
        remaining.sort(key=lambda x: (x[0], x[1], x[2]))

        selected: list[tuple[str, str, dict[str, Any]]] = []
        axes: set[str] = set()
        for _, axis, cid, spec in remaining:
            if axis in axes:
                continue
            selected.append((cid, axis, spec)); axes.add(axis)
            if len(selected) == 2:
                break
        if len(selected) < 2:
            for _, axis, cid, spec in remaining:
                if any(cid == row[0] for row in selected):
                    continue
                selected.append((cid, axis, spec))
                if len(selected) == 2:
                    break
        if len(selected) != 2:
            raise RuntimeError(f"REMAINING_CANDIDATES_LT_2:{sid}:{len(selected)}")

        ids = [x[0] for x in selected]
        specs = {cid: spec for cid, _, spec in selected}
        plan_rows.append({
            "strategy_id": sid, "strategy_alias": alias, "candidate_ids": ids,
            "candidate_specs": specs, "generation": 3,
            "evidence_lanes": ["PRIOR_MULTIMODAL_DASHBOARD", "PRIOR_GEMINI_DIRECT_VIDEO",
                               "PRIOR_RED_TEAM", "GENERATION1_REPLAY", "GENERATION2_REPLAY",
                               "DISTINCT_AXIS_ROTATION"],
            "single_axis_reason": "Two prior bounded generations produced no L090 candidate; rotate to the next untested axes.",
            "falsification_test": "Candidate must dominate NO_CHANGE under parity, retention, loss, DD, economics and positive-window gates.",
            "priority": int(base.get("priority") or 999), "promotion_authority": False,
        })
        counts = dict(old.get("axis_generation_count") or {})
        for axis in old.get("selected_axes", []):
            counts[str(axis)] = counts.get(str(axis), 0) + 1
        next_ledger.append({
            "strategy_id": sid,
            "incumbent_candidate_sha": stable_sha(final_rows[sid]["variants"][0]["candidate_config"]),
            "tested_candidate_ids": sorted(tested_ids), "tested_axes": sorted(tested_axes),
            "axis_generation_count": counts, "selected_candidate_ids": ids,
            "selected_axes": [x[1] for x in selected],
            "remaining_axes": sorted({a for _, a, _, _ in remaining} - axes, key=axis_rank),
            "next_axis": min((a for _, a, _, _ in remaining if a not in axes), key=axis_rank, default="WAIT_NEW_EVIDENCE"),
            "prior_final_sha256": stable_sha(prior_final), "prior_ledger_sha256": stable_sha(prior_ledger),
            "new_data_epoch": False, "w1_epoch": False, "sealed_epoch": False,
            "promotion_authority": False, "execution_allowed": False, "order_authority": "BLOCKED",
        })

    plan_rows.sort(key=lambda r: (r["priority"], r["strategy_id"]))
    next_ledger.sort(key=lambda r: r["strategy_id"])
    plan = {
        "schema_version": "1.0", "version": VERSION, "state": "PASS_DISTINCT_AXIS_ROTATION_PLAN",
        "capability_marker": "DISTINCT_AXIS_ROTATION_L090", "strategy_count": len(plan_rows),
        "candidate_count": sum(len(r["candidate_ids"]) for r in plan_rows), "generation": 3,
        "rows": plan_rows, "prior_final_sha256": stable_sha(prior_final),
        "same_strategy_axis_data_generation_limit": 2, "private_code_sent": False,
        "account_data_sent": False, "canonical_mutated": False, "registry_mutated": False,
        "protected_mutations": 0, "execution_allowed": False, "order_authority": "BLOCKED",
        "promotion_authority": False, "next": "ISOLATED_REPLAY_DISTINCT_AXES_L090",
    }
    ledger = {
        "schema_version": "1.0", "version": VERSION, "state": "PASS_SEARCH_LEDGER",
        "strategy_count": len(next_ledger), "axis_order": list(AXIS_ORDER), "rows": next_ledger,
        "duplicate_strategy_axis_data_runs": 0, "promotion_authority": False,
        "execution_allowed": False, "order_authority": "BLOCKED",
    }
    atomic_json(out / "plan.json", plan)
    atomic_json(out / "search_ledger.json", ledger)
    print(json.dumps({"state": plan["state"], "strategies": len(plan_rows), "candidates": plan["candidate_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
