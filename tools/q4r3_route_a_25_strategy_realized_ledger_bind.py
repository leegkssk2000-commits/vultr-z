from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import math
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
WORKTREE = Path(os.environ.get("Q4R3_ROUTE_A_WORKTREE", "/tmp/q4r3-route-a-25-strategy-ledger"))
AUDIT_PATH = WORKTREE / "tools" / "q4r3_route_a_raschke_v3_factorial_portfolio_audit.py"

CANONICAL_OUT = ROOT / "runtime" / "q4r3_25_strategy_realized_r_ledger_latest.json"
COVERAGE_OUT = ROOT / "runtime" / "q4r3_25_strategy_realized_r_coverage_latest.json"
SOURCE_OUT = ROOT / "runtime" / "q4r3_25_strategy_realized_r_source_audit_latest.json"
PORTFOLIO_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_portfolio_role_rebound_latest.json"
DECISION_OUT = ROOT / "runtime" / "q4r3_25_strategy_realized_r_bind_decision_latest.json"
HTML_OUT = ROOT / "runtime" / "q4r3_25_strategy_realized_r_bind_latest.html"

PRIOR_FACTORIAL = ROOT / "runtime" / "q4r3_route_a_raschke_v3_sparse_factorial_latest.json"
PRIOR_TRADES = ROOT / "runtime" / "q4r3_route_a_raschke_v3_sparse_factorial_trades_latest.json"
PRIOR_DECISION = ROOT / "runtime" / "q4r3_route_a_raschke_v3_factorial_portfolio_decision_latest.json"
PRIOR_INVENTORY = ROOT / "runtime" / "q4r3_route_a_raschke_v3_portfolio_source_inventory_latest.json"

RUNTIME_MAX_FILE = 100 * 1024 * 1024
EXPECTED_STRATEGIES = 25
MIN_FULL_ROWS = 200
MIN_ROWS_PER_STRATEGY = 1

UNIVERSE_KEYS = {
    "strategy_universe",
    "strategy_names",
    "strategies",
    "strategy_cards",
    "registry",
    "strategy_registry",
    "enabled_strategies",
    "active_strategies",
    "candidate_strategies",
    "all_strategies",
}
STRATEGY_KEYS = ("strategy", "strategy_name", "strategy_id", "strategy_key", "strategy_slug", "name", "slug", "id")
ALIAS_KEYS = ("aliases", "alias", "legacy_names", "legacy_ids")
PNL_KEYS = (
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
EXIT_TS_KEYS = ("exit_ts", "close_ts", "closed_ts", "closed_at", "exit_time", "close_time")
ENTRY_TS_KEYS = ("entry_ts", "open_ts", "opened_at", "signal_ts", "ts", "timestamp")
SYMBOL_KEYS = ("symbol", "market", "ticker")
SIDE_KEYS = ("side", "direction", "position_side")
STATUS_KEYS = ("status", "state", "trade_status", "position_status")
CLOSE_REASON_KEYS = ("close_reason", "exit_reason", "outcome", "result", "reason")
TRADE_ID_KEYS = ("trade_id", "position_id", "event_id", "id", "request_id")
PARENT_STRATEGY_KEYS = {
    "by_strategy",
    "strategies",
    "strategy_trades",
    "trades_by_strategy",
    "closed_by_strategy",
    "ledger_by_strategy",
}
CLOSED_STATUS = {"closed", "done", "settled", "final", "resolved", "exited", "complete", "completed"}
OPEN_STATUS = {"open", "active", "running", "pending", "queued", "candidate"}
SOURCE_NAME_TOKENS = ("ledger", "trade", "closed", "pnl", "shadow", "paper", "strategy", "replay", "portfolio")
SOURCE_EXCLUDES = (
    "q4r3_25_strategy_realized_r_",
    "q4r3_route_a_raschke_v3_sparse_factorial_trades",
    "q4r3_route_a_raschke_v3_2r_rescue_trades",
    "q4r3_route_a_raschke_v3_all_signal_ledger",
    "portfolio_source_inventory",
)
NON_STRATEGY_NAMES = {
    "alpha",
    "beta",
    "gamma",
    "delta",
    "long",
    "short",
    "paper",
    "live",
    "shadow",
    "closed",
    "open",
    "unknown",
    "none",
    "true",
    "false",
}


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUDIT = load_module("q4r3_25_strategy_ledger_audit_base", AUDIT_PATH)


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


def normalize_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text


def plausible_strategy_name(value: Any) -> bool:
    name = normalize_name(value)
    if len(name) < 3 or name in NON_STRATEGY_NAMES:
        return False
    if name.isdigit() or name.startswith("http"):
        return False
    return True


def first_value(obj: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def object_strategy_names(obj: Dict[str, Any]) -> Tuple[List[str], Dict[str, str]]:
    names = []
    aliases: Dict[str, str] = {}
    preferred = first_value(obj, ("strategy_id", "strategy_key", "strategy_slug", "slug", "name", "strategy_name", "strategy"))
    canonical = normalize_name(preferred) if plausible_strategy_name(preferred) else ""
    for key in STRATEGY_KEYS:
        if key in obj and plausible_strategy_name(obj[key]):
            names.append(normalize_name(obj[key]))
    for key in ALIAS_KEYS:
        value = obj.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if plausible_strategy_name(item):
                names.append(normalize_name(item))
    names = list(dict.fromkeys(names))
    if canonical:
        for name in names:
            aliases[name] = canonical
    return names, aliases


def extract_universe_candidates(obj: Any, source: str, parent_key: str = "", depth: int = 0) -> Iterator[Dict[str, Any]]:
    if depth > 8:
        return
    if isinstance(obj, dict):
        lower_parent = parent_key.lower()
        if lower_parent in UNIVERSE_KEYS:
            names: List[str] = []
            aliases: Dict[str, str] = {}
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if isinstance(value, (dict, list)):
                        if plausible_strategy_name(key):
                            names.append(normalize_name(key))
                        if isinstance(value, dict):
                            sub_names, sub_aliases = object_strategy_names(value)
                            names.extend(sub_names)
                            aliases.update(sub_aliases)
                    elif plausible_strategy_name(value):
                        names.append(normalize_name(value))
            names = sorted(set(names))
            if names:
                yield {"source": source, "key": parent_key, "names": names, "aliases": aliases}
        direct_names, direct_aliases = object_strategy_names(obj)
        if parent_key.lower() in UNIVERSE_KEYS and direct_names:
            yield {"source": source, "key": parent_key, "names": sorted(set(direct_names)), "aliases": direct_aliases}
        for key, value in obj.items():
            yield from extract_universe_candidates(value, source, str(key), depth + 1)
    elif isinstance(obj, list):
        if parent_key.lower() in UNIVERSE_KEYS:
            names: List[str] = []
            aliases: Dict[str, str] = {}
            for value in obj:
                if isinstance(value, str) and plausible_strategy_name(value):
                    names.append(normalize_name(value))
                elif isinstance(value, dict):
                    sub_names, sub_aliases = object_strategy_names(value)
                    names.extend(sub_names)
                    aliases.update(sub_aliases)
            names = sorted(set(names))
            if names:
                yield {"source": source, "key": parent_key, "names": names, "aliases": aliases}
        for value in obj:
            yield from extract_universe_candidates(value, source, parent_key, depth + 1)


def candidate_score(candidate: Dict[str, Any]) -> Tuple[int, int, int, int]:
    count = len(candidate["names"])
    exact = 1 if count == EXPECTED_STRATEGIES else 0
    near = -abs(count - EXPECTED_STRATEGIES)
    key_weight = 2 if candidate["key"].lower() in {"strategy_universe", "strategy_registry", "strategy_cards"} else 1
    path_weight = sum(token in candidate["source"].lower() for token in ("registry", "universe", "strategy", "card"))
    return exact, near, key_weight, path_weight


def universe_source_paths() -> List[Path]:
    roots = [ROOT / "runtime", ROOT / "config", ROOT / "configs", ROOT / "data"]
    paths: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            lower = str(path).lower()
            if 0 < size <= 20 * 1024 * 1024 and any(token in lower for token in ("strategy", "registry", "card", "universe", "ranking")):
                paths.append(path)
    return sorted(set(paths))


def discover_universe() -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    file_errors = []
    for path in universe_source_paths():
        try:
            payload = load_json(path)
            candidates.extend(extract_universe_candidates(payload, str(path)))
        except Exception as exc:
            file_errors.append({"path": str(path), "error": repr(exc)})
    prior_inventory = None
    if PRIOR_INVENTORY.exists():
        try:
            prior_inventory = load_json(PRIOR_INVENTORY)
            names = [normalize_name(name) for name in prior_inventory.get("strategies", []) if plausible_strategy_name(name)]
            if names:
                candidates.append({"source": str(PRIOR_INVENTORY), "key": "observed_strategies", "names": sorted(set(names)), "aliases": {}})
        except Exception as exc:
            file_errors.append({"path": str(PRIOR_INVENTORY), "error": repr(exc)})
    candidates.sort(key=candidate_score, reverse=True)
    selected = candidates[0] if candidates else {"source": None, "key": None, "names": [], "aliases": {}}
    exact_candidates = [candidate for candidate in candidates if len(candidate["names"]) == EXPECTED_STRATEGIES]
    if exact_candidates:
        exact_candidates.sort(key=candidate_score, reverse=True)
        selected = exact_candidates[0]
    alias_map = {name: name for name in selected["names"]}
    alias_map.update(selected.get("aliases", {}))
    return {
        "selected_source": selected.get("source"),
        "selected_key": selected.get("key"),
        "expected_strategy_count": len(selected.get("names", [])),
        "expected_strategies": selected.get("names", []),
        "alias_map": alias_map,
        "exact_25_found": len(selected.get("names", [])) == EXPECTED_STRATEGIES,
        "candidate_count": len(candidates),
        "top_candidates": [
            {"source": c["source"], "key": c["key"], "count": len(c["names"]), "names": c["names"]}
            for c in candidates[:10]
        ],
        "file_errors": file_errors,
    }


def runtime_source_paths() -> List[Path]:
    runtime = ROOT / "runtime"
    if not runtime.exists():
        return []
    paths = []
    for path in runtime.glob("*.json"):
        lower = path.name.lower()
        if any(token in lower for token in SOURCE_EXCLUDES):
            continue
        if not any(token in lower for token in SOURCE_NAME_TOKENS):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if 0 < size <= RUNTIME_MAX_FILE:
            paths.append(path)
    return sorted(paths)


def row_closed(obj: Dict[str, Any], exit_ts: Optional[int], close_reason: Any) -> bool:
    status = normalize_name(first_value(obj, STATUS_KEYS))
    if status in OPEN_STATUS:
        return False
    if status in CLOSED_STATUS:
        return True
    if exit_ts is not None:
        return True
    return close_reason not in (None, "")


def strategy_from_obj(obj: Dict[str, Any], inherited: Optional[str]) -> Optional[str]:
    explicit = first_value(obj, ("strategy", "strategy_name", "strategy_id", "strategy_key", "strategy_slug"))
    if plausible_strategy_name(explicit):
        return normalize_name(explicit)
    return inherited


def iter_realized_rows(obj: Any, source: str, inherited_strategy: Optional[str] = None, parent_key: str = "", depth: int = 0) -> Iterator[Dict[str, Any]]:
    if depth > 10:
        return
    if isinstance(obj, dict):
        strategy = strategy_from_obj(obj, inherited_strategy)
        pnl_key = next((key for key in PNL_KEYS if key in obj and safe_float(obj[key]) is not None), None)
        exit_key = next((key for key in EXIT_TS_KEYS if key in obj and timestamp_ms(obj[key]) is not None), None)
        entry_key = next((key for key in ENTRY_TS_KEYS if key in obj and timestamp_ms(obj[key]) is not None), None)
        close_reason = first_value(obj, CLOSE_REASON_KEYS)
        exit_ts = timestamp_ms(obj[exit_key]) if exit_key else None
        if strategy and pnl_key and row_closed(obj, exit_ts, close_reason):
            timestamp_value = exit_ts or (timestamp_ms(obj[entry_key]) if entry_key else None)
            if timestamp_value is not None:
                symbol = str(first_value(obj, SYMBOL_KEYS) or "UNKNOWN").upper()
                side = normalize_name(first_value(obj, SIDE_KEYS) or "unknown")
                trade_id = str(first_value(obj, TRADE_ID_KEYS) or "")
                yield {
                    "observed_strategy": strategy,
                    "realized_R": float(obj[pnl_key]),
                    "exit_ts": int(timestamp_value),
                    "entry_ts": timestamp_ms(obj[entry_key]) if entry_key else None,
                    "symbol": symbol,
                    "side": side,
                    "trade_id": trade_id,
                    "status": normalize_name(first_value(obj, STATUS_KEYS) or "closed_by_evidence"),
                    "close_reason": str(close_reason or ""),
                    "source": source,
                    "source_pnl_key": pnl_key,
                    "source_exit_key": exit_key or entry_key,
                }
        strategy_map = parent_key.lower() in PARENT_STRATEGY_KEYS
        for key, value in obj.items():
            next_strategy = strategy
            if strategy_map and isinstance(value, (dict, list)) and plausible_strategy_name(key):
                next_strategy = normalize_name(key)
            yield from iter_realized_rows(value, source, next_strategy, str(key), depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_realized_rows(value, source, inherited_strategy, parent_key, depth + 1)


def canonicalize_strategy(observed: str, alias_map: Dict[str, str], expected: Sequence[str]) -> Tuple[str, str]:
    normalized = normalize_name(observed)
    if normalized in alias_map:
        return alias_map[normalized], "alias_map"
    if normalized in expected:
        return normalized, "exact"
    compact = normalized.replace("_", "")
    matches = [name for name in expected if name.replace("_", "") == compact]
    if len(matches) == 1:
        return matches[0], "punctuation_normalized"
    return normalized, "unmatched"


def record_identity(row: Dict[str, Any]) -> Tuple[Any, ...]:
    if row.get("trade_id"):
        return (row["canonical_strategy"], row["trade_id"])
    return (
        row["canonical_strategy"],
        row["symbol"],
        row.get("entry_ts"),
        row["exit_ts"],
        round(float(row["realized_R"]), 10),
    )


def build_canonical_ledger(universe: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    expected = list(universe["expected_strategies"])
    alias_map = dict(universe["alias_map"])
    source_audit = []
    all_rows: List[Dict[str, Any]] = []
    duplicate_count = 0
    seen = set()
    for path in runtime_source_paths():
        audit: Dict[str, Any] = {"path": str(path), "size_bytes": path.stat().st_size}
        try:
            payload = load_json(path)
            extracted = list(iter_realized_rows(payload, str(path)))
            accepted = 0
            observed_names = set()
            for row in extracted:
                canonical, method = canonicalize_strategy(row["observed_strategy"], alias_map, expected)
                enriched = dict(row)
                enriched["canonical_strategy"] = canonical
                enriched["mapping_method"] = method
                identity = record_identity(enriched)
                if identity in seen:
                    duplicate_count += 1
                    continue
                seen.add(identity)
                enriched["event_hash"] = hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()[:20]
                all_rows.append(enriched)
                observed_names.add(canonical)
                accepted += 1
            audit.update({"parsed": True, "extracted_rows": len(extracted), "accepted_rows": accepted, "strategies": sorted(observed_names)})
        except Exception as exc:
            audit.update({"parsed": False, "extracted_rows": 0, "accepted_rows": 0, "strategies": [], "error": repr(exc)})
        source_audit.append(audit)
    all_rows.sort(key=lambda row: (int(row["exit_ts"]), row["canonical_strategy"], row["event_hash"]))

    by_strategy: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        by_strategy[row["canonical_strategy"]].append(row)
    expected_set = set(expected)
    observed_set = set(by_strategy)
    coverage_rows = []
    for strategy in sorted(expected_set | observed_set):
        rows = by_strategy.get(strategy, [])
        coverage_rows.append(
            {
                "strategy": strategy,
                "expected": strategy in expected_set,
                "rows": len(rows),
                "net_R": float(sum(float(row["realized_R"]) for row in rows)),
                "first_exit_ts": min((int(row["exit_ts"]) for row in rows), default=None),
                "last_exit_ts": max((int(row["exit_ts"]) for row in rows), default=None),
                "sources": sorted({row["source"] for row in rows}),
                "unmatched_rows": sum(1 for row in rows if row["mapping_method"] == "unmatched"),
            }
        )
    missing = sorted(strategy for strategy in expected if len(by_strategy.get(strategy, [])) < MIN_ROWS_PER_STRATEGY)
    unexpected = sorted(strategy for strategy in observed_set if expected_set and strategy not in expected_set)
    covered_expected = sum(1 for strategy in expected if by_strategy.get(strategy))
    full_ready = (
        len(expected) == EXPECTED_STRATEGIES
        and covered_expected == EXPECTED_STRATEGIES
        and len(all_rows) >= MIN_FULL_ROWS
    )
    coverage = {
        "status": "PASS_Q4R3_25_STRATEGY_REALIZED_R_COVERAGE",
        "expected_strategy_count": len(expected),
        "covered_expected_strategy_count": covered_expected,
        "observed_strategy_count": len(observed_set),
        "total_rows": len(all_rows),
        "duplicate_rows_removed": duplicate_count,
        "missing_expected_strategies": missing,
        "unexpected_observed_strategies": unexpected,
        "full_25_strategy_source_ready": full_ready,
        "requirements": {"expected_strategies": EXPECTED_STRATEGIES, "rows_min": MIN_FULL_ROWS, "rows_per_strategy_min": MIN_ROWS_PER_STRATEGY},
        "by_strategy": coverage_rows,
    }
    source_report = {
        "status": "PASS_Q4R3_25_STRATEGY_REALIZED_R_SOURCE_AUDIT",
        "files_scanned": len(source_audit),
        "files_with_rows": sum(1 for item in source_audit if item.get("accepted_rows", 0) > 0),
        "accepted_rows": len(all_rows),
        "files": source_audit,
        "contract": "Only row-level realized-R records with closed evidence and timestamp are accepted. Summary-only PnL and configured strategy membership are rejected.",
    }
    ledger = {
        "status": "PASS_Q4R3_25_STRATEGY_REALIZED_R_LEDGER_BIND",
        "universe": universe,
        "row_count": len(all_rows),
        "rows": all_rows,
        "integrity": {
            "duplicate_rows_removed": duplicate_count,
            "all_rows_have_timestamp": all(int(row["exit_ts"]) > 0 for row in all_rows),
            "all_rows_have_finite_R": all(math.isfinite(float(row["realized_R"])) for row in all_rows),
            "closed_evidence_required": True,
        },
    }
    portfolio_rows = [
        {
            "strategy": row["canonical_strategy"],
            "pnl_r": float(row["realized_R"]),
            "timestamp_ms": int(row["exit_ts"]),
            "symbol": row["symbol"],
            "source": row["source"],
        }
        for row in all_rows
    ]
    return ledger, coverage, source_report, portfolio_rows


def best_raschke_rows() -> Tuple[str, List[Dict[str, Any]]]:
    decision = load_json(PRIOR_DECISION)
    trades_payload = load_json(PRIOR_TRADES)
    best = str(decision.get("best_independent_candidate") or "")
    rows = trades_payload.get("confirmation_trades", {}).get(best, [])
    if not isinstance(rows, list):
        rows = []
    return best, rows


def rerun_portfolio_role(portfolio_rows: Sequence[Dict[str, Any]], coverage: Dict[str, Any]) -> Dict[str, Any]:
    best, raschke_rows = best_raschke_rows()
    inventory = {
        "strategy_count": coverage["covered_expected_strategy_count"],
        "full_25_strategy_source_ready": coverage["full_25_strategy_source_ready"],
    }
    result = AUDIT.portfolio_role(portfolio_rows, raschke_rows, inventory)
    result["raschke_candidate"] = best
    result["canonical_ledger_rows"] = len(portfolio_rows)
    result["coverage_ready"] = coverage["full_25_strategy_source_ready"]
    return result


def write_html(universe: Dict[str, Any], coverage: Dict[str, Any], portfolio: Dict[str, Any], decision: Dict[str, Any]) -> None:
    rows = []
    for item in coverage["by_strategy"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['strategy'])}</td>"
            f"<td>{item['expected']}</td>"
            f"<td>{item['rows']}</td>"
            f"<td>{item['net_R']:.4f}</td>"
            f"<td>{item['unmatched_rows']}</td>"
            "</tr>"
        )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>25 strategy realized-R ledger bind</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>25-strategy realized-R ledger bind</h1>",
            "<h2>Universe</h2><pre>", html.escape(json.dumps(universe, ensure_ascii=False, indent=2)), "</pre>",
            "<table><thead><tr><th>Strategy</th><th>Expected</th><th>Rows</th><th>Net R</th><th>Unmatched</th></tr></thead><tbody>",
            "".join(rows),
            "</tbody></table><h2>Portfolio rerun</h2><pre>", html.escape(json.dumps(portfolio, ensure_ascii=False, indent=2)), "</pre>",
            "<h2>Decision</h2><pre>", html.escape(json.dumps(decision, ensure_ascii=False, indent=2)), "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    universe = discover_universe()
    ledger, coverage, source_report, portfolio_rows = build_canonical_ledger(universe)
    portfolio = rerun_portfolio_role(portfolio_rows, coverage)

    independent_decision = load_json(PRIOR_DECISION)
    independent_pass = bool(independent_decision.get("independent_gate_pass_candidates"))
    role = str(portfolio.get("role", "UNRESOLVED"))
    full_ready = bool(coverage["full_25_strategy_source_ready"])
    if independent_pass:
        verdict = "A_INDEPENDENT_GATE_PASS_FOURTH_SHADOW_CANDIDATE"
        action = "FOURTH_SHADOW_CANDIDATE_OBSERVER_ONLY"
    elif full_ready and role == "FULL_25_STRATEGY_DIVERSIFIER":
        verdict = "B_INDEPENDENT_FAIL_PORTFOLIO_PASS_RESERVE_ENSEMBLE"
        action = "RESERVE_ENSEMBLE_CANDIDATE"
    elif full_ready:
        verdict = "C_INDEPENDENT_AND_PORTFOLIO_FAIL_FREEZE_RASCHKE"
        action = "FREEZE_AS_DIAGNOSTIC_MATERIAL"
    else:
        verdict = "PORTFOLIO_UNRESOLVED_CANONICAL_LEDGER_INCOMPLETE"
        action = "HOLD_AND_BIND_MISSING_REALIZED_R_SOURCES"

    decision = {
        "status": "PASS_Q4R3_25_STRATEGY_REALIZED_R_BIND_DECISION",
        "verdict": verdict,
        "action": action,
        "expected_universe_exact_25": universe["exact_25_found"],
        "expected_strategy_count": coverage["expected_strategy_count"],
        "covered_expected_strategy_count": coverage["covered_expected_strategy_count"],
        "canonical_row_count": coverage["total_rows"],
        "missing_expected_strategies": coverage["missing_expected_strategies"],
        "unexpected_observed_strategies": coverage["unexpected_observed_strategies"],
        "full_25_strategy_source_ready": full_ready,
        "portfolio_role": role,
        "portfolio_raschke_candidate": portfolio.get("raschke_candidate"),
        "next_modules": (
            ["FOURTH_SHADOW_OBSERVER_PRECHECK"] if independent_pass else
            ["RESERVE_ENSEMBLE_VALUE_ADD_REPLAY"] if full_ready and role == "FULL_25_STRATEGY_DIVERSIFIER" else
            ["FREEZE_RASCHKE_MOVE_TO_NEXT_STRATEGY"] if full_ready else
            ["TRACE_MISSING_STRATEGY_REALIZED_R_WRITERS", "CANONICAL_LEDGER_APPEND_AFTER_SOURCE_CONFIRMATION"]
        ),
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

    write_html(universe, coverage, portfolio, decision)
    atomic_json(CANONICAL_OUT, ledger)
    atomic_json(COVERAGE_OUT, coverage)
    atomic_json(SOURCE_OUT, source_report)
    atomic_json(PORTFOLIO_OUT, portfolio)
    atomic_json(DECISION_OUT, decision)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(json.dumps({"universe": universe, "coverage": coverage, "portfolio": portfolio}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
