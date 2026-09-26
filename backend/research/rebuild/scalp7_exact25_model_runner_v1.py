"""Frozen complete-model runner; admission precedes every genuine data load.

Historical execution is an explicitly declared OHLC model, not observed fills.
Reference costs exclude unknown funding. This module cannot allocate a budget,
create a scope, promote a model, submit orders, or alter a running service.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import heapq
import importlib
import inspect
import itertools
import json
import math
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from backend.research.rebuild.economic7_campaign_registry_v1 import (
    CampaignLedger,
    CandidateIdentity,
)
from backend.research.rebuild.scalp7_exact25_execution_v1 import (
    MODEL,
    DetailExecutionAdapter,
    account_snapshots_from_ledger,
)
from backend.research.rebuild.scalp7_exact25_pipeline_v1 import (
    digest,
    environment_versions,
)
from backend.research.rebuild.scalp7_implementation_contract_v1 import AUTHORITY

SCHEMA = "zel.scalp7.exact25_model_runner.v1"
ROOT = Path(__file__).resolve().parents[3]
MINUTE = 60_000
TERMINAL = {"CLOSED", "CANCELLED", "EXPIRED", "UNRESOLVED"}


def _positive(value: Any, name: str, zero: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER:" + name)
    number = float(value)
    if not math.isfinite(number) or number < 0 or (not zero and number == 0):
        raise ValueError("INVALID_NUMBER:" + name)
    return number


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def code_closure(module_name: str) -> dict[str, str]:
    """Include actual local imports, package initializers, runner and engine."""
    if not module_name.startswith("backend.research.rebuild."):
        raise ValueError("RESEARCH_MODEL_MODULE_REQUIRED")
    module = importlib.import_module(module_name)
    pending = [Path(str(module.__file__)).resolve(), Path(__file__).resolve()]
    found: dict[str, str] = {}
    while pending:
        path = pending.pop()
        relative = str(path.relative_to(ROOT))
        if relative in found:
            continue
        found[relative] = _sha(path)
        for parent in path.parents:
            if parent == ROOT:
                break
            init = parent / "__init__.py"
            if init.is_file():
                pending.append(init)
        for node in ast.walk(ast.parse(path.read_bytes())):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module, *[node.module + "." + a.name for a in node.names]]
            for name in names:
                target = ROOT / (name.replace(".", "/") + ".py")
                if name.startswith("backend.") and target.is_file():
                    pending.append(target)
    return dict(sorted(found.items()))


def _windows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("EXPLICIT_WINDOWS_REQUIRED")
    previous = -1
    names: set[str] = set()
    for row in rows:
        if row["name"] in names or row["kind"] not in {
            "CONTEXT",
            "TRAIN",
            "VALIDATION",
            "ROLLING",
            "FRESH",
        }:
            raise ValueError("WINDOW_IDENTITY_INVALID")
        names.add(row["name"])
        start, end = row["start_ts_ms"], row["end_ts_ms"]
        if (
            type(start) is not int
            or type(end) is not int
            or start < previous
            or end <= start
        ):
            raise ValueError("WINDOW_OVERLAP_OR_CLOCK_INVALID")
        if start % MINUTE or end % MINUTE:
            raise ValueError("WINDOW_MINUTE_BOUNDARY_REQUIRED")
        previous = end


def data_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Content and semantic roles define an experiment, not checkout locators."""
    locator_keys = {
        "path",
        "directory",
        "canonical_root",
        "source_inventory_path",
        "time_authority_directory",
    }

    def normalize(value: Any) -> Any:
        if isinstance(value, Mapping):
            out = {}
            for key, item in value.items():
                if key in locator_keys:
                    continue
                if key == "artifacts":
                    out[key] = sorted(
                        [
                            {
                                "sha256": row["sha256"],
                                "role": row.get("role", "INPUT_ARTIFACT"),
                            }
                            for row in item
                        ],
                        key=lambda row: (row["role"], row["sha256"]),
                    )
                else:
                    out[key] = normalize(item)
            return out
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, str) and value.startswith("/"):
            return "ABSOLUTE_LOCATOR_EXCLUDED_FROM_EXPERIMENT_IDENTITY"
        return value

    return normalize(manifest)


def callback_history_policy(module_name: str, model_id: str) -> dict[str, Any]:
    """Frozen bounded dependencies verified against the bound callback source."""
    prefix = "backend.research.rebuild."
    bounded = {
        (
            prefix + "scalp7_exact25_indicator_models_v1",
            "ST30_STRUCTURAL_CONTROL_V1",
        ): 1,
        (
            prefix + "scalp7_exact25_indicator_models_v1",
            "ST30_COMPLETED_BAND_TRAIL_V1",
        ): 1,
        (
            prefix + "scalp7_exact25_reference_models_v1",
            "sr_levels_30m_prior_utc_day_box_breakout_control_v1",
        ): 1,
        (
            prefix + "scalp7_exact25_reference_models_v1",
            "sr_levels_30m_prior_utc_day_box_intraday_v1",
        ): 1,
        (
            prefix + "scalp7_exact25_reference_models_v1",
            "liquidity_sweep_15m_daily_soup_intraday_v1",
        ): 1,
        (
            prefix + "scalp7_exact25_structure_models_v1",
            "ANTI30_CAUSAL_FLAG_PIVOT_V1",
        ): 3,
    }
    limit = bounded.get((module_name, model_id))
    return {
        "mode": "FULL_CAUSAL_PREFIX" if limit is None else "LAST_N_CANONICAL_DECISIONS",
        "bars": limit,
        "proof": "SOURCE_HASH_BOUND_BAR_ONLY_ST_SR_SOUP_OR_LAST3_POSTENTRY_ANTI",
        "full_prefix_clock_validation": True,
    }


def _callback_history(
    rows: list[dict[str, Any]], index: int, policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    limit = policy["bars"]
    start = 0 if limit is None else max(0, index + 1 - limit)
    return rows[start : index + 1]


def freeze_model(
    *,
    model_module: str,
    model_id: str,
    strategy_id: str,
    baseline_id: str,
    changed_axis: str,
    config: Mapping[str, Any],
    data_manifest: Mapping[str, Any],
    cost: Mapping[str, Any],
    windows: list[dict[str, Any]],
    initial_cash_usdt: Any,
    compiler: str = "compile_model",
    execution_mode: str = "DETAIL_CONDITIONAL",
) -> dict[str, Any]:
    """Freeze code and contracts without loading data or allocating execution."""
    _windows(windows)
    if execution_mode not in {"DETAIL_CONDITIONAL", "SESSION_TARGET"}:
        raise ValueError("EXECUTION_MODE_INVALID")
    if cost.get("kind") != "REFERENCE_ALL_IN_RATE_EXCLUDING_FUNDING":
        raise ValueError("EXPLICIT_REFERENCE_COST_REQUIRED")
    rates = cost.get("per_side_rates")
    if isinstance(rates, Mapping) and rates:
        for symbol, rate in rates.items():
            _positive(rate, "per_side_rate:" + symbol, zero=True)
    elif data_manifest.get("data_kind") == "SYNTHETIC_FIXTURE":
        _positive(cost.get("per_side_rate"), "per_side_rate", zero=True)
    else:
        raise ValueError("PER_SYMBOL_REFERENCE_COST_REQUIRED")
    if data_manifest.get("data_kind") == "GENUINE_RAW_HISTORY":
        symbols = data_manifest.get("symbols")
        if (
            not isinstance(symbols, list)
            or not symbols
            or len(symbols) != len(set(symbols))
            or set(symbols) != set(rates or {})
        ):
            raise ValueError("GENUINE_SYMBOL_COST_UNIVERSE_MISMATCH")
    if cost.get("funding_status") != "UNKNOWN_NOT_ZERO":
        raise ValueError("FUNDING_UNCERTAINTY_MUST_BE_PRESERVED")
    if data_manifest.get("data_kind") not in {
        "GENUINE_RAW_HISTORY",
        "SYNTHETIC_FIXTURE",
    }:
        raise ValueError("DATA_KIND_REQUIRED")
    module = importlib.import_module(model_module)
    callable_names = (
        [compiler, "create_order", "exit_update"]
        if execution_mode == "DETAIL_CONDITIONAL"
        else [
            compiler,
            (
                "NoisePortfolioTargetModel"
                if "symbol_configs" in config
                else "SessionTargetModel"
            ),
        ]
    )
    callables = {
        name: hashlib.sha256(
            inspect.getsource(getattr(module, name)).encode()
        ).hexdigest()
        for name in callable_names
    }
    payload = {
        "schema": SCHEMA,
        "model_module": model_module,
        "model_id": model_id,
        "strategy_id": strategy_id,
        "baseline_id": baseline_id,
        "changed_axis": changed_axis,
        "config": copy.deepcopy(dict(config)),
        "data_manifest": copy.deepcopy(dict(data_manifest)),
        "cost": copy.deepcopy(dict(cost)),
        "windows": copy.deepcopy(windows),
        "initial_cash_usdt": _positive(initial_cash_usdt, "initial_cash_usdt"),
        "compiler": compiler,
        "execution_mode": execution_mode,
        "code_closure": code_closure(model_module),
        "callables": callables,
        "environment": environment_versions(),
        "fill_model": MODEL,
        "callback_history_policy": callback_history_policy(model_module, model_id),
        "capital_policy": (
            "LINEAR_SLEEVE_FIXED_SESSION_QTY"
            if execution_mode == "SESSION_TARGET"
            else "LINEAR_RESEARCH_REALIZED_CASH_MINUS_RESERVED_NOTIONAL"
        ),
        "gap_policy": "UNRESOLVED_OWNERSHIP_RETAINED_NO_SYNTHETIC_CLOSE",
        "price_basis": "LAST_PRICE",
        "authority": dict(AUTHORITY),
    }
    loader = data_manifest.get("loader")
    if loader is not None:
        payload["loader_code_closure"] = code_closure(loader["module"])
        loader_function = getattr(
            importlib.import_module(loader["module"]), loader["function"]
        )
        payload["loader_callable_sha256"] = hashlib.sha256(
            inspect.getsource(loader_function).encode()
        ).hexdigest()
    rule = digest(
        {
            k: v
            for k, v in payload.items()
            if k not in {"data_manifest", "cost", "windows"}
        }
    )
    identity = CandidateIdentity(
        candidate_id=model_id,
        strategy_id=strategy_id,
        baseline_id=baseline_id,
        changed_axis=changed_axis,
        rule_sha256=rule,
        data_sha256=digest(data_identity(data_manifest)),
        cost_sha256=digest(cost),
        window_sha256=digest(windows),
    )
    payload["candidate_identity"] = asdict(identity)
    payload["identity_key"] = identity.key
    payload["binding_sha256"] = digest(payload)
    return payload


def verify_binding(binding: Mapping[str, Any], expected: str) -> Any:
    payload = {k: v for k, v in binding.items() if k != "binding_sha256"}
    if binding.get("binding_sha256") != expected or digest(payload) != expected:
        raise ValueError("PINNED_BINDING_MISMATCH")
    if binding["code_closure"] != code_closure(binding["model_module"]):
        raise ValueError("CODE_CLOSURE_CHANGED")
    if binding["environment"] != environment_versions():
        raise ValueError("RUNTIME_ENVIRONMENT_CHANGED")
    identity = CandidateIdentity(**binding["candidate_identity"])
    if identity.key != binding["identity_key"]:
        raise ValueError("IDENTITY_KEY_MISMATCH")
    _windows(binding["windows"])
    rebuilt = freeze_model(
        **{
            key: binding[key]
            for key in (
                "model_module",
                "model_id",
                "strategy_id",
                "baseline_id",
                "changed_axis",
                "config",
                "data_manifest",
                "cost",
                "windows",
                "initial_cash_usdt",
                "compiler",
                "execution_mode",
            )
        }
    )
    if rebuilt["candidate_identity"] != binding["candidate_identity"]:
        raise ValueError("IDENTITY_PAYLOAD_BINDING_MISMATCH")
    if rebuilt.get("loader_callable_sha256") != binding.get("loader_callable_sha256"):
        raise ValueError("DATA_LOADER_CALLABLE_CHANGED")
    if rebuilt["callables"] != binding["callables"]:
        raise ValueError("CALLABLE_SOURCE_CHANGED")
    return importlib.import_module(binding["model_module"])


def admission(
    binding: Mapping[str, Any], *, registry_path: str | Path, scope: str, owner: str
) -> dict[str, Any]:
    """Read-only check: no scope, file, candidate, or allowance is created."""
    path = Path(registry_path)
    if not path.is_file():
        raise PermissionError("NEW_FULL_ALLOCATION_ABSENT")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        allocated = db.execute(
            "SELECT * FROM scopes WHERE scope=?", (scope,)
        ).fetchone()
        if allocated is None or allocated["owner"] != owner:
            raise PermissionError("NEW_FULL_ALLOCATION_ABSENT")
        contract = json.loads(allocated["contract_json"])
        if (
            not contract.get("approval_ref")
            or contract.get("new_full_authorized") is not True
        ):
            raise PermissionError("EXPLICIT_NEW_FULL_APPROVAL_RECEIPT_REQUIRED")
        claim = db.execute(
            "SELECT * FROM claims WHERE identity_key=?", (binding["identity_key"],)
        ).fetchone()
        if claim is None or claim["scope"] != scope:
            raise PermissionError("EXACT_IDENTITY_RESERVATION_REQUIRED")
        if json.loads(claim["identity_json"]) != binding["candidate_identity"]:
            raise PermissionError("RESERVATION_IDENTITY_MISMATCH")
        if claim["state"] != "RESERVED":
            raise PermissionError("EXISTING_EXECUTION_MUST_BE_RECOVERED_NOT_REPEATED")
        started = db.execute(
            "SELECT count(*) FROM events WHERE scope=? AND event='STARTED'", (scope,)
        ).fetchone()[0]
        if started >= allocated["max_executions"]:
            raise PermissionError("NEW_FULL_BUDGET_EXHAUSTED")
        return {
            "scope": scope,
            "owner": owner,
            "approval_ref": contract["approval_ref"],
        }


def _verify_input_files(manifest: Mapping[str, Any]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("IMMUTABLE_INPUT_ARTIFACTS_REQUIRED")
    for artifact in artifacts:
        if _sha(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError("INPUT_ARTIFACT_CHANGED:" + artifact["path"])


def _eligible(stamp: int, windows: list[dict[str, Any]]) -> bool:
    return any(
        w["kind"] not in {"CONTEXT", "TRAIN"}
        and w["start_ts_ms"] <= stamp < w["end_ts_ms"]
        for w in windows
    )


class _CashBook:
    def __init__(self, initial: float) -> None:
        self.cash = initial
        self.positions: dict[str, tuple[float, float, int]] = {}

    def consume(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self.cash -= float(row["fee_usdt"])
            ep, qty, price = (
                row["position_episode_id"],
                float(row["qty_base"]),
                float(row["fill_price"]),
            )
            if row["effect"] == "OPEN":
                old, entry, side = self.positions.get(ep, (0.0, 0.0, row["side"]))
                self.positions[ep] = (
                    old + qty,
                    (old * entry + qty * price) / (old + qty),
                    side,
                )
            else:
                old, entry, side = self.positions[ep]
                self.cash += side * qty * (price - entry)
                if old > qty:
                    self.positions[ep] = (old - qty, entry, side)
                else:
                    del self.positions[ep]


def _detail_groups(frames: Mapping[str, pd.DataFrame]) -> Any:
    def rows(symbol: str, frame: pd.DataFrame) -> Any:
        previous = -1
        for values in frame.itertuples(index=False, name=None):
            row = dict(zip(frame.columns, values))
            opened = row["open_ts_ms"]
            if (
                type(opened) is not int
                or opened <= previous
                or opened % MINUTE
                or row["close_ts_ms"] != opened + MINUTE
                or row["available_ts_ms"] != opened + MINUTE
                or row.get("symbol", symbol) != symbol
            ):
                raise ValueError("CANONICAL_MINUTE_CLOCK_REQUIRED")
            previous = opened
            yield opened, symbol, {**row, "symbol": symbol}

    merged = heapq.merge(*(rows(s, f) for s, f in sorted(frames.items())))
    for stamp, group in itertools.groupby(merged, key=lambda item: item[0]):
        yield stamp, list(group)


def _fee(binding: Mapping[str, Any], symbol: str) -> float:
    rates = binding["cost"].get("per_side_rates")
    if isinstance(rates, Mapping):
        if symbol not in rates:
            raise ValueError("SYMBOL_COST_MISSING:" + symbol)
        return _positive(rates[symbol], "symbol_cost", zero=True)
    if binding["data_manifest"]["data_kind"] != "SYNTHETIC_FIXTURE":
        raise ValueError("PER_SYMBOL_REFERENCE_COST_REQUIRED")
    return _positive(binding["cost"]["per_side_rate"], "fixture_cost", zero=True)


def _conditional(
    binding: Mapping[str, Any],
    module: Any,
    compiled: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    if compiled.get("complete") is not True:
        raise ValueError("INCOMPLETE_MODEL_CANNOT_ENTER_RUNNER")
    plans = sorted(
        compiled["plans"],
        key=lambda p: (
            p.get("order_active_ts_ms", p["feature_available_ts_ms"]),
            p["symbol"],
        ),
    )
    decisions = compiled.get("decisions", inputs["frames"])
    decision_rows = {
        s: [{**r, "symbol": s} for r in f.to_dict("records")]
        for s, f in decisions.items()
    }
    decision_index = {
        s: {r["available_ts_ms"]: (i, r) for i, r in enumerate(rows)}
        for s, rows in decision_rows.items()
    }
    prefix_known = {
        s: list(itertools.accumulate((r["available_ts_ms"] for r in rows), max))
        for s, rows in decision_rows.items()
    }
    prefix_closed = {
        s: list(itertools.accumulate((r["close_ts_ms"] for r in rows), max))
        for s, rows in decision_rows.items()
    }
    active: dict[str, DetailExecutionAdapter] = {}
    reserved: dict[str, float] = {}
    executions, ledger, statuses = [], [], []
    seen: set[str] = set()
    book = _CashBook(binding["initial_cash_usdt"])
    pointer = 0
    for opened, batch in _detail_groups(inputs["detail_frames"]):
        # All same-open admissions use cash known before this minute's witnesses.
        while (
            pointer < len(plans)
            and plans[pointer].get(
                "order_active_ts_ms", plans[pointer]["feature_available_ts_ms"]
            )
            <= opened
        ):
            plan = plans[pointer]
            pointer += 1
            symbol = plan["symbol"]
            fee = _fee(binding, symbol)
            stamp = int(plan["feature_available_ts_ms"])
            if not _eligible(stamp, binding["windows"]):
                continue
            if symbol in active:
                statuses.append(
                    {"symbol": symbol, "ts_ms": stamp, "status": "EXISTING_OWNERSHIP"}
                )
                continue
            free = book.cash - sum(reserved.values())
            if free <= 0:
                statuses.append(
                    {
                        "symbol": symbol,
                        "ts_ms": stamp,
                        "status": "FINITE_CAPITAL_UNAVAILABLE",
                    }
                )
                continue
            order = module.create_order(
                plan,
                free,
                binding["identity_key"],
                compiled.get("rule_digest", plan.get("rule_digest")),
            )
            order.setdefault(
                "position_episode_id",
                binding["identity_key"] + ":" + symbol + ":" + str(pointer),
            )
            episode = order["position_episode_id"]
            if episode in seen:
                raise ValueError("DUPLICATE_POSITION_EPISODE")
            seen.add(episode)
            reference = _positive(
                plan["reference_entry_price"], "reference_entry_price"
            )
            quantity = _positive(order["qty_base"], "qty_base")
            cap = float(
                order.get(
                    "reserved_notional_usdt",
                    order.get("signal", {}).get(
                        "reserved_notional_usdt", quantity * reference
                    ),
                )
            )
            reserve = cap * (1 + 2 * fee)
            if reserve > free + 1e-9:
                statuses.append(
                    {
                        "symbol": symbol,
                        "ts_ms": stamp,
                        "status": "NOTIONAL_RESERVATION_EXCEEDS_CASH",
                    }
                )
                continue
            original_entry = getattr(module, "entry_update", None)

            def guarded_entry(
                signal: Any,
                price: float,
                *,
                q: float = quantity,
                limit: float = cap,
                callback: Any = original_entry,
            ) -> dict[str, Any]:
                if q * price > limit + 1e-9:
                    return {
                        "reject": True,
                        "reason": "ACTUAL_FILL_EXCEEDS_RESERVED_NOTIONAL",
                    }
                return {} if callback is None else callback(signal, price)

            active[symbol] = DetailExecutionAdapter(
                order,
                fill_model=MODEL,
                fee_rate=fee,
                entry_update=guarded_entry,
                exit_update=module.exit_update,
            )
            reserved[symbol] = reserve
        newly_known = []
        for _, symbol, detail in batch:
            adapter = active.get(symbol)
            if adapter is None or adapter.state == "UNRESOLVED":
                continue
            before = len(adapter.ledger)
            contiguous_end = (
                adapter.details[-1]["close_ts_ms"]
                if adapter.details
                else adapter.order["order_active_ts_ms"]
            )
            try:
                if (
                    not adapter.details
                    and detail["open_ts_ms"] > adapter.order["order_active_ts_ms"]
                ):
                    adapter._unresolved("MISSING_ACTIVATION_MINUTE")
                else:
                    adapter.process_detail_bar(detail)
            except ValueError as exc:
                if (
                    str(exc) in {"ENTRY_CALLBACK_REJECTED", "ENTRY_INVALIDATES_STOP"}
                    and not adapter.ledger
                ):
                    adapter.cancel(detail["available_ts_ms"], str(exc))
                else:
                    raise
            newly_known.extend(adapter.ledger[before:])
            decision_pair = decision_index.get(symbol, {}).get(
                detail["available_ts_ms"]
            )
            if adapter.state not in TERMINAL and decision_pair is not None:
                i, decision = decision_pair
                if decision["open_ts_ms"] >= adapter.order["order_active_ts_ms"]:
                    if (
                        prefix_known[symbol][i] > decision["available_ts_ms"]
                        or prefix_closed[symbol][i] > decision["close_ts_ms"]
                    ):
                        raise ValueError("CALLBACK_HISTORY_CONTAINS_FUTURE")
                    adapter.process_decision_bar(
                        decision,
                        _callback_history(
                            decision_rows[symbol], i, binding["callback_history_policy"]
                        ),
                    )
            if adapter.state in TERMINAL:
                execution = adapter.finish()
                if adapter.state == "UNRESOLVED":
                    execution["unresolved_observed_ts_ms"] = min(
                        detail["open_ts_ms"], contiguous_end
                    )
                    execution["gap_resume_or_detection_ts_ms"] = detail["open_ts_ms"]
                    execution["unresolved_from_ts_ms"] = (adapter.position or {}).get(
                        "entry_ts_ms", adapter.order["order_active_ts_ms"]
                    )
                executions.append(execution)
                statuses.append(
                    {
                        "symbol": symbol,
                        "ts_ms": adapter.last_available,
                        "status": adapter.state,
                    }
                )
                if adapter.state != "UNRESOLVED":
                    del active[symbol]
                    del reserved[symbol]
        newly_known.sort(key=lambda r: (r["ts_ms"], r["symbol"]))
        book.consume(newly_known)
        ledger.extend(newly_known)
    for adapter in active.values():
        if adapter.state != "UNRESOLVED":
            result = adapter.finish()
            result["unresolved_observed_ts_ms"] = adapter.last_available
            result["unresolved_from_ts_ms"] = (adapter.position or {}).get(
                "entry_ts_ms", adapter.order["order_active_ts_ms"]
            )
            executions.append(result)
    return {"ledger": ledger, "executions": executions, "statuses": statuses}


def _session(
    binding: Mapping[str, Any],
    module: Any,
    schedule: list[dict[str, Any]],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    config = copy.deepcopy(binding["config"])
    portfolio = "symbol_configs" in config
    model_class = (
        module.NoisePortfolioTargetModel if portfolio else module.SessionTargetModel
    )
    model = model_class(config, binding["initial_cash_usdt"])
    sleeves = model.models if portfolio else {config["symbol"]: model}
    if set(inputs["detail_frames"]) != set(sleeves):
        raise ValueError("SESSION_SLEEVE_UNIVERSE_MISMATCH")
    pending: dict[str, dict[str, Any]] = {}
    decisions = sorted(
        schedule, key=lambda r: (r["feature_available_ts_ms"], r["symbol"])
    )
    pointer = 0
    previous: dict[str, dict[str, Any]] = {}
    unknown_clock: dict[str, int] = {}
    statuses = []

    def queue(rows: Any) -> None:
        for row in rows or []:
            pending[row["order_id"]] = row

    def mark_gap(symbol: str, reason: str, stamp: int) -> None:
        sleeves[symbol].mark_gap(reason)
        if sleeves[symbol].state == "UNRESOLVED":
            unknown_clock.setdefault(symbol, stamp)
            statuses.append({"symbol": symbol, "ts_ms": stamp, "status": reason})

    for opened, batch in _detail_groups(inputs["detail_frames"]):
        current = {symbol: detail for _, symbol, detail in batch}
        for symbol, detail in current.items():
            prior = previous.get(symbol)
            if prior is not None and (
                opened != prior["close_ts_ms"]
                or detail["segment_id"] != prior["segment_id"]
            ):
                mark_gap(symbol, "UNRESOLVED_GENUINE_MINUTE_GAP", prior["close_ts_ms"])
            previous[symbol] = detail
        queue(model.on_clock(opened))
        # All decisions known at this open precede fill acknowledgments at close.
        while (
            pointer < len(decisions)
            and decisions[pointer]["feature_available_ts_ms"] <= opened
        ):
            decision = decisions[pointer]
            pointer += 1
            if _eligible(decision["feature_available_ts_ms"], binding["windows"]):
                queue(model.on_decision(decision))
        for order_id, order in list(pending.items()):
            symbol = order["symbol"]
            sleeve = sleeves[symbol]
            if order_id not in model.pending_orders:
                del pending[order_id]
                continue
            if sleeve.state == "UNRESOLVED" or order["order_active_ts_ms"] > opened:
                continue
            if opened >= order["expires_ts_ms"]:
                mark_gap(symbol, "UNRESOLVED_ORDER_EXPIRY_WITHOUT_MINUTE", opened)
                continue
            detail = current.get(symbol)
            if detail is None:
                continue
            fee = _fee(binding, symbol)
            price = _positive(detail["open"], "open")
            qty = _positive(order["qty_base"], "qty_base")
            if order["effect"] == "OPEN" and float(sleeve.cash) <= 0:
                mark_gap(symbol, "UNRESOLVED_NONPOSITIVE_FINITE_SLEEVE_EQUITY", opened)
                continue
            receipt = {
                **order,
                "type": "FILL",
                "fill_id": "model:" + order_id,
                "ts_ms": opened,
                "available_ts_ms": detail["available_ts_ms"],
                "fill_price": price,
                "fee_usdt": qty * price * fee,
                "maker_taker": "TAKER",
                "execution_evidence": "MODEL_NOT_OBSERVED",
                "source_ref": MODEL,
                "quantity_unit": "BASE",
                "cash_unit": "USDT",
            }
            queue(model.record_fill(receipt))
            del pending[order_id]
    executions = []
    for symbol, sleeve in sleeves.items():
        if sleeve.position is not None or sleeve.pending_orders:
            stamp = previous.get(symbol, {}).get("close_ts_ms", 0)
            mark_gap(symbol, "UNRESOLVED_END_OF_DETAIL", stamp)
        result = sleeve.finish()
        if result["state"] == "UNRESOLVED":
            stamp = unknown_clock.get(
                symbol, previous.get(symbol, {}).get("close_ts_ms", 0)
            )
            result["unresolved_observed_ts_ms"] = stamp
            episode = (sleeve.position or {}).get("episode")
            entries = [
                r["ts_ms"]
                for r in result["ledger"]
                if r["effect"] == "OPEN" and r["position_episode_id"] == episode
            ]
            activations = [
                r["order_active_ts_ms"] for r in sleeve.pending_orders.values()
            ]
            result["unresolved_from_ts_ms"] = min(entries + activations, default=stamp)
        executions.append(result)
    result = model.finish()
    return {"ledger": result["ledger"], "executions": executions, "statuses": statuses}


def _episodes(ledger: list[dict[str, Any]], multiplier: int) -> list[dict[str, Any]]:
    episodes: dict[str, dict[str, Any]] = {}
    for row in ledger:
        ep = row["position_episode_id"]
        q, p = float(row["qty_base"]), float(row["fill_price"])
        if row["effect"] == "OPEN":
            if ep not in episodes:
                episodes[ep] = {
                    "episode_id": ep,
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "entry_ts_ms": row["ts_ms"],
                    "quantity": 0.0,
                    "entry_value": 0.0,
                    "remaining": 0.0,
                    "gross_usdt": 0.0,
                    "cost_usdt": 0.0,
                    "closed": False,
                }
            item = episodes[ep]
            item["quantity"] += q
            item["remaining"] += q
            item["entry_value"] += q * p
        else:
            item = episodes[ep]
            item["gross_usdt"] += (
                item["side"] * q * (p - item["entry_value"] / item["quantity"])
            )
            item["remaining"] -= q
            if abs(item["remaining"]) < 1e-12:
                item["closed"] = True
                item["outcome_available_ts_ms"] = row["available_ts_ms"]
                item["exit_ts_ms"] = row["ts_ms"]
        item["cost_usdt"] += float(row["fee_usdt"]) * multiplier
        item["net_reference_usdt"] = item["gross_usdt"] - item["cost_usdt"]
    return list(episodes.values())


def summarize(
    executed: Mapping[str, Any], binding: Mapping[str, Any], inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Only resolved closed cohorts receive metrics; unknown is never zero."""
    ledger = executed["ledger"]
    unknown = [
        e
        for e in executed["executions"]
        if e.get("state", e.get("status")) == "UNRESOLVED"
        or e.get("unresolved") is True
    ]
    reports: dict[str, Any] = {}
    for multiplier in (1, 2):
        episodes = _episodes(ledger, multiplier)
        windows = []
        for window in binding["windows"]:
            if window["kind"] in {"TRAIN", "CONTEXT"}:
                continue
            start, end = window["start_ts_ms"], window["end_ts_ms"]
            cohort = [
                e
                for e in episodes
                if start <= e["entry_ts_ms"] < end
                and e["closed"]
                and e["outcome_available_ts_ms"] < end
            ]
            crossing = [
                e
                for e in episodes
                if e["entry_ts_ms"] < end
                and (not e["closed"] or e["outcome_available_ts_ms"] >= end)
                and e["entry_ts_ms"] >= start
            ]
            carried = [
                e
                for e in episodes
                if e["entry_ts_ms"] < start
                and (not e["closed"] or e["outcome_available_ts_ms"] >= start)
            ]
            nets = [
                e["net_reference_usdt"]
                for e in sorted(cohort, key=lambda e: e["outcome_available_ts_ms"])
            ]
            win = sum(x > 0 for x in nets)
            gains, losses = sum(x for x in nets if x > 0), -sum(
                x for x in nets if x < 0
            )
            streak = maximum = 0
            for value in nets:
                streak = streak + 1 if value < 0 else 0
                maximum = max(maximum, streak)
            unresolved_count = len(crossing)
            affected = [e for e in unknown if e.get("unresolved_from_ts_ms", 0) < end]
            complete = not (unresolved_count or carried or affected)
            windows.append(
                {
                    **window,
                    "T_resolved": len(nets),
                    "T_per_day_resolved": len(nets) / ((end - start) / 86_400_000),
                    "WR_resolved_pct": 100 * win / len(nets) if nets else None,
                    "gross_resolved_usdt": sum(e["gross_usdt"] for e in cohort),
                    "net_resolved_reference_usdt": sum(nets),
                    "net_per_trade_resolved_reference_usdt": (
                        sum(nets) / len(nets) if nets else None
                    ),
                    "PF_resolved_reference": gains / losses if losses else None,
                    "PF_no_losses": bool(nets) and losses == 0,
                    "MaxLS_resolved": maximum if nets else None,
                    "cross_boundary_or_open_count": unresolved_count,
                    "carry_in_count": len(carried),
                    "complete_window": complete,
                    "net_complete_reference_usdt": sum(nets) if complete else None,
                    "actual_historical_net_usdt": None,
                    "DD_pct": None,
                    "DD_status": "USE_SEPARATE_SAMPLED_ACCOUNT_CURVE_NOT_TRADE_SUM",
                    "funding_status": "UNKNOWN_NOT_ZERO",
                }
            )
        costs = [{**r, "fee_usdt": float(r["fee_usdt"]) * multiplier} for r in ledger]
        account = None
        account_status = "UNRESOLVED_EXECUTION_PREVENTS_COMPLETE_ACCOUNT_CURVE"
        cutoff = min(
            (e.get("unresolved_observed_ts_ms", 0) for e in unknown), default=2**63 - 1
        )
        samples_before_unknown = [
            p for p in inputs.get("price_snapshots", []) if p["ts_ms"] < cutoff
        ]
        if samples_before_unknown:
            last_sample = samples_before_unknown[-1]["ts_ms"]
            prefix_costs = [r for r in costs if r["ts_ms"] <= last_sample]
            account = account_snapshots_from_ledger(
                prefix_costs,
                samples_before_unknown,
                initial_cash_usdt=binding["initial_cash_usdt"],
                start_ts_ms=binding["windows"][0]["start_ts_ms"],
                price_basis="LAST_PRICE",
            )
            account_status = "REFERENCE_COST_LAST_PRICE_NAV_FUNDING_UNKNOWN" + (
                "_PREFIX_ONLY" if unknown else ""
            )
            curve = account["valuation"]["curve"]
            for window in windows:
                samples = [
                    r
                    for r in curve
                    if window["start_ts_ms"] <= r["ts_ms"] < window["end_ts_ms"]
                ]
                if window["complete_window"] and samples:
                    prior = [r for r in curve if r["ts_ms"] < window["start_ts_ms"]]
                    baseline = (
                        prior[-1]["equity_usdt"]
                        if prior
                        else binding["initial_cash_usdt"]
                    )
                    peak, dd = float(baseline), 0.0
                    for sample in samples:
                        equity = float(sample["equity_usdt"])
                        peak = max(peak, equity)
                        if peak > 0:
                            dd = max(dd, 100 * (peak - equity) / peak)
                    window["DD_pct"] = dd
                    window["DD_status"] = "SAMPLED_LAST_PRICE_REFERENCE_SCENARIO"
        reports[str(multiplier) + "x"] = {
            "windows": windows,
            "episodes": episodes,
            "account": account,
            "account_status": account_status,
        }
    return {
        "schema": SCHEMA,
        "identity_key": binding["identity_key"],
        "binding_sha256": binding["binding_sha256"],
        "cost_scenarios": reports,
        "execution": executed,
        "unknown_execution_count": len(unknown),
        "fresh_T": 0,
        "fresh_status": "NO_GENUINE_FORWARD_OBSERVATION_EXECUTED",
        "authority": dict(AUTHORITY),
        "formal_promotion": "BLOCKED",
        "economics_claim": "REFERENCE_COST_MODEL_COMPARISON_NOT_REALIZED_ACCOUNT_PERFORMANCE",
    }


def _replay(
    binding: Mapping[str, Any], inputs: Mapping[str, Any], module: Any
) -> dict[str, Any]:
    compiler = getattr(module, binding["compiler"])
    if binding["execution_mode"] == "SESSION_TARGET":
        compiled = compiler(inputs["frames"], binding["config"])
        executed = _session(binding, module, compiled, inputs)
    else:
        compiled = compiler(binding["model_id"], inputs["frames"], binding["config"])
        executed = _conditional(binding, module, compiled, inputs)
    return summarize(executed, binding, inputs)


def run_fixture(
    binding: Mapping[str, Any],
    inputs: Mapping[str, Any],
    *,
    expected_binding_sha256: str,
) -> dict[str, Any]:
    """Synthetic wiring checks never count as FULL or authentic economic evidence."""
    if binding["data_manifest"].get("data_kind") != "SYNTHETIC_FIXTURE":
        raise PermissionError(
            "GENUINE_HISTORY_REQUIRES_PREEXISTING_NEW_FULL_ALLOCATION"
        )
    if not binding["data_manifest"].get("construction_reason"):
        raise ValueError("EXPLICIT_FIXTURE_CONSTRUCTION_REQUIRED")
    for group in ("frames", "detail_frames"):
        if any(
            frame.attrs.get("source_rows_are_genuine") is True
            or frame.attrs.get("data_kind") == "GENUINE_RAW_HISTORY"
            for frame in inputs[group].values()
        ):
            raise PermissionError("GENUINE_LOADER_PROVENANCE_CANNOT_ENTER_FIXTURE_PATH")
    module = verify_binding(binding, expected_binding_sha256)
    result = _replay(binding, inputs, module)
    result.update(full_execution_performed=False, data_kind="SYNTHETIC_FIXTURE")
    return result


def run_authorized(
    binding: Mapping[str, Any],
    *,
    expected_binding_sha256: str,
    registry_path: str | Path,
    scope: str,
    owner: str,
    output_path: str | Path,
) -> dict[str, Any]:
    """Exactly one preallocated FULL; no loader or producer runs before admission.

    The manifest names a hash-bound research loader whose local import closure is
    included in the binding. Loader returns canonical frames/detail/last prices.
    """
    if binding["data_manifest"].get("data_kind") != "GENUINE_RAW_HISTORY":
        raise ValueError("GENUINE_HISTORY_MANIFEST_REQUIRED")
    admission(binding, registry_path=registry_path, scope=scope, owner=owner)
    module = verify_binding(binding, expected_binding_sha256)
    loader_spec = binding["data_manifest"].get("loader")
    if not isinstance(loader_spec, Mapping):
        raise ValueError("FROZEN_DATA_LOADER_REQUIRED")
    loader_module = importlib.import_module(loader_spec["module"])
    loader = getattr(loader_module, loader_spec["function"])
    loader_closure = code_closure(loader_spec["module"])
    if binding.get("loader_code_closure") != loader_closure:
        raise ValueError("DATA_LOADER_CLOSURE_CHANGED")
    _verify_input_files(binding["data_manifest"])
    destination = Path(output_path)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError("NEW_DURABLE_RESULT_PATH_REQUIRED")
    ledger = CampaignLedger(registry_path)
    key = binding["identity_key"]
    if not ledger.start(key, owner):
        raise PermissionError("EXISTING_EXECUTION_MUST_BE_RECOVERED_NOT_REPEATED")
    try:
        inputs = loader(binding["data_manifest"], binding["config"])
        result = _replay(binding, inputs, module)
        result.update(full_execution_performed=True, data_kind="GENUINE_RAW_HISTORY")
        payload = json.dumps(result, sort_keys=True, allow_nan=False).encode()
        temporary = destination.with_suffix(destination.suffix + ".partial")
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish atomically without replacing a path created after preflight.
        # Both names are in one directory, so the hard link stays on one filesystem.
        os.link(temporary, destination)
        temporary.unlink()
        directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        ledger.finish(
            key,
            owner,
            "COMPLETED",
            {
                "result_path": str(destination),
                "result_file_sha256": _sha(destination),
                "binding_sha256": binding["binding_sha256"],
                "result_sha256": digest(result),
                "unknown_execution_count": result["unknown_execution_count"],
            },
        )
        return result
    except BaseException as exc:
        ledger.finish(
            key,
            owner,
            "FAILED",
            {
                "binding_sha256": binding["binding_sha256"],
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "budget_consumed": True,
                "automatic_retry_forbidden": True,
            },
        )
        raise
