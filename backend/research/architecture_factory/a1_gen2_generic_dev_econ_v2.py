#!/usr/bin/env python3
from __future__ import annotations

import json, math, urllib.parse, urllib.request
from typing import Any, Mapping

from backend.research.architecture_factory import a1_gen2_generic_dev_econ_v1 as base

FUNDING_API='https://open-api.bingx.com/openApi/swap/v2/quote/fundingRate'
SUPPORTED_SOURCES={'ohlcv','volume','funding'}
EXTRA_FIELDS={'funding','funding_rate','funding_bps'}


def _funding_rows(symbol:str)->list[dict[str,float]]:
    url=FUNDING_API+'?'+urllib.parse.urlencode({'symbol':symbol,'limit':100})
    with urllib.request.urlopen(url,timeout=30) as r: payload=json.loads(r.read().decode())
    if isinstance(payload,dict) and payload.get('code') not in (None,0): raise RuntimeError(f"BINGX_FUNDING:{payload.get('code')}:{payload.get('msg')}")
    rows=payload.get('data',[]) if isinstance(payload,dict) else []
    cutoff=base._cutoff_ms(); out=[]
    for x in rows:
        if not isinstance(x,Mapping): continue
        ts=x.get('fundingTime') or x.get('time') or x.get('timestamp'); rate=x.get('fundingRate') if x.get('fundingRate') is not None else x.get('rate')
        if ts is None or rate is None: continue
        try: ts=int(ts); rate=float(rate)
        except Exception: continue
        if ts<cutoff: out.append({'ts':ts,'rate':rate})
    return sorted({int(x['ts']):x for x in out}.values(),key=lambda x:int(x['ts']))


def _attach_funding(rs:list[dict[str,float]], fr:list[dict[str,float]])->list[dict[str,float]]:
    if not rs or not fr:return []
    first=int(fr[0]['ts']); j=-1; current=None; out=[]
    for raw in rs:
        ts=int(raw['ts'])
        if ts<first: continue
        while j+1<len(fr) and int(fr[j+1]['ts'])<=ts:
            j+=1; current=float(fr[j]['rate'])
        if current is None: continue
        row=dict(raw); row['funding']=current; row['funding_rate']=current; row['funding_bps']=current*10000.0; out.append(row)
    return out


class Expr(base.Expr):
    def validate(self,s:str):
        tree=base.ast.parse(self.normalize(s),mode='eval')
        allowed_names={'open','high','low','close','volume',*EXTRA_FIELDS,*self.features.keys(),*self.FUNCS}
        for n in base.ast.walk(tree):
            if isinstance(n,base.ast.Name):
                if n.id not in allowed_names: raise ValueError(f'UNKNOWN_NAME:{n.id}')
                continue
            if isinstance(n,base.ast.Expression|base.ast.Load|base.ast.Constant): continue
            if isinstance(n,base.ast.BinOp) and isinstance(n.op,self.ALLOWED_BIN): continue
            if isinstance(n,base.ast.BoolOp) and isinstance(n.op,self.ALLOWED_BOOL): continue
            if isinstance(n,base.ast.UnaryOp) and isinstance(n.op,self.ALLOWED_UNARY): continue
            if isinstance(n,base.ast.Compare) and all(isinstance(op,self.ALLOWED_CMP) for op in n.ops): continue
            if isinstance(n,base.ast.IfExp): continue
            if isinstance(n,base.ast.Call) and isinstance(n.func,base.ast.Name) and n.func.id in self.FUNCS: continue
            if isinstance(n,self.ALLOWED_BIN+self.ALLOWED_BOOL+self.ALLOWED_UNARY+self.ALLOWED_CMP): continue
            raise ValueError(f'UNSUPPORTED_AST:{type(n).__name__}')
        return tree

    def _series_value(self,name:str,j:int):
        if j<0 or j>=len(self.rows): return None
        if name in {'open','high','low','close','volume',*EXTRA_FIELDS}:
            v=self.rows[j].get(name); return float(v) if isinstance(v,(int,float)) and math.isfinite(float(v)) else None
        arr=self.features.get(name); return arr[j] if arr and j<len(arr) else None

    def env(self):
        env=super().env(); i=self.i
        for k in EXTRA_FIELDS: env[k]=self._series_value(k,i)
        return env


def evaluate_candidate(candidate:Mapping[str,Any])->dict[str,Any]:
    cid=str(candidate.get('candidate_id') or ''); req=set(candidate.get('required_sources') or [])
    if not req or not req.issubset(SUPPORTED_SOURCES):
        return {'candidate_id':cid,'state':'SKIP_HISTORY_SOURCE_NOT_READY','required_sources':sorted(req),'supported_sources':sorted(SUPPORTED_SOURCES),'economic_pass':False}
    if 'funding' not in req: return base.evaluate_candidate(candidate)
    spec=candidate.get('executable_spec')
    if not isinstance(spec,Mapping): return {'candidate_id':cid,'state':'REJECT_SPEC_MISSING','economic_pass':False}
    interval=str(spec.get('bar_interval') or '')
    if interval not in base.INTERVAL_MAP:return {'candidate_id':cid,'state':'REJECT_INTERVAL','economic_pass':False}
    entry=str(spec.get('entry_rule') or ''); side_rule=str(spec.get('side_rule') or ''); exit_rule=str(spec.get('exit_rule') or 'time_stop')
    try: hold=int(spec.get('max_hold_bars') or 0)
    except Exception: hold=0
    if not 1<=hold<=720:return {'candidate_id':cid,'state':'REJECT_HOLD','economic_pass':False}
    alltr=[]; source={}; first_ts=None; last_ts=None
    try:
        for symbol in base.SYMBOLS:
            raw=base.bars(symbol,interval); fr=_funding_rows(symbol); rs=_attach_funding(raw,fr)
            source[symbol]={'bars':len(rs),'funding_rows':len(fr),'funding_first_ts':int(fr[0]['ts']) if fr else None,'funding_last_ts':int(fr[-1]['ts']) if fr else None}
            if rs:
                first_ts=min(first_ts or int(rs[0]['ts']),int(rs[0]['ts'])); last_ts=max(last_ts or int(rs[-1]['ts']),int(rs[-1]['ts']))
            features:dict[str,list[float|None]]={}; eng=Expr(rs,features)
            for f in spec.get('features') or []:
                name=str(f.get('name') or '').strip(); formula=base._feature_formula(str(f.get('formula') or ''))
                if not name or not formula:raise ValueError('FEATURE_EMPTY')
                eng.validate(formula); arr=[]; features[name]=arr
                for i in range(len(rs)):
                    try:
                        v=eng.eval(formula,i); arr.append(float(v) if isinstance(v,(int,float)) and math.isfinite(float(v)) else None)
                    except (TypeError,ZeroDivisionError,ValueError):arr.append(None)
            eng=Expr(rs,features); eng.validate(entry); base._validate_side(side_rule,eng)
            time_only=exit_rule.strip().lower() in {'time_stop','time stop','max_hold','max_hold_bars'}
            if not time_only:eng.validate(exit_rule)
            i=max(30,1); entry_eval_errors=0
            while i<len(rs)-1:
                try: fire=bool(eng.eval(entry,i))
                except (TypeError,ZeroDivisionError,ValueError): entry_eval_errors+=1; fire=False
                if not fire:i+=1;continue
                side=base._side(side_rule,eng,i)
                if side not in {'long','short'}:raise ValueError('SIDE_RULE_UNSUPPORTED')
                entry_i=i+1; entry_px=rs[entry_i]['open']; exit_i=min(entry_i+hold-1,len(rs)-1)
                if not time_only:
                    for j in range(entry_i,min(entry_i+hold,len(rs))):
                        try:
                            if bool(eng.eval(exit_rule,j)):exit_i=j;break
                        except (TypeError,ZeroDivisionError,ValueError):raise ValueError('EXIT_RULE_UNSUPPORTED')
                exit_px=rs[exit_i]['close']; gross=(exit_px/entry_px-1.0)*10000*(1 if side=='long' else -1); net=gross-base.COST_BPS
                alltr.append({'symbol':symbol,'side':side,'gross_bps':gross,'net_bps':net,'entry_ts':int(rs[entry_i]['ts']),'exit_ts':int(rs[exit_i]['ts'])})
                i=max(i+1,exit_i+1)
            if entry_eval_errors>max(50,len(rs)//2):raise ValueError(f'ENTRY_RUNTIME_ERRORS:{entry_eval_errors}')
    except Exception as exc:
        return {'candidate_id':cid,'state':'REJECT_UNEXECUTABLE_SPEC','error':f'{type(exc).__name__}:{str(exc)[:240]}','economic_pass':False}
    net=[x['net_bps'] for x in alltr]; gross=[x['gross_bps'] for x in alltr]
    days=max(1e-9,((last_ts or base._cutoff_ms())-(first_ts or base._cutoff_ms()))/86_400_000)
    metrics={'trades':len(net),'gross_expectancy_bps':sum(gross)/len(gross) if gross else None,'net_expectancy_bps':sum(net)/len(net) if net else None,'net_pnl_bps':sum(net),'profit_factor':base._pf(net),'payoff':base._payoff(net),'win_rate':sum(1 for x in net if x>0)/len(net) if net else None,'drawdown_bps':base._dd(net),'cost_bps_per_trade':base.COST_BPS,'events_per_day':len(net)/days,'net_bps_per_calendar_day':sum(net)/days,'development_days':days}
    common={'candidate_id':cid,'strategy_id':candidate.get('strategy_id'),'provider':candidate.get('provider'),'metrics':metrics,'source_summary':source,'development_only':True,'prospective':False,'uses_data_strictly_before_gen1_boundary':True,'boundary':base.BOUNDARY,'funding_history_mode':'BINGX_PUBLIC_FUNDING_HISTORY_FILTERED_STRICTLY_PRE_BOUNDARY'}
    if not net:return {**common,'state':'FAIL_INSUFFICIENT_EVENTS','economic_pass':False}
    passed=bool(len(net)>=12 and (metrics['net_expectancy_bps'] or 0)>0 and (metrics['profit_factor'] or 0)>1 and (metrics['net_bps_per_calendar_day'] or 0)>0)
    return {**common,'state':'PASS_DEVELOPMENT_ECONOMICS' if passed else 'FAIL_DEVELOPMENT_ECONOMICS','economic_pass':passed}


def evaluate_queue(queue:list[Mapping[str,Any]])->dict[str,Any]:
    rows=[evaluate_candidate(c) for c in queue]; passed=[x for x in rows if x.get('economic_pass')]; failed=[x for x in rows if x.get('state')=='FAIL_DEVELOPMENT_ECONOMICS']; insufficient=[x for x in rows if x.get('state')=='FAIL_INSUFFICIENT_EVENTS']; skipped=[x for x in rows if str(x.get('state') or '').startswith('SKIP_')]; rejected=[x for x in rows if str(x.get('state') or '').startswith('REJECT_')]
    return {'schema_version':'zel.a1_gen2_generic_dev_econ.v2','development_only':True,'prospective':False,'cost_bps_per_trade':base.COST_BPS,'boundary':base.BOUNDARY,'supported_sources':sorted(SUPPORTED_SOURCES),'candidate_count':len(rows),'economic_pass_count':len(passed),'economic_fail_count':len(failed),'insufficient_event_count':len(insufficient),'source_skip_count':len(skipped),'spec_reject_count':len(rejected),'passes':passed,'rows':rows,'selection_authority':False,'promotion_authority':False,'execution_authority':'NONE','order_authority':'BLOCKED','live_trade_authority':'BLOCKED','exchange_order_submitted':False,'protected_mutations':0}
