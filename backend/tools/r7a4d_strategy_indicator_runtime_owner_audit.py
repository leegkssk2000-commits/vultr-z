from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

CONTRACT_REL = Path("backend/contracts/ZOS_25_STRATEGY_INDICATOR_CONTRACT_v1.json")
OUTPUT_DIRNAME = "r7a4d_strategy_indicator_runtime_owner_audit_v1"

SEARCH_ROOTS = (
    Path("backend/strategies"),
    Path("strategies"),
    Path("backend/bots"),
    Path("backend/engine"),
    Path("engine"),
)

CODE_SUFFIXES = {".py", ".json", ".yaml", ".yml"}

ALIASES = {
    "BollingerBands": ("bollinger", "bb_upper", "bb_lower", "bb_basis"),
    "KeltnerChannel": ("keltner", "kc_upper", "kc_lower", "kc_center"),
    "SuperTrend": ("supertrend", "st_mult", "st_len"),
    "AnchoredVWAP": ("anchored_vwap", "anchor_vwap", "avwap"),
    "VWAP": ("vwap",),
    "EMA": ("ema",),
    "EMA_ribbon": ("ema_ribbon", "ribbon"),
    "fast_MA": ("ema_fast", "ma_fast"),
    "slow_MA": ("ema_slow", "ma_slow"),
    "trend_MA": ("trend_ma", "ema_len"),
    "MACD": ("macd",),
    "RSI": ("rsi",),
    "MFI": ("mfi",),
    "ATR": ("atr",),
    "ATR_N": ("atr", "n_unit"),
    "OBV": ("obv",),
    "OBV_MA": ("obv_ma",),
    "DonchianChannel": ("donchian", "dc_high", "dc_low"),
    "volume": ("volume", "vol_"),
    "volume_spike_zscore_or_ratio": ("volume_z", "vol_z", "volume_spike", "vol_mult"),
    "three_candle_FVG": ("fvg", "fair_value_gap", "i-2", "shift(2)"),
    "timezone_session_clock": ("zoneinfo", "timezone", "session"),
    "confirmed_pivots": ("pivot", "swing_high", "swing_low"),
    "confirmed_support_resistance": ("support", "resistance", "sr_", "swing_high", "swing_low"),
    "range_boundaries": ("range_high", "range_low", "high_max", "low_min"),
    "grid_anchor": ("grid", "anchor"),
    "ATR_grid_spacing": ("grid", "atr"),
    "range_regime": ("adx", "range", "sideways"),
    "trend_veto": ("trend_veto", "not trend", "trend_"),
    "inventory_limits": ("inventory", "max_add", "pyramiding", "position"),
    "reentry_reset": ("reset", "cooldown", "reentry", "last_entry"),
    "cost_model": ("fee", "slippage", "funding", "cost_bps"),
}


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_NOT_OBJECT:{path}")
    return value


def files_under(root: Path) -> List[Path]:
    found: List[Path] = []
    for rel in SEARCH_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in CODE_SUFFIXES and "__pycache__" not in path.parts:
                found.append(path)
    return sorted(set(found))


def normalized_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").lower()


def strategy_candidates(strategy: str, paths: Sequence[Path]) -> List[Path]:
    token = strategy.lower()
    compact = token.replace("_", "")
    results: List[Path] = []
    for path in paths:
        rel = str(path).lower()
        name = path.stem.lower()
        if token in rel or compact in name.replace("_", ""):
            results.append(path)
            continue
        text = normalized_text(path)
        if f'"{token}"' in text or f"'{token}'" in text or f"strategy_name = \"{token}\"" in text:
            results.append(path)
    return sorted(set(results))


def has_any(text: str, terms: Iterable[str]) -> bool:
    return any(str(term).lower() in text for term in terms)


def indicator_presence(text: str, indicator: str) -> bool:
    terms = ALIASES.get(indicator, (indicator,))
    return has_any(text, terms)


def python_functions(path: Path) -> List[str]:
    if path.suffix != ".py":
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owner_score(path: Path, strategy: str) -> int:
    text = normalized_text(path)
    score = 0
    if path.stem.lower() == strategy.lower():
        score += 10
    if f'strategy_name = "{strategy.lower()}"' in text or f"strategy_name = '{strategy.lower()}'" in text:
        score += 8
    funcs = python_functions(path)
    if "strategy" in funcs:
        score += 6
    if any(name.startswith("run_") for name in funcs):
        score += 4
    if "generic_legendary_templates" in text or "_impl(" in text:
        score -= 5
    if "authentic" in path.parts:
        score += 3
    return score


def audit_strategy(root: Path, strategy: str, spec: Mapping[str, Any], paths: Sequence[Path]) -> Dict[str, Any]:
    candidates = strategy_candidates(strategy, paths)
    candidate_rows: List[Dict[str, Any]] = []
    merged_text = "\n".join(normalized_text(path) for path in candidates)
    for path in candidates:
        candidate_rows.append({
            "path": str(path.relative_to(root)),
            "sha256": sha256(path),
            "owner_score": owner_score(path, strategy),
            "functions": python_functions(path),
            "generic_wrapper": "generic_legendary_templates" in normalized_text(path) or "_impl(" in normalized_text(path),
        })
    candidate_rows.sort(key=lambda row: (-int(row["owner_score"]), str(row["path"])))
    top_score = candidate_rows[0]["owner_score"] if candidate_rows else None
    top_owners = [row for row in candidate_rows if row["owner_score"] == top_score and top_score is not None]
    core = [str(value) for value in spec.get("core", [])]
    presence = {indicator: indicator_presence(merged_text, indicator) for indicator in core}
    missing = sorted(indicator for indicator, present in presence.items() if not present)
    required_fix = [str(value) for value in spec.get("required_fix", [])]

    lifecycle_checks = {
        "required_columns": has_any(merged_text, ("required_cols", "required_columns")),
        "warmup_bars": has_any(merged_text, ("min_bars", "warmup", "not_enough_bars", "short")),
        "entry_timing": has_any(merged_text, ("shift(1)", "prev", "previous", "next_bar", "bar_close")),
        "stop": has_any(merged_text, ("stop", "sl", "trail")),
        "profit_exit": has_any(merged_text, ("tp", "take_profit", "profit", "exit")),
        "reentry_reset": has_any(merged_text, ALIASES["reentry_reset"]),
        "cost_model": has_any(merged_text, ALIASES["cost_model"]),
        "indicator_output_trace": has_any(merged_text, ("indicators", "payload", "decision_trace")),
    }
    lifecycle_missing = sorted(key for key, ok in lifecycle_checks.items() if not ok)
    wrapper_only = bool(candidate_rows) and all(bool(row["generic_wrapper"]) for row in candidate_rows)
    owner_ambiguous = len(top_owners) != 1
    status = "PASS"
    blockers: List[str] = []
    if not candidates:
        blockers.append("NO_IMPLEMENTATION_CANDIDATE")
    if owner_ambiguous:
        blockers.append("RUNTIME_OWNER_NOT_UNIQUE")
    if missing:
        blockers.append("CORE_INDICATOR_MISSING")
    if lifecycle_missing:
        blockers.append("LIFECYCLE_CONTRACT_MISSING")
    if wrapper_only:
        blockers.append("GENERIC_WRAPPER_ONLY")
    if str(spec.get("status")) in {"STRUCTURAL_MISMATCH", "PARTIAL"}:
        blockers.append(f"PREDECLARED_{spec.get('status')}")
    if blockers:
        status = "HOLD"
    return {
        "strategy": strategy,
        "status": status,
        "declared_status": spec.get("status"),
        "candidate_count": len(candidate_rows),
        "runtime_owner": top_owners[0]["path"] if len(top_owners) == 1 else None,
        "runtime_owner_ambiguous": owner_ambiguous,
        "candidates": candidate_rows,
        "core_indicator_presence": presence,
        "missing_core_indicators": missing,
        "required_fix": required_fix,
        "lifecycle_checks": lifecycle_checks,
        "missing_lifecycle_fields": lifecycle_missing,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--target-sha", default="UNKNOWN")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    contract_path = root / CONTRACT_REL
    contract = load_json(contract_path)
    strategies = contract.get("strategies")
    if not isinstance(strategies, dict) or len(strategies) != 25:
        raise ValueError("CONTRACT_STRATEGY_COUNT_NOT_25")
    paths = files_under(root)
    results = [audit_strategy(root, name, spec, paths) for name, spec in sorted(strategies.items())]
    pass_count = sum(row["status"] == "PASS" for row in results)
    hold_count = len(results) - pass_count
    unique_owner_count = sum(row["runtime_owner"] is not None for row in results)
    summary = {
        "state": "PASS_25_STRATEGY_CONTRACT_AND_OWNER_AUDIT" if hold_count == 0 else "HOLD_25_STRATEGY_CONTRACT_OR_OWNER_GAPS",
        "authority": "RESEARCH_ONLY_NO_EXECUTION",
        "target_sha": args.target_sha,
        "contract": str(CONTRACT_REL),
        "strategy_count": len(results),
        "pass_count": pass_count,
        "hold_count": hold_count,
        "unique_runtime_owner_count": unique_owner_count,
        "searched_file_count": len(paths),
        "source_strategy_mutated": False,
        "registry_mutated": False,
        "service_mutated": False,
        "live_enabled": False,
        "results": results,
        "next_stage": "FIX_ONE_STRUCTURAL_MISMATCH_AT_A_TIME" if hold_count else "RUN_PER_STRATEGY_OOS_CONTRACT_REPLAY"
    }
    out_dir = root / "runtime" / OUTPUT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary_v1.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if len(results) == 25 else 2


if __name__ == "__main__":
    raise SystemExit(main())
