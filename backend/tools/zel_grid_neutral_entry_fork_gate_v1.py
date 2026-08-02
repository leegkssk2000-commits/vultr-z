from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_GRID_NEUTRAL_ENTRY_FORK_GATE_V1"
SCHEMA = "zel.grid_neutral.entry_fork_gate.receipt.v1"


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def num(row: Mapping[str, Any], keys: Sequence[str]) -> float:
    for key in keys:
        value = row.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return 0.0


def text(row: Mapping[str, Any], keys: Sequence[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def max_drawdown(values: Sequence[float]) -> float:
    equity = peak = worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [num(row, ("realized_R", "net_R", "pnl_r", "net_reference_R")) for row in rows]
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    return {
        "trade_count": len(rows),
        "net_R": sum(values),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "max_drawdown_R": max_drawdown(values),
    }


def read_grid_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[arg-type]
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, Mapping):
                raise RuntimeError(f"ROW_NOT_OBJECT:{line_no}")
            if text(row, ("strategy_id", "strategy", "strategy_name")) == "grid_rebalance":
                rows.append(dict(row))
    return rows


def close(a: Any, b: Any, tolerance: float = 1e-9) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)


def evaluate(*, policy: Mapping[str, Any], trades: Path, source_root: Path) -> dict[str, Any]:
    rows = read_grid_rows(trades)
    neutral = [row for row in rows if text(row, ("regime", "market_regime"), "unknown") == "neutral"]
    windows = Counter(text(row, ("window_id", "window"), "unknown") for row in neutral)
    all_ids = sorted(text(row, ("event_id", "trade_id", "position_id")) for row in rows)
    neutral_ids = sorted(text(row, ("event_id", "trade_id", "position_id")) for row in neutral)
    neutral_metrics = metrics(neutral)
    source = source_root / str(policy["canonical_source_path"])

    checks = {
        "source_exists": source.is_file(),
        "source_sha_match": source.is_file() and file_sha(source) == policy["canonical_source_sha256"],
        "trade_count_match": len(rows) == int(policy["expected_trade_count"]),
        "neutral_trade_count_match": len(neutral) == int(policy["expected_neutral_trade_count"]),
        "window_counts_match": dict(sorted(windows.items())) == dict(sorted(policy["expected_window_neutral_trade_counts"].items())),
        "all_event_digest_match": stable_sha(all_ids) == policy["event_id_set_sha256"],
        "neutral_event_digest_match": stable_sha(neutral_ids) == policy["neutral_event_id_set_sha256"],
        "neutral_net_R_match": close(neutral_metrics["net_R"], policy["neutral_metrics"]["net_R"]),
        "neutral_profit_factor_match": close(neutral_metrics["profit_factor"], policy["neutral_metrics"]["profit_factor"]),
        "neutral_max_drawdown_match": close(neutral_metrics["max_drawdown_R"], policy["neutral_metrics"]["max_drawdown_R"]),
        "existing_ledger_regime_causal_false": policy.get("existing_ledger_regime_causal") is False,
        "entry_time_reconstruction_required": policy.get("entry_time_reconstruction_required") is True,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    parity_pass = not blockers
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "state": "PASS_GRID_NEUTRAL_ENTRY_FORK_GATE_READY" if parity_pass else "HOLD_GRID_NEUTRAL_ENTRY_FORK_GATE",
        "strategy_id": "grid_rebalance",
        "checks": checks,
        "blockers": blockers,
        "trade_count": len(rows),
        "neutral_trade_count": len(neutral),
        "neutral_window_counts": dict(sorted(windows.items())),
        "neutral_metrics": neutral_metrics,
        "event_id_set_sha256": stable_sha(all_ids),
        "neutral_event_id_set_sha256": stable_sha(neutral_ids),
        "canonical_source_sha256": file_sha(source) if source.is_file() else None,
        "existing_ledger_regime_causal": False,
        "entry_time_reconstruction_required": True,
        "tmp_fork_allowed": parity_pass,
        "incumbent_mutation_allowed": False,
        "raw_trade_rows_published": False,
        "raw_event_ids_published": False,
        "process_arguments_published": False,
        "credentials_published": False,
        "canonical_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "RECONSTRUCT_REGIME_AT_ENTRY_TIMESTAMP_IN_TMP_FORK" if parity_pass else "RESOLVE_SINGLE_PARITY_BLOCKER",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = root / "backend/strategies/grid_rebalance.py"
        source.parent.mkdir(parents=True)
        source.write_text("def decide(): return None\n")
        rows = [
            {"strategy_id": "grid_rebalance", "event_id": "a", "window_id": "1m_w1", "regime": "neutral", "realized_R": 2.0},
            {"strategy_id": "grid_rebalance", "event_id": "b", "window_id": "1m_w2", "regime": "neutral", "realized_R": -1.0},
        ]
        trades = root / "trades.jsonl"
        trades.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        m = metrics(rows)
        policy = {
            "canonical_source_path": "backend/strategies/grid_rebalance.py",
            "canonical_source_sha256": file_sha(source),
            "expected_trade_count": 2,
            "expected_neutral_trade_count": 2,
            "expected_window_neutral_trade_counts": {"1m_w1": 1, "1m_w2": 1},
            "neutral_metrics": m,
            "event_id_set_sha256": stable_sha(["a", "b"]),
            "neutral_event_id_set_sha256": stable_sha(["a", "b"]),
            "existing_ledger_regime_causal": False,
            "entry_time_reconstruction_required": True,
        }
        receipt = evaluate(policy=policy, trades=trades, source_root=root)
        assert receipt["state"] == "PASS_GRID_NEUTRAL_ENTRY_FORK_GATE_READY", receipt
        assert receipt["tmp_fork_allowed"] is True
        assert receipt["process_arguments_published"] is False
        policy["neutral_metrics"] = dict(m, net_R=999.0)
        held = evaluate(policy=policy, trades=trades, source_root=root)
        assert held["state"] == "HOLD_GRID_NEUTRAL_ENTRY_FORK_GATE", held
        assert "neutral_net_R_match" in held["blockers"]
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--trades", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.policy or not args.trades or not args.source_root:
        parser.error("--policy, --trades and --source-root are required")
    policy = json.loads(args.policy.read_text())
    receipt = evaluate(policy=policy, trades=args.trades, source_root=args.source_root)
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded)
    if args.stdout or not args.out:
        print(encoded, end="")
    return 0 if receipt["tmp_fork_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
