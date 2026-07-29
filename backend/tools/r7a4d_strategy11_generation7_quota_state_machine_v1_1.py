from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.tools import r7a4d_strategy11_generation7_quota_state_machine_v1 as core

VERSION = "R7A4D_STRATEGY11_GENERATION7_QUOTA_STATE_MACHINE_V1_3"
MAX_DAILY_CANDIDATES = 10
MAX_PROVIDER_RETRY_EPOCHS = 3
QUOTA_MARKERS = (
    "rate limit", "ratelimit", "rate_limit", "http 429", "http_429",
    "status 429", "daily free allocation", "used up your daily free allocation",
    "quota exceeded", "quota_exceeded", "resource_exhausted", "too many requests",
    "verified_quota",
)
RETRYABLE_OUTPUT_MARKERS = (
    "retryable_provider_output", "response_json_recovery_exhausted",
    "response_json_decode_failed", "response_json_shape_mismatch",
    "badrequesterror",
)


def is_verified_quota_failure(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in QUOTA_MARKERS)


def is_retryable_provider_output(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in RETRYABLE_OUTPUT_MARKERS)


def token_is(value: Any, token: str) -> bool:
    parts = str(value or "").split(":", 2)
    return len(parts) >= 2 and parts[1] == token


def classify_payload(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    if status == "PASS_AI_REVIEW_DECISION_GATE":
        return "ACCEPTED"
    if status == "WAIT_AI_QUOTA_REVIEW":
        wait_codes = [str(value) for value in result.get("wait_codes") or []]
        if wait_codes and all(is_retryable_provider_output(code) for code in wait_codes):
            return "WAIT_PROVIDER_RETRY"
        if wait_codes and all(
            code.endswith("WAIT_NEXT_QUOTA_BATCH") or is_verified_quota_failure(code)
            for code in wait_codes
        ):
            return "WAIT_QUOTA"
        return "BLOCKER"
    if status == "HOLD_AI_REVIEW_DECISION_GATE":
        blockers = [str(value) for value in result.get("blocker_codes") or []]
        if blockers and all(token_is(blocker, "SEMANTIC_REJECT") for blocker in blockers):
            return "SEMANTIC_REJECT"
        if blockers and all(token_is(blocker, "ADVISORY_HOLD") for blocker in blockers):
            return "ADVISORY_HOLD"
        return "BLOCKER"
    return "BLOCKER"


def strict_classify(path: Path) -> str:
    return classify_payload(core.read_json(path))


def classify_for_core(path: Path) -> str:
    state = strict_classify(path)
    if state == "WAIT_PROVIDER_RETRY":
        return "WAIT_QUOTA"
    if state == "ADVISORY_HOLD":
        return "SEMANTIC_REJECT"
    return state


def restore_epoch_state(prior_roots: list[Path], epoch_date: str) -> dict[str, Any]:
    used = 0
    reserved_files: set[str] = set()
    retry_attempts: dict[str, int] = {}
    latest_results: dict[str, dict[str, Any]] = {}
    for root in prior_roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("quota_epoch_reservation.json")):
            try:
                payload = core.read_json(path)
            except Exception:
                continue
            if str(payload.get("quota_epoch_date") or "") != epoch_date:
                continue
            value = int(payload.get("quota_epoch_candidates_used") or 0)
            if not 0 <= value <= MAX_DAILY_CANDIDATES:
                raise ValueError(f"INVALID_QUOTA_EPOCH_USAGE:{path}:{value}")
            used = max(used, value)
            reserved_files.update(map(str, payload.get("quota_epoch_selected_files") or []))
            for name, count in (payload.get("provider_retry_attempts") or {}).items():
                retry_attempts[str(name)] = max(retry_attempts.get(str(name), 0), int(count))
        for path in sorted(root.rglob("*.json")):
            try:
                payload = core.read_json(path)
            except Exception:
                continue
            if payload.get("schema_version") != "strategy11.ai_review_decision_gate.v3":
                continue
            if "__" not in path.stem:
                continue
            latest_results[path.name] = payload
    retryable_files = {
        name for name, payload in latest_results.items()
        if classify_payload(payload) == "WAIT_PROVIDER_RETRY"
    }
    for name in retryable_files:
        reserved_files.add(name)
        retry_attempts[name] = max(retry_attempts.get(name, 0), 1)
    return {
        "used": used,
        "reserved_files": reserved_files,
        "retry_attempts": retry_attempts,
        "retryable_files": retryable_files,
    }


def restore_epoch_usage(prior_roots: list[Path], epoch_date: str) -> int:
    return int(restore_epoch_state(prior_roots, epoch_date)["used"])


def reserve_epoch_usage(
    output_root: Path,
    *,
    epoch_date: str,
    epoch_state: dict[str, Any],
    new_selected: list[Path],
    retry_selected: list[Path],
    max_new_candidates: int,
) -> dict[str, Any]:
    used_before = int(epoch_state["used"])
    used_after = used_before + len(new_selected)
    if used_after > max_new_candidates:
        raise RuntimeError(f"DAILY_CANDIDATE_BUDGET_BREACH:{used_after}:{max_new_candidates}")
    reserved_files = set(map(str, epoch_state["reserved_files"]))
    reserved_files.update(path.name for path in new_selected)
    reserved_files.update(path.name for path in retry_selected)
    retry_attempts = {str(k): int(v) for k, v in epoch_state["retry_attempts"].items()}
    for path in retry_selected:
        retry_attempts[path.name] = retry_attempts.get(path.name, 0) + 1
        if retry_attempts[path.name] > MAX_PROVIDER_RETRY_EPOCHS:
            raise RuntimeError(f"PROVIDER_OUTPUT_RETRY_BUDGET_BREACH:{path.name}:{retry_attempts[path.name]}")
    reservation = {
        "schema_version": "strategy11.generation7.quota_epoch_reservation.v3",
        "version": VERSION,
        "state": "QUOTA_EPOCH_CANDIDATES_RESERVED",
        "quota_epoch_date": epoch_date,
        "quota_epoch_candidates_used_before": used_before,
        "quota_epoch_new_candidate_files": [path.name for path in new_selected],
        "quota_epoch_selected_candidate_count": len(reserved_files),
        "quota_epoch_selected_files": sorted(reserved_files),
        "quota_epoch_candidates_used": used_after,
        "quota_epoch_candidates_remaining": max_new_candidates - used_after,
        "provider_retry_files": [path.name for path in retry_selected],
        "provider_retry_attempts": dict(sorted(retry_attempts.items())),
        "provider_retry_attempt_limit": MAX_PROVIDER_RETRY_EPOCHS,
        **core.SAFETY,
    }
    reservation["reservation_sha"] = core.stable_sha(reservation)
    core.write_json(output_root / "quota_epoch_reservation.json", reservation)
    return reservation


def rewrite_outputs(
    manifest: dict[str, Any],
    output_root: Path,
    ai_root: Path,
    reservation: dict[str, Any],
) -> dict[str, Any]:
    classifications = {path.name: strict_classify(path) for path in sorted(ai_root.glob("*.json"))}
    retry_names = {name for name, state in classifications.items() if state == "WAIT_PROVIDER_RETRY"}
    quota_names = {name for name, state in classifications.items() if state == "WAIT_QUOTA"}
    advisory_names = {name for name, state in classifications.items() if state == "ADVISORY_HOLD"}

    all_wait_rows = list(manifest.get("wait_quota") or [])
    retry_rows = [row for row in all_wait_rows if row.get("file") in retry_names]
    quota_rows = [row for row in all_wait_rows if row.get("file") in quota_names]
    if len(retry_rows) != len(retry_names) or len(quota_rows) != len(quota_names):
        raise RuntimeError("WAIT_STATE_ROW_ACCOUNTING_MISMATCH")

    all_rejected_rows = list(manifest.get("semantic_rejected") or [])
    advisory_rows = [{**row, "state": "ADVISORY_HOLD"} for row in all_rejected_rows if row.get("file") in advisory_names]
    semantic_rows = [row for row in all_rejected_rows if row.get("file") not in advisory_names]
    if len(advisory_rows) != len(advisory_names):
        raise RuntimeError("ADVISORY_HOLD_ROW_ACCOUNTING_MISMATCH")

    advisory_by_strategy: dict[str, list[str]] = {}
    for row in advisory_rows:
        advisory_by_strategy.setdefault(str(row["strategy_id"]), []).append(str(row["candidate_id"]))
    for row in manifest.get("strategy_states") or []:
        strategy_id = str(row["strategy_id"])
        holds = sorted(advisory_by_strategy.get(strategy_id, []))
        if holds:
            row["advisory_held_candidate_ids"] = holds
            row["semantic_rejected_candidate_ids"] = [
                candidate_id for candidate_id in row.get("semantic_rejected_candidate_ids") or []
                if candidate_id not in holds
            ]

    manifest["version"] = VERSION
    manifest["wait_quota"] = quota_rows
    manifest["wait_provider_retry"] = retry_rows
    manifest["wait_quota_count"] = len(quota_rows)
    manifest["wait_provider_retry_count"] = len(retry_rows)
    manifest["semantic_rejected"] = semantic_rows
    manifest["semantic_reject_count"] = len(semantic_rows)
    manifest["advisory_held"] = advisory_rows
    manifest["advisory_hold_count"] = len(advisory_rows)
    if retry_rows:
        manifest["state"] = "WAIT_GENERATION7_PROVIDER_RETRY"
        manifest["next"] = "RETRY_RESERVED_PROVIDER_OUTPUTS"
    elif quota_rows:
        manifest["state"] = "WAIT_GENERATION7_AI_QUOTA"
        manifest["next"] = "WAIT_NEXT_DAILY_QUOTA_EPOCH"
    manifest.update({
        "state_machine_adapter_version": VERSION,
        "quota_epoch_date": reservation["quota_epoch_date"],
        "quota_epoch_candidates_used": reservation["quota_epoch_candidates_used"],
        "quota_epoch_candidates_remaining": reservation["quota_epoch_candidates_remaining"],
        "quota_epoch_selected_files": reservation["quota_epoch_selected_files"],
        "quota_epoch_reservation_sha": reservation["reservation_sha"],
        "provider_retry_attempts": reservation["provider_retry_attempts"],
        "provider_retry_attempt_limit": reservation["provider_retry_attempt_limit"],
    })
    manifest.pop("state_sha", None)
    manifest["state_sha"] = core.stable_sha(manifest)

    accepted_path = output_root / "accepted_plan.json"
    accepted = core.read_json(accepted_path)
    accepted["state"] = manifest["state"] if not manifest["all_candidates_final"] else accepted["state"]
    accepted["ai_wait_quota_count"] = len(quota_rows)
    accepted["ai_wait_provider_retry_count"] = len(retry_rows)
    accepted["ai_semantic_reject_count"] = len(semantic_rows)
    accepted["ai_advisory_hold_count"] = len(advisory_rows)
    accepted["state_machine_adapter_version"] = VERSION
    accepted["quota_epoch_reservation_sha"] = reservation["reservation_sha"]

    ledger_path = output_root / "search_ledger.json"
    ledger = core.read_json(ledger_path)
    retry_by_strategy: dict[str, list[str]] = {}
    for row in retry_rows:
        retry_by_strategy.setdefault(str(row["strategy_id"]), []).append(str(row["candidate_id"]))
    for row in advisory_rows:
        advisory_by_strategy.setdefault(str(row["strategy_id"]), []).append(str(row["candidate_id"]))
    for row in ledger.get("strategy_states") or []:
        strategy_id = str(row["strategy_id"])
        retries = sorted(retry_by_strategy.get(strategy_id, []))
        holds = sorted(advisory_by_strategy.get(strategy_id, []))
        if retries:
            row["wait_provider_retry_candidate_ids"] = retries
            row["wait_quota_candidate_ids"] = [
                candidate_id for candidate_id in row.get("wait_quota_candidate_ids") or []
                if candidate_id not in retries
            ]
            row["state"] = "WAIT_PROVIDER_RETRY"
        if holds:
            row["advisory_held_candidate_ids"] = holds
            row["semantic_rejected_candidate_ids"] = [
                candidate_id for candidate_id in row.get("semantic_rejected_candidate_ids") or []
                if candidate_id not in holds
            ]
    for row in ledger.get("rows") or []:
        strategy_id = str(row["strategy_id"])
        retries = sorted(retry_by_strategy.get(strategy_id, []))
        holds = sorted(advisory_by_strategy.get(strategy_id, []))
        if retries:
            row["rejection_reason"] = ";".join(f"{candidate_id}:WAIT_PROVIDER_OUTPUT_RETRY" for candidate_id in retries)
            row["next_axis"] = "WAIT_PROVIDER_RETRY"
        elif holds:
            reason = str(row.get("rejection_reason") or "")
            for candidate_id in holds:
                reason = reason.replace(f"{candidate_id}:AI_SEMANTIC_REJECT", f"{candidate_id}:AI_ADVISORY_HOLD")
            row["rejection_reason"] = reason
    ledger["ai_wait_quota_count"] = len(quota_rows)
    ledger["ai_wait_provider_retry_count"] = len(retry_rows)
    ledger["ai_semantic_reject_count"] = len(semantic_rows)
    ledger["ai_advisory_hold_count"] = len(advisory_rows)
    ledger["state_machine_adapter_version"] = VERSION
    ledger["quota_epoch_reservation_sha"] = reservation["reservation_sha"]

    core.write_json(output_root / "ai_manifest.json", manifest)
    core.write_json(accepted_path, accepted)
    core.write_json(ledger_path, ledger)
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
    plan, causes, ledger = core.build_payloads(args.plan_root, args.payload_root)
    args.ai_root.mkdir(parents=True, exist_ok=True)
    prior_roots = list(args.prior_root)
    for payload in sorted(args.payload_root.glob("*.json")):
        core.run_router(args.router, args.policy, payload, args.ai_root / payload.name, prior_roots, cache_only=True)

    epoch_state = restore_epoch_state(prior_roots, epoch_date)
    remaining_budget = max(0, args.max_new_candidates - int(epoch_state["used"]))
    result_paths = {path.name: path for path in sorted(args.ai_root.glob("*.json"))}
    retry_selected = [
        result_paths[name] for name in sorted(epoch_state["retryable_files"])
        if name in result_paths
        and name in epoch_state["reserved_files"]
        and int(epoch_state["retry_attempts"].get(name, 0)) < MAX_PROVIDER_RETRY_EPOCHS
    ]
    exhausted = sorted(
        name for name in epoch_state["retryable_files"]
        if int(epoch_state["retry_attempts"].get(name, 0)) >= MAX_PROVIDER_RETRY_EPOCHS
    )
    if exhausted:
        core.write_json(args.output_root / "provider_retry_exhausted.json", {
            "state": "HOLD_PROVIDER_OUTPUT_RETRY_EXHAUSTED",
            "files": exhausted,
            "provider_retry_attempt_limit": MAX_PROVIDER_RETRY_EPOCHS,
            **core.SAFETY,
        })
        raise RuntimeError(f"PROVIDER_OUTPUT_RETRY_EXHAUSTED:{len(exhausted)}")

    quota_waiting = [
        path for path in result_paths.values()
        if strict_classify(path) == "WAIT_QUOTA" and path.name not in epoch_state["reserved_files"]
    ]
    new_selected = quota_waiting[:remaining_budget]
    reservation = reserve_epoch_usage(
        args.output_root,
        epoch_date=epoch_date,
        epoch_state=epoch_state,
        new_selected=new_selected,
        retry_selected=retry_selected,
        max_new_candidates=args.max_new_candidates,
    )

    live_prior = [*prior_roots, args.ai_root]
    for result_path in [*retry_selected, *new_selected]:
        payload = args.payload_root / result_path.name
        core.run_router(args.router, args.policy, payload, result_path, live_prior, cache_only=False)

    final_retry_failures = sorted(
        path.name for path in retry_selected
        if strict_classify(path) == "WAIT_PROVIDER_RETRY"
        and int(reservation["provider_retry_attempts"].get(path.name, 0)) >= MAX_PROVIDER_RETRY_EPOCHS
    )
    if final_retry_failures:
        core.write_json(args.output_root / "provider_retry_exhausted.json", {
            "state": "HOLD_PROVIDER_OUTPUT_RETRY_EXHAUSTED",
            "files": final_retry_failures,
            "provider_retry_attempts": reservation["provider_retry_attempts"],
            "provider_retry_attempt_limit": MAX_PROVIDER_RETRY_EPOCHS,
            **core.SAFETY,
        })
        raise RuntimeError(f"PROVIDER_OUTPUT_RETRY_EXHAUSTED:{len(final_retry_failures)}")

    core.classify = classify_for_core
    manifest = core.finalize(plan, causes, ledger, args.ai_root, args.output_root, args.max_new_candidates)
    manifest = rewrite_outputs(manifest, args.output_root, args.ai_root, reservation)
    print(
        manifest["state"],
        "pass=", manifest["pass_count"],
        "reject=", manifest["semantic_reject_count"],
        "hold=", manifest["advisory_hold_count"],
        "quota_wait=", manifest["wait_quota_count"],
        "provider_retry=", manifest["wait_provider_retry_count"],
        "epoch_used=", manifest["quota_epoch_candidates_used"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
