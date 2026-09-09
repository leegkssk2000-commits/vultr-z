"""Two price-only retracement children. No AVWAP, volume, orders, or I/O.

Reuse the prior causal pivot definition and zones, not its AVWAP condition.
This is a new experiment; old source-blocked T1/F1/F0 remain unchanged.
"""
from unittest.mock import patch
from backend.research.rebuild import chart_mechanism_features_v1 as f
BAR=f.BAR_MS
MODES=('FIB','SHIFTED')
RULES={m:'C54_PRICE_ONLY_'+m+'_AFTER_PR1230_V1' for m in MODES}


def context(rows,obs,mode):
    if mode not in MODES:raise ValueError('PRICE_ZONE_MODE')
    i,q=obs['signal_index'],obs['trend_index']
    # Never read volume; a neutral unused member only satisfies the old Bar type.
    bars=[f.Bar(r['bar_open_ts'],r['open'],r['high'],r['low'],r['close'],0.) for r in rows[:i+1]]
    f.validate(bars)
    result=dict(mode=mode,signal_index=i,available_at=rows[i]['bar_close_ts'],
                eligible=False,reason='NO_CONFIRMED_PRICE_ANCHOR',anchor=None,
                depth=None,pullback_low=None,pullback_start=None,pullback_end=None,
                volume_used=False,avwap_used=False)
    if q is None:return result
    if not 0<=q<i-1:raise ValueError('NONCONTIGUOUS_PULLBACK')
    anchor=f.known_upswing(bars,i,q)
    if anchor is None:return result
    level=min(b.low for b in bars[q+1:i])
    depth=f.retracement(anchor['low']['price'],anchor['high']['price'],level)
    eligible=f.in_zone(depth,mode)
    return dict(result,anchor=anchor,depth=depth,pullback_low=level,pullback_start=q+1,pullback_end=i-1,
                eligible=eligible,reason=None if eligible else 'PRICE_RETRACEMENT_ZONE_VETO')


def replay(rows,bundle,*,eval_start_ms,eval_end_ms,cost_model,mode='FIB',enabled=True,reference_checkpoint=None):
    from backend.research.rebuild import kr3_c51_entry_context_v1 as parent
    if mode not in MODES or type(enabled) is not bool:raise ValueError('PRICE_ONLY_MODE')
    kw=dict(eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost_model=cost_model,mode='B',reference_checkpoint=reference_checkpoint)
    if not enabled:return parent.replay(rows,bundle,**kw)
    observe,admit=parent.observations,parent.allowed
    def observations(r,b):
        out=observe(r,b)
        for i,o in out.items():o['price_context']=context(r,o,mode)
        return out
    def allowed(o,m):return admit(o,m) and o['price_context']['eligible']
    with patch.object(parent,'observations',observations),patch.object(parent,'allowed',allowed):
        result=parent.replay(rows,bundle,**kw)
    for e in result['events']:
        if e['exclusion_reason']=='ENTRY_CONTEXT_B_VETO' and e['entry_context']['B']:
            e['exclusion_reason']=e['entry_context']['price_context']['reason']
    result['audit'].update(rule=RULES[mode],direct_parent=parent.RULES['B'],C54_exit_unchanged=True,
        original_volume_unchanged=True,volume_used=False,avwap_used=False,
        original_TF_unchanged=True,mode=mode)
    return result
