from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_path_state_source_restore_v1 as core

VERSION = "R7A4D_STRATEGY11_PATH_STATE_SOURCE_RESTORE_V1_2"
GENERATION_ARTIFACT_PREFIX = "s11-generation7-quota-state-v1-"
MAX_ARTIFACT_PAGES = 20


def ending(root: Path, suffix: str, name: str) -> Path:
    rows = sorted(path.resolve() for path in root.rglob(Path(suffix).name) if str(path).replace("\\", "/").endswith(suffix))
    return core.one(rows, name)


def finalize_manifest(result: dict[str, Any], out: Path, **extra: Any) -> dict[str, Any]:
    finalized = dict(result)
    finalized["version"] = VERSION
    finalized.update(extra)
    finalized.pop("source_manifest_sha", None)
    finalized["source_manifest_sha"] = core.canonical_sha(finalized)
    core.write_json(out / "source_manifest.json", finalized)
    return finalized


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
    shutil.rmtree(temporary)
    return finalize_manifest(result, out, restore_mode="LOCAL_GENERATION7")


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "strategy11-path-state-source-restore-v1-2",
    }


def api_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=github_headers(token))
    with urllib.request.urlopen(request, timeout=60) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"GITHUB_API_OBJECT_REQUIRED:{url}")
    return value


def download_artifact(url: str, token: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=github_headers(token))
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"ARTIFACT_ZIP_PATH_ESCAPE:{member.filename}")
        bundle.extractall(destination)


def remote_generation_artifacts(token: str, repository: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for page in range(1, MAX_ARTIFACT_PAGES + 1):
        url = f"https://api.github.com/repos/{repository}/actions/artifacts?per_page=100&page={page}"
        payload = api_json(url, token)
        rows = payload.get("artifacts")
        if not isinstance(rows, list):
            raise ValueError(f"GITHUB_ARTIFACT_ROWS_REQUIRED:{page}")
        for artifact in rows:
            if not isinstance(artifact, dict) or artifact.get("expired"):
                continue
            if str(artifact.get("name") or "").startswith(GENERATION_ARTIFACT_PREFIX):
                matches.append(artifact)
        if len(rows) < 100:
            break
    return sorted(matches, key=lambda row: (str(row.get("created_at") or ""), int(row.get("id") or 0)), reverse=True)


def restore_remote_generation(out: Path) -> dict[str, Any] | None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        return None
    artifacts = remote_generation_artifacts(token, repository)
    if not artifacts:
        return None
    temporary_root = out.parent / ".remote_generation_artifacts"
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    temporary_root.mkdir(parents=True)
    try:
        for artifact in artifacts:
            artifact_id = int(artifact.get("id") or 0)
            archive_url = str(artifact.get("archive_download_url") or "")
            if artifact_id <= 0 or not archive_url:
                continue
            artifact_root = temporary_root / str(artifact_id)
            archive = temporary_root / f"{artifact_id}.zip"
            download_artifact(archive_url, token, archive)
            safe_extract(archive, artifact_root)
            completed = False
            for path in artifact_root.rglob("replay_completion.json"):
                try:
                    value = core.read_json(path)
                except Exception:
                    continue
                if value.get("state") == "PASS_GENERATION7_QUOTA_STATE_MACHINE_PATH_LOOP_COMPLETE":
                    completed = True
                    break
            if not completed:
                continue
            result = restore_generation(artifact_root, out)
            if result is None:
                raise ValueError(f"REMOTE_COMPLETED_ARTIFACT_NOT_RESTORABLE:{artifact_id}")
            run = artifact.get("workflow_run") or {}
            return finalize_manifest(
                result,
                out,
                restore_mode="REMOTE_GENERATION7_PAGINATED",
                remote_artifact_id=artifact_id,
                remote_artifact_name=str(artifact.get("name") or ""),
                remote_artifact_created_at=str(artifact.get("created_at") or ""),
                remote_run_id=run.get("id"),
                remote_head_sha=run.get("head_sha"),
            )
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-path-root", type=Path, required=True)
    parser.add_argument("--generation-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    result = core.restore_prior(args.prior_path_root, args.out)
    if result is not None:
        result = finalize_manifest(result, args.out, restore_mode="LOCAL_PRIOR_PATH")
    if result is None:
        result = restore_generation(args.generation_root, args.out)
    if result is None:
        result = restore_remote_generation(args.out)
    if result is None:
        result = {
            "schema_version": "strategy11.path_state.source_restore.status.v1",
            "version": VERSION,
            "state": "WAIT_PATH_SOURCE_ARTIFACT",
            "artifact_pages_scanned": MAX_ARTIFACT_PAGES,
            **core.SAFETY,
        }
    core.write_json(args.status, result)
    print(result["state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
