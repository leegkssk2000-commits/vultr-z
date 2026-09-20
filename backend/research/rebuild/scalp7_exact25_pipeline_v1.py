"""Exact25 producer dispatch and bounded declared-fixture integration.

This is not a FULL runner or an economic authorization gateway. A caller's
SYNTHETIC_FIXTURE declaration is recorded, not magically authenticated. Small
fixture caps limit this integration path; no market data is loaded here. Source
completeness and a named fixture execution completion remain different states.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import json
import math
import inspect
import platform
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    MODEL,
    DetailExecutionAdapter,
    account_snapshots_from_ledger,
)
from backend.research.rebuild.scalp7_implementation_contract_v1 import (
    AUTHORITY,
    _decimal,
    _required_text,
    _timestamp,
    validate_rules,
)

SCHEMA = "zel.scalp7.exact25_fixture_pipeline.v1"
ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "backend.research.rebuild."
GROUPS = {
    "indicators": (
        "bb_revert",
        "mfi_rsi_div",
        "obv_trend",
        "rsi_swing_fail",
        "supertrend_pullback",
        "trend_ma_macd",
    ),
    "session": (
        "break_and_continue",
        "rbreaker_like",
        "session_bias",
        "squeeze_break",
        "trend_rider",
        "turtle_trend",
    ),
    "structure": (
        "ema_ribbon_scalp",
        "keltner_trend",
        "pivot_reversal",
        "range_fade",
        "scalp_snap",
        "vol_spike_fade",
    ),
    "reference": (
        "anchor_vwap_trend",
        "vwap_revert",
        "fvg_revert",
        "liquidity_sweep",
        "sr_levels",
    ),
    "capital": ("alpha_combo", "grid_rebalance"),
}
EXACT25 = tuple(sorted(x for group in GROUPS.values() for x in group))
MAX_SOURCE_ROWS = 256
MAX_DETAIL_ROWS = 2048
MAX_SYMBOLS = 3


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        if len(value) > MAX_SOURCE_ROWS:
            raise ValueError("CONFIG_FRAME_EXCEEDS_FIXTURE_CAP")
        return {
            "type": "DATAFRAME",
            "columns": list(value.columns),
            "records": _canonical(value.to_dict("records")),
        }
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("CONFIG_KEYS_MUST_BE_TEXT")
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if hasattr(value, "item"):
        return _canonical(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("UNSUPPORTED_OR_NONFINITE_CANONICAL_VALUE")


def digest(value: Any) -> str:
    return _hash_bytes(
        json.dumps(
            _canonical(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    )


def _producer(strategy_id: str) -> Any:
    matches = [g for g, ids in GROUPS.items() if strategy_id in ids]
    if len(matches) != 1:
        raise ValueError("NOT_ORIGINAL_EXACT25_ID")
    return importlib.import_module(PACKAGE + "scalp7_exact25_" + matches[0] + "_v1")


def registry() -> dict[str, dict[str, Any]]:
    rows = {}
    for group, ids in GROUPS.items():
        module = _producer(ids[0])
        definitions = module.catalog()
        if set(definitions) != set(ids):
            raise ValueError("EXACT25_GROUP_CATALOG_DRIFT:" + group)
        path = Path(module.__file__).resolve()
        for strategy, definition in definitions.items():
            rows[strategy] = {
                **copy.deepcopy(definition),
                "strategy_id": strategy,
                "producer_path": str(path.relative_to(ROOT)),
                "producer_sha256": _hash_bytes(path.read_bytes()),
                "caller": module.__name__ + ".evaluate",
            }
    if len(rows) != 25 or tuple(sorted(rows)) != EXACT25:
        raise ValueError("EXACT25_DENOMINATOR_INVALID")
    return rows


def _code_closure(strategy_id: str) -> dict[str, str]:
    """Hash local imported code recursively; never import to execute a replay."""
    starts = [
        Path(_producer(strategy_id).__file__).resolve(),
        Path(__file__).resolve(),
        ROOT / "backend/research/rebuild/scalp7_exact25_execution_v1.py",
        ROOT / "backend/research/rebuild/scalp7_implementation_contract_v1.py",
    ]
    queue, found = list(starts), {}
    while queue:
        path = queue.pop()
        name = str(path.relative_to(ROOT))
        if name in found:
            continue
        payload = path.read_bytes()
        found[name] = _hash_bytes(payload)
        for parent in path.parents:
            if parent == ROOT:
                break
            initializer = parent / "__init__.py"
            if (
                initializer.is_file()
                and str(initializer.relative_to(ROOT)) not in found
            ):
                queue.append(initializer)
        for node in ast.walk(ast.parse(payload)):
            candidates = []
            if isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                candidates = [
                    node.module,
                    *[node.module + "." + alias.name for alias in node.names],
                ]
            for candidate in candidates:
                if not candidate.startswith("backend."):
                    continue
                dependency = ROOT / (candidate.replace(".", "/") + ".py")
                if dependency.is_file():
                    queue.append(dependency)
    return dict(sorted(found.items()))


def environment_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": importlib.import_module("numpy").__version__,
    }


def _callable_digest(strategy_id: str) -> str:
    try:
        source = inspect.getsource(_producer(strategy_id).evaluate)
    except (OSError, TypeError) as exc:
        raise ValueError("PRODUCER_CALLABLE_SOURCE_UNAVAILABLE") from exc
    return _hash_bytes(source.encode())


def _completion_rule(completion: Mapping[str, Any]) -> dict[str, Any]:
    if (
        completion.get("origin") != "DECLARED_HYPOTHESIS"
        or completion.get("usage") != "FIXTURE_INTEGRATION_ONLY"
    ):
        raise ValueError("EXPLICIT_FIXTURE_HYPOTHESIS_REQUIRED")
    if completion.get("exact_source_reproduction") is not False:
        raise ValueError("COMPLETION_IS_NOT_SOURCE_REPRODUCTION")
    return {
        "rule_id": "FIXTURE_EXECUTION_COMPLETION",
        "origin": "DECLARED_HYPOTHESIS",
        "hypothesis_id": _required_text(completion, "hypothesis_id"),
        "rationale": _required_text(completion, "rationale"),
        "version": _required_text(completion, "version"),
        "unit": "explicit fixture execution policy",
        "expression": json.dumps(
            _canonical(completion), sort_keys=True, allow_nan=False
        ),
        "exact_source_reproduction": False,
    }


def freeze_binding(
    strategy_id: str,
    config: Mapping[str, Any],
    source_rules: Sequence[Mapping[str, Any]],
    completion: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind an explicit small-fixture caller; grants zero FULL executions."""
    entry = registry()[strategy_id]
    source_digest = validate_rules(source_rules)
    completion_rules = [] if completion is None else [_completion_rule(completion)]
    combined = [*copy.deepcopy(list(source_rules)), *completion_rules]
    binding = {
        "schema": SCHEMA,
        "environment": environment_versions(),
        "strategy_id": strategy_id,
        "producer_path": entry["producer_path"],
        "producer_sha256": entry["producer_sha256"],
        "producer_callable_sha256": _callable_digest(strategy_id),
        "code_closure": _code_closure(strategy_id),
        "config": _canonical(config),
        "config_digest": digest(config),
        "source_rules": copy.deepcopy(list(source_rules)),
        "source_rule_digest": source_digest,
        "completion": copy.deepcopy(completion),
        "execution_rules": combined,
        "execution_rule_digest": validate_rules(combined),
        "complete_source_strategy": entry["complete_strategy"],
        "economic_ready": False,
        "authority": dict(AUTHORITY),
        "full_execution_authorized": False,
    }
    binding["binding_sha256"] = digest(binding)
    return binding


def _verify(
    binding: Mapping[str, Any], config: Mapping[str, Any], expected: str
) -> Any:
    payload = {k: v for k, v in binding.items() if k != "binding_sha256"}
    if digest(payload) != expected or binding.get("binding_sha256") != expected:
        raise ValueError("PINNED_BINDING_DIGEST_MISMATCH")
    strategy = _required_text(binding, "strategy_id")
    if binding.get("environment") != environment_versions():
        raise ValueError("RUNTIME_ENVIRONMENT_CHANGED")
    if (
        digest(config) != binding["config_digest"]
        or _canonical(config) != binding["config"]
    ):
        raise ValueError("CONFIG_BINDING_MISMATCH")
    if _code_closure(strategy) != binding["code_closure"]:
        raise ValueError("CODE_CLOSURE_CHANGED")
    if _callable_digest(strategy) != binding["producer_callable_sha256"]:
        raise ValueError("PRODUCER_CALLABLE_CHANGED")
    if validate_rules(binding["source_rules"]) != binding["source_rule_digest"]:
        raise ValueError("SOURCE_RULE_DIGEST_MISMATCH")
    if validate_rules(binding["execution_rules"]) != binding["execution_rule_digest"]:
        raise ValueError("EXECUTION_RULE_DIGEST_MISMATCH")
    return _producer(strategy)


def _source_frames(frames: Mapping[str, pd.DataFrame], tf: int) -> None:
    if not frames or len(frames) > MAX_SYMBOLS or tf not in (15, 30):
        raise ValueError("SMALL_SCALP7_FIXTURE_REQUIRED")
    for symbol, frame in frames.items():
        if not isinstance(symbol, str) or not symbol or len(frame) > MAX_SOURCE_ROWS:
            raise ValueError("SOURCE_FIXTURE_CAP_OR_SYMBOL_INVALID")
        previous = -1
        for row in frame.to_dict("records"):
            opened = _timestamp(row.get("open_ts_ms"), "open_ts_ms")
            closed = _timestamp(row.get("close_ts_ms"), "close_ts_ms")
            available = _timestamp(row.get("available_ts_ms"), "available_ts_ms")
            if (
                opened <= previous
                or opened % (tf * 60000)
                or closed != opened + tf * 60000
                or available < closed
            ):
                raise ValueError("EXCLUSIVE_CANONICAL_SOURCE_CLOCK_REQUIRED")
            previous = opened
            if "symbol" in row and row["symbol"] != symbol:
                raise ValueError("SOURCE_SYMBOL_MISMATCH")


def evaluate_bound(
    binding: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
    *,
    expected_binding_sha256: str,
) -> dict[str, Any]:
    module = _verify(binding, config, expected_binding_sha256)
    tf = _timestamp(config.get("timeframe_min"), "timeframe_min")
    if binding["strategy_id"] in GROUPS["capital"] and not frames:
        if tf not in (15, 30):
            raise ValueError("SCALP7_TIMEFRAME_REQUIRED")
    else:
        _source_frames(frames, tf)
    before = digest({"frames": frames, "config": config})
    result = module.evaluate(
        binding["strategy_id"], copy.deepcopy(dict(frames)), copy.deepcopy(dict(config))
    )
    if result["strategy_id"] != binding["strategy_id"]:
        raise ValueError("PRODUCER_STRATEGY_MISMATCH")
    actual_digest = validate_rules(result["rules"])
    if (
        actual_digest != result["rule_digest"]
        or actual_digest != binding["source_rule_digest"]
    ):
        raise ValueError("ACTUAL_CALLER_RULES_DIFFER_FROM_FROZEN_BINDING")
    if result.get("complete_strategy") is not binding["complete_source_strategy"]:
        raise ValueError("SOURCE_COMPLETENESS_CHANGED")
    _verify(binding, config, expected_binding_sha256)
    return {
        "binding_sha256": expected_binding_sha256,
        "input_sha256": before,
        "producer": result,
        "complete_source_strategy": result["complete_strategy"],
        "economic_ready": False,
        "full_executions": 0,
        "authority": dict(AUTHORITY),
    }


def _order(
    intent: Mapping[str, Any], binding: Mapping[str, Any], ordinal: int
) -> dict[str, Any]:
    completion = binding["completion"]
    if completion is None:
        raise ValueError("NO_DECLARED_EXECUTION_COMPLETION")
    if completion.get("fill_model") != MODEL:
        raise ValueError("FIXTURE_MODEL_MUST_BE_EXPLICIT")
    if completion.get("activation_policy") != "FEATURE_AVAILABLE_EXACT_MINUTE":
        raise ValueError("ACTIVATION_POLICY_REQUIRED")
    available = _timestamp(
        intent.get("feature_available_ts_ms"), "feature_available_ts_ms"
    )
    if available % 60000:
        raise ValueError("NONCANONICAL_ACTIVATION_NOT_BACKDATED_OR_ROUNDED")
    origin = intent.get(
        "setup_ts_ms", intent.get("origin_ts_ms", intent.get("bar_open_ts_ms"))
    )
    if origin is None or _timestamp(origin, "setup_ts_ms") > available:
        raise ValueError("INTENT_SETUP_CLOCK_REQUIRED")
    if (
        intent.get("rule_digest", binding["source_rule_digest"])
        != binding["source_rule_digest"]
    ):
        raise ValueError("INTENT_RULE_DIGEST_MISMATCH")
    side = intent.get("side")
    if isinstance(side, bool) or side not in (-1, 1):
        raise ValueError("INTENT_SIDE_REQUIRED")
    qty = _decimal(completion.get("qty_base"), "qty_base", positive=True)
    if (
        intent.get("qty_base") is not None
        and _decimal(intent["qty_base"], "source_qty", positive=True) != qty
    ):
        raise ValueError("SOURCE_QUANTITY_OVERRIDE_FORBIDDEN")
    kind = intent.get("order_kind")
    if kind is None:
        kind = completion.get("missing_order_kind")
    if kind not in {"NEXT_OPEN", "LIMIT", "STOP_MARKET"}:
        raise ValueError("ORDER_KIND_UNRESOLVED")
    stop = intent.get("protective_stop")
    if stop is None:
        policy = completion.get("missing_stop", {})
        if policy.get("policy") != "EXPLICIT_FIXTURE_PRICE":
            raise ValueError("INITIAL_STOP_UNRESOLVED")
        stop = policy.get("price")
    _decimal(stop, "protective_stop", positive=True)
    expires = intent.get("expires_ts_ms")
    if expires is None:
        policy = completion.get("missing_expiry", {})
        if policy.get("policy") != "AFTER_ACTIVATION_MINUTES":
            raise ValueError("ORDER_EXPIRY_UNRESOLVED")
        minutes = _timestamp(policy.get("minutes"), "expiry_minutes")
        if minutes < 1:
            raise ValueError("POSITIVE_ORDER_EXPIRY_REQUIRED")
        expires = available + minutes * 60000
    if _timestamp(expires, "expires_ts_ms") <= available:
        raise ValueError("ORDER_EXPIRED_BEFORE_ACTIVATION")
    lifecycle = completion.get("lifecycle", {})
    if lifecycle.get("policy") not in {
        "STOP_ONLY_REMAINDER_UNRESOLVED",
        "EXIT_AFTER_COMPLETE_DECISION_BARS",
    }:
        raise ValueError("LIFECYCLE_COMPLETION_UNRESOLVED")
    if (
        lifecycle["policy"] == "EXIT_AFTER_COMPLETE_DECISION_BARS"
        and _timestamp(lifecycle.get("bars"), "lifecycle_bars") < 1
    ):
        raise ValueError("POSITIVE_LIFECYCLE_BARS_REQUIRED")
    fee = _decimal(completion.get("fee_rate"), "fee_rate")
    if fee < 0:
        raise ValueError("NEGATIVE_FEE_RATE")
    identity = _required_text(completion, "identity")
    return {
        "identity": identity,
        "symbol": _required_text(intent, "symbol"),
        "side": side,
        "position_episode_id": identity + ":" + str(ordinal),
        "rule_digest": binding["execution_rule_digest"],
        "decision_tf_min": binding["config"]["timeframe_min"],
        "qty_base": str(qty),
        "order_kind": kind,
        "trigger_price": intent.get("trigger_price"),
        "protective_stop": stop,
        "feature_available_ts_ms": available,
        "order_submit_ts_ms": available,
        "order_active_ts_ms": available,
        "expires_ts_ms": expires,
        "timing_basis": "HISTORICAL_MODEL",
        "source_intent": copy.deepcopy(dict(intent)),
        "completion_hypothesis_id": completion["hypothesis_id"],
        "source_complete": binding["complete_source_strategy"],
        "binding_sha256": binding["binding_sha256"],
    }


def chronological_ledger(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Stable same-ms order retains supplied causal sequence, never lexical ID."""
    return sorted(
        [dict(row) for row in rows], key=lambda row: (row["ts_ms"], row["symbol"])
    )


def run_synthetic_pipeline(
    binding: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
    detail_frames: Mapping[str, pd.DataFrame],
    price_snapshots: Sequence[Mapping[str, Any]],
    *,
    expected_binding_sha256: str,
    input_manifest: Mapping[str, Any],
    initial_cash_usdt: Any,
    start_ts_ms: int,
    price_basis: str,
) -> dict[str, Any]:
    """Real caller chain on caller-declared bounded fixtures; no FULL authority."""
    if input_manifest.get("data_kind") != "SYNTHETIC_FIXTURE":
        raise ValueError("REAL_HISTORY_EXECUTION_NOT_AUTHORIZED")
    _required_text(input_manifest, "case_id")
    _required_text(input_manifest, "construction_reason")
    if len(detail_frames) > MAX_SYMBOLS or set(detail_frames) - set(frames):
        raise ValueError("DETAIL_SYMBOL_BINDING_MISMATCH")
    records = {}
    for symbol, frame in detail_frames.items():
        if len(frame) > MAX_DETAIL_ROWS:
            raise ValueError("DETAIL_FIXTURE_CAP_EXCEEDED")
        rows = frame.to_dict("records")
        previous = -1
        for row in rows:
            if row.get("symbol", symbol) != symbol:
                raise ValueError("DETAIL_SYMBOL_BINDING_MISMATCH")
            row["symbol"] = symbol
            opened = _timestamp(row.get("open_ts_ms"), "open_ts_ms")
            if (
                opened <= previous
                or opened % 60000
                or row.get("close_ts_ms") != opened + 60000
            ):
                raise ValueError("ONE_MINUTE_CHRONOLOGICAL_DETAIL_REQUIRED")
            previous = opened
        records[symbol] = rows
    result = evaluate_bound(
        binding, frames, config, expected_binding_sha256=expected_binding_sha256
    )
    producer = result["producer"]
    statuses, executions, ledger = [], [], []
    occupancy: dict[str, int] = {}
    intents = sorted(
        enumerate(producer["intents"]),
        key=lambda item: (
            item[1]["feature_available_ts_ms"],
            item[1]["symbol"],
            item[0],
        ),
    )
    for ordinal, intent in intents:
        disposition = {
            "intent_ordinal": ordinal,
            "symbol": intent["symbol"],
            "feature_available_ts_ms": intent["feature_available_ts_ms"],
        }
        try:
            order = _order(intent, binding, ordinal)
        except ValueError as exc:
            statuses.append(
                {
                    **disposition,
                    "status": "BLOCKED_INCOMPLETE_EXECUTION",
                    "reason": str(exc),
                }
            )
            continue
        symbol, active = order["symbol"], order["order_active_ts_ms"]
        if symbol not in records:
            statuses.append({**disposition, "status": "BLOCKED_MISSING_DETAIL_SOURCE"})
            continue
        if active < occupancy.get(symbol, -1):
            statuses.append(
                {**disposition, "status": "MISSED_EXISTING_POSITION_OR_ORDER_OWNERSHIP"}
            )
            continue
        completion = binding["completion"]
        policy = completion["lifecycle"]

        def exit_update(
            position: dict[str, Any], bar: Any, history: Any
        ) -> dict[str, Any]:
            del bar, history
            return (
                {
                    "exit_next_open": policy["policy"]
                    == "EXIT_AFTER_COMPLETE_DECISION_BARS"
                    and position["hold_bars"] >= policy["bars"],
                    "reason": "DECLARED_FIXTURE_LIFECYCLE",
                }
                if policy["policy"] == "EXIT_AFTER_COMPLETE_DECISION_BARS"
                else {}
            )

        adapter = DetailExecutionAdapter(
            order,
            fill_model=MODEL,
            fee_rate=completion["fee_rate"],
            exit_update=exit_update,
        )
        source_rows = [
            {**row, "symbol": symbol} for row in frames[symbol].to_dict("records")
        ]
        for detail in records[symbol]:
            if detail["close_ts_ms"] <= active:
                continue
            adapter.process_detail_bar(detail)
            if adapter.state in {"UNRESOLVED", "CLOSED", "CANCELLED", "EXPIRED"}:
                break
            for decision in source_rows:
                if (
                    decision["available_ts_ms"] == detail["available_ts_ms"]
                    and decision["close_ts_ms"] == detail["close_ts_ms"]
                    and decision["open_ts_ms"] >= active
                ):
                    history = pd.DataFrame(
                        [
                            row
                            for row in source_rows
                            if row["available_ts_ms"] <= decision["available_ts_ms"]
                            and row["close_ts_ms"] <= decision["close_ts_ms"]
                        ]
                    )
                    adapter.process_decision_bar(decision, history)
            if adapter.state in {"UNRESOLVED", "CLOSED", "CANCELLED", "EXPIRED"}:
                break
        executed = adapter.finish()
        executions.append({"intent_ordinal": ordinal, **executed})
        ledger.extend(executed["ledger"])
        occupancy[symbol] = (
            2**63 - 1 if executed["state"] == "UNRESOLVED" else adapter.last_available
        )
        statuses.append(
            {
                **disposition,
                "status": executed["state"],
                "order_state": executed["order_state"],
                "original_source_status": intent.get(
                    "status", intent.get("execution_status")
                ),
                "source_lifecycle_gap": intent.get("lifecycle_gap"),
                "completion_hypothesis_id": completion["hypothesis_id"],
            }
        )
    ledger = chronological_ledger(ledger)
    account = account_snapshots_from_ledger(
        ledger,
        price_snapshots,
        initial_cash_usdt=initial_cash_usdt,
        start_ts_ms=start_ts_ms,
        price_basis=price_basis,
    )
    _verify(binding, config, expected_binding_sha256)
    return {
        **result,
        "schema": SCHEMA,
        "input_manifest": copy.deepcopy(dict(input_manifest)),
        "input_provenance": "CALLER_DECLARATION_NOT_INDEPENDENT_AUTHENTICATION",
        "integration_input_sha256": digest(
            {
                "frames": frames,
                "config": config,
                "detail_frames": {s: r for s, r in records.items()},
                "price_snapshots": price_snapshots,
                "initial_cash_usdt": initial_cash_usdt,
                "start_ts_ms": start_ts_ms,
                "price_basis": price_basis,
                "manifest": input_manifest,
            }
        ),
        "intent_dispositions": statuses,
        "executions": executions,
        "fill_ledger": ledger,
        "account": account,
        "source_limitations_preserved": copy.deepcopy(producer["limitations"]),
        "configured_research_execution": bool(executions),
        "candidate_ready_for_full": False,
        "economic_benchmark_completed": False,
        "new_full_executions": 0,
        "economic_improvement_claim": False,
        "limits": {
            "source_rows_per_symbol": MAX_SOURCE_ROWS,
            "detail_rows_per_symbol": MAX_DETAIL_ROWS,
            "symbols": MAX_SYMBOLS,
        },
        "fixture_occupancy_policy": "ONE_EPISODE_PER_SYMBOL_UNRESOLVED_RETAINS_OWNERSHIP",
        "occupancy_release_clock": "OUTCOME_WITNESS_AVAILABLE_NOT_INFERRED_EARLIER_OPEN",
        "authority": dict(AUTHORITY),
    }
