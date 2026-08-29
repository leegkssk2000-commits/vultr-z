#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.prep import rr_exit_robust_geometry_v1 as v1

SCHEMA = "zel.rr_exit.robust_geometry.v2"
MIN_DEV_T = 12
MIN_VAL_T = 6
SPLIT_POLICY = "LATEST_CHRONOLOGICAL_CUTOFF_PRESERVING_VAL_GE6_AND_CLEAN_DEV_GE12"


def temporal_split(
    base_rows: list[dict[str, Any]],
    path_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    """Outcome-blind chronological cutoff with purge.

    Cutoff selection may inspect signal/exit timestamps only. It never inspects PnL,
    win/loss sign, MFE/MAE, or candidate economics. Among cutoffs that preserve at
    least MIN_VAL_T validation rows and MIN_DEV_T fully completed development rows,
    select the latest chronological cutoff. Trades opened before cutoff but closed
    at/after cutoff are purged from development.
    """
    if len(base_rows) != len(path_rows):
        raise RuntimeError("RR_PATH_ROW_PARITY")
    if len(base_rows) < MIN_DEV_T + MIN_VAL_T:
        raise RuntimeError(f"RR_TEMPORAL_SPLIT_PARENT_SUPPORT_INSUFFICIENT:T={len(base_rows)}")

    best_diag: tuple[int, int, int] | None = None
    for i in range(len(base_rows) - MIN_VAL_T, MIN_DEV_T - 1, -1):
        cutoff = int(base_rows[i]["signal_ts"])
        dev_base: list[dict[str, Any]] = []
        dev_paths: list[dict[str, Any]] = []
        val_base: list[dict[str, Any]] = []
        purged: list[dict[str, Any]] = []

        for row, path in zip(base_rows, path_rows):
            signal_ts = int(row.get("signal_ts") or 0)
            exit_ts = int(row.get("exit_ts") or 0)
            if signal_ts >= cutoff:
                val_base.append(row)
            elif exit_ts < cutoff:
                dev_base.append(row)
                dev_paths.append(path)
            else:
                purged.append(row)

        diag = (len(dev_base), len(val_base), len(purged))
        if best_diag is None or diag[0] > best_diag[0]:
            best_diag = diag
        if len(val_base) < MIN_VAL_T or len(dev_base) < MIN_DEV_T:
            continue
        if max(int(x.get("exit_ts") or 0) for x in dev_base) >= min(int(x.get("signal_ts") or 0) for x in val_base):
            raise RuntimeError("RR_TEMPORAL_SPLIT_LEAKAGE")
        return dev_base, dev_paths, val_base, purged, cutoff

    b = best_diag or (0, 0, 0)
    raise RuntimeError(f"RR_TEMPORAL_SPLIT_SUPPORT_INSUFFICIENT:BEST_DEV={b[0]}:BEST_VAL={b[1]}:PURGED={b[2]}")


def run(trend_path: Path, a4dir: Path, breakdir: Path, out: Path) -> dict[str, Any]:
    old_split = v1.temporal_split
    try:
        v1.temporal_split = temporal_split
        result = v1.run(trend_path, a4dir, breakdir, out)
    finally:
        v1.temporal_split = old_split

    result["schema_version"] = SCHEMA
    result["search_method"] = "OUTCOME_BLIND_LATEST_PURGED_TEMPORAL_CUTOFF_THEN_DEV_EMPIRICAL_QUANTILE_GRID_SINGLE_CANDIDATE_VALIDATION"
    result["split_policy"] = SPLIT_POLICY
    result["split_min_development_T"] = MIN_DEV_T
    result["split_min_validation_T"] = MIN_VAL_T
    result["cutoff_selection_uses_pnl"] = False
    result["cutoff_selection_uses_win_loss"] = False
    result["cutoff_selection_uses_mfe_mae"] = False
    result["cutoff_selection_uses_candidate_economics"] = False
    result["cutoff_selection_uses_exit_completion_chronology_only"] = True
    result["validation_used_to_select_candidate"] = False
    result["same_validation_reuse_for_alternate_rr_candidate_forbidden"] = True
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    rows = [{"signal_ts": 2 * i + 1, "exit_ts": 2 * i + 2} for i in range(20)]
    rows[12]["exit_ts"] = 40
    paths = [dict(x) for x in rows]
    dev, _, val, purged, cutoff = temporal_split(rows, paths)
    assert len(dev) == 13
    assert len(val) == 6
    assert len(purged) == 1
    assert cutoff == 29
    assert max(int(x["exit_ts"]) for x in dev) < min(int(x["signal_ts"]) for x in val)
    print("PASS_RR_EXIT_ROBUST_GEOMETRY_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trend70-source", type=Path)
    ap.add_argument("--a4-source-dir", type=Path)
    ap.add_argument("--break-source-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/rr_exit_robust_geometry_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if None in (a.trend70_source, a.a4_source_dir, a.break_source_dir):
        raise SystemExit("sources required")
    r = run(a.trend70_source, a.a4_source_dir, a.break_source_dir, a.out)
    print(json.dumps({
        "state": r["state"],
        "T": r["parent_T"],
        "dev_T": r["development_T"],
        "val_T": r["validation_T"],
        "purged_T": r["purged_overlap_T"],
        "temporal_nonoverlap": r["temporal_nonoverlap"],
        "selected": {"tp_r": r["selected"]["tp_r"], "sl_r": r["selected"]["sl_r"]},
        "validation": r["validation"],
        "robust": r["robust_candidate_ready"],
        "next": r["next"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
