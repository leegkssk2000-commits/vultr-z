#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "config" / "zel_alpha_engine_vnext.json"
EXPECTED_ENGINE_ORDER = [
    "market_data",
    "alpha_engine",
    "regime_router",
    "entry_qualifier",
    "risk_exit",
    "execution",
    "portfolio",
    "bots_skills_advisor",
    "shadow",
    "paper",
    "live",
]
EXPECTED_ALPHA_FAMILIES = [
    "trend_momentum",
    "carry_flow",
    "relative_value_psa",
]


def load_policy(path: Path = DEFAULT_POLICY) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_policy(policy: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if policy.get("state") != "ALPHA_FIRST_LOCK":
        errors.append("state must be ALPHA_FIRST_LOCK")
    if policy.get("engine_order") != EXPECTED_ENGINE_ORDER:
        errors.append("engine_order does not match canonical ZEL vNext order")

    alpha_engine = policy.get("alpha_engine")
    if not isinstance(alpha_engine, Mapping):
        errors.append("alpha_engine section missing")
    elif alpha_engine.get("allowlist") != EXPECTED_ALPHA_FAMILIES:
        errors.append("alpha allowlist must contain exactly the three canonical families")

    objective = policy.get("objective")
    if not isinstance(objective, Mapping):
        errors.append("objective section missing")
    else:
        if objective.get("win_rate") != "RANK_ONLY":
            errors.append("win_rate must be RANK_ONLY")
        if objective.get("win_rate_improvement_required_for_pass") is not False:
            errors.append("win-rate improvement must not be a PASS gate")
        if objective.get("tp_sl_exit_optimization_before_positive_forward_alpha_edge") != "FORBIDDEN":
            errors.append("exit optimization must stay forbidden before positive forward alpha edge")

    if policy.get("promotion_authority") != "DETERMINISTIC_GATE_ONLY":
        errors.append("promotion authority must be deterministic-gate-only")
    return errors


def _normalize_repo_path(path: str) -> str:
    if path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def _is_allowed(path: str, allowed_prefixes: Sequence[str]) -> bool:
    normalized = _normalize_repo_path(path)
    for prefix in allowed_prefixes:
        normalized_prefix = _normalize_repo_path(prefix)
        if normalized_prefix.endswith("/"):
            if normalized.startswith(normalized_prefix):
                return True
        elif normalized == normalized_prefix:
            return True
    return False


def path_violations(changed_files: Iterable[str], policy: Mapping[str, object]) -> list[str]:
    lock = policy.get("zero_survivor_change_lock")
    if not isinstance(lock, Mapping) or not lock.get("enabled"):
        return []
    if int(policy.get("seed_survivor_count", 0)) > 0:
        return []

    allowed = lock.get("allowed_prefixes")
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        return ["<policy-error: allowed_prefixes missing>"]
    return sorted({p for p in changed_files if p and not _is_allowed(p, allowed)})


def objective_verdict(metrics: Mapping[str, object]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if metrics.get("integrity_ok") is not True:
        failures.append("integrity_ok")

    try:
        if float(metrics.get("oos_net_pnl", 0.0)) <= 0.0:
            failures.append("oos_net_pnl_positive")
    except (TypeError, ValueError):
        failures.append("oos_net_pnl_positive")

    try:
        if float(metrics.get("oos_expectancy", 0.0)) <= 0.0:
            failures.append("oos_expectancy_positive")
    except (TypeError, ValueError):
        failures.append("oos_expectancy_positive")

    if metrics.get("dd_within_ssot") is not True:
        failures.append("dd_within_ssot")

    # Win rate is intentionally not a PASS gate. It may be used for ranking only.
    return (not failures, failures)


def git_changed_files(base: str, head: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZEL ALPHA_FIRST_LOCK policy guard")
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--files", nargs="*")
    parser.add_argument("--candidate-json", type=Path)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    errors = validate_policy(policy)
    if errors:
        for error in errors:
            print(f"POLICY_FAIL: {error}", file=sys.stderr)
        return 2

    changed_files: list[str] = []
    if args.files is not None:
        changed_files = list(args.files)
    elif args.base and args.head:
        changed_files = git_changed_files(args.base, args.head)

    violations = path_violations(changed_files, policy)
    if violations:
        for path in violations:
            print(f"ALPHA_FIRST_LOCK_BLOCK: {path}", file=sys.stderr)
        return 3

    if args.candidate_json:
        with args.candidate_json.open("r", encoding="utf-8") as fh:
            metrics = json.load(fh)
        passed, failures = objective_verdict(metrics)
        if not passed:
            print("OBJECTIVE_HOLD: " + ",".join(failures), file=sys.stderr)
            return 4

    print("ALPHA_FIRST_LOCK_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
