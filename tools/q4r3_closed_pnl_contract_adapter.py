from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
RUNTIME = ROOT / "runtime"
WORKTREE = Path(os.environ.get("Q4R3_ROUTE_A_WORKTREE", "/tmp/q4r3-route-a-closed-pnl-adapter"))
AUDIT_PATH = WORKTREE / "tools" / "q4r3_route_a_raschke_v3_factorial_portfolio_audit.py"

COVERAGE_IN = RUNTIME / "q4r3_25_strategy_realized_r_coverage_latest.json"
LEDGER_IN = RUNTIME / "q4r3_25_strategy_realized_r_ledger_latest.json"
PRIOR_DECISION = RUNTIME / "q4r3_route_a_raschke_v3_factorial_portfolio_decision_latest.json"
PRIOR_TRADES = RUNTIME / "q4r3_route_a_raschke_v3_sparse_factorial_trades_latest.json"

AUDIT_OUT = RUNTIME / "q4r3_closed_pnl_contract_adapter_audit_latest.json"
EXTENDED_LEDGER_OUT = RUNTIME / "q4r3_25_strategy_realized_r_extended_ledger_latest.json"
COVERAGE_OUT = RUNTIME / "q4r3_25_strategy_realized_r_extended_coverage_latest.json"
PORTFOLIO_OUT = RUNTIME / "q4r3_route_a_raschke_v3_portfolio_role_extended_latest.json"
DECISION_OUT = RUNTIME / "q4r3_closed_pnl_contract_adapter_decision_latest.json"
HANDOFF_OUT = RUNTIME / "q4r3_closed_pnl_contract_adapter_handoff_latest.json"

EXPECTED_STRATEGIES = 25
MIN_TOTAL_ROWS = 200
MAX_FILE_BYTES = 24 * 1024 * 1024
MAX_DEPTH = 12

STRATEGY_KEYS = ("strategy", "strategy_name", "strategy_id", "strategy_key", "strategy_slug")
SYMBOL_KEYS = ("symbol", "market", "ticker")
SIDE_KEYS = ("side", "direction", "position_side")
TRADE_ID_KEYS = ("trade_id", "position_id", "event_id", "request_id")
STATUS_KEYS = ("status", "state", "trade_status", "position_status")
EXIT_TS_KEYS = ("exit_ts", "close_ts", "closed_ts", "closed_at", "exit_time", "close_time")
ENTRY_TS_KEYS = ("entry_ts", "open_ts", "opened_at", "signal_ts")
CLOSE_REASON_KEYS = ("close_reason", "exit_reason", "outcome")

R_KEYS = (
    "realized_r",
    "realized_R",
    "pnl_r",
    "pnl_R",
    "net_r",
    "net_R",
    "result_r",
    "policy_pnl_r",
    "raw_pnl_r",
)
USDT_KEYS = (
    "realized_pnl_usdt",
    "realized_net_pnl_usdt",
    "net_realized_pnl_usdt",
    "net_pnl_usdt",
    "closed_pnl_usdt",
)
RISK_USDT_KEYS = (
    "initial_risk_usdt",
    "position_risk_usdt",
    "risk_usdt",
    "risk_amount_usdt",
    "initial_stop_risk_usdt",
    "planned_risk_usdt",
    "max_loss_usdt",
)

CLOSED_STATUS = {"closed", "done", "settled", "final", "resolved", "exited", "complete", "completed"}
OPEN_STATUS = {"open", "active", "running", "pending", "queued", "candidate"}
PARENT_STRATEGY_KEYS = {"by_strategy", "strategies", "strategy_trades", "trades_by_strategy", "closed_by_strategy", "ledger_by_strategy"}
SOURCE_TOKENS = ("ledger", "trade", "closed", "pnl", "paper", "shadow", "position", "exit")
SOURCE_EXCLUDES = (
    "q4r3_closed_pnl_contract_adapter",
    "q4r3_25_strategy_realized_r_extended",
    "q4r3_route_a_raschke_v3_portfolio_role_extended",
)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUDIT = load_module("q4r3_closed_pnl_contract_audit_base", AUDIT_PATH)


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(errors="ignore"))


def safe_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def timestamp_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number * 1000 if abs(number) < 100_000_000_000 else number
    text = str(value).strip()
    if not text:
        return None
    try:
        number = int(float(text))
        return number * 1000 if abs(number) < 100_000_000_000 else number
    except ValueError:
        pass
    try:
        return int(pd.Timestamp(text).timestamp() * 1000)
    except Exception:
        return None


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)


def first_value(obj: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def first_numeric(obj: Dict[str, Any], keys: Sequence[str]) -> Tuple[Optional[str], Optional[float]]:
    for key in keys:
        if key in obj:
            value = safe_float(obj[key])
            if value is not None:
                return key, value
    return None, None


def strategy_from_obj(obj: Dict[str, Any], inherited: Optional[str]) -> Optional[str]:
    explicit = first_value(obj, STRATEGY_KEYS)
    normalized = normalize(explicit)
    return normalized or inherited


def closed_evidence(obj: Dict[str, Any], exit_ts: Optional[int]) -> Tuple[bool, str]:
    status = normalize(first_value(obj, STATUS_KEYS))
    if status in OPEN_STATUS:
        return False, "OPEN_STATUS"
    if obj.get("status_closed") is True or obj.get("is_closed") is True or obj.get("closed") is True:
        return True, "BOOLEAN_CLOSED"
    if status in CLOSED_STATUS:
        return True, "STATUS_CLOSED"
    if exit_ts is not None:
        return True, "EXIT_TIMESTAMP"
    if first_value(obj, CLOSE_REASON_KEYS) not in (None, ""):
        return True, "CLOSE_REASON"
    return False, "NO_CLOSED_EVIDENCE"


def classify_contract(obj: Dict[str, Any], strategy: str, source: str) -> Optional[Dict[str, Any]]:
    exit_key = next((key for key in EXIT_TS_KEYS if key in obj and timestamp_ms(obj[key]) is not None), None)
    entry_key = next((key for key in ENTRY_TS_KEYS if key in obj and timestamp_ms(obj[key]) is not None), None)
    exit_ts = timestamp_ms(obj[exit_key]) if exit_key else None
    is_closed, closed_source = closed_evidence(obj, exit_ts)
    if not is_closed:
        return None

    r_key, realized_r = first_numeric(obj, R_KEYS)
    usdt_key, realized_usdt = first_numeric(obj, USDT_KEYS)
    risk_key, risk_usdt = first_numeric(obj, RISK_USDT_KEYS)
    timestamp_value = exit_ts
    symbol = str(first_value(obj, SYMBOL_KEYS) or "UNKNOWN").upper()
    side = normalize(first_value(obj, SIDE_KEYS) or "unknown")
    trade_id = str(first_value(obj, TRADE_ID_KEYS) or "")

    if timestamp_value is None:
        contract_state = "CLOSED_ROW_NO_EXIT_TIMESTAMP"
        realized_r = None
        conversion = "NONE"
    elif r_key is not None:
        contract_state = "R_READY_EXISTING"
        conversion = "EXPLICIT_R"
    elif usdt_key is not None and risk_key is not None and risk_usdt is not None and risk_usdt > 0:
        realized_r = float(realized_usdt) / float(risk_usdt)
        contract_state = "R_READY_FROM_EXPLICIT_USDT_RISK"
        conversion = "REALIZED_USDT_DIV_EXPLICIT_RISK_USDT"
    elif usdt_key is not None:
        contract_state = "CLOSED_PNL_USDT_NO_RISK_DENOMINATOR"
        realized_r = None
        conversion = "NONE"
    else:
        contract_state = "CLOSED_ROW_NO_REALIZED_PNL"
        realized_r = None
        conversion = "NONE"

    return {
        "strategy": strategy,
        "contract_state": contract_state,
        "realized_R": realized_r,
        "realized_pnl_usdt": realized_usdt,
        "risk_usdt": risk_usdt,
        "exit_ts": timestamp_value,
        "entry_ts": timestamp_ms(obj[entry_key]) if entry_key else None,
        "symbol": symbol,
        "side": side,
        "trade_id": trade_id,
        "closed_evidence": closed_source,
        "source": source,
        "source_r_key": r_key,
        "source_usdt_key": usdt_key,
        "source_risk_key": risk_key,
        "source_exit_key": exit_key,
        "conversion": conversion,
    }


def iter_contract_rows(obj: Any, source: str, targets: set[str], inherited_strategy: Optional[str] = None, parent_key: str = "", depth: int = 0) -> Iterator[Dict[str, Any]]:
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        strategy = strategy_from_obj(obj, inherited_strategy)
        if strategy in targets:
            classified = classify_contract(obj, strategy, source)
            if classified is not None:
                yield classified
        is_strategy_map = parent_key.lower() in PARENT_STRATEGY_KEYS
        for key, value in obj.items():
            next_strategy = strategy
            if is_strategy_map and isinstance(value, (dict, list)):
                key_strategy = normalize(key)
                if key_strategy:
                    next_strategy = key_strategy
            yield from iter_contract_rows(value, source, targets, next_strategy, str(key), depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_contract_rows(value, source, targets, inherited_strategy, parent_key, depth + 1)


def source_paths() -> List[Path]:
    paths: List[Path] = []
    if not RUNTIME.exists():
        return paths
    for path in RUNTIME.rglob("*.json"):
        lower = path.name.lower()
        if any(token in lower for token in SOURCE_EXCLUDES):
            continue
        if not any(token in lower for token in SOURCE_TOKENS):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if 0 < size <= MAX_FILE_BYTES:
            paths.append(path)
    return sorted(set(paths))


def row_identity(row: Dict[str, Any]) -> Tuple[Any, ...]:
    if row.get("trade_id"):
        return row["strategy"], row["trade_id"]
    return (
        row["strategy"],
        row["symbol"],
        row.get("entry_ts"),
        row.get("exit_ts"),
        row.get("source_usdt_key"),
        round(float(row["realized_pnl_usdt"]), 10) if row.get("realized_pnl_usdt") is not None else None,
        round(float(row["realized_R"]), 10) if row.get("realized_R") is not None else None,
    )


def scan_missing_contracts(missing: Sequence[str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    targets = set(missing)
    rows: List[Dict[str, Any]] = []
    file_audit = []
    seen = set()
    duplicates = 0
    for path in source_paths():
        audit = {"path": str(path), "size_bytes": path.stat().st_size}
        try:
            payload = load_json(path)
            extracted = list(iter_contract_rows(payload, str(path), targets))
            accepted = 0
            states = Counter()
            strategies = set()
            for row in extracted:
                identity = row_identity(row)
                if identity in seen:
                    duplicates += 1
                    continue
                seen.add(identity)
                enriched = dict(row)
                enriched["event_hash"] = hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()[:20]
                rows.append(enriched)
                states[enriched["contract_state"]] += 1
                strategies.add(enriched["strategy"])
                accepted += 1
            audit.update({"parsed": True, "rows": accepted, "states": dict(states), "strategies": sorted(strategies)})
        except Exception as exc:
            audit.update({"parsed": False, "rows": 0, "states": {}, "strategies": [], "error": repr(exc)})
        if audit["rows"] > 0 or not audit["parsed"]:
            file_audit.append(audit)
    rows.sort(key=lambda row: (row.get("exit_ts") or 0, row["strategy"], row["event_hash"]))
    return rows, {
        "files_scanned": len(source_paths()),
        "files_with_contract_rows": sum(1 for item in file_audit if item.get("rows", 0) > 0),
        "duplicate_rows_removed": duplicates,
        "files": file_audit,
    }


def merge_extended_ledger(base_ledger: Dict[str, Any], contract_rows: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    universe = base_ledger.get("universe", {})
    expected = list(universe.get("expected_strategies", []))
    base_rows = [dict(row) for row in base_ledger.get("rows", []) if isinstance(row, dict)]
    extended = list(base_rows)
    seen = set()
    for row in base_rows:
        identity = (
            row.get("canonical_strategy"),
            row.get("trade_id"),
            row.get("symbol"),
            row.get("entry_ts"),
            row.get("exit_ts"),
            round(float(row.get("realized_R", 0.0)), 10),
        )
        seen.add(identity)

    appended = 0
    for row in contract_rows:
        if not str(row["contract_state"]).startswith("R_READY_") or row.get("realized_R") is None:
            continue
        canonical = row["strategy"]
        identity = (
            canonical,
            row.get("trade_id"),
            row.get("symbol"),
            row.get("entry_ts"),
            row.get("exit_ts"),
            round(float(row["realized_R"]), 10),
        )
        if identity in seen:
            continue
        seen.add(identity)
        extended.append(
            {
                "observed_strategy": canonical,
                "canonical_strategy": canonical,
                "mapping_method": "closed_pnl_contract_adapter",
                "realized_R": float(row["realized_R"]),
                "exit_ts": int(row["exit_ts"]),
                "entry_ts": row.get("entry_ts"),
                "symbol": row["symbol"],
                "side": row["side"],
                "trade_id": row.get("trade_id", ""),
                "status": "closed_by_adapter",
                "close_reason": "",
                "source": row["source"],
                "source_pnl_key": row.get("source_r_key") or row.get("source_usdt_key"),
                "source_risk_key": row.get("source_risk_key"),
                "source_exit_key": row.get("source_exit_key"),
                "conversion": row["conversion"],
                "event_hash": row["event_hash"],
            }
        )
        appended += 1

    extended.sort(key=lambda row: (int(row.get("exit_ts") or 0), str(row.get("canonical_strategy")), str(row.get("event_hash"))))
    by_strategy: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in extended:
        by_strategy[str(row.get("canonical_strategy"))].append(row)
    covered = sum(1 for strategy in expected if by_strategy.get(strategy))
    missing = sorted(strategy for strategy in expected if not by_strategy.get(strategy))
    full_ready = len(expected) == EXPECTED_STRATEGIES and covered == EXPECTED_STRATEGIES and len(extended) >= MIN_TOTAL_ROWS
    coverage = {
        "status": "PASS_Q4R3_25_STRATEGY_REALIZED_R_EXTENDED_COVERAGE",
        "expected_strategy_count": len(expected),
        "covered_expected_strategy_count": covered,
        "total_rows": len(extended),
        "adapter_rows_appended": appended,
        "missing_expected_strategies": missing,
        "full_25_strategy_source_ready": full_ready,
        "by_strategy": [
            {
                "strategy": strategy,
                "rows": len(by_strategy.get(strategy, [])),
                "net_R": float(sum(float(row["realized_R"]) for row in by_strategy.get(strategy, []))),
            }
            for strategy in expected
        ],
    }
    ledger = {
        "status": "PASS_Q4R3_25_STRATEGY_REALIZED_R_EXTENDED_LEDGER",
        "universe": universe,
        "base_row_count": len(base_rows),
        "adapter_rows_appended": appended,
        "row_count": len(extended),
        "rows": extended,
        "integrity": {
            "no_inferred_r_from_rr_or_price_fields": True,
            "usdt_conversion_requires_explicit_positive_risk_usdt": True,
            "all_rows_have_finite_R": all(math.isfinite(float(row["realized_R"])) for row in extended),
        },
    }
    portfolio_rows = [
        {
            "strategy": row["canonical_strategy"],
            "pnl_r": float(row["realized_R"]),
            "timestamp_ms": int(row["exit_ts"]),
            "symbol": row.get("symbol", "UNKNOWN"),
            "source": row.get("source", ""),
        }
        for row in extended
    ]
    return ledger, coverage, portfolio_rows


def best_raschke_rows() -> Tuple[str, List[Dict[str, Any]]]:
    decision = load_json(PRIOR_DECISION)
    payload = load_json(PRIOR_TRADES)
    best = str(decision.get("best_independent_candidate") or "")
    rows = payload.get("confirmation_trades", {}).get(best, [])
    return best, rows if isinstance(rows, list) else []


def portfolio_role(portfolio_rows: Sequence[Dict[str, Any]], coverage: Dict[str, Any]) -> Dict[str, Any]:
    best, raschke_rows = best_raschke_rows()
    if not coverage["full_25_strategy_source_ready"]:
        return {
            "status": "PORTFOLIO_SOURCE_NOT_READY",
            "role": "UNRESOLVED",
            "raschke_candidate": best,
            "covered_expected_strategy_count": coverage["covered_expected_strategy_count"],
            "missing_expected_strategies": coverage["missing_expected_strategies"],
        }
    inventory = {"strategy_count": coverage["covered_expected_strategy_count"], "full_25_strategy_source_ready": True}
    result = AUDIT.portfolio_role(portfolio_rows, raschke_rows, inventory)
    result["raschke_candidate"] = best
    return result


def summarized_by_strategy(rows: Sequence[Dict[str, Any]], missing: Sequence[str]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["strategy"]].append(row)
    result = []
    for strategy in missing:
        subset = grouped.get(strategy, [])
        counts = Counter(row["contract_state"] for row in subset)
        result.append(
            {
                "strategy": strategy,
                "contract_rows": len(subset),
                "states": dict(counts),
                "r_ready_rows": sum(count for state, count in counts.items() if state.startswith("R_READY_")),
                "usdt_without_risk_rows": counts.get("CLOSED_PNL_USDT_NO_RISK_DENOMINATOR", 0),
                "no_exit_timestamp_rows": counts.get("CLOSED_ROW_NO_EXIT_TIMESTAMP", 0),
                "sources": sorted({row["source"] for row in subset})[:20],
            }
        )
    return result


def main() -> None:
    coverage_in = load_json(COVERAGE_IN)
    base_ledger = load_json(LEDGER_IN)
    missing = [normalize(name) for name in coverage_in.get("missing_expected_strategies", [])]
    contract_rows, source_audit = scan_missing_contracts(missing)
    extended_ledger, extended_coverage, portfolio_rows = merge_extended_ledger(base_ledger, contract_rows)
    portfolio = portfolio_role(portfolio_rows, extended_coverage)
    by_strategy = summarized_by_strategy(contract_rows, missing)
    counts = Counter(row["contract_state"] for row in contract_rows)

    full_ready = bool(extended_coverage["full_25_strategy_source_ready"])
    role = str(portfolio.get("role", "UNRESOLVED"))
    r_ready_new = int(extended_coverage["adapter_rows_appended"])
    usdt_only = int(counts.get("CLOSED_PNL_USDT_NO_RISK_DENOMINATOR", 0))
    if full_ready and role == "FULL_25_STRATEGY_DIVERSIFIER":
        verdict = "R_READY_COMPLETE_PORTFOLIO_DIVERSIFIER"
        next_action = "RESERVE_ENSEMBLE_CANDIDATE"
    elif full_ready:
        verdict = "R_READY_COMPLETE_NO_PORTFOLIO_VALUE"
        next_action = "FREEZE_RASCHKE_AS_DIAGNOSTIC_MATERIAL"
    elif r_ready_new == 0 and usdt_only > 0:
        verdict = "HISTORICAL_CLOSED_PNL_EXISTS_BUT_R_DENOMINATOR_ABSENT"
        next_action = "STOP_HISTORICAL_R_BACKFILL_AND_REQUIRE_FORWARD_R_WRITER"
    else:
        verdict = "PARTIAL_R_CONTRACT_RECOVERY_STILL_INCOMPLETE"
        next_action = "HOLD_TARGETED_FORWARD_R_WRITER_ONLY"

    adapter_audit = {
        "status": "PASS_Q4R3_CLOSED_PNL_CONTRACT_ADAPTER_AUDIT",
        "verdict": "CLOSED_PNL_CONTRACT_CLASSIFIED_WITHOUT_UNSAFE_R_INFERENCE",
        "missing_input_strategies": missing,
        "contract_state_counts": dict(counts),
        "by_strategy": by_strategy,
        "source_audit": source_audit,
        "safety": {
            "rr_not_used_as_realized_r": True,
            "entry_sl_size_not_used_without_explicit_risk_usdt": True,
            "realized_pnl_pct_not_used_as_realized_r": True,
            "summary_rows_without_exit_timestamp_not_promoted": True,
        },
    }
    decision = {
        "status": "PASS_Q4R3_CLOSED_PNL_CONTRACT_ADAPTER_DECISION",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "base_covered_strategy_count": int(coverage_in.get("covered_expected_strategy_count", 0)),
        "extended_covered_strategy_count": extended_coverage["covered_expected_strategy_count"],
        "adapter_r_ready_rows_appended": r_ready_new,
        "contract_state_counts": dict(counts),
        "missing_after_adapter": extended_coverage["missing_expected_strategies"],
        "full_25_strategy_source_ready": full_ready,
        "portfolio_role": role,
        "research_stop_rule": "No more historical R reconstruction unless an explicit positive risk_usdt denominator exists. Missing strategies must emit realized_R prospectively at close.",
        "authority": {
            "order_authority": "blocked",
            "execution_authority": "none",
            "real_order_enabled": False,
            "paper_request_written": False,
            "live_execution_allowed": False,
            "production_strategy_modified": False,
            "final_holdout_opened": False,
        },
    }
    handoff = {
        "schema": "q4r3_closed_pnl_contract_adapter_handoff_v1",
        "status": decision["status"],
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "base_covered_strategy_count": decision["base_covered_strategy_count"],
        "extended_covered_strategy_count": decision["extended_covered_strategy_count"],
        "adapter_r_ready_rows_appended": r_ready_new,
        "contract_state_counts": dict(counts),
        "missing_after_adapter": decision["missing_after_adapter"],
        "portfolio_role": role,
        "by_strategy": by_strategy,
        "safety": adapter_audit["safety"],
        "authority": decision["authority"],
        "raw_trade_rows_included": False,
    }

    atomic_json(AUDIT_OUT, adapter_audit)
    atomic_json(EXTENDED_LEDGER_OUT, extended_ledger)
    atomic_json(COVERAGE_OUT, extended_coverage)
    atomic_json(PORTFOLIO_OUT, portfolio)
    atomic_json(DECISION_OUT, decision)
    atomic_json(HANDOFF_OUT, handoff)
    print(json.dumps(handoff, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
