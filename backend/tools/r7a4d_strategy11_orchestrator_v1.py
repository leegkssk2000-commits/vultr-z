from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

UTC = dt.timezone.utc
TERMINAL_FAILURES = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "pending", "requested"}


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def minutes_since(value: str | None) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (utc_now() - parsed).total_seconds() / 60.0)


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class GitHubAPI:
    def __init__(self, token: str, repo: str) -> None:
        self.token = token
        self.repo = repo
        self.base = "https://api.github.com"

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "strategy11-orchestrator-v1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status == 204:
                    return {}
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GITHUB_HTTP_{exc.code}:{method}:{path}:{detail[:1200]}") from exc

    def repo_info(self) -> Mapping[str, Any]:
        return self.request("GET", f"/repos/{self.repo}")

    def pull(self, number: int) -> Mapping[str, Any]:
        return self.request("GET", f"/repos/{self.repo}/pulls/{number}")

    def workflow_runs(self, branch: str) -> list[Mapping[str, Any]]:
        query = urllib.parse.urlencode({"branch": branch, "per_page": 100})
        payload = self.request("GET", f"/repos/{self.repo}/actions/runs?{query}")
        return [row for row in payload.get("workflow_runs", []) if isinstance(row, Mapping)]

    def artifacts(self, run_id: int) -> list[Mapping[str, Any]]:
        payload = self.request("GET", f"/repos/{self.repo}/actions/runs/{run_id}/artifacts?per_page=100")
        return [row for row in payload.get("artifacts", []) if isinstance(row, Mapping)]

    def rerun_failed(self, run_id: int) -> None:
        self.request("POST", f"/repos/{self.repo}/actions/runs/{run_id}/rerun-failed-jobs", {})

    def default_has_workflow(self, default_branch: str, workflow_path: str) -> bool:
        query = urllib.parse.urlencode({"ref": default_branch})
        try:
            self.request("GET", f"/repos/{self.repo}/contents/{workflow_path}?{query}")
            return True
        except RuntimeError as exc:
            if "GITHUB_HTTP_404" in str(exc):
                return False
            raise


def latest_matching_run(api: GitHubAPI, branch: str, workflow_name: str) -> Mapping[str, Any] | None:
    rows = [row for row in api.workflow_runs(branch) if str(row.get("name")) == workflow_name]
    if not rows:
        return None
    rows.sort(key=lambda row: (str(row.get("created_at") or ""), int(row.get("run_attempt") or 0)), reverse=True)
    return rows[0]


def failed_attempt_count(api: GitHubAPI, branch: str, workflow_name: str, head_sha: str | None) -> int:
    rows = [row for row in api.workflow_runs(branch) if str(row.get("name")) == workflow_name]
    if head_sha:
        rows = [row for row in rows if str(row.get("head_sha") or "") == head_sha]
    return sum(1 for row in rows if str(row.get("conclusion") or "") in TERMINAL_FAILURES)


def inspect_stage(
    api: GitHubAPI,
    stage: Mapping[str, Any],
    policy: Mapping[str, Any],
    allow_mutations: bool,
) -> dict[str, Any]:
    stage_id = str(stage["stage_id"])
    result: dict[str, Any] = {
        "stage_id": stage_id,
        "order": int(stage["order"]),
        "implemented": bool(stage.get("implemented")),
        "data_dependent": bool(stage.get("data_dependent")),
        "depends_on": list(stage.get("depends_on", [])),
        "action": "hold",
        "state": "UNKNOWN",
        "blockers": [],
        "mutation_performed": False,
    }

    not_before = parse_time(stage.get("not_before_utc"))
    if result["data_dependent"] and not_before and utc_now() < not_before:
        result.update({
            "state": "WAIT_DATA",
            "action": "hold",
            "not_before_utc": not_before.isoformat().replace("+00:00", "Z"),
            "remaining_minutes": round((not_before - utc_now()).total_seconds() / 60.0, 2),
        })
        return result

    if not result["implemented"]:
        result.update({"state": "IMPLEMENTATION_REQUIRED", "action": "route_change"})
        return result

    pr_number = stage.get("pr_number")
    branch = str(stage.get("head_branch") or "")
    workflow_name = str(stage.get("workflow_name") or "")
    if not pr_number or not branch or not workflow_name:
        result.update({
            "state": "HOLD",
            "action": "block",
            "blockers": ["IMPLEMENTED_STAGE_METADATA_INCOMPLETE"],
        })
        return result

    pull = api.pull(int(pr_number))
    head_sha = str((pull.get("head") or {}).get("sha") or "")
    result.update({
        "pr_number": int(pr_number),
        "pr_state": pull.get("state"),
        "draft": pull.get("draft"),
        "head_branch": branch,
        "head_sha": head_sha,
        "workflow_name": workflow_name,
    })
    if pull.get("state") != "open":
        result.update({"state": "HOLD", "action": "block", "blockers": ["AUTHORITY_PR_NOT_OPEN"]})
        return result

    run = latest_matching_run(api, branch, workflow_name)
    if run is None:
        result.update({"state": "NO_RUN", "action": "route_change", "blockers": ["WORKFLOW_RUN_MISSING"]})
        return result

    run_id = int(run["id"])
    status = str(run.get("status") or "")
    conclusion = str(run.get("conclusion") or "")
    result.update({
        "run_id": run_id,
        "run_attempt": int(run.get("run_attempt") or 1),
        "run_status": status,
        "run_conclusion": conclusion or None,
        "run_head_sha": run.get("head_sha"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
    })

    if status in ACTIVE_STATUSES or status != "completed":
        age = minutes_since(run.get("updated_at"))
        threshold = float(policy["queued_stale_minutes"] if status == "queued" else policy["in_progress_stale_minutes"])
        result["heartbeat_age_minutes"] = age
        if age is not None and age > threshold:
            result.update({"state": "HOLD", "action": "hold", "blockers": [f"{status.upper()}_STALE"]})
        else:
            result.update({"state": "RUNNING", "action": "hold"})
        return result

    if conclusion == "success":
        artifacts = api.artifacts(run_id)
        names = [str(row.get("name") or "") for row in artifacts]
        prefix = str(stage.get("artifact_prefix") or "")
        result["artifact_names"] = names
        result["artifact_count"] = len(names)
        if prefix and not any(name.startswith(prefix) for name in names):
            result.update({"state": "HOLD", "action": "block", "blockers": ["REQUIRED_ARTIFACT_MISSING"]})
        elif str(run.get("head_sha") or "") != head_sha:
            result.update({"state": "HOLD", "action": "block", "blockers": ["RUN_HEAD_SHA_MISMATCH"]})
        else:
            result.update({"state": "PASS", "action": "hold"})
        return result

    if conclusion in TERMINAL_FAILURES:
        count = failed_attempt_count(api, branch, workflow_name, head_sha)
        result["same_head_failure_count"] = count
        max_retries = int(policy["max_same_cause_retries"])
        if allow_mutations and count <= max_retries:
            try:
                api.rerun_failed(run_id)
                result.update({
                    "state": "AUTO_RECOVERY_STARTED",
                    "action": "route_change",
                    "mutation_performed": True,
                })
            except RuntimeError as exc:
                result.update({
                    "state": "HOLD",
                    "action": "hold",
                    "blockers": ["RERUN_PERMISSION_OR_API_FAILED", str(exc)[:500]],
                })
        elif count > max_retries:
            result.update({"state": "HOLD", "action": "hold", "blockers": ["SAME_CAUSE_RETRY_BUDGET_EXHAUSTED"]})
        else:
            result.update({"state": "RECOVERY_READY", "action": "route_change"})
        return result

    result.update({"state": "HOLD", "action": "hold", "blockers": [f"UNHANDLED_CONCLUSION:{conclusion}"]})
    return result


def apply_dependency_gates(rows: list[dict[str, Any]]) -> None:
    by_id = {row["stage_id"]: row for row in rows}
    for row in rows:
        dependencies = row.get("depends_on", [])
        unsatisfied = [dep for dep in dependencies if by_id.get(dep, {}).get("state") != "PASS"]
        if not unsatisfied:
            row["dependencies_satisfied"] = True
            continue
        row["dependencies_satisfied"] = False
        row["unsatisfied_dependencies"] = unsatisfied
        if row["state"] in {"IMPLEMENTATION_REQUIRED", "NO_RUN"}:
            row["state"] = "BLOCKED_BY_DEPENDENCY"
            row["action"] = "hold"


def choose_next_request(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        row for row in rows
        if row["state"] == "IMPLEMENTATION_REQUIRED"
        and row.get("dependencies_satisfied") is True
        and not row.get("data_dependent")
    ]
    if not candidates:
        return None
    chosen = min(candidates, key=lambda row: row["order"])
    return {
        "stage_id": chosen["stage_id"],
        "reason": "NEXT_NON_DATA_STAGE_IMPLEMENTATION_REQUIRED",
        "required_action": "CREATE_MINIMUM_READ_ONLY_CHILD",
        "single_cause_only": True,
        "protected_mutations": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-mutations", choices=("true", "false"), default="false")
    parser.add_argument("--workflow-path", default=".github/workflows/r7a4d-strategy11-orchestrator-v1.yml")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    out = Path(args.out).resolve()
    config = strict_json(config_path)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repo:
        raise RuntimeError("GITHUB_RUNTIME_CONTEXT_MISSING")

    api = GitHubAPI(token, repo)
    repo_info = api.repo_info()
    default_branch = str(repo_info.get("default_branch") or "")
    allow_mutations = args.allow_mutations == "true"
    rows = [inspect_stage(api, stage, config["policy"], allow_mutations) for stage in config["stages"]]
    rows.sort(key=lambda row: row["order"])
    apply_dependency_gates(rows)
    next_request = choose_next_request(rows)

    unrecoverable = [
        row for row in rows
        if row["state"] == "HOLD" and row.get("blockers")
    ]
    active = [row for row in rows if row["state"] in {"RUNNING", "AUTO_RECOVERY_STARTED", "RECOVERY_READY"}]
    nondata_pending = [
        row for row in rows
        if not row.get("data_dependent") and row["state"] not in {"PASS", "BLOCKED_BY_DEPENDENCY"}
    ]
    wait_data = [row for row in rows if row["state"] == "WAIT_DATA"]

    full_native_active = api.default_has_workflow(default_branch, args.workflow_path)
    if unrecoverable:
        state = "HOLD"
    elif active:
        state = "RUNNING"
    elif next_request:
        state = "READY_FOR_NEXT_CHILD"
    elif nondata_pending:
        state = "PRE_W1_PENDING"
    elif wait_data:
        state = "WAIT_DATA_ONLY"
    else:
        state = "PASS"

    summary = {
        "schema_version": "1.0",
        "orchestrator_version": config["orchestrator_version"],
        "state": state,
        "generated_at_utc": utc_now().isoformat().replace("+00:00", "Z"),
        "repo": repo,
        "default_branch": default_branch,
        "github_native": True,
        "activation_mode": "FULL_NATIVE" if full_native_active else "PR_CHAIN_VALIDATED_DEFAULT_BRANCH_ACTIVATION_PENDING",
        "full_native_schedule_and_workflow_run_active": full_native_active,
        "allow_mutations": allow_mutations,
        "transition_contract": config["transitions"],
        "stages": rows,
        "next_stage_request": next_request,
        "unrecoverable_blocker_count": len(unrecoverable),
        "active_stage_count": len(active),
        "wait_data_stage_count": len(wait_data),
        "pre_w1_pending_count": len(nondata_pending),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "state_sha256": stable_sha(rows),
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "merge_performed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    atomic_json(out / "summary.json", summary)
    atomic_json(out / "stage_matrix.json", {"rows": rows})
    atomic_json(out / "next_stage_request.json", next_request or {"state": "NONE"})

    print(json.dumps({
        "state": state,
        "activation_mode": summary["activation_mode"],
        "active": len(active),
        "hold": len(unrecoverable),
        "wait_data": len(wait_data),
        "next": None if next_request is None else next_request["stage_id"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
