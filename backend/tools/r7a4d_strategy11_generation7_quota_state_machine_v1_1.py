from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1 as core

VERSION = "R7A4D_STRATEGY11_GENERATION7_QUOTA_STATE_MACHINE_V1_1"
MAX_DAILY_CANDIDATES = 10
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


def usage_from_payload(payload: dict[str, Any], path: Path, epoch_date: str) -> int | None:
    if str(payload.get("quota_epoch_date") or "") != epoch_date:
        return None
    used = int(payload.get("quota_epoch_candidates_used") or 0)
    if not 0 <= used <= MAX_DAILY_CANDIDATES:
        raise ValueError(f"INVALID_QUOTA_EPOCH_USAGE:{path}:{used}")
    return used


def restore_epoch_usage(prior_roots: list[Path], epoch_date: str) -> int:
    usages: list[int] = []
    for root in prior_roots:
        if not root.exists():
            continue
        paths = [*root.rglob("quota_epoch_reservation.json"), *root.rglob("ai_manifest.json")]
        for path in sorted(set(paths)):
            try:
                payload = core.read_json(path)
            except Exception:
                continue
            used = usage_from_payload(payload, path, epoch_date)
            if used is not None:
                usages.append(used)
    return max(usages, default=0)


def reserve_epoch_usage(
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
    reservation = {
        "schema_version": "strategy11.generation7.quota_epoch_reservation.v1",
        "version": VERSION,
        "state": "QUOTA_EPOCH_CANDIDATES_RESERVED",
        "quota_epoch_date": epoch_date,
        "quota_epoch_candidates_used_before": used_before,
        "quota_epoch_selected_candidate_count": len(selected),
        "quota_epoch_selected_files": [path.name for path in selected],
        "quota_epoch_candidates_used": used_after,
        "quota_epoch_candidates_remaining": max_new_candidates - used_after,
        **core.SAFETY,
    }
    reservation["reservation_sha"] = core.stable_sha(reservation)
    core.write_json(output_root / "quota_epoch_reservation.json", reservation)
    return reservation


def rewrite_manifest(
    manifest: dict[str, Any],
    output_root: Path,
    *,
    epoch_date: str,
    used_before: int,
    selected: list[Path],
    max_new_candidates: int,
) -> dict[str, Any]:
    reservation = core.read_json(output_root / "quota_epoch_reservation.json")
    expected_used = used_before + len(selected)
    if reservation.get("quota_epoch_date") != epoch_date:
        raise RuntimeError("QUOTA_RESERVATION_DATE_MISMATCH")
    reservation_used = reservation.get("quota_epoch_candidates_used")
    if reservation_used is None or int(reservation_used) != expected_used:
        raise RuntimeError("QUOTA_RESERVATION_USAGE_MISMATCH")
    if reservation.get("quota_epoch_selected_files") != [path.name for path in selected]:
        raise RuntimeError("QUOTA_RESERVATION_SELECTION_MISMATCH")

    manifest["state_machine_adapter_version"] = VERSION
    manifest["quota_epoch_date"] = epoch_date
    manifest["quota_epoch_candidates_used_before"] = used_before
    manifest["quota_epoch_selected_candidate_count"] = len(selected)
    manifest["quota_epoch_selected_files"] = [path.name for path in selected]
    manifest["quota_epoch_candidates_used"] = expected_used
    manifest["quota_epoch_candidates_remaining"] = max_new_candidates - expected_used
    manifest["quota_epoch_reservation_sha"] = reservation["reservation_sha"]
    manifest.pop("state_sha", None)
    manifest["state_sha"] = core.stable_sha(manifest)
    core.write_json(output_root / "ai_manifest.json", manifest)

    for name in ("accepted_plan.json", "search_ledger.json"):
        path = output_root / name
        payload = core.read_json(path)
        payload["state_machine_adapter_version"] = VERSION
        payload["quota_epoch_date"] = epoch_date
        payload["quota_epoch_candidates_used"] = expected_used
        payload["quota_epoch_candidates_remaining"] = max_new_candidates - expected_used
        payload["quota_epoch_reservation_sha"] = reservation["reservation_sha"]
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
    parser.add_argument("--max-new-candidates", type=int, default=MAX_DAILY_CANDIDATES)
    parser.add_argument("--quota-epoch-date", default="")
    args = parser.parse_args()
    if not 1 <= args.max_new_candidates <= MAX_DAILY_CANDIDATES:
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
    reserve_epoch_usage(
        args.output_root,
        epoch_date=epoch_date,
        used_before=used_before,
        selected=selected,
        max_new_candidates=args.max_new_candidates,
    )

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
