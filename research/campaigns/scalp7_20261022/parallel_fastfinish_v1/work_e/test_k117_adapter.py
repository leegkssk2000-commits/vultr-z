"""Synthetic deterministic contract/negative tests; zero economic FULL runs."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import k117_adapter as k

D=k.dependencies()
T=((int(__import__('datetime').datetime.fromisoformat(D.manifest['freeze_at_utc']).timestamp()*1000)//k.TF)+2)*k.TF
DAY=86_400_000
END=(T//DAY-1)*DAY
FIT={'train_start_ms':END-90*DAY,'train_end_ms':END,'last_fit_observation_ms':END-DAY,
     'train_rows':90,'training_feature_sha256':'1'*64,'disp_q67':1.,'meanabs_q85':1.,'vol_q25':1.,'vol_q67':2.}
FIT['sha256']=k.digest(FIT)
SOURCE={'identity_sha256':'2'*64,'volume_units':'BASE_ASSET','synthetic_fill':False,
        'stale_ms':90000,'stale_authority':'FIXTURE_ONLY_NOT_PRODUCTION_SSOT','higher_timeframe_complete':True}
COST={'source_sha256':'3'*64,'available_ts_ms':T,'fee_bps':6.,'funding_bps':1.,'slippage_bps':3.,'kind':'FIXTURE_ONLY'}


def bars(n=124):
    rows=[]
    for i in range(n):
        t=T-(122-i)*k.TF
        rows.append({'open_ts_ms':t,'close_ts_ms':t+k.TF,'available_ts_ms':t+k.TF,'segment_id':0,
            'open':100.,'high':101.,'low':99.,'close':100.,'volume':1000.,
            'regime':'TREND_DISPERSED','regime_available_ts_ms':t+k.TF,
            'regime_fit_end_ts_ms':END,'regime_spec_sha256':FIT['sha256']})
    return D.pd.DataFrame(rows)


def model(a,f=None,**overrides):
    f=bars() if f is None else f
    args={'symbol':'BTC-USDT','frame':f,'asof_ms':int(f.iloc[-1].available_ts_ms),
          'source':SOURCE,'fit':FIT,'frozen_cost_bps':10.}
    args.update(overrides)
    return a.on_bar(**args)


def pending(a):
    row={'open_ts_ms':T,'close_ts_ms':T+k.TF,'available_ts_ms':T+k.TF,
         'feature_available_ts_ms':T+k.TF,'segment_id':0,'open':100.,'high':101.,'low':99.,'close':100.,'atr':2.}
    sig=D.native._keltner_parent_signal('BTC-USDT',row,1,99.,'TREND_DISPERSED',T+k.TF,10.)
    sig['identity']=k.IDENTITY;sig['max_hold_bars']=50
    sig['meta']['lifecycle_adapter_parent_identity']=D.positive.KELTNER_PARENT
    a.state['signals']['BTC-USDT']={'source_stale_ms':90000,'hg':D.helpers['_hg_dump'](D.positive.HolyGrailState(side=1,stage=1,episode_traded=False,pull_low=99.,pull_high=101.))}
    a.state['pending']['BTC-USDT']={'signal':sig,'decision_ts_ms':T+k.TF,'source_bar':row,'cost_bps':10.}
    event={'evidence_kind':'OBSERVED_OPEN_EVENT','receipt_sha256':'4'*64,'source_ts_ms':T+k.TF,'received_at_ms':T+k.TF,'price':100.}
    return row,event


def opened(a):
    row,event=pending(a)
    a.entry_open(symbol='BTC-USDT',opened=event,cost_model=COST,asof_ms=T+k.TF)
    return row


def position_frame(row,*prices):
    data=[{k:v for k,v in row.items() if k!='atr'}]
    for i,(o,h,l,c) in enumerate(prices,1):
        t=T+i*k.TF
        data.append({'open_ts_ms':t,'close_ts_ms':t+k.TF,'available_ts_ms':t+k.TF,'feature_available_ts_ms':t+k.TF,
                     'segment_id':0,'open':o,'high':h,'low':l,'close':c})
    return D.pd.DataFrame(data)


class Contracts(unittest.TestCase):
    def a(self):return k.Adapter(enabled=True,fixture=True)
    def test_default_off(self):
        with self.assertRaisesRegex(ValueError,'DEFAULT_OFF'):k.Adapter()
    def test_formal_gate_cannot_be_enabled(self):
        with self.assertRaisesRegex(ValueError,k.FORMAL_GATE):k.Adapter(enabled=True)
    def test_frozen_identity_pins(self):
        self.assertEqual(D.manifest['frozen']['objective_lifetime.py']['sha256'],'40659bc91044cca35ea6fc0aad383487b59ac16ec8aeb74639f8f5663e131bb7')
        self.assertEqual(D.manifest['repo']['ops/scalp7_keltner_fresh_touch_successor_v1.py'],'e0afbe1d76c4a3c8b4470aae82b152bd3f59676339294653719c3f3a85e2f855')
    def test_bar_duplicate_unchanged_hash(self):
        a=self.a();self.assertEqual(model(a)['status'],'NO_SIGNAL');before=k.digest(a.state)
        self.assertEqual(model(a)['status'],'DUPLICATE');self.assertEqual(k.digest(a.state),before)
    def test_stale_source(self):
        a=self.a();f=bars();r=model(a,f,asof_ms=int(f.iloc[-1].available_ts_ms)+90001)
        self.assertEqual(r['reason'],'STALE_SOURCE');self.assertFalse(a.state['signals'])
    def test_unavailable(self):
        a=self.a();f=bars();self.assertEqual(model(a,f,asof_ms=int(f.iloc[-1].available_ts_ms)-1)['reason'],'UNAVAILABLE_BAR')
    def test_unknown_volume(self):
        a=self.a();self.assertEqual(model(a,source={**SOURCE,'volume_units':'UNKNOWN'})['reason'],'VOLUME_UNIT_UNKNOWN')
    def test_stale_authority_missing(self):
        a=self.a();self.assertEqual(model(a,source={**SOURCE,'stale_authority':None})['reason'],'STALE_THRESHOLD_AUTHORITY_MISSING')
    def test_incomplete_higher_timeframe(self):
        self.assertEqual(model(self.a(),source={**SOURCE,'higher_timeframe_complete':False})['reason'],'INCOMPLETE_HIGHER_TIMEFRAME')
    def test_reordered_events(self):
        a=self.a();model(a,bars(124));r=model(a,bars(123),asof_ms=int(bars(124).iloc[-1].available_ts_ms))
        self.assertEqual(r['status'],'UNKNOWN')
    def test_missing_bar(self):
        a=self.a();model(a,bars(124));self.assertEqual(model(a,bars(126))['reason'],'GAP_OR_REORDERED_BAR')
    def test_history_mutated(self):
        a=self.a();model(a,bars(124));f=bars(125);f.loc[5,'high']=102
        self.assertEqual(model(a,f)['reason'],'HISTORY_CHANGED')
    def test_source_identity_mismatch(self):
        a=self.a();model(a,bars(124));self.assertEqual(model(a,bars(125),source={**SOURCE,'identity_sha256':'9'*64})['reason'],'SOURCE_IDENTITY_CHANGED')
    def test_context_unknown_retry_same_bar(self):
        a=self.a();f=bars();f.loc[len(f)-1,'regime_available_ts_ms']+=1
        self.assertEqual(model(a,f)['reason'],'CAUSAL_CONTEXT_UNBOUND');self.assertFalse(a.state['signals'])
        self.assertEqual(model(a,bars())['status'],'NO_SIGNAL')
    def test_future_fit(self):
        f=deepcopy(FIT);f['last_fit_observation_ms']=T+100*k.TF;f.pop('sha256');f['sha256']=k.digest(f)
        self.assertEqual(model(self.a(),fit=f)['reason'],'CONTEXT_FIT_NOT_CAUSAL')
    def test_frozen_fit_and_cost_cannot_change(self):
        a=self.a();model(a,bars(124));f=deepcopy(FIT);f['vol_q25']+=.1;f.pop('sha256');f['sha256']=k.digest(f)
        self.assertEqual(model(a,bars(125),fit=f)['reason'],'FROZEN_FIT_CHANGED')
        self.assertEqual(model(a,bars(125),frozen_cost_bps=11.)['reason'],'FROZEN_COST_CHANGED')
    def test_carry_exact_inclusive_reserve(self):
        base={'exit_ts_ms':28_800_000,'signal':{'partial_fraction':.1}}
        child={'exit_ts_ms':57_600_000}
        snap={'funding_rows':[{'ts_ms':0},{'ts_ms':28_800_000},{'ts_ms':57_600_000}],'funding_p95_abs_bps':2.}
        cost,detail=D.carry(base,child,snap)
        self.assertAlmostEqual(cost,3.6);self.assertEqual(detail['additional_events'],2)
        snap['funding_rows'][1]['ts_ms']+=1
        self.assertIsNone(D.carry(base,child,snap)[0])
    def test_pre_freeze_no_retro_signal(self):
        a=self.a();f=bars();shift=200*k.TF
        for c in ['open_ts_ms','close_ts_ms','available_ts_ms','regime_available_ts_ms']:f[c]-=shift
        self.assertEqual(model(a,f)['reason'],'PRE_START_OR_INCOMPLETE_BAR')
    def test_native_exception_transaction(self):
        a=self.a()
        with patch.object(D.positive,'_hg_event',side_effect=RuntimeError('fixture exception')):
            r=model(a)
        self.assertEqual(r['status'],'UNKNOWN');self.assertEqual(a.state['signals'],{})
    def test_deterministic_restart_hash(self):
        a=self.a();model(a,bars(124));b=k.Adapter(enabled=True,fixture=True,state=a.state)
        model(a,bars(125));model(b,bars(125));self.assertEqual(k.digest(a.state),k.digest(b.state))
    def test_old_b_identity_rejected(self):
        a=self.a();s=deepcopy(a.state);s['identity']='scalp7_keltner_hg_fresh_touch_after_reject_utc30m_v1'
        with self.assertRaisesRegex(ValueError,'RUNTIME_IDENTITY'):k.Adapter(enabled=True,fixture=True,state=s)
    def test_unavailable_costs(self):
        for field in ('fee_bps','funding_bps','slippage_bps'):
            with self.subTest(field=field):
                a=self.a();_,event=pending(a);before=k.digest(a.state)
                with self.assertRaisesRegex(ValueError,'COST_UNAVAILABLE'):
                    a.entry_open(symbol='BTC-USDT',opened=event,cost_model={**COST,field:None},asof_ms=T+k.TF)
                self.assertEqual(k.digest(a.state),before)
    def test_late_open_not_backfilled(self):
        a=self.a();_,event=pending(a);event['received_at_ms']+=1
        r=a.entry_open(symbol='BTC-USDT',opened=event,cost_model=COST,asof_ms=T+k.TF+1)
        self.assertEqual(r['status'],'UNKNOWN');self.assertFalse(a.state['positions']);self.assertTrue(a.state['pending'])
    def test_malformed_stop_boundary(self):
        a=self.a();_,event=pending(a);a.state['pending']['BTC-USDT']['signal']['stop_price']=float('nan')
        with self.assertRaisesRegex(ValueError,'NONFINITE'):a.entry_open(symbol='BTC-USDT',opened=event,cost_model=COST,asof_ms=T+k.TF)
    def test_stop_first_beats_partial(self):
        a=self.a();row=opened(a);f=position_frame(row,(100,104,98,102))
        r=a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+2*k.TF)
        self.assertEqual(r['trade']['reason'],'STOP_FIRST');self.assertAlmostEqual(r['trade']['gross_bps'],-120.)
        self.assertEqual(r['trade']['mfe_R'],0);self.assertIsNone(r['trade']['NAV'])
    def test_gap_stop(self):
        a=self.a();row=opened(a);f=position_frame(row,(100,100.2,99.2,100),(98,99,97,98))
        r=a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+3*k.TF)
        self.assertEqual(r['trade']['reason'],'OPEN_GAP_STOP');self.assertEqual(r['trade']['exit_prices']['BTC-USDT'],98)
    def test_partial_fee_be_runner(self):
        a=self.a();row=opened(a);f=position_frame(row,(100,102.5,99.2,102))
        r=a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+2*k.TF)
        p=a.state['positions']['BTC-USDT']['position']['position']
        self.assertAlmostEqual(p['remaining'],.9);self.assertAlmostEqual(p['realized_parts_bps'],24.)
        self.assertAlmostEqual(p['stop_price'],100.12)
        f=position_frame(row,(100,102.5,99.2,102),(102,104,101,103))
        a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+3*k.TF)
        p=a.state['positions']['BTC-USDT']['position']['position'];self.assertAlmostEqual(p['stop_price'],102.5)
    def test_position_duplicate_and_restart(self):
        a=self.a();row=opened(a);f=position_frame(row,(100,100.2,99.2,100))
        a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+2*k.TF);before=k.digest(a.state)
        b=k.Adapter(enabled=True,fixture=True,state=a.state)
        self.assertEqual(b.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+2*k.TF)['status'],'DUPLICATE')
        self.assertEqual(k.digest(b.state),before)
    def test_gap_keeps_occupancy(self):
        a=self.a();row=opened(a);f=position_frame(row,(100,100.2,99.2,100),(100,100.2,99.2,100),(100,100.2,99.2,100));f=f.drop(index=2)
        self.assertEqual(a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+4*k.TF)['status'],'UNRESOLVED')
        self.assertTrue(a.state['positions']);self.assertFalse(a.state['trades'])
    def test_stale_position_source_is_hold(self):
        a=self.a();row=opened(a);f=position_frame(row,(100,100.2,99.2,100))
        with self.assertRaisesRegex(ValueError,'STALE_POSITION_SOURCE'):
            a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+2*k.TF+90001)
        self.assertTrue(a.state['positions']);self.assertFalse(a.state['trades'])
    def test_future_exit_bar_not_consumed(self):
        a=self.a();row=opened(a);f=position_frame(row,(100,100.2,99.2,100))
        with self.assertRaisesRegex(ValueError,'FUTURE_POSITION_BAR'):a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+k.TF)
    def test_structural_next_open_original_pullback(self):
        a=self.a();row=opened(a);f=position_frame(row,(100,100.1,98.9,98.95),(99.1,100,99,99.5))
        r=a.advance_position(symbol='BTC-USDT',frame=f,asof_ms=T+3*k.TF)
        self.assertEqual(r['trade']['reason'],'K126_PULLBACK_STRUCTURE_FAILURE_NEXT_OPEN');self.assertEqual(r['trade']['exit_prices']['BTC-USDT'],99.1)
    def test_exact_frozen_timeout_callback(self):
        a=self.a();row,_=pending(a);s=deepcopy(a.state['pending']['BTC-USDT']['signal']);s['identity']=D.positive.KELTNER_PARENT
        f=position_frame(row,(100,100.2,99.2,100));bar=f.iloc[-1].to_dict()
        cb=D.structural(True).callback(s,row,[])
        base={'signal':s,'side':1,'entry_price':100.,'entry_prices':{'BTC-USDT':100.},'entry_ts_ms':T+k.TF,'initial_risk':1.2,'stop_price':98.8,'remaining':.9,'hold_bars':25,'mfe_R':1.9}
        self.assertEqual(cb(base,bar,f)['reason'],'MAX_HOLD_NEXT_OPEN')
        base['mfe_R']=2.;self.assertFalse(cb(base,bar,f)['exit_next_open'])
    def test_objective_known_veto_and_hit_required(self):
        obj=D.objective([]);hg=D.positive.HolyGrailState(side=1,stage=1,pull_low=99,pull_high=101)
        before={'stage':0,'side':0,'episode_traded':False};r={'feature_available_ts_ms':T,'close_ts_ms':T,'hi20':105.,'lo20':95.,'high':101.,'low':99.}
        self.assertFalse(obj.after_native(before,hg,None,r,'BTC-USDT'))
        self.assertFalse(obj.rejected(hg,r,'BTC-USDT',T,'UNBOUND'));self.assertIsNone(obj.first_veto_ts)
        self.assertFalse(obj.rejected(hg,r,'BTC-USDT',T,'RANGE_MIXED'))
        r={**r,'feature_available_ts_ms':T+k.TF,'close_ts_ms':T+k.TF,'high':105.}
        self.assertTrue(obj.after_native({'stage':1,'side':1,'episode_traded':False},hg,None,r,'BTC-USDT'));self.assertEqual(hg.stage,0)
    def test_atomic_restart_lock_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=k.FixtureJournal(tmp);a=self.a();model(a);j.commit(a.state)
            with self.assertRaisesRegex(ValueError,'LOCK_COLLISION'):k.FixtureJournal(tmp)
            self.assertEqual(k.digest(j.load()),k.digest(a.state));j.close()
            j=k.FixtureJournal(tmp);state=j.load();b=k.Adapter(enabled=True,fixture=True,state=state);self.assertEqual(k.digest(a.state),k.digest(b.state))
            shortened=deepcopy(a.state);shortened['events']=[]
            with self.assertRaisesRegex(ValueError,'ADD_ONLY'):j.commit(shortened)
            p=Path(tmp)/'STATE.json';x=json.loads(p.read_text());x['NAV']=123;p.write_text(json.dumps(x))
            with self.assertRaisesRegex(ValueError,'STATE_HASH_MISMATCH'):j.load()
            j.close()
    def test_crash_before_atomic_replace_recovers_prior_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=k.FixtureJournal(tmp);a=self.a();model(a,bars(124));j.commit(a.state);old=k.digest(j.load())
            model(a,bars(125))
            with patch('os.replace',side_effect=OSError('simulated crash before replace')):
                with self.assertRaises(OSError):j.commit(a.state)
            j.close();j=k.FixtureJournal(tmp)
            self.assertEqual(k.digest(j.load()),old);j.commit(a.state);self.assertEqual(k.digest(j.load()),k.digest(a.state));j.close()
    def test_b_files_unaffected_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Path(tmp)/'work_b_orderless_fixture';b.mkdir();(b/'STATE.json').write_bytes(b'four versions original');(b/'archived_gap.json').write_bytes(b'gap preserved')
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in b.iterdir()}
            with self.assertRaisesRegex(ValueError,'ACTIVE_B_PATH'):k.FixtureJournal(b)
            model(self.a());self.assertEqual(hashes,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in b.iterdir()})
    def test_import_network_credentials_blocked_subprocess(self):
        script="""import sys,importlib,socket,tempfile
sys.path.insert(0,sys.argv[1])
import k117_adapter as k
counts=k.install_boundary()
for op in [lambda:importlib.import_module('ccxt'),lambda:importlib.import_module('backend.production.order_client'),lambda:open('/tmp/.env'),lambda:socket.create_connection(('127.0.0.1',1))]:
 try:op();raise AssertionError('NOT_BLOCKED')
 except ValueError:pass
assert counts['order_calls']==0 and counts['credential_file_reads']==0
print('BOUNDARY_PASS')
"""
        r=subprocess.run([sys.executable,'-c',script,str(k.HERE)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn('BOUNDARY_PASS',r.stdout)

if __name__=='__main__':unittest.main(verbosity=2)
