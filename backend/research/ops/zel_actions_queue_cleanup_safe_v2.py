#!/usr/bin/env python3
"""Explicitly pinned cancellation of OLD paused workflows, not a blanket purge.

This script executes only from the user-owned existing Queue Purge workflow with
GITHUB_TOKEN actions:write. Default plan 'dry_run' NEVER cancels anything.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA = "zel.actions.queue_purge.trigger.v2"
STATE = "PAUSE_OBSOLETE_SCHEDULES_20261025"
REPOSITORY = "leegkssk2000-commits/vultr-z"
PAUSED_FILES = frozenset(
    ".github/workflows/" + item
    for item in (
        "a1-a4-exact-parent-repair-batch-v1.yml",
        "a1-a5-named-channel-conversion-v10.yml",
        "a1-break-box-iterative-dd-repair-v1.yml",
        "a1-experimental-scalp-exhaustion-economics-v1.yml",
        "a1-gen2-repair-short-sma50-family-v1.yml",
        "a1-improvement-session-bias-v2.yml",
        "a1-top5-highamp-rescue-scan-v1.yml",
        "a1-top6-trendma-fresh-oos-v1.yml",
        "a1-top6-trendma-long-rebound-v1.yml",
        "a1-trend-rider-exact-parent-repair-batch-v1.yml",
        "a1-trend-rider-liquid12-rescue-v1.yml",
        "r7a4d-strategy11-authority-map-auto-v1.yml",
        "r7a4d-strategy11-continuous-data-v1.yml",
        "r7a4d-strategy11-generation7-quota-state-machine-v1.yml",
        "r7a4d-strategy11-intrabar-observer-v1.yml",
        "r7a4d-strategy11-orchestrator-v1.yml",
        "r7a4d-strategy11-path-candidate-state-machine-v1.yml",
        "r7a4d-strategy11-unattended-improvement-v2-1.yml",
        "r7a4d-strategy11-v3-internal-regime-expanded.yml",
        "r7a4d-strategy11-w1-boundary-accelerator-v1.yml",
        "r7a4d-strategy11-w1-native-ema-bind-v1.yml",
        "r7a4d-strategy11-w1-native-orchestrator-v1.yml",
        "strategy-synthesis-ablation-v1.yml",
    )
)


def parse_time(v: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    if d.utcoffset() is None or d.utcoffset() != dt.timedelta(0):
        raise ValueError("UTC_REQUIRED")
    return d


def validate_plan(plan: dict[str, Any], current: int) -> None:
    assert plan["schema_version"] == SCHEMA
    assert plan["state"] == STATE
    assert plan["mode"] in ("dry_run", "cancel")
    assert plan["sequence"] == (1 if plan["mode"] == "dry_run" else 2)
    assert plan["order_authority"] == "BLOCKED"
    assert plan["production_mutations"] == 0
    assert plan["economic_full_launched"] is False
    assert plan["ref"] == "master"
    selected = parse_time(plan["selected_before_utc"])
    now = dt.datetime.now(dt.timezone.utc)
    assert now >= selected and (now - selected).total_seconds() < 48 * 3600
    assert 1 <= len(plan["targets"]) <= 35
    ids = [int(x["id"]) for x in plan["targets"]]
    assert len(ids) == len(set(ids))
    protected = [int(x) for x in plan["protected_run_ids"]]
    assert 40122207006 in protected  # completed authorized Squeeze FULL
    assert len(protected) == len(set(protected))
    assert current not in ids
    assert not set(ids).intersection(protected)
    for t in plan["targets"]:
        assert t["workflow_path"] in PAUSED_FILES
        assert t["event"] in ("push", "schedule")
        assert t["status_at_selection"] in ("pending", "queued")
        assert t["head_branch"] == "master"
        assert isinstance(t["name"], str) and len(t["name"]) > 2
        assert int(t["workflow_id"]) > 0
        assert parse_time(t["created_at"]) <= selected
        assert "K117" not in t["name"] and "BingX WS" not in t["name"]
    if plan["mode"] == "cancel":
        assert int(plan["verified_dry_run_id"]) > 0
    else:
        assert plan["verified_dry_run_id"] is None


def main() -> int:
    if os.environ.get("GITHUB_EVENT_NAME") != "push":
        raise RuntimeError("PUSH_OF_VERSIONED_PLAN_ONLY")
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise RuntimeError("UNKNOWN_REPOSITORY")
    token = os.environ["GITHUB_TOKEN"]
    current = int(os.environ["GITHUB_RUN_ID"])
    plan = json.loads(
        Path("backend/research/zel_actions_queue_purge_trigger_v1.json").read_text()
    )
    validate_plan(plan, current)
    base = "https://api.github.com/repos/" + REPOSITORY
    h = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ZEL-specific-queue-cleanup-v2",
    }

    def call(url: str, method: str = "GET") -> tuple[int, dict[str, Any] | None]:
        req = urllib.request.Request(url, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            return exc.code, {"message": exc.read().decode("utf-8", "replace")[:220]}

    def fetch_run(run_id: int) -> dict[str, Any]:
        status, value = call(base + "/actions/runs/" + str(run_id))
        if status != 200 or not isinstance(value, dict):
            raise RuntimeError(f"RUN_READ_FAILED:{run_id}:{status}")
        return value

    if plan["mode"] == "cancel":
        prev = fetch_run(int(plan["verified_dry_run_id"]))
        if not (
            prev["name"] == "ZEL Actions Queue Purge V1"
            and prev["event"] == "push"
            and prev["status"] == "completed"
            and prev["conclusion"] == "success"
            and parse_time(prev["created_at"]) > parse_time(plan["selected_before_utc"])
        ):
            raise RuntimeError("NO_SUCCESSFUL_PRIOR_DRY_RUN")

    validated: list[int] = []
    skipped: list[dict[str, Any]] = []
    config_cache: dict[str, str] = {}

    # FIRST: read-validate ALL identities, file disable-state and run status.
    # Any unexpected metadata fails BEFORE the first cancellation.
    for candidate in plan["targets"]:
        rid = int(candidate["id"])
        run = fetch_run(rid)
        for expected, current_value in (
            ("workflow_id", run["workflow_id"]),
            ("name", run["name"]),
            ("event", run["event"]),
            ("created_at", run["created_at"]),
            ("head_branch", run["head_branch"]),
            ("workflow_path", run["path"].split("@")[0]),
        ):
            if candidate[expected] != current_value:
                raise RuntimeError(f"PINNED_RUN_IDENTITY_CHANGED:{rid}:{expected}")
        if run["event"] not in ("schedule", "push"):
            raise RuntimeError("NON_RESEARCH_AUTOMATION_EVENT")
        filename = candidate["workflow_path"]
        if filename not in config_cache:
            path = urllib.parse.quote(filename, safe="/")
            code, meta = call(base + "/contents/" + path + "?ref=master")
            if (
                code != 200
                or not isinstance(meta, dict)
                or meta.get("encoding") != "base64"
            ):
                raise RuntimeError(f"WORKFLOW_SOURCE_READ_FAILED:{filename}:{code}")
            src = base64.b64decode(meta["content"]).decode("utf-8")
            if re.search(r"^  (?:schedule|push|workflow_run):", src, re.M):
                raise RuntimeError("WORKFLOW_STILL_HAS_AUTO_TRIGGER:" + filename)
            if not re.search(r"^  workflow_dispatch:", src, re.M):
                raise RuntimeError("MANUAL_EXECUTION_WAS_NOT_PRESERVED")
            config_cache[filename] = src
        if run["status"] in ("pending", "queued"):
            validated.append(rid)
        else:
            skipped.append({"id": rid, "reason": "ALREADY_STARTED_OR_FINISHED"})

    canceled: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    if plan["mode"] == "cancel":
        for rid in validated:
            latest = fetch_run(rid)
            if latest["status"] not in ("pending", "queued"):
                skipped.append(
                    {"id": rid, "reason": "STATUS_CHANGED_SKIP_NO_IN_PROGRESS_CANCEL"}
                )
                continue
            code, response = call(base + f"/actions/runs/{rid}/cancel", "POST")
            if code == 202:
                canceled.append({"id": rid, "http_status": code})
            elif code == 409:
                skipped.append({"id": rid, "reason": "GH_ALREADY_COMPLETE"})
            else:
                failed.append({"id": rid, "http_status": code, "response": response})

    receipt = {
        "schema_version": "zel.actions.queue_purge.safe_v2",
        "state": (
            "DRY_RUN_VERIFIED"
            if plan["mode"] == "dry_run"
            else (
                "PINNED_OLD_QUEUE_CANCELED"
                if not failed
                else "HOLD_PARTIAL_API_FAILURE"
            )
        ),
        "mode": plan["mode"],
        "targets": len(plan["targets"]),
        "verified_eligible_ids": validated,
        "cancellation_requests_accepted": canceled,
        "skips": skipped,
        "failures": failed,
        "preserved_manual_or_PR_runners": True,
        "economic_full_launched": False,
        "order_authority": "BLOCKED",
        "promotion_authority": False,
        "production_mutations": 0,
    }
    out = Path("out")
    out.mkdir(exist_ok=True)
    (out / "queue_purge_receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "mode": receipt["mode"],
                "target_count": receipt["targets"],
                "eligible": len(validated),
                "cancellations": len(canceled),
                "failures": len(failed),
                "skips": len(skipped),
            },
            sort_keys=True,
        )
    )
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
