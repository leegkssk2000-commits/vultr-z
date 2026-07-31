from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
from typing import Any, Mapping
import numpy as np, pandas as pd

VERSION='ZEL_COMPONENT_AUTONOMY_V1'
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
def ema(s,n): return s.astype(float).ewm(span=n,adjust=False,min_periods=n).mean()
def features(df):
 x=df.copy(); x['timestamp']=pd.to_datetime(x.get('timestamp',x['timestamp_ms']),unit=None if 'timestamp' in x else 'ms',utc=True)
 for c in 'open high low close volume'.split(): x[c]=pd.to_numeric(x[c],errors='raise').astype(float)
 c,h,l,o,v=x.close,x.high,x.low,x.open,x.volume; prev=c.shift(1)
 tr=pd.concat((h-l,(h-prev).abs(),(l-prev).abs()),axis=1).max(axis=1); x['atr']=tr.rolling(14,min_periods=14).mean()
 for n in (20,21,50,55): x[f'e{n}']=ema(c,n)
 m=ema(c,12)-ema(c,26); x['hist']=m-ema(m,9); x['hp']=x['hist'].shift(1); x['imp']=(x['hist']-x['hp']).abs()
 w=(h-l).replace(0,np.nan); x['body']=(c-o).abs()/w; x['loc']=(c-l)/w
 x['slope20']=x.e20-x.e20.shift(4); x['gate']=(c>x.e20)&(x.e20>x.e50)&(x.slope20>0)
 x['trend']=(c>x.e21)&(x.e21>x.e55)&(x.e21>x.e21.shift(1))&(x.e55>=x.e55.shift(1)); x['cross']=(x['hp']<=0)&(x['hist']>0)
 x['short']=(c<x.e21)&(x.e21<x.e55)&(x['hp']>=0)&(x['hist']<0)
 x['atr_pct']=x['atr']/c*100; x['dist']=(c-x.e21).abs()/x['atr'].replace(0,np.nan); x['beam']=x['trend']&x['cross']&(x['imp']>=.08)&(x['body']>=.45)&(x['loc']>=.62)
 vm=v.rolling(30,min_periods=20).mean(); vs=v.rolling(30,min_periods=20).std(ddof=0); x['vz']=(v-vm)/vs.replace(0,np.nan)
 x['trend_score']=(((x.e21-x.e55).abs()/x['atr'].replace(0,np.nan))/2).clip(0,1); x['confirm_score']=(x['imp']/.12).clip(0,1)
 x['breakout_score']=(x['body'].fillna(0)*x['loc'].fillna(.5)).clip(0,1); x['intuition_score']=((x['vz'].fillna(0)+2)/4).clip(0,1)
 risk=((x['atr_pct'].fillna(2)/5.5)*.55+(x['dist'].fillna(2)/3).clip(0,1)*.45).clip(0,1); x['risk_score']=risk; x['safety_score']=1-risk
 x['signal']=(x['trend']&x['cross']&x['gate']&(x['atr_pct'].between(.25,5.5))&(x['imp']>=.03)&(x['dist']<=1.84)).fillna(False)
 return x

def build_events(root,manifest,warm=220,cost_bps=4.):
 out=[]; short_count=0
 for r in manifest['rows']:
  df=pd.read_csv(Path(root)/r['path']); x=features(df); short_count+=int(x['short'].iloc[warm:].sum())
  for i in np.flatnonzero(x.signal.to_numpy())[np.flatnonzero(x.signal.to_numpy())>=warm]:
   if i+1>=len(x): continue
   row=x.iloc[i]; entry=f(x.open.iloc[i+1]); atr=f(row.atr); risk=max(entry-min(f(row.low),f(row.e21)-atr,entry-1.6*atr),.4*atr)
   target_r=2.6 if bool(row.beam) else 2.; stop=entry-risk; target=entry+risk*target_r; end=min(len(x),i+49); exitp=f(x.close.iloc[end-1]); reason='TIME48'
   mfe=mae=0.; exit_i=end-1
   for j in range(i+1,end):
    hi,lo=f(x.high.iloc[j]),f(x.low.iloc[j]); mfe=max(mfe,(hi-entry)/max(risk,1e-12)); mae=max(mae,(entry-lo)/max(risk,1e-12))
    if lo<=stop or hi>=target:
     exitp=stop if lo<=stop else target; reason='SL' if lo<=stop else 'TP'; exit_i=j; break
   net=.5*((exitp/entry)-1)*100-2*.5*cost_bps/10000*100
   ret24=.5*((f(x.close.iloc[min(len(x)-1,i+24)])/entry)-1)*100-2*.5*cost_bps/10000*100
   scores={k:f(row.get(k)) for k in ('trend_score','confirm_score','breakout_score','intuition_score','safety_score','risk_score')}
   out.append({'window_id':r['window_id'],'symbol':r['symbol'],'entry_ts':pd.Timestamp(x.timestamp.iloc[i+1]).isoformat(),'exit_ts':pd.Timestamp(x.timestamp.iloc[exit_i]).isoformat(),'net':net,'ret24':ret24,'mfe_r':mfe,'mae_r':mae,'beam':bool(row.beam),'volume_z':f(row.vz,-9),'atr_pct':f(row.atr_pct),'scores':scores,'reason':reason})
 return sorted(out,key=lambda z:(z['window_id'],z['entry_ts'],z['symbol'])),short_count

def stats(rows):
 a=[f(r['net']) for r in rows]; wins=[x for x in a if x>0]; losses=[x for x in a if x<0]; eq=pk=dd=0
 for x in a: eq+=x; pk=max(pk,eq); dd=max(dd,pk-eq)
 gl=abs(sum(losses)); pf=sum(wins)/gl if gl>1e-12 else (999. if wins else 0.)
 return {'trade_count':len(a),'win_rate_pct':100*len(wins)/len(a) if a else 0.,'net_return_pct_sum':sum(a),'profit_factor':pf,'max_drawdown_pct':dd,'average_mfe_r':sum(f(r['mfe_r']) for r in rows)/len(rows) if rows else 0.,'average_mae_r':sum(f(r['mae_r']) for r in rows)/len(rows) if rows else 0.}
def delta(c,b,p):
 d={'net':f(c['net_return_pct_sum'])-f(b['net_return_pct_sum']),'pf':f(c['profit_factor'])-f(b['profit_factor']),'dd_reduction':f(b['max_drawdown_pct'])-f(c['max_drawdown_pct']),'retention':f(c['trade_count'])/max(f(b['trade_count']),1)}; e=p['epoch_policy']
 return {'deltas':d,'material':d['net']>=e['minimum_material_net_pct_points'] and d['retention']>=e['minimum_trade_retention'] and (d['pf']>=e['minimum_material_pf'] or d['dd_reduction']>=e['minimum_material_dd_pct_points'])}
def botfit(r,name,w,cap):
 s=r['scores']; pairs={'LBot':('trend_score','confirm_score'),'MBot':('confirm_score','intuition_score'),'OBot':('breakout_score','trend_score'),'SBot':('safety_score','safety_score')}; a,b=pairs[name]; v=w*f(s[a])+(1-w)*f(s[b]); return min(v,cap) if f(s['risk_score'])>=.85 else v
def apply_filter(events,fn): return [r for r in events if fn(r)]
def skill_rows(events,p):
 ans=[]
 for sid in ['BASE_NO_SKILL','SK_ENTRY_LONG_BEAM','SK_ENTRY_SHORT_BEAM','SK_ADD_DCA','SK_ADD_AVG_DOWN','SK_ADD_WATER_ADD','SK_ADD_PYRAMIDING','SK_ADD_PROFITABLE_SCALE_IN','SK_EXIT_PARTIAL_30','SK_EXIT_TRAILING_STOP','SK_EXIT_MFE_RUNNER','SK_EXIT_RUNNER_HOLD','SK_EXIT_TIME_STOP','SK_EXIT_BREAK_EVEN_SHIFT','SK_RISK_REDUCE_25']:
  rows=[]; obs=0
  for r0 in events:
   r=dict(r0); n=f(r['net']); mfe=f(r['mfe_r']);
   if sid=='SK_ENTRY_LONG_BEAM' and r['beam']: continue
   if sid=='SK_ENTRY_SHORT_BEAM': rows.append(r); continue
   if sid in {'SK_ADD_DCA','SK_ADD_AVG_DOWN','SK_ADD_WATER_ADD'}:
    if f(r['mae_r'])>=.25: obs+=1
   elif sid in {'SK_ADD_PYRAMIDING','SK_ADD_PROFITABLE_SCALE_IN'} and mfe>=.35 and n>0:
    mult=1.14 if sid.endswith('PYRAMIDING') else 1.28; r['net']=n*mult
   elif sid=='SK_EXIT_PARTIAL_30' and mfe>=1: r['net']=.3*max(n,.5)+.7*n
   elif sid=='SK_EXIT_TRAILING_STOP' and mfe>=1: r['net']=max(n,(mfe-1)*.25)
   elif sid=='SK_EXIT_MFE_RUNNER' and mfe>=1: r['net']=max(n,.3*.5+.7*min(mfe,3)*.5)
   elif sid=='SK_EXIT_RUNNER_HOLD' and mfe>=2: r['net']=max(n,min(mfe,3)*.5)
   elif sid=='SK_EXIT_TIME_STOP': r['net']=f(r['ret24'])
   elif sid=='SK_EXIT_BREAK_EVEN_SHIFT' and mfe>=1 and n<0: r['net']=-.04
   elif sid=='SK_RISK_REDUCE_25' and mfe>=.75: r['net']=.25*.375+.75*n
   rows.append(r)
  ans.append({'skill_id':sid,'stats':stats(rows),'loss_direction_observer_count':obs,'loss_direction_observer_only':sid in {'SK_ADD_DCA','SK_ADD_AVG_DOWN','SK_ADD_WATER_ADD'}})
 return ans
def run(policy,root,prev=None):
 m=read(Path(root)/'manifest.json'); exp=policy['source_authorities']['strategy_archive_expected_sha'];
 if m.get('archive_sha256')!=exp: raise RuntimeError(f'ARCHIVE_SHA_MISMATCH:{m.get("archive_sha256")}:{exp}')
 events,shorts=build_events(root,m,int(m.get('warmup_bars',220)),policy['risk_contract']['cost_bps_per_side']); base=stats(events); fp=sha({'archive':exp,'policy':sha(policy)}); ep=(int((prev or {}).get('epoch',0))+1) if (prev or {}).get('data_fingerprint')==fp else 1
 bots=[]
 for name in ('LBot','MBot','OBot','SBot'):
  for w in policy['bot_search']['primary_weights']:
   for t in policy['bot_search']['helper_thresholds']:
    for c in policy['bot_search']['warning_caps']:
     st=stats(apply_filter(events,lambda r,n=name,w=w,t=t,c=c:botfit(r,n,w,c)>=t)); bots.append({'bot':name,'weight':w,'threshold':t,'warning_cap':c,'stats':st,'evidence':delta(st,base,policy)})
 teams=[]
 for name,tm in policy['team_search']['teams'].items():
  for s in policy['team_search']['support_thresholds']:
   for v in policy['team_search']['watcher_veto_thresholds']:
    def ok(r,tm=tm,s=s,v=v):
     q={b:botfit(r,b,.7,.25) for b in ('LBot','MBot','OBot','SBot')}; return q[tm['main']]>=.5 and q[tm['support']]>=s and (('SBot' not in tm['watchers']) or q['SBot']>=1-v)
    st=stats(apply_filter(events,ok)); teams.append({'team':name,'support_threshold':s,'watcher_veto_threshold':v,'stats':st,'evidence':delta(st,base,policy)})
 skills=skill_rows(events,policy)
 for x in skills:x['evidence']=delta(x['stats'],base,policy)
 advisors=[]
 for z in policy['advisor_search']['ZBOT']['disagreement_thresholds']:
  for vz in policy['advisor_search']['LICO']['minimum_volume_z']:
   for am in policy['advisor_search']['LICO']['maximum_atr_pct']:
    rows=apply_filter(events,lambda r,z=z,vz=vz,am=am:abs(f(r['scores']['trend_score'])-f(r['scores']['confirm_score']))<=z and f(r['volume_z'],-9)>=vz and f(r['atr_pct'])<=am)
    st=stats(rows); advisors.append({'profile':{'zbot_disagreement':z,'lico_volume_z':vz,'lico_atr_max':am,'zico_loss_cooldown':'EVENT_LEDGER_STAGE2','zlice_lineage_coverage_pct':100.},'stats':st,'evidence':delta(st,base,policy)})
 def best(rows):return max(rows,key=lambda x:(1 if x['evidence']['material'] else 0,f(x['stats']['net_return_pct_sum']),f(x['stats']['profit_factor']),-f(x['stats']['max_drawdown_pct'])))
 bb,bt,bs,ba=map(best,(bots,teams,skills,advisors)); team=policy['team_search']['teams'][bt['team']]
 def fullok(r):
  q={b:botfit(r,b,bb['weight'],bb['warning_cap']) for b in ('LBot','MBot','OBot','SBot')}; return q[bb['bot']]>=bb['threshold'] and q[team['main']]>=.5 and q[team['support']]>=bt['support_threshold'] and (('SBot' not in team['watchers']) or q['SBot']>=1-bt['watcher_veto_threshold']) and abs(f(r['scores']['trend_score'])-f(r['scores']['confirm_score']))<=ba['profile']['zbot_disagreement'] and f(r['volume_z'],-9)>=ba['profile']['lico_volume_z'] and f(r['atr_pct'])<=ba['profile']['lico_atr_max']
 full_events=apply_filter(events,fullok); fullskill=next(x for x in skill_rows(full_events,policy) if x['skill_id']==bs['skill_id']); full=fullskill['stats']; ev=delta(full,base,policy); prevbest=f((prev or {}).get('best_full_net'),-1e99); imp=f(full['net_return_pct_sum'])-(prevbest if prevbest>-1e98 else f(base['net_return_pct_sum'])); patience=0 if imp>=policy['epoch_policy']['minimum_material_net_pct_points'] else int((prev or {}).get('patience',0))+1; state='CONVERGED_HOLD' if patience>=policy['epoch_policy']['patience_epochs'] or ep>policy['epoch_policy']['max_epochs_per_data_fingerprint'] else 'PASS_COMPONENT_AUTONOMY_EPOCH'
 out={'schema_version':'1.0','version':VERSION,'state':state,'epoch':min(ep,policy['epoch_policy']['max_epochs_per_data_fingerprint']),'data_fingerprint':fp,'archive_sha256':exp,'strategy_id':policy['source_authorities']['strategy_id'],'strategy_variant':policy['source_authorities']['strategy_variant'],'execution_fidelity':'SOURCE_BOUND_EVENT_LEVEL_COUNTERFACTUAL','control':{'stats':base,'event_count':len(events),'short_observer_signals':shorts,'event_ledger_sha256':sha(events)},'module_results':{'bots':{'tested':len(bots),'best':bb},'teams':{'tested':len(teams),'best':bt},'skills':{'tested':len(skills),'best':bs},'advisors':{'tested':len(advisors),'best':ba}},'full_stack':{'stats':full,'evidence':ev},'component_attribution':{'bot_delta_net':f(bb['stats']['net_return_pct_sum'])-f(base['net_return_pct_sum']),'team_delta_net':f(bt['stats']['net_return_pct_sum'])-f(base['net_return_pct_sum']),'skill_delta_net':f(bs['stats']['net_return_pct_sum'])-f(base['net_return_pct_sum']),'advisor_delta_net':f(ba['stats']['net_return_pct_sum'])-f(base['net_return_pct_sum']),'full_stack_delta_net':f(full['net_return_pct_sum'])-f(base['net_return_pct_sum'])},'convergence':{'patience':patience,'maximum_epochs':policy['epoch_policy']['max_epochs_per_data_fingerprint'],'reopen_on':policy['epoch_policy']['reopen_on']},'ai_usage':{'xai_grok_required':False,'groq_required_this_epoch':False,'gemini_required_this_epoch':state=='CONVERGED_HOLD','reason':'AI_ESCALATES_ONLY_ON_NEW_FINGERPRINT_OR_CONVERGENCE','router_policy':policy['ai_policy']},'shadow_start_allowed':False,'paper_allowed':False,'live_allowed':False,**SAFE}; out['result_sha256']=sha(out); return out
def fixture(out):
 rng=np.random.default_rng(7); root=Path(out)/'archive'; (root/'market').mkdir(parents=True,exist_ok=True); rr=[]
 for w in range(1,3):
  for sym in ('BTCUSDT','SOLUSDT'):
   n=320; close=100*np.exp(np.cumsum(rng.normal(.0004, .003,n))); op=np.r_[close[0],close[:-1]]; hi=np.maximum(op,close)*(1+rng.uniform(.001,.004,n)); lo=np.minimum(op,close)*(1-rng.uniform(.001,.004,n)); ts=pd.date_range(f'2026-0{w}-01',periods=n,freq='15min',tz='UTC'); df=pd.DataFrame({'timestamp_ms':ts.astype('int64')//10**6,'open':op,'high':hi,'low':lo,'close':close,'volume':rng.lognormal(8,.5,n)}); p=root/'market'/f'A{w:02d}-{sym}.csv'; df.to_csv(p,index=False); rr.append({'window_id':f'A{w:02d}','symbol':sym,'path':str(p.relative_to(root))})
 m={'rows':rr,'warmup_bars':220}; m['archive_sha256']=sha(rr); write(root/'manifest.json',m); pol=read(Path(__file__).with_name('zel_component_autonomy_policy_v1.json')); pol['source_authorities']['strategy_archive_expected_sha']=m['archive_sha256']; pol['bot_search']={'primary_weights':[.7],'helper_thresholds':[.72],'warning_caps':[.25]}; pol['team_search']['support_thresholds']=[.55]; pol['team_search']['watcher_veto_thresholds']=[.8]; pol['advisor_search']['ZBOT']['disagreement_thresholds']=[.3]; pol['advisor_search']['LICO']['minimum_volume_z']=[-.5]; pol['advisor_search']['LICO']['maximum_atr_pct']=[4.]; a=run(pol,root); b=run(pol,root); assert a['result_sha256']==b['result_sha256'] and set(a['module_results'])=={'bots','teams','skills','advisors'} and a['order_authority']=='BLOCKED'; write(Path(out)/'fixture_result.json',a); print(json.dumps({'state':'PASS_COMPONENT_AUTONOMY_FIXTURE','sha':a['result_sha256']})); return 0
def main():
 ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest='mode',required=True); r=sp.add_parser('run'); r.add_argument('--policy',required=True); r.add_argument('--archive-root',required=True); r.add_argument('--previous-state'); r.add_argument('--out',required=True); q=sp.add_parser('fixture'); q.add_argument('--out',required=True); a=ap.parse_args()
 if a.mode=='fixture':return fixture(a.out)
 pol=read(a.policy); prev=read(a.previous_state) if a.previous_state and Path(a.previous_state).is_file() else None; z=run(pol,Path(a.archive_root),prev); write(Path(a.out)/'final.json',z); write(Path(a.out)/'state.json',{'epoch':z.get('epoch',0),'data_fingerprint':z.get('data_fingerprint'),'patience':z.get('convergence',{}).get('patience',0),'best_full_net':z.get('full_stack',{}).get('stats',{}).get('net_return_pct_sum',0),**SAFE}); print(json.dumps({'state':z['state'],'epoch':z.get('epoch'),'full_net':z.get('full_stack',{}).get('stats',{}).get('net_return_pct_sum'),'sha':z['result_sha256']})); return 0
if __name__=='__main__': raise SystemExit(main())
