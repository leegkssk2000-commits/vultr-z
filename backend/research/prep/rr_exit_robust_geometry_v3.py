#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.prep import rr_exit_robust_geometry_v1 as v1

SCHEMA = "zel.rr_exit.robust_geometry.v3"
MIN_DEV_T = 12
MIN_VAL_T = 6
SPLIT_POLICY = "LATEST_NONOVERLAPPING_EPISODE_BOUNDARY_PRESERVING_DEV_GE12_VAL_GE6"


def overlap_episodes(rows: list[dict[str, Any]]) -> list[list[int]]:
    """Partition chronological trades into connected overlap episodes.

    Only signal_ts/exit_ts are used. A new episode starts strictly after every
    trade in the prior episode has exited. No PnL or path economics participate.
    """
    if not rows:
        return []
    episodes: list[list[int]] = []
    current: list[int] = []
    episode_end = -1
    for i, row in enumerate(rows):
        signal_ts = int(row.get("signal_ts") or 0)
        exit_ts = int(row.get("exit_ts") or 0)
        if exit_ts <= signal_ts:
            raise RuntimeError(f"RR_INVALID_TRADE_INTERVAL:{i}:{signal_ts}:{exit_ts}")
        if current and signal_ts > episode_end:
            episodes.append(current)
            current = []
            episode_end = -1
        current.append(i)
        episode_end = max(episode_end, exit_ts)
    if current:
        episodes.append(current)
    return episodes


def temporal_split(
    base_rows: list[dict[str, Any]],
    path_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    if len(base_rows) != len(path_rows):
        raise RuntimeError("RR_PATH_ROW_PARITY")
    if len(base_rows) < MIN_DEV_T + MIN_VAL_T:
        raise RuntimeError(f"RR_EPISODE_PARENT_SUPPORT_INSUFFICIENT:T={len(base_rows)}")

    episodes = overlap_episodes(base_rows)
    sizes = [len(x) for x in episodes]
    candidates: list[tuple[int, int, int]] = []
    running = 0
    for episode_idx in range(len(episodes) - 1):
        running += len(episodes[episode_idx])
        dev_t = running
        val_t = len(base_rows) - running
        if dev_t >= MIN_DEV_T and val_t >= MIN_VAL_T:
            candidates.append((episode_idx + 1, dev_t, val_t))

    if not candidates:
        raise RuntimeError(
            "RR_EPISODE_SPLIT_SUPPORT_INSUFFICIENT:"
            f"EPISODES={sizes}:TOTAL={len(base_rows)}:MIN_DEV={MIN_DEV_T}:MIN_VAL={MIN_VAL_T}"
        )

    boundary_episode, dev_t, _ = candidates[-1]
    cutoff_index = episodes[boundary_episode][0]
    cutoff = int(base_rows[cutoff_index]["signal_ts"])
    dev_base = [dict(x) for x in base_rows[:dev_t]]
    dev_paths = [dict(x) for x in path_rows[:dev_t]]
    val_base = [dict(x) for x in base_rows[dev_t:]]
    purged: list[dict[str, Any]] = []

    max_dev_exit = max(int(x.get("exit_ts") or 0) for x in dev_base)
    min_val_signal = min(int(x.get("signal_ts") or 0) for x in val_base)
    if max_dev_exit >= min_val_signal:
        raise RuntimeError(f"RR_EPISODE_BOUNDARY_LEAKAGE:{max_dev_exit}>={min_val_signal}")
    return dev_base, dev_paths, val_base, purged, cutoff


def run(trend_path: Path, a4dir: Path, breakdir: Path, out: Path) -> dict[str, Any]:
    old_split = v1.temporal_split
    try:
        v1.temporal_split = temporal_split
        result = v1.run(trend_path, a4dir, breakdir, out)
    finally:
        v1.temporal_split = old_split

    # Reconstruct episode diagnostics from the same frozen Broad parent without
    # allowing them to influence candidate selection.
    trend = v1.rr.read(trend_path)
    lanes = v1.rr.latest_sets(trend, a4dir, breakdir)
    broad = next(x for x in lanes if x["lane"] == "trend_rider_broad")
    base_rows = sorted(
        [dict(x) for x in broad["rows"]],
        key=lambda x: (int(x["signal_ts"]), str(x["symbol"]), str(x["side"])),
    )
    eps = overlap_episodes(base_rows)

    result["schema_version"] = SCHEMA
    result["search_method"] = "OUTCOME_BLIND_OVERLAP_EPISODE_BOUNDARY_THEN_DEV_EMPIRICAL_QUANTILE_GRID_SINGLE_CANDIDATE_VALIDATION"
    result["split_policy"] = SPLIT_POLICY
    result["split_min_development_T"] = MIN_DEV_T
    result["split_min_validation_T"] = MIN_VAL_T
    result["overlap_episode_count"] = len(eps)
    result["overlap_episode_sizes"] = [len(x) for x in eps]
    result["purged_overlap_T"] = 0
    result["boundary_selection_uses_pnl"] = False
    result["boundary_selection_uses_win_loss"] = False
    result["boundary_selection_uses_mfe_mae"] = False
    result["boundary_selection_uses_candidate_economics"] = False
    result["boundary_selection_uses_signal_exit_chronology_only"] = True
    result["validation_used_to_select_candidate"] = False
    result["same_validation_reuse_for_alternate_rr_candidate_forbidden"] = True
    result.pop("receipt_sha256", None)
    result["receipt_sha256"] = v1.stable(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    # Episodes: 4, 8, 6, 6 -> latest valid boundary gives dev=18,val=6.
    rows: list[dict[str, Any]] = []
    t = 0
    for size in (4, 8, 6, 6):
        episode_start = t + 10
        episode_exit = episode_start + 100
        for j in range(size):
            rows.append({"signal_ts": episode_start + j, "exit_ts": episode_exit - j})
        t = episode_exit + 10
    paths = [dict(x) for x in rows]
    eps = overlap_episodes(rows)
    assert [len(x) for x in eps] == [4, 8, 6, 6]
    dev, _, val, purged, cutoff = temporal_split(rows, paths)
    assert len(dev) == 18 and len(val) == 6 and len(purged) == 0
    assert max(int(x["exit_ts"]) for x in dev) < min(int(x["signal_ts"]) for x in val)
    assert cutoff == int(val[0]["signal_ts"])
    print("PASS_RR_EXIT_ROBUST_GEOMETRY_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trend70-source", type=Path)
    ap.add_argument("--a4-source-dir", type=Path)
    ap.add_argument("--break-source-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/rr_exit_robust_geometry_v3.json"))
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
        "episodes": r["overlap_episode_sizes"],
        "dev_T": r["development_T"],
        "val_T": r["validation_T"],
        "purged_T": r["purged_overlap_T"],
        "selected": {"tp_r": r["selected"]["tp_r"], "sl_r": r["selected"]["sl_r"]},
        "plateau": r["plateau"],
        "validation": r["validation"],
        "robust": r["robust_candidate_ready"],
        "next": r["next"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
