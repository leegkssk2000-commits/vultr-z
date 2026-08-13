from __future__ import annotations

import argparse
import fcntl
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production.zel_production_ai_admission_executor_v1 import _execution_cost_bps, _finite
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_pre_survivor_progress.v1"
POLICY_SCHEMA = "zel.production_pre_survivor_progress_policy.v1"
HISTORY_SCHEMA = "zel.production_pre_survivor_progress_event.v1"
FEEDBACK_SCHEMA = "zel.production_pre_survivor_feedback.v1"
DEFAULT_POLICY = Path("config/zel_production_pre_survivor_progress_v1.json")

RANKING_METHOD = "LEXICOGRAPHIC_NO_WEIGHT_OBSERVATION_ONLY"
RANKING_FIELDS = [
    "net_expectancy_bps_desc",
    "profit_factor_desc",
    "max_drawdown_bps_asc",
    "net_pnl_bps_desc",
    "trade_count_desc",
]


def _authority_guard(row: Mapping[str, Any], prefix: str) -> None:
    if row.get("selection_authority") is not False or row.get("promotion_authority") is not False:
        raise RuntimeError(f"{prefix}_SELECTION_AUTHORITY_FORBIDDEN")
    if row.get("execution_authority") != "NONE" or row.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_EXECUTION_AUTHORITY_FORBIDDEN")
    if row.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{prefix}_LIVE_AUTHORITY_FORBIDDEN")
    if row.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{prefix}_EXCHANGE_ORDER_FORBIDDEN")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_NON_PAPER_FORBIDDEN")
    for key in (
        "admission_result_path",
        "observation_history_path",
        "execution_cost_authority_path",
        "state_path",
        "history_path",
        "feedback_path",
    ):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"PRE_SURVIVOR_PROGRESS_PATH_MISSING:{key}")
    if policy.get("ranking_method") != RANKING_METHOD or list(policy.get("ranking_fields") or []) != RANKING_FIELDS:
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_RANKING_DRIFT")
    if policy.get("win_rate_role") != "OBSERVATION_ONLY_NOT_GATE":
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_WIN_RATE_ROLE_DRIFT")
    if policy.get("numeric_threshold_proposals_allowed") is not False or policy.get("parameter_search_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_SEARCH_FORBIDDEN")
    _authority_guard(policy, "PRE_SURVIVOR_PROGRESS_POLICY")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_MUTATION_FORBIDDEN")
    return dict(policy)


def read_observation_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception as exc:
            raise RuntimeError(f"PRE_SURVIVOR_PROGRESS_OBSERVATION_JSON_INVALID:{line_no}") from exc
        if not isinstance(row, dict):
            raise RuntimeError(f"PRE_SURVIVOR_PROGRESS_OBSERVATION_ROW_INVALID:{line_no}")
        rows.append(row)
    return rows


def _returns_for_contract(rows: Sequence[Mapping[str, Any]], contract_id: str, cost_bps: float) -> list[float]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping) or str(raw.get("contract_id") or "") != contract_id:
            continue
        symbol = str(raw.get("symbol") or "")
        if not symbol:
            continue
        by_symbol.setdefault(symbol, []).append(dict(raw))

    values: list[tuple[int, float]] = []
    for symbol, symbol_rows in sorted(by_symbol.items()):
        xs = sorted(symbol_rows, key=lambda x: int(x.get("outcome_candle_ts_ms") or 0))
        for cur, nxt in zip(xs, xs[1:]):
            if cur.get("context_pass") is not True:
                continue
            side = int(cur.get("signal_side") or cur.get("primary_imbalance_sign") or 0)
            if side == 0:
                continue
            entry = _finite(cur.get("outcome_close"), f"{symbol}.entry_close")
            exit_ = _finite(nxt.get("outcome_close"), f"{symbol}.next_close")
            if entry <= 0.0 or exit_ <= 0.0:
                raise RuntimeError(f"PRE_SURVIVOR_PROGRESS_PRICE_INVALID:{symbol}")
            gross_bps = side * (exit_ / entry - 1.0) * 10_000.0
            values.append((int(cur.get("outcome_candle_ts_ms") or 0), gross_bps - cost_bps))
    values.sort(key=lambda x: x[0])
    return [value for _, value in values]


def economic_metrics(values: Sequence[float]) -> dict[str, Any]:
    vals = [float(x) for x in values]
    if any(not math.isfinite(x) for x in vals):
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_RETURN_NONFINITE")
    wins = [x for x in vals if x > 0.0]
    losses = [x for x in vals if x < 0.0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    cumulative = 0.0
    peak = 0.0
    max_drawdown_bps = 0.0
    for value in vals:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown_bps = max(max_drawdown_bps, peak - cumulative)
    trade_count = len(vals)
    net_pnl_bps = sum(vals)
    return {
        "trade_count": trade_count,
        "win_count": len(wins),
        "loss_count": len(losses),
        "flat_count": trade_count - len(wins) - len(losses),
        "win_rate_pct": 100.0 * len(wins) / trade_count if trade_count else 0.0,
        "net_pnl_bps": net_pnl_bps,
        "net_pnl_pct": net_pnl_bps / 100.0,
        "net_expectancy_bps": net_pnl_bps / trade_count if trade_count else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0.0 else (999.0 if gross_profit > 0.0 else 0.0),
        "max_drawdown_bps": max_drawdown_bps,
        "max_drawdown_pct": max_drawdown_bps / 100.0,
    }


def _rank_key(metrics: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        float(metrics.get("net_expectancy_bps") or 0.0),
        float(metrics.get("profit_factor") or 0.0),
        -float(metrics.get("max_drawdown_bps") or 0.0),
        float(metrics.get("net_pnl_bps") or 0.0),
        float(metrics.get("trade_count") or 0.0),
    )


def _delta(current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(previous, Mapping):
        return None
    return {
        "trade_count": int(current.get("trade_count") or 0) - int(previous.get("trade_count") or 0),
        "win_rate_pct": float(current.get("win_rate_pct") or 0.0) - float(previous.get("win_rate_pct") or 0.0),
        "net_pnl_bps": float(current.get("net_pnl_bps") or 0.0) - float(previous.get("net_pnl_bps") or 0.0),
        "net_pnl_pct": float(current.get("net_pnl_pct") or 0.0) - float(previous.get("net_pnl_pct") or 0.0),
        "net_expectancy_bps": float(current.get("net_expectancy_bps") or 0.0) - float(previous.get("net_expectancy_bps") or 0.0),
        "profit_factor": float(current.get("profit_factor") or 0.0) - float(previous.get("profit_factor") or 0.0),
        "max_drawdown_bps": float(current.get("max_drawdown_bps") or 0.0) - float(previous.get("max_drawdown_bps") or 0.0),
        "max_drawdown_pct": float(current.get("max_drawdown_pct") or 0.0) - float(previous.get("max_drawdown_pct") or 0.0),
    }


def _direction(current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> str:
    if not isinstance(previous, Mapping):
        return "BASELINE"
    current_count = int(current.get("trade_count") or 0)
    previous_count = int(previous.get("trade_count") or 0)
    if current_count < previous_count:
        return "DATA_REGRESSION"
    current_key = _rank_key(current)
    previous_key = _rank_key(previous)
    if current_key > previous_key:
        return "IMPROVED"
    if current_key < previous_key:
        return "REGRESSED"
    return "UNCHANGED"


def _previous_family(previous_state: Mapping[str, Any] | None, identity: str) -> Mapping[str, Any] | None:
    if not isinstance(previous_state, Mapping) or previous_state.get("schema_version") != SCHEMA:
        return None
    for row in previous_state.get("families") or []:
        if isinstance(row, Mapping) and str(row.get("identity") or "") == identity:
            metrics = row.get("metrics")
            return metrics if isinstance(metrics, Mapping) else None
    return None


def progress_tick(
    policy: Mapping[str, Any],
    *,
    admission_result: Mapping[str, Any] | None,
    observation_history: Sequence[Mapping[str, Any]],
    cost_authority: Mapping[str, Any] | None,
    previous_state: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    base_safety = {
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "action": "hold",
    }
    if not isinstance(admission_result, Mapping):
        state = {
            "schema_version": SCHEMA,
            "state": "HOLD_PRE_SURVIVOR_PROGRESS_ADMISSION_MISSING",
            "families": [],
            "ranking_method": RANKING_METHOD,
            "ranking_fields": list(RANKING_FIELDS),
            "win_rate_role": "OBSERVATION_ONLY_NOT_GATE",
            "updated_at_ms": now,
            **base_safety,
        }
        state["economic_fingerprint_sha256"] = stable_sha([])
        state["receipt_sha256"] = stable_sha(state)
        feedback = {
            "schema_version": FEEDBACK_SCHEMA,
            "state": "HOLD_PRE_SURVIVOR_FEEDBACK_NO_ECONOMIC_RESULT",
            "entries": [],
            "updated_at_ms": now,
            **base_safety,
        }
        feedback["receipt_sha256"] = stable_sha(feedback)
        event = {
            "schema_version": HISTORY_SCHEMA,
            "state": state["state"],
            "economic_fingerprint_sha256": state["economic_fingerprint_sha256"],
            "families": [],
            "created_at_ms": now,
            **base_safety,
        }
        event["receipt_sha256"] = stable_sha(event)
        return state, event, feedback

    _authority_guard(admission_result, "PRE_SURVIVOR_PROGRESS_ADMISSION")
    if not isinstance(cost_authority, Mapping):
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_COST_AUTHORITY_MISSING")
    cost_bps = _execution_cost_bps(cost_authority)
    results = admission_result.get("results")
    if not isinstance(results, list):
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_RESULTS_INVALID")

    families: list[dict[str, Any]] = []
    for raw in results:
        if not isinstance(raw, Mapping):
            continue
        contract_id = str(raw.get("contract_id") or "").strip()
        family_id = str(raw.get("family_id") or "").strip()
        if not contract_id or not family_id:
            continue
        identity = f"{family_id}:{contract_id}"
        metrics = economic_metrics(_returns_for_contract(observation_history, contract_id, cost_bps))
        previous_metrics = _previous_family(previous_state, identity)
        direction = _direction(metrics, previous_metrics)
        families.append(
            {
                "identity": identity,
                "family_id": family_id,
                "contract_id": contract_id,
                "template_id": str(raw.get("template_id") or ""),
                "admission_state": str(raw.get("state") or ""),
                "economic_candidate": raw.get("economic_candidate") is True,
                "metrics": metrics,
                "delta_vs_previous": _delta(metrics, previous_metrics),
                "progress_direction": direction,
                "ranking_authority": False,
                "win_rate_role": "OBSERVATION_ONLY_NOT_GATE",
            }
        )

    fingerprint_material = [
        {
            "identity": row["identity"],
            "admission_state": row["admission_state"],
            "economic_candidate": row["economic_candidate"],
            "metrics": row["metrics"],
        }
        for row in families
    ]
    economic_fingerprint = stable_sha(fingerprint_material)
    directions = [str(row["progress_direction"]) for row in families]
    if any(direction == "DATA_REGRESSION" for direction in directions):
        state_name = "HOLD_PRE_SURVIVOR_PROGRESS_DATA_REGRESSION"
    elif not families:
        state_name = "HOLD_PRE_SURVIVOR_PROGRESS_NO_MEASURABLE_FAMILY"
    else:
        state_name = "PASS_PRE_SURVIVOR_PROGRESS_CAPTURED"

    state = {
        "schema_version": SCHEMA,
        "state": state_name,
        "admission_state": str(admission_result.get("state") or ""),
        "admission_receipt_sha256": str(admission_result.get("receipt_sha256") or ""),
        "economic_fingerprint_sha256": economic_fingerprint,
        "family_count": len(families),
        "families": families,
        "progress_summary": {
            "baseline": directions.count("BASELINE"),
            "improved": directions.count("IMPROVED"),
            "regressed": directions.count("REGRESSED"),
            "unchanged": directions.count("UNCHANGED"),
            "data_regression": directions.count("DATA_REGRESSION"),
        },
        "ranking_method": RANKING_METHOD,
        "ranking_fields": list(RANKING_FIELDS),
        "ranking_authority": False,
        "win_rate_role": "OBSERVATION_ONLY_NOT_GATE",
        "execution_cost_bps": cost_bps,
        "updated_at_ms": now,
        **base_safety,
    }
    state["receipt_sha256"] = stable_sha(state)

    feedback_entries = [
        {
            "family_id": row["family_id"],
            "contract_id": row["contract_id"],
            "template_id": row["template_id"],
            "admission_state": row["admission_state"],
            "progress_direction": row["progress_direction"],
            "metrics": dict(row["metrics"]),
            "delta_vs_previous": None if row["delta_vs_previous"] is None else dict(row["delta_vs_previous"]),
            "improvement_objective": [
                "net_expectancy_bps_up",
                "profit_factor_up",
                "max_drawdown_bps_down",
                "net_pnl_bps_up",
            ],
            "win_rate_role": "OBSERVATION_ONLY_NOT_GATE",
            "numeric_threshold_proposals_allowed": False,
            "parameter_search_allowed": False,
            "ranking_authority": False,
        }
        for row in families
    ]
    feedback = {
        "schema_version": FEEDBACK_SCHEMA,
        "state": "PASS_PRE_SURVIVOR_ECONOMIC_FEEDBACK" if feedback_entries else "HOLD_PRE_SURVIVOR_FEEDBACK_NO_MEASURABLE_FAMILY",
        "source_progress_receipt_sha256": state["receipt_sha256"],
        "entries": feedback_entries,
        "next": "EDGE_ACQUISITION_MAY_CONSUME_PROGRESS_CONTEXT",
        "numeric_threshold_proposals_allowed": False,
        "parameter_search_allowed": False,
        "updated_at_ms": now,
        **base_safety,
    }
    feedback["receipt_sha256"] = stable_sha(feedback)

    event = {
        "schema_version": HISTORY_SCHEMA,
        "state": state_name,
        "economic_fingerprint_sha256": economic_fingerprint,
        "source_progress_receipt_sha256": state["receipt_sha256"],
        "admission_receipt_sha256": state["admission_receipt_sha256"],
        "families": families,
        "progress_summary": dict(state["progress_summary"]),
        "created_at_ms": now,
        **base_safety,
    }
    event["receipt_sha256"] = stable_sha(event)
    return state, event, feedback


def append_history_event(path: Path, event: Mapping[str, Any]) -> bool:
    fingerprint = str(event.get("economic_fingerprint_sha256") or "")
    if len(fingerprint) != 64:
        raise RuntimeError("PRE_SURVIVOR_PROGRESS_FINGERPRINT_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        for line_no, raw in enumerate(fh.read().splitlines(), 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception as exc:
                raise RuntimeError(f"PRE_SURVIVOR_PROGRESS_HISTORY_JSON_INVALID:{line_no}") from exc
            if not isinstance(row, Mapping) or row.get("schema_version") != HISTORY_SCHEMA:
                raise RuntimeError(f"PRE_SURVIVOR_PROGRESS_HISTORY_ROW_INVALID:{line_no}")
            if str(row.get("economic_fingerprint_sha256") or "") == fingerprint:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                return False
        fh.seek(0, 2)
        fh.write(json.dumps(dict(event), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        fh.flush()
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    path.chmod(0o600)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Capture PAPER-only pre-survivor economic progress")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = json.loads(ns.policy.read_text(encoding="utf-8"))
    cfg = validate_policy(policy)
    state_path = Path(str(cfg["state_path"]))
    state, event, feedback = progress_tick(
        cfg,
        admission_result=read_json(Path(str(cfg["admission_result_path"]))),
        observation_history=read_observation_history(Path(str(cfg["observation_history_path"]))),
        cost_authority=read_json(Path(str(cfg["execution_cost_authority_path"]))),
        previous_state=read_json(state_path),
    )
    history_appended = append_history_event(Path(str(cfg["history_path"])), event)
    state["history_appended"] = history_appended
    state["receipt_sha256"] = stable_sha({k: v for k, v in state.items() if k != "receipt_sha256"})
    feedback["source_progress_receipt_sha256"] = state["receipt_sha256"]
    feedback["receipt_sha256"] = stable_sha({k: v for k, v in feedback.items() if k != "receipt_sha256"})
    atomic_json_write(state_path, state)
    atomic_json_write(Path(str(cfg["feedback_path"])), feedback)
    print(
        json.dumps(
            {
                "state": state["state"],
                "family_count": state["family_count"] if "family_count" in state else 0,
                "progress_summary": state.get("progress_summary", {}),
                "history_appended": history_appended,
                "receipt_sha256": state["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
