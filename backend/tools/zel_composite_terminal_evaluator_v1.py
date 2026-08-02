from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import importlib.util
import json
import math
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

VERSION = "ZEL_COMPOSITE_TERMINAL_EVALUATOR_V1"
WINDOW_ORDER = ("1m_w1", "1m_w2", "1m_w3")
REQUIRED_TRADE_FIELDS = {
    "event_id",
    "strategy_id",
    "symbol",
    "side",
    "entry_ts",
    "exit_ts",
    "realized_R",
    "realized_R_including_funding_estimate",
    "MFE_R",
    "MAE_R",
    "time_exposure_min",
    "regime",
    "window_id",
    "data_interval",
    "initial_risk_usdt",
    "fee",
    "slippage",
}
LICO_REQUIRED_FIELDS = {
    "price",
    "pos_pct",
    "lev",
    "entry_ts",
    "funding_8h_pct",
    "dd_day_pct",
    "dd_total_pct",
}
LICO_LIQ_ALTERNATIVES = ("liq_price", "liq_buffer_pct")
TRANSFORM_MODULES = {"TRADE_METHOD", "SKILL_PROFILE", "LICO"}
PARITY_MODULES = {"LBOT", "MBOT", "OBOT", "SBOT", "ZBOT", "ZLICE"}
STRUCTURAL_MODULES = {"ZICO"}
POST_SCORE_MODULES = {"PORTFOLIO_GOVERNOR"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def load_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise RuntimeError(f"TRADE_OBJECT_REQUIRED:{line_number}")
            rows.append(value)
    return rows


def max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return drawdown


def metrics(rows: Sequence[Mapping[str, Any]], field: str = "realized_R") -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row.get("exit_ts") or ""), str(row.get("event_id") or "")))
    values = [safe_float(row.get(field), 0.0) or 0.0 for row in ordered]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    mfe = [safe_float(row.get("MFE_R")) for row in ordered]
    mae = [safe_float(row.get("MAE_R")) for row in ordered]
    exposure = [safe_float(row.get("time_exposure_min")) for row in ordered]
    fees = [safe_float(row.get("fee"), 0.0) or 0.0 for row in ordered]
    slippage = [safe_float(row.get("slippage"), 0.0) or 0.0 for row in ordered]
    funding = [safe_float(row.get("funding_pnl_estimate_usdt"), 0.0) or 0.0 for row in ordered]
    return {
        "sample_count": len(values),
        "net_R": sum(values),
        "expectancy_R": statistics.fmean(values) if values else None,
        "median_R": statistics.median(values) if values else None,
        "win_rate_pct": (len(wins) / len(values) * 100.0) if values else None,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else (None if not values else float("inf")),
        "gross_profit_R": gross_profit,
        "gross_loss_R": gross_loss,
        "max_drawdown_R": max_drawdown(values),
        "average_MFE_R": statistics.fmean(value for value in mfe if value is not None) if any(value is not None for value in mfe) else None,
        "average_MAE_R": statistics.fmean(value for value in mae if value is not None) if any(value is not None for value in mae) else None,
        "average_exposure_min": statistics.fmean(value for value in exposure if value is not None) if any(value is not None for value in exposure) else None,
        "fee_total_usdt": sum(fees),
        "slippage_total_usdt": sum(slippage),
        "funding_total_usdt": sum(funding),
    }


def event_set_sha(rows: Sequence[Mapping[str, Any]]) -> str:
    return stable_sha(sorted(str(row.get("event_id") or "") for row in rows))


def grouped_metrics(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return {name: metrics(values) for name, values in sorted(grouped.items())}


def validate_terminal(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    terminal = load_json(root / "terminal_receipt.json")
    report = load_json(root / "report.json")
    artifact_manifest = load_json(root / "artifact_manifest.json")
    trades_path = root / "trades.jsonl.gz"
    if terminal.get("state") != "PASS":
        errors.append(f"TERMINAL_STATE:{terminal.get('state')}")
    if report.get("state") != "PASS":
        errors.append(f"REPORT_STATE:{report.get('state')}")
    if report.get("interval") != "1m":
        errors.append(f"REPORT_INTERVAL:{report.get('interval')}")
    replay = report.get("replay") if isinstance(report.get("replay"), dict) else {}
    if int(replay.get("strategy_count_completed") or 0) != 25:
        errors.append("STRATEGY_COUNT_NOT_25")
    if int(replay.get("strategy_failure_count") or 0) != 0:
        errors.append("STRATEGY_FAILURES_PRESENT")
    if not trades_path.is_file():
        errors.append("TRADES_FILE_MISSING")
        trades: list[dict[str, Any]] = []
    else:
        trades = load_trades(trades_path)
    missing_fields: set[str] = set()
    for row in trades:
        missing_fields.update(REQUIRED_TRADE_FIELDS - set(row))
    if missing_fields:
        errors.append("TRADE_FIELDS_MISSING:" + ",".join(sorted(missing_fields)))
    event_ids = [str(row.get("event_id") or "") for row in trades]
    duplicate_count = len(event_ids) - len(set(event_ids))
    if duplicate_count:
        errors.append(f"DUPLICATE_EVENT_IDS:{duplicate_count}")
    windows = sorted({str(row.get("window_id") or "") for row in trades})
    if windows != sorted(WINDOW_ORDER):
        errors.append("WINDOW_SET_MISMATCH:" + ",".join(windows))
    artifact_rows = artifact_manifest.get("artifacts") if isinstance(artifact_manifest.get("artifacts"), list) else []
    expected = {str(row.get("path") or ""): str(row.get("sha256") or "") for row in artifact_rows if isinstance(row, dict)}
    for name in ("report.json", "trades.jsonl.gz"):
        path = root / name
        digest = expected.get(name)
        if digest and path.is_file() and sha256_path(path) != digest:
            errors.append(f"ARTIFACT_SHA_MISMATCH:{name}")
    return terminal, report, artifact_manifest, trades, sorted(set(errors))


def import_trade_method(source_root: Path):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    return importlib.import_module("backend.trade_methods.resolver")


def trade_method_behavior(source_root: Path, strategy_ids: Iterable[str]) -> dict[str, Any]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    try:
        module = import_trade_method(source_root)
    except Exception as exc:
        return {
            "state": "HOLD_TRADE_METHOD_IMPORT_FAILED",
            "strategy_count": 0,
            "rows": [],
            "errors": [f"IMPORT:{type(exc).__name__}:{exc}"],
        }
    for strategy_id in sorted(set(strategy_ids)):
        try:
            result = module.h74tm8_resolve_trade_method(strategy_id, [], 0.0)
            if not isinstance(result, dict):
                raise RuntimeError("RESULT_NOT_OBJECT")
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "decision": result.get("decision"),
                    "action": result.get("action"),
                    "registry_enabled": result.get("registry_enabled"),
                    "size_multiplier": result.get("size_multiplier"),
                    "target_r": result.get("target_r"),
                    "execution_authority": result.get("execution_authority"),
                    "order_authority": result.get("order_authority"),
                    "paper_execution_allowed": result.get("paper_execution_allowed"),
                    "live_execution_allowed": result.get("live_execution_allowed"),
                }
            )
        except Exception as exc:
            errors.append(f"{strategy_id}:{type(exc).__name__}:{exc}")
    unsafe = [
        row
        for row in rows
        if row.get("execution_authority") not in {"NONE", "none"}
        or row.get("order_authority") not in {"BLOCKED", "blocked"}
        or row.get("paper_execution_allowed") is not False
        or row.get("live_execution_allowed") is not False
    ]
    enabled = [row for row in rows if row.get("registry_enabled") is True or (safe_float(row.get("size_multiplier"), 0.0) or 0.0) > 0]
    if errors:
        state = "HOLD_TRADE_METHOD_BEHAVIOR_ERRORS"
    elif unsafe:
        state = "HOLD_TRADE_METHOD_AUTHORITY_UNSAFE"
    elif enabled:
        state = "HOLD_TRADE_METHOD_ENABLED_COUNTERFACTUAL_ADAPTER_REQUIRED"
    else:
        state = "PASS_TRADE_METHOD_DISABLED_HOLD_BEHAVIOR"
    return {
        "state": state,
        "strategy_count": len(rows),
        "enabled_strategy_count": len(enabled),
        "unsafe_strategy_count": len(unsafe),
        "distinct_behavior_count": len({stable_sha(row) for row in rows}),
        "rows": rows,
        "errors": errors,
    }


def lico_history_readiness(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    missing_counts: Counter[str] = Counter()
    for row in rows:
        for field in LICO_REQUIRED_FIELDS:
            if row.get(field) in {None, ""}:
                missing_counts[field] += 1
        if not any(row.get(field) not in {None, ""} for field in LICO_LIQ_ALTERNATIVES):
            missing_counts["liq_price|liq_buffer_pct"] += 1
        src_keys = row.get("src_keys") if isinstance(row.get("src_keys"), list) else []
        if not src_keys:
            missing_counts["src_keys"] += 1
    ready = bool(rows) and not missing_counts
    return {
        "state": "PASS_LICO_HISTORICAL_MIN_DATA" if ready else "HOLD_LICO_HISTORICAL_MIN_DATA_MISSING",
        "trade_count": len(rows),
        "missing_counts": dict(sorted(missing_counts.items())),
        "historical_replay_ready": ready,
    }


def candidate_blockers(
    plan: Mapping[str, Any],
    method_behavior: Mapping[str, Any],
    lico_readiness: Mapping[str, Any],
    source_root: Path,
) -> list[str]:
    children = set(str(value) for value in plan.get("child_module_ids", []))
    classification = plan.get("classification") if isinstance(plan.get("classification"), dict) else {}
    blockers = list(classification.get("w2_blockers") or [])
    if "TRADE_METHOD" in children and method_behavior.get("state") != "PASS_TRADE_METHOD_DISABLED_HOLD_BEHAVIOR":
        blockers.append("TRADE_METHOD_COUNTERFACTUAL_ADAPTER_NOT_READY")
    if "TRADE_METHOD" in children and method_behavior.get("state") == "PASS_TRADE_METHOD_DISABLED_HOLD_BEHAVIOR":
        blockers.append("TRADE_METHOD_REGISTRY_DISABLED")
    if "SKILL_PROFILE" in children:
        adapter_path = source_root / "backend/tools/zel_skill_counterfactual_adapter_v1.py"
        if not adapter_path.is_file():
            blockers.append("SKILL_COUNTERFACTUAL_EXECUTION_ADAPTER_MISSING")
    if "LICO" in children and lico_readiness.get("state") != "PASS_LICO_HISTORICAL_MIN_DATA":
        blockers.append("LICO_HISTORICAL_MIN_DATA_MISSING")
    if children & STRUCTURAL_MODULES:
        blockers.append("RUNTIME_OBSERVER_STRUCTURAL_ONLY")
    if children & POST_SCORE_MODULES:
        blockers.append("POST_SCORE_MODULE_INSIDE_CANDIDATE")
    if "STRATEGY_SIGNAL" not in children:
        blockers.append("BASE_SIGNAL_MISSING")
    return sorted(set(str(value) for value in blockers))


def parity_result(
    composite_id: str,
    window_id: str,
    rows: Sequence[Mapping[str, Any]],
    child_module_ids: Sequence[str],
) -> dict[str, Any]:
    base_metrics = metrics(rows)
    funded_metrics = metrics(rows, "realized_R_including_funding_estimate")
    return {
        "composite_id": composite_id,
        "window_id": window_id,
        "state": "PASS_ZERO_DELTA_CONTEXT_PARITY",
        "child_module_ids": list(child_module_ids),
        "trade_count": len(rows),
        "base_event_set_sha256": event_set_sha(rows),
        "candidate_event_set_sha256": event_set_sha(rows),
        "event_set_identical": True,
        "base_metrics": base_metrics,
        "candidate_metrics": base_metrics,
        "candidate_metrics_including_funding_estimate": funded_metrics,
        "delta_net_R": 0.0,
        "delta_expectancy_R": 0.0,
        "delta_max_drawdown_R": 0.0,
        "direct_alpha_claim_allowed": False,
        "economic_superiority_claim_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "action": "hold",
    }


def blocked_result(
    composite_id: str,
    window_id: str,
    child_module_ids: Sequence[str],
    blockers: Sequence[str],
) -> dict[str, Any]:
    return {
        "composite_id": composite_id,
        "window_id": window_id,
        "state": "HOLD_COMPOSITE_COUNTERFACTUAL_NOT_EXECUTABLE",
        "child_module_ids": list(child_module_ids),
        "blockers": sorted(set(blockers)),
        "trade_count": 0,
        "metrics": None,
        "direct_alpha_claim_allowed": False,
        "economic_superiority_claim_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "action": "hold",
    }


def evaluate_window(
    window_id: str,
    rows: Sequence[Mapping[str, Any]],
    plans: Sequence[Mapping[str, Any]],
    method_behavior: Mapping[str, Any],
    lico_readiness: Mapping[str, Any],
    source_root: Path,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for plan in plans:
        composite_id = str(plan.get("composite_id") or "")
        children = [str(value) for value in plan.get("child_module_ids", [])]
        classification = plan.get("classification") if isinstance(plan.get("classification"), dict) else {}
        candidate_class = str(classification.get("candidate_class") or "")
        blockers = candidate_blockers(plan, method_behavior, lico_readiness, source_root)
        if candidate_class == "W2_CONTEXT_PARITY_ONLY" and not blockers:
            result = parity_result(composite_id, window_id, rows, children)
        else:
            result = blocked_result(composite_id, window_id, children, blockers or [candidate_class or "UNCLASSIFIED"])
        result["candidate_class"] = candidate_class
        result["plan_sha256"] = plan.get("plan_sha256")
        result["valid_order_permutation_count"] = plan.get("valid_order_permutation_count")
        result["rejected_order_permutation_count"] = plan.get("rejected_order_permutation_count")
        results.append(result)
    results.sort(key=lambda row: row["composite_id"])
    parity = [row for row in results if row["state"] == "PASS_ZERO_DELTA_CONTEXT_PARITY"]
    blocked = [row for row in results if row["state"].startswith("HOLD_")]
    base_metrics = metrics(rows)
    return {
        "window_id": window_id,
        "trade_count": len(rows),
        "strategy_count_with_trades": len({str(row.get("strategy_id") or "") for row in rows}),
        "event_set_sha256": event_set_sha(rows),
        "base_metrics": base_metrics,
        "base_metrics_including_funding_estimate": metrics(rows, "realized_R_including_funding_estimate"),
        "by_symbol": grouped_metrics(rows, "symbol"),
        "by_regime": grouped_metrics(rows, "regime"),
        "by_side": grouped_metrics(rows, "side"),
        "candidate_count": len(results),
        "parity_control_count": len(parity),
        "economic_survivor_count": 0,
        "blocked_candidate_count": len(blocked),
        "candidate_results": results,
    }


def stage_receipt(
    stage_id: str,
    window: Mapping[str, Any],
    predecessor_sha256: str,
    terminal_sha256: str,
    plan_sha256: str,
) -> dict[str, Any]:
    parity_count = int(window.get("parity_control_count") or 0)
    blocked_count = int(window.get("blocked_candidate_count") or 0)
    if parity_count > 0:
        state = f"PASS_COMPOSITE_{stage_id}_PARITY_ONLY_NO_ALPHA"
    else:
        state = f"HOLD_COMPOSITE_{stage_id}_NO_EXECUTABLE_CONTROL"
    receipt: dict[str, Any] = {
        "schema_version": f"zel.composite.{stage_id.casefold()}.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "stage_id": stage_id,
        "state": state,
        "window_id": window.get("window_id"),
        "terminal_receipt_sha256": terminal_sha256,
        "ablation_plan_sha256": plan_sha256,
        "predecessor_receipt_sha256": predecessor_sha256,
        "trade_count": window.get("trade_count"),
        "strategy_count_with_trades": window.get("strategy_count_with_trades"),
        "candidate_count": window.get("candidate_count"),
        "parity_control_count": parity_count,
        "economic_survivor_count": 0,
        "blocked_candidate_count": blocked_count,
        "base_metrics": window.get("base_metrics"),
        "base_metrics_including_funding_estimate": window.get("base_metrics_including_funding_estimate"),
        "by_symbol": window.get("by_symbol"),
        "by_regime": window.get("by_regime"),
        "by_side": window.get("by_side"),
        "candidate_results": window.get("candidate_results"),
        "new_nonoverlap_window": True,
        "same_dataset_search_forbidden": True,
        "economic_superiority_claim_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "runtime_binding_allowed": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def load_governor(path: Path):
    name = "zel_composite_portfolio_governor_runtime"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("PORTFOLIO_GOVERNOR_IMPORT_SPEC_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def joint_risk_receipt(
    w3: Mapping[str, Any],
    source_root: Path,
    plan_sha256: str,
) -> dict[str, Any]:
    controls = [
        row
        for row in w3.get("candidate_results", [])
        if isinstance(row, dict) and row.get("state") == "PASS_ZERO_DELTA_CONTEXT_PARITY"
    ][:5]
    materials = []
    for index, row in enumerate(controls):
        metrics_row = row.get("candidate_metrics") if isinstance(row.get("candidate_metrics"), dict) else {}
        materials.append(
            {
                "material_id": row.get("composite_id"),
                "classification": "CORE",
                "material_sealed": True,
                "net_after_cost": 0.0,
                "confidence": 0.0,
                "uncertainty": 1.0,
                "dd_pct": abs(float(metrics_row.get("max_drawdown_R") or 0.0)),
                "joint_tail_dd_pct": abs(float(metrics_row.get("max_drawdown_R") or 0.0)),
                "cost_pct": 0.0,
                "capacity_score": 0.0,
                "incumbent_weight": 1.0 / max(len(controls), 1),
            }
        )
    governor_status = "HOLD_PORTFOLIO_GOVERNOR"
    governor_blockers: list[str] = []
    governor_output: dict[str, Any] = {}
    if len(materials) < 2:
        governor_blockers.append("MATERIAL_COUNT_OUT_OF_RANGE")
    else:
        payload = {
            "candidate_set_sha": stable_sha(sorted(str(row.get("composite_id") or "") for row in controls)),
            "correlation_artifact_sha": stable_sha({"mode": "PARITY_CONTROLS_ZERO_DELTA", "controls": [row.get("composite_id") for row in controls]}),
            "materials": materials,
            "policy": {
                "total_risk_budget": 1.0,
                "max_material_weight": 0.5,
                "min_material_weight": 0.0,
                "max_turnover": 0.25,
            },
            "research_only": True,
            "promotion_authority": False,
            "protected_mutations": 0,
            "execution_allowed": False,
            "order_authority": "BLOCKED",
            "runtime_bound": False,
        }
        try:
            governor = load_governor(source_root / "backend/research/strategy11_portfolio_governor_v1.py")
            governor_output = governor.govern(payload)
            governor_status = str(governor_output.get("status") or governor_status)
            governor_blockers = list(governor_output.get("blockers") or [])
        except Exception as exc:
            governor_blockers = [str(exc)[:1000]]
    expected_no_edge = "NO_POSITIVE_RISK_ADJUSTED_EDGE" in governor_blockers
    state = (
        "PASS_COMPOSITE_PORTFOLIO_JOINT_RISK_RETAIN_INCUMBENT_NO_EDGE"
        if expected_no_edge or (not materials and governor_blockers)
        else "HOLD_COMPOSITE_PORTFOLIO_JOINT_RISK_REVIEW"
    )
    receipt: dict[str, Any] = {
        "schema_version": "zel.composite.portfolio_joint_risk.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "stage_id": "PORTFOLIO_JOINT_RISK",
        "state": state,
        "predecessor_receipt_sha256": w3.get("receipt_sha256"),
        "ablation_plan_sha256": plan_sha256,
        "material_count": len(materials),
        "economic_material_count": 0,
        "parity_control_material_count": len(materials),
        "governor_status": governor_status,
        "governor_blockers": governor_blockers,
        "governor_output": governor_output,
        "target_risk_weights": {},
        "incumbent_weights_retained": True,
        "economic_superiority_claim_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "runtime_binding_allowed": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def evaluate(
    terminal_root: Path,
    plan_path: Path,
    contract_path: Path,
    source_root: Path,
) -> dict[str, Any]:
    terminal, report, artifact_manifest, trades, terminal_errors = validate_terminal(terminal_root)
    plan = load_json(plan_path)
    contract = load_json(contract_path)
    errors = list(terminal_errors)
    if plan.get("state") != "PASS_COMPOSITE_ABLATION_ORDER_PLAN":
        errors.append(f"PLAN_STATE:{plan.get('state')}")
    if int(plan.get("candidate_count") or 0) != 30:
        errors.append("PLAN_CANDIDATE_COUNT_NOT_30")
    if contract.get("schema_version") != "zel.composite.adapter_contract.v1":
        errors.append("ADAPTER_CONTRACT_SCHEMA")
    strategy_ids = [str(row.get("strategy_id") or "") for row in trades]
    method_behavior = trade_method_behavior(source_root, strategy_ids)
    if method_behavior.get("unsafe_strategy_count"):
        errors.append("TRADE_METHOD_AUTHORITY_UNSAFE")
    lico_readiness = lico_history_readiness(trades)
    window_rows = {
        window_id: [row for row in trades if str(row.get("window_id") or "") == window_id]
        for window_id in WINDOW_ORDER
    }
    if any(not window_rows[window_id] for window_id in WINDOW_ORDER):
        errors.append("EMPTY_REQUIRED_WINDOW")
    plans = plan.get("plans") if isinstance(plan.get("plans"), list) else []
    windows = {
        window_id: evaluate_window(
            window_id,
            window_rows[window_id],
            plans,
            method_behavior,
            lico_readiness,
            source_root,
        )
        for window_id in WINDOW_ORDER
    }
    terminal_sha = stable_sha(terminal)
    plan_sha = str(plan.get("receipt_sha256") or stable_sha(plan))
    ablation = stage_receipt("W1_ABLATION", windows["1m_w1"], terminal_sha, terminal_sha, plan_sha)
    w2 = stage_receipt("W2_FORWARD", windows["1m_w2"], str(ablation["receipt_sha256"]), terminal_sha, plan_sha)
    w3 = stage_receipt("W3_DURABILITY", windows["1m_w3"], str(w2["receipt_sha256"]), terminal_sha, plan_sha)
    joint = joint_risk_receipt(w3, source_root, plan_sha)
    stage_states = [ablation["state"], w2["state"], w3["state"], joint["state"]]
    stage_complete = all(state.startswith("PASS_") for state in stage_states)
    state = (
        "PASS_COMPOSITE_POST_TERMINAL_SEQUENCE_COMPLETE_RETAIN_INCUMBENT"
        if not errors and stage_complete
        else "HOLD_COMPOSITE_POST_TERMINAL_SEQUENCE"
    )
    result: dict[str, Any] = {
        "schema_version": "zel.composite.post_terminal_sequence.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "terminal_receipt_sha256": terminal_sha,
        "terminal_artifact_manifest_sha256": stable_sha(artifact_manifest),
        "terminal_report_sha256": stable_sha(report),
        "terminal_trades_sha256": sha256_path(terminal_root / "trades.jsonl.gz"),
        "ablation_plan_sha256": plan_sha,
        "adapter_contract_sha256": stable_sha(contract),
        "source_pin_sha256": stable_sha(load_json(source_root / "backend/research/zel_composite_live_source_pin_v1.json")),
        "strategy_count_completed": (report.get("replay") or {}).get("strategy_count_completed"),
        "closed_trade_count": len(trades),
        "window_trade_counts": {window_id: len(rows) for window_id, rows in window_rows.items()},
        "duplicate_event_count": len(trades) - len({str(row.get("event_id") or "") for row in trades}),
        "trade_method_behavior": method_behavior,
        "lico_history_readiness": lico_readiness,
        "stages": {
            "W1_ABLATION": ablation,
            "W2_FORWARD": w2,
            "W3_DURABILITY": w3,
            "PORTFOLIO_JOINT_RISK": joint,
        },
        "economic_survivor_count": 0,
        "incumbent_retained": True,
        "errors": sorted(set(errors)),
        "economic_superiority_claim_allowed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "runtime_binding_allowed": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    result["sequence_id"] = stable_sha(
        {
            "terminal": result["terminal_receipt_sha256"],
            "trades": result["terminal_trades_sha256"],
            "plan": plan_sha,
            "contract": result["adapter_contract_sha256"],
            "source_pin": result["source_pin_sha256"],
        }
    )
    result["receipt_sha256"] = stable_sha(result)
    return result


def write_outputs(out_dir: Path, result: Mapping[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "latest.json": result,
        "w1_ablation.json": result["stages"]["W1_ABLATION"],
        "w2_forward.json": result["stages"]["W2_FORWARD"],
        "w3_durability.json": result["stages"]["W3_DURABILITY"],
        "portfolio_joint_risk.json": result["stages"]["PORTFOLIO_JOINT_RISK"],
    }
    for name, payload in outputs.items():
        (out_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n",
            encoding="utf-8",
        )


def self_test() -> None:
    rows = [
        {
            "event_id": "e1",
            "strategy_id": "s1",
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_ts": "2026-01-01T00:00:00Z",
            "exit_ts": "2026-01-01T01:00:00Z",
            "realized_R": 1.0,
            "realized_R_including_funding_estimate": 0.9,
            "MFE_R": 1.2,
            "MAE_R": -0.2,
            "time_exposure_min": 60.0,
            "regime": "long",
            "window_id": "1m_w1",
            "data_interval": "1m",
            "initial_risk_usdt": 1.0,
            "fee": 0.1,
            "slippage": 0.01,
            "funding_pnl_estimate_usdt": -0.1,
        },
        {
            "event_id": "e2",
            "strategy_id": "s1",
            "symbol": "BTCUSDT",
            "side": "short",
            "entry_ts": "2026-01-02T00:00:00Z",
            "exit_ts": "2026-01-02T01:00:00Z",
            "realized_R": -0.5,
            "realized_R_including_funding_estimate": -0.45,
            "MFE_R": 0.2,
            "MAE_R": -0.7,
            "time_exposure_min": 60.0,
            "regime": "short",
            "window_id": "1m_w1",
            "data_interval": "1m",
            "initial_risk_usdt": 1.0,
            "fee": 0.1,
            "slippage": 0.01,
            "funding_pnl_estimate_usdt": 0.05,
        },
    ]
    value = metrics(rows)
    assert value["sample_count"] == 2, value
    assert abs(float(value["net_R"]) - 0.5) < 1e-12, value
    assert abs(float(value["profit_factor"]) - 2.0) < 1e-12, value
    parity = parity_result("C1", "1m_w1", rows, ["STRATEGY_SIGNAL", "LBOT"])
    assert parity["event_set_identical"] is True, parity
    assert parity["delta_net_R"] == 0.0, parity
    assert lico_history_readiness(rows)["state"] == "HOLD_LICO_HISTORICAL_MIN_DATA_MISSING"
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.terminal_root or not args.plan or not args.contract or not args.source_root or not args.out_dir:
        parser.error("terminal-root, plan, contract, source-root and out-dir are required")
    result = evaluate(
        args.terminal_root.resolve(),
        args.plan.resolve(),
        args.contract.resolve(),
        args.source_root.resolve(),
    )
    write_outputs(args.out_dir.resolve(), result)
    print(
        json.dumps(
            {
                "state": result["state"],
                "sequence_id": result["sequence_id"],
                "trades": result["closed_trade_count"],
                "windows": result["window_trade_counts"],
                "economic_survivors": result["economic_survivor_count"],
                "incumbent_retained": result["incumbent_retained"],
                "errors": result["errors"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
