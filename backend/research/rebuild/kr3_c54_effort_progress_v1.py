"""One C54 child: veto high volume without bullish recovery-body progress.

Only completed signal/pullback observations. No new thresholds, exit, sizing,
orders, source I/O or ex-post winner labels. C54 ATR and C51 protection retained.
"""
from copy import deepcopy
from unittest.mock import patch
import math
from backend.research.rebuild import kr3_c51_entry_context_v1 as parent
BAR=parent.BAR
RULE_ID='KR3_C54_RECOVERY_EFFORT_WITHOUT_PROGRESS_V1'
RULES={'B':RULE_ID}
VETO='RECOVERY_EFFORT_WITHOUT_PROGRESS_VETO'
MISSING='RECOVERY_VOLUME_CONTEXT_UNAVAILABLE'


def participation(rows,i,q):
    if q is None or not 0<=q<i-1:
        return {'available':False,'veto':True,'reason':MISSING}
    before=rows[q+1:i];volumes=[r['volume'] for r in before];bodies=[abs(r['close']-r['open']) for r in before]
    values=volumes+[rows[i]['volume']]+bodies+[rows[i]['open'],rows[i]['close']]
    if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in values):
        raise ValueError('INVALID_PARTICIPATION_SOURCE')
    if min(volumes+[rows[i]['volume']])<0:raise ValueError('NEGATIVE_VOLUME')
    n=len(before);volume=sum(volumes)/n;body=sum(bodies)/n;progress=max(0.,rows[i]['close']-rows[i]['open'])
    available=volume>0
    high=available and rows[i]['volume']>volume
    weak=progress<=body
    return {'available':available,'veto':not available or (high and weak),
            'reason':MISSING if not available else VETO if high and weak else None,
            'pullback_start_index':q+1,'pullback_end_index':i-1,'pullback_count':n,
            'pullback_last_available_at':rows[i-1]['bar_close_ts'],
            'mean_pullback_volume':volume,'signal_volume':rows[i]['volume'],
            'mean_pullback_abs_body':body,'signal_bull_body':progress,
            'relative_volume':rows[i]['volume']/volume if available else None,
            'higher_volume':high,'weak_bull_body':weak,'available_at':rows[i]['bar_close_ts'],
            'source_bars':[dict(index=j,ts=rows[j]['bar_close_ts'],open=rows[j]['open'],close=rows[j]['close'],volume=rows[j]['volume']) for j in range(q+1,i+1)]}


def replay(rows,bundle,*,eval_start_ms,eval_end_ms,cost_model,enabled=True,mode='B',reference_checkpoint=None):
    if mode!='B' or type(enabled) is not bool:raise ValueError('C54_CHILD_MODE')
    kwargs=dict(eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost_model=cost_model,mode='B',reference_checkpoint=reference_checkpoint)
    if not enabled:return parent.replay(rows,bundle,**kwargs)
    original_observations=parent.observations;original_allowed=parent.allowed
    def observations(r,b):
        out=original_observations(r,b)
        for i,obs in out.items():obs['participation']=participation(r,i,obs['trend_index'])
        return out
    def allowed(obs,mode):return original_allowed(obs,mode) and not obs['participation']['veto']
    with patch.object(parent,'observations',observations),patch.object(parent,'allowed',allowed):
        result=parent.replay(rows,bundle,**kwargs)
    for event in result['events']:
        if event['exclusion_reason']=='ENTRY_CONTEXT_B_VETO' and event['entry_context']['B']:
            event['exclusion_reason']=event['entry_context']['participation']['reason']
    result['audit'].update(rule=RULE_ID,change_axis='RECOVERY_VOLUME_RELATIVE_TO_PULLBACK_AND_BULL_BODY',
        direct_parent=parent.RULES['B'],entry_context_veto_T=sum(e['exclusion_reason'] in ('ENTRY_CONTEXT_B_VETO',VETO,MISSING) for e in result['events']),
        effort_progress_veto_T=sum(e['exclusion_reason']==VETO for e in result['events']),
        participation_missing_T=sum(e['exclusion_reason']==MISSING for e in result['events']),
        C54_ATR_preserved=True,C51_exit_preserved=True)
    return result
