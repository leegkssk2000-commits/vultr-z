from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

ROOT = Path("/home/z/z")
WORKTREE = Path(os.environ.get("Q4R3_ROUTE_A_WORKTREE", "/tmp/q4r3-route-a-v3-factorial-portfolio"))
BASE_PATH = WORKTREE / "tools" / "q4r3_route_a_raschke_v3_2r_rescue_tournament.py"

FACTORIAL_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_sparse_factorial_latest.json"
FACTORIAL_TRADES_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_sparse_factorial_trades_latest.json"
PORTFOLIO_INVENTORY_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_portfolio_source_inventory_latest.json"
PORTFOLIO_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_portfolio_role_latest.json"
DECISION_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_factorial_portfolio_decision_latest.json"
TRIAL_OUT = ROOT / "runtime" / "q4r3_route_a_raschke_v3_factorial_portfolio_trial_latest.json"
HTML_OUT = ROOT / "runtime" / "raschke_v3_factorial_portfolio_audit_latest.html"

FACTOR_NAMES = (
    "long_only",
    "side_specific_target",
    "time_stop_120m_unless_1R",
    "trend_1h_4h_alignment",
    "link_reserve",
)
DUMMY_NAMES = ("dummy_1", "dummy_2")
COST_PRIMARY = 0.15
COST_STRESS = 0.20
LOSS_CAP_R = 0.50
TIMEOUT_MIN = 480
COOLDOWN_MIN = 60
MINUTE_MS = 60_000

CONFIRM_GATE = {
    "retention_pct_min": 35.0,
    "events_second_min": 15,
    "prior_avg_R_min": 0.0,
    "second_avg_R_min": 0.0,
    "cost_0.20_avg_R_min_exclusive": 0.0,
    "profit_factor_min": 1.30,
    "positive_symbols_min": 3,
    "positive_month_ratio_min": 0.50,
    "bootstrap_second_lower_min": -0.10,
}

STRATEGY_KEYS = ("strategy", "strategy_name", "strategy_id", "strategy_key", "strategy_slug")
PNL_KEYS = (
    "net_R_0.15",
    "net_r_0.15",
    "net_R",
    "net_r",
    "pnl_r",
    "realized_r",
    "realized_R",
    "result_r",
    "pnl_R",
)
TIMESTAMP_KEYS = ("exit_ts", "close_ts", "closed_at", "closed_ts", "entry_ts", "signal_ts", "ts", "timestamp")
SYMBOL_KEYS = ("symbol", "market", "ticker")
PORTFOLIO_PARENT_KEYS = ("by_strategy", "strategies", "strategy_trades", "trades_by_strategy", "closed_by_strategy")
PORTFOLIO_NAME_TOKENS = ("ledger", "trades", "closed", "shadow", "pnl", "strategy", "replay")
PORTFOLIO_EXCLUDE_TOKENS = (
    "q4r3_route_a_raschke_v3_",
    "raschke_v3_",
    "2r_rescue",
    "factorial_portfolio",
)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = load_module("q4r3_raschke_v3_factorial_base", BASE_PATH)
WINDOWS = tuple(BASE.WINDOWS)
SYMBOLS = tuple(BASE.SYMBOLS)
SIDES = tuple(BASE.SIDES)


def atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


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
        number = float(text)
        integer = int(number)
        return integer * 1000 if abs(integer) < 100_000_000_000 else integer
    except ValueError:
        pass
    try:
        return int(pd.Timestamp(text).timestamp() * 1000)
    except Exception:
        return None


def hadamard_screening_design() -> List[Dict[str, Any]]:
    columns = FACTOR_NAMES + DUMMY_NAMES
    rows: List[Dict[str, Any]] = []
    for row_index in range(8):
        levels: Dict[str, int] = {}
        for column_index, name in enumerate(columns, start=1):
            parity = (row_index & column_index).bit_count() % 2
            levels[name] = 1 if parity == 0 else -1
        rows.append(
            {
                "run_id": f"PB8_R{row_index + 1}",
                "levels": levels,
                "factors": {name: levels[name] > 0 for name in FACTOR_NAMES},
            }
        )
    return rows


def directional_r(side: str, price: float, entry: float, risk: float) -> float:
    return (price - entry) / risk if side == "long" else (entry - price) / risk


def regime_aligned(raw: pd.DataFrame, entry_idx: int, side: str) -> bool:
    end = entry_idx - 1
    if end < 240:
        return False
    close_now = float(raw.iloc[end]["close"])
    close_60 = float(raw.iloc[end - 60]["close"])
    close_240 = float(raw.iloc[end - 240]["close"])
    ret_60 = close_now / close_60 - 1.0
    ret_240 = close_now / close_240 - 1.0
    return (ret_60 > 0 and ret_240 > 0) if side == "long" else (ret_60 < 0 and ret_240 < 0)


def signal_allowed(raw: pd.DataFrame, signal: Dict[str, Any], factors: Dict[str, bool]) -> bool:
    side = str(signal["side"])
    if factors.get("long_only", False) and side != "long":
        return False
    if factors.get("link_reserve", False) and str(signal["symbol"]) == "LINKUSDT":
        return False
    if factors.get("trend_1h_4h_alignment", False) and not regime_aligned(raw, int(signal["entry_idx"]), side):
        return False
    return True


def simulate_factorial(
    raw: pd.DataFrame,
    signal: Dict[str, Any],
    factors: Dict[str, bool],
    side_target_map: Dict[str, float],
    policy_name: str,
) -> Optional[Dict[str, Any]]:
    if not signal_allowed(raw, signal, factors):
        return None
    entry_idx = int(signal["entry_idx"])
    if entry_idx < 0 or entry_idx >= len(raw):
        return None
    entry = float(raw.iloc[entry_idx]["open"])
    risk = abs(float(signal["signal_entry"]) - float(signal["native_stop"]))
    if not math.isfinite(risk) or risk <= 0:
        return None
    side = str(signal["side"])
    target_r = float(side_target_map[side]) if factors.get("side_specific_target", False) else 2.0
    last_idx = min(len(raw) - 1, entry_idx + TIMEOUT_MIN - 1)
    if not BASE.path_contiguous(raw, entry_idx, last_idx):
        return None

    max_mfe = 0.0
    outcome = "TIMEOUT"
    exit_idx = last_idx
    exit_r = directional_r(side, float(raw.iloc[last_idx]["close"]), entry, risk)
    ambiguity = False

    for current in range(entry_idx, last_idx + 1):
        elapsed = current - entry_idx
        bar = raw.iloc[current]
        favorable_price = float(bar["high"] if side == "long" else bar["low"])
        adverse_price = float(bar["low"] if side == "long" else bar["high"])
        favorable_r = directional_r(side, favorable_price, entry, risk)
        adverse_r = directional_r(side, adverse_price, entry, risk)
        stop_hit = adverse_r <= -LOSS_CAP_R
        target_hit = favorable_r >= target_r
        if stop_hit and target_hit:
            outcome = "STOP_TARGET_AMBIGUOUS"
            exit_idx = current
            exit_r = -LOSS_CAP_R
            ambiguity = True
            break
        if stop_hit:
            outcome = "SL"
            exit_idx = current
            exit_r = -LOSS_CAP_R
            break
        if target_hit:
            outcome = "TP"
            exit_idx = current
            exit_r = target_r
            break
        max_mfe = max(max_mfe, favorable_r)
        if factors.get("time_stop_120m_unless_1R", False) and elapsed >= 120 and max_mfe < 1.0:
            outcome = "TIME_STOP_120"
            exit_idx = current
            exit_r = directional_r(side, float(bar["close"]), entry, risk)
            break

    return {
        "event_id": signal["event_id"],
        "window": signal["window"],
        "symbol": signal["symbol"],
        "side": side,
        "signal_ts": int(signal["signal_ts"]),
        "entry_ts": int(raw.iloc[entry_idx]["ts"]),
        "exit_ts": int(raw.iloc[exit_idx]["ts"]),
        "entry": entry,
        "base_risk": risk,
        "gross_r": float(exit_r),
        "outcome": outcome,
        "policy": policy_name,
        "target_r": target_r,
        "duration_min": int(exit_idx - entry_idx),
        "mfe_R_observed": float(max_mfe),
        "ambiguity": ambiguity,
        "factors": dict(factors),
    }


def replay_factorial(
    raw: pd.DataFrame,
    signals: Sequence[Dict[str, Any]],
    factors: Dict[str, bool],
    side_target_map: Dict[str, float],
    policy_name: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    blocked_until = -1
    for signal in sorted(signals, key=lambda row: int(row["entry_ts"])):
        if int(signal["entry_ts"]) <= blocked_until:
            continue
        trade = simulate_factorial(raw, signal, factors, side_target_map, policy_name)
        if trade is None:
            continue
        rows.append(trade)
        blocked_until = int(trade["exit_ts"]) + COOLDOWN_MIN * MINUTE_MS
    return rows


def replay_config(
    raw_cache: Dict[Tuple[str, str], pd.DataFrame],
    signals_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]],
    factors: Dict[str, bool],
    side_target_map: Dict[str, float],
    policy_name: str,
    windows: Sequence[str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for window in windows:
        for symbol in SYMBOLS:
            key = (window, symbol)
            rows.extend(replay_factorial(raw_cache[key], signals_by_key[key], factors, side_target_map, policy_name))
    return rows


def symbol_average(rows: Sequence[Dict[str, Any]], symbol: str, cost_pct: float) -> float:
    values = [BASE.net_r(row, cost_pct) for row in rows if str(row["symbol"]) == symbol]
    return float(statistics.fmean(values)) if values else 0.0


def estimate_effects(
    design: Sequence[Dict[str, Any]],
    rows_by_run: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    reports: Dict[str, Any] = {}
    for run in design:
        run_id = str(run["run_id"])
        rows = rows_by_run[run_id]
        reports[run_id] = {
            "levels": run["levels"],
            "factors": run["factors"],
            "metrics_cost_0.15": BASE.metrics(rows, COST_PRIMARY),
            "metrics_cost_0.20": BASE.metrics(rows, COST_STRESS),
            "symbol_avg_R": {symbol: symbol_average(rows, symbol, COST_PRIMARY) for symbol in SYMBOLS},
        }

    effects: Dict[str, Any] = {}
    for name in FACTOR_NAMES + DUMMY_NAMES:
        on_runs = [run for run in design if int(run["levels"][name]) > 0]
        off_runs = [run for run in design if int(run["levels"][name]) < 0]
        on_values = [float(reports[str(run["run_id"])]["metrics_cost_0.15"]["avg_net_R"]) for run in on_runs]
        off_values = [float(reports[str(run["run_id"])]["metrics_cost_0.15"]["avg_net_R"]) for run in off_runs]
        symbol_effects = {}
        for symbol in SYMBOLS:
            symbol_on = [float(reports[str(run["run_id"])]["symbol_avg_R"][symbol]) for run in on_runs]
            symbol_off = [float(reports[str(run["run_id"])]["symbol_avg_R"][symbol]) for run in off_runs]
            symbol_effects[symbol] = float(statistics.fmean(symbol_on) - statistics.fmean(symbol_off))
        effects[name] = {
            "main_effect_avg_R": float(statistics.fmean(on_values) - statistics.fmean(off_values)),
            "on_avg_R": float(statistics.fmean(on_values)),
            "off_avg_R": float(statistics.fmean(off_values)),
            "positive_symbol_effects": sum(1 for value in symbol_effects.values() if value > 0),
            "symbol_effects": symbol_effects,
        }

    dummy_floor = max(abs(float(effects[name]["main_effect_avg_R"])) for name in DUMMY_NAMES)
    selection_floor = max(0.02, 1.5 * dummy_floor)
    eligible = [
        name
        for name in FACTOR_NAMES
        if float(effects[name]["main_effect_avg_R"]) > selection_floor
        and int(effects[name]["positive_symbol_effects"]) >= 3
    ]
    selected = sorted(eligible, key=lambda name: float(effects[name]["main_effect_avg_R"]), reverse=True)[:2]
    best_prior_run = max(
        design,
        key=lambda run: (
            float(reports[str(run["run_id"])]["metrics_cost_0.15"]["avg_net_R"]),
            float(reports[str(run["run_id"])]["metrics_cost_0.15"]["profit_factor_R"]),
            -float(reports[str(run["run_id"])]["metrics_cost_0.15"]["max_drawdown_R"]),
        ),
    )
    return {
        "design": list(design),
        "reports": reports,
        "effects": effects,
        "dummy_noise_floor": dummy_floor,
        "selection_floor": selection_floor,
        "selected_positive_factors": selected,
        "best_prior_run": str(best_prior_run["run_id"]),
        "best_prior_factors": dict(best_prior_run["factors"]),
        "interpretation": "PB8 main-effect screening only; interactions are intentionally deferred to frozen confirmation replay.",
    }


def confirmation_configs(screen: Dict[str, Any]) -> List[Dict[str, Any]]:
    selected = list(screen["selected_positive_factors"])
    baseline = {name: False for name in FACTOR_NAMES}
    candidates: List[Tuple[str, Dict[str, bool]]] = [("confirm_baseline", dict(baseline))]
    for name in selected:
        factors = dict(baseline)
        factors[name] = True
        candidates.append((f"confirm_{name}", factors))
    if len(selected) == 2:
        factors = dict(baseline)
        factors[selected[0]] = True
        factors[selected[1]] = True
        candidates.append((f"confirm_{selected[0]}__{selected[1]}", factors))
    candidates.append((f"confirm_prior_best_{screen['best_prior_run']}", dict(screen["best_prior_factors"])))

    deduplicated: List[Dict[str, Any]] = []
    seen: set[Tuple[Tuple[str, bool], ...]] = set()
    for name, factors in candidates:
        key = tuple(sorted((factor, bool(value)) for factor, value in factors.items()))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append({"candidate": name, "factors": factors})
    return deduplicated


def confirmation_gate(report: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    prior = report["prior_cost_0.15"]
    second = report["second_cost_0.15"]
    combined = report["combined_cost_0.15"]
    stress = report["combined_cost_0.20"]
    lower = report["bootstrap_second_cost_0.15"].get("lower_95")
    retention = float(combined["events"] / max(int(baseline["combined_cost_0.15"]["events"]), 1) * 100.0)
    checks = {
        "retention": retention >= CONFIRM_GATE["retention_pct_min"],
        "events_second": int(second["events"]) >= CONFIRM_GATE["events_second_min"],
        "prior_nonnegative": float(prior["avg_net_R"]) >= CONFIRM_GATE["prior_avg_R_min"],
        "second_nonnegative": float(second["avg_net_R"]) >= CONFIRM_GATE["second_avg_R_min"],
        "cost_0.20_survival": float(stress["avg_net_R"]) > CONFIRM_GATE["cost_0.20_avg_R_min_exclusive"],
        "profit_factor": float(combined["profit_factor_R"]) >= CONFIRM_GATE["profit_factor_min"],
        "symbol_breadth": int(combined["positive_symbols"]) >= CONFIRM_GATE["positive_symbols_min"],
        "month_stability": float(combined["positive_month_ratio"]) >= CONFIRM_GATE["positive_month_ratio_min"],
        "bootstrap_second": lower is not None and float(lower) >= CONFIRM_GATE["bootstrap_second_lower_min"],
    }
    return {
        "gate_pass": all(checks.values()),
        "checks": checks,
        "failed_checks": [key for key, value in checks.items() if not value],
        "retention_pct": retention,
        "worst_window_avg_R": min(float(prior["avg_net_R"]), float(second["avg_net_R"])),
    }


def run_confirmation(
    configs: Sequence[Dict[str, Any]],
    raw_cache: Dict[Tuple[str, str], pd.DataFrame],
    signals_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]],
    side_target_map: Dict[str, float],
) -> Tuple[Dict[str, Any], Dict[str, List[Dict[str, Any]]]]:
    reports: Dict[str, Any] = {}
    rows_by_candidate: Dict[str, List[Dict[str, Any]]] = {}
    for index, config in enumerate(configs):
        name = str(config["candidate"])
        rows = replay_config(raw_cache, signals_by_key, config["factors"], side_target_map, name, WINDOWS)
        rows_by_candidate[name] = rows
        prior = [row for row in rows if row["window"] == WINDOWS[0]]
        second = [row for row in rows if row["window"] == WINDOWS[1]]
        reports[name] = {
            "factors": config["factors"],
            "prior_cost_0.15": BASE.metrics(prior, COST_PRIMARY),
            "second_cost_0.15": BASE.metrics(second, COST_PRIMARY),
            "combined_cost_0.15": BASE.metrics(rows, COST_PRIMARY),
            "combined_cost_0.20": BASE.metrics(rows, COST_STRESS),
            "bootstrap_second_cost_0.15": BASE.block_bootstrap_mean_ci(second, COST_PRIMARY, 4100 + index),
        }
    baseline = reports["confirm_baseline"]
    for report in reports.values():
        report["gate"] = confirmation_gate(report, baseline)
    ranking = sorted(
        reports,
        key=lambda name: (
            bool(reports[name]["gate"]["gate_pass"]),
            float(reports[name]["gate"]["worst_window_avg_R"]),
            float(reports[name]["combined_cost_0.15"]["avg_net_R"]),
            float(reports[name]["combined_cost_0.15"]["profit_factor_R"]),
            -float(reports[name]["combined_cost_0.15"]["max_drawdown_R"]),
        ),
        reverse=True,
    )
    return {
        "configs": list(configs),
        "reports": reports,
        "ranking": ranking,
        "gate_pass_candidates": [name for name in ranking if bool(reports[name]["gate"]["gate_pass"])],
        "best_candidate": ranking[0] if ranking else None,
    }, rows_by_candidate


def iter_json_records(obj: Any, inherited_strategy: Optional[str] = None, parent_key: str = "", depth: int = 0) -> Iterator[Dict[str, Any]]:
    if depth > 8:
        return
    if isinstance(obj, dict):
        explicit = next((str(obj[key]) for key in STRATEGY_KEYS if key in obj and obj[key] not in (None, "")), None)
        strategy_name = explicit or inherited_strategy
        pnl_key = next((key for key in PNL_KEYS if key in obj and safe_float(obj[key]) is not None), None)
        ts_key = next((key for key in TIMESTAMP_KEYS if key in obj and timestamp_ms(obj[key]) is not None), None)
        if strategy_name and pnl_key and ts_key:
            symbol = next((str(obj[key]) for key in SYMBOL_KEYS if key in obj and obj[key] not in (None, "")), "UNKNOWN")
            yield {
                "strategy": strategy_name,
                "pnl_r": float(obj[pnl_key]),
                "timestamp_ms": int(timestamp_ms(obj[ts_key]) or 0),
                "symbol": symbol,
                "pnl_key": pnl_key,
                "timestamp_key": ts_key,
            }
        is_strategy_map = parent_key.lower() in PORTFOLIO_PARENT_KEYS
        for key, value in obj.items():
            next_strategy = strategy_name
            if is_strategy_map and isinstance(value, (list, dict)) and key not in STRATEGY_KEYS:
                next_strategy = str(key)
            yield from iter_json_records(value, next_strategy, str(key), depth + 1)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_json_records(value, inherited_strategy, parent_key, depth + 1)


def portfolio_candidate_paths() -> List[Path]:
    runtime = ROOT / "runtime"
    if not runtime.exists():
        return []
    candidates = []
    for path in runtime.glob("*.json"):
        lower = path.name.lower()
        if any(token in lower for token in PORTFOLIO_EXCLUDE_TOKENS):
            continue
        if not any(token in lower for token in PORTFOLIO_NAME_TOKENS):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if 0 < size <= 50 * 1024 * 1024:
            candidates.append(path)
    return sorted(candidates)


def scan_portfolio_sources() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    files = []
    all_rows: List[Dict[str, Any]] = []
    seen = set()
    for path in portfolio_candidate_paths():
        record: Dict[str, Any] = {"path": str(path), "size_bytes": path.stat().st_size}
        try:
            payload = json.loads(path.read_text(errors="ignore"))
            extracted = list(iter_json_records(payload))
            accepted = 0
            strategies = set()
            for row in extracted:
                if not row["strategy"] or int(row["timestamp_ms"]) <= 0:
                    continue
                identity = (str(row["strategy"]), int(row["timestamp_ms"]), str(row["symbol"]), round(float(row["pnl_r"]), 10))
                if identity in seen:
                    continue
                seen.add(identity)
                enriched = dict(row)
                enriched["source"] = str(path)
                all_rows.append(enriched)
                strategies.add(str(row["strategy"]))
                accepted += 1
            record.update({"parsed": True, "rows": accepted, "strategies": sorted(strategies)})
        except Exception as exc:
            record.update({"parsed": False, "rows": 0, "strategies": [], "error": repr(exc)})
        files.append(record)
    strategies = sorted({str(row["strategy"]) for row in all_rows})
    inventory = {
        "status": "PASS_Q4R3_RASCHKE_V3_PORTFOLIO_SOURCE_INVENTORY",
        "files_scanned": len(files),
        "files": files,
        "deduplicated_rows": len(all_rows),
        "strategy_count": len(strategies),
        "strategies": strategies,
        "preliminary_source_ready": len(strategies) >= 5 and len(all_rows) >= 50,
        "full_25_strategy_source_ready": len(strategies) >= 25 and len(all_rows) >= 200,
        "contract": "Only explicit strategy-tagged realized-R rows are accepted; queue membership or configured strategies are not treated as performance data.",
    }
    return inventory, all_rows


def series_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return float(worst)


def block_key(timestamp_value: int) -> int:
    width = 6 * 60 * 60 * 1000
    return int(timestamp_value // width * width)


def portfolio_role(rows: Sequence[Dict[str, Any]], raschke_rows: Sequence[Dict[str, Any]], inventory: Dict[str, Any]) -> Dict[str, Any]:
    if not raschke_rows:
        return {"status": "NO_RASCHKE_ROWS", "role": "UNRESOLVED"}
    start = min(int(row["entry_ts"]) for row in raschke_rows)
    end = max(int(row["exit_ts"]) for row in raschke_rows)
    eligible = [row for row in rows if start <= int(row["timestamp_ms"]) <= end]
    strategies = sorted({str(row["strategy"]) for row in eligible})
    if len(strategies) < 5 or len(eligible) < 50:
        return {
            "status": "PORTFOLIO_SOURCE_NOT_READY",
            "role": "UNRESOLVED",
            "overlap_rows": len(eligible),
            "overlap_strategies": len(strategies),
            "strategies": strategies,
            "required": {"strategies_min_preliminary": 5, "rows_min": 50, "strategies_full": 25},
        }

    by_strategy_block: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for row in eligible:
        by_strategy_block[str(row["strategy"])][block_key(int(row["timestamp_ms"]))] += float(row["pnl_r"])
    raschke_blocks: Dict[int, float] = defaultdict(float)
    for row in raschke_rows:
        raschke_blocks[block_key(int(row["exit_ts"]))] += BASE.net_r(row, COST_PRIMARY)
    blocks = sorted(set(raschke_blocks) | {block for mapping in by_strategy_block.values() for block in mapping})

    scaled: Dict[str, Dict[int, float]] = {}
    strategy_scale: Dict[str, float] = {}
    for strategy_name in strategies:
        values = [float(by_strategy_block[strategy_name].get(block, 0.0)) for block in blocks]
        nonzero = [value for value in values if abs(value) > 1e-12]
        standard_deviation = statistics.pstdev(nonzero) if len(nonzero) >= 2 else 0.0
        scale = 1.0 / standard_deviation if standard_deviation > 1e-9 else 1.0
        strategy_scale[strategy_name] = scale
        scaled[strategy_name] = {block: float(by_strategy_block[strategy_name].get(block, 0.0) * scale) for block in blocks}
    raschke_values_raw = [float(raschke_blocks.get(block, 0.0)) for block in blocks]
    raschke_nonzero = [value for value in raschke_values_raw if abs(value) > 1e-12]
    raschke_std = statistics.pstdev(raschke_nonzero) if len(raschke_nonzero) >= 2 else 0.0
    raschke_scale = 1.0 / raschke_std if raschke_std > 1e-9 else 1.0
    raschke_scaled = {block: float(raschke_blocks.get(block, 0.0) * raschke_scale) for block in blocks}

    base_values = [float(statistics.fmean(scaled[name][block] for name in strategies)) for block in blocks]
    added_values = [
        float((sum(scaled[name][block] for name in strategies) + raschke_scaled[block]) / (len(strategies) + 1))
        for block in blocks
    ]
    raschke_values = [raschke_scaled[block] for block in blocks]
    correlation = None
    if len(blocks) >= 3 and statistics.pstdev(base_values) > 1e-9 and statistics.pstdev(raschke_values) > 1e-9:
        correlation = float(pd.Series(base_values).corr(pd.Series(raschke_values)))
    negative_indexes = [index for index, value in enumerate(base_values) if value < 0]
    crisis_sum = float(sum(raschke_values[index] for index in negative_indexes))
    crisis_positive_ratio = (
        float(sum(1 for index in negative_indexes if raschke_values[index] > 0) / len(negative_indexes))
        if negative_indexes
        else None
    )
    base_mdd = series_drawdown(base_values)
    added_mdd = series_drawdown(added_values)
    base_mean = float(statistics.fmean(base_values)) if base_values else 0.0
    added_mean = float(statistics.fmean(added_values)) if added_values else 0.0

    all_scaled = dict(scaled)
    all_scaled["__RASCHKE_CANDIDATE__"] = raschke_scaled
    all_names = sorted(all_scaled)
    full_values = [float(statistics.fmean(all_scaled[name][block] for name in all_names)) for block in blocks]
    leave_one_out = []
    for name in all_names:
        remaining = [other for other in all_names if other != name]
        without = [float(statistics.fmean(all_scaled[other][block] for other in remaining)) for block in blocks]
        leave_one_out.append(
            {
                "strategy": name,
                "mean_contribution": float(statistics.fmean(full_values) - statistics.fmean(without)),
                "mdd_contribution": float(series_drawdown(full_values) - series_drawdown(without)),
            }
        )
    leave_one_out.sort(key=lambda row: (float(row["mean_contribution"]), -float(row["mdd_contribution"])), reverse=True)
    raschke_rank = next(index + 1 for index, row in enumerate(leave_one_out) if row["strategy"] == "__RASCHKE_CANDIDATE__")

    full_ready = len(strategies) >= 25 and bool(inventory.get("full_25_strategy_source_ready"))
    diversification_pass = added_mdd < base_mdd and crisis_sum > 0 and (correlation is None or correlation < 0.50)
    role = "FULL_25_STRATEGY_DIVERSIFIER" if full_ready and diversification_pass else (
        "PRELIMINARY_DIVERSIFIER" if diversification_pass else "NO_MARGINAL_PORTFOLIO_VALUE"
    )
    return {
        "status": "PASS_Q4R3_RASCHKE_V3_PORTFOLIO_ROLE_AUDIT",
        "role": role,
        "full_25_strategy_conclusion_allowed": full_ready,
        "overlap_rows": len(eligible),
        "overlap_strategies": len(strategies),
        "strategy_names": strategies,
        "block_count_6h": len(blocks),
        "base": {"mean_per_block": base_mean, "max_drawdown": base_mdd},
        "with_raschke": {"mean_per_block": added_mean, "max_drawdown": added_mdd},
        "marginal": {
            "mean_delta": added_mean - base_mean,
            "mdd_delta": added_mdd - base_mdd,
            "correlation_to_base": correlation,
            "crisis_block_R": crisis_sum,
            "crisis_positive_ratio": crisis_positive_ratio,
            "unique_positive_blocks": sum(1 for base, candidate in zip(base_values, raschke_values) if base <= 0 and candidate > 0),
            "diversification_pass": diversification_pass,
        },
        "leave_one_out_rank": raschke_rank,
        "leave_one_out_total": len(leave_one_out),
        "leave_one_out": leave_one_out,
        "normalization": "Each strategy is inverse-volatility scaled on nonzero 6-hour blocks, then equal-strategy weighted. This is a role audit, not an executable allocator.",
    }


def write_html(factorial: Dict[str, Any], portfolio: Dict[str, Any], decision: Dict[str, Any]) -> None:
    rows = []
    confirmation = factorial["confirmation"]
    for name in confirmation["ranking"]:
        report = confirmation["reports"][name]
        combined = report["combined_cost_0.15"]
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{report['gate']['gate_pass']}</td>"
            f"<td>{report['prior_cost_0.15']['avg_net_R']:.4f}</td>"
            f"<td>{report['second_cost_0.15']['avg_net_R']:.4f}</td>"
            f"<td>{combined['avg_net_R']:.4f}</td>"
            f"<td>{combined['profit_factor_R']:.3f}</td>"
            f"<td>{combined['max_drawdown_R']:.3f}</td>"
            f"<td>{html.escape(', '.join(report['gate']['failed_checks']))}</td>"
            "</tr>"
        )
    page = "".join(
        [
            "<!doctype html><html><head><meta charset='utf-8'><title>Raschke factorial and portfolio audit</title>",
            "<style>body{background:#0b0f14;color:#e5e7eb;font-family:Arial;margin:20px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #334155;padding:7px}pre{background:#111827;padding:12px;white-space:pre-wrap}</style></head><body>",
            "<h1>Raschke sparse factorial and portfolio role audit</h1>",
            "<table><thead><tr><th>Candidate</th><th>Gate</th><th>Prior avg R</th><th>Second avg R</th><th>Combined avg R</th><th>PF</th><th>MDD</th><th>Failed</th></tr></thead><tbody>",
            "".join(rows),
            "</tbody></table><h2>Portfolio role</h2><pre>",
            html.escape(json.dumps(portfolio, ensure_ascii=False, indent=2)),
            "</pre><h2>Decision</h2><pre>",
            html.escape(json.dumps(decision, ensure_ascii=False, indent=2)),
            "</pre></body></html>",
        ]
    )
    HTML_OUT.write_text(page, encoding="utf-8")


def main() -> None:
    raw_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    signals_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    raw_integrity: Dict[str, Any] = {}
    for window in WINDOWS:
        for symbol in SYMBOLS:
            key = (window, symbol)
            raw, integrity = BASE.V2.load_raw(BASE.raw_path(window, symbol))
            raw_cache[key] = raw
            raw_integrity[f"{window}|{symbol}"] = integrity
            signals_by_key[key] = BASE.generate_signals(raw, symbol, window)

    side_target_map, side_target_training_audit = BASE.choose_prior_side_targets(raw_cache, signals_by_key)
    design = hadamard_screening_design()
    prior_rows_by_run: Dict[str, List[Dict[str, Any]]] = {}
    for run in design:
        prior_rows_by_run[str(run["run_id"])] = replay_config(
            raw_cache,
            signals_by_key,
            run["factors"],
            side_target_map,
            str(run["run_id"]),
            (WINDOWS[0],),
        )
    screen = estimate_effects(design, prior_rows_by_run)
    configs = confirmation_configs(screen)
    confirmation, confirmation_rows = run_confirmation(configs, raw_cache, signals_by_key, side_target_map)
    best_candidate = str(confirmation["best_candidate"])
    best_rows = confirmation_rows.get(best_candidate, [])

    inventory, portfolio_rows = scan_portfolio_sources()
    portfolio = portfolio_role(portfolio_rows, best_rows, inventory)

    independent_pass = bool(confirmation["gate_pass_candidates"])
    portfolio_pass = str(portfolio.get("role")) in {"FULL_25_STRATEGY_DIVERSIFIER", "PRELIMINARY_DIVERSIFIER"}
    full_portfolio = bool(portfolio.get("full_25_strategy_conclusion_allowed"))
    if independent_pass:
        route = "A_INDEPENDENT_GATE_PASS_FOURTH_SHADOW_CANDIDATE"
        action = "FOURTH_SHADOW_CANDIDATE_OBSERVER_ONLY"
    elif portfolio_pass and full_portfolio:
        route = "B_INDEPENDENT_FAIL_PORTFOLIO_PASS_RESERVE_ENSEMBLE"
        action = "RESERVE_ENSEMBLE_CANDIDATE"
    elif portfolio_pass:
        route = "B_PRELIMINARY_PORTFOLIO_VALUE_NEEDS_FULL_25_SOURCE"
        action = "HOLD_PRELIMINARY_DIVERSIFIER"
    elif str(portfolio.get("status")) == "PORTFOLIO_SOURCE_NOT_READY":
        route = "PORTFOLIO_UNRESOLVED_SOURCE_NOT_READY"
        action = "HOLD_AND_BIND_25_STRATEGY_REALIZED_LEDGER"
    else:
        route = "C_INDEPENDENT_AND_PORTFOLIO_FAIL_FREEZE_RASCHKE"
        action = "FREEZE_AS_DIAGNOSTIC_MATERIAL"

    factorial = {
        "status": "PASS_Q4R3_RASCHKE_V3_SPARSE_FACTORIAL",
        "verdict": "PB8_PRIOR_SCREEN_AND_FROZEN_SECOND_WINDOW_CONFIRMATION_COMPLETE",
        "factors": FACTOR_NAMES,
        "side_target_map_prior_only": side_target_map,
        "side_target_training_audit": side_target_training_audit,
        "screen": screen,
        "confirmation": confirmation,
        "best_candidate": best_candidate,
        "raw_integrity": raw_integrity,
        "signal_counts": {f"{window}|{symbol}": len(signals_by_key[(window, symbol)]) for window in WINDOWS for symbol in SYMBOLS},
        "limitations": [
            "PB8 estimates main effects efficiently but aliases interactions; only selected factors and the prior-best run are confirmed on the second window.",
            "No result from the second window is used to select screening factors or side-specific targets.",
        ],
    }
    decision = {
        "status": "PASS_Q4R3_RASCHKE_V3_FACTORIAL_PORTFOLIO_DECISION",
        "verdict": route,
        "action": action,
        "independent_gate_pass_candidates": confirmation["gate_pass_candidates"],
        "best_independent_candidate": best_candidate,
        "portfolio_role": portfolio.get("role"),
        "portfolio_source_strategy_count": inventory.get("strategy_count"),
        "full_25_strategy_conclusion_allowed": full_portfolio,
        "research_stop_rule": {
            "if_independent_pass": "fourth_shadow_candidate_observer_only",
            "if_independent_fail_portfolio_pass": "reserve_or_ensemble_component",
            "if_both_fail_with_full_source": "freeze_raschke_and_move_to_next_strategy",
            "if_portfolio_source_missing": "bind_realized_25_strategy_ledger_before_final_role_decision",
        },
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
    trial = {
        "status": "PASS_Q4R3_RASCHKE_V3_FACTORIAL_PORTFOLIO_TRIAL",
        "trial_id": "q4r3_raschke_v3_factorial_portfolio_001",
        "selection_order": [
            "prior_only_PB8_main_effect_screen",
            "dummy_noise_floor",
            "positive_effect_on_at_least_three_symbols",
            "freeze_top_two_and_prior_best",
            "second_window_confirmation",
            "portfolio_role_only_from_explicit_strategy_tagged_realized_R",
        ],
        "factor_contract": {
            "long_only": "bidirectional versus long-only",
            "side_specific_target": "fixed 2R versus prior-trained long/short target map",
            "time_stop_120m_unless_1R": "none versus close at 120 minutes if MFE remains below 1R",
            "trend_1h_4h_alignment": "none versus sign agreement of pre-entry 60-minute and 240-minute returns",
            "link_reserve": "LINK included versus excluded from active lane",
        },
        "gate": CONFIRM_GATE,
        "no_threshold_search_after_results": True,
        "no_final_holdout_access": True,
        "no_strategy_mutation": True,
    }

    write_html(factorial, portfolio, decision)
    atomic_json(FACTORIAL_OUT, factorial)
    atomic_json(FACTORIAL_TRADES_OUT, {"status": "PASS", "confirmation_trades": confirmation_rows})
    atomic_json(PORTFOLIO_INVENTORY_OUT, inventory)
    atomic_json(PORTFOLIO_OUT, portfolio)
    atomic_json(DECISION_OUT, decision)
    atomic_json(TRIAL_OUT, trial)
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    print(json.dumps({"screen_selected": screen["selected_positive_factors"], "confirmation_ranking": confirmation["ranking"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
