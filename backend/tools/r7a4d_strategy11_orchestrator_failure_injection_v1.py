from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Mapping

VERSION = "R7A4D_STRATEGY11_ORCHESTRATOR_FAILURE_INJECTION_V1"
ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_PATH = ROOT / "backend/tools/r7a4d_strategy11_orchestrator_v1.py"


def load_orchestrator() -> Any:
    name = "r7a4d_strategy11_orchestrator_for_failure_injection"
    spec = importlib.util.spec_from_file_location(name, ORCHESTRATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("ORCHESTRATOR_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


orch = load_orchestrator()


def write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


class FakeAPI:
    def __init__(self, *, pull_sha: str = "head-good", runs: list[dict[str, Any]] | None = None,
                 artifacts: list[dict[str, Any]] | None = None, rerun_error: str | None = None) -> None:
        self.pull_sha = pull_sha
        self.runs = list(runs or [])
        self.artifact_rows = list(artifacts or [])
        self.rerun_error = rerun_error
        self.rerun_calls: list[int] = []

    def pull(self, number: int) -> Mapping[str, Any]:
        return {"state": "open", "draft": True, "head": {"sha": self.pull_sha}}

    def workflow_runs(self, branch: str) -> list[Mapping[str, Any]]:
        return list(self.runs)

    def artifacts(self, run_id: int) -> list[Mapping[str, Any]]:
        return list(self.artifact_rows)

    def rerun_failed(self, run_id: int) -> None:
        if self.rerun_error:
            raise RuntimeError(self.rerun_error)
        self.rerun_calls.append(run_id)


def stage(**overrides: Any) -> dict[str, Any]:
    value = {
        "stage_id": "FIXTURE_STAGE",
        "order": 10,
        "pr_number": 999,
        "head_branch": "fixture-branch",
        "workflow_name": "Fixture Workflow",
        "artifact_prefix": "fixture-artifact-",
        "depends_on": [],
        "data_dependent": False,
        "implemented": True,
    }
    value.update(overrides)
    return value


def run(*, status: str = "completed", conclusion: str | None = "success", head_sha: str = "head-good",
        run_id: int = 101, attempt: int = 1, updated_at: str = "2026-07-27T23:00:00Z") -> dict[str, Any]:
    return {
        "id": run_id,
        "name": "Fixture Workflow",
        "status": status,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "run_attempt": attempt,
        "created_at": "2026-07-27T22:00:00Z",
        "updated_at": updated_at,
    }


def policy() -> dict[str, Any]:
    return {
        "max_same_cause_retries": 2,
        "queued_stale_minutes": 45,
        "in_progress_stale_minutes": 60,
    }


def assert_case(name: str, condition: bool, detail: Any, rows: list[dict[str, Any]]) -> None:
    state = "PASS" if condition else "FAIL"
    rows.append({"case": name, "state": state, "detail": detail})
    if not condition:
        raise AssertionError(f"{name}:{detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out).resolve()
    cases: list[dict[str, Any]] = []

    success_api = FakeAPI(runs=[run()], artifacts=[{"name": "fixture-artifact-101-attempt-1"}])
    success = orch.inspect_stage(success_api, stage(), policy(), False)
    assert_case("SUCCESS_ARTIFACT_AND_HEAD", success["state"] == "PASS", success, cases)

    missing = orch.inspect_stage(FakeAPI(runs=[run()], artifacts=[]), stage(), policy(), False)
    assert_case("ARTIFACT_MISSING_FAIL_CLOSED", missing["state"] == "HOLD" and "REQUIRED_ARTIFACT_MISSING" in missing["blockers"], missing, cases)

    mismatch = orch.inspect_stage(FakeAPI(runs=[run(head_sha="wrong")], artifacts=[{"name": "fixture-artifact-ok"}]), stage(), policy(), False)
    assert_case("HEAD_SHA_MISMATCH_FAIL_CLOSED", mismatch["state"] == "HOLD" and "RUN_HEAD_SHA_MISMATCH" in mismatch["blockers"], mismatch, cases)

    failed_rows = [run(conclusion="failure", run_id=201)]
    recovery_api = FakeAPI(runs=failed_rows)
    recovery = orch.inspect_stage(recovery_api, stage(), policy(), True)
    assert_case("FAILURE_RERUN_WITHIN_BUDGET", recovery["state"] == "AUTO_RECOVERY_STARTED" and recovery_api.rerun_calls == [201], recovery, cases)

    timeout_api = FakeAPI(runs=[run(conclusion="timed_out", run_id=202)])
    timeout = orch.inspect_stage(timeout_api, stage(), policy(), True)
    assert_case("TIMEOUT_RERUN_WITHIN_BUDGET", timeout["state"] == "AUTO_RECOVERY_STARTED" and timeout_api.rerun_calls == [202], timeout, cases)

    exhausted_runs = [run(conclusion="failure", run_id=301), run(conclusion="timed_out", run_id=302), run(conclusion="cancelled", run_id=303)]
    exhausted = orch.inspect_stage(FakeAPI(runs=exhausted_runs), stage(), policy(), True)
    assert_case("RETRY_BUDGET_EXHAUSTED", exhausted["state"] == "HOLD" and "SAME_CAUSE_RETRY_BUDGET_EXHAUSTED" in exhausted["blockers"], exhausted, cases)

    api_429 = orch.inspect_stage(FakeAPI(runs=[run(conclusion="failure", run_id=401)], rerun_error="GITHUB_HTTP_429"), stage(), policy(), True)
    assert_case("API_429_FAIL_CLOSED", api_429["state"] == "HOLD" and "RERUN_PERMISSION_OR_API_FAILED" in api_429["blockers"], api_429, cases)

    queued = orch.inspect_stage(
        FakeAPI(runs=[run(status="queued", conclusion=None, updated_at="2000-01-01T00:00:00Z")]),
        stage(), policy(), False,
    )
    assert_case("QUEUED_STALE_FAIL_CLOSED", queued["state"] == "HOLD" and "QUEUED_STALE" in queued["blockers"], queued, cases)

    progress = orch.inspect_stage(
        FakeAPI(runs=[run(status="in_progress", conclusion=None, updated_at="2000-01-01T00:00:00Z")]),
        stage(), policy(), False,
    )
    assert_case("IN_PROGRESS_STALE_FAIL_CLOSED", progress["state"] == "HOLD" and "IN_PROGRESS_STALE" in progress["blockers"], progress, cases)

    wait = orch.inspect_stage(
        FakeAPI(),
        stage(stage_id="DATA_WAIT", data_dependent=True, not_before_utc="2099-01-01T00:00:00Z"),
        policy(), False,
    )
    assert_case("WAIT_DATA_IS_NOT_FAILURE", wait["state"] == "WAIT_DATA" and wait["action"] == "hold", wait, cases)

    dependency_rows = [
        {"stage_id": "A", "order": 10, "state": "PASS", "depends_on": [], "data_dependent": False},
        {"stage_id": "WAIT", "order": 20, "state": "WAIT_DATA", "depends_on": [], "data_dependent": True},
        {"stage_id": "NEXT", "order": 30, "state": "IMPLEMENTATION_REQUIRED", "depends_on": ["A"], "data_dependent": False},
    ]
    orch.apply_dependency_gates(dependency_rows)
    request = orch.choose_next_request(dependency_rows)
    assert_case("WAIT_DATA_CONTINUES_NONDATA_BACKLOG", bool(request) and request["stage_id"] == "NEXT", request, cases)

    blocked_rows = [
        {"stage_id": "A", "order": 10, "state": "HOLD", "depends_on": [], "data_dependent": False},
        {"stage_id": "NEXT", "order": 20, "state": "IMPLEMENTATION_REQUIRED", "depends_on": ["A"], "data_dependent": False},
    ]
    orch.apply_dependency_gates(blocked_rows)
    request_blocked = orch.choose_next_request(blocked_rows)
    assert_case("DEPENDENCY_HOLD_BLOCKS_CHILD", request_blocked is None and blocked_rows[1]["state"] == "BLOCKED_BY_DEPENDENCY", blocked_rows, cases)

    config_path = Path(args.config).resolve()
    workflow_path = Path(args.workflow).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    workflow_text = workflow_path.read_text(encoding="utf-8")
    static = {
        "contents_read_only": "contents: read" in workflow_text,
        "actions_write_only_recovery": "actions: write" in workflow_text,
        "order_blocked_assertion": "order_authority'] == 'BLOCKED'" in workflow_text,
        "execution_none_assertion": "execution_authority'] == 'NONE'" in workflow_text,
        "protected_zero_assertion": "protected_mutations'] == 0" in workflow_text,
        "canonical_merge_forbidden": config["policy"]["canonical_merge_forbidden"] is True,
        "protected_mutations_forbidden": config["policy"]["protected_mutations_forbidden"] is True,
        "email_forbidden": config["policy"]["email_forbidden"] is True,
    }
    assert_case("STATIC_SAFETY_CONTRACT", all(static.values()), static, cases)

    result = {
        "schema_version": "1.0",
        "version": VERSION,
        "state": "PASS_FAILURE_INJECTION",
        "case_count": len(cases),
        "passed_count": sum(row["state"] == "PASS" for row in cases),
        "failed_count": sum(row["state"] != "PASS" for row in cases),
        "cases": cases,
        "injected_classes": [
            "REQUIRED_ARTIFACT_MISSING", "RUN_HEAD_SHA_MISMATCH", "FAILURE", "TIMED_OUT",
            "RETRY_BUDGET_EXHAUSTED", "API_429", "QUEUED_STALE", "IN_PROGRESS_STALE",
            "WAIT_DATA", "DEPENDENCY_HOLD",
        ],
        "next": "PRE_W1_COMPLETION_AUDIT",
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }
    write(out / "summary.json", result)
    print(json.dumps({"state": result["state"], "cases": result["case_count"], "passed": result["passed_count"], "next": result["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
