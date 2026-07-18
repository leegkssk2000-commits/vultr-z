#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_sha(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256_bytes(body)


def read_bytes(path: Path, limit: int) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > limit:
            return b""
        return path.read_bytes()
    except OSError:
        return b""


def parse_json(data: bytes) -> Any | None:
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def walk_values(payload: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key), value
            yield from walk_values(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from walk_values(value)


def first_metric(payload: Any, aliases: tuple[str, ...]) -> Any:
    normalized = {alias.lower() for alias in aliases}
    for key, value in walk_values(payload):
        if key.lower() in normalized and isinstance(value, (str, int, float, bool)):
            return value
    return None


def metrics(payload: Any) -> dict[str, Any]:
    return {
        "closed_count": first_metric(payload, ("closed_count", "closed", "state_closed", "total_closed", "verified_closed_count")),
        "pnl_r": first_metric(payload, ("pnl_r", "net_r", "total_r", "h85z_pnl", "shadow_pnl_r")),
        "winrate_pct": first_metric(payload, ("winrate_pct", "wr_pct", "win_rate", "winrate", "wr")),
        "latest_trace_id": first_metric(payload, ("latest_trace_id", "trace_id", "position_id", "last_trace_id")),
        "source": first_metric(payload, ("source", "src", "ledger_source", "data_source")),
    }


def fetch_endpoint(url: str, host: str, limit: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="r73b4s2_") as tmp:
        header_path = Path(tmp) / "headers.txt"
        body_path = Path(tmp) / "body.bin"
        command = [
            "curl", "-k", "-sS", "-L", "--max-time", "10",
            "-D", str(header_path), "-o", str(body_path), "-w", "%{http_code}",
        ]
        if host:
            command.extend(["-H", f"Host: {host}"])
        command.append(url)
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=15)
        body = read_bytes(body_path, limit)
        headers = read_bytes(header_path, 262144).decode("utf-8", errors="ignore")
        try:
            status = int((result.stdout or "0").strip()[-3:])
        except ValueError:
            status = 0
        payload = parse_json(body)
        content_type = ""
        for line in headers.splitlines():
            if line.lower().startswith("content-type:"):
                content_type = line.split(":", 1)[1].strip()
        return {
            "url": url,
            "host": host,
            "curl_rc": result.returncode,
            "http_status": status,
            "content_type": content_type,
            "size_bytes": len(body),
            "raw_sha256": sha256_bytes(body) if body else "",
            "canonical_json_sha256": canonical_json_sha(payload) if payload is not None else "",
            "json_valid": payload is not None,
            "metrics": metrics(payload) if payload is not None else {},
            "stderr": (result.stderr or "")[-500:],
            "payload": payload,
        }


def context_snippets(path: Path, needles: tuple[str, ...], radius: int = 2) -> list[dict[str, Any]]:
    data = read_bytes(path, 2_000_000)
    if not data:
        return []
    lines = data.decode("utf-8", errors="ignore").splitlines()
    hit_lines: set[int] = set()
    lowered_needles = tuple(value.lower() for value in needles)
    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(needle in lowered for needle in lowered_needles):
            hit_lines.add(index)
    output: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for index in sorted(hit_lines):
        if index in consumed:
            continue
        start = max(0, index - radius)
        end = min(len(lines), index + radius + 1)
        consumed.update(range(start, end))
        output.append({
            "path": str(path),
            "start_line": start + 1,
            "end_line": end,
            "text": "\n".join(f"{line_no + 1}:{lines[line_no]}" for line_no in range(start, end)),
        })
    return output[:40]


def file_inventory(roots: list[Path], response_sha: str, limit: int, max_files: int,
                   preferred_names: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    matches: list[dict[str, Any]] = []
    preferred: list[dict[str, Any]] = []
    count = 0
    preferred_set = set(preferred_names)
    for root in roots:
        if not root.is_dir():
            continue
        try:
            iterator = root.rglob("*.json")
            for path in iterator:
                count += 1
                if count > max_files:
                    return matches, preferred, count
                data = read_bytes(path, limit)
                if not data:
                    continue
                payload = parse_json(data)
                canonical = canonical_json_sha(payload) if payload is not None else ""
                record = {
                    "path": str(path),
                    "size_bytes": len(data),
                    "raw_sha256": sha256_bytes(data),
                    "canonical_json_sha256": canonical,
                    "json_valid": payload is not None,
                    "metrics": metrics(payload) if payload is not None else {},
                }
                if response_sha and canonical == response_sha:
                    matches.append(record)
                if path.name in preferred_set:
                    preferred.append(record)
        except OSError:
            continue
    return matches, preferred, count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    limit = int(contract["max_body_bytes"])

    endpoint_records: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for attempt in contract["endpoint_attempts"]:
        record = fetch_endpoint(str(attempt["url"]), str(attempt.get("host", "")), limit)
        endpoint_records.append({key: value for key, value in record.items() if key != "payload"})
        if selected is None and 200 <= record["http_status"] < 300 and record["json_valid"]:
            selected = record

    blockers: list[str] = []
    if selected is None:
        blockers.append("ALIMI_VIEW_ENDPOINT_JSON_UNREACHABLE")
        selected_sha = ""
    else:
        selected_sha = str(selected["canonical_json_sha256"])

    roots = [Path(value) for value in contract["web_roots"]]
    matches, preferred, scanned = file_inventory(
        roots, selected_sha, limit, int(contract["max_json_files"]),
        [str(value) for value in contract["preferred_origin_names"]],
    )
    if scanned > int(contract["max_json_files"]):
        blockers.append("TARGETED_JSON_SCAN_TRUNCATED")
    if selected is not None and not matches:
        blockers.append("ENDPOINT_ORIGIN_FILE_UNRESOLVED")

    index_snippets: list[dict[str, Any]] = []
    for value in contract["index_files"]:
        index_snippets.extend(context_snippets(
            Path(value),
            ("view_contract_latest.json", "view_contract_authoritative_latest.json", "q4r3_shadow_closed_ledger_latest.json", "fetch("),
            radius=3,
        ))

    caddy_snippets: list[dict[str, Any]] = []
    for value in contract["caddy_files"]:
        caddy_snippets.extend(context_snippets(
            Path(value),
            ("alimi.z-os.vip", "view_contract", "rewrite", "reverse_proxy", "handle", "root", "file_server"),
            radius=3,
        ))

    unique_match_hashes = sorted({item["canonical_json_sha256"] for item in matches})
    origin_mode = "FILE_MATCH" if matches else ("ENDPOINT_ONLY" if selected is not None else "UNRESOLVED")
    payload = {
        "schema": "q4r3_exact25_r73b4s2_alimi_endpoint_origin_resolver_status_v1",
        "state": "PASS" if not blockers else "HOLD",
        "blockers": blockers,
        "blocker_count": len(blockers),
        "read_only": True,
        "mutation_count": 0,
        "origin_mode": origin_mode,
        "selected_endpoint": ({key: value for key, value in selected.items() if key != "payload"} if selected else {}),
        "endpoint_records": endpoint_records,
        "file_match_count": len(matches),
        "unique_match_hash_count": len(unique_match_hashes),
        "file_matches": matches,
        "preferred_candidate_count": len(preferred),
        "preferred_candidates": preferred,
        "targeted_json_file_count": scanned,
        "index_snippets": index_snippets,
        "caddy_snippets": caddy_snippets,
        "next_stage": contract["next_stage"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "state": payload["state"],
        "blocker_count": payload["blocker_count"],
        "origin_mode": origin_mode,
        "selected_http_status": payload["selected_endpoint"].get("http_status", 0),
        "selected_closed_count": payload["selected_endpoint"].get("metrics", {}).get("closed_count"),
        "selected_pnl_r": payload["selected_endpoint"].get("metrics", {}).get("pnl_r"),
        "file_match_count": len(matches),
        "preferred_candidate_count": len(preferred),
        "targeted_json_file_count": scanned,
    }, sort_keys=True))
    return 0 if payload["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
