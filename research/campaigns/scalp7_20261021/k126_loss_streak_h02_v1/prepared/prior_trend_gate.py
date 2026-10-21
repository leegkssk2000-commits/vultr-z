"""Research-only H02: prior rising-ADX witness before native first touch.
Original generator, native rejection reset, cost, stop and winner extension are retained.
No market API, optimizer, order client or global module mutation.
"""
from pathlib import Path
from types import SimpleNamespace
import inspect, math, sys
sys.path.insert(0, '/home/z/z/runtime/k_winner_handoff_context_order_attempt2_20261021')
import handoff_comparison as h
positive, execution, k = h.positive, h.execution, h.k
IDENTITY = 'scalp7_k126_prior_adx_rise_before_touch_v1'

class WitnessState(positive.HolyGrailState):
    def __init__(self):
        super().__init__()
        self.prior_rise_ts = None
        self.touch_ts = None
        self.touch_witness_ts = None
    def event_reset(self):
        super().event_reset()
        self.prior_rise_ts = self.touch_ts = self.touch_witness_ts = None

class PriorTrendGate:
    def __init__(self, enabled):
        self.enabled = bool(enabled)
        self.current = None
        self.events = []
        self.lifecycle = h.Handoff(False)
    def event(self, state, row, previous):
        stamp = int(row['feature_available_ts_ms'])
        prev_stamp = int(previous['feature_available_ts_ms'])
        if prev_stamp >= stamp or stamp < int(row['close_ts_ms']):
            raise ValueError('H02_CAUSAL_CLOSED_PREFIX_REQUIRED')
        before_stage = state.stage
        event = positive._hg_event(state, row, previous)
        if before_stage == 0 and state.stage == 1:
            state.touch_ts = stamp
            state.touch_witness_ts = state.prior_rise_ts
        # Qualification is observed BEFORE a later touch, never retrofitted to it.
        values = [float(row[f'g{n}']) for n in positive.LONG_GMMA]
        current_side = (1 if all(a > b for a,b in zip(values,values[1:])) and row['g60'] > previous['g60'] else
                       -1 if all(a < b for a,b in zip(values,values[1:])) and row['g60'] < previous['g60'] else 0)
        if (state.stage == 0 and not state.episode_traded and current_side != 0
                and state.side == current_side and float(row['adx14']) > 30.0
                and float(row['adx14']) > float(previous['adx14'])
                and current_side * (float(row['g20'])-float(previous['g20'])) > 0):
            state.prior_rise_ts = stamp
        if event is not None:
            witness, touch = state.touch_witness_ts, state.touch_ts
            qualified = witness is not None and touch is not None and witness < touch < stamp
            self.current = {'signal_open_ts_ms':int(row['open_ts_ms']), 'side':int(event[0]),
                            'prior_rising_adx_ts_ms':witness, 'first_native_touch_ts_ms':touch,
                            'turn_available_ts_ms':stamp, 'qualified':qualified}
        return event
    def evidence(self, symbol, row, signal, partition):
        e = self.current
        if e is None or e['signal_open_ts_ms'] != int(row['open_ts_ms']) or e['side'] != int(signal['side']):
            raise ValueError('H02_SIGNAL_WITNESS_MISMATCH')
        out = {**e, 'symbol':symbol, 'signal_ts_ms':int(signal['signal_ts_ms']), 'partition':partition,
               'source_gate_reject':self.enabled and not e['qualified']}
        self.events.append(out)
        return out
    def build(self):
        h.timeout.verify_dependencies()
        if __import__('hashlib').sha256(Path(k.__file__).read_bytes()).hexdigest() != 'e0afbe1d76c4a3c8b4470aae82b152bd3f59676339294653719c3f3a85e2f855':
            raise ValueError('NATIVE_GENERATOR_PIN_CHANGED')
        src=inspect.getsource(k._fresh_touch_successor)
        old='                if duplicate in seen:'
        new=('                source_evidence = _source_gate.evidence(symbol, row, signal, partition)\n'
             '                if _source_gate.enabled and not source_evidence["qualified"]:\n'
             '                    reason = "H02_PRIOR_ADX_RISE_NOT_BEFORE_TOUCH"\n'
             '                elif duplicate in seen:')
        if src.count(old) != 1: raise ValueError('H02_ADMISSION_INJECTION_NOT_UNIQUE')
        src=src.replace(old,new)
        scope=dict(vars(k))
        scope['_source_gate']=self
        scope['positive']=SimpleNamespace(**{**vars(positive),'HolyGrailState':WitnessState,'_hg_event':self.event})
        scope['execution']=SimpleNamespace(**{**vars(execution),'_single':self.lifecycle.single})
        exec(compile(src,'h02_isolated_native.py','exec'),scope)
        return scope['_fresh_touch_successor']
