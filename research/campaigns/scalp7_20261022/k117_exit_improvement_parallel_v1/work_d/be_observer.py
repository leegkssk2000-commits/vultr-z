"""Passive, hash-bound observation of the frozen native single-position engine.

No exit rule, threshold, quantity, price, fee or native return is replaced.
Disabled instrumentation returns the original function object. Enabled mode
adds observation calls to a private AST copy; the original module is untouched.
Costs below are the engine's entry-fixed reference cost. Final saved carry
charges and ex-post 2x cost stress are not copied into a decision stop.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import inspect
from types import CodeType, FunctionType

ENGINE_SHA256 = "d1461371124c2fbb3e4e9acb0afb7457fcec0b9740b908c2d98a6401bcae6cb1"
POSITIVE_SOURCE_SHA256 = "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2"
SCHEMA = "zel.work_d.k117.passive_be_observer.v1"


def _key(signal):
    getter = signal.get if isinstance(signal, dict) else lambda name: None
    return [getter("symbol"), getter("side"), getter("signal_ts_ms")]


def _snapshot(position):
    """Whitelist native state; never retain a frame or a mutable strategy object."""
    entry = float(position["entry_price"])
    side = int(position["side"])
    stop = float(position["stop_price"])
    remaining = float(position["remaining"])
    realized = float(position["realized_parts_bps"])
    cost = float(position["cost_bps"])
    stop_terminal = side * (stop / entry - 1) * 10_000
    protected_gross = realized + remaining * stop_terminal
    meta = position["signal"].get("meta", {})
    return {
        "entry_price": entry, "side": side,
        "entry_ts_ms": int(position["entry_ts_ms"]),
        "initial_stop": float(position["initial_stop"]),
        "initial_risk": float(position["initial_risk"]),
        "stop_price": stop, "remaining": remaining,
        "realized_parts_bps": realized,
        "observed_mfe_R": float(position["mfe_R"]),
        "observed_mae_R": float(position["mae_R"]),
        "hold_bars": int(position["hold_bars"]),
        "cost_bps": cost,
        "signal_frozen_cost_bps": meta.get("frozen_cost_bps"),
        "signal_be_arm_r": meta.get("be_arm_r"),
        "partial_executed": bool(position.get("partial_executed", False)),
        "quantity_unit": "FRACTION_OF_ORIGINAL_ENTRY_NOTIONAL",
        "pnl_unit": "ORIGINAL_EQUAL_NOTIONAL_TRADE_BPS",
        "gross_at_exact_current_stop_fill_bps": protected_gross,
        "net_at_exact_current_stop_fill_reference_bps": protected_gross - cost,
        "exact_stop_fill_is_not_guaranteed": True,
        "future_carry_not_included": True,
        "cost2x_stress_is_not_execution_input": True,
    }


def _closed_bar(bar):
    # Called only after stop/target checks and the native availability guard.
    return {
        "bar_open_ts_ms": int(bar["open_ts_ms"]),
        "bar_close_ts_ms": int(bar["close_ts_ms"]),
        "available_ts_ms": int(bar["available_ts_ms"]),
        "completed_close": float(bar["close"]),
    }


class BEObserver:
    """Collect completed native-call bundles, keeping original return objects."""

    def __init__(self):
        self.records = []
        self._contexts = {}
        self._serial = 0

    @property
    def flat_events(self):
        return [event for record in self.records for event in record["events"]]

    def begin(self, signal):
        self._serial += 1
        token = self._serial
        self._contexts[token] = {
            "trade_key": deepcopy(_key(signal)), "events": [],
            "be_seen": False, "runner_seen": False, "staged_stop": None,
            "last_pending": None,
        }
        return token

    def _append(self, token, kind, **fields):
        context = self._contexts[token]
        event = {
            "kind": kind, "event_seq": len(context["events"]) + 1,
            "trade_key": deepcopy(context["trade_key"]), **deepcopy(fields),
        }
        context["events"].append(event)
        return event

    def on_entry(self, token, position):
        self._append(token, "ENTRY", position=_snapshot(position),
                     available_ts_ms=int(position["entry_ts_ms"]))

    def on_bar_start(self, token, position, opened, opening, pending):
        context = self._contexts[token]
        staged = context["staged_stop"]
        activated = None
        if staged is not None and not pending:
            if (opened > staged["request_bar_open_ts_ms"]
                    and opened >= staged["decision_available_ts_ms"]
                    and float(position["stop_price"]) == staged["accepted_stop"]):
                activated = staged["event_seq"]
        context["last_pending"] = pending
        self._append(
            token, "BAR_START", position=_snapshot(position),
            bar_open_ts_ms=int(opened), bar_open_price=float(opening),
            pending_exit_reason=pending,
            effective_stop=float(position["stop_price"]),
            stop_effective_for_protective_check=not bool(pending),
            stop_check_will_be_skipped_due_to_pending_exit=bool(pending),
            activation_of_request_event_seq=activated,
            staged_stop_request_event_seq=staged["event_seq"] if staged else None,
            high_low_not_exposed=True,
        )
        # A request can be linked once, to the next eligible observed bar.
        if staged is not None:
            context["staged_stop"] = None

    def on_callback_before(self, token, position, bar):
        self._append(token, "CALLBACK_BEFORE", position=_snapshot(position),
                     **_closed_bar(bar),
                     stop_and_target_checks_already_passed=True)

    def on_callback_after(self, token, position, bar, update):
        context = self._contexts[token]
        meta = position["signal"].get("meta", {})
        arm = meta.get("be_arm_r")
        eligible = arm is not None and float(position["mfe_R"]) >= float(arm)
        reason = update.get("reason")
        # A frozen outer structure callback may replace the reason while keeping
        # the native next_stop. Separate rule eligibility and actual proposal
        # consistency, instead of treating the final reason as the state trace.
        keltner = position["signal"].get("identity") in (
            "scalp7_keltner_hg_parent_utc30m_v2", "scalp7_keltner_hg_td075_utc30m_v2")
        expected_be, expected_runner = None, None
        runner_eligible = keltner and float(position["mfe_R"]) >= 3.0
        if keltner and eligible and meta.get("frozen_cost_bps") is not None:
            entry, side = float(position["entry_price"]), int(position["side"])
            expected_be = entry * (1 + side * (float(meta["frozen_cost_bps"]) + 2.0) / 10_000)
            if runner_eligible:
                peak = entry + side * float(position["mfe_R"]) * float(position["initial_risk"])
                proposed = peak - side * 1.25 * float(position["initial_risk"])
                expected_runner = max(expected_be, proposed) if side == 1 else min(expected_be, proposed)
        requested = update.get("next_stop")
        frozen_request_matches = requested is not None and (
            float(requested) == expected_be or float(requested) == expected_runner)
        runner_request_matches = expected_runner is not None and requested is not None and float(requested) == expected_runner
        native_be_request = (
            eligible and requested is not None and
            (frozen_request_matches or reason in ("FEE_BE_NEXT_BAR", "HG_3R_RUNNER_NEXT_BAR"))
        )
        first_be = native_be_request and not context["be_seen"]
        native_runner_request = runner_request_matches or reason == "HG_3R_RUNNER_NEXT_BAR"
        first_runner = native_runner_request and not context["runner_seen"]
        if native_be_request:
            context["be_seen"] = True
        if native_runner_request:
            context["runner_seen"] = True
        self._append(
            token, "CALLBACK_AFTER", position=_snapshot(position),
            **_closed_bar(bar),
            update={k: deepcopy(update[k]) for k in
                    ("reason", "next_stop", "exit_next_open", "partial_fraction", "partial_price")
                    if k in update},
            be_eligibility_observed=bool(eligible),
            be_first_arm=bool(first_be), runner_first_arm=bool(first_runner),
            be_arm_threshold_source="signal.meta.be_arm_r",
            runner_branch_eligible_from_frozen_rule=bool(runner_eligible),
            runner_request_consistent_with_frozen_rule=bool(runner_request_matches),
            be_request_consistent_with_frozen_rule=bool(frozen_request_matches),
            expected_fee_be_from_frozen_rule=expected_be,
            expected_runner_from_frozen_rule=expected_runner,
            final_reason_overrode_consistent_native_stop=bool(
                frozen_request_matches and reason not in ("FEE_BE_NEXT_BAR", "HG_3R_RUNNER_NEXT_BAR")),
            frozen_rule_reference_sha256=POSITIVE_SOURCE_SHA256,
            callback_call_path_must_be_bound_by_owner=True,
            stop_request_is_not_same_bar_fill=True,
        )

    def on_partial(self, token, position, bar, fraction, price):
        entry = float(position["entry_price"])
        side = int(position["side"])
        fraction, price = float(fraction), float(price)
        increment = fraction * side * (price / entry - 1) * 10_000
        self._append(
            token, "PARTIAL_FILLED", position=_snapshot(position),
            **_closed_bar(bar), partial_fraction=fraction, partial_price=price,
            remaining_before=float(position["remaining"]) + fraction,
            remaining_after=float(position["remaining"]),
            realized_increment_bps=increment,
            realized_parts_before_bps=float(position["realized_parts_bps"]) - increment,
            realized_parts_after_bps=float(position["realized_parts_bps"]),
            partial_fraction_unit="ORIGINAL_ENTRY_NOTIONAL_FRACTION",
            price_validation="NATIVE_FROZEN_TARGET_AND_COMPLETE_BAR_RANGE_PASSED",
        )

    def on_stop_applied(self, token, position, bar, requested, previous):
        side = int(position["side"])
        accepted, previous = float(position["stop_price"]), float(previous)
        event = self._append(
            token, "STOP_APPLIED", position=_snapshot(position),
            **_closed_bar(bar),
            requested_stop=float(requested), previous_stop=previous,
            accepted_stop=accepted, monotonic=side * (accepted - previous) >= 0,
            stop_tightened=side * (accepted - previous) > 0,
            no_same_bar_application=True,
            decision_available_ts_ms=int(bar["available_ts_ms"]),
            next_observed_bar_required=True,
            accepted_stop_beyond_completed_close=side * (float(bar["close"]) - accepted) < 0,
        )
        self._contexts[token]["staged_stop"] = {
            "event_seq": event["event_seq"], "accepted_stop": accepted,
            "decision_available_ts_ms": int(bar["available_ts_ms"]),
            "request_bar_open_ts_ms": int(bar["open_ts_ms"]),
        }

    def on_close(self, token, position, row):
        reason = row["reason"]
        pending = self._contexts[token]["last_pending"]
        precedence = (
            "PENDING_NEXT_OPEN_BEFORE_STOP" if pending
            else "STOP_BEFORE_TARGET_MFE_CALLBACK" if reason in ("STOP_FIRST", "OPEN_GAP_STOP")
            else "TARGET_BEFORE_MFE_CALLBACK" if reason == "TARGET"
            else "NATIVE_CLOSE"
        )
        self._append(
            token, "TERMINAL", position=_snapshot(position),
            reason=reason, precedence=precedence,
            exit_ts_ms=int(row["exit_ts_ms"]),
            outcome_available_ts_ms=int(row["outcome_available_ts_ms"]),
            outcome_time_precision=row["outcome_time_precision"],
            exit_prices=deepcopy(row["exit_prices"]),
            gross_bps=float(row["gross_bps"]), cost_bps=float(row["cost_bps"]),
            net_bps=float(row["net_bps"]),
            stop_hit_bar_extrema_were_not_promoted_to_observed_mfe=True,
        )
        return row

    def on_return(self, token, result):
        row, unresolved, until, reason = result
        if unresolved is not None:
            self._append(
                token, "UNRESOLVED", position=_snapshot(unresolved["position"]),
                state=unresolved["state"], exclusion=unresolved["exclusion"],
                unresolved_reason=unresolved["position"].get("unresolved_reason", "GAP_OR_END"),
                last_observed_close_ts_ms=unresolved.get("last_observed_close_ts_ms"),
                ownership_retained=True,
                unapplied_stop_request=deepcopy(self._contexts[token]["staged_stop"]),
            )
        elif reason is not None:
            self._append(token, "REJECTED", reason=reason)
        context = self._contexts.pop(token)
        self.records.append({
            "schema": SCHEMA, "trade_key": context["trade_key"],
            "trade": deepcopy(row), "events": context["events"],
            "unresolved": deepcopy(unresolved), "rejection_reason": reason,
            "ownership_until_ts_ms": int(until),
            "engine_source_sha256": ENGINE_SHA256,
            "passive_only": True,
        })
        return result


def _code_fingerprint(code):
    def constant(value):
        if isinstance(value, CodeType):
            return _code_fingerprint(value)
        if isinstance(value, tuple):
            return tuple(constant(v) for v in value)
        return (type(value).__name__, repr(value))
    return (
        code.co_code, tuple(constant(v) for v in code.co_consts),
        code.co_names, code.co_varnames, code.co_argcount,
        code.co_posonlyargcount, code.co_kwonlyargcount, code.co_flags,
        code.co_freevars, code.co_cellvars,
    )


def _call(method, arguments):
    return ast.Call(
        func=ast.Attribute(value=ast.Name(id="__be_observer", ctx=ast.Load()),
                           attr=method, ctx=ast.Load()),
        args=[ast.Name(id="__be_token", ctx=ast.Load()), *arguments],
        keywords=[],
    )


def _statement(source):
    return ast.parse(source).body[0]


def _position_subscript(target, name):
    return (isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name) and target.value.id == "position"
            and isinstance(target.slice, ast.Constant) and target.slice.value == name)


class _Instrument(ast.NodeTransformer):
    def __init__(self):
        self.counts = {name: 0 for name in
                       ("entry", "bar_start", "callback", "partial", "stop", "close", "return")}

    def visit_AnnAssign(self, node):
        node = self.generic_visit(node)
        if isinstance(node.target, ast.Name) and node.target.id == "position":
            self.counts["entry"] += 1
            return [node, _statement("__be_observer.on_entry(__be_token, position)")]
        return node

    def visit_Assign(self, node):
        node = self.generic_visit(node)
        if len(node.targets) != 1:
            return node
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "opened":
            self.counts["bar_start"] += 1
            return [node, _statement("__be_observer.on_bar_start(__be_token, position, opened, bar['open'], pending)")]
        if (isinstance(target, ast.Name) and target.id == "update"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "callback"):
            self.counts["callback"] += 1
            return [_statement("__be_observer.on_callback_before(__be_token, position, bar)"),
                    node, _statement("__be_observer.on_callback_after(__be_token, position, bar, update)")]
        if _position_subscript(target, "partial_executed"):
            self.counts["partial"] += 1
            return [node, _statement("__be_observer.on_partial(__be_token, position, bar, fraction, partial_px)")]
        if _position_subscript(target, "stop_price"):
            self.counts["stop"] += 1
            return [node, _statement("__be_observer.on_stop_applied(__be_token, position, bar, new_stop, stop)")]
        return node

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "_close_row":
            self.counts["close"] += 1
            return _call("on_close", [ast.Name(id="position", ctx=ast.Load()), node])
        return node

    def visit_Return(self, node):
        node = self.generic_visit(node)
        self.counts["return"] += 1
        return ast.Return(value=_call("on_return", [node.value]))


class _RemoveHooks(ast.NodeTransformer):
    @staticmethod
    def hook(value):
        return (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name) and value.func.value.id == "__be_observer")

    def visit_Expr(self, node):
        return None if self.hook(node.value) else self.generic_visit(node)

    def visit_Assign(self, node):
        if any(isinstance(t, ast.Name) and t.id == "__be_token" for t in node.targets):
            return None
        return self.generic_visit(node)

    def visit_Call(self, node):
        if self.hook(node) and node.func.attr == "on_close":
            return self.visit(node.args[2])
        if self.hook(node) and node.func.attr == "on_return":
            return self.visit(node.args[1])
        return self.generic_visit(node)


def instrument_single(incumbent, *, source_text, observer, enabled=False):
    """Build a passive private copy; no replay or mutation occurs during build."""
    if enabled is not True:
        return incumbent
    if not isinstance(source_text, str) or hashlib.sha256(source_text.encode()).hexdigest() != ENGINE_SHA256:
        raise ValueError("FROZEN_ENGINE_SOURCE_CHANGED")
    if not isinstance(observer, BEObserver):
        raise TypeError("BE_OBSERVER_REQUIRED")
    if not inspect.isfunction(incumbent) or incumbent.__name__ != "_single":
        raise ValueError("FROZEN_SINGLE_FUNCTION_REQUIRED")
    parsed = ast.parse(source_text)
    names = ("_single", "_close_row", "_can_follow", "_finite")
    functions = {}
    for name in names:
        matches = [n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == name]
        if len(matches) != 1:
            raise ValueError("FROZEN_FUNCTION_NOT_UNIQUE:" + name)
        functions[name] = matches[0]
    # Compile the full module without executing it. CPython's import-aware
    # optimization depends on module context (e.g. math.isfinite), so compiling
    # isolated functions can produce different but equivalent bytecode.
    reference = compile(parsed, "<frozen-engine-reference>", "exec", dont_inherit=True)
    expected_codes = {}
    for name in names:
        matches = [value for value in reference.co_consts
                   if isinstance(value, CodeType) and value.co_name == name]
        if len(matches) != 1:
            raise ValueError("FROZEN_CODE_OBJECT_NOT_UNIQUE:" + name)
        expected_codes[name] = matches[0]
    for name in names:
        actual = incumbent if name == "_single" else incumbent.__globals__.get(name)
        node = functions[name]
        expected_annotations = {
            argument.arg: ast.unparse(argument.annotation)
            for argument in node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            if argument.annotation is not None}
        if node.returns is not None:
            expected_annotations["return"] = ast.unparse(node.returns)
        expected_defaults = tuple(ast.literal_eval(value) for value in node.args.defaults) or None
        if (not inspect.isfunction(actual)
                or _code_fingerprint(actual.__code__) != _code_fingerprint(expected_codes[name])
                or actual.__defaults__ != expected_defaults
                or actual.__annotations__ != expected_annotations):
            raise ValueError("FROZEN_FUNCTION_CODE_OR_SIGNATURE_CHANGED:" + name)
    original = functions["_single"]
    transformer = _Instrument()
    changed = transformer.visit(deepcopy(original))
    changed.body.insert(0, _statement("__be_token = __be_observer.begin(signal)"))
    required = {"entry": 1, "bar_start": 1, "callback": 1, "partial": 1,
                "stop": 1, "close": 3, "return": 14}
    if transformer.counts != required:
        raise ValueError("INSTRUMENTATION_INSERTION_COUNT_CHANGED")
    restored = _RemoveHooks().visit(deepcopy(changed))
    if ast.dump(restored, include_attributes=False) != ast.dump(original, include_attributes=False):
        raise ValueError("INSTRUMENTATION_CHANGED_NATIVE_AST")
    target_scope = dict(incumbent.__globals__)
    if "__be_observer" in target_scope:
        raise ValueError("OBSERVER_GLOBAL_NAME_COLLISION")
    target_scope["__be_observer"] = observer
    module = deepcopy(parsed)
    module.body = [changed if isinstance(node, ast.FunctionDef) and node.name == "_single" else node
                   for node in module.body]
    compiled = compile(ast.fix_missing_locations(module), "<passive-native-be-observer>", "exec",
                       dont_inherit=True)
    codes = [value for value in compiled.co_consts
             if isinstance(value, CodeType) and value.co_name == "_single"]
    if len(codes) != 1:
        raise ValueError("INSTRUMENTED_SINGLE_NOT_UNIQUE")
    result = FunctionType(codes[0], target_scope, incumbent.__name__,
                          incumbent.__defaults__, incumbent.__closure__)
    result.__annotations__ = deepcopy(incumbent.__annotations__)
    result.__kwdefaults__ = deepcopy(incumbent.__kwdefaults__)
    result.__module__ = incumbent.__module__
    result.__qualname__ = incumbent.__qualname__
    if str(inspect.signature(result)) != str(inspect.signature(incumbent)):
        raise ValueError("INSTRUMENTED_SIGNATURE_CHANGED")
    return result
