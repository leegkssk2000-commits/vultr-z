from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
from typing import Any
import pandas as pd

VERSION='ZEL_COMPONENT_AUTONOMY_V1_1_EXACT_LEDGER'
SAFE={'research_only':True,'promotion_authority':False,'protected_mutations':0,'execution_allowed':False,'execution_authority':'NONE','order_authority':'BLOCKED','runtime_bound':False}

def sha(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def read(p):
 v=json.loads(Path(p).read_text());
 if not isinstance(v,dict): raise ValueError(f'OBJECT_REQUIRED:{p}')
 return v
def write(p,v):
 p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(v,indent=2,sort_keys=True,allow_nan=False)+'\n')
def f(v,d=0.):
 try:
  x=float(v); return x if math.isfinite(x) else d
 except Exception:return d
def policy_path(): return Path(__file__).resolve().parents[1]/'research'/'zel_component_autonomy_policy_v1.json'
def event(row):
 ft=dict(row.get('features') or {}); atr_rank=f(ft.get('atr_percentile'),50)/100; dist=f(ft.get('distance_ema20_atr'),2); risk=max(0,min(1,.55*atr_rank+.45*min(dist/3,1)))
 scores={'trend_score':max(0,min(1,(f(ft.get('adx14'))/40+.5*bool(ft.get('trend_ema20_50')))/1.5)),'confirm_score':max(0,min(1,.45*bool(ft.get('macd_positive'))+.30*bool(ft.get('obv_positive'))+.25*bool(ft.get('directional_close_long')))),'breakout_score':max(0,min(1,.55*f(ft.get('body_atr'))+.45*bool(ft.get('donchian_break_long')))),'intuition_score':max(0,min(1,(f(ft.get('volume_z'))+2)/4)),'safety_score':1-risk,'risk_score':risk}
 return {'window_id':row['window_id'],'symbol':row['symbol'],'entry_ts':row['entry_ts'],'exit_ts':row['exit_ts'],'net':f(row.get('net_return_pct')),'mfe_r':f(row.get('mfe_r')),'mae_r':f(row.get('mae_r')),'bars_held':int(row.get('bars_held') or 0),'beam':row.get('signal_skill')=='long_beam','volume_z':f(ft.get('volume_z'),-9),'atr_pct':f(ft.get('atr_pct')),'scores':scores,'lineage_complete':bool(row.get('signal_ts') and row.get('entry_ts') and row.get('exit_ts') and row.get('features'))}
def load_events(ledger,summary):
 if ledger.get('strategy_id')!='trend_ma_macd' or summary.get('strategy_id')!='trend_ma_macd': raise RuntimeError('STRATEGY_ID_MISMATCH')
 if summary.get('authority')!='READ_ONLY_BASELINE_EVIDENCE_NO_EXECUTION': raise RuntimeError('EVIDENCE_AUTHORITY_INVALID')
 rows=[event(x) for x in ledger.get('trades',[])]; base=summary.get('baseline') or {}
 if len(rows)!=int(base.get('trade_count',-1)): raise RuntimeError('TRADE_COUNT_MISMATCH')
 if abs(sum(f(x['net']) for x in rows)-f(base.get('net_return_pct_sum')))>1e-9: raise RuntimeError('NET_SUM_MISMATCH')
 if not rows or not all(x['lineage_complete'] for x in rows): raise RuntimeError('LINEAGE_INCOMPLETE')
 return sorted(rows,key=lambda x:(x['entry_ts'],x['symbol']))
def stats(rows):
 a=[f(x['net']) for x in rows]; w=[x for x in a if x>0]; l=[x for x in a if x<0]; eq=pk=dd=0
 for x in a: eq+=x; pk=max(pk,eq); dd=max(dd,pk-eq)
 gl=abs(sum(l)); pf=sum(w)/gl if gl>1e-12 else (999. if w else 0.)
 return {'trade_count':len(a),'win_rate_pct':100*len(w)/len(a) if a else 0.,'net_return_pct_sum':sum(a),'profit_factor':pf,'max_drawdown_pct':dd,'average_mfe_r':sum(f(x['mfe_r']) for x in rows)/len(rows) if rows else 0.,'average_mae_r':sum(f(x['mae_r']) for x in rows)/len(rows) if rows else 0.}
def delta(c,b,p):
 d={'net':f(c['net_return_pct_sum'])-f(b['net_return_pct_sum']),'pf':f(c['profit_factor'])-f(b['profit_factor']),'dd_reduction':f(b['max_drawdown_pct'])-f(c['max_drawdown_pct']),'retention':f(c['trade_count'])/max(f(b['trade_count']),1)}; e=p['epoch_policy']; return {'deltas':d,'material':d['net']>=e['minimum_material_net_pct_points'] and d['retention']>=e['minimum_trade_retention'] and (d['pf']>=e['minimum_material_pf'] or d['dd_reduction']>=e['minimum_material_dd_pct_points'])}
def botfit(r,n,w,cap):
 s=r['scores']; q={'LBot':('trend_score','confirm_score'),'MBot':('confirm_score','intuition_score'),'OBot':('breakout_score','trend_score'),'SBot':('safety_score','safety_score')}; a,b=q[n]; v=w*f(s[a])+(1-w)*f(s[b]); return min(v,cap) if f(s['risk_score'])>=.85 else v
def filt(rows,fn): return [x for x in rows if fn(x)]
def skills(rows):
 out=[]
 for sid in ['BASE_NO_SKILL','SK_ENTRY_LONG_BEAM','SK_ENTRY_SHORT_BEAM','SK_ADD_DCA','SK_ADD_AVG_DOWN','SK_ADD_WATER_ADD','SK_ADD_PYRAMIDING','SK_ADD_PROFITABLE_SCALE_IN','SK_EXIT_PARTIAL_30','SK_EXIT_TRAILING_STOP','SK_EXIT_MFE_RUNNER','SK_EXIT_RUNNER_HOLD','SK_EXIT_TIME_STOP','SK_EXIT_BREAK_EVEN_SHIFT','SK_RISK_REDUCE_25']:
  z=[]; obs=0; fidelity='EXACT_ABLATION' if sid.startswith('SK_ENTRY') else 'EVENT_LEVEL_COUNTERFACTUAL'
  for r0 in rows:
   r=dict(r0); n=f(r['net']); mfe=f(r['mfe_r'])
   if sid=='SK_ENTRY_LONG_BEAM' and r['beam']: continue
   if sid=='SK_ENTRY_SHORT_BEAM': z.append(r); continue
   if sid in {'SK_ADD_DCA','SK_ADD_AVG_DOWN','SK_ADD_WATER_ADD'}:
    obs+=int(f(r['mae_r'])>=.25); fidelity='OBSERVER_ONLY'
   elif sid in {'SK_ADD_PYRAMIDING','SK_ADD_PROFITABLE_SCALE_IN'} and mfe>=.35 and n>0: r['net']=n*(1.14 if sid.endswith('PYRAMIDING') else 1.28)
   elif sid=='SK_EXIT_PARTIAL_30' and mfe>=1:r['net']=.3*max(n,.5)+.7*n
   elif sid=='SK_EXIT_TRAILING_STOP' and mfe>=1:r['net']=max(n,(mfe-1)*.25)
   elif sid=='SK_EXIT_MFE_RUNNER' and mfe>=1:r['net']=max(n,.15+.35*min(mfe,3))
   elif sid=='SK_EXIT_RUNNER_HOLD' and mfe>=2:r['net']=max(n,.5*min(mfe,3))
   elif sid=='SK_EXIT_TIME_STOP' and r['bars_held']>48:r['net']=n*48/max(r['bars_held'],1)
   elif sid=='SK_EXIT_BREAK_EVEN_SHIFT' and mfe>=1 and n<0:r['net']=-.04
   elif sid=='SK_RISK_REDUCE_25' and mfe>=.75:r['net']=.09375+.75*n
   z.append(r)
  out.append({'skill_id':sid,'fidelity':fidelity,'stats':stats(z),'loss_direction_observer_count':obs,'loss_direction_observer_only':sid in {'SK_ADD_DCA','SK_ADD_AVG_DOWN','SK_ADD_WATER_ADD'}})
 return out
def apply_cooldown(rows,bars):
 if bars<=0:return rows
 out=[]; last={}
 for r in rows:
  t=pd.Timestamp(r['entry_ts']); sym=r['symbol']; prev=last.get(sym)
  if prev is not None and t<prev+pd.Timedelta(minutes=15*bars):continue
  out.append(r)
  if f(r['net'])<0:last[sym]=pd.Timestamp(r['exit_ts'])
 return out
def optimize(p,ledger,summary,prev=None):
 rows=load_events(ledger,summary); base=stats(rows); lsha=sha(ledger); ssha=sha(summary); fp=sha({'ledger':lsha,'summary':ssha,'policy':sha(p)}); same=(prev or {}).get('data_fingerprint')==fp; ep=int((prev or {}).get('epoch',0))+1 if same else 1; prior=(prev or {}) if same else {}
 bots=[]
 for n in ('LBot','MBot','OBot','SBot'):
  for w in p['bot_search']['primary_weights']:
   for t in p['bot_search']['helper_thresholds']:
    for c in p['bot_search']['warning_caps']:
     st=stats(filt(rows,lambda r,n=n,w=w,t=t,c=c:botfit(r,n,w,c)>=t)); bots.append({'bot':n,'weight':w,'threshold':t,'warning_cap':c,'stats':st,'evidence':delta(st,base,p)})
 teams=[]
 for name,tm in p['team_search']['teams'].items():
  for s in p['team_search']['support_thresholds']:
   for v in p['team_search']['watcher_veto_thresholds']:
    def ok(r,tm=tm,s=s,v=v):
     q={b:botfit(r,b,.7,.25) for b in ('LBot','MBot','OBot','SBot')}; return q[tm['main']]>=.5 and q[tm['support']]>=s and (('SBot' not in tm['watchers']) or q['SBot']>=1-v)
    st=stats(filt(rows,ok)); teams.append({'team':name,'support_threshold':s,'watcher_veto_threshold':v,'stats':st,'evidence':delta(st,base,p)})
 sk=skills(rows)
 for x in sk:x['evidence']=delta(x['stats'],base,p)
 adv=[]
 for z in p['advisor_search']['ZBOT']['disagreement_thresholds']:
  for cd in p['advisor_search']['ZICO']['loss_cooldown_bars']:
   for vz in p['advisor_search']['LICO']['minimum_volume_z']:
    for am in p['advisor_search']['LICO']['maximum_atr_pct']:
     q=filt(rows,lambda r,z=z,vz=vz,am=am:abs(f(r['scores']['trend_score'])-f(r['scores']['confirm_score']))<=z and f(r['volume_z'],-9)>=vz and f(r['atr_pct'])<=am); q=apply_cooldown(q,int(cd)); st=stats(q); adv.append({'profile':{'zbot_disagreement':z,'zico_loss_cooldown_bars':cd,'lico_volume_z':vz,'lico_atr_max':am,'zlice_lineage_coverage_pct':100.},'stats':st,'evidence':delta(st,base,p)})
 def best(a):return max(a,key=lambda x:(1 if x['evidence']['material'] else 0,f(x['stats']['net_return_pct_sum']),f(x['stats']['profit_factor']),-f(x['stats']['max_drawdown_pct'])))
 bb,bt,bs,ba=map(best,(bots,teams,sk,adv)); tm=p['team_search']['teams'][bt['team']]
 def okfull(r):
  q={b:botfit(r,b,bb['weight'],bb['warning_cap']) for b in ('LBot','MBot','OBot','SBot')}; return q[bb['bot']]>=bb['threshold'] and q[tm['main']]>=.5 and q[tm['support']]>=bt['support_threshold'] and (('SBot' not in tm['watchers']) or q['SBot']>=1-bt['watcher_veto_threshold']) and abs(f(r['scores']['trend_score'])-f(r['scores']['confirm_score']))<=ba['profile']['zbot_disagreement'] and f(r['volume_z'],-9)>=ba['profile']['lico_volume_z'] and f(r['atr_pct'])<=ba['profile']['lico_atr_max']
 fullrows=apply_cooldown(filt(rows,okfull),int(ba['profile']['zico_loss_cooldown_bars'])); full=next(x for x in skills(fullrows) if x['skill_id']==bs['skill_id'])['stats']; ev=delta(full,base,p); prevbest=f(prior.get('best_full_net'),-1e99); imp=f(full['net_return_pct_sum'])-(prevbest if prevbest>-1e98 else f(base['net_return_pct_sum'])); patience=0 if imp>=p['epoch_policy']['minimum_material_net_pct_points'] else int(prior.get('patience',0))+1; state='CONVERGED_HOLD' if patience>=p['epoch_policy']['patience_epochs'] or ep>p['epoch_policy']['max_epochs_per_data_fingerprint'] else 'PASS_COMPONENT_AUTONOMY_EPOCH'
 out={'schema_version':'1.1','version':VERSION,'state':state,'epoch':min(ep,p['epoch_policy']['max_epochs_per_data_fingerprint']),'data_fingerprint':fp,'source_authority':{'ledger_sha256':lsha,'summary_sha256':ssha,'authority_exact_summary_sha256':summary.get('authority_exact_summary_sha256'),'selected_authority_result_sha256':summary.get('selected_authority_result_sha256')},'strategy_id':'trend_ma_macd','strategy_variant':'BASE_EXACT_TF_EMA_TRAIL1R_ATR1','execution_fidelity':'CANONICAL_EXACT_TRADE_LEDGER_PLUS_EVENT_COUNTERFACTUAL_COMPONENTS','control':{'stats':base,'event_count':len(rows),'event_ledger_sha256':sha(rows)},'module_results':{'bots':{'tested':len(bots),'best':bb},'teams':{'tested':len(teams),'best':bt},'skills':{'tested':len(sk),'best':bs},'advisors':{'tested':len(adv),'best':ba}},'full_stack':{'stats':full,'evidence':ev},'component_attribution':{'bot_delta_net':f(bb['stats']['net_return_pct_sum'])-f(base['net_return_pct_sum']),'team_delta_net':f(bt['stats']['net_return_pct_sum'])-f(base['net_return_pct_sum']),'skill_delta_net':f(bs['stats']['net_return_pct_sum'])-f(base['net_return_pct_sum']),'advisor_delta_net':f(ba['stats']['net_return_pct_sum'])-f(base['net_return_pct_sum']),'full_stack_delta_net':f(full['net_return_pct_sum'])-f(base['net_return_pct_sum'])},'convergence':{'patience':patience,'fingerprint_reset':not same,'maximum_epochs':p['epoch_policy']['max_epochs_per_data_fingerprint'],'reopen_on':p['epoch_policy']['reopen_on']},'ai_usage':{'xai_grok_required':False,'groq_required_this_epoch':False,'gemini_required_this_epoch':state=='CONVERGED_HOLD','reason':'AI_ESCALATES_ONLY_ON_NEW_FINGERPRINT_OR_CONVERGENCE','router_policy':p['ai_policy']},'shadow_start_allowed':False,'paper_allowed':False,'live_allowed':False,**SAFE}; out['result_sha256']=sha(out); return out
def fixture(out):
 rows=[]
 for i,n in enumerate([.30,-.20,.55,-.35,.70,-.10]):rows.append({'window_id':f'F{1+i//2}','symbol':'BTCUSDT' if i%2==0 else 'SOLUSDT','entry_ts':f'2026-01-0{i+1}T00:00:00+00:00','exit_ts':f'2026-01-0{i+1}T01:00:00+00:00','net_return_pct':n,'mfe_r':max(.2,n*4+1),'mae_r':max(.1,-n*2+.2),'bars_held':4+i,'signal_skill':'long_beam' if i%3==0 else 'trend_entry','signal_ts':f'2026-01-0{i+1}T00:00:00+00:00','features':{'atr_percentile':20+i*10,'distance_ema20_atr':.5+i*.1,'adx14':15+i*3,'trend_ema20_50':True,'macd_positive':i%2==0,'obv_positive':True,'directional_close_long':True,'body_atr':.4+i*.1,'donchian_break_long':False,'volume_z':-.5+i*.2,'atr_pct':.4+i*.1}})
 led={'strategy_id':'trend_ma_macd','trades':rows}; base=stats([event(x) for x in rows]); summ={'strategy_id':'trend_ma_macd','authority':'READ_ONLY_BASELINE_EVIDENCE_NO_EXECUTION','baseline':{'trade_count':len(rows),'net_return_pct_sum':base['net_return_pct_sum']},'authority_exact_summary_sha256':'fixture','selected_authority_result_sha256':'fixture'}; p=read(policy_path()); p['bot_search']={'primary_weights':[.7],'helper_thresholds':[.72],'warning_caps':[.25]}; p['team_search']['support_thresholds']=[.55]; p['team_search']['watcher_veto_thresholds']=[.8]; p['advisor_search']['ZBOT']['disagreement_thresholds']=[.3]; p['advisor_search']['ZICO']['loss_cooldown_bars']=[4]; p['advisor_search']['LICO']['minimum_volume_z']=[-.5]; p['advisor_search']['LICO']['maximum_atr_pct']=[4.]; a=optimize(p,led,summ); b=optimize(p,led,summ); assert a['result_sha256']==b['result_sha256'] and a['order_authority']=='BLOCKED' and a['convergence']['fingerprint_reset'] is True; write(Path(out)/'fixture_result.json',a); print('PASS_COMPONENT_AUTONOMY_FIXTURE',a['result_sha256']); return 0
def main():
 ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest='mode',required=True); r=sp.add_parser('run'); r.add_argument('--policy',required=True); r.add_argument('--ledger',required=True); r.add_argument('--summary',required=True); r.add_argument('--previous-state'); r.add_argument('--out',required=True); q=sp.add_parser('fixture'); q.add_argument('--out',required=True); a=ap.parse_args()
 if a.mode=='fixture':return fixture(a.out)
 p=read(a.policy); prev=read(a.previous_state) if a.previous_state and Path(a.previous_state).is_file() else None; z=optimize(p,read(a.ledger),read(a.summary),prev); write(Path(a.out)/'final.json',z); write(Path(a.out)/'state.json',{'epoch':z['epoch'],'data_fingerprint':z['data_fingerprint'],'patience':z['convergence']['patience'],'best_full_net':z['full_stack']['stats']['net_return_pct_sum'],'result_sha256':z['result_sha256'],**SAFE}); print(z['state'],z['result_sha256']); return 0
if __name__=='__main__':raise SystemExit(main())
