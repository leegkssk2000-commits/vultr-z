#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v1 as base
from backend.research.architecture_factory import a1_named_channel_gemini_sweep_v2 as v2

SCHEMA = "zel.a1.named_channel_gemini_sweep.v3"

_FINAL = {"USE", "REJECT_SOURCE", "REJECT_CHANNEL_MISMATCH"}


def _fair_review_priority(
    pool: Sequence[Mapping[str, Any]],
    reviews: Mapping[str, Any],
    channel_order: Mapping[str, int],
) -> list[dict[str, Any]]:
    """Return unreviewed videos in channel-fair round-robin order.

    The old sorter allowed the fixed contract channel order to dominate every
    review batch.  This implementation first gives review capacity to the
    least-reviewed channels, then round-robins across all channels with
    pending candidates.  Within a channel, verified search view count (when
    available) and recency are only discovery priorities, never evidence
    authority.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    final_review_count: dict[str, int] = {name: 0 for name in channel_order}

    pool_by_id: dict[str, Mapping[str, Any]] = {}
    for raw in pool:
        vid = str(raw.get("video_id") or "")
        if vid:
            pool_by_id[vid] = raw

    for vid, prior in reviews.items():
        if not isinstance(prior, Mapping) or str(prior.get("status") or "").upper() not in _FINAL:
            continue
        raw = pool_by_id.get(str(vid))
        if not raw:
            continue
        channel = str(raw.get("target_channel") or "")
        final_review_count[channel] = final_review_count.get(channel, 0) + 1

    for raw in pool:
        vid = str(raw.get("video_id") or "")
        prior = reviews.get(vid)
        if isinstance(prior, Mapping) and str(prior.get("status") or "").upper() in _FINAL:
            continue
        channel = str(raw.get("target_channel") or "")
        row = dict(raw)
        groups.setdefault(channel, []).append(row)

    for rows in groups.values():
        rows.sort(
            key=lambda x: (
                int(x.get("claimed_view_count_unverified") or 0),
                str(x.get("published_at") or ""),
                str(x.get("video_id") or ""),
            ),
            reverse=True,
        )

    channel_names = sorted(
        groups,
        key=lambda name: (
            int(final_review_count.get(name, 0)),
            int(channel_order.get(name, 999)),
            name,
        ),
    )

    out: list[dict[str, Any]] = []
    while True:
        added = False
        for name in channel_names:
            rows = groups.get(name) or []
            if not rows:
                continue
            out.append(rows.pop(0))
            added = True
        if not added:
            break
    return out


def run(output: Path, existing_path: Path = base.DEFAULT_EXISTING) -> dict[str, Any]:
    old_priority = base._review_priority
    try:
        base._review_priority = _fair_review_priority
        result = v2.run(output, existing_path)
    finally:
        base._review_priority = old_priority
    result["schema_version"] = SCHEMA
    result["review_rotation_policy"] = "LEAST_REVIEWED_CHANNEL_FIRST_THEN_TRUE_ROUND_ROBIN"
    result.setdefault("metrics", {})["fair_channel_review_rotation"] = True
    result["receipt_sha256"] = base._sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    pool = [
        {"video_id": "AAAAAAAAAAA", "target_channel": "A", "claimed_view_count_unverified": 100, "published_at": "2026-01-03"},
        {"video_id": "BBBBBBBBBBB", "target_channel": "A", "claimed_view_count_unverified": 90, "published_at": "2026-01-02"},
        {"video_id": "CCCCCCCCCCC", "target_channel": "B", "claimed_view_count_unverified": 10, "published_at": "2026-01-01"},
        {"video_id": "DDDDDDDDDDD", "target_channel": "C", "claimed_view_count_unverified": 5, "published_at": "2026-01-01"},
    ]
    order = _fair_review_priority(pool, {}, {"A": 0, "B": 1, "C": 2})
    assert [x["target_channel"] for x in order[:3]] == ["A", "B", "C"], order
    reviews = {"AAAAAAAAAAA": {"status": "USE"}}
    order2 = _fair_review_priority(pool, reviews, {"A": 0, "B": 1, "C": 2})
    assert [x["target_channel"] for x in order2[:2]] == ["B", "C"], order2
    assert v2._strict_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is not None
    print("PASS_A1_NAMED_CHANNEL_GEMINI_SWEEP_V3_SELF_TEST")
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
    print(json.dumps({"state": r["state"], **r["metrics"], "errors": r["provider"]["errors"][:3]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
