from apscheduler.schedulers.background import BackgroundScheduler
from engine.signal_hub import dispatch_signals
from engine.risk_unit import risk_check

_sched = BackgroundScheduler()

def main_loop():
    dispatch_signals()
    risk_check()

def start():
    if not _sched.running:
        _sched.add_job(main_loop, 'interval', seconds=10, id='main_loop', replace_existing=True)
        _sched.start()