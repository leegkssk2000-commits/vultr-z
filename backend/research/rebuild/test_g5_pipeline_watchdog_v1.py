from backend.research.rebuild.g5_pipeline_watchdog_v1 import funnel


def test_signal_starvation():
    assert funnel({'raw_signal_count':0},{})['classification']=='SIGNAL_STARVATION'


def test_admission_rejecting_all_raw_signals():
    assert funnel({'raw_signal_count':3,'collector_actionable_signal_count':0},{})['classification']=='ADMISSION_REJECTING_ALL_RAW_SIGNALS'


def test_live_maturing():
    assert funnel({'collector_actionable_signal_count':2,'maturing_count':2},{})['classification']=='SIGNAL_LIVE_MATURING'


def test_closed_candidate_waiting_settlement():
    assert funnel({'closed_candidate_count':1},{})['classification']=='CLOSED_CANDIDATE_WAITING_SETTLEMENT_OR_WRITER'


def test_negative_economics():
    x=funnel({}, {'closed_T':5,'metrics':{'net_pnl_bps':-820.2,'profit_factor':0.0}})
    assert x['classification']=='ECONOMIC_EVIDENCE_NEGATIVE'
