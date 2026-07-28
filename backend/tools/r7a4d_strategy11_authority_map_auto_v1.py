from __future__ import annotations

import argparse
import base64
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


VERSION = "R7A4D_STRATEGY11_AUTHORITY_MAP_AUTO_V1"
CAPABILITY_MARKER = "AUTHORITY_MAP_AUTO_GENERATOR"
UTC = dt.timezone.utc


def strict_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class GitHubAPI:
    def __init__(self, token: str, repo: str) -> None:
        self.token = token
        self.repo = repo
        self.base = "https://api.github.com"

    def request(self, path: str) -> Any:
        request = urllib.request.Request(
            self.base + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "strategy11-authority-map-auto-v1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GITHUB_HTTP_{exc.code}:{path}:{detail[:1000]}") from exc

    def pull(self, number: int) -> Mapping[str, Any]:
        return self.request(f"/repos/{self.repo}/pulls/{number}")

    def run(self, run_id: int) -> Mapping[str, Any]:
        return self.request(f"/repos/{self.repo}/actions/runs/{run_id}")

    def artifacts(self, run_id: int) -> list[Mapping[str, Any]]:
        payload = self.request(f"/repos/{self.repo}/actions/runs/{run_id}/artifacts?per_page=100")
        return [row for row in payload.get("artifacts", []) if isinstance(row, Mapping)]

    def open_pulls(self) -> list[Mapping[str, Any]]:
        payload = self.request(f"/repos/{self.repo}/pulls?state=open&per_page=100&sort=updated&direction=desc")
        return [row for row in payload if isinstance(row, Mapping)]

    def content_json(self, ref: str, path: str) -> tuple[dict[str, Any], str]:
        query = urllib.parse.urlencode({"ref": ref})
        payload = self.request(f"/repos/{self.repo}/contents/{path}?{query}")
        if str(payload.get("encoding")) != "base64":
            raise RuntimeError("CONTENT_ENCODING_NOT_BASE64")
        raw = base64.b64decode(str(payload["content"]))
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def normalize_title(value: str) -> str:
    tokens = []
    for raw in value.lower().replace("_", " ").replace("-", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum())
        if token and token not in {"v1", "v2", "clean", "child", "strategy11", "r7a4d"}:
            tokens.append(token)
    return " ".join(tokens)


def inspect_authority(api: GitHubAPI, spec: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    pr_number = int(spec["pr_number"])
    pull = api.pull(pr_number)
    head_sha = str((pull.get("head") or {}).get("sha") or "")
    expected_head = str(spec.get("expected_head_sha") or "")
    merged = bool(pull.get("merged") or pull.get("merged_at"))

    if expected_head and head_sha != expected_head:
        blockers.append("PR_HEAD_SHA_MISMATCH")
    if "expected_merged" in spec and merged is not bool(spec["expected_merged"]):
        blockers.append("PR_MERGE_STATE_MISMATCH")

    run_payload: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = []
    run_id = spec.get("run_id")
    if run_id is not None:
        run = api.run(int(run_id))
        run_payload = {
            "run_id": int(run_id),
            "name": run.get("name"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "head_sha": run.get("head_sha"),
            "run_attempt": run.get("run_attempt"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
        }
        expected_conclusion = str(spec.get("expected_conclusion") or "")
        if expected_conclusion and str(run.get("conclusion") or "") != expected_conclusion:
            blockers.append("RUN_CONCLUSION_MISMATCH")
        if expected_head and str(run.get("head_sha") or "") != expected_head:
            blockers.append("RUN_HEAD_SHA_MISMATCH")
        artifacts = [
            {
                "id": int(row["id"]),
                "name": str(row.get("name") or ""),
                "expired": bool(row.get("expired")),
                "digest": row.get("digest"),
            }
            for row in api.artifacts(int(run_id))
        ]

    return {
        "stage_id": str(spec["stage_id"]),
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "pr": {
            "number": pr_number,
            "title": pull.get("title"),
            "state": pull.get("state"),
            "draft": pull.get("draft"),
            "merged": merged,
            "base_ref": (pull.get("base") or {}).get("ref"),
            "head_ref": (pull.get("head") or {}).get("ref"),
            "head_sha": head_sha,
            "updated_at": pull.get("updated_at"),
        },
        "run": run_payload,
        "artifacts": artifacts,
        "authority_fingerprint": stable_sha({
            "stage_id": spec["stage_id"],
            "pr_number": pr_number,
            "head_sha": head_sha,
            "run_id": run_id,
            "run_head_sha": None if run_payload is None else run_payload.get("head_sha"),
            "artifact_digests": [row.get("digest") for row in artifacts],
        }),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    seed_path = Path(args.seed).resolve()
    out = Path(args.out).resolve()
    seed = strict_json(seed_path)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", str(seed.get("repository") or "")).strip()
    if not token or not repo:
        raise RuntimeError("GITHUB_RUNTIME_CONTEXT_MISSING")

    api = GitHubAPI(token, repo)
    authorities = [inspect_authority(api, row) for row in seed["authorities"]]
    blockers = [
        f"{row['stage_id']}:{blocker}"
        for row in authorities
        for blocker in row["blockers"]
    ]

    stream_spec = seed["data_stream"]
    stream, stream_sha = api.content_json(str(stream_spec["ref"]), str(stream_spec["manifest_path"]))
    stream_blockers: list[str] = []
    if str(stream.get("state")) != str(stream_spec["required_state"]):
        stream_blockers.append("DATA_STREAM_STATE_MISMATCH")
    if len(stream.get("symbols", [])) != int(stream_spec["required_symbols"]):
        stream_blockers.append("DATA_STREAM_SYMBOL_COUNT_MISMATCH")
    for key, expected in {
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    }.items():
        if stream.get(key) != expected:
            stream_blockers.append(f"DATA_STREAM_SAFETY_MISMATCH:{key}")
    blockers.extend(stream_blockers)

    latest_closed = parse_time(stream.get("latest_closed_end"))
    stream_age_minutes = None
    if latest_closed is not None:
        stream_age_minutes = max(0.0, (dt.datetime.now(UTC) - latest_closed).total_seconds() / 60.0)

    relevant_open = []
    title_groups: dict[str, list[int]] = {}
    for pull in api.open_pulls():
        title = str(pull.get("title") or "")
        head_ref = str((pull.get("head") or {}).get("ref") or "")
        body = str(pull.get("body") or "")
        if "strategy11" not in (title + " " + body + " " + head_ref).lower() and "r7a4d" not in head_ref.lower():
            continue
        number = int(pull["number"])
        normalized = normalize_title(title)
        title_groups.setdefault(normalized, []).append(number)
        relevant_open.append({
            "number": number,
            "title": title,
            "draft": bool(pull.get("draft")),
            "base_ref": (pull.get("base") or {}).get("ref"),
            "head_ref": head_ref,
            "head_sha": (pull.get("head") or {}).get("sha"),
            "updated_at": pull.get("updated_at"),
            "normalized_title": normalized,
        })
    potential_duplicates = [
        {"normalized_title": title, "pr_numbers": sorted(numbers)}
        for title, numbers in title_groups.items()
        if title and len(numbers) > 1
    ]

    state = "PASS_AUTHORITY_MAP_CURRENT" if not blockers else "HOLD_AUTHORITY_MAP_DRIFT"
    summary = {
        "schema_version": "1.0",
        "version": VERSION,
        "capability_marker": CAPABILITY_MARKER,
        "state": state,
        "generated_at_utc": dt.datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "repository": repo,
        "authority_count": len(authorities),
        "authority_pass_count": sum(row["state"] == "PASS" for row in authorities),
        "blockers": blockers,
        "authorities": authorities,
        "data_stream": {
            "ref": stream_spec["ref"],
            "manifest_path": stream_spec["manifest_path"],
            "manifest_sha256": stream_sha,
            "state": stream.get("state"),
            "available_non_overlap_bars": stream.get("available_non_overlap_bars"),
            "missing_to_w1_480": stream.get("missing_to_w1_480"),
            "w1_ready": stream.get("w1_ready"),
            "latest_closed_end": stream.get("latest_closed_end"),
            "age_minutes": None if stream_age_minutes is None else round(stream_age_minutes, 2),
            "blockers": stream_blockers,
        },
        "open_strategy11_prs": sorted(relevant_open, key=lambda row: row["number"]),
        "potential_duplicate_title_groups": potential_duplicates,
        "seed_sha256": hashlib.sha256(seed_path.read_bytes()).hexdigest(),
        "canonical_mutated": False,
        "registry_mutated": False,
        "protected_mutations": 0,
        "execution_allowed": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "next": "USE_GENERATED_MAP_AS_ORCHESTRATOR_INPUT" if not blockers else "HOLD_AND_RESOLVE_ONLY_REPORTED_DRIFT",
    }
    atomic_json(out / "summary.json", summary)
    atomic_json(out / "authority_map.json", {"authorities": authorities})
    atomic_json(out / "open_pr_topology.json", {
        "pull_requests": sorted(relevant_open, key=lambda row: row["number"]),
        "potential_duplicate_title_groups": potential_duplicates,
    })

    lines = [
        "# Strategy11 authority map auto v1",
        "",
        f"- State: **{state}**",
        f"- Authorities: `{summary['authority_pass_count']}/{summary['authority_count']}` PASS",
        f"- Data: `{stream.get('available_non_overlap_bars')}/480` bars",
        f"- Missing: `{stream.get('missing_to_w1_480')}` bars",
        f"- Manifest age: `{summary['data_stream']['age_minutes']}` minutes",
        f"- Open Strategy11 PRs: `{len(relevant_open)}`",
        f"- Potential duplicate title groups: `{len(potential_duplicates)}`",
        f"- Next: `{summary['next']}`",
    ]
    (out / "authority_map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": state,
        "authority_pass": summary["authority_pass_count"],
        "authority_total": summary["authority_count"],
        "available_bars": stream.get("available_non_overlap_bars"),
        "blockers": blockers,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
