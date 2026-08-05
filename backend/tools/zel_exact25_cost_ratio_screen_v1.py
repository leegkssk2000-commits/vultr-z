from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_EXACT25_COST_RATIO_SCREEN_V1"
SCHEMA = "zel.exact25.cost_ratio.screen.v1"
CHECKPOINT_SCHEMA = "zel.exact25.cost_ratio.checkpoint.v1"
HEARTBEAT_SCHEMA = "zel.exact25.cost_ratio.heartbeat.v1"
WINDOWS = ("1m_w1", "1m_w2", "1m_w3")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def normalized_exit_reason(row: Mapping[str, Any]) -> str:
    for key in ("exit_reason", "reason", "close_reason"):
        value = str(row.get(key) or "").strip().lower()
        if value:
            return value
    return "unknown"


def row_integrity(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    identities: list[str] = []
    missing_identity = 0
    required = (
        "fee", "slippage", "funding_pnl_estimate_usdt",
        "realized_R_including_funding_estimate", "initial_risk_usdt", "entry_price",
    )
    missing_cost = 0
    for row in rows:
        identity = str(row.get("event_id") or row.get("position_id") or "").strip()
        if identity:
            identities.append(identity)
        else:
            missing_identity += 1
        if any(finite_number(row.get(key)) is None for key in required):
            missing_cost += 1
    return {
        "trade_count": len(rows),
        "identity_count": len(identities),
        "missing_identity_count": missing_identity,
        "duplicate_trade_count": len(identities) - len(set(identities)),
        "unknown_exit_count": sum(1 for row in rows if normalized_exit_reason(row) in {"", "unknown", "none", "null"}),
        "missing_cost_lineage_count": missing_cost,
        "cost_lineage_complete": missing_cost == 0,
    }


def economic_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    keys = (
        "event_id", "position_id", "strategy_id", "owner_sha256", "symbol", "window_id", "side",
        "entry_ts", "exit_ts", "entry_price", "exit_price", "qty", "original_qty", "initial_risk_usdt",
        "gross_pnl_usdt", "realized_R", "realized_R_including_funding_estimate", "h3_stressed_R",
        "fee", "slippage", "funding_pnl_estimate_usdt", "exit_reason", "reason", "close_reason",
        "data_source_sha256",
    )
    normalized: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for key in keys:
            if key not in row:
                continue
            value = row.get(key)
            if isinstance(value, float):
                value = round(value, 12) if math.isfinite(value) else None
            item[key] = value
        normalized.append(item)
    normalized.sort(key=lambda row: (
        str(row.get("event_id") or row.get("position_id") or ""),
        str(row.get("entry_ts") or ""),
        str(row.get("exit_ts") or ""),
    ))
    return stable_sha(normalized)


def apply_h3_cost_floor(rows: Sequence[Mapping[str, Any]], all_in_cost_pct: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stressed: list[dict[str, Any]] = []
    extra_total = 0.0
    applied = 0
    invalid = 0
    for source in rows:
        row = dict(source)
        entry = finite_number(row.get("entry_price"))
        qty = finite_number(row.get("original_qty")) or finite_number(row.get("qty"))
        risk = finite_number(row.get("initial_risk_usdt"))
        net_r = finite_number(row.get("realized_R_including_funding_estimate"))
        fee = finite_number(row.get("fee"))
        slippage = finite_number(row.get("slippage"))
        funding = finite_number(row.get("funding_pnl_estimate_usdt"))
        if None in (entry, qty, risk, net_r, fee, slippage, funding) or risk is None or risk <= 0:
            invalid += 1
            row["h3_stressed_R"] = None
            stressed.append(row)
            continue
        required_cost = abs(float(entry) * float(qty)) * all_in_cost_pct / 100.0
        observed_adverse = abs(float(fee)) + abs(float(slippage)) + max(0.0, -float(funding))
        extra = max(0.0, required_cost - observed_adverse)
        if extra > 0:
            applied += 1
            extra_total += extra
        row["h3_required_cost_usdt"] = required_cost
        row["h3_observed_adverse_cost_usdt"] = observed_adverse
        row["h3_extra_cost_usdt"] = extra
        row["h3_stressed_R"] = float(net_r) - extra / float(risk)
        stressed.append(row)
    return stressed, {
        "all_in_cost_pct": all_in_cost_pct,
        "stress_applied_trade_count": applied,
        "extra_cost_usdt_total": extra_total,
        "invalid_stress_lineage_count": invalid,
        "stress_lineage_complete": invalid == 0,
    }


def payoff_metrics(engine: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = dict(engine.metrics(rows, "h3_stressed_R"))
    values = [value for row in rows if (value := finite_number(row.get("h3_stressed_R"))) is not None]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    result.update({
        "average_win_R": average_win,
        "average_loss_abs_R": average_loss,
        "payoff_ratio": average_win / average_loss if average_loss else (999.0 if average_win else 0.0),
    })
    return result


def by_window(engine: Any, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output = {
        window: payoff_metrics(engine, [row for row in rows if str(row.get("window_id")) == window])
        for window in WINDOWS
    }
    output["all"] = payoff_metrics(engine, rows)
    return output


def metric_signature(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: round(float(metrics.get(key) or 0.0), 12)
        for key in ("sample_count", "win_rate", "net_R", "profit_factor", "expectancy_R", "max_drawdown_R", "payoff_ratio")
    }


def control_parity(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "economic_digest_equal": first["economic_digest_sha256"] == second["economic_digest_sha256"],
        "metrics_equal": {
            window: metric_signature(first["metrics"][window]) == metric_signature(second["metrics"][window])
            for window in (*WINDOWS, "all")
        },
        "integrity_equal": first["integrity"] == second["integrity"],
        "counters_equal": first["counters"] == second["counters"],
    }
    result["all_pass"] = (
        result["economic_digest_equal"]
        and all(result["metrics_equal"].values())
        and result["integrity_equal"]
        and result["counters_equal"]
    )
    return result


def absolute_gate(metrics: Mapping[str, Any], baseline_count: int, minimum_count: int, policy: Mapping[str, Any]) -> tuple[bool, list[str], float]:
    count = int(metrics.get("sample_count") or 0)
    retention = count / baseline_count * 100.0 if baseline_count else 0.0
    blockers: list[str] = []
    if count < minimum_count:
        blockers.append("SAMPLE_BELOW_MIN")
    if retention < float(policy["minimum_retention_pct"]):
        blockers.append("RETENTION_BELOW_MIN")
    if float(metrics.get("net_R") or 0.0) <= 0:
        blockers.append("NET_R_NOT_POSITIVE")
    if float(metrics.get("profit_factor") or 0.0) < 1.0:
        blockers.append("PF_BELOW_ONE")
    if float(metrics.get("expectancy_R") or 0.0) <= 0:
        blockers.append("EXPECTANCY_NOT_POSITIVE")
    if float(metrics.get("payoff_ratio") or 0.0) < 1.0:
        blockers.append("PAYOFF_BELOW_ONE")
    return not blockers, blockers, retention


def beats_control(candidate: Mapping[str, Any], control: Mapping[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if float(candidate.get("net_R") or 0.0) <= float(control.get("net_R") or 0.0):
        blockers.append("NET_R_NOT_ABOVE_CONTROL")
    if float(candidate.get("profit_factor") or 0.0) < float(control.get("profit_factor") or 0.0):
        blockers.append("PF_WORSE_THAN_CONTROL")
    if float(candidate.get("max_drawdown_R") or 0.0) > float(control.get("max_drawdown_R") or 0.0):
        blockers.append("DD_WORSE_THAN_CONTROL")
    return not blockers, blockers


class CostRatioOwner:
    def __init__(self, base: Any, producer: Any, strategy_id: str, symbol: str, interval: str, axis_id: str, config: Mapping[str, Any]) -> None:
        self.base = base
        self.producer = producer
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.interval = interval
        self.axis_id = axis_id
        self.config = dict(config)
        self.owner_sha256 = stable_sha({
            "base_owner_sha256": str(getattr(base, "owner_sha256", "")),
            "axis_id": axis_id,
            "config": self.config,
            "version": VERSION,
        })
        self.valid_entry_count = 0
        self.blocked_entry_count = 0
        self.unknown_side_count = 0
        self.minimum_observed_ratio: float | None = None
        self.maximum_observed_ratio: float | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def strategy(self, current: Any, state: Any = None, risk_action: str = "hold") -> dict[str, Any]:
        result = self.base.strategy(current, state=state, risk_action=risk_action)
        if not isinstance(result, dict) or state is not None:
            return result
        current_price = float(current["close"].iloc[-1])
        if self.producer.valid_entry(result, current_price) is None:
            return result
        self.valid_entry_count += 1
        try:
            position = self.producer.make_position(
                self.strategy_id,
                str(getattr(self.base, "owner_sha256", "")),
                self.symbol,
                self.interval,
                result,
                current,
                1.0,
                0.0005,
                1.0,
            )
        except Exception:
            position = None
        if not isinstance(position, Mapping):
            self.unknown_side_count += 1
            return result
        entry = finite_number(position.get("entry_price"))
        qty = finite_number(position.get("original_qty")) or finite_number(position.get("qty"))
        risk = finite_number(position.get("initial_risk_usdt"))
        all_in = finite_number(self.config.get("all_in_cost_pct"))
        threshold = finite_number(self.config.get("ratio_threshold"))
        if None in (entry, qty, risk, all_in, threshold) or float(entry) * float(qty) == 0 or float(all_in) <= 0:
            self.unknown_side_count += 1
            return result
        risk_distance_pct = float(risk) / abs(float(entry) * float(qty)) * 100.0
        ratio = risk_distance_pct / float(all_in)
        self.minimum_observed_ratio = ratio if self.minimum_observed_ratio is None else min(self.minimum_observed_ratio, ratio)
        self.maximum_observed_ratio = ratio if self.maximum_observed_ratio is None else max(self.maximum_observed_ratio, ratio)
        if ratio >= float(threshold):
            return result
        self.blocked_entry_count += 1
        return {"action": "hold", "reason": "research_entry_risk_to_all_in_cost_ratio", "research_only": True}


def checkpoint_path(root: Path, unit: str) -> Path:
    return root / f"{unit}.json"


def checkpoint_save(path: Path, fingerprint: str, unit: str, body: Mapping[str, Any]) -> None:
    payload: dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_fingerprint": fingerprint,
        "unit": unit,
        "body": dict(body),
        "body_sha256": stable_sha(body),
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    payload["checkpoint_sha256"] = stable_sha(payload)
    atomic_json(path, payload)


def checkpoint_load(path: Path, fingerprint: str, unit: str) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = read_json(path)
    expected = str(payload.get("checkpoint_sha256") or "")
    material = dict(payload)
    material.pop("checkpoint_sha256", None)
    if stable_sha(material) != expected or payload.get("input_fingerprint") != fingerprint or payload.get("unit") != unit:
        raise RuntimeError(f"CHECKPOINT_VALIDATION_FAIL:{path}")
    body = payload.get("body")
    if not isinstance(body, Mapping) or stable_sha(body) != payload.get("body_sha256"):
        raise RuntimeError(f"CHECKPOINT_BODY_FAIL:{path}")
    return dict(body)


def heartbeat(path: Path, fingerprint: str, state: str, completed: Sequence[str], current: str | None, expected: int, error: str | None = None) -> None:
    payload: dict[str, Any] = {
        "schema_version": HEARTBEAT_SCHEMA,
        "version": VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "input_fingerprint": fingerprint,
        "state": state,
        "completed_units": list(completed),
        "completed_count": len(completed),
        "expected_count": expected,
        "current_unit": current,
        "error": error,
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    payload["receipt_sha256"] = stable_sha(payload)
    atomic_json(path, payload)


def with_heartbeat(callback: Any, heartbeat_out: Path, fingerprint: str, completed: Sequence[str], current: str, expected: int) -> Any:
    stop = threading.Event()

    def emit() -> None:
        while not stop.wait(60.0):
            heartbeat(heartbeat_out, fingerprint, "RUNNING", completed, current, expected)

    thread = threading.Thread(target=emit, daemon=True)
    thread.start()
    try:
        return callback()
    finally:
        stop.set()
        thread.join(timeout=5.0)


def replay_unit(
    selected: Any,
    cost_floor: Any,
    engine_path: Path,
    source_root: Path,
    data_root: Path,
    strategy_id: str,
    all_in_cost_pct: float,
    mode: str,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    original_wrapper = selected.FilteredOwner
    replay_config: Mapping[str, Any] | None = None
    try:
        axis_id: str | None = None
        if mode == "incumbent":
            selected.FilteredOwner = cost_floor.RiskDistanceOwner
            axis_id = "MIN_ENTRY_RISK_DISTANCE_PCT"
            replay_config = {"config_id": "DIAGNOSTIC_INCUMBENT_016PCT", "minimum_risk_distance_pct": 0.16}
        elif mode == "candidate":
            selected.FilteredOwner = CostRatioOwner
            axis_id = "ENTRY_RISK_DISTANCE_TO_ALL_IN_COST_RATIO"
            replay_config = dict(config or {})
        card, raw_rows, counters = selected.run_replay(
            engine_path, source_root, data_root, strategy_id, axis_id, replay_config
        )
    finally:
        selected.FilteredOwner = original_wrapper
    engine = load_module(engine_path, f"zel_gen3_metric_{mode}_{os.getpid()}_{stable_sha(config or {})[:8]}")
    stressed_rows, stress = apply_h3_cost_floor(raw_rows, all_in_cost_pct)
    return {
        "mode": mode,
        "config": dict(replay_config or {}),
        "config_sha256": stable_sha(replay_config or {}),
        "metrics": by_window(engine, stressed_rows),
        "counters": dict(counters),
        "integrity": row_integrity(stressed_rows),
        "h3_cost_stress": stress,
        "economic_digest_sha256": economic_digest(stressed_rows),
        "source_owner_sha256": str(card.get("owner_sha256") or ""),
        "raw_trade_rows_published": False,
    }


def validate_binding(binding: Mapping[str, Any], expanded: Mapping[str, Any]) -> float:
    dataset = binding.get("expanded_dataset") if isinstance(binding.get("expanded_dataset"), Mapping) else {}
    cost = binding.get("cost_receipt") if isinstance(binding.get("cost_receipt"), Mapping) else {}
    if expanded.get("state") != "PASS_EXPANDED_1M_PARTITIONS_PREPARED":
        raise RuntimeError("EXPANDED_PARTITIONS_NOT_PASS")
    if dataset.get("dataset_sha256") != expanded.get("source_dataset_sha256"):
        raise RuntimeError("EXPANDED_DATASET_BINDING_MISMATCH")
    if dataset.get("verification_receipt_sha256") != expanded.get("source_verification_receipt_sha256"):
        raise RuntimeError("EXPANDED_VERIFY_BINDING_MISMATCH")
    if cost.get("state") != "PASS_BINGX_LIGHT_CALIBRATION":
        raise RuntimeError("H3_COST_RECEIPT_NOT_PASS")
    if cost.get("h3_receipt_sha256") != "c7f00381c2805efc3380c6d2392c134278ea9a15c4a51d0e2020f6bd145ea912":
        raise RuntimeError("H3_RECEIPT_SHA_MISMATCH")
    if cost.get("plus_one_bar_receipt_sha256") != "481ad99a2a39f420bd8b99be09440abc2eb9ddc4014285315a22f9550659cb55":
        raise RuntimeError("PLUS_ONE_BAR_RECEIPT_SHA_MISMATCH")
    if int(binding.get("protected_mutations", -1)) != 0:
        raise RuntimeError("BINDING_PROTECTED_MUTATION_FAIL")
    all_in = finite_number(cost.get("all_in_cost_pct"))
    if all_in is None or all_in <= 0:
        raise RuntimeError("ALL_IN_COST_BINDING_INVALID")
    parts = sum(float(cost[key]) for key in ("round_trip_fee_pct", "slippage_stress_pct", "funding_horizon_pct"))
    if abs(parts - all_in) > 1e-12:
        raise RuntimeError("ALL_IN_COST_SUM_MISMATCH")
    return all_in


def operational_pass(unit: Mapping[str, Any], *, candidate: bool = False) -> bool:
    counters = unit["counters"]
    integrity = unit["integrity"]
    return (
        int(counters.get("error_count") or 0) == 0
        and int(counters.get("censored_open_count") or 0) == 0
        and (not candidate or int(counters.get("blocked_entry_count") or 0) > 0)
        and int(counters.get("unknown_side_count") or 0) == 0
        and integrity["missing_identity_count"] == 0
        and integrity["duplicate_trade_count"] == 0
        and integrity["unknown_exit_count"] == 0
        and integrity["cost_lineage_complete"] is True
        and unit["h3_cost_stress"]["stress_lineage_complete"] is True
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    selected = load_module(args.selected_helper.resolve(), f"zel_selected_gen3_{os.getpid()}")
    cost_floor = load_module(args.cost_floor_helper.resolve(), f"zel_cost_floor_gen3_{os.getpid()}")
    policy = read_json(args.policy.resolve())
    binding = read_json(args.binding.resolve())
    expanded = read_json(args.expanded_receipt.resolve())
    all_in_cost_pct = validate_binding(binding, expanded)
    configs = [
        {
            "config_id": f"COST_RATIO_{str(value).replace('.', '_')}",
            "ratio_threshold": float(value),
            "all_in_cost_pct": all_in_cost_pct,
        }
        for value in policy["candidate_ratio_thresholds"]
    ]
    fingerprint_material = {
        "version": VERSION,
        "engine_sha256": file_sha(args.engine.resolve()),
        "selected_helper_sha256": file_sha(args.selected_helper.resolve()),
        "cost_floor_helper_sha256": file_sha(args.cost_floor_helper.resolve()),
        "screen_sha256": file_sha(Path(__file__).resolve()),
        "policy_sha256": file_sha(args.policy.resolve()),
        "binding_sha256": file_sha(args.binding.resolve()),
        "expanded_receipt_binding": {
            "state": expanded["state"],
            "partition_sha256": expanded["partition_sha256"],
            "source_dataset_sha256": expanded["source_dataset_sha256"],
            "source_verification_receipt_sha256": expanded["source_verification_receipt_sha256"],
            "total_1m_rows": expanded["total_1m_rows"],
        },
        "source_root": str(args.source_root.resolve()),
        "strategy_id": policy["strategy_id"],
        "configs": configs,
    }
    fingerprint = stable_sha(fingerprint_material)
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    completed: list[str] = []
    expected = 3 + len(configs)
    heartbeat(args.heartbeat_out, fingerprint, "STARTING", completed, None, expected)

    def unit(name: str, mode: str, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
        path = checkpoint_path(args.checkpoint_dir, name)
        cached = checkpoint_load(path, fingerprint, name)
        if cached is not None:
            completed.append(name)
            heartbeat(args.heartbeat_out, fingerprint, "CHECKPOINT_REUSED", completed, name, expected)
            return cached
        body = with_heartbeat(
            lambda: replay_unit(
                selected,
                cost_floor,
                args.engine.resolve(),
                args.source_root.resolve(),
                args.data_root.resolve(),
                str(policy["strategy_id"]),
                all_in_cost_pct,
                mode,
                config,
            ),
            args.heartbeat_out,
            fingerprint,
            completed,
            name,
            expected,
        )
        checkpoint_save(path, fingerprint, name, body)
        completed.append(name)
        heartbeat(args.heartbeat_out, fingerprint, "CHECKPOINT_COMMITTED", completed, name, expected)
        return body

    try:
        baseline_a = unit("baseline-a", "baseline")
        baseline_b = unit("baseline-b", "baseline")
        parity = control_parity(baseline_a, baseline_b)
        if not parity["all_pass"]:
            raise RuntimeError(f"DOUBLE_BASELINE_PARITY_FAIL:{parity}")
        incumbent = unit("incumbent-016", "incumbent")
        candidates = [
            unit(f"candidate-{index:02d}", "candidate", config)
            for index, config in enumerate(configs, 1)
        ]
        if not operational_pass(baseline_a):
            raise RuntimeError(f"EXPANDED_BASELINE_INTEGRITY_FAIL:{baseline_a}")
        gate = policy["positive_gate"]
        assessed: list[dict[str, Any]] = []
        for candidate in candidates:
            w1_abs, abs_blockers, retention = absolute_gate(
                candidate["metrics"]["1m_w1"],
                int(baseline_a["metrics"]["1m_w1"].get("sample_count") or 0),
                int(gate["minimum_w1_trade_count"]),
                gate,
            )
            raw_pass, raw_blockers = beats_control(candidate["metrics"]["1m_w1"], baseline_a["metrics"]["1m_w1"])
            inc_pass, inc_blockers = beats_control(candidate["metrics"]["1m_w1"], incumbent["metrics"]["1m_w1"])
            blockers = abs_blockers + [f"RAW_{item}" for item in raw_blockers] + [f"INC_{item}" for item in inc_blockers]
            operational = operational_pass(candidate, candidate=True)
            if not operational:
                blockers.append("OPERATIONAL_INTEGRITY_FAIL")
            row = dict(candidate)
            row.update({
                "w1_pass": operational and w1_abs and raw_pass and inc_pass,
                "w1_retention_pct": retention,
                "w1_blockers": blockers,
            })
            assessed.append(row)
        eligible = [row for row in assessed if row["w1_pass"]]
        selected_candidate = max(
            eligible,
            key=lambda row: (
                float(row["metrics"]["1m_w1"].get("net_R") or 0.0),
                float(row["metrics"]["1m_w1"].get("profit_factor") or 0.0),
                float(row["metrics"]["1m_w1"].get("payoff_ratio") or 0.0),
            ),
            default=None,
        )
        confirmation: dict[str, Any] = {}
        survivor = False
        if selected_candidate is not None:
            all_pass = True
            for window in ("1m_w2", "1m_w3", "all"):
                passed, blockers, retention = absolute_gate(
                    selected_candidate["metrics"][window],
                    int(baseline_a["metrics"][window].get("sample_count") or 0),
                    int(gate["minimum_confirmation_trade_count"]),
                    gate,
                )
                raw_pass, raw_blockers = beats_control(selected_candidate["metrics"][window], baseline_a["metrics"][window])
                inc_pass, inc_blockers = beats_control(selected_candidate["metrics"][window], incumbent["metrics"][window])
                window_pass = passed and raw_pass and inc_pass
                confirmation[window] = {
                    "pass": window_pass,
                    "blockers": blockers + [f"RAW_{item}" for item in raw_blockers] + [f"INC_{item}" for item in inc_blockers],
                    "retention_pct": retention,
                    "baseline": baseline_a["metrics"][window],
                    "incumbent": incumbent["metrics"][window],
                    "candidate": selected_candidate["metrics"][window],
                }
                all_pass = all_pass and window_pass
            survivor = all_pass
        diagnostic_best = max(
            assessed,
            key=lambda row: (
                float(row["metrics"]["1m_w1"].get("net_R") or -1e99),
                float(row["w1_retention_pct"]),
            ),
            default=None,
        )
        receipt: dict[str, Any] = {
            "schema_version": SCHEMA,
            "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": "PASS_SCALP_GEN3_COST_RATIO_COMPLETE",
            "input_fingerprint": fingerprint,
            "input_fingerprint_material": fingerprint_material,
            "strategy_id": policy["strategy_id"],
            "axis_id": policy["axis_id"],
            "expanded_dataset": {
                "source_dataset_sha256": expanded["source_dataset_sha256"],
                "partition_sha256": expanded["partition_sha256"],
                "total_1m_rows": expanded["total_1m_rows"],
                "receipt_sha256": expanded["receipt_sha256"],
            },
            "h3_cost_binding": binding["cost_receipt"],
            "double_baseline_parity": parity,
            "baseline": baseline_a,
            "diagnostic_incumbent_016pct": incumbent,
            "candidate_count": len(assessed),
            "candidates": assessed,
            "selected_config": selected_candidate["config"] if selected_candidate else None,
            "selected_config_sha256": selected_candidate["config_sha256"] if selected_candidate else None,
            "diagnostic_best_config": diagnostic_best["config"] if diagnostic_best else None,
            "confirmation": confirmation,
            "survivor": survivor,
            "survivor_state": "PASS_POSITIVE_W1_W2_W3_SCALP_GEN3_SURVIVOR" if survivor else "HOLD_NO_POSITIVE_SCALP_GEN3_SURVIVOR",
            "entry_time_information_only": True,
            "future_MFE_MAE_used": False,
            "threshold_selected_on_w1_only": True,
            "selected_threshold_frozen_for_w2_w3": True,
            "raw_trade_rows_published": False,
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
            "next": "SEAL_SURVIVOR_AND_RUN_INDEPENDENT_OOS_STRESS" if survivor else "PRESERVE_DIAGNOSTIC_INCUMBENT_AND_ADVANCE_DISTINCT_AXIS",
        }
        receipt["receipt_sha256"] = stable_sha(receipt)
        atomic_json(args.out, receipt)
        heartbeat(args.heartbeat_out, fingerprint, "PASS", completed, None, expected)
        return receipt
    except Exception as exc:
        heartbeat(args.heartbeat_out, fingerprint, "FAIL", completed, None, expected, f"{type(exc).__name__}:{exc}")
        raise


def self_test() -> int:
    rows = [{
        "event_id": "a",
        "entry_price": 100,
        "qty": 1,
        "initial_risk_usdt": 1,
        "fee": 0.02,
        "slippage": 0.01,
        "funding_pnl_estimate_usdt": -0.001,
        "realized_R_including_funding_estimate": 0.5,
        "exit_reason": "tp",
        "window_id": "1m_w1",
    }]
    stressed, metadata = apply_h3_cost_floor(rows, 0.10)
    assert metadata["stress_lineage_complete"] is True
    assert stressed[0]["h3_stressed_R"] < 0.5
    passed, blockers, retention = absolute_gate(
        {"sample_count": 30, "net_R": 2, "profit_factor": 1.2, "expectancy_R": 0.1, "payoff_ratio": 1.1},
        40,
        20,
        {"minimum_retention_pct": 60},
    )
    assert passed and not blockers and retention == 75.0
    better, blockers = beats_control(
        {"net_R": 2, "profit_factor": 1.2, "max_drawdown_R": 3},
        {"net_R": 1, "profit_factor": 1.1, "max_drawdown_R": 4},
    )
    assert better and not blockers
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--selected-helper", type=Path)
    parser.add_argument("--cost-floor-helper", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--expanded-receipt", type=Path)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--heartbeat-out", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.engine, args.source_root, args.data_root, args.selected_helper,
        args.cost_floor_helper, args.policy, args.binding, args.expanded_receipt,
        args.checkpoint_dir, args.heartbeat_out, args.out,
    )
    if any(value is None for value in required):
        parser.error("all runtime arguments are required")
    receipt = run(args)
    print(json.dumps({
        "state": receipt["state"],
        "survivor": receipt["survivor"],
        "survivor_state": receipt["survivor_state"],
        "receipt_sha256": receipt["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
