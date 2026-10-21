"""One disabled-by-default INTERNAL HYPOTHESIS, not a demonstrated stale-state bug.

A completed native turn with a *known* ineligible context ends its untraded
pullback lifetime. A subsequent native touch must be available strictly later.
UNBOUND/unknown context and weak trend bars do not trigger this policy. Entry,
stop geometry, callbacks, fees, and ownership remain those of the supplied
frozen incumbent. No real-price evaluation is performed by this module.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import CodeType, FunctionType
from typing import Any

IDENTITY = "scalp7_k126_known_regime_veto_fresh_touch_v1"
CLASSIFICATION = "INTERNAL_STATE_LIFETIME_HYPOTHESIS_NOT_PROVEN_BUG"
SOURCE_SHA256 = "9cab68472492d27a0a990cdce73e51ecd8009866f2ba12fc3a29b02381094252"
NATIVE_SHA256 = "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2"
KNOWN_INELIGIBLE = frozenset({
    "TREND_COHERENT", "COMPRESSION", "VOL_EXPANSION_MIXED", "RANGE_MIXED",
})


def _code_signature(code: CodeType) -> tuple[Any, ...]:
    """Ignore only source-location metadata when checking isolated native code."""
    return (
        code.co_code, code.co_names, code.co_varnames, code.co_freevars,
        code.co_cellvars, code.co_argcount, code.co_posonlyargcount,
        code.co_kwonlyargcount, code.co_flags,
        tuple(_code_signature(v) if isinstance(v, CodeType) else v for v in code.co_consts),
        getattr(code, "co_exceptiontable", b""),
    )


def build(incumbent: FunctionType, *, source_text: str, enabled: bool = False) -> FunctionType:
    """Wrap the exact latest incumbent's isolated successor, preserving its scope.

    Owner integration (after the separate source-state trace):
      control = structural_failure.ExitComparison(True).build()
      candidate = build(control,
          source_text=inspect.getsource(structural_failure.h.k._fresh_touch_successor),
          enabled=True)
    The owner's original pinned exit wrapper stays in control.__globals__.
    This function never calls the successor and never loads candles. The
    control-only origin observer must run on the incumbent first; the enabled
    candidate rejects benchmark_observations rather than emit a misleading
    pre-policy state snapshot.
    """
    if type(enabled) is not bool:
        raise ValueError("EXPLICIT_BOOLEAN_ENABLE_REQUIRED")
    if not isinstance(incumbent, FunctionType):
        raise ValueError("ISOLATED_NATIVE_FUNCTION_REQUIRED")
    if not enabled:
        return incumbent
    if hashlib.sha256(source_text.encode()).hexdigest() != SOURCE_SHA256:
        raise ValueError("FROZEN_SUCCESSOR_FUNCTION_SOURCE_CHANGED")
    scope = dict(incumbent.__globals__)
    if "positive" not in scope:
        raise ValueError("INCUMBENT_NOT_THE_PINNED_SUCCESSOR")
    positive = scope["positive"]
    if hashlib.sha256(Path(positive.__file__).read_bytes()).hexdigest() != NATIVE_SHA256:
        raise ValueError("FROZEN_POSITIVE_SOURCE_CHANGED")
    # Compile with the same annotations mode as the caller, not this file's
    # future-annotations setting. No global strategy function is monkeypatched.
    check = dict(scope)
    exec(compile(source_text, "work_c_native_verification.py", "exec", dont_inherit=True), check)
    original = check["_fresh_touch_successor"]
    if _code_signature(original.__code__) != _code_signature(incumbent.__code__):
        raise ValueError("INCUMBENT_NOT_THE_PINNED_SUCCESSOR")

    tree = ast.parse(source_text)
    native = tree.body[0]
    if not isinstance(native, ast.FunctionDef) or native.name != "_fresh_touch_successor":
        raise ValueError("FROZEN_SUCCESSOR_SHAPE_CHANGED")
    inserted = {"state": 0, "post_native": 0, "regime": 0}

    class LifetimeOnly(ast.NodeTransformer):
        def visit_Assign(self, node: ast.Assign):
            self.generic_visit(node)
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == "state":
                    inserted["state"] += 1
                    return [node, *ast.parse("_c_known_veto_ts_ms = None").body]
                if node.targets[0].id == "after":
                    inserted["post_native"] += 1
                    guard = ast.parse('''
if (_c_known_veto_ts_ms is not None and before["stage"] == 0
        and state.stage == 1 and event is None):
    if int(row["feature_available_ts_ms"]) <= _c_known_veto_ts_ms:
        state.event_reset()
    else:
        _c_known_veto_ts_ms = None
''').body
                    return [*guard, node]
            return node

        def visit_If(self, node: ast.If):
            self.generic_visit(node)
            target = ast.parse('regime not in {"PANIC_DISPERSION", "TREND_DISPERSED"}', mode="eval").body
            if ast.dump(node.test) == ast.dump(target):
                inserted["regime"] += 1
                if not isinstance(node.body[-1], ast.Continue):
                    raise ValueError("REGIME_VETO_NO_LONGER_TERMINAL")
                change = ast.parse('''
if regime in _C_KNOWN_INELIGIBLE:
    _c_known_veto_ts_ms = int(stamp)
    state.event_reset()
    if observation is not None:
        observation["admission"] = {
            "state": "REGIME_INELIGIBLE_CANDIDATE_RESET", "reason": regime,
            "decision_ts_ms": int(stamp), "state_after_policy": _state(state),
            "candidate_identity": _C_LIFETIME_IDENTITY,
        }
''').body
                node.body[-1:-1] = change
            return node

    tree = LifetimeOnly().visit(tree)
    if inserted != {"state": 1, "post_native": 1, "regime": 1}:
        raise ValueError("LIFETIME_INSERTION_NOT_UNIQUE")
    native.body[0:0] = ast.parse('''
if benchmark_observations is not None:
    raise ValueError("CANDIDATE_REQUIRES_SEPARATE_INCUMBENT_ORIGIN_TRACE")
''').body
    ast.fix_missing_locations(tree)
    scope["_C_KNOWN_INELIGIBLE"] = KNOWN_INELIGIBLE
    scope["_C_LIFETIME_IDENTITY"] = IDENTITY
    exec(compile(tree, "work_c_known_regime_veto_lifetime.py", "exec", dont_inherit=True), scope)
    candidate = scope["_fresh_touch_successor"]
    candidate.candidate_identity = IDENTITY
    candidate.candidate_classification = CLASSIFICATION
    candidate.single_changed_axis = "UNTRADED_STATE_LIFETIME_AFTER_KNOWN_REGIME_VETO"
    return candidate
