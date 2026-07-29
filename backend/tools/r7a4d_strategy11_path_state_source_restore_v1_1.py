from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_path_state_source_restore_v1 as core

VERSION = "R7A4D_STRATEGY11_PATH_STATE_SOURCE_RESTORE_V1_1"


def ending(root: Path, suffix: str, name: str) -> Path:
    rows = sorted(path.resolve() for path in root.rglob(Path(suffix).name) if str(path).replace("\\", "/").endswith(suffix))
    return core.one(rows, name)


def restore_generation(root: Path, out: Path) -> dict[str, Any] | None:
    if not root.exists():
        return None
    completions = []
    for path in root.rglob("replay_completion.json"):
        try:
            value = core.read_json(path)
        except Exception:
            continue
        if value.get("state") == "PASS_GENERATION7_QUOTA_STATE_MACHINE_PATH_LOOP_COMPLETE":
            completions.append((path, value))
    if not completions:
        return None
    _, completion = sorted(completions, key=lambda row: str(row[0]))[-1]
    replay_batch = ending(root, "replay/batch.json", "generation_replay_batch")
    path_plan = ending(root, "final/pre_shadow_path_plan.json", "generation_path_plan")
    search_ledger = ending(root, "final/search_ledger.json", "generation_search_ledger")
    path_index = ending(root, "final/path_evidence/index.json", "generation_path_index")
    triage = ending(root, "final/source_bound_triage/triage.json", "generation_triage")
    temporary = out.parent / ".generation_source_tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    shutil.copytree(replay_batch.parent, temporary / "replay")
    shutil.copytree(path_index.parent, temporary / "path_evidence")
    shutil.copy2(triage, temporary / "triage.json")
    shutil.copy2(search_ledger, temporary / "search_ledger.json")
    shutil.copy2(path_plan, temporary / "path_plan.json")
    result = core.copy_source(temporary, out, "GENERATION7", str(completion.get("completion_sha")))
    result["version"] = VERSION
    core.write_json(out / "source_manifest.json", result)
    shutil.rmtree(temporary)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-path-root", type=Path, required=True)
    parser.add_argument("--generation-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    result = core.restore_prior(args.prior_path_root, args.out)
    if result is None:
        result = restore_generation(args.generation_root, args.out)
    if result is None:
        result = {
            "schema_version": "strategy11.path_state.source_restore.status.v1",
            "version": VERSION,
            "state": "WAIT_PATH_SOURCE_ARTIFACT",
            **core.SAFETY,
        }
    core.write_json(args.status, result)
    print(result["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
