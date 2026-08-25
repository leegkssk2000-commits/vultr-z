#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v1 as base
from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v2 as v2
from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v4 as v4
from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v5 as v5

SCHEMA = "zel.a1.named_channel_gemini_sweep.v6"
DISCOVERY_POLICY = "ALL_9_CHANNELS_ROUND_ROBIN__MOST_VIEWED_NEWEST_ARCHIVE_MECHANISM_DENSE"
_ORIG_V2_NORMALIZE = v2._normalize_search


def _safe_normalize_search(value: Mapping[str, Any], target: Mapping[str, Any]) -> list[dict[str, Any]]:
    """V4-compatible normalization without monkey-patch recursion."""
    rows = _ORIG_V2_NORMALIZE(value, target)
    meta: dict[str, Mapping[str, Any]] = {}
    for raw in value.get("videos") or []:
        if not isinstance(raw, Mapping):
            continue
        vid = v2._valid_id(raw.get("video_id"))
        if vid:
            meta[vid] = raw
    allowed = {"MOST_VIEWED", "NEWEST", "ARCHIVE", "MECHANISM_DENSE"}
    for row in rows:
        raw = meta.get(str(row.get("video_id") or "")) or {}
        bucket = str(raw.get("discovery_bucket") or "").strip().upper()
        row["discovery_bucket"] = bucket if bucket in allowed else "UNCLASSIFIED"
    return rows


def run(output: Path, existing_path: Path = base.DEFAULT_EXISTING) -> dict[str, Any]:
    old_v4_norm = v4._normalize_search
    try:
        v4._normalize_search = _safe_normalize_search
        result = v5.run(output, existing_path)
    finally:
        v4._normalize_search = old_v4_norm

    result["schema_version"] = SCHEMA
    result["discovery_policy"] = DISCOVERY_POLICY
    result.setdefault("normalization_integrity", {})["v2_v4_recursion_guard"] = True
    result["normalization_integrity"]["search_normalizer"] = "V6_SAFE_ORIGINAL_V2_PLUS_V4_BUCKET_METADATA"
    result["receipt_sha256"] = base._sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    target = {"display_name": "Trading Notes", "aliases": ["Trading Notes"]}
    value = {
        "videos": [
            {
                "target_channel": "Trading Notes",
                "video_id": "dQw4w9WgXcQ",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "x",
                "channel": "Trading Notes",
                "published_at": "",
                "claimed_view_count": 0,
                "discovery_bucket": "MOST_VIEWED",
                "why_relevant": "test",
            }
        ]
    }
    rows = _safe_normalize_search(value, target)
    assert len(rows) == 1
    assert rows[0]["video_id"] == "dQw4w9WgXcQ"
    assert rows[0]["discovery_bucket"] == "MOST_VIEWED"
    print("PASS_A1_NAMED_CHANNEL_GEMINI_SWEEP_V6_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_named_channel_gemini_latest.json"))
    ap.add_argument("--existing", type=Path, default=base.DEFAULT_EXISTING)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output, args.existing)
    print(json.dumps({"state": r["state"], **r["metrics"], "errors": r["provider"]["errors"][:6]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
