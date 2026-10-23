"""Default-OFF K117 adapter; no transport, collector, or order authority.

The exact frozen OHLC execution profile rejects late observations. B's quote
execution cannot silently replace it. Real activation remains blocked by the
recorded PREAUTO/admission gate. Explicit development observation is separate
from synthetic fixtures and confers no formal prospective credit.
"""
from __future__ import annotations
import argparse
import ast
from copy import deepcopy
from datetime import datetime
import fcntl
import hashlib
import importlib.abc
import json
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
IDENTITY = 'scalp7_k126_veto_objective_completed_fresh_touch_v1'
FINAL = 'ef16489a81dbd2fcd74af60fcba08515da8e22f0'
TF = 1_800_000
FORMAL_GATE = 'ISSUE1414_PREAUTO_CONTRACT_NOT_VERIFIED'
SCHEMA = 'k117.prospective.adapter.v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def pins():
    data = json.loads((HERE / 'SOURCE_PINS.json').read_bytes())
    if data['identity'] != IDENTITY or data['final_freeze'] != FINAL:
        raise ValueError('IDENTITY_PIN_CHANGED')
    for name, item in data['frozen'].items():
        if hashlib.sha256((HERE/'frozen'/name).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('FROZEN_SOURCE_CHANGED:' + name)
    for name, expected in data['repo'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise ValueError('DEPENDENCY_CHANGED:' + name)
    return data


def extracted(name, selected, scope):
    """Compile only named AST definitions from byte-exact frozen evidence.

    Never execute legacy absolute-path imports, evaluation drivers or CLI code.
    Function/class bodies are unmodified and their whole files are hash checked.
    """
    tree = ast.parse((HERE/'frozen'/name).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in selected]
    if {n.name for n in nodes} != set(selected):
        raise ValueError('FROZEN_DEFINITION_MISSING')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), name, 'exec'), scope)
    return scope


def dependencies():
    data = pins()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import pandas as pd
    from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
    from backend.research.rebuild import scalp7_execution_v2 as execution
    from backend.research.rebuild import scalp7_observed_paper_v3 as paper
    from backend.research.rebuild import scalp7_rolling_context_v2 as context
    from backend.research.rebuild.scalp7_fresh_forward_v2 import bind_frozen_context
    from backend.research.rebuild.economic7_canonical_history_v1 import atomic_json
    from ops import scalp7_dual_native_funnel_v1 as native
    from research.campaigns.scalp7_20261013.dual_streak_v1.streak_successor_policies import RejectedHGEventReset
    objective = extracted('objective_lifetime.py', ['ObjectiveLifetime'], {
        'math': math, 'KNOWN_INELIGIBLE': frozenset({'TREND_COHERENT','COMPRESSION','VOL_EXPANSION_MIXED','RANGE_MIXED'})})['ObjectiveLifetime']
    timeout = extracted('winner_timeout_comparison.py', ['_continuation_callback'], {'positive':positive,'math':math})['_continuation_callback']
    h = SimpleNamespace(timeout=SimpleNamespace(_continuation_callback=timeout),
                        key=lambda s:(str(s['symbol']),int(s['side']),int(s['signal_ts_ms'])))
    structural = extracted('structural_failure.py', ['ExitComparison'], {
        'h':h, 'math':math, 'REASON':'K126_PULLBACK_STRUCTURE_FAILURE_NEXT_OPEN'})['ExitComparison']
    carry = extracted('run_paired.py', ['carry_scenario'], {})['carry_scenario']
    helpers = extracted('orderless_signals.py', ['verify_fit','bind_causal_context','_hg_dump','_hg_load','_prefix_hash'], {
        'positive':positive,'context':context,'bind_frozen_context':bind_frozen_context,
        'math':math,'_digest':digest,'asdict':__import__('dataclasses').asdict,
        'SOURCE_COLUMNS':('open_ts_ms','close_ts_ms','available_ts_ms','segment_id','open','high','low','close'), 'json':json})
    return SimpleNamespace(pd=pd, positive=positive, execution=execution, paper=paper,
        context=context, atomic=atomic_json, native=native, reset=RejectedHGEventReset,
        objective=objective, structural=structural, carry=carry, helpers=helpers, manifest=data)


class NoOrderImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        low = fullname.lower()
        if any(x in low for x in ('ccxt','order_client','order_router','execution_client','bingx_client','binance.client','backend.production')):
            raise ValueError('ORDER_CLIENT_IMPORT_BLOCKED:' + fullname)
        return None


def install_boundary():
    # Reuse B's credential/public endpoint audit then narrow this code-only lane
    # to zero network and zero process-spawning. No privileged data is loaded.
    pins()
    import urllib.parse
    scope = extracted('orderless_shadow.py', ['install_audit_boundary'],
                      {'Path':Path,'os':os,'sys':sys,'urllib':__import__('urllib'),'ENDPOINTS':set()})
    counts = scope['install_audit_boundary']()
    sys.meta_path.insert(0, NoOrderImports())
    def audit(event, args):
        if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system','os.exec','os.posix_spawn'}:
            counts['blocked_calls'] += 1
            raise ValueError('CODE_ONLY_EXTERNAL_IO_BLOCKED')
        if event == 'open' and isinstance(args[0],(str,bytes)):
            p = Path(os.fsdecode(args[0]))
            if p.name in {'credentials','credentials.json','id_rsa','id_ed25519'}:
                counts['blocked_calls'] += 1
                raise ValueError('CREDENTIAL_FILE_BLOCKED')
    sys.addaudithook(audit)
    return counts


def _finite(v):
    if isinstance(v,bool) or not math.isfinite(float(v)):
        raise ValueError('FINITE_NUMBER_REQUIRED')
    return float(v)


def check_cost(cost, asof, *, allow_fixture=True):
    if not isinstance(cost,dict) or not cost.get('source_sha256') or len(cost['source_sha256']) != 64:
        raise ValueError('COST_SOURCE_UNBOUND')
    if int(cost['available_ts_ms']) > asof:
        raise ValueError('COST_NOT_AVAILABLE')
    for key in ('fee_bps','funding_bps','slippage_bps'):
        if cost.get(key) is None:
            raise ValueError('COST_UNAVAILABLE:' + key)
        _finite(cost[key])
    if cost['fee_bps'] < 0 or cost['slippage_bps'] < 0:
        raise ValueError('NEGATIVE_FEE_OR_SLIPPAGE')
    if cost.get('kind') not in {'FIXTURE_ONLY','EXPLICIT_PROSPECTIVE_COST_MODEL'}:
        raise ValueError('COST_MODEL_UNBOUND')
    if not allow_fixture and cost['kind']=='FIXTURE_ONLY':
        raise ValueError('FIXTURE_COST_FOR_REAL_OBSERVATION_FORBIDDEN')
    return sum(float(cost[k]) for k in ('fee_bps','funding_bps','slippage_bps'))


class Adapter:
    def __init__(self, *, enabled=False, fixture=False, development=False, state=None, started_at_ms=None):
        if type(enabled) is not bool or not enabled:
            raise ValueError('DEFAULT_OFF')
        if type(fixture) is not bool or type(development) is not bool or (fixture and development):
            raise ValueError('EXPLICIT_SINGLE_OBSERVATION_MODE_REQUIRED')
        if not fixture and not development:
            raise ValueError('SHADOW_READY_HOLD:' + FORMAL_GATE)
        self.d = dependencies()
        self.freeze_ms = int(datetime.fromisoformat(self.d.manifest['freeze_at_utc']).timestamp()*1000)
        start = self.freeze_ms if started_at_ms is None else int(started_at_ms)
        if start < self.freeze_ms:
            raise ValueError('PRE_FREEZE_START')
        binding = digest({'pins':self.d.manifest,'adapter_sha':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
        self.state = deepcopy(state) if state is not None else {
            'schema':SCHEMA,'identity':IDENTITY,'final_freeze':FINAL,'binding':binding,
            'fixture':fixture,'development_observation':development,
            'mode':'DEVELOPMENT_OBSERVATION' if development else 'SYNTHETIC_FIXTURE',
            'formal_gate':FORMAL_GATE,'fresh_start_ms':start,'signals':{},'pending':{},'positions':{},
            'fit_sha256':None,'frozen_costs':{},
            'trades':[],'events':[],'NAV':None,'actual_funding_verified':False,
            'order_calls':0,'credential_file_reads':0,'formal_fresh_credit':False}
        if (self.state.get('schema')!=SCHEMA or self.state.get('identity')!=IDENTITY
            or self.state.get('final_freeze')!=FINAL or self.state.get('binding')!=binding
            or self.state.get('fixture') is not fixture
            or self.state.get('development_observation') is not development
            or self.state.get('formal_fresh_credit') is not False
            or self.state.get('mode')!=('DEVELOPMENT_OBSERVATION' if development else 'SYNTHETIC_FIXTURE')):
            raise ValueError('RUNTIME_IDENTITY_OR_CODE_MISMATCH')
        self._verify_events()

    def _verify_events(self):
        previous = None
        for event in self.state['events']:
            body = dict(event); claimed = body.pop('event_sha256')
            if body['previous'] != previous or claimed != digest(body):
                raise ValueError('ADD_ONLY_LEDGER_HASH_MISMATCH')
            previous = claimed

    def log(self, kind, body):
        event={'seq':len(self.state['events']),'kind':kind,'body':deepcopy(body),
               'previous':self.state['events'][-1]['event_sha256'] if self.state['events'] else None}
        event['event_sha256']=digest(event);self.state['events'].append(event)

    def on_bar(self, *, symbol, frame, asof_ms, source, fit, frozen_cost_bps):
        before=deepcopy(self.state)
        try:
            return self._bar(symbol,frame,int(asof_ms),source,fit,float(frozen_cost_bps))
        except Exception as exc:
            self.state=before
            self.log('HOLD',{'symbol':symbol,'reason':str(exc),'asof_ms':int(asof_ms)})
            return {'status':'UNKNOWN','action':'hold','reason':str(exc),'signal':None}

    def _bar(self,symbol,frame,asof,source,fit,cost):
        d=self.d
        if symbol not in d.context.SYMBOLS: raise ValueError('SYMBOL_UNBOUND')
        if source.get('volume_units') not in {'BASE_ASSET','FIXED_CONTRACT'}:
            raise ValueError('VOLUME_UNIT_UNKNOWN')
        if not source.get('identity_sha256') or len(source['identity_sha256'])!=64:
            raise ValueError('SOURCE_IDENTITY_UNBOUND')
        if source.get('synthetic_fill') is not False: raise ValueError('SYNTHETIC_SOURCE_FORBIDDEN')
        if not source.get('stale_authority') or int(source.get('stale_ms',0))<=0:
            raise ValueError('STALE_THRESHOLD_AUTHORITY_MISSING')
        if source.get('higher_timeframe_complete') is not True:
            raise ValueError('INCOMPLETE_HIGHER_TIMEFRAME')
        checked=d.positive._validated(frame)
        d.execution._frame_records(checked,30)
        if checked.empty: raise ValueError('NO_CLOSED_BAR')
        if (checked.available_ts_ms>asof).any(): raise ValueError('UNAVAILABLE_BAR')
        last=checked.iloc[-1];opened=int(last.open_ts_ms);closed=int(last.close_ts_ms)
        if closed<self.state['fresh_start_ms'] or asof<closed:raise ValueError('PRE_START_OR_INCOMPLETE_BAR')
        if asof-int(last.available_ts_ms)>int(source['stale_ms']):raise ValueError('STALE_SOURCE')
        saved=self.state['signals'].get(symbol)
        if saved:
            if asof < saved['last_asof']:raise ValueError('DECISION_CLOCK_REVERSED')
            if source['identity_sha256']!=saved['source_identity']:raise ValueError('SOURCE_IDENTITY_CHANGED')
            if digest(source)!=saved['source_guard_sha256']:raise ValueError('SOURCE_GUARD_CHANGED')
            prior=int(saved['last_open'])
            hist=checked.loc[checked.open_ts_ms<=prior]
            if d.helpers['_prefix_hash'](hist)!=saved['prefix_hash']:raise ValueError('HISTORY_CHANGED')
            if opened==prior:return {'status':'DUPLICATE','signal':None,'action':'hold'}
            if opened!=prior+TF or str(last.segment_id)!=saved['segment']:raise ValueError('GAP_OR_REORDERED_BAR')
            if symbol in self.state['pending']:raise ValueError('UNRESOLVED_PRIOR_ENTRY_DECISION')
        d.helpers['verify_fit'](fit,closed)
        if self.state['fit_sha256'] not in (None,fit['sha256']):raise ValueError('FROZEN_FIT_CHANGED')
        if symbol in self.state['frozen_costs'] and self.state['frozen_costs'][symbol]!=cost:
            raise ValueError('FROZEN_COST_CHANGED')
        if last.get('regime_spec_sha256')!=fit['sha256']:raise ValueError('CONTEXT_UNBOUND')
        if not math.isfinite(cost) or cost<=0:raise ValueError('FROZEN_COST_UNBOUND')
        self.state['fit_sha256']=fit['sha256'];self.state['frozen_costs'][symbol]=cost
        enriched=d.positive.enriched_segments(checked)[-1];rows=enriched.to_dict('records');i=len(rows)-1
        row=rows[-1];prev=rows[-2] if i else row
        regime,available=d.positive._regime(row,None)
        if regime not in {'PANIC_DISPERSION','TREND_DISPERSED','TREND_COHERENT',
                          'COMPRESSION','VOL_EXPANSION_MIXED','RANGE_MIXED'}:
            raise ValueError('CAUSAL_CONTEXT_UNBOUND')
        hg=d.helpers['_hg_load'](saved['hg']) if saved else d.positive.HolyGrailState()
        objective=d.objective([])
        unknown=bool(saved['bootstrap_unknown']) if saved else False
        if saved: objective.__dict__.update(deepcopy(saved['objective']))
        if saved is None:
            # Indicator context is reusable; historical admission/positions are not.
            for j in range(121,i):
                raw_before=d.helpers['_hg_dump'](hg)
                event=d.positive._hg_event(hg,rows[j],rows[j-1])
                objective.after_native(raw_before,hg,event,rows[j],symbol)
            unknown=hg.side!=0
        raw_before=d.helpers['_hg_dump'](hg)
        event=d.positive._hg_event(hg,row,prev) if i>=121 else None
        if unknown and (hg.side==0 or hg.side!=raw_before['side']):
            unknown=False;objective.clear()
        if objective.after_native(raw_before,hg,event,row,symbol):event=None
        result={'status':'NO_SIGNAL','signal':None,'action':'hold','reason':'FROZEN_NATIVE_CONDITIONS_NOT_MET'}
        stamp=max(int(row['feature_available_ts_ms']),int(available))
        if i<121 or unknown:
            result.update(status='UNKNOWN',reason='WARMUP_OR_HISTORICAL_ADMISSION_UNKNOWN')
        elif event is not None:
            hg.episode_traded=False
            if regime not in {'PANIC_DISPERSION','TREND_DISPERSED'}:
                objective.rejected(hg,row,symbol,stamp,regime)
                if regime in {'UNBOUND','NO_CONTEXT'}:result.update(status='UNKNOWN',reason='CAUSAL_CONTEXT_UNBOUND')
            else:
                sig=d.native._keltner_parent_signal(symbol,row,int(event[0]),float(event[1]),regime,int(available),cost)
                sig['identity']=IDENTITY
                sig['meta']['lifecycle_adapter_parent_identity']=d.positive.KELTNER_PARENT
                sig['max_hold_bars']=50
                d.execution.validate_signal(sig)
                self.state['pending'][symbol]={'signal':sig,'decision_ts_ms':asof,'source_bar':dict(row),'cost_bps':cost}
                result.update(status='SIGNAL',signal=deepcopy(sig),reason='FROZEN_K117_NATIVE_SIGNAL')
        self.state['signals'][symbol]={'last_open':opened,'segment':str(last.segment_id),
            'last_asof':asof,
            'source_guard_sha256':digest(source),'source_stale_ms':int(source['stale_ms']),
            'source_identity':source['identity_sha256'],'prefix_hash':d.helpers['_prefix_hash'](checked),
            'hg':d.helpers['_hg_dump'](hg),'objective':deepcopy(objective.__dict__),'bootstrap_unknown':unknown}
        self.log('BAR',{'symbol':symbol,'close_ts_ms':closed,'available_ts_ms':int(row['available_ts_ms']),
                        'decision_ts_ms':asof,'status':result['status'],'signal':result['signal']})
        return result

    def entry_open(self, *, symbol, opened, cost_model, asof_ms):
        """Admit only an actually observed exact next open; late data stays unknown.

        This is deliberately stricter than B's post-decision quote profile. Never
        pretend a later quote was the past next-open price of the frozen policy.
        """
        item=self.state['pending'].get(symbol)
        if not item:raise ValueError('NO_PENDING_SIGNAL')
        sig=item['signal'];expected=int(sig['signal_open_ts_ms'])+TF
        if (opened.get('evidence_kind')!='OBSERVED_OPEN_EVENT' or not opened.get('receipt_sha256')
            or opened['source_ts_ms']!=expected or opened['received_at_ms']!=expected
            or int(asof_ms)!=expected or item['decision_ts_ms']>expected
            or int(sig['signal_ts_ms'])>expected):
            self.log('HOLD',{'symbol':symbol,'reason':'LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL'})
            return {'status':'UNKNOWN','reason':'LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL'}
        total=check_cost(cost_model,int(asof_ms),allow_fixture=self.state['fixture'])
        px=_finite(opened['price']);native=deepcopy(sig);native['identity']=self.d.positive.KELTNER_PARENT
        self.d.execution.validate_signal(native)
        update=self.d.positive.entry_update(native,px)
        reason='POSITION_ALREADY_OWNED' if symbol in self.state['positions'] else update.get('reason') if update.get('reject') else None
        hg=self.d.helpers['_hg_load'](self.state['signals'][symbol]['hg'])
        policy=self.d.reset();policy.generated(int(sig['signal_ts_ms']))
        policy.decided(hg,accepted=reason is None,decision_ts_ms=int(asof_ms))
        self.state['signals'][symbol]['hg']=self.d.helpers['_hg_dump'](hg)
        if reason:
            del self.state['pending'][symbol];self.log('REJECTED',{'symbol':symbol,'reason':reason});return {'status':'REJECTED','reason':reason}
        self.state['positions'][symbol]={**deepcopy(item),'open_event':deepcopy(opened),
            'cost_model':deepcopy(cost_model),'modeled_cost_bps':total,'last_frame':None,
            'unresolved':True,'realized_net_bps':None,'unrealized_bps':None}
        del self.state['pending'][symbol]
        self.log('OPEN',{'symbol':symbol,'open_event':opened,'signal':sig})
        return {'status':'OPEN','NAV':None}

    def advance_position(self, *, symbol, frame, asof_ms):
        """Reuse the pinned engine on only the observed prefix of an admitted trade.

        It cannot create a past admission. Source gaps retain ownership; callbacks
        and fills, including partial/BE/runner/structural exits, are the originals.
        """
        item=self.state['positions'][symbol]
        if (frame.available_ts_ms>int(asof_ms)).any():raise ValueError('FUTURE_POSITION_BAR')
        guard=self.state['signals'][symbol].get('source_stale_ms')
        if guard is None:raise ValueError('POSITION_STALE_AUTHORITY_MISSING')
        if int(asof_ms)-int(frame.iloc[-1].available_ts_ms)>guard:raise ValueError('STALE_POSITION_SOURCE')
        records,index=self.d.execution._frame_records(frame,30)
        sig=deepcopy(item['signal']);sig['identity']=self.d.positive.KELTNER_PARENT
        entry_index=index.get(int(item['open_event']['source_ts_ms']))
        if entry_index is None:raise ValueError('OBSERVED_ENTRY_BAR_MISSING')
        if float(records[entry_index]['open'])!=float(item['open_event']['price']):raise ValueError('ENTRY_OPEN_EVIDENCE_CHANGED')
        prior=item.get('last_frame')
        if prior:
            if int(asof_ms)<prior['asof_ms']:raise ValueError('POSITION_CLOCK_REVERSED')
            old=frame.loc[frame.close_ts_ms<=prior['last_close']]
            if digest(json.loads(old.to_json(orient='records')))!=prior['hash']:raise ValueError('POSITION_HISTORY_CHANGED')
            if int(frame.iloc[-1].close_ts_ms)==prior['last_close']:
                return {'status':'DUPLICATE','NAV':None}
        else:
            if int(records[entry_index]['close_ts_ms'])>asof_ms:raise ValueError('INCOMPLETE_POSITION_BAR')
        source=records[index[int(sig['signal_open_ts_ms'])]]
        callback=self.d.structural(True).callback(sig,source,[])
        trade,unresolved,until,reason=self.d.execution._single(sig,frame,records,index,item['cost_bps'],callback,self.d.positive.entry_update)
        if reason:raise ValueError('FROZEN_ENTRY_DISAGREEMENT:'+reason)
        if trade:
            carry=0.;carry_detail={'additional_events':0}
            if int(trade['exit_ts_ms'])-int(trade['entry_ts_ms'])>25*TF:
                base_sig=deepcopy(sig);base_sig['max_hold_bars']=25
                base,op,_,why=self.d.execution._single(base_sig,frame,records,index,item['cost_bps'],self.d.positive.exit_update,self.d.positive.entry_update)
                if base is None or op or why:raise ValueError('CARRY_REFERENCE_UNKNOWN')
                snap=json.loads((ROOT/'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_bytes())
                carry,carry_detail=self.d.carry(base,trade,snap['snapshots'][symbol])
                if carry is None:raise ValueError('CARRY_CLOCK_UNBOUND_NOT_ZERO')
            trade['identity']=IDENTITY;trade['signal']['identity']=IDENTITY
            trade['reference_cost_bps']=trade['cost_bps']+carry
            trade['cost_bps']=trade['reference_cost_bps'];trade['net_bps']=trade['gross_bps']-trade['cost_bps']
            trade['net_cost2x_bps']=trade['gross_bps']-2*trade['cost_bps']
            trade['carry_scenario']=carry_detail
            trade['cost_kind']='FROZEN_REFERENCE_PLUS_8H_RESERVE_SCENARIO_NOT_ACTUAL_FUNDING'
            trade['prospective_modeled_cost_bps']=item['modeled_cost_bps']
            trade['prospective_net_bps']=None
            trade['prospective_cost_state']='HOLD:FULL_HOLDING_PERIOD_FUNDING_LINEAGE_NOT_VERIFIED'
            trade['actual_funding_verified']=False
            trade['NAV']=None;trade['fixture']=self.state['fixture']
            trade['development_observation']=self.state['development_observation'];trade['formal_fresh_credit']=False
            self.state['trades'].append(trade);del self.state['positions'][symbol];self.log('CLOSED',trade)
            return {'status':'CLOSED','trade':trade}
        item['position']=deepcopy(unresolved);item['unresolved']=True
        item['last_frame']={'last_close':int(frame.iloc[-1].close_ts_ms),'hash':digest(json.loads(frame.to_json(orient='records'))),'asof_ms':int(asof_ms)}
        self.log('UNRESOLVED',{'symbol':symbol,'until':until,'position':unresolved})
        return {'status':'UNRESOLVED','NAV':None}


class FixtureJournal:
    """One atomic state plus add-only event hashes. Never opens a B runtime path."""
    def __init__(self,path):
        self.path=Path(path).resolve()
        if any('work_b_orderless' in part for part in self.path.parts):raise ValueError('ACTIVE_B_PATH_FORBIDDEN')
        self.path.mkdir(parents=True,exist_ok=True)
        self.lock=(self.path/'writer.lock').open('a+b')
        try:fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close();raise ValueError('WRITER_LOCK_COLLISION')
    def load(self):
        p=self.path/'STATE.json'
        if not p.exists():return None
        raw=json.loads(p.read_bytes());h=raw.pop('state_sha256')
        if digest(raw)!=h:raise ValueError('STATE_HASH_MISMATCH')
        return raw
    def commit(self,state):
        old=self.load()
        if old and state['events'][:len(old['events'])]!=old['events']:raise ValueError('LEDGER_NOT_ADD_ONLY')
        dependencies().atomic(self.path/'STATE.json',{**state,'state_sha256':digest(state)})
    def close(self):self.lock.close()


def preflight(source=None,b_pointer=None):
    manifest=pins(); blockers=[FORMAL_GATE]; evidence={}
    if b_pointer:
        p=json.loads(Path(b_pointer).read_bytes());pid=int(p['pid']);alive=Path('/proc',str(pid)).exists()
        evidence['B']={'pid':pid,'alive':alive,'out':p['out']}
        if alive:blockers.append('EXISTING_B_WRITER_ACTIVE')
    if source:
        path=Path(source);identity=(path/'IDENTITY.json').read_bytes();cursor=json.loads((path/'CURSOR.json').read_bytes());j=json.loads(identity)
        evidence['source']={'identity_sha256':hashlib.sha256(identity).hexdigest(),'volume_units':j.get('volume_units')}
        if cursor.get('identity_sha256')!=hashlib.sha256(identity).hexdigest():blockers.append('SOURCE_IDENTITY_MISMATCH')
        if j.get('volume_units') not in {'BASE_ASSET','FIXED_CONTRACT'}:blockers.append('VOLUME_UNIT_UNKNOWN')
    blockers.extend(['K117_IDENTITY_ADMISSION_NOT_VERIFIED','EXACT_NEXT_OPEN_PROSPECTIVE_CLOCK_NOT_VERIFIED','PROSPECTIVE_COST_FUNDING_LINEAGE_NOT_VERIFIED'])
    return {'state':'SHADOW_READY_HOLD:'+blockers[0],'identity':IDENTITY,'default_off':True,
            'source_binding_sha256':digest(manifest),'adapter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'formal_active':False,'code_only':True,'development_observation_available':True,
            'blockers':blockers,'evidence':evidence,'orders':0}


def main():
    p=argparse.ArgumentParser();p.add_argument('--preflight',action='store_true');p.add_argument('--source');p.add_argument('--b-pointer');p.add_argument('--enable',action='store_true')
    args=p.parse_args()
    allowed={'PATH','LANG','LC_ALL','TZ','SYSTEMROOT'}
    env={k:v for k,v in os.environ.items() if k in allowed};os.environ.clear();os.environ.update(env)
    install_boundary()
    if args.enable:raise SystemExit('HOLD:'+FORMAL_GATE)
    print(json.dumps(preflight(args.source,args.b_pointer),sort_keys=True))

if __name__=='__main__':main()
