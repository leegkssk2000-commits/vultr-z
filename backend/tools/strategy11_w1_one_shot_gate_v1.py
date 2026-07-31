from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

UTC = dt.timezone.utc


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def github_context() -> tuple[str, str, dict[str, str]]:
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", "")).strip()
    if not repo or not token:
        raise RuntimeError("GITHUB_LOOKUP_CONTEXT_MISSING")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "strategy11-w1-one-shot-gate",
    }
    return repo, token, headers


def github_artifacts(name: str, fixture: Path | None) -> list[dict[str, Any]]:
    if fixture is not None:
        data = strict_json(fixture)
        rows = data.get("artifacts", data) if isinstance(data, Mapping) else data
        return [dict(row) for row in rows if isinstance(row, Mapping) and row.get("name") == name and not row.get("expired", False)]
    repo, _token, headers = github_context()
    output: list[dict[str, Any]] = []
    for page in range(1, 21):
        query = urllib.parse.urlencode({"per_page": 100, "page": page, "name": name})
        request = urllib.request.Request(f"https://api.github.com/repos/{repo}/actions/artifacts?{query}", headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        rows = payload.get("artifacts", [])
        output.extend(dict(row) for row in rows if row.get("name") == name and not row.get("expired", False))
        if len(rows) < 100:
            break
    output.sort(key=lambda row: (str(row.get("updated_at") or ""), int(row.get("id") or 0)), reverse=True)
    return output


def github_release(tag: str, fixture: Path | None) -> dict[str, Any] | None:
    if not tag:
        return None
    if fixture is not None:
        data = strict_json(fixture)
        rows = data.get("releases", []) if isinstance(data, Mapping) else []
        matches = [dict(row) for row in rows if isinstance(row, Mapping) and row.get("tag_name") == tag and not row.get("draft", False)]
        return matches[0] if matches else None
    repo, _token, headers = github_context()
    encoded = urllib.parse.quote(tag, safe="")
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/tags/{encoded}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return dict(payload) if isinstance(payload, Mapping) and not payload.get("draft", False) else None


def workflow_run(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("workflow_run")
    return value if isinstance(value, Mapping) else {}


def common_status(contract: Mapping[str, Any], state: str, now: dt.datetime, blockers: list[str], next_step: str) -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "version": contract["version"],
        "state": state,
        "blockers": blockers,
        "w1_not_before_utc": contract["w1_not_before_utc"],
        "clock_now_utc": now.isoformat().replace("+00:00", "Z"),
        "next": next_step,
        "research_only": True,
        "promotion_authority": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "runtime_bound": False,
    }


def write_outputs(values: Mapping[str, Any]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            text = "true" if value is True else "false" if value is False else str(value)
            handle.write(f"{key}={text}\n")


def w1_mode(args: argparse.Namespace, contract: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
    stream_path = Path(args.stream)
    stream = strict_json(stream_path)
    assert stream.get("state") == "PASS" and stream.get("blockers") == [], stream
    assert len(stream.get("symbols", [])) == 5, stream
    assert stream.get("canonical_mutated") is False
    assert stream.get("registry_mutated") is False
    assert int(stream.get("protected_mutations", -1)) == 0
    assert stream.get("execution_allowed") is False
    assert stream.get("order_authority") == "BLOCKED"
    completion_name = str(contract["completion_artifact_name"])
    durable_tag = str(contract.get("durable_completion_release_tag") or "")
    fixture = Path(args.artifact_index) if args.artifact_index else None
    completed = github_artifacts(completion_name, fixture)
    durable_release = github_release(durable_tag, fixture) if durable_tag else None
    target = parse_time(str(contract["w1_not_before_utc"]))
    latest = parse_time(str(stream["latest_closed_end"]))
    available = int(stream.get("available_non_overlap_bars", 0))
    missing = int(stream.get("missing_to_w1_480", 480))
    clock_ready = now >= target
    data_ready = bool(stream.get("w1_ready")) and available >= 480 and missing == 0 and latest >= target
    if durable_release:
        state, ready, next_step = "ALREADY_COMPLETED", False, "USE_DURABLE_W1_RELEASE_RECEIPT"
    elif completed:
        state, ready, next_step = "ALREADY_COMPLETED", False, "USE_EXISTING_W1_COMPLETION_RECEIPT"
    elif not (clock_ready and data_ready):
        state, ready, next_step = "WAIT_DATA", False, "WAIT_NEXT_HOURLY_NATIVE_RUN"
    else:
        state, ready, next_step = "READY_TO_EXECUTE", True, "EXECUTE_SHARED_W1_ONCE"
    result = common_status(contract, state, now, [], next_step)
    result.update({
        "clock_ready": clock_ready,
        "data_ready": data_ready,
        "stream_available_non_overlap_bars": available,
        "stream_missing_to_w1_480": missing,
        "stream_w1_ready": bool(stream.get("w1_ready")),
        "stream_latest_closed_end": stream.get("latest_closed_end"),
        "stream_manifest_sha256": hashlib.sha256(stream_path.read_bytes()).hexdigest(),
        "completion_artifact_name": completion_name,
        "completion_receipt_count": len(completed),
        "durable_completion_release_tag": durable_tag,
        "durable_completion_release_found": durable_release is not None,
        "durable_completion_release_id": (durable_release or {}).get("id"),
        "one_shot_ready": ready,
    })
    write_outputs({"ready": ready, "state": state, "available": available, "missing": missing, "stream_sha": result["stream_manifest_sha256"], "durable_release_found": durable_release is not None})
    return result


def ema_mode(args: argparse.Namespace, contract: Mapping[str, Any], now: dt.datetime) -> dict[str, Any]:
    target = parse_time(str(contract["w1_not_before_utc"]))
    completion_name = str(contract["completion_artifact_name"])
    upstream_name = str(contract["upstream_completion_artifact_name"])
    fixture = Path(args.artifact_index) if args.artifact_index else None
    completed = github_artifacts(completion_name, fixture)
    upstream = github_artifacts(upstream_name, fixture)
    if completed:
        state, ready, next_step = "ALREADY_COMPLETED", False, "USE_EXISTING_EMA_COMPLETION_RECEIPT"
        selected: Mapping[str, Any] = {}
    elif now < target:
        state, ready, next_step = "WAIT_DATA", False, "WAIT_NEXT_HOURLY_NATIVE_RUN"
        selected = {}
    elif not upstream:
        state, ready, next_step = "WAIT_UPSTREAM", False, "WAIT_NATIVE_W1_COMPLETION_RECEIPT"
        selected = {}
    else:
        state, ready, next_step = "RESOLVE_UPSTREAM", True, "DOWNLOAD_UPSTREAM_NATIVE_ARTIFACT"
        selected = upstream[0]
    run = workflow_run(selected)
    run_id = run.get("id") or selected.get("workflow_run_id") or ""
    head_sha = run.get("head_sha") or selected.get("head_sha") or ""
    artifact_name = selected.get("name") or ""
    if ready and not run_id:
        raise RuntimeError("UPSTREAM_COMPLETION_RUN_ID_MISSING")
    result = common_status(contract, state, now, [], next_step)
    result.update({
        "clock_ready": now >= target,
        "one_shot_ready": ready,
        "completion_artifact_name": completion_name,
        "completion_receipt_count": len(completed),
        "upstream_completion_artifact_name": upstream_name,
        "upstream_receipt_count": len(upstream),
        "upstream_run_id": str(run_id),
        "upstream_head_sha": str(head_sha),
        "upstream_artifact_name": str(artifact_name),
    })
    write_outputs({"ready": ready, "state": state, "run_id": run_id, "head_sha": head_sha, "artifact_name": artifact_name})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("w1", "ema"), required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--stream")
    parser.add_argument("--out", required=True)
    parser.add_argument("--artifact-index")
    parser.add_argument("--now-utc")
    args = parser.parse_args()
    contract = strict_json(Path(args.contract))
    now = parse_time(args.now_utc) if args.now_utc else dt.datetime.now(UTC)
    if args.mode == "w1":
        if not args.stream:
            raise RuntimeError("STREAM_PATH_REQUIRED")
        result = w1_mode(args, contract, now)
    else:
        result = ema_mode(args, contract, now)
    result["status_sha256"] = stable_sha({key: value for key, value in result.items() if key != "status_sha256"})
    atomic_json(Path(args.out), result)
    print(json.dumps({"state": result["state"], "next": result["next"], "ready": result["one_shot_ready"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
