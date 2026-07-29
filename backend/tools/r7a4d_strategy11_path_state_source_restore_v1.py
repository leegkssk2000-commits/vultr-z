from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

VERSION = "R7A4D_STRATEGY11_PATH_STATE_SOURCE_RESTORE_V1"
SAFETY = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "execution_allowed": False,
    "order_authority": "BLOCKED",
    "runtime_bound": False,
}


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def one(paths: list[Path], name: str) -> Path:
    unique = sorted(set(path.resolve() for path in paths))
    if len(unique) != 1:
        raise ValueError(f"SOURCE_PATH_COUNT:{name}:{len(unique)}")
    return unique[0]


def copy_source(source_root: Path, out: Path, source_type: str, authority_sha: str) -> dict[str, Any]:
    required = {
        "replay": source_root / "replay",
        "path_evidence": source_root / "path_evidence",
        "triage": source_root / "triage.json",
        "search_ledger": source_root / "search_ledger.json",
        "path_plan": source_root / "path_plan.json",
    }
    for name, path in required.items():
        if not path.exists():
            raise ValueError(f"SOURCE_COMPONENT_MISSING:{name}:{path}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(required["replay"], out / "replay")
    shutil.copytree(required["path_evidence"], out / "path_evidence")
    shutil.copy2(required["triage"], out / "triage.json")
    shutil.copy2(required["search_ledger"], out / "search_ledger.json")
    shutil.copy2(required["path_plan"], out / "path_plan.json")
    components = {
        "replay_batch_sha": file_sha(out / "replay" / "batch.json"),
        "path_index_sha": read_json(out / "path_evidence" / "index.json")["index_sha"],
        "triage_sha": read_json(out / "triage.json")["triage_sha"],
        "search_ledger_file_sha": file_sha(out / "search_ledger.json"),
        "path_plan_sha": read_json(out / "path_plan.json")["plan_sha"],
    }
    manifest = {
        "schema_version": "strategy11.path_state.source_manifest.v1",
        "version": VERSION,
        "state": "PASS_PATH_STATE_SOURCE_RESTORED",
        "source_type": source_type,
        "source_authority_sha": authority_sha,
        "components": components,
        **SAFETY,
    }
    manifest["source_manifest_sha"] = canonical_sha(manifest)
    write_json(out / "source_manifest.json", manifest)
    return manifest


def restore_prior(root: Path, out: Path) -> dict[str, Any] | None:
    manifests = sorted(root.rglob("source_manifest.json")) if root.exists() else []
    valid = []
    for path in manifests:
        try:
            value = read_json(path)
        except Exception:
            continue
        if value.get("state") != "PASS_PATH_STATE_SOURCE_READY":
            continue
        source_root = path.parent / "source"
        if source_root.exists():
            valid.append((path, value, source_root))
    if not valid:
        return None
    if len(valid) > 1:
        valid.sort(key=lambda row: str(row[0]))
    _, value, source_root = valid[-1]
    return copy_source(source_root, out, "PATH_EPOCH", str(value.get("source_authority_sha") or value.get("source_manifest_sha")))


def restore_generation(root: Path, out: Path) -> dict[str, Any] | None:
    if not root.exists():
        return None
    completions = []
    for path in root.rglob("replay_completion.json"):
        try:
            value = read_json(path)
        except Exception:
            continue
        if value.get("state") == "PASS_GENERATION7_QUOTA_STATE_MACHINE_PATH_LOOP_COMPLETE":
            completions.append((path, value))
    if not completions:
        return None
    completion_path, completion = sorted(completions, key=lambda row: str(row[0]))[-1]
    replay_batch = one(list(root.rglob("replay/batch.json")), "generation_replay_batch")
    path_plan = one(list(root.rglob("pre_shadow_path_plan.json")), "generation_path_plan")
    search_ledger = one(list(root.rglob("search_ledger.json")), "generation_search_ledger")
    path_index = one(list(root.rglob("path_evidence/index.json")), "generation_path_index")
    triage = one(list(root.rglob("source_bound_triage/triage.json")), "generation_triage")
    temporary = out.parent / ".generation_source_tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    shutil.copytree(replay_batch.parent, temporary / "replay")
    shutil.copytree(path_index.parent, temporary / "path_evidence")
    shutil.copy2(triage, temporary / "triage.json")
    shutil.copy2(search_ledger, temporary / "search_ledger.json")
    shutil.copy2(path_plan, temporary / "path_plan.json")
    result = copy_source(temporary, out, "GENERATION7", str(completion.get("completion_sha")))
    shutil.rmtree(temporary)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-path-root", type=Path, required=True)
    parser.add_argument("--generation-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    result = restore_prior(args.prior_path_root, args.out)
    if result is None:
        result = restore_generation(args.generation_root, args.out)
    if result is None:
        result = {
            "schema_version": "strategy11.path_state.source_restore.status.v1",
            "version": VERSION,
            "state": "WAIT_PATH_SOURCE_ARTIFACT",
            **SAFETY,
        }
    write_json(args.status, result)
    print(result["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
