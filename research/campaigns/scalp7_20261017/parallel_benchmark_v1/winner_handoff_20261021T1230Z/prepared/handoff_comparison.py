"""One isolated chronological child: yield an extended position to a fresh native signal.
No root modifications, no extra simultaneous position, no final-PnL selection.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib, inspect, sys
BASE=Path('/home/z/z/runtime/k_winner_timeout_20261021T1142Z')
REPO=Path('/home/z/worktrees/zel-work-b-retry-6f7a4217-20261020')
sys.path[:0]=[str(REPO),str(BASE)]
from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from ops import scalp7_keltner_fresh_touch_successor_v1 as k
import winner_timeout_comparison as timeout
START=1768262400000
TF=1800000

def key(t):return (str(t['symbol']),int(t['side']),int(t['signal_ts_ms']))

class Handoff:
    def __init__(self, enabled=True):
        self.enabled=enabled;self.events=[];self.decisions=[]
    def single(self,signal,frame,records,index,cost,callback,entry_update=None):
        if int(signal['signal_ts_ms'])<START:
            return execution._single(signal,frame,records,index,cost,callback,entry_update)
        changed=deepcopy(signal);changed['max_hold_bars']=50;trace=[]
        result=execution._single(changed,frame,records,index,cost,timeout._continuation_callback(trace),entry_update)
        self.decisions.extend({'trade_key':list(key(signal)),**v} for v in trace)
        return result
    def shortened(self,held,new_signal,frame,records,index,cost):
        """Only the current signal, its next open, and the old completed prefix decide.
        The engine's precomputed old final PnL/MFE are not eligibility features.
        """
        if not self.enabled or int(new_signal['signal_ts_ms'])<START:return None
        old=held['signal'];stamp=int(new_signal['signal_ts_ms'])
        if int(old['side'])!=int(new_signal['side']):return None
        entry=held['entry_ts_ms']
        if stamp-entry<25*TF or stamp-entry>=50*TF:return None
        allowed,decision,gate_reason=k.native._entry_gate(new_signal,{new_signal['symbol']:frame})
        if not allowed or decision is None or int(decision)!=stamp:return None
        trace=[];observed=[];extended=timeout._continuation_callback(trace)
        def callback(position,bar,history):
            update=extended(position,bar,history)
            if int(bar['available_ts_ms'])!=stamp or update.get('exit_next_open'):return update
            if not trace or not trace[0]['extend'] or int(position['hold_bars'])<25:return update
            observed.append({'observed_at_ms':stamp,'hold_bars':int(position['hold_bars']),
                'mfe_R_observed':float(position['mfe_R']),'remaining':float(position['remaining']),
                'stop_price':float(position['stop_price']),'entry_price':float(position['entry_price'])})
            return {**update,'exit_next_open':True,'reason':'EXTENDED_FRESH_SIGNAL_HANDOFF_NEXT_OPEN'}
        changed=deepcopy(old);changed['max_hold_bars']=50
        trade,unresolved,until,reason=execution._single(changed,frame,records,index,cost,callback,positive.entry_update)
        if not observed:return None  # a prior protective stop/time exit dominates
        if reason or unresolved or trade is None:raise ValueError('HANDOFF_UNRESOLVED_NO_SYNTHETIC_FILL')
        if trade['reason']!='EXTENDED_FRESH_SIGNAL_HANDOFF_NEXT_OPEN' or int(trade['exit_ts_ms'])!=int(decision) or int(until)!=int(decision):
            raise ValueError('HANDOFF_FILL_TIME_MISMATCH')
        return trade,until,observed[-1]
    def switch(self,held,new_signal,frame,records,index,cost,window,rows,unresolved,boundary):
        if held is None:return None
        changed=self.shortened(held,new_signal,frame,records,index,cost)
        if changed is None:return None
        shortened,until,snapshot=changed
        oldkey=key(held['signal']);matches=[]
        for collection in (rows,unresolved,boundary):
            for i,t in enumerate(collection):
                tk=key(t if 'signal_ts_ms' in t else t['position']['signal'])
                if t.get('window_label')==str(window['label']) and tk==oldkey:matches.append((collection,i))
        if len(matches)!=1:raise ValueError('HANDOFF_PREVIOUS_LEDGER_NOT_UNIQUE')
        collection,index_old=matches[0];collection.pop(index_old)
        row=k._relabel(shortened);row['window_label']=str(window['label']);row['partition']=str(window['partition'])
        if row['outcome_available_ts_ms']>=int(window['end_ms']):raise ValueError('HANDOFF_AFTER_WINDOW_END')
        rows.append(row)
        self.events.append({'previous_key':list(oldkey),'new_signal_key':list(key(new_signal)),
            'decision_available_ts_ms':int(until),'old_close_ts_ms':shortened['exit_ts_ms'],
            'old_close_price':shortened['exit_prices'][new_signal['symbol']],
            'observed_state':snapshot,'old_fee_model_bps':shortened['cost_bps'],
            'new_entry_must_pay_separate_full_cost':True,'simultaneous_positions':1,
            'new_full_leg_after_old_remaining_closed':True})
        return int(until)
    def build(self):
        timeout.verify_dependencies()
        raw=Path(k.__file__).read_bytes()
        if hashlib.sha256(raw).hexdigest()!='e0afbe1d76c4a3c8b4470aae82b152bd3f59676339294653719c3f3a85e2f855':raise ValueError('NATIVE_PIN_CHANGED')
        source=inspect.getsource(k._fresh_touch_successor)
        edits=[
          ('    ownership: dict[tuple[str, str], int] = {}', '    ownership: dict[tuple[str, str], int] = {}\n    held_positions: dict = {}'),
          ('                    if stamp < ownership.get(owner, -1):\n                        reason = "POSITION_ALREADY_OWNED"\n                    else:',
           '                    if stamp < ownership.get(owner, -1):\n                        hand_frame,hand_records,hand_index = prepared[(str(window["label"]),symbol)]\n                        released = _handoff.switch(held_positions.get(owner),signal,hand_frame,hand_records,hand_index,cost,window,rows,unresolved,boundary_excluded)\n                        if released is None:\n                            reason = "POSITION_ALREADY_OWNED"\n                        else:\n                            ownership[owner] = released\n                    if reason is None:'),
          ('                ownership[owner] = int(until)',
           '                ownership[owner] = int(until)\n                filled = trade if trade is not None else open_position\n                held_positions[owner] = {"signal":deepcopy(signal),"entry_ts_ms":int(filled["entry_ts_ms"])}')]
        for a,b in edits:
            if source.count(a)!=1:raise ValueError('NATIVE_INJECTION_NOT_UNIQUE')
            source=source.replace(a,b)
        scope=dict(vars(k));scope['deepcopy']=deepcopy;scope['_handoff']=self
        scope['execution']=SimpleNamespace(**{**vars(execution),'_single':self.single})
        exec(compile(source,'isolated_native_handoff.py','exec'),scope)
        return scope['_fresh_touch_successor'],source
