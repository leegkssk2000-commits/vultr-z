from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "backend/contracts/ZOS_STRATEGY_INDICATOR_CONTRACTS_v1.json"
REPORT_DIR = ROOT / "artifacts/strategy_indicator_contract_audit_v1"


TOKEN_PATTERNS: dict[str, tuple[str, ...]] = {
    "ema": (r"\bema\b", r"_ema\(", r"ewm\("),
    "ema_ribbon": (r"ribbon_(?:long|short)", r"ema1_len", r"ema2_len", r"ema3_len"),
    "atr": (r"\batr\b", r"_atr\("),
    "rsi": (r"\brsi\b", r"_rsi\("),
    "bollinger": (r"bollinger", r"bb_upper", r"bb_lower", r"bb_basis"),
    "macd": (r"\bmacd\b", r"macd_hist"),
    "vwap": (r"\bvwap\b", r"_vwap", r"_calc_vwap"),
    "anchor": (r"anchor", r"anchored"),
    "box": (r"box_high", r"box_low", r"tight_box"),
    "breakout": (r"breakout", r"long_break", r"short_break"),
    "retest": (r"retest", r"reclaim"),
    "reclaim": (r"reclaim",),
    "volume": (r"\bvolume\b", r"vol_ma", r"vol_now"),
    "volume_spike": (r"vol_spike", r"spike_ok", r"vol_mult"),
    "grid": (r"grid_step", r"grid_rebalance", r"\bk\s*="),
    "trend_veto": (r"trend_veto", r"long_veto", r"short_veto", r"not trend_(?:long|short)"),
    "keltner": (r"kc_upper", r"kc_lower", r"keltner"),
    "swing": (r"swing_high", r"swing_low"),
    "wick": (r"upper_wick", r"lower_wick", r"wick_ratio"),
    "mfi": (r"\bmfi\b", r"_mfi\("),
    "divergence": (r"diverg", r"makes_lower_low", r"makes_higher_high"),
    "obv": (r"\bobv\b", r"_obv\("),
    "pivot": (r"pivot", r"swing_high", r"swing_low"),
    "range": (r"session_high", r"session_low", r"box_height", r"high_max", r"low_min", r"range_high"),
    "sideways": (r"sideways", r"ema_flat", r"max_box_pct"),
    "reversal": (r"reversal", r"rev_buy", r"rev_sell"),
    "swing_failure": (r"swing_fail", r"had_oversold", r"had_overbought"),
    "snap_reversal": (r"snap_long", r"snap_short", r"snap_drive"),
    "session": (r"session_name", r"asia", r"london", r"newyork"),
    "squeeze_release": (r"squeeze_on", r"released", r"prev_squeeze"),
    "support_resistance": (r"sr_levels", r"swing_high", r"swing_low"),
    "supertrend": (r"supertrend", r"st_len", r"st_mult"),
    "pullback": (r"pullback", r"dip_add"),
    "trend_continuation": (r"trend_long", r"trend_short", r"st_rising", r"st_falling"),
    "donchian": (r"donchian", r"dc_high", r"dc_low"),
    "pyramiding": (r"pyramiding", r"add_count"),
    "mean_reversion": (r"revert", r"fade", r"mean_reversion"),
    "fvg": (r"fvg", r"gap_dir", r"gap_low", r"gap_high"),
}


@dataclass
class StrategyAudit:
    strategy_id: str
    path: str
    callable: str
    source_sha_registry: str
    source_sha_actual: str | None
    source_sha_match: bool
    source_exists: bool
    syntax_ok: bool
    callable_exists: bool
    missing_core: list[str]
    missing_hard_structural: list[str]
    review_findings: list[str]
    required_column_failures: list[str]
    lookahead_findings: list[str]
    authority_findings: list[str]
    risk_contract_ok: bool
    long_short_contract_ok: bool
    status: str


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _callable_names(source: str, filename: str) -> set[str]:
    tree = ast.parse(source, filename=filename)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}.{child.name}")
    return names


def _has_token(source: str, token: str) -> bool:
    return any(re.search(pattern, source, flags=re.I) for pattern in TOKEN_PATTERNS.get(token, (re.escape(token),)))


def _structural_checks(source: str) -> dict[str, bool]:
    compact = re.sub(r"\s+", " ", source.lower())
    ema_lengths = {int(v) for v in re.findall(r"ema\d*_len\s*:\s*int\s*=\s*(\d+)", source, flags=re.I)}
    return {
        "reference_box_excludes_signal_bar": bool(
            re.search(r"box\s*=\s*df\.iloc\[-\(cfg\.box_bars\s*\+\s*1\):-1\]", compact)
            or re.search(r"box\s*=\s*df\.iloc\[-cfg\.box_bars\s*-\s*1:-1\]", compact)
        ),
        "at_least_three_distinct_ema_lengths": len(ema_lengths) >= 3,
        "scalp_specific_trigger": bool("ribbon_long" in compact and "body_atr" in compact and "reclaim" in compact),
        "three_candle_fvg": bool(
            re.search(r"i\s*-\s*2", compact)
            and re.search(r"high.*i\s*-\s*2", compact)
            and re.search(r"low.*i\]", compact)
        ),
        "reference_range_excludes_signal_bar": bool(
            re.search(r"recent\s*=\s*df\.iloc\[-\(cfg\.range_lookback\s*\+\s*1\):-1\]", compact)
        ),
        "explicit_overlap_precedence": bool(
            re.search(r"london_active\s+and\s+ny_active", compact)
            or re.search(r"ny_active\s+and\s+london_active", compact)
        ),
        "timezone_explicit": bool("zoneinfo" in compact and "session_tz" in compact),
        "reference_levels_exclude_signal_bar": bool(
            re.search(r"recent\s*=\s*df\.iloc\[-\(cfg\.lookback\s*\+\s*1\):-1\]", compact)
        ),
        "volume_spike_is_entry_gate": bool(
            re.search(r"short_fade_setup\s*=\s*spike_ok\s+and", compact)
            and re.search(r"long_fade_setup\s*=\s*spike_ok\s+and", compact)
        ),
    }


def _lookahead_findings(source: str) -> list[str]:
    findings: list[str] = []
    patterns = {
        "NEGATIVE_SHIFT": r"\.shift\(\s*-\d+",
        "CENTERED_ROLLING": r"rolling\([^\)]*center\s*=\s*true",
        "FUTURE_ILOC": r"iloc\[[^\]]*(?:i|idx)\s*\+\s*\d+",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, source, flags=re.I):
            findings.append(label)
    return findings


def _authority_findings(source: str) -> list[str]:
    findings: list[str] = []
    patterns = {
        "NETWORK_IMPORT": r"\bimport\s+(?:requests|httpx|aiohttp|ccxt)\b|\bfrom\s+(?:requests|httpx|aiohttp|ccxt)\b",
        "SUBPROCESS": r"\bsubprocess\b|\bos\.system\b",
        "ORDER_AUTHORITY": r"place_order|create_order|send_order|real_order_enabled\s*=\s*true|live_enabled\s*=\s*true",
        "FILE_WRITE": r"write_text\(|write_bytes\(|open\([^\)]*,\s*['\"](?:w|a|x)",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, source, flags=re.I):
            findings.append(label)
    return findings


def _required_column_failures(source: str, columns: list[str]) -> list[str]:
    failures: list[str] = []
    for column in columns:
        required_patterns = (
            rf"required(?:_cols)?\s*=\s*\{{[^\}}]*['\"]{re.escape(column)}['\"]",
            rf"required\s*=\s*\{{[^\}}]*['\"]{re.escape(column)}['\"]",
        )
        if not any(re.search(pattern, source, flags=re.I | re.S) for pattern in required_patterns):
            failures.append(column)
    return failures


def _audit_strategy(strategy_id: str, spec: Mapping[str, Any], row: Mapping[str, Any]) -> StrategyAudit:
    engine = row.get("canonical_engine") if isinstance(row.get("canonical_engine"), dict) else {}
    path_value = str(engine.get("implementation_path") or "")
    callable_name = str(engine.get("callable") or "")
    expected_sha = str(engine.get("source_sha256") or "")
    path = ROOT / path_value
    source_exists = path.is_file() and not path.is_symlink()
    actual_sha: str | None = _sha256(path) if source_exists else None
    source = path.read_text(encoding="utf-8", errors="replace") if source_exists else ""

    syntax_ok = False
    callable_exists = False
    if source_exists:
        try:
            callable_exists = callable_name in _callable_names(source, path_value)
            syntax_ok = True
        except SyntaxError:
            syntax_ok = False

    missing_core = [token for token in spec.get("core", []) if not _has_token(source, str(token))]
    structural = _structural_checks(source)
    missing_hard = [name for name in spec.get("hard_structural", []) if not structural.get(str(name), False)]
    review_findings = [name for name in spec.get("review", []) if not structural.get(str(name), False)]
    required_failures = _required_column_failures(source, [str(v) for v in spec.get("required_columns", [])])
    lookahead = _lookahead_findings(source)
    authority = _authority_findings(source)
    risk_ok = bool(re.search(r"['\"]sl['\"]", source) and re.search(r"['\"]tp['\"]", source))
    long_short_ok = bool(re.search(r"long", source, flags=re.I) and re.search(r"short", source, flags=re.I))
    sha_match = bool(source_exists and expected_sha and actual_sha == expected_sha)

    blockers = []
    if not source_exists:
        blockers.append("SOURCE_MISSING")
    if not sha_match:
        blockers.append("SOURCE_SHA_MISMATCH")
    if not syntax_ok:
        blockers.append("SYNTAX_INVALID")
    if not callable_exists:
        blockers.append("CALLABLE_UNRESOLVED")
    blockers.extend(f"MISSING_CORE:{item}" for item in missing_core)
    blockers.extend(f"MISSING_STRUCTURAL:{item}" for item in missing_hard)
    blockers.extend(f"REQUIRED_COLUMN_NOT_FAIL_CLOSED:{item}" for item in required_failures)
    blockers.extend(f"LOOKAHEAD:{item}" for item in lookahead)
    blockers.extend(f"AUTHORITY:{item}" for item in authority)
    if not risk_ok:
        blockers.append("RISK_OUTPUT_CONTRACT_MISSING")
    if not long_short_ok:
        blockers.append("LONG_SHORT_CONTRACT_MISSING")

    return StrategyAudit(
        strategy_id=strategy_id,
        path=path_value,
        callable=callable_name,
        source_sha_registry=expected_sha,
        source_sha_actual=actual_sha,
        source_sha_match=sha_match,
        source_exists=source_exists,
        syntax_ok=syntax_ok,
        callable_exists=callable_exists,
        missing_core=missing_core,
        missing_hard_structural=missing_hard,
        review_findings=review_findings,
        required_column_failures=required_failures,
        lookahead_findings=lookahead,
        authority_findings=authority,
        risk_contract_ok=risk_ok,
        long_short_contract_ok=long_short_ok,
        status="PASS" if not blockers else "HOLD",
    )


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Strategy25 Indicator Contract Audit v1",
        "",
        f"- state: **{report['state']}**",
        f"- canonical owners: **{report['canonical_owner_count']}/{report['expected_strategy_count']}**",
        f"- PASS: **{report['pass_count']}**",
        f"- HOLD: **{report['hold_count']}**",
        f"- parameter SSOT: **{report['parameter_ssot_status']}**",
        "",
        "| strategy | status | missing core | hard structural | review | SHA |",
        "|---|---:|---|---|---|---:|",
    ]
    for item in report["strategies"]:
        lines.append(
            "| {strategy_id} | {status} | {core} | {hard} | {review} | {sha} |".format(
                strategy_id=item["strategy_id"],
                status=item["status"],
                core=", ".join(item["missing_core"]) or "-",
                hard=", ".join(item["missing_hard_structural"]) or "-",
                review=", ".join(item["review_findings"]) or "-",
                sha="PASS" if item["source_sha_match"] else "FAIL",
            )
        )
    lines.extend(["", "## Hard blockers", ""])
    lines.extend(f"- `{value}`" for value in report["hard_blockers"] or ["NONE"])
    lines.extend(["", "## Review findings", ""])
    lines.extend(f"- `{value}`" for value in report["review_findings"] or ["NONE"])
    return "\n".join(lines) + "\n"


def main() -> int:
    contract = _read_json(CONTRACT_PATH)
    registry = _read_json(ROOT / str(contract["registry_path"]))
    config = _read_json(ROOT / str(contract["config_path"]))
    specs = contract.get("strategies") if isinstance(contract.get("strategies"), dict) else {}
    rows = [row for row in registry.get("entries", []) if isinstance(row, dict)]
    row_by_id = {str(row.get("strategy_id") or ""): row for row in rows}

    audits: list[StrategyAudit] = []
    hard_blockers: list[str] = []
    review_findings: list[str] = []

    if registry.get("fail_closed") is not True or int(registry.get("active_entry_count", -1)) != 0:
        hard_blockers.append("REGISTRY_AUTHORITY_NOT_FAIL_CLOSED")
    if len(rows) != int(contract["expected_strategy_count"]):
        hard_blockers.append(f"REGISTRY_COUNT:{len(rows)}")
    if set(row_by_id) != set(specs):
        hard_blockers.append("REGISTRY_CONTRACT_ID_SET_MISMATCH")

    for strategy_id in sorted(specs):
        row = row_by_id.get(strategy_id)
        if row is None:
            hard_blockers.append(f"{strategy_id}:NO_CANONICAL_OWNER")
            continue
        if row.get("active_allowed") is not False or row.get("fail_closed") is not True:
            hard_blockers.append(f"{strategy_id}:AUTHORITY_NOT_FAIL_CLOSED")
        audit = _audit_strategy(strategy_id, specs[strategy_id], row)
        audits.append(audit)
        if audit.status != "PASS":
            for value in (
                audit.missing_core
                + audit.missing_hard_structural
                + audit.required_column_failures
                + audit.lookahead_findings
                + audit.authority_findings
            ):
                hard_blockers.append(f"{strategy_id}:{value}")
            if not audit.source_sha_match:
                hard_blockers.append(f"{strategy_id}:SOURCE_SHA_MISMATCH")
            if not audit.syntax_ok:
                hard_blockers.append(f"{strategy_id}:SYNTAX_INVALID")
            if not audit.callable_exists:
                hard_blockers.append(f"{strategy_id}:CALLABLE_UNRESOLVED")
        review_findings.extend(f"{strategy_id}:{value}" for value in audit.review_findings)

    config_values = config.get("strategies") if isinstance(config.get("strategies"), dict) else {}
    parameter_ssot_status = "PASS" if all(isinstance(v, dict) for v in config_values.values()) else "GAP_DATACLASS_DEFAULTS_NOT_EXTERNALIZED"
    if parameter_ssot_status != "PASS":
        review_findings.append(parameter_ssot_status)

    pass_count = sum(audit.status == "PASS" for audit in audits)
    report = {
        "schema_version": "1.1",
        "authority": contract.get("authority"),
        "state": "PASS" if not hard_blockers else "HOLD",
        "expected_strategy_count": int(contract["expected_strategy_count"]),
        "canonical_owner_count": len(audits),
        "pass_count": pass_count,
        "hold_count": len(audits) - pass_count,
        "parameter_ssot_status": parameter_ssot_status,
        "hard_blocker_count": len(sorted(set(hard_blockers))),
        "review_finding_count": len(sorted(set(review_findings))),
        "hard_blockers": sorted(set(hard_blockers)),
        "review_findings": sorted(set(review_findings)),
        "strategies": [asdict(audit) for audit in audits],
        "next": "RUN_CHILD_REPAIRS_AND_PARITY_TESTS" if hard_blockers else "RUN_NONOVERLAP_OOS",
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "audit.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (REPORT_DIR / "audit.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "STATE": report["state"],
        "OWNERS": f"{report['canonical_owner_count']}/{report['expected_strategy_count']}",
        "PASS": report["pass_count"],
        "HOLD": report["hold_count"],
        "HARD_BLOCKERS": report["hard_blocker_count"],
        "REVIEW": report["review_finding_count"],
        "PARAMETER_SSOT": report["parameter_ssot_status"],
        "NEXT": report["next"],
    }, sort_keys=True))
    for value in report["hard_blockers"]:
        print(f"BLOCKER={value}")
    for value in report["review_findings"]:
        print(f"REVIEW={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
