from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

VERSION = "R7A4D_STRATEGY11_PATH_CANDIDATE_REPLAY_V1_1"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    core_path = Path(__file__).with_name("r7a4d_strategy11_path_candidate_replay_v1.py").resolve()
    command = [
        sys.executable,
        str(core_path),
        "--research-root", str(args.research_root.resolve()),
        "--source-replay-root", str(args.source_replay_root.resolve()),
        "--plan", str(args.plan.resolve()),
        "--policy", str(args.policy.resolve()),
        "--fresh-root", str(args.fresh_root.resolve()),
        "--evidence-root", str(args.evidence_root.resolve()),
        "--source-run-id", args.source_run_id,
        "--source-head-sha", args.source_head_sha,
        "--out", str(args.out.resolve()),
    ]
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    if process.returncode != 0:
        raise RuntimeError(
            f"PATH_REPLAY_SUBPROCESS_FAILED:{process.returncode}:"
            f"stdout={process.stdout[-2000:]}:stderr={process.stderr[-4000:]}"
        )
    result = read_json(args.out.resolve() / "batch.json")
    plan = read_json(args.plan)
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
        write_json(args.out.resolve() / strategy_id / "summary.json", row)
    result["version"] = VERSION
    write_json(args.out.resolve() / "batch.json", result)
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
