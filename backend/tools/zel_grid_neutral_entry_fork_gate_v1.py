from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Mapping

VERSION = "ZEL_GRID_NEUTRAL_ENTRY_FORK_GATE_V2"
SCHEMA = "zel.grid_neutral.entry_fork_gate.receipt.v2"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def close(a: Any, b: Any, tolerance: float = 1e-9) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)


def metrics_match(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return (
        int(actual.get("trade_count") or 0) == int(expected.get("trade_count") or 0)
        and close(actual.get("net_R"), expected.get("net_R"))
        and close(actual.get("profit_factor"), expected.get("profit_factor"))
        and close(actual.get("max_drawdown_R"), expected.get("max_drawdown_R"))
    )


def evaluate(
    *,
    policy: Mapping[str, Any],
    semantic: Mapping[str, Any],
    source_root: Path,
    canonical_source_sha256: str | None = None,
) -> dict[str, Any]:
    source = source_root / str(policy["canonical_source_path"])
    local_exists = source.is_file()
    actual_source_sha = canonical_source_sha256.strip() if canonical_source_sha256 else file_sha(source) if local_exists else None
    source_proved = bool(actual_source_sha)
    entry = semantic.get("entry_range_metrics") if isinstance(semantic.get("entry_range_metrics"), Mapping) else {}
    exit_reference = semantic.get("exit_neutral_metrics") if isinstance(semantic.get("exit_neutral_metrics"), Mapping) else {}
    checks = {
        "source_digest_proved": source_proved,
        "source_sha_match": actual_source_sha == policy["canonical_source_sha256"],
        "semantic_state_match": semantic.get("state") == policy["required_semantic_state"],
        "reconstruction_state_match": semantic.get("reconstruction_state") == policy["required_reconstruction_state"],
        "trade_count_match": int(semantic.get("trade_count") or 0) == int(policy["expected_trade_count"]),
        "entry_range_metrics_match": metrics_match(entry, policy["entry_range_metrics"]),
        "exit_neutral_reference_match": metrics_match(exit_reference, policy["exit_neutral_reference"]),
        "economic_gate_false": semantic.get("economic_gate_pass") is policy["required_economic_gate_pass"],
        "fork_blocked_true": semantic.get("fork_blocked") is policy["required_fork_blocked"],
        "tmp_fork_false": semantic.get("tmp_fork_stage_allowed") is policy["required_tmp_fork_stage_allowed"],
        "execution_none": semantic.get("execution_authority") == "NONE",
        "order_blocked": semantic.get("order_authority") == "BLOCKED",
        "canonical_unchanged": semantic.get("canonical_mutated") is False,
        "runtime_unchanged": semantic.get("runtime_mutated") is False,
        "formal_ledger_unchanged": semantic.get("formal_ledger_mutated") is False,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    verified = not blockers
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_GRID_NEUTRAL_ENTRY_FORK_BLOCKED" if verified else "HOLD_GRID_NEUTRAL_ENTRY_FORK_GATE_INTEGRITY",
        "strategy_id": policy["strategy_id"],
        "checks": checks,
        "blockers": blockers,
        "canonical_source_sha256": actual_source_sha,
        "source_bytes_copied": False,
        "semantic_summary_sha256": stable_sha(semantic),
        "entry_range_metrics": dict(entry),
        "exit_neutral_reference": dict(exit_reference),
        "economic_gate_pass": False,
        "fork_blocked": True,
        "tmp_fork_allowed": False,
        "existing_ledger_regime_causal": False,
        "entry_time_reconstruction_complete": semantic.get("reconstruction_state") == policy["required_reconstruction_state"],
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "RETURN_TO_STRATEGY_LOSS_QUEUE" if verified else "RESOLVE_GATE_INTEGRITY_BLOCKERS",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "backend/strategies/grid_rebalance.py"
        source.parent.mkdir(parents=True)
        source.write_text("grid\n", encoding="utf-8")
        policy = {
            "strategy_id": "grid_rebalance",
            "canonical_source_path": "backend/strategies/grid_rebalance.py",
            "canonical_source_sha256": file_sha(source),
            "required_semantic_state": "PASS_GRID_NEUTRAL_SEMANTIC_CORRECTION_FORK_BLOCKED",
            "required_reconstruction_state": "PASS_GRID_ENTRY_REGIME_RECONSTRUCTED",
            "expected_trade_count": 580,
            "entry_range_metrics": {"trade_count": 11, "net_R": -2.0, "profit_factor": 0.5, "max_drawdown_R": -4.0},
            "exit_neutral_reference": {"trade_count": 248, "net_R": 64.0, "profit_factor": 3.0, "max_drawdown_R": -5.0},
            "required_economic_gate_pass": False,
            "required_fork_blocked": True,
            "required_tmp_fork_stage_allowed": False,
        }
        semantic = {
            "state": policy["required_semantic_state"],
            "reconstruction_state": policy["required_reconstruction_state"],
            "trade_count": 580,
            "entry_range_metrics": policy["entry_range_metrics"],
            "exit_neutral_metrics": policy["exit_neutral_reference"],
            "economic_gate_pass": False,
            "fork_blocked": True,
            "tmp_fork_stage_allowed": False,
            "canonical_mutated": False,
            "runtime_mutated": False,
            "formal_ledger_mutated": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
        }
        passed = evaluate(policy=policy, semantic=semantic, source_root=root)
        assert passed["state"] == "PASS_GRID_NEUTRAL_ENTRY_FORK_BLOCKED", passed
        digest_only = evaluate(
            policy=policy,
            semantic=semantic,
            source_root=root / "missing",
            canonical_source_sha256=policy["canonical_source_sha256"],
        )
        assert digest_only["state"] == "PASS_GRID_NEUTRAL_ENTRY_FORK_BLOCKED", digest_only
        tampered = dict(semantic)
        tampered["tmp_fork_stage_allowed"] = True
        failed = evaluate(policy=policy, semantic=tampered, source_root=root)
        assert failed["state"] == "HOLD_GRID_NEUTRAL_ENTRY_FORK_GATE_INTEGRITY", failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--semantic-summary", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--canonical-source-sha256")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("PASS_GRID_NEUTRAL_ENTRY_FORK_GATE_SELF_TEST")
        return 0
    if not args.policy or not args.semantic_summary:
        raise SystemExit("--policy and --semantic-summary required")
    receipt = evaluate(
        policy=read_object(args.policy),
        semantic=read_object(args.semantic_summary),
        source_root=args.source_root.resolve(),
        canonical_source_sha256=args.canonical_source_sha256,
    )
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["state"] == "PASS_GRID_NEUTRAL_ENTRY_FORK_BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
