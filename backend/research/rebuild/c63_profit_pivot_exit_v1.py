"""One C63 exit-only hypothesis. No source loading, orders or sweep.

Confirmed radius2 low strictly above accrued modelled break-even can ratchet
protection. A close tests ONLY the previously activated level. Actual native
exits take precedence; liquidation remains the native next-observed-open path.
"""
from dataclasses import dataclass
from math import isfinite
from unittest.mock import patch

RULE_ID='C63_CONFIRMED_PROFIT_PIVOT_LOW_EXIT_V1'
REASON='CONFIRMED_PROFIT_PIVOT_CLOSE'
RADIUS=2

@dataclass
class Protection:
    entry_index: int
    entry_price: float
    active: float | None = None
    known_index: int | None = None
    pivot_index: int | None = None
    last_index: int | None = None

    def step(self,index,close,cost_bps,new_pivot,native_reason):
        if type(index) is not int or index<self.entry_index or (self.last_index is not None and index!=self.last_index+1):
            raise ValueError('PIVOT_CLOSE_ORDER')
        if any(type(v) not in (int,float) or not isfinite(v) for v in (close,cost_bps,self.entry_price)) or min(close,self.entry_price)<=0 or cost_bps<0:
            raise ValueError('PIVOT_PRICE_COST')
        self.last_index=index
        before=self.active
        triggered=before is not None and self.known_index<index and close<before
        selected=native_reason if native_reason is not None else REASON if triggered else None
        threshold=self.entry_price*(1+cost_bps/10000)
        update=None
        if new_pivot is not None:
            p=new_pivot
            if p.get('kind')!='LOW' or p.get('known_index')!=index or p.get('index')!=index-RADIUS:
                raise ValueError('PIVOT_CONFIRMATION_CLOCK')
            if type(p.get('price')) not in (int,float) or not isfinite(p['price']) or p['price']<=0:
                raise ValueError('PIVOT_LEVEL')
            if selected is None and p['index']>=self.entry_index and p['price']>threshold and (before is None or p['price']>before):
                self.active=p['price'];self.known_index=index;self.pivot_index=p['index'];update=dict(p)
        return dict(index=index,close=close,cost_bps=cost_bps,break_even=threshold,
            previous_level=before,previous_level_broken=triggered,native_reason=native_reason,
            selected_reason=selected,newly_confirmed_low=new_pivot,activated=update,
            active_after=self.active,active_known_index=self.known_index,
            guard_semantics='TEST_OLD_LEVEL_THEN_RATCHET_FOR_SUBSEQUENT_CLOSE')


def position(bars,signal,variant,features,end,cost_model,original_path,original_exit):
    from backend.research.rebuild import chart_mechanism_execution_v1 as engine
    from backend.research.rebuild.chart_mechanism_features_v1 import confirmed_pivots
    from backend.research.rebuild.kr3_profit_zone_exit_v1 import decision_cost
    if variant!='M1':raise ValueError('C63_ONLY')
    i=signal['signal_index'];ei=i+1;entry=bars[ei]
    state=Protection(ei,entry.open);observations=[]
    def decide(v,close,floor,target,momentum,held):
        j=i+held;stamp=bars[j].open_ts+engine.BAR
        native=original_exit(v,close,floor,target,momentum,held)
        cost=decision_cost(entry.open_ts,stamp,cost_model)['cost_bps']
        # The canonical helper itself sees ONLY completed prefix j. No future
        # bar or retrospective pivot annotation is fed to this decision.
        newly=[p for p in confirmed_pivots(bars,j,radius=RADIUS) if p['kind']=='LOW' and p['known_index']==j]
        if len(newly)>1:raise ValueError('PIVOT_DUPLICATE')
        obs=state.step(j,close,cost,newly[0] if newly else None,native)
        observations.append(dict(obs,kind='PROFIT_PIVOT_OBSERVATION',signal_index=i,ts=stamp,held_bars=held))
        return obs['selected_reason']
    with patch.object(engine,'exit_reason',decide):
        trade,opened,trace=original_path(bars,signal,variant,features,end)
    (trade if trade is not None else opened).update(profit_pivot_rule=RULE_ID,profit_pivot_radius=RADIUS,
        profit_pivot_last_level=state.active,profit_pivot_available_index=state.known_index,
        protection_is_guaranteed_profit=False)
    return trade,opened,trace+observations


def replay(rows,*,eval_start_ms,eval_end_ms,cost_model,enabled=True,fixed_signal_indices=None):
    # Reuse the already checked C63 FIXED/FULL entry/occupancy adapter. Replace
    # only its position hook in this one serial owner, restoring every hook.
    from backend.research.rebuild import c63_failed_breakout_exit_v1 as wiring
    with patch.object(wiring,'position',position),patch.object(wiring,'RULE_ID',RULE_ID),patch.object(wiring,'REASON',REASON):
        result=wiring.replay(rows,eval_start_ms=eval_start_ms,eval_end_ms=eval_end_ms,cost_model=cost_model,
                             enabled=enabled,fixed_signal_indices=fixed_signal_indices)
    if enabled:result['audit'].update(change_axis='EXIT_ONLY_CONFIRMED_PROFIT_PIVOT',radius=RADIUS,
        no_partial_realization=True,no_native_hold_extension=True,activation_requires_current_accrued_cost=True,
        future_profit_or_fill_guarantee=False)
    return result
