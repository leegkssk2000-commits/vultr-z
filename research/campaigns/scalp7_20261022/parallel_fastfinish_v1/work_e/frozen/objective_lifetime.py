"""One internal successor: expire a vetoed setup only after its frozen objective is reached.

The objective is the incumbent's already-available prior20 high/low at the
native EMA20 touch, not a newly optimized length or a future swing. This is
source-motivated internal logic, not a source-exact Raschke rule. No order I/O.
"""
from __future__ import annotations
import ast
import hashlib
import math
from pathlib import Path
from types import FunctionType

IDENTITY = "scalp7_k126_veto_objective_completed_fresh_touch_v1"
SOURCE_SHA256 = "9cab68472492d27a0a990cdce73e51ecd8009866f2ba12fc3a29b02381094252"
NATIVE_SHA256 = "b0919c9e3542d6d2e14ab8f545179c7bfc43d661379bc1f6d0714a6603ea9aa2"
KNOWN_INELIGIBLE = frozenset({"TREND_COHERENT", "COMPRESSION", "VOL_EXPANSION_MIXED", "RANGE_MIXED"})

class ObjectiveLifetime:
    def __init__(self, events: list[dict]):
        self.events = events
        self.last_available = None
        self.clear()

    def clear(self):
        self.side = 0
        self.target = None
        self.touch_ts = None
        self.first_hit_ts = None
        self.first_veto_ts = None

    def _expire(self, state, row, symbol, reason):
        stamp = int(row["feature_available_ts_ms"])
        if self.touch_ts is None or self.first_veto_ts is None or self.first_hit_ts is None:
            raise ValueError("OBJECTIVE_EXPIRY_EVIDENCE_MISSING")
        if max(self.touch_ts, self.first_veto_ts, self.first_hit_ts) > stamp:
            raise ValueError("OBJECTIVE_EXPIRY_BEFORE_EVIDENCE")
        self.events.append({"symbol": symbol, "side": self.side,
            "touch_ts_ms": self.touch_ts, "frozen_prior20_objective": self.target,
            "first_objective_hit_ts_ms": self.first_hit_ts,
            "first_known_veto_ts_ms": self.first_veto_ts, "expired_ts_ms": stamp,
            "reason": reason, "decision_inputs_only": True})
        # A generated-but-rejected event must not leave the episode consumed.
        state.episode_traded = False
        state.event_reset()
        self.clear()

    def after_native(self, before, state, event, row, symbol):
        """Called once after the original HG event, before the unchanged admission."""
        stamp = int(row["feature_available_ts_ms"])
        if stamp < int(row["close_ts_ms"]) or (self.last_available is not None and stamp < self.last_available):
            raise ValueError("OBJECTIVE_NONCAUSAL_CLOCK")
        self.last_available = stamp
        if not state.stage:
            self.clear()
            return False
        if before["episode_traded"] and before["side"] == state.side:
            self.clear()
            return False
        new_touch = before["stage"] == 0 or before["side"] != state.side
        if new_touch:
            if event is not None:
                raise ValueError("TOUCH_AND_TURN_SAME_NATIVE_CALL")
            self.clear()
            self.side = int(state.side)
            self.target = float(row["hi20" if self.side == 1 else "lo20"])
            self.touch_ts = stamp
            if self.side not in (-1, 1) or not math.isfinite(self.target) or self.target <= 0:
                raise ValueError("OBJECTIVE_SOURCE_NOT_BOUND")
        if self.target is None or self.side != state.side:
            raise ValueError("OBJECTIVE_NATIVE_ORIGIN_MISSING")
        extreme = float(row["high"] if self.side == 1 else row["low"])
        if not math.isfinite(extreme):
            raise ValueError("OBJECTIVE_PRICE_NOT_FINITE")
        hit = extreme >= self.target if self.side == 1 else extreme <= self.target
        if hit and self.first_hit_ts is None:
            self.first_hit_ts = stamp
        if self.first_veto_ts is not None and self.first_hit_ts is not None:
            self._expire(state, row, symbol, "PRIOR_OBJECTIVE_COMPLETE_AFTER_KNOWN_VETO")
            return True
        return False

    def rejected(self, state, row, symbol, stamp, regime):
        if regime not in KNOWN_INELIGIBLE:
            return False
        if self.target is None or not state.stage:
            raise ValueError("VETO_WITHOUT_NATIVE_TOUCH_ORIGIN")
        if int(stamp) > int(row["feature_available_ts_ms"]):
            raise ValueError("VETO_REGIME_AVAILABLE_AFTER_POLICY_CLOCK")
        if self.first_veto_ts is None:
            self.first_veto_ts = int(stamp)
        if self.first_hit_ts is not None:
            self._expire(state, row, symbol, "KNOWN_VETO_WITH_OBJECTIVE_ALREADY_COMPLETE")
            return True
        return False


def build(incumbent: FunctionType, *, source_text: str, enabled: bool = False):
    if type(enabled) is not bool:
        raise ValueError("EXPLICIT_BOOLEAN_ENABLE_REQUIRED")
    if not enabled:
        return incumbent
    if hashlib.sha256(source_text.encode()).hexdigest() != SOURCE_SHA256:
        raise ValueError("FROZEN_SUCCESSOR_SOURCE_CHANGED")
    from state_lifetime_adapter import _code_signature
    scope = dict(incumbent.__globals__)
    if hashlib.sha256(Path(scope["positive"].__file__).read_bytes()).hexdigest() != NATIVE_SHA256:
        raise ValueError("FROZEN_NATIVE_CHANGED")
    check = dict(scope)
    exec(compile(source_text, "objective_native_verification.py", "exec", dont_inherit=True), check)
    if _code_signature(check["_fresh_touch_successor"].__code__) != _code_signature(incumbent.__code__):
        raise ValueError("INCUMBENT_NOT_EXACT")
    tree = ast.parse(source_text)
    counts = {"init": 0, "after": 0, "veto": 0}
    class Patch(ast.NodeTransformer):
        def visit_Assign(self, node):
            self.generic_visit(node)
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == "state":
                    counts["init"] += 1
                    return [node, *ast.parse("_objective = _ObjectiveLifetime(_objective_events)").body]
                if node.targets[0].id == "after":
                    counts["after"] += 1
                    return [*ast.parse("if _objective.after_native(before, state, event, row, symbol):\n    event = None").body, node]
            return node
        def visit_If(self, node):
            self.generic_visit(node)
            target = ast.parse('regime not in {"PANIC_DISPERSION", "TREND_DISPERSED"}', mode="eval").body
            if ast.dump(node.test) == ast.dump(target):
                counts["veto"] += 1
                if not isinstance(node.body[-1], ast.Continue):
                    raise ValueError("NATIVE_REGIME_BRANCH_CHANGED")
                node.body[-1:-1] = ast.parse("_objective.rejected(state, row, symbol, stamp, regime)").body
            return node
    tree = Patch().visit(tree)
    if counts != {"init": 1, "after": 1, "veto": 1}:
        raise ValueError("NONUNIQUE_POLICY_INSERTION")
    tree.body[0].body[0:0] = ast.parse('if benchmark_observations is not None:\n    raise ValueError("USE_SAVED_INCUMBENT_TRACE_NOT_POLICY_OBSERVER")').body
    ast.fix_missing_locations(tree)
    events = []
    scope.update(_ObjectiveLifetime=ObjectiveLifetime, _objective_events=events)
    exec(compile(tree, "objective_completed_lifetime.py", "exec", dont_inherit=True), scope)
    candidate = scope["_fresh_touch_successor"]
    candidate.candidate_identity = IDENTITY
    candidate.events = events
    candidate.single_changed_axis = "VETO_EXPIRY_ONLY_WHEN_ORIGINAL_PRIOR20_OBJECTIVE_COMPLETE"
    return candidate
