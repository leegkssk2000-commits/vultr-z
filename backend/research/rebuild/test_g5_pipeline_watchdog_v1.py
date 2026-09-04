from backend.research.rebuild.g5_pipeline_watchdog_v1 import funnel


def run() -> None:
    assert funnel({'raw_signal_count':0},{})['classification']=='SIGNAL_STARVATION'
    assert funnel({'raw_signal_count':3,'collector_actionable_signal_count':0},{})['classification']=='ADMISSION_REJECTING_ALL_RAW_SIGNALS'
    assert funnel({'collector_actionable_signal_count':2,'maturing_count':2},{})['classification']=='SIGNAL_LIVE_MATURING'
    assert funnel({'closed_candidate_count':1},{})['classification']=='CLOSED_CANDIDATE_WAITING_SETTLEMENT_OR_WRITER'
    x=funnel({}, {'closed_T':5,'metrics':{'net_pnl_bps':-820.2,'profit_factor':0.0}})
    assert x['classification']=='ECONOMIC_EVIDENCE_NEGATIVE'
    print('PASS_G5_PIPELINE_WATCHDOG_REGRESSION')


if __name__ == '__main__':
    run()
