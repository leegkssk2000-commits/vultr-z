"""One exit-only hypothesis on K126; source-motivated, not an author-exact rule.
A post-entry completed close outside the adverse end of the original reversal
signal bar invalidates that bar-level trigger. The initial protective stop and
all existing exits have priority. No fitted distance, time, or MFE threshold.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib, inspect, math, sys
sys.path.insert(0, '/home/z/z/runtime/k_winner_handoff_context_order_attempt2_20261021')
import handoff_comparison as h
IDENTITY='scalp7_k126_reversal_bar_failure_next_open_v1'
REASON='K126_REVERSAL_BAR_FAILURE_NEXT_OPEN'

def crossed(side, close, low, high):
    if side not in (-1,1): raise ValueError('INVALID_SIDE')
    if not all(math.isfinite(float(x)) for x in (close,low,high)): raise ValueError('NONFINITE_LEVEL')
    if low>high: raise ValueError('INVALID_SIGNAL_RANGE')
    return close<low if side==1 else close>high

class ExitComparison:
    def __init__(self, enabled):
        self.enabled=bool(enabled)
        self.events=[]
        self.timeout_decisions=[]
    def callback(self,signal,source_bar,trace):
        extended=h.timeout._continuation_callback(trace)
        found=False
        def cb(position,bar,history):
            nonlocal found
            update=extended(position,bar,history)
            if int(bar['open_ts_ms'])<int(position['entry_ts_ms']): raise ValueError('PREENTRY_EXIT')
            if int(source_bar['available_ts_ms'])>int(position['entry_ts_ms']): raise ValueError('SIGNAL_NOT_KNOWN_AT_ENTRY')
            bad=crossed(int(position['side']),float(bar['close']),float(source_bar['low']),float(source_bar['high']))
            if bad and not found:
                found=True
                event={'trade_key':list(h.key(signal)), 'signal_open_ts_ms':int(source_bar['open_ts_ms']),
                  'signal_available_ts_ms':int(source_bar['available_ts_ms']), 'signal_low':float(source_bar['low']),
                  'signal_high':float(source_bar['high']), 'first_failure_available_ts_ms':int(bar['available_ts_ms']),
                  'first_failure_close_ts_ms':int(bar['close_ts_ms']), 'failure_close':float(bar['close']),
                  'hold_bars':int(position['hold_bars']), 'observed_mfe_R':float(position['mfe_R']),
                  'remaining':float(position['remaining']), 'existing_exit_already_due':bool(update.get('exit_next_open')),
                  'existing_reason':update.get('reason'), 'rule_enabled':self.enabled,
                  'actionable':not bool(update.get('exit_next_open'))}
                self.events.append(event)
            if self.enabled and bad and not update.get('exit_next_open'):
                update={**update,'exit_next_open':True,'reason':REASON}
            return update
        return cb
    def single(self,signal,frame,records,index,cost,callback,entry_update=None):
        if int(signal['signal_ts_ms'])<h.START:
            return h.execution._single(signal,frame,records,index,cost,callback,entry_update)
        if signal['identity']!=h.positive.KELTNER_PARENT or int(signal['max_hold_bars'])!=25:
            raise ValueError('UNEXPECTED_CONTROL_SIGNAL')
        i=index.get(int(signal['signal_open_ts_ms']))
        if i is None: return h.execution._single(signal,frame,records,index,cost,callback,entry_update)
        source_bar=records[i]
        changed=deepcopy(signal);changed['max_hold_bars']=50
        trace=[]
        out=h.execution._single(changed,frame,records,index,cost,self.callback(signal,source_bar,trace),entry_update)
        self.timeout_decisions.extend({'trade_key':list(h.key(signal)),**x} for x in trace)
        return out
    def build(self):
        h.timeout.verify_dependencies()
        if hashlib.sha256(Path(h.k.__file__).read_bytes()).hexdigest()!='e0afbe1d76c4a3c8b4470aae82b152bd3f59676339294653719c3f3a85e2f855':
            raise ValueError('NATIVE_K_SOURCE_CHANGED')
        scope=dict(vars(h.k))
        scope['execution']=SimpleNamespace(**{**vars(h.execution),'_single':self.single})
        code=inspect.getsource(h.k._fresh_touch_successor)
        exec(compile(code,'isolated_k126_exit_only.py','exec'),scope)
        return scope['_fresh_touch_successor']
