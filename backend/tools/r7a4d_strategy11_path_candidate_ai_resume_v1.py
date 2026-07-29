from __future__ import annotations

import argparse
from pathlib import Path

from backend.tools.r7a4d_strategy11_generation7_quota_state_machine_v1 import classify, run_router
from backend.tools.r7a4d_strategy11_path_candidate_state_v1 import filter_reviews
from backend.tools.r7a4d_strategy11_generation7_quota_state_machine_v1 import read_json

VERSION = "R7A4D_STRATEGY11_PATH_CANDIDATE_AI_RESUME_V1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--ai-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--router", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--prior-root", type=Path, action="append", default=[])
    parser.add_argument("--max-new-candidates", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.max_new_candidates <= 10:
        raise SystemExit("MAX_NEW_CANDIDATES_MUST_BE_1_TO_10")
    prepared = read_json(args.prepared)
    args.ai_root.mkdir(parents=True, exist_ok=True)
    prior_roots = list(args.prior_root)
    for payload in sorted(args.payload_root.glob("*.json")):
        run_router(
            args.router,
            args.policy,
            payload,
            args.ai_root / payload.name,
            prior_roots,
            cache_only=True,
        )
    unresolved = [path for path in sorted(args.ai_root.glob("*.json")) if classify(path) == "WAIT_QUOTA"]
    selected = unresolved[: args.max_new_candidates]
    live_prior = [*prior_roots, args.ai_root]
    for result_path in selected:
        run_router(
            args.router,
            args.policy,
            args.payload_root / result_path.name,
            result_path,
            live_prior,
            cache_only=False,
        )
    result = filter_reviews(prepared, args.ai_root, args.output_root)
    print(
        result["state"],
        "accepted=", result["accepted_count"],
        "reject=", result["semantic_reject_count"],
        "wait=", result["wait_quota_count"],
        "unsupported=", result["unsupported_count"],
    )
    return 1 if str(result["state"]).startswith("HOLD_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
