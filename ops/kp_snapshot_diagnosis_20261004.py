"""Fixed-target read-only followup to PR1353; never starts the old producers."""
import json
from pathlib import Path
import time

# CI concatenates the reviewed helper above this file for stdin-only SSH.
if 'capture' not in globals():
    from ops.kp_committed_cursor_snapshot_v1 import capture, load, read_relative, read_relative_record, sha

ROOT = Path('/home/z/z/runtime/scalp7_broad_v2_20260915')
WORKTREE = Path('/home/z/worktrees/scalp7-broad-v2-20260915')
CANDIDATE = 'scalp7_keltner_hg_parent_utc30m_v2'
PIN = 'a5c2d7d6888b1cbf5e5c851c66b11127736fda94fd58f0484e19381c7e1efca9'


def state_metadata(folder: str) -> dict:
    result = {'folder': folder}
    for filename in ('FREEZE.json', 'STATUS.json', 'STATE.json'):
        try:
            raw, identity = read_relative_record(ROOT, folder + '/' + filename, 64 * 1024 * 1024)
            d = load(raw)
            item = {'sha256': sha(raw), 'file_mtime_ns': identity['mtime_ns'], 'read_file_identity': identity,
                    'metadata': {k:d[k] for k in ('schema', 'state', 'reason', 'observed_at_ms', 'last_poll_ms',
                                                'poll_count', 'cursors', 'source_cursor_sha256', 'freeze_sha256',
                                                'config_sha256', 'state_or_signal_cursor_advanced') if k in d}}
            if filename == 'STATE.json':
                item['claimed_state_sha256'] = d.get('state_sha256')
                item['canonical_serializer_check'] = 'NOT_ASSERTED_BY_METADATA_PROJECTION'
                evaluations = d.get('evaluations', {})
                if CANDIDATE in evaluations:
                    row = evaluations[CANDIDATE]
                    item['candidate_evaluation_clock'] = {k:row[k] for k in
                         ('last_complete_decision_close_ms', 'evaluated_at_ms', 'input_snapshot_cutoff_ms', 'state') if k in row}
                item['signal_fill_position_trade_bodies_exported'] = False
            result[filename] = item
        except Exception as exc:
            result[filename] = {'error_type': type(exc).__name__}
    return result


def main():
    report = {'schema':'kp30.snapshot_diagnosis.v1', 'candidate':CANDIDATE,
              'observed_at_ms':time.time_ns()//1_000_000, 'service_changes':0,
              'new_collectors':0, 'market_runs':0, 'shared_runtime_replaced':False,
              'snapshot_implementation':'ISOLATED_READONLY_METADATA_NOT_ACTIVATED_MARKET_READER'}
    report['before'] = {x:state_metadata(x) for x in ('fresh_forward','observed_paper_clock_v3')}
    report['live_module_hashes'] = {}
    for name in ('scalp7_fresh_source_v2.py','scalp7_fresh_forward_v2.py','scalp7_observed_paper_v3.py','scalp7_positive_lanes_v2.py'):
        try:
            raw=read_relative(WORKTREE,'backend/research/rebuild/'+name,200000)
            report['live_module_hashes'][name]=sha(raw)
        except Exception as exc:report['live_module_hashes'][name]={'error_type':type(exc).__name__}
    try:
        report['snapshot']=capture(ROOT/'fresh_1m_verified',PIN,after_capture=lambda:time.sleep(20),time_budget_s=145)
    except Exception as exc:
        report['snapshot']={'metadata_snapshot_pass':False,'error_type':type(exc).__name__,
                            'error_code':str(exc) if type(exc).__name__=='SnapshotError' else 'READ_OR_SCHEMA_ERROR'}
    report['after'] = {x:state_metadata(x) for x in ('fresh_forward','observed_paper_clock_v3')}
    report['all_use_history_certified']=False
    report['execution_ready']=False
    print(json.dumps(report,sort_keys=True,separators=(',', ':'),allow_nan=False))

if __name__ == '__main__':main()
