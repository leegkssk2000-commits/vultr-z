"""HG1997 full-account bridge; no new rule, budget, or promotion authority.

The immutable generic runner instantiates DetailExecutionAdapter directly. HG
requires its already implemented HGExecutionAdapter so a stop-only minute can
invalidate an unfilled order. This separate runner preserves that lifecycle,
shared-capital reservation, data-gap ownership and the existing accounting.
"""
from __future__ import annotations

import importlib
import itertools
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.research.rebuild import scalp7_exact25_model_runner_v1 as base
from backend.research.rebuild import scalp7_hg_closure_v1 as hg
from backend.research.rebuild.scalp7_product_contracts_v1 import bind_price_grid

MODEL_ID = hg.MODEL_ID
MODULE = "backend.research.rebuild.scalp7_hg_economic_bridge_v1"
VERSION = "scalp7.hg_economic_bridge.v1"
AUTHORITY = {"order": "BLOCKED", "live": "BLOCKED", "promotion": False}


def _config(config: Mapping[str, Any], frames: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a supplied point-in-time grid, never guess a historical increment."""
    if set(config) != {"price_grids"} or set(config["price_grids"]) != set(frames):
        raise ValueError("EXACT_HG_PRICE_GRID_UNIVERSE_REQUIRED")
    ticks = {}
    for symbol, frame in sorted(frames.items()):
        if frame.empty:
            raise ValueError("NONEMPTY_HG_FRAME_REQUIRED")
        item = config["price_grids"][symbol]
        raw = json.dumps(item["receipt"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        stamps = [int(x) for x in frame["available_ts_ms"]]
        for stamp in (min(stamps), max(stamps)):
            bound = bind_price_grid(raw, expected_sha256=item["canonical_receipt_sha256"],
                symbol=symbol, venue=item["receipt"]["venue"], product="USDT_M_PERPETUAL",
                at_ts_ms=stamp, evidence_class=item["receipt"]["evidence_class"])
            if bound["evidence_class"] == "SYNTHETIC_FIXTURE" and (
                frame.attrs.get("data_kind") != "SYNTHETIC_FIXTURE"
                or frame.attrs.get("source_rows_are_genuine") is True
            ):
                raise PermissionError("SYNTHETIC_GRID_CANNOT_AUTHENTICATE_MARKET_HISTORY")
        ticks[symbol] = bound["tick_size"]
    return {"tick_sizes": ticks}


def compile_model(model_id: str, frames: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    compiled = hg.compile_model(model_id, frames, _config(config, frames))
    return {**compiled, "adapter_factory": "scalp7_hg_closure_v1.HGExecutionAdapter",
            "receipt_bytes_bound": True, "provider_authenticity_independently_verified": False,
            "genuine_economic_readiness": "PREALLOCATED_IDENTITY_AND_PINNED_INPUTS_REQUIRED"}


def create_order(plan: dict[str, Any], capital: float, identity: str, rule_digest: str) -> dict[str, Any]:
    return hg.create_order(plan, capital, identity, rule_digest)


def entry_update(signal: dict[str, Any], entry_price: float) -> dict[str, Any]:
    return hg.entry_update(signal, entry_price)


def exit_update(position: dict[str, Any], bar: dict[str, Any], history: Any) -> dict[str, Any]:
    return hg.exit_update(position, bar, history)


def freeze_binding(**kwargs: Any) -> dict[str, Any]:
    """Build an unallocated binding; a config hash is not an execution approval."""
    if kwargs.get("model_id", MODEL_ID) != MODEL_ID:
        raise ValueError("EXISTING_HG_MODEL_ONLY")
    forbidden = {"model_module", "strategy_id", "compiler", "execution_mode"} & set(kwargs)
    if forbidden:
        raise ValueError("FIXED_HG_INTERFACE_REQUIRED")
    args = {**kwargs, "model_id": MODEL_ID, "model_module": MODULE,
            "strategy_id": "keltner_trend", "execution_mode": "DETAIL_CONDITIONAL"}
    if args["data_manifest"].get("data_kind") == "GENUINE_RAW_HISTORY":
        grids = args["config"].get("price_grids", {})
        if set(grids) != set(args["data_manifest"].get("symbols", [])) or not grids:
            raise ValueError("MARKET_GRID_UNIVERSE_REQUIRED")
        if any(x["receipt"].get("evidence_class") != "OBSERVED_METADATA" for x in grids.values()):
            raise PermissionError("OBSERVED_HISTORICAL_GRID_REQUIRED")
    return base.freeze_model(**args)


def _verify(binding: Mapping[str, Any], expected: str) -> None:
    if (binding.get("model_module"), binding.get("model_id"), binding.get("strategy_id"),
        binding.get("execution_mode"), binding.get("compiler")) != (
        MODULE, MODEL_ID, "keltner_trend", "DETAIL_CONDITIONAL", "compile_model"):
        raise ValueError("EXACT_HG_BRIDGE_BINDING_REQUIRED")
    base.verify_binding(binding, expected)


def _replay_inputs(binding: Mapping[str, Any], inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Internal replay callback. Public callers must use run_fixture/run_authorized.

    Based on the immutable runner's shared-capital conditional loop; the only
    lifecycle substitution is HGExecutionAdapter, not a changed HG rule.
    """
    compiled = compile_model(MODEL_ID, inputs["frames"], binding["config"])
    plans = sorted(compiled["plans"], key=lambda p: (p["order_active_ts_ms"], p["symbol"]))
    decisions = {s: [{**r, "symbol": s} for r in f.to_dict("records")]
                 for s, f in compiled["decisions"].items()}
    index = {s: {r["available_ts_ms"]: (i, r) for i, r in enumerate(rows)} for s, rows in decisions.items()}
    known = {s: list(itertools.accumulate((r["available_ts_ms"] for r in rows), max)) for s, rows in decisions.items()}
    closed = {s: list(itertools.accumulate((r["close_ts_ms"] for r in rows), max)) for s, rows in decisions.items()}
    active, reserved, seen = {}, {}, set()
    executions, ledger, statuses = [], [], []
    book, pointer = base._CashBook(binding["initial_cash_usdt"]), 0
    for opened, batch in base._detail_groups(inputs["detail_frames"]):
        while pointer < len(plans) and plans[pointer]["order_active_ts_ms"] <= opened:
            plan = plans[pointer]; pointer += 1
            symbol, stamp = plan["symbol"], int(plan["feature_available_ts_ms"])
            if not base._eligible(stamp, binding["windows"]):
                continue
            if symbol in active:
                statuses.append({"symbol": symbol, "ts_ms": stamp, "status": "EXISTING_OWNERSHIP"}); continue
            free = book.cash - sum(reserved.values())
            if free <= 0:
                statuses.append({"symbol": symbol, "ts_ms": stamp, "status": "FINITE_CAPITAL_UNAVAILABLE"}); continue
            fee = base._fee(binding, symbol)
            order = create_order(plan, free, binding["identity_key"], compiled["rule_digest"])
            order.setdefault("position_episode_id", binding["identity_key"] + ":" + symbol + ":" + str(pointer))
            episode = order["position_episode_id"]
            if episode in seen:
                raise ValueError("DUPLICATE_POSITION_EPISODE")
            seen.add(episode)
            qty = base._positive(order["qty_base"], "qty_base")
            cap = float(order.get("reserved_notional_usdt", order.get("signal", {}).get(
                "reserved_notional_usdt", qty * base._positive(plan["reference_entry_price"], "reference_entry_price"))))
            reserve = cap * (1 + 2 * fee)
            if reserve > free + 1e-9:
                statuses.append({"symbol": symbol, "ts_ms": stamp, "status": "NOTIONAL_RESERVATION_EXCEEDS_CASH"}); continue
            def guarded_entry(signal: Any, price: float, *, q: float = qty, limit: float = cap) -> dict[str, Any]:
                if q * price > limit + 1e-9:
                    return {"reject": True, "reason": "ACTUAL_FILL_EXCEEDS_RESERVED_NOTIONAL"}
                return entry_update(signal, price)
            active[symbol] = hg.HGExecutionAdapter(order, fill_model=base.MODEL, fee_rate=fee,
                entry_update=guarded_entry, exit_update=exit_update)
            reserved[symbol] = reserve
        newly_known = []
        for _, symbol, detail in batch:
            adapter = active.get(symbol)
            if adapter is None or adapter.state == "UNRESOLVED":
                continue
            before = len(adapter.ledger)
            contiguous_end = adapter.details[-1]["close_ts_ms"] if adapter.details else adapter.order["order_active_ts_ms"]
            try:
                if not adapter.details and detail["open_ts_ms"] > adapter.order["order_active_ts_ms"]:
                    adapter._unresolved("MISSING_ACTIVATION_MINUTE")
                else:
                    adapter.process_detail_bar(detail)
            except ValueError as exc:
                if str(exc) in {"ENTRY_CALLBACK_REJECTED", "ENTRY_INVALIDATES_STOP"} and not adapter.ledger:
                    adapter.cancel(detail["available_ts_ms"], str(exc))
                else:
                    raise
            newly_known.extend(adapter.ledger[before:])
            pair = index.get(symbol, {}).get(detail["available_ts_ms"])
            if adapter.state not in base.TERMINAL and pair is not None:
                i, decision = pair
                if decision["open_ts_ms"] >= adapter.order["order_active_ts_ms"]:
                    if known[symbol][i] > decision["available_ts_ms"] or closed[symbol][i] > decision["close_ts_ms"]:
                        raise ValueError("CALLBACK_HISTORY_CONTAINS_FUTURE")
                    adapter.process_decision_bar(decision, base._callback_history(decisions[symbol], i, binding["callback_history_policy"]))
            if adapter.state in base.TERMINAL:
                outcome = adapter.finish()
                if adapter.state == "UNRESOLVED":
                    outcome.update(unresolved_observed_ts_ms=min(detail["open_ts_ms"], contiguous_end),
                        gap_resume_or_detection_ts_ms=detail["open_ts_ms"],
                        unresolved_from_ts_ms=(adapter.position or {}).get("entry_ts_ms", adapter.order["order_active_ts_ms"]))
                executions.append(outcome)
                statuses.append({"symbol": symbol, "ts_ms": adapter.last_available, "status": adapter.state})
                if adapter.state != "UNRESOLVED":
                    del active[symbol]; del reserved[symbol]
        newly_known.sort(key=lambda r: (r["ts_ms"], r["symbol"]))
        book.consume(newly_known); ledger.extend(newly_known)
    for adapter in active.values():
        if adapter.state != "UNRESOLVED":
            outcome = adapter.finish()
            outcome.update(unresolved_observed_ts_ms=adapter.last_available,
                unresolved_from_ts_ms=(adapter.position or {}).get("entry_ts_ms", adapter.order["order_active_ts_ms"]))
            executions.append(outcome)
    out = base.summarize({"ledger": ledger, "executions": executions, "statuses": statuses}, binding, inputs)
    out.update(bridge_version=VERSION, exact_source_reproduction=False, strategy_rules_changed=False,
               original_parent_results_reused=False, g4_complete=False)
    return out


def run_fixture(binding: Mapping[str, Any], inputs: Mapping[str, Any], *, expected_binding_sha256: str) -> dict[str, Any]:
    manifest = binding["data_manifest"]
    if manifest.get("data_kind") != "SYNTHETIC_FIXTURE" or not manifest.get("construction_reason"):
        raise PermissionError("DECLARED_SYNTHETIC_FIXTURE_REQUIRED")
    if set(inputs["frames"]) != set(inputs["detail_frames"]) or not 0 < len(inputs["frames"]) <= 3:
        raise ValueError("BOUNDED_FIXTURE_UNIVERSE_REQUIRED")
    for group, cap in (("frames", 256), ("detail_frames", 2048)):
        if sum(len(f) for f in inputs[group].values()) > cap:
            raise PermissionError("FIXTURE_ROW_CAP_EXCEEDED")
        for frame in inputs[group].values():
            if frame.attrs.get("data_kind") != "SYNTHETIC_FIXTURE" or frame.attrs.get("source_rows_are_genuine") is True:
                raise PermissionError("MARKET_HISTORY_NOT_A_FIXTURE")
    _verify(binding, expected_binding_sha256)
    return {**_replay_inputs(binding, inputs), "full_execution_performed": False, "data_kind": "SYNTHETIC_FIXTURE", "new_full_runs": 0}


def run_authorized(binding: Mapping[str, Any], *, expected_binding_sha256: str,
                   registry_path: str | Path, scope: str, owner: str, output_path: str | Path) -> dict[str, Any]:
    """One previously approved/reserved run; never allocate a scope or retry."""
    if binding["data_manifest"].get("data_kind") != "GENUINE_RAW_HISTORY":
        raise ValueError("GENUINE_HISTORY_MANIFEST_REQUIRED")
    base.admission(binding, registry_path=registry_path, scope=scope, owner=owner)
    _verify(binding, expected_binding_sha256)
    spec = binding["data_manifest"].get("loader")
    if not isinstance(spec, Mapping) or base.code_closure(spec["module"]) != binding.get("loader_code_closure"):
        raise ValueError("FROZEN_LOADER_REQUIRED")
    if any(x["receipt"].get("evidence_class") != "OBSERVED_METADATA" for x in binding["config"]["price_grids"].values()):
        raise PermissionError("OBSERVED_HISTORICAL_GRID_REQUIRED")
    base._verify_input_files(binding["data_manifest"])
    destination = Path(output_path)
    partial = destination.with_suffix(destination.suffix + ".partial")
    if os.path.lexists(destination) or os.path.lexists(partial) or not destination.parent.is_dir():
        raise ValueError("NEW_DURABLE_OUTPUT_REQUIRED")
    ledger = base.CampaignLedger(registry_path)
    if not ledger.start(binding["identity_key"], owner):
        raise PermissionError("EXISTING_EXECUTION_MUST_BE_RECOVERED_NOT_REPEATED")
    published = False
    try:
        supplied = getattr(importlib.import_module(spec["module"]), spec["function"])(binding["data_manifest"], binding["config"])
        out = {**_replay_inputs(binding, supplied), "full_execution_performed": True, "data_kind": "GENUINE_RAW_HISTORY"}
        with partial.open("xb") as handle:
            handle.write(json.dumps(out, sort_keys=True, allow_nan=False).encode()); handle.flush(); os.fsync(handle.fileno())
        os.link(partial, destination); published = True
        fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        partial.unlink()
        ledger.finish(binding["identity_key"], owner, "COMPLETED", {
            "result_path": str(destination), "result_file_sha256": base._sha(destination),
            "binding_sha256": binding["binding_sha256"], "unknown_execution_count": out["unknown_execution_count"]})
        return out
    except BaseException as exc:
        if not published:
            ledger.finish(binding["identity_key"], owner, "FAILED", {"binding_sha256": binding["binding_sha256"],
                "exception_type": type(exc).__name__, "budget_consumed": True, "automatic_retry_forbidden": True})
        # A published result is reconciled with its original claim, never replayed.
        raise
