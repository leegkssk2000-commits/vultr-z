from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1 as core

VERSION = "R7A4D_STRATEGY11_GENERATION7_QUOTA_STATE_MACHINE_V1_1"
QUOTA_MARKERS = (
    "rate limit",
    "ratelimit",
    "rate_limit",
    "http 429",
    "http_429",
    "status 429",
    "daily free allocation",
    "used up your daily free allocation",
    "quota exceeded",
    "quota_exceeded",
    "resource_exhausted",
    "too many requests",
    "verified_quota",
)


def is_verified_quota_failure(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in QUOTA_MARKERS)


def strict_classify(path: Path) -> str:
    result = core.read_json(path)
    status = str(result.get("status") or "")
    if status == "PASS_AI_REVIEW_DECISION_GATE":
        return "ACCEPTED"
    if status == "WAIT_AI_QUOTA_REVIEW":
        wait_codes = [str(value) for value in result.get("wait_codes") or []]
        if wait_codes and all(
            code.endswith("WAIT_NEXT_QUOTA_BATCH") or is_verified_quota_failure(code)
            for code in wait_codes
        ):
            return "WAIT_QUOTA"
        return "BLOCKER"
    if status == "HOLD_AI_REVIEW_DECISION_GATE":
        blockers = [str(value) for value in result.get("blocker_codes") or []]
        terminal_markers = ("SEMANTIC_REJECT", "SINGLE_AXIS_FALSE", "LINEAGE_INCOMPLETE")
        if blockers and all(any(marker in blocker for marker in terminal_markers) for blocker in blockers):
            return "SEMANTIC_REJECT"
        return "BLOCKER"
    return "BLOCKER"


def restore_epoch_usage(prior_roots: list[Path], epoch_date: str) -> int:
    for root in reversed(prior_roots):
        if not root.exists():
            continue
        manifests = sorted(root.rglob("ai_manifest.json"), reverse=True)
        for path in manifests:
            try:
                manifest = core.read_json(path)
            except Exception:
                continue
            if str(manifest.get("quota_epoch_date") or "") != epoch_date:
                continue
            used = int(manifest.get("quota_epoch_candidates_used") or 0)
            if used < 0:
                raise ValueError(f"NEGATIVE_QUOTA_EPOCH_USAGE:{path}:{used}")
            return used
    return 0


def rewrite_manifest(
    manifest: dict[str, Any],
    output_root: Path,
    *,
    epoch_date: str,
    used_before: int,
    selected: list[Path],
    max_new_candidates: int,
) -> dict[str, Any]:
    used_after = used_before + len(selected)
    if used_after > max_new_candidates:
        raise RuntimeError(f"DAILY_CANDIDATE_BUDGET_BREACH:{used_after}:{max_new_candidates}")
    manifest["state_machine_adapter_version"] = VERSION
    manifest["quota_epoch_date"] = epoch_date
    manifest["quota_epoch_candidates_used_before"] = used_before
    manifest["quota_epoch_selected_candidate_count"] = len(selected)
    manifest["quota_epoch_selected_files"] = [path.name for path in selected]
    manifest["quota_epoch_candidates_used"] = used_after
    manifest["quota_epoch_candidates_remaining"] = max_new_candidates - used_after
    manifest.pop("state_sha", None)
    manifest["state_sha"] = core.stable_sha(manifest)
    core.write_json(output_root / "ai_manifest.json", manifest)

    for name in ("accepted_plan.json", "search_ledger.json"):
        path = output_root / name
        payload = core.read_json(path)
        payload["state_machine_adapter_version"] = VERSION
        payload["quota_epoch_date"] = epoch_date
        payload["quota_epoch_candidates_used"] = used_after
        payload["quota_epoch_candidates_remaining"] = max_new_candidates - used_after
        core.write_json(path, payload)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--ai-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--prior-root", type=Path, action="append", default=[])
    parser.add_argument("--max-new-candidates", type=int, default=10)
    parser.add_argument("--quota-epoch-date", default="")
    args = parser.parse_args()
    if not 1 <= args.max_new_candidates <= 10:
        raise SystemExit("MAX_NEW_CANDIDATES_MUST_BE_1_TO_10")

    epoch_date = args.quota_epoch_date or datetime.now(timezone.utc).date().isoformat()
    core.classify = strict_classify
    plan, causes, ledger = core.build_payloads(args.plan_root, args.payload_root)
    args.ai_root.mkdir(parents=True, exist_ok=True)
    prior_roots = list(args.prior_root)

    for payload in sorted(args.payload_root.glob("*.json")):
        core.run_router(args.router, args.policy, payload, args.ai_root / payload.name, prior_roots, cache_only=True)

    used_before = restore_epoch_usage(prior_roots, epoch_date)
    remaining_budget = max(0, args.max_new_candidates - used_before)
    unresolved = [path for path in sorted(args.ai_root.glob("*.json")) if strict_classify(path) == "WAIT_QUOTA"]
    selected = unresolved[:remaining_budget]
    live_prior = [*prior_roots, args.ai_root]
    for result_path in selected:
        payload = args.payload_root / result_path.name
        core.run_router(args.router, args.policy, payload, result_path, live_prior, cache_only=False)

    manifest = core.finalize(plan, causes, ledger, args.ai_root, args.output_root, args.max_new_candidates)
    manifest = rewrite_manifest(
        manifest,
        args.output_root,
        epoch_date=epoch_date,
        used_before=used_before,
        selected=selected,
        max_new_candidates=args.max_new_candidates,
    )
    print(
        manifest["state"],
        "pass=", manifest["pass_count"],
        "reject=", manifest["semantic_reject_count"],
        "wait=", manifest["wait_quota_count"],
        "epoch_used=", manifest["quota_epoch_candidates_used"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
