"""Saved observations and source/accounting bindings only. Never strategy replay."""
from collections import Counter
from datetime import datetime,timezone
from backend.research.rebuild import jc_gate_probe_v1 as g
p=g.prior;OUT=g.OUT

def need(ok,message):
    if not ok:raise RuntimeError(message)

def utc(ts):return '—' if ts is None else datetime.fromtimestamp(ts/1000,timezone.utc).strftime('%Y-%m-%d %H:%M')

def render():
    s=p.read(OUT/'DIAGNOSTIC_SUMMARY.json');econ=p.read(OUT/'REFERENCE_ECONOMICS.json')
    lines=['# JC boundary and funnel repair — Issue1252','',
      '**NO_SETUP_AFTER_BOUNDED_REPAIR.** Boundary context repaired; extra wait unchanged because wait-only witness count is zero. Both first FULLs are NOT_RUN; no candidate/evaluation numbers or reservations assigned. Historical 79/142 retained. This is a signal preflight result, not a new zero-trade economic backtest.','',
      '## History eligibility and daily decisions','',
      'Calendar days with sufficient history differ from days after the first eligible fresh daily decision. Six symbols retain sufficient pre-start history, but the boundary candle is first available only at 2024-12-20 00:00 UTC. No claim of fully validated 375-day trading. HYPE has no verified listing origin or invented warmup. The SEEN2026 504-day pre-start prefix is unchanged. Decision counts include a signal exactly at the terminal boundary (pending, no next open).','',
      '|Period|Symbol|Old history days|New history days|First eligible daily decision UTC|Days after first decision|','|---|---|---:|---:|---|---:|']
    for per,syms in s['periods'].items():
        for sym,v in syms.items():
            old=v['ORIGINAL_CONTEXT']['coverage'];new=v['BOUNDARY_CONNECTED']['coverage'];first=new['first_eligible_decision']
            span=0 if first is None else (p.CAL[per]['runoff_end_ms']-first)/g.native.DAY
            lines.append(f"|{per}|{sym}|{old['history_qualified_calendar_days']:.4f}|{new['history_qualified_calendar_days']:.4f}|{utc(first)}|{span:.4f}|")
    lines+=['','## Cumulative gate passes','','Order-dependent cumulative counts; independent evaluability/pass counts and first-failure counts are saved separately. A later zero does not establish that condition as an independent cause.','','|Condition|DEV original|DEV repaired context|SEEN original|SEEN repaired context|','|---|---:|---:|---:|---:|']
    for gate in g.GATES:
        counts=[sum(v[ctx]['cumulative'][gate] for v in s['periods'][per].values()) for per in p.PERIODS for ctx in ('ORIGINAL_CONTEXT','BOUNDARY_CONNECTED')]
        lines.append('|'+gate+'|'+'|'.join(map(str,counts))+'|')
    lines+=['','DEV connected context: 364 first fail history; 2,042 recent high; 214 squeeze; 5 EMA21. SEEN: 786 recent high; 61 squeeze. No complete setup in either context and no wait-only witness.','','|DEV blocker|Available UTC|Close|EMA21|','|---|---|---:|---:|']
    for x in p.read(OUT/'BLOCKING_OBSERVATIONS.json'):
        o=x['observations'];lines.append(f"|{x['symbol']}|{utc(x['available_at'])}|{o['close']:.8f}|{o['EMA21']:.8f}|")
    lines+=['','The source does not mandate two additional days after the handle becomes confirmed. The approval requires a wait-only witness to remove that delay; none exists. Radius2, squeeze3, high365/recent20, geometry, EMA/ATR, no-chase, allocations, stops, targets, 72-hour management and runner are unchanged.','',
      '## Economic reference — saved results only','','Fixed reference-notional trade-bps; terminal values include hypothetical open liquidation costs. These are not account returns or live performance. No repaired-result PnL, avoided losses, missed wins or drawdown is imputed from signal zero.','','|Period|Rule|Closed/open|WR %|Avg win|Avg loss|Payoff|PF|Terminal net|Cost2|Daily DD|','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    fmt=lambda v:'—' if v is None else f'{v:.2f}'
    for per,values in econ.items():
        for name in ('C63_SAVED','JC79_SAVED'):
            m=values[name];vals=[None if m['win_rate'] is None else 100*m['win_rate'],m['average_win_bps'],m['average_loss_bps'],m['realized_payoff'],m['PF'],m['terminal_net_bps'],m['terminal_cost2x_net_bps'],m['marked_DD_trade_sum_bps']]
            lines.append(f"|{per}|{name}|{m['closed']}/{m['open']}|"+'|'.join(fmt(v) for v in vals)+'|')
        lines.append(f'|{per}|JC_REPAIRED NOT_RUN|—|—|—|—|—|—|—|—|—|')
    lines+=['','Repaired risk/attribution (loss tail, streak, exposure, winner coverage, new/excluded/open transitions, partial exits and trailing): NOT_RUN, not zero. JC79 REJECT_KEEP_C63 is preserved. The original source is an options workflow; this remains a disclosed crypto adaptation.','',
      '## Evidence and closure','','All seven raw boundary rows pass exact decimal close and high/low/volume containment. Missing initial 4-hour bars, original day open and prefix quantities remain unverified. No new market GET, OOS, paid AI, baseline replay, FIXED, sweep, order or deployment. Native setup boolean parity was checked for every saved diagnostic observation; final verification recounts saved flags only.','',
      'Source mapping: SOURCE_MAPPING.md. Independent gate counts: DIAGNOSTIC_SUMMARY.json. Full observations: DEV2025/ and SEEN2026/GATE_OBSERVATIONS.json.gz. Original history hashes: PRESERVATION.json. Closure CI/review/merge identifiers are recorded on the PR and Issue1252.','']
    return '\n'.join(lines)

def verify():
    p.check();spec=p.read(OUT/'SPEC.json')
    need(spec['scope']==g.SCOPE,'SCOPE')
    for name,digest in spec['files_sha256'].items():need(p.h(p.ROOT/name)==digest,'FILE_DRIFT:'+name)
    for name,digest in p.read(OUT/'PRESERVATION.json').items():need(p.h(p.ROOT/name)==digest,'PR1251_HISTORY_DRIFT:'+name)
    s=p.read(OUT/'DIAGNOSTIC_SUMMARY.json');need(s['economic_preflight']=='NO_SETUP_AFTER_BOUNDED_REPAIR','OUTCOME')
    need(not s['remove_extra_wait'] and s['wait_only_witness_count']==0 and not any(s['expected_setups'].values()),'NO_SETUP_CONDITION')
    budget=p.read(OUT/'BUDGET.json');prior=p.read(p.OUT/'BUDGET.json')
    q=budget.pop('jc_boundary_funnel_allocation');need(budget==prior,'INHERITED_LEDGER_CHANGED')
    need(q['started']==q['reserved']==q['completed']==q['failed']==0,'NO_EXECUTIONS')
    need((budget['cumulative_actual'],budget['cumulative_actual_evaluations'])==(79,142),'ORDINALS')
    for per in p.PERIODS:
        path=OUT/per/'GATE_OBSERVATIONS.json.gz';need(p.h(path)==s['observation_sha256'][per],'OBSERVATION_HASH')
        for sym,pair in p.gz(path).items():
            for ctx,v in pair.items():
                obs=v['observations'];cumulative={k:0 for k in g.GATES};first=Counter();ind={k:dict(pass_count=0,evaluable=0) for k in g.GATES}
                for x in obs:
                    need(p.CAL[per]['start_ms']<=x['available_at']<=p.CAL[per]['runoff_end_ms'],'DECISION_WINDOW')
                    need(all(z['available_at']<=x['available_at'] for z in x['observations']['pivots']),'FUTURE_PIVOT')
                    flags=x['conditions'];carry=True
                    for k in g.GATES:
                        flag=flags[k];carry=carry and flag is True;cumulative[k]+=int(carry)
                        if flag is not None:ind[k]['evaluable']+=1;ind[k]['pass_count']+=int(flag)
                    first[next((k for k in g.GATES if flags[k] is not True),'PASS')]+=1
                    need(x['all_pass']==all(z is True for z in flags.values()),'ALL_PASS')
                need(v['cumulative']==cumulative and v['independent']==ind and v['first_fail']==dict(first),'FUNNEL_RECOUNT')
                need(v['native_boolean_parity_checked']==len(obs)==v['repaired_boolean_parity_checked'],'PARITY_COUNT')
                need(v['original_setups']==v['no_extra_wait_setups']==0 and not v['wait_only_witnesses'],'PRECHECK_ZERO')
                need({k:x for k,x in v.items() if k not in ('observations','wait_only_witnesses')}==s['periods'][per][sym][ctx],'SUMMARY_RECOUNT')
            if per=='DEV2025':
                *_,receipt,tick=g.inputs(per,sym)
                need(receipt==s['bindings'][sym],'RAW_BOUNDARY_RECEIPT')
        reference=p.read(OUT/'REFERENCE_ECONOMICS.json')[per]
        need(reference['C63_SAVED']==p.a.snapshot(p.old.baseline('C63',per)),'SAVED_C63')
        need(reference['JC79_SAVED']==p.a.snapshot(p.gz(p.OUT/per/'RESULT.json.gz')),'SAVED_JC79')
    need((OUT/'REPORT.md').read_text()==render(),'REPORT_PARITY')
    print('SAVED_BOUNDARY_FUNNEL_AND_HISTORY_PASS; STRATEGY_REPLAYS=0; NEW_FULL=0; 79/142_UNCHANGED')

if __name__=='__main__':verify()
