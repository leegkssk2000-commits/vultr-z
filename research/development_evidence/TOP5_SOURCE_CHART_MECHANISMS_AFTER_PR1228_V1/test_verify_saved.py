"""Synthetic tampering regressions only; never loads a market packet."""
import importlib.util
from pathlib import Path
from copy import deepcopy
import unittest
HERE=Path(__file__).parent
def load(name):
    s=importlib.util.spec_from_file_location('chart_'+name,HERE/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
v=load('verify_saved');r=load('report_saved');a=v.checker(HERE.parents[2])
def rows():return [dict(bar_open_ts=i*v.BAR,bar_close_ts=(i+1)*v.BAR,open=100.,high=102.,low=98.,close=101.,volume=10.) for i in range(25)]
def fixture():
    rs=rows();t=dict(signal_index=19,signal_ts=20*v.BAR,entry_index=20,entry_ts=20*v.BAR,entry_price=100.,fixed_floor=95.,fixed_target=None,
        exit_index=21,exit_ts=21*v.BAR,exit_price=100.,exit_reason='MOMENTUM_NONPOSITIVE_CLOSE_NEXT_OPEN')
    x=dict(kind='HELD_CLOSE_OBSERVATION',signal_index=19,index=20,ts=21*v.BAR,close=101.,floor=95.,target=None,momentum=0.,held_bars=1,exit_reason='MOMENTUM_NONPOSITIVE_CLOSE')
    return dict(trades=[t],open_positions=[],events=[],trace=[x]),rs
def test_first_exit_source_binding():
    raw,rs=fixture();assert v.check_standalone_trace(raw,rs,'M1',a)==1
def test_omitted_held_bar_rejected():
    raw,rs=fixture();raw['trace']=[]
    with unittest.TestCase().assertRaisesRegex(ValueError,'OMISSION'):v.check_standalone_trace(raw,rs,'M1',a)
def test_future_close_rejected():
    raw,rs=fixture();raw['trace'][0]['close']=102.
    with unittest.TestCase().assertRaisesRegex(ValueError,'SOURCE_CLOSE'):v.check_standalone_trace(raw,rs,'M1',a)
def test_priority_tampering_rejected():
    raw,rs=fixture();raw['trades'][0]['fixed_floor']=101.;raw['trace'][0]['floor']=101.
    with unittest.TestCase().assertRaisesRegex(ValueError,'FIRST_EXIT_REASON'):v.check_standalone_trace(raw,rs,'M1',a)
def test_actual_open_binding_rejects_close_fill():
    raw,rs=fixture();raw['trades'][0]['entry_price']=101.
    with unittest.TestCase().assertRaisesRegex(ValueError,'SOURCE_ENTRY_OPEN'):v.check_source(raw,rs,'M1',a)
def test_sample_order_not_best_profit():
    source=dict(trades=[dict(net_bps=100.,signal_ts=2,symbol='X',signal_index=2),dict(net_bps=1.,signal_ts=1,symbol='X',signal_index=1)],open_observations=[],events=[])
    assert r.samples(source)['WIN']['net_bps']==1.

class SavedEvidenceTests(unittest.TestCase):
    pass
for _name,_fn in list(globals().items()):
    if _name.startswith('test_') and callable(_fn):setattr(SavedEvidenceTests,_name,lambda self,fn=_fn:fn())
del _name,_fn
if __name__=='__main__':unittest.main()
