#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from collections import defaultdict
from pathlib import Path

DIRECT_ROLES={
  'direct_crypto_alpha','direct_crypto_futures_alpha','direct_crypto_futures_signal',
  'direct_crypto_microstructure','direct_bitcoin_alpha','direct_crypto_portfolio_alpha'
}
IMPLEMENTATION_ROLES={'reproducible_implementation','implementation_case_study'}

FAMILIES={
  'trend_momentum': {
    'components': {'trend_following','time_series_momentum','moving_average_ratio','momentum','momentum_confirmation'},
    'minimum_direct': 3,
    'purpose': 'directional persistence / pullback-continuation prior'
  },
  'volatility_breakout': {
    'components': {'donchian_breakout','donchian_ensemble','breakout','atr_breakout','volatility_squeeze','volatility_expansion','bollinger_breakout'},
    'minimum_direct': 3,
    'purpose': 'compression/range escape and volatility expansion prior'
  },
  'regime_mean_reversion': {
    'components': {'mean_reversion','volume_profile','local_extrema'},
    'minimum_direct': 3,
    'purpose': 'conditional fade/reclaim only in validated non-trend regimes'
  },
  'pairs_stat_arb': {
    'components': {'cointegration','pairs_trading','copula','mean_reverting_spread','mispricing_index'},
    'minimum_direct': 3,
    'purpose': 'orthogonal relative-value / spread-reversion family'
  },
  'microstructure_ofi': {
    'components': {'order_flow_imbalance','absorption','liquidity_fragility','adverse_selection','microstructure','spread_state'},
    'minimum_direct': 3,
    'purpose': 'short-horizon entry quality and adverse-selection filter/family'
  },
  'session_clock': {
    'components': {'session_filter','clock_phase','intraday_seasonality','market_timing','seasonality'},
    'minimum_direct': 3,
    'purpose': 'time-of-day / clock-phase conditional edge and routing'
  },
}

CROSS_CUTTING={
  'cost_turnover_hurdle': {'transaction_costs','cost_hurdle','turnover_control','cost_control','fee_drag','funding_rate','slippage'},
  'volatility_risk_normalization': {'atr_risk','atr_stop','atr_filter','volatility_sizing','volatility_trailing','volatility_regime'},
  'regime_no_trade': {'regime_filter','volatility_regime','no_trade_zone','adx_regime'},
  'liquidity_selection': {'liquidity_filter','liquidity_state','market_depth','spread_state'},
  'fresh_oos_integrity': {'fresh_oos','walk_forward','oos_validation','negative_control','data_integrity','multiple_testing'},
}

def main():
  ap=argparse.ArgumentParser(); ap.add_argument('--evidence',required=True); ap.add_argument('--out',required=True); a=ap.parse_args()
  d=json.loads(Path(a.evidence).read_text()); rows=d['records']
  fam_out=[]
  for fid,cfg in FAMILIES.items():
    hits=[]; direct=[]; impl=[]
    for r in rows:
      overlap=sorted(set(r.get('components',[])) & cfg['components'])
      if not overlap: continue
      item={'id':r['id'],'tier':r['tier'],'role':r['role'],'matched':overlap}
      hits.append(item)
      if r['role'] in DIRECT_ROLES: direct.append(item)
      if r['role'] in IMPLEMENTATION_ROLES: impl.append(item)
    state='READY_FOR_EXECUTABLE_SPEC' if len(direct)>=cfg['minimum_direct'] else 'HOLD_MORE_DIRECT_EVIDENCE'
    fam_out.append({'family':fid,'state':state,'purpose':cfg['purpose'],'direct_count':len(direct),'implementation_count':len(impl),'all_support_count':len(hits),'direct_ids':[x['id'] for x in direct],'implementation_ids':[x['id'] for x in impl]})
  cross=[]
  for name,comps in CROSS_CUTTING.items():
    ids=[r['id'] for r in rows if set(r.get('components',[])) & comps and r['role']!='practitioner_prior']
    cross.append({'mechanism':name,'support_count':len(ids),'ids':ids})
  ready=[x['family'] for x in fam_out if x['state']=='READY_FOR_EXECUTABLE_SPEC']
  payload={
    'schema_version':'zel.evidence_alpha.v3.consensus.v1',
    'state':'PASS_STAGE2_CONSENSUS_READY' if ready else 'HOLD_STAGE2_NO_READY_FAMILY',
    'evidence_records':len(rows),
    'family_direct_floor':3,
    'families':fam_out,
    'ready_families':ready,
    'cross_cutting_mechanisms':cross,
    'common_dna_from_dual_audit':['trend_following','cointegration','order_flow_imbalance'],
    'rules':{
      'community_never_satisfies_direct_floor':True,
      'negative_controls_do_not_create_alpha':True,
      'cross_asset_mechanics_do_not_satisfy_direct_crypto_floor':True,
      'youtube_counted':0,
      'stage3_requires_executable_spec_and_independent_ai_review':True,
      'one_axis_ablation_only_after_base_micro_viability':True
    },
    'research_only':True,'execution_authority':'NONE','order_authority':'BLOCKED','promotion_authority':False,'selection_authority':False,'stage3_unlocked':False
  }
  Path(a.out).write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
  print(json.dumps(payload,sort_keys=True))

if __name__=='__main__': main()
