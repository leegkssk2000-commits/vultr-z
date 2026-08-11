#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "zel.p3.flow_source_provenance_audit.v1"
DEFAULT_ROOT = Path("/home/z/z")
ROOT_NAMES = ("backend", "config", "policies", "research", "runtime", "scripts", "tools")
MAX_FILES = 10000
MAX_TEXT_BYTES = 750_000
TEXT_SUFFIXES = {".py", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".ini", ".md", ".txt", ".csv", ".sh"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "archive", "artifacts", "cache", ".cache"}
ENDPOINT_RE = re.compile(r"/openApi/[A-Za-z0-9_./-]+")
FLOW_PATTERNS = {
    "long_short": re.compile(r"longShort|long_short|long.?short", re.I),
    "position_ratio": re.compile(r"positionRatio|position_ratio|position.?ratio", re.I),
    "taker_flow": re.compile(r"takerBuy|taker_buy|takerSell|taker_sell|taker", re.I),
    "buy_sell": re.compile(r"buySell|buy_sell|buy.?sell", re.I),
    "order_flow": re.compile(r"order[_ ]?flow", re.I),
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def iter_files(root: Path) -> Iterable[Path]:
    emitted = 0
    for name in ROOT_NAMES:
        base = root / name
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for filename in filenames:
                yield Path(dirpath) / filename
                emitted += 1
                if emitted >= MAX_FILES:
                    return


def read_bounded(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_TEXT_BYTES).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def flow_tags(text: str) -> list[str]:
    return sorted(name for name, pattern in FLOW_PATTERNS.items() if pattern.search(text))


def audit(root: Path) -> dict[str, Any]:
    scanned = 0
    matches: list[dict[str, Any]] = []
    endpoint_literals: set[str] = set()

    for path in iter_files(root):
        scanned += 1
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or size > MAX_TEXT_BYTES:
            continue
        text = read_bounded(path)
        if not text:
            continue
        tags = flow_tags(text)
        if not tags:
            continue
        endpoints = sorted(set(ENDPOINT_RE.findall(text)))
        endpoint_literals.update(endpoints)
        matches.append({
            "path": safe_rel(root, path),
            "sha256": sha256_file(path),
            "size_bytes": size,
            "flow_tags": tags,
            "endpoint_literals": endpoints,
            "contains_timestamp_terms": bool(re.search(r"timestamp|fundingTime|updateTime|openTime|closeTime|\btime\b|\bts\b", text, re.I)),
            "contains_schema_terms": bool(re.search(r"schema|fields|columns|keys|record", text, re.I)),
            "raw_market_values_emitted": False,
        })

    verified_candidates = [
        row for row in matches
        if row["endpoint_literals"] and any("/openApi/" in endpoint for endpoint in row["endpoint_literals"])
    ]
    state = "PASS_FLOW_PROVENANCE_CANDIDATE_FOUND" if verified_candidates else "HOLD_NO_REPOSITORY_VERIFIED_NATIVE_FLOW_ENDPOINT"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "runtime_root": str(root),
        "files_scanned_bounded": scanned,
        "scan_cap": MAX_FILES,
        "flow_match_count": len(matches),
        "endpoint_backed_candidate_count": len(verified_candidates),
        "unique_endpoint_literals_in_flow_matches": sorted(endpoint_literals),
        "flow_matches": matches,
        "endpoint_backed_candidates": verified_candidates,
        "binding_allowed": False,
        "binding_rule": "PATH_SHA_AND_NATIVE_ENDPOINT_LITERAL_ARE_DISCOVERY_ONLY_UNTIL_SCHEMA_AND_READABILITY_ARE_SEPARATELY_VERIFIED",
        "synthetic_proxy_allowed": False,
        "raw_market_values_emitted": False,
        "runtime_mutated": False,
        "service_state_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    material = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    receipt["receipt_sha256"] = hashlib.sha256(material).hexdigest()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded read-only P3 native flow source provenance audit")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("G0_ROOT", str(DEFAULT_ROOT))))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "flow_match_count": result["flow_match_count"],
        "endpoint_backed_candidate_count": result["endpoint_backed_candidate_count"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
