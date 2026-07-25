from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "backend/contracts/ZOS_STRATEGY_INDICATOR_CONTRACTS_v1.json"
REPORT_DIR = ROOT / "artifacts/strategy_indicator_contract_audit_v1"


TOKEN_PATTERNS: dict[str, tuple[str, ...]] = {
    "ema": (r"\bema\b", r"_ema\(", r"ewm\("),
    "ema_ribbon": (r"ribbon", r"ema_?\d+", r"ema_(fast|mid|slow|trend)"),
    "atr": (r"\batr\b", r"_atr\("),
    "rsi": (r"\brsi\b", r"_rsi\("),
    "bollinger": (r"bollinger", r"bb_upper", r"bb_lower", r"bb_basis"),
    "macd": (r"\bmacd\b", r"macd_hist"),
    "vwap": (r"\bvwap\b", r"_calc_vwap"),
    "anchor": (r"anchor", r"anchored"),
    "breakout": (r"break(out|_)" ,),
    "retest": (r"retest", r"reclaim"),
    "volume": (r"\bvolume\b", r"vol_ma", r"volume_z"),
    "volume_spike": (r"volume_spike", r"vol(ume)?_z", r"spike_ok", r"vol_mult"),
    "grid": (r"\bgrid\b", r"grid_step"),
    "trend_veto": (r"trend_veto", r"veto_(long|short)", r"adx"),
    "keltner": (r"keltner", r"kc_upper", r"kc_lower"),
    "swing": (r"swing_high", r"swing_low", r"lookback"),
    "wick": (r"upper_wick", r"lower_wick", r"wick_body"),
    "reclaim": (r"reclaim",),
    "mfi": (r"\bmfi\b", r"_mfi\("),
    "divergence": (r"diverg", r"makes_lower_low", r"makes_higher_high"),
    "obv": (r"\bobv\b", r"_obv\("),
    "pivot": (r"\bpivot\b", r"swing_high", r"swing_low"),
    "range": (r"\brange\b", r"box_height", r"high_max", r"low_min"),
    "sideways": (r"sideways", r"ema_flat", r"max_box_pct"),
    "reversal": (r"reversal", r"rev_buy", r"rev_sell"),
    "swing_failure": (r"swing_fail", r"had_oversold", r"had_overbought"),
    "snap_reversal": (r"snap_(long|short)", r"snap_drive", r"snap_reversal"),
    "session": (r"session", r"asia", r"london", r"newyork"),
    "squeeze_release": (r"squeeze_on", r"released", r"prev_squeeze"),
    "support_resistance": (r"support", r"resistance", r"sr_levels", r"swing_high", r"swing_low"),
    "supertrend": (r"supertrend", r"\bst\b", r"st_len", r"st_mult"),
    "pullback": (r"pullback", r"dip_add"),
    "trend_continuation": (r"trend_cont", r"trend_(long|short)"),
    "donchian": (r"donchian", r"dc_high", r"dc_low"),
    "pyramiding": (r"pyramiding", r"add_count"),
    "mean_reversion": (r"mean_reversion", r"revert", r"fade"),
    "fvg": (r"\bfvg\b", r"fair.?value.?gap", r"gap_(up|down)"),
    "trend": (r"trend_(long|short)", r"ema_(fast|slow|trend)"),
}


@dataclass
class SourceRecord:
    path: str
    strategy_ids: list[str]
    is_wrapper: bool
    has_strategy_function: bool
    has_run_function: bool
    detected: dict[str, bool]
    structural: dict[str, bool]
    syntax_ok: bool
    syntax_error: str | None


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _strategy_ids(text: str, path: Path, known: set[str]) -> list[str]:
    found: set[str] = set()
    for pattern in (
        r"STRATEGY_ID\s*=\s*['\"]([^'\"]+)['\"]",
        r"strategy_name\s*=\s*['\"]([^'\"]+)['\"]",
        r"_impl\(\s*['\"]([^'\"]+)['\"]",
        r"legendary_(?:mean_reversion|trend_continuation|breakout)\(\s*['\"]([^'\"]+)['\"]",
    ):
        found.update(re.findall(pattern, text))

    stem = path.stem.lower()
    candidates = {
        stem,
        re.sub(r"_(legendary|authentic|strategy|v\d+)$", "", stem),
        re.sub(r"_(legendary|authentic|strategy|v\d+)", "", stem),
    }
    for candidate in candidates:
        if candidate in known:
            found.add(candidate)
    return sorted(found & known)


def _detected(text: str) -> dict[str, bool]:
    lowered = text.lower()
    return {
        name: any(re.search(pattern, lowered, flags=re.I) for pattern in patterns)
        for name, patterns in TOKEN_PATTERNS.items()
    }


def _distinct_ema_lengths(text: str) -> set[int]:
    values: set[int] = set()
    for match in re.finditer(r"ema(?:_[a-z]+)?_len\s*:\s*int\s*=\s*(\d+)", text, flags=re.I):
        values.add(int(match.group(1)))
    for match in re.finditer(r"ema(?:_[a-z]+)?_len\s*=\s*(\d+)", text, flags=re.I):
        values.add(int(match.group(1)))
    return values


def _structural(text: str) -> dict[str, bool]:
    lowered = text.lower()
    ema_lengths = _distinct_ema_lengths(text)
    three_candle = bool(
        re.search(r"shift\(\s*2\s*\)", lowered)
        or re.search(r"iloc\[\s*-3\s*\]", lowered)
        or re.search(r"\bi\s*-\s*2\b", lowered)
        or re.search(r"prev2", lowered)
    )
    explicit_overlap = bool(
        "overlap" in lowered
        and (
            re.search(r"london.*newyork|newyork.*london", lowered, flags=re.S)
            or re.search(r"if\s+.*(?:london|ny).*and.*(?:ny|london)", lowered)
        )
    )
    volume_gate = bool(
        re.search(r"(?:long|short)_(?:setup|signal|entry).*volume", lowered, flags=re.S)
        or re.search(r"volume.*(?:long|short)_(?:setup|signal|entry)", lowered, flags=re.S)
        or re.search(r"(?:spike_ok|volume_spike|vol_ok)\s+and", lowered)
        or re.search(r"and\s+(?:spike_ok|volume_spike|vol_ok)", lowered)
    )
    confirmed_anchor = bool(
        re.search(r"confirmed_(?:swing|anchor)|anchor_(?:ts|index|idx)", lowered)
        and not re.search(r"(?:idxmax|idxmin)\(\).*(?:last|recent)|recent.*(?:idxmax|idxmin)\(\)", lowered, flags=re.S)
    )
    range_gate = bool(
        "adx" in lowered
        or "range_regime" in lowered
        or "sideways" in lowered
        or "ema_flat" in lowered
        or ("max_atr_pct" in lowered and "trend_veto" in lowered)
    )
    next_bar = bool(
        "next_bar" in lowered
        or "pending_entry" in lowered
        or re.search(r"signal_(?:idx|index|ts).*entry_(?:idx|index|ts)", lowered, flags=re.S)
    )
    return {
        "at_least_three_distinct_ema_lengths": len(ema_lengths) >= 3,
        "scalp_specific_trigger": bool("scalp" in lowered and ("snap" in lowered or "impulse" in lowered or "reclaim" in lowered)),
        "three_candle_fvg": three_candle,
        "explicit_overlap_precedence": explicit_overlap,
        "timezone_explicit": bool("zoneinfo" in lowered or "timezone" in lowered or "session_tz" in lowered),
        "volume_spike_is_entry_gate": volume_gate,
        "confirmed_anchor_not_rolling_extreme": confirmed_anchor,
        "range_regime_gate": range_gate,
        "bar_close_then_next_bar_entry": next_bar,
    }


def _source_records(known: set[str]) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    base = ROOT / "backend/strategies"
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = _read(path)
        ids = _strategy_ids(text, path, known)
        if not ids:
            continue
        syntax_ok = True
        syntax_error = None
        try:
            ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            syntax_ok = False
            syntax_error = f"{exc.msg}:{exc.lineno}:{exc.offset}"
        records.append(
            SourceRecord(
                path=str(path.relative_to(ROOT)),
                strategy_ids=ids,
                is_wrapper=bool(re.search(r"\b_impl\s*\(", text)),
                has_strategy_function=bool(re.search(r"^def\s+strategy\s*\(", text, flags=re.M)),
                has_run_function=bool(re.search(r"^def\s+run_[a-zA-Z0-9_]+\s*\(", text, flags=re.M)),
                detected=_detected(text),
                structural=_structural(text),
                syntax_ok=syntax_ok,
                syntax_error=syntax_error,
            )
        )
    return records


def _audit() -> dict[str, Any]:
    contract = json.loads(_read(CONTRACT_PATH))
    contracts: dict[str, dict[str, Any]] = contract["strategies"]
    known = set(contracts)
    records = _source_records(known)
    by_id: dict[str, list[SourceRecord]] = defaultdict(list)
    for record in records:
        for strategy_id in record.strategy_ids:
            by_id[strategy_id].append(record)

    strategy_results: dict[str, Any] = {}
    hard_blockers: list[str] = []
    warnings: list[str] = []

    for strategy_id, spec in contracts.items():
        sources = by_id.get(strategy_id, [])
        direct = [r for r in sources if not r.is_wrapper and r.has_strategy_function]
        wrappers = [r for r in sources if r.is_wrapper]
        merged_detected = {
            key: any(record.detected.get(key, False) for record in sources)
            for key in TOKEN_PATTERNS
        }
        merged_structural = {
            key: any(record.structural.get(key, False) for record in sources)
            for key in _structural("")
        }
        missing_core = [name for name in spec.get("core", []) if not merged_detected.get(name, False)]
        missing_structural = [name for name in spec.get("structural", []) if not merged_structural.get(name, False)]
        syntax_failures = [r.path for r in sources if not r.syntax_ok]

        if not sources:
            hard_blockers.append(f"{strategy_id}:NO_SOURCE")
        if missing_core:
            hard_blockers.append(f"{strategy_id}:MISSING_CORE:{','.join(missing_core)}")
        if missing_structural:
            hard_blockers.append(f"{strategy_id}:MISSING_STRUCTURAL:{','.join(missing_structural)}")
        if syntax_failures:
            hard_blockers.append(f"{strategy_id}:SYNTAX_ERROR:{','.join(syntax_failures)}")
        if len(direct) > 1:
            warnings.append(f"{strategy_id}:MULTIPLE_DIRECT_OWNERS:{','.join(r.path for r in direct)}")
        if sources and not direct and wrappers:
            warnings.append(f"{strategy_id}:WRAPPER_ONLY:{','.join(r.path for r in wrappers)}")

        strategy_results[strategy_id] = {
            "contract": spec,
            "sources": [asdict(record) for record in sources],
            "direct_owner_candidates": [r.path for r in direct],
            "wrapper_candidates": [r.path for r in wrappers],
            "missing_core": missing_core,
            "missing_structural": missing_structural,
            "syntax_failures": syntax_failures,
            "status": "PASS" if not (missing_core or missing_structural or syntax_failures or not sources) else "HOLD",
        }

    return {
        "schema_version": "1.0",
        "authority": contract.get("authority"),
        "strategy_count_expected": len(contracts),
        "strategy_count_found": sum(bool(by_id.get(strategy_id)) for strategy_id in contracts),
        "source_record_count": len(records),
        "hard_blocker_count": len(hard_blockers),
        "warning_count": len(warnings),
        "hard_blockers": hard_blockers,
        "warnings": warnings,
        "strategies": strategy_results,
        "state": "PASS" if not hard_blockers else "HOLD",
        "next": "LOCK_RUNTIME_OWNERS_AND_REPAIR_HARD_BLOCKERS" if hard_blockers else "RUN_OOS_PARITY_VALIDATION",
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Indicator Contract Audit v1",
        "",
        f"- state: **{report['state']}**",
        f"- strategies found: **{report['strategy_count_found']}/{report['strategy_count_expected']}**",
        f"- source records: **{report['source_record_count']}**",
        f"- hard blockers: **{report['hard_blocker_count']}**",
        f"- warnings: **{report['warning_count']}**",
        "",
        "## Strategy Matrix",
        "",
        "| strategy | status | direct owners | wrappers | missing core | missing structural |",
        "|---|---:|---:|---:|---|---|",
    ]
    for strategy_id, item in report["strategies"].items():
        lines.append(
            "| {sid} | {status} | {direct} | {wrap} | {core} | {struct} |".format(
                sid=strategy_id,
                status=item["status"],
                direct=len(item["direct_owner_candidates"]),
                wrap=len(item["wrapper_candidates"]),
                core=", ".join(item["missing_core"]) or "-",
                struct=", ".join(item["missing_structural"]) or "-",
            )
        )
    lines.extend(["", "## Hard Blockers", ""])
    lines.extend(f"- `{item}`" for item in report["hard_blockers"] or ["NONE"])
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- `{item}`" for item in report["warnings"] or ["NONE"])
    return "\n".join(lines) + "\n"


def main() -> int:
    report = _audit()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "audit.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "audit.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "STATE": report["state"],
        "STRATEGIES": f"{report['strategy_count_found']}/{report['strategy_count_expected']}",
        "SOURCE_RECORDS": report["source_record_count"],
        "HARD_BLOCKERS": report["hard_blocker_count"],
        "WARNINGS": report["warning_count"],
        "NEXT": report["next"],
    }, sort_keys=True))
    for blocker in report["hard_blockers"]:
        print(f"BLOCKER={blocker}")
    for warning in report["warnings"]:
        print(f"WARNING={warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
