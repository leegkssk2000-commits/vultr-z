from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import html
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

SNAPSHOT_DIR = Path("runtime_results/q4r3/strategy_source_snapshot")
SOURCE_PREFIX = SNAPSHOT_DIR / "source"
MANIFEST_NAME = "manifest.json"
REVIEW_QUEUE_NAME = "review_queue.json"

REGISTRY_PATH_HINTS = (
    "registry",
    "catalog",
    "manifest",
    "strategy_cards",
    "policy",
    "profiles",
)

OUTPUT_KEYS = (
    "side",
    "action",
    "size",
    "entry",
    "sl",
    "tp",
    "pyramiding",
    "why",
    "skill",
    "confidence",
    "tags",
    "indicators",
)

FEATURE_GROUPS: Dict[str, Tuple[str, ...]] = {
    "regime": ("regime", "market_context", "htf_regime", "adx", "squeeze", "trend_slope"),
    "volatility": ("atr", "atr_pct", "volatility", "bollinger", "keltner", "true_range"),
    "momentum": ("rsi", "macd", "mfi", "momentum", "roc", "obv"),
    "structure": ("swing_high", "swing_low", "support", "resistance", "pivot", "range_high", "range_low"),
    "liquidity": ("liquidity", "sweep", "wick", "vwap", "volume_z", "order_flow"),
    "execution": ("spread_bps", "slippage", "latency", "fee", "late_chase", "chase"),
    "stateful": ("position_side", "position_qty", "avg_entry", "add_count", "pyramiding", "reduce", "scale_in", "water_add"),
    "risk_exit": ("stop", "sl", "take_profit", "tp", "trailing", "partial", "runner", "risk_action", "risk_gate"),
    "long_short": ("enter_long", "enter_short", 'side="long"', 'side="short"', 'side = "long"', 'side = "short"'),
    "skills": ("skill", "long_beam", "short_beam", "mfe_runner", "runner_hold", "trailing", "partial"),
}

GENERIC_WRAPPER_MARKERS = (
    "generic_legendary_templates",
    "legendary_mean_reversion as _impl",
    "legendary_trend_continuation as _impl",
    "legendary_liquidity_reclaim as _impl",
    "legendary_breakout as _impl",
    "legendary_meta_hold as _impl",
    "return _impl(",
)

THIN_WRAPPER_MAX_LINES = 40
OWNER_CONFIDENCE_MARGIN = 14


@dataclass(frozen=True)
class ModuleAnalysis:
    strategy: str
    path: str
    kind: str
    sha256: str
    size_bytes: int
    line_count: int
    ast_ok: bool
    defines_strategy: bool
    direct_strategy_logic: bool
    generic_wrapper: bool
    wrapper_target: Optional[str]
    function_count: int
    class_count: int
    config_class_count: int
    return_dict_count: int
    output_key_count: int
    feature_groups: Dict[str, bool]
    score: int
    reasons: Tuple[str, ...]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)


def strategy_pattern(strategy: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in normalize(strategy).split("_") if part]
    return re.compile(r"(?<![a-z0-9])" + r"[\s_\-./]*".join(parts) + r"(?![a-z0-9])", re.I)


def module_kind(path: str) -> str:
    lower = path.lower()
    if "/legendary_rebuild/" in lower:
        return "legendary"
    if "/strategies_v4/" in lower or lower.endswith("_v4.py"):
        return "v4"
    if "/strategies/" in lower:
        return "canonical"
    return "support"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def find_wrapper_target(text: str) -> Optional[str]:
    match = re.search(r"from\s+[^\n]+\s+import\s+([A-Za-z0-9_]+)\s+as\s+_impl", text)
    if match:
        return match.group(1)
    match = re.search(r"return\s+([A-Za-z0-9_]+)\(", text)
    if match and match.group(1) not in {"dict", "float", "int", "str", "list", "tuple"}:
        return match.group(1)
    return None


def ast_metrics(text: str) -> Dict[str, Any]:
    metrics = {
        "ast_ok": False,
        "defines_strategy": False,
        "function_count": 0,
        "class_count": 0,
        "config_class_count": 0,
        "return_dict_count": 0,
    }
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return metrics
    metrics["ast_ok"] = True
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            metrics["function_count"] += 1
            if node.name == "strategy":
                metrics["defines_strategy"] = True
        elif isinstance(node, ast.ClassDef):
            metrics["class_count"] += 1
            if node.name.lower().endswith("config") or any(
                isinstance(decorator, ast.Name) and decorator.id == "dataclass"
                for decorator in node.decorator_list
            ):
                metrics["config_class_count"] += 1
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            metrics["return_dict_count"] += 1
    return metrics


def feature_presence(lower: str) -> Dict[str, bool]:
    return {
        group: any(marker.lower() in lower for marker in markers)
        for group, markers in FEATURE_GROUPS.items()
    }


def score_module(strategy: str, relative_path: str, text: str) -> ModuleAnalysis:
    data = text.encode("utf-8")
    lower = text.lower()
    lines = text.splitlines()
    metrics = ast_metrics(text)
    kind = module_kind(relative_path)
    wrapper_target = find_wrapper_target(text)
    generic_wrapper = any(marker in lower for marker in GENERIC_WRAPPER_MARKERS)
    if len(lines) <= THIN_WRAPPER_MAX_LINES and wrapper_target:
        generic_wrapper = True

    strategy_fn_match = re.search(r"^def\s+strategy\s*\(", text, flags=re.M)
    direct_strategy_logic = bool(strategy_fn_match) and not generic_wrapper and len(lines) > THIN_WRAPPER_MAX_LINES
    feature_groups = feature_presence(lower)
    output_key_count = sum(1 for key in OUTPUT_KEYS if re.search(rf"[\"']{re.escape(key)}[\"']\s*:", text))

    score = 0
    reasons: List[str] = []
    if metrics["ast_ok"]:
        score += 4
    if metrics["defines_strategy"]:
        score += 14
        reasons.append("strategy_callable")
    if direct_strategy_logic:
        score += 24
        reasons.append("direct_specialized_logic")
    if generic_wrapper:
        score -= 24
        reasons.append("generic_or_thin_wrapper")
    if metrics["config_class_count"]:
        score += min(10, 5 + metrics["config_class_count"] * 2)
        reasons.append("explicit_config_surface")
    if metrics["function_count"] >= 4:
        score += min(10, metrics["function_count"])
        reasons.append("nontrivial_function_surface")
    if metrics["return_dict_count"] or output_key_count >= 6:
        score += 8
        reasons.append("explicit_output_contract")
    score += min(16, int(math.log2(max(len(lines), 1))) * 2)
    if len(lines) >= 150:
        reasons.append("substantive_implementation")

    weighted_features = {
        "regime": 6,
        "volatility": 4,
        "momentum": 3,
        "structure": 4,
        "liquidity": 3,
        "execution": 5,
        "stateful": 5,
        "risk_exit": 8,
        "long_short": 5,
        "skills": 4,
    }
    for group, weight in weighted_features.items():
        if feature_groups[group]:
            score += weight
            reasons.append(f"feature:{group}")

    if kind == "canonical" and direct_strategy_logic:
        score += 6
        reasons.append("canonical_specialized_bonus")
    if kind == "v4" and generic_wrapper:
        score -= 4
    if "except exception" in lower and "class strategydecision" in lower:
        score -= 3
        reasons.append("local_fallback_contract")

    return ModuleAnalysis(
        strategy=strategy,
        path=relative_path,
        kind=kind,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        line_count=len(lines),
        ast_ok=bool(metrics["ast_ok"]),
        defines_strategy=bool(metrics["defines_strategy"]),
        direct_strategy_logic=direct_strategy_logic,
        generic_wrapper=generic_wrapper,
        wrapper_target=wrapper_target,
        function_count=int(metrics["function_count"]),
        class_count=int(metrics["class_count"]),
        config_class_count=int(metrics["config_class_count"]),
        return_dict_count=int(metrics["return_dict_count"]),
        output_key_count=output_key_count,
        feature_groups=feature_groups,
        score=score,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def serialize_module(module: ModuleAnalysis) -> Dict[str, Any]:
    return {
        "strategy": module.strategy,
        "path": module.path,
        "kind": module.kind,
        "sha256": module.sha256,
        "size_bytes": module.size_bytes,
        "line_count": module.line_count,
        "ast_ok": module.ast_ok,
        "defines_strategy": module.defines_strategy,
        "direct_strategy_logic": module.direct_strategy_logic,
        "generic_wrapper": module.generic_wrapper,
        "wrapper_target": module.wrapper_target,
        "function_count": module.function_count,
        "class_count": module.class_count,
        "config_class_count": module.config_class_count,
        "return_dict_count": module.return_dict_count,
        "output_key_count": module.output_key_count,
        "feature_groups": module.feature_groups,
        "score": module.score,
        "reasons": list(module.reasons),
    }


def owner_decision(strategy: str, modules: Sequence[ModuleAnalysis]) -> Dict[str, Any]:
    ranked = sorted(modules, key=lambda item: (item.score, item.direct_strategy_logic, item.line_count), reverse=True)
    if not ranked:
        return {
            "strategy": strategy,
            "verdict": "OWNER_MISSING",
            "proposed_owner": None,
            "confidence": 0.0,
            "margin": None,
            "modules": [],
        }

    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    margin = top.score - second.score if second else top.score
    full_direct = [module for module in ranked if module.direct_strategy_logic]

    if len(ranked) == 1 and top.direct_strategy_logic:
        verdict = "SINGLE_DIRECT_OWNER_CANDIDATE"
        confidence = 0.93
    elif top.direct_strategy_logic and margin >= OWNER_CONFIDENCE_MARGIN:
        verdict = "PROPOSED_OWNER_CONFIDENT"
        confidence = min(0.98, 0.78 + margin / 100.0)
    elif top.direct_strategy_logic and len(full_direct) == 1:
        verdict = "PROPOSED_OWNER_WITH_WRAPPER_ALTERNATES"
        confidence = 0.86
    elif top.direct_strategy_logic:
        verdict = "MULTIPLE_DIRECT_IMPLEMENTATIONS_REVIEW_REQUIRED"
        confidence = 0.62
    else:
        verdict = "NO_SPECIALIZED_DIRECT_OWNER"
        confidence = 0.30

    alternatives: List[Dict[str, Any]] = []
    for module in ranked[1:]:
        if module.generic_wrapper and module.kind == "legendary":
            role = "GENERIC_LEGENDARY_RESERVE"
        elif module.generic_wrapper and module.kind == "v4":
            role = "THIN_V4_OVERLAY_RESERVE"
        elif module.kind == "legendary":
            role = "LEGENDARY_ABLATION_CANDIDATE"
        elif module.kind == "v4":
            role = "V4_ABLATION_CANDIDATE"
        else:
            role = "ALTERNATE_IMPLEMENTATION_REVIEW"
        alternatives.append({"path": module.path, "role": role, "score": module.score})

    return {
        "strategy": strategy,
        "verdict": verdict,
        "proposed_owner": top.path,
        "proposed_owner_kind": top.kind,
        "proposed_owner_sha256": top.sha256,
        "confidence": round(confidence, 4),
        "margin": margin,
        "full_direct_count": len(full_direct),
        "alternatives": alternatives,
        "modules": [serialize_module(module) for module in ranked],
    }


def registry_candidate_paths(snapshot_source: Path) -> List[Path]:
    candidates: List[Path] = []
    for path in snapshot_source.rglob("*"):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if any(hint in lower for hint in REGISTRY_PATH_HINTS):
            candidates.append(path)
    return sorted(candidates)


def registry_audit(snapshot_source: Path, strategies: Sequence[str]) -> Dict[str, Any]:
    expected = set(strategies)
    files: List[Dict[str, Any]] = []
    exact_coverage_files: List[str] = []
    for path in registry_candidate_paths(snapshot_source):
        text = read_text(path)
        covered = sorted(strategy for strategy in expected if strategy_pattern(strategy).search(text))
        if not covered:
            continue
        extra_strategy_like: List[str] = []
        try:
            payload = json.loads(text)
            if isinstance(payload, Mapping):
                extra_strategy_like = sorted(
                    normalize(key) for key in payload.keys() if normalize(key) and normalize(key) not in expected
                )[:100]
        except Exception:
            pass
        relative = str(path.relative_to(snapshot_source))
        coverage_count = len(covered)
        if coverage_count == len(expected):
            exact_coverage_files.append(relative)
        files.append(
            {
                "path": relative,
                "coverage_count": coverage_count,
                "coverage_pct": round(coverage_count / len(expected) * 100.0, 3) if expected else 0.0,
                "covered": covered,
                "missing": sorted(expected - set(covered)),
                "extra_top_level_keys": extra_strategy_like,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    files.sort(key=lambda item: (item["coverage_count"], item["path"]), reverse=True)

    if len(exact_coverage_files) == 1:
        verdict = "SINGLE_EXACT_25_REGISTRY_CANDIDATE"
        authority = exact_coverage_files[0]
    elif len(exact_coverage_files) > 1:
        verdict = "MULTIPLE_EXACT_25_REGISTRY_CANDIDATES"
        authority = None
    else:
        verdict = "REGISTRY_AUTHORITY_SPLIT_OR_INCOMPLETE"
        authority = None

    return {
        "verdict": verdict,
        "authoritative_candidate": authority,
        "exact_coverage_files": exact_coverage_files,
        "files": files,
    }


def render_html(result: Mapping[str, Any]) -> str:
    rows: List[str] = []
    for item in result.get("owners", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('strategy')))}</td>"
            f"<td>{html.escape(str(item.get('proposed_owner')))}</td>"
            f"<td>{html.escape(str(item.get('verdict')))}</td>"
            f"<td>{item.get('confidence')}</td>"
            f"<td>{item.get('margin')}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Q4R3 Canonical Owner Matrix</title>"
        "<style>body{font-family:Arial,sans-serif;background:#111;color:#eee;margin:24px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #444;padding:8px;text-align:left}"
        "th{background:#222}</style></head><body>"
        f"<h1>{html.escape(str(result.get('verdict')))}</h1>"
        f"<p>Registry: {html.escape(str(result.get('registry_audit', {}).get('verdict')))}</p>"
        "<table><thead><tr><th>Strategy</th><th>Proposed owner</th><th>Verdict</th><th>Confidence</th><th>Margin</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )


def write_csv(path: Path, owners: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["strategy", "proposed_owner", "kind", "sha256", "verdict", "confidence", "margin", "full_direct_count", "alternatives"])
        for item in owners:
            writer.writerow(
                [
                    item.get("strategy"),
                    item.get("proposed_owner"),
                    item.get("proposed_owner_kind"),
                    item.get("proposed_owner_sha256"),
                    item.get("verdict"),
                    item.get("confidence"),
                    item.get("margin"),
                    item.get("full_direct_count"),
                    ";".join(f"{alt.get('path')}={alt.get('role')}" for alt in item.get("alternatives", [])),
                ]
            )


def run(worktree: Path, output_dir: Path) -> Dict[str, Any]:
    snapshot = worktree / SNAPSHOT_DIR
    manifest = json.loads(read_text(snapshot / MANIFEST_NAME))
    queue = json.loads(read_text(snapshot / REVIEW_QUEUE_NAME))
    snapshot_source = worktree / SOURCE_PREFIX

    strategies = [normalize(item.get("strategy")) for item in queue.get("strategies", [])]
    strategies = [strategy for strategy in strategies if strategy]
    strategy_map = manifest.get("strategy_map", {})

    owners: List[Dict[str, Any]] = []
    missing_files: List[str] = []
    for strategy in strategies:
        modules: List[ModuleAnalysis] = []
        for source_path in strategy_map.get(strategy, []):
            published = snapshot_source / source_path
            if not published.exists():
                missing_files.append(source_path)
                continue
            modules.append(score_module(strategy, source_path, read_text(published)))
        owners.append(owner_decision(strategy, modules))

    owners.sort(key=lambda item: item["strategy"])
    registry = registry_audit(snapshot_source, strategies)
    verdict_counts = Counter(item["verdict"] for item in owners)
    unresolved = [
        item["strategy"]
        for item in owners
        if item["verdict"] in {
            "OWNER_MISSING",
            "NO_SPECIALIZED_DIRECT_OWNER",
            "MULTIPLE_DIRECT_IMPLEMENTATIONS_REVIEW_REQUIRED",
        }
    ]
    confident_count = sum(
        1
        for item in owners
        if item["verdict"] in {
            "SINGLE_DIRECT_OWNER_CANDIDATE",
            "PROPOSED_OWNER_CONFIDENT",
            "PROPOSED_OWNER_WITH_WRAPPER_ALTERNATES",
        }
    )

    if missing_files:
        verdict = "SOURCE_SNAPSHOT_INCOMPLETE"
        next_action = "REPAIR_SOURCE_SNAPSHOT_BEFORE_OWNER_SELECTION"
    elif unresolved:
        verdict = "CANONICAL_OWNER_REVIEW_GAPS_REMAIN"
        next_action = "MANUALLY_REVIEW_ONLY_UNRESOLVED_DIRECT_IMPLEMENTATION_TIES"
    elif registry["verdict"] != "SINGLE_EXACT_25_REGISTRY_CANDIDATE":
        verdict = "OWNER_MATRIX_READY_REGISTRY_AUTHORITY_UNRESOLVED"
        next_action = "DEFINE_ONE_25_STRATEGY_REGISTRY_AUTHORITY_BEFORE_CONTRACT_HARNESS"
    else:
        verdict = "OWNER_MATRIX_AND_REGISTRY_READY_FOR_SHARED_CONTRACT_HARNESS"
        next_action = "BUILD_READ_ONLY_REGISTRY_DRIVEN_25_STRATEGY_CONTRACT_HARNESS"

    result: Dict[str, Any] = {
        "schema": "q4r3_strategy_canonical_owner_matrix_v1",
        "status": "PASS_Q4R3_STRATEGY_CANONICAL_OWNER_MATRIX",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_strategy_count": len(strategies),
        "source_snapshot_complete": bool(manifest.get("direct_strategy_snapshot_complete")) and not missing_files,
        "missing_files": missing_files,
        "owner_summary": {
            "confident_or_single_count": confident_count,
            "unresolved_count": len(unresolved),
            "unresolved_strategies": unresolved,
            "verdict_counts": dict(verdict_counts),
        },
        "registry_audit": registry,
        "owners": owners,
        "repair_order": [
            "confirm_one_owner_per_strategy",
            "define_one_exact_25_registry_authority",
            "mark_legendary_and_v4_as_ablation_overlays_not_parallel_owners",
            "connect_signal_output_to_one_shared_entry_risk_and_close_r_boundary",
            "build_one_registry_driven_25_strategy_contract_harness",
            "run_per_strategy_ablation_walk_forward_and_regime_holdout",
            "freeze_final_owner_sha_matrix_before_portfolio_combination",
        ],
        "safety": {
            "read_only": True,
            "source_files_modified": False,
            "registry_modified": False,
            "strategy_modified": False,
            "paper_live_order_modified": False,
            "persistent_forward_r_watcher_modified": False,
            "raw_trade_rows_included": False,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(output_dir / "q4r3_strategy_canonical_owner_matrix_latest.json", result)
    atomic_json(
        output_dir / "q4r3_strategy_canonical_owner_repair_plan_latest.json",
        {
            "schema": "q4r3_strategy_canonical_owner_repair_plan_v1",
            "verdict": verdict,
            "action": "HOLD",
            "next_action": next_action,
            "registry_verdict": registry["verdict"],
            "unresolved_strategies": unresolved,
            "owners": [
                {
                    "strategy": item["strategy"],
                    "proposed_owner": item.get("proposed_owner"),
                    "proposed_owner_sha256": item.get("proposed_owner_sha256"),
                    "verdict": item["verdict"],
                    "confidence": item["confidence"],
                    "alternatives": item.get("alternatives", []),
                }
                for item in owners
            ],
            "repair_order": result["repair_order"],
        },
    )
    write_csv(output_dir / "q4r3_strategy_canonical_owner_matrix_latest.csv", owners)
    (output_dir / "q4r3_strategy_canonical_owner_matrix_latest.html").write_text(render_html(result), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.worktree, args.output_dir)
    print(
        json.dumps(
            {
                "status": result["status"],
                "verdict": result["verdict"],
                "expected_strategy_count": result["expected_strategy_count"],
                "owner_summary": result["owner_summary"],
                "registry_verdict": result["registry_audit"]["verdict"],
                "next_action": result["next_action"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
