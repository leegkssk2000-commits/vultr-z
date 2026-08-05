from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_LICO_CRYPTO_FLOW_CUMULATIVE_V2"
SCHEMA = "zel.lico.crypto_flow.cumulative.effectiveness.v2"
WINDOW_ORDER = {"W1": 0, "W2": 1, "W3": 2, "UNKNOWN": 9}


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def read_rows(path: Path) -> list[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    rows: list[dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise RuntimeError(f"ROW_NOT_OBJECT:{path}:{line_number}")
            rows.append(value)
    return rows


def write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True, allow_nan=False) + "\n")


def strategy_id(row: Mapping[str, Any]) -> str:
    return str(row.get("strategy_id") or row.get("strategy") or row.get("strategy_name") or "")


def identity(row: Mapping[str, Any]) -> str:
    return str(row.get("event_id") or row.get("position_id") or row.get("trade_id") or "")


def sort_rows(rows: Sequence[Mapping[str, Any]], lico: Any) -> list[dict[str, Any]]:
    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        window = lico.normalize_window(lico.nested_value(row, lico.WINDOW_FIELDS))
        try:
            entry = lico.parse_timestamp_ms(lico.nested_value(row, lico.ENTRY_TS_FIELDS))
        except Exception:
            entry = 2**63 - 1
        try:
            exit_value = lico.parse_timestamp_ms(lico.nested_value(row, ("exit_ts", "exit_time", "closed_at", "close_ts")))
        except Exception:
            exit_value = 2**63 - 1
        return (WINDOW_ORDER.get(window, 9), entry, exit_value, strategy_id(row), identity(row))

    return [dict(row) for row in sorted(rows, key=key)]


def metric_delta(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trade_count": int(candidate["trade_count"]) - int(base["trade_count"]),
        "net_R": float(candidate["net_R"]) - float(base["net_R"]),
        "profit_factor": float(candidate["profit_factor"]) - float(base["profit_factor"]),
        "expectancy_R": float(candidate["expectancy_R"]) - float(base["expectancy_R"]),
        "payoff_ratio": float(candidate["payoff_ratio"]) - float(base["payoff_ratio"]),
        "win_rate_pct_points": float(candidate["win_rate_pct"]) - float(base["win_rate_pct"]),
        "max_drawdown_R_improvement": float(base["max_drawdown_R"]) - float(candidate["max_drawdown_R"]),
    }


def verify_receipt_hash(receipt: Mapping[str, Any], stable_sha: Any) -> bool:
    expected = str(receipt.get("receipt_sha256") or "")
    material = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return bool(expected) and stable_sha(material) == expected


def build(
    *,
    cumulative_contract_path: Path,
    lico_contract_path: Path,
    raw_terminal_path: Path,
    grid_candidate_path: Path,
    grid_receipt_path: Path,
    lico_engine_path: Path,
    grid_tool_path: Path,
    out_path: Path,
) -> dict[str, Any]:
    cumulative_contract = read_json(cumulative_contract_path)
    base_lico_contract = read_json(lico_contract_path)
    grid_receipt = read_json(grid_receipt_path)
    lico = load_module(lico_engine_path, f"zel_lico_cumulative_engine_{os.getpid()}")
    grid = load_module(grid_tool_path, f"zel_lico_cumulative_grid_{os.getpid()}")

    raw_rows = read_rows(raw_terminal_path)
    candidate_grid_rows = read_rows(grid_candidate_path)
    raw_sha = lico.file_sha(raw_terminal_path)
    expected_raw_sha = str(cumulative_contract["raw_terminal"]["sha256"])
    expected_raw_count = int(cumulative_contract["raw_terminal"]["trade_count"])
    expected_grid_count = int(cumulative_contract["incumbent"]["raw_grid_trade_count"])
    raw_grid_rows = [row for row in raw_rows if strategy_id(row) == "grid_rebalance"]
    non_grid_rows = [row for row in raw_rows if strategy_id(row) != "grid_rebalance"]

    grid_candidate_digest = grid.economic_digest(candidate_grid_rows)
    grid_checks = {
        "raw_terminal_sha_match": raw_sha == expected_raw_sha,
        "raw_terminal_count_match": len(raw_rows) == expected_raw_count,
        "raw_grid_count_match": len(raw_grid_rows) == expected_grid_count,
        "grid_receipt_state_pass": grid_receipt.get("state") == "PASS_GRID_CUMULATIVE_INCUMBENT_MATERIALIZED",
        "grid_receipt_hash_valid": verify_receipt_hash(grid_receipt, grid.stable_sha),
        "grid_candidate_pass": grid_receipt.get("candidate_pass") is True,
        "grid_baseline_parity_all": all((grid_receipt.get("baseline_parity") or {}).values()),
        "grid_candidate_checks_all": all((grid_receipt.get("candidate_checks") or {}).values()),
        "grid_censored_zero": int(grid_receipt.get("baseline_censored_open_count") or 0) == 0 and int(grid_receipt.get("candidate_censored_open_count") or 0) == 0,
        "grid_candidate_digest_match": grid_candidate_digest == grid_receipt.get("candidate_economic_digest_sha256"),
        "grid_candidate_file_sha_match": lico.file_sha(grid_candidate_path) == grid_receipt.get("private_candidate_rows_sha256"),
    }
    if not all(grid_checks.values()):
        raise RuntimeError("CUMULATIVE_GRID_LINEAGE_FAILED:" + json.dumps(grid_checks, sort_keys=True))

    cumulative_rows = sort_rows([*non_grid_rows, *candidate_grid_rows], lico)
    raw_sorted = sort_rows(raw_rows, lico)
    cumulative_identity = [identity(row) for row in cumulative_rows]
    cumulative_checks = {
        "non_grid_count_preserved": len(non_grid_rows) == expected_raw_count - expected_grid_count,
        "candidate_grid_count_match_receipt": len(candidate_grid_rows) == int(grid_receipt["candidate_grid_trade_count"]),
        "cumulative_count_equation": len(cumulative_rows) == len(non_grid_rows) + len(candidate_grid_rows),
        "cumulative_identity_missing_zero": all(cumulative_identity),
        "cumulative_duplicate_zero": len(cumulative_identity) == len(set(cumulative_identity)),
        "raw_grid_rows_removed": sum(1 for row in cumulative_rows if strategy_id(row) == "grid_rebalance") == len(candidate_grid_rows),
    }
    if not all(cumulative_checks.values()):
        raise RuntimeError("CUMULATIVE_LEDGER_BUILD_FAILED:" + json.dumps(cumulative_checks, sort_keys=True))

    raw_normalized, raw_integrity = lico.load_trades(raw_terminal_path)
    raw_metrics = {window: lico.metrics([row for row in raw_normalized if row["window"] == window]) for window in ("W1", "W2", "W3")}
    raw_metrics["ALL"] = lico.metrics(raw_normalized)

    with tempfile.TemporaryDirectory(prefix="zel-lico-cumulative-v2-") as temp_dir:
        temp = Path(temp_dir)
        private_cumulative_path = temp / "cumulative.jsonl.gz"
        effective_contract_path = temp / "effective_contract.json"
        effect_path = temp / "effect.json"
        write_rows(private_cumulative_path, cumulative_rows)
        effective_contract = json.loads(json.dumps(base_lico_contract))
        effective_contract["evaluation"]["expected_terminal_trade_count"] = len(cumulative_rows)
        effective_contract["cumulative_lineage"] = {
            "raw_terminal_sha256": raw_sha,
            "grid_candidate_digest_sha256": grid_candidate_digest,
            "grid_materializer_receipt_sha256": grid_receipt["receipt_sha256"],
            "ordering_policy": "WINDOW_ENTRY_EXIT_STRATEGY_IDENTITY",
        }
        effective_contract_path.write_text(json.dumps(effective_contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        effect = lico.run(effective_contract_path, private_cumulative_path, effect_path)
        private_cumulative_sha = lico.file_sha(private_cumulative_path)

    if not str(effect.get("state") or "").startswith("PASS_LICO_CRYPTO_FLOW_"):
        raise RuntimeError(f"CUMULATIVE_LICO_EFFECT_NOT_ACCEPTED:{effect.get('state')}")
    effectiveness = effect.get("effectiveness")
    if not isinstance(effectiveness, Mapping):
        raise RuntimeError("CUMULATIVE_EFFECTIVENESS_MISSING")
    cumulative_baseline = effectiveness["baseline"]
    selected = effectiveness.get("selected")
    selected_all = selected.get("all") if isinstance(selected, Mapping) else None
    survivor = effectiveness.get("survivor") is True

    if survivor:
        state = "PASS_LICO_CRYPTO_CUMULATIVE_VALIDATED_SURVIVOR"
    elif selected is not None:
        state = "PASS_LICO_CRYPTO_CUMULATIVE_BOUND_NO_VALID_SURVIVOR"
    else:
        state = "PASS_LICO_CRYPTO_CUMULATIVE_NO_W1_ELIGIBLE_FILTER"

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": lico.now_iso(),
        "state": state,
        "lineage": {
            "issue": 581,
            "parent_pr": 580,
            "incumbent_pr": 550,
            "raw_terminal_sha256": raw_sha,
            "raw_terminal_trade_count": len(raw_rows),
            "raw_grid_trade_count": len(raw_grid_rows),
            "candidate_grid_trade_count": len(candidate_grid_rows),
            "cumulative_trade_count": len(cumulative_rows),
            "private_cumulative_ledger_sha256": private_cumulative_sha,
            "grid_materializer_receipt_sha256": grid_receipt["receipt_sha256"],
            "grid_candidate_economic_digest_sha256": grid_candidate_digest,
            "lico_market_dataset_sha256": effect["source"]["dataset_sha256"],
        },
        "grid_checks": grid_checks,
        "cumulative_checks": cumulative_checks,
        "raw_integrity": raw_integrity,
        "raw_portfolio_baseline": raw_metrics,
        "cumulative_incumbent_baseline": cumulative_baseline,
        "raw_to_cumulative_delta": {window: metric_delta(raw_metrics[window], cumulative_baseline[window]) for window in ("W1", "W2", "W3", "ALL")},
        "lico_incremental_effectiveness": effectiveness,
        "selected_config_id": effectiveness.get("selected_config_id"),
        "selected_frozen_w2_w3": effectiveness.get("selected_frozen_w2_w3") is True,
        "selected_all": selected_all,
        "survivor": survivor,
        "survivor_blockers": effectiveness.get("survivor_blockers") or [],
        "binding": effect["binding"],
        "flow_snapshot_count": effect["flow_snapshot_count"],
        "source": effect["source"],
        "comparison_authority": "CUMULATIVE_INCUMBENT_VS_CUMULATIVE_PLUS_LICO_ONLY",
        "raw_minus_746_used_as_incremental_baseline": False,
        "future_mfe_mae_used": False,
        "entry_time_asof_only": True,
        "raw_trade_rows_published": False,
        "private_candidate_rows_published": False,
        "private_cumulative_rows_published": False,
        "strategy_rules_mutated": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "shadow_mutated": False,
        "paper_mutated": False,
        "live_mutated": False,
        "protected_mutations": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": "PRESERVE_CUMULATIVE_LICO_INTERACTION" if survivor else "PRESERVE_DIAGNOSTIC_AND_TEST_STRATEGY_CONDITIONAL_FLOW",
    }
    receipt["receipt_sha256"] = lico.stable_sha(receipt)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def self_test() -> int:
    base = {"trade_count": 10, "net_R": -5.0, "profit_factor": 0.5, "expectancy_R": -0.5, "payoff_ratio": 0.8, "win_rate_pct": 40.0, "max_drawdown_R": 7.0}
    candidate = {"trade_count": 8, "net_R": -2.0, "profit_factor": 0.8, "expectancy_R": -0.25, "payoff_ratio": 0.9, "win_rate_pct": 50.0, "max_drawdown_R": 4.0}
    delta = metric_delta(base, candidate)
    assert delta["net_R"] == 3.0
    assert delta["max_drawdown_R_improvement"] == 3.0
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cumulative-contract", type=Path)
    parser.add_argument("--lico-contract", type=Path)
    parser.add_argument("--raw-terminal", type=Path)
    parser.add_argument("--grid-candidate", type=Path)
    parser.add_argument("--grid-receipt", type=Path)
    parser.add_argument("--lico-engine", type=Path)
    parser.add_argument("--grid-tool", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.cumulative_contract,
        args.lico_contract,
        args.raw_terminal,
        args.grid_candidate,
        args.grid_receipt,
        args.lico_engine,
        args.grid_tool,
        args.out,
    )
    if any(value is None for value in required):
        parser.error("all runtime arguments required")
    receipt = build(
        cumulative_contract_path=args.cumulative_contract.resolve(),
        lico_contract_path=args.lico_contract.resolve(),
        raw_terminal_path=args.raw_terminal.resolve(),
        grid_candidate_path=args.grid_candidate.resolve(),
        grid_receipt_path=args.grid_receipt.resolve(),
        lico_engine_path=args.lico_engine.resolve(),
        grid_tool_path=args.grid_tool.resolve(),
        out_path=args.out.resolve(),
    )
    print(json.dumps({"state": receipt["state"], "selected_config_id": receipt["selected_config_id"], "survivor": receipt["survivor"], "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
