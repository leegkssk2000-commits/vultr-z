from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_path_candidate_replay_v1 as core

VERSION = "R7A4D_STRATEGY11_PATH_CANDIDATE_REPLAY_V1_1"


def run(args: argparse.Namespace) -> dict[str, Any]:
    result = core.run(args)
    plan = core.read_json(args.plan)
    generations = {
        (str(row.get("strategy_id") or ""), str(row.get("candidate_id") or "")): int(row.get("generation") or 1)
        for row in plan.get("accepted") or []
    }
    for row in result["rows"]:
        strategy_id = str(row["strategy_id"])
        candidate_ids = list(row.get("tested_candidate_ids") or [])
        if len(candidate_ids) != 1:
            raise ValueError(f"PATH_REPLAY_TESTED_CANDIDATE_COUNT:{strategy_id}:{len(candidate_ids)}")
        candidate_id = candidate_ids[0]
        generation = generations.get((strategy_id, candidate_id))
        if generation is None:
            raise ValueError(f"PATH_REPLAY_GENERATION_MISSING:{strategy_id}:{candidate_id}")
        row["same_axis_generation_count"] = generation
        row["path_replay_version"] = VERSION
        core.write_json(args.out.resolve() / strategy_id / "summary.json", row)
    result["version"] = VERSION
    core.write_json(args.out.resolve() / "batch.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-root", type=Path, required=True)
    parser.add_argument("--source-replay-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args)
    print(result["state"], "strategies=", result["strategy_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
