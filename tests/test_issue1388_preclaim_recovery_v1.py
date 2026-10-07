import copy
import pytest
from ops import issue1388_preclaim_recovery_v1 as r


def evidence():
    run = dict(id=r.ORIGINAL_RUN, head_sha=r.ORIGINAL_COMMIT, event='push', run_attempt=1, status='completed', conclusion='cancelled')
    job = dict(id=r.ORIGINAL_JOB, run_id=r.ORIGINAL_RUN, run_attempt=1, name=r.JOB_NAME, status='completed', conclusion='cancelled', runner_id=0, runner_name='', steps=[])
    return run, job


def test_exact_zero_step_cancel_is_admission_not_economic_consumption():
    run, job = evidence()
    r.verify_unstarted(run, job, r.ORIGINAL_COMMIT, r.ORIGINAL_RUN, r.ORIGINAL_JOB)


@pytest.mark.parametrize('field,value', [('runner_id',2),('runner_name','host'),('steps',None),('steps',[{'name':'Set up job'}]),('conclusion','failure'),('run_attempt',2),('run_id',1)])
def test_unconfirmed_or_started_job_never_recovers(field,value):
    run, job = evidence();job[field]=value
    with pytest.raises(r.screen.ScreenError):r.verify_unstarted(run,job,r.ORIGINAL_COMMIT,r.ORIGINAL_RUN,r.ORIGINAL_JOB)


@pytest.mark.parametrize('field,value', [('head_sha','f'*40),('event','workflow_dispatch'),('run_attempt',2),('status','in_progress'),('conclusion','failure')])
def test_drift_and_rerun_rejected(field,value):
    run,job=evidence();run[field]=value
    with pytest.raises(r.screen.ScreenError):r.verify_unstarted(run,job,r.ORIGINAL_COMMIT,r.ORIGINAL_RUN,r.ORIGINAL_JOB)


def test_third_or_modified_admission_rejected_before_api(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv('GITHUB_EVENT_NAME','push')
    for changed in [['A\t'+r.ROOT_PATH+'RECOVERY_004_3.json'],['M\t'+r.ROOT_PATH+'RECOVERY_004_1.json']]:
        with pytest.raises(r.screen.ScreenError):r.recover(tmp_path,tmp_path/'ignored','a'*40,'b'*40,changed)


def recovery_fixture(tmp_path,monkeypatch):
    import json,hashlib
    monkeypatch.chdir(tmp_path);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1');monkeypatch.setenv('GITHUB_EVENT_NAME','push');monkeypatch.setenv('GITHUB_RUN_ID','999')
    activation = r.Path(r.ROOT_PATH+'ACTIVATION_004.json');activation.parent.mkdir(parents=True)
    raw=b'{"candidate_id":"R_BTC_NEGATIVE_SHOCK_1H_V1"}\n';activation.write_bytes(raw)
    document=dict(schema='zel.issue1388.preclaim_admission_recovery.v1',admission_number=1,economic_consumed=0,original_activation_commit=r.ORIGINAL_COMMIT,activation_file_sha256=hashlib.sha256(raw).hexdigest(),order_authority='BLOCKED')
    recovery=r.Path(r.ROOT_PATH+'RECOVERY_004_1.json');recovery.write_text(json.dumps(document))
    monkeypatch.setattr(r.subprocess,'check_output',lambda *args,**kwargs:raw)
    run,job=evidence()
    calls=[]
    def get(route,absent=False):
        calls.append(route)
        if absent:return None
        if route.endswith('/999'):return dict(head_sha='c'*40,event='push',run_attempt=1)
        if '/jobs?' in route:return dict(jobs=[job])
        if '/actions/runs/' in route:return run
        return dict(object=dict(sha='d'*40))
    monkeypatch.setattr(r,'get',get)
    writes=[]
    def create(*args):writes.append(args);return 'd'*40
    monkeypatch.setattr(r.screen,'create_record',create)
    return activation,recovery,calls,writes,get


def test_full_admission_chain_binds_existing_activation_and_atomic_record(tmp_path,monkeypatch):
    activation,path,calls,writes,_=recovery_fixture(tmp_path,monkeypatch)
    assert r.recover(tmp_path,activation,'c'*40,'b'*40,['A\t'+str(path)])=='d'*40
    assert len(writes)==1
    assert writes[0][2]['economic_consumed']==0
    assert writes[0][2]['current_run_id']==999
    assert 'research-execution-consumptions/issue1388-cheap-btc-shock-1h-v1' in ''.join(calls)


@pytest.mark.parametrize('cause',['existing_claim','api_unknown','create_race_or_response_loss'])
def test_existing_claim_unknown_and_atomic_loss_never_retry(tmp_path,monkeypatch,cause):
    activation,path,calls,writes,get=recovery_fixture(tmp_path,monkeypatch)
    if cause=='create_race_or_response_loss':
        def failed(*args):writes.append(args);raise r.screen.ScreenError('AMBIGUOUS_CREATE')
        monkeypatch.setattr(r.screen,'create_record',failed)
    else:
        def blocked(route,absent=False):
            if absent:raise r.screen.ScreenError(cause)
            return get(route,absent=absent)
        monkeypatch.setattr(r,'get',blocked)
    with pytest.raises(r.screen.ScreenError):r.recover(tmp_path,activation,'c'*40,'b'*40,['A\t'+str(path)])
    assert len(writes)==(1 if cause=='create_race_or_response_loss' else 0)


def test_original_payload_tamper_with_new_outer_hash_still_rejected(tmp_path,monkeypatch):
    activation,path,_,writes,_=recovery_fixture(tmp_path,monkeypatch)
    activation.write_bytes(b'{"candidate_id":"different"}')
    with pytest.raises(r.screen.ScreenError,match='ORIGINAL_ACTIVATION_DRIFT'):r.recover(tmp_path,activation,'c'*40,'b'*40,['A\t'+str(path)])
    assert not writes


@pytest.mark.parametrize('cause',['current_run','readback','profile_ref'])
def test_current_api_readback_and_permanent_ref_drift_fail_closed(tmp_path,monkeypatch,cause):
    activation,path,calls,writes,get=recovery_fixture(tmp_path,monkeypatch)
    if cause=='profile_ref':
        changed=copy.deepcopy(r.screen.PROFILES);changed[r.screen.BTC_SHOCK_ID]['execution_ref']='refs/heads/elsewhere'
        monkeypatch.setattr(r.screen,'PROFILES',changed)
    else:
        def corrupt(route,absent=False):
            if not absent and ((cause=='current_run' and route.endswith('/999')) or (cause=='readback' and '/git/ref/' in route)):return {}
            return get(route,absent=absent)
        monkeypatch.setattr(r,'get',corrupt)
    with pytest.raises(r.screen.ScreenError):r.recover(tmp_path,activation,'c'*40,'b'*40,['A\t'+str(path)])
    assert len(writes)==(1 if cause=='readback' else 0)


def test_second_admission_requires_first_add_commit_and_zero_step_prior(tmp_path,monkeypatch):
    import json
    activation,path,calls,writes,get=recovery_fixture(tmp_path,monkeypatch)
    second=r.Path(r.ROOT_PATH+'RECOVERY_004_2.json')
    document=json.loads(path.read_bytes());document.update(admission_number=2,prior_run_id=777,prior_job_id=888);second.write_text(json.dumps(document))
    raw=activation.read_bytes()
    def git(args,**kwargs):return 'e'*40+'\n' if 'log' in args else raw
    monkeypatch.setattr(r.subprocess,'check_output',git)
    def api(route,absent=False):
        if route.endswith('/777'):return dict(id=777,head_sha='e'*40,event='push',run_attempt=1,status='completed',conclusion='cancelled')
        if '/777/jobs?' in route:
            _,job=evidence();job.update(id=888,run_id=777);return dict(jobs=[job])
        return get(route,absent=absent)
    monkeypatch.setattr(r,'get',api)
    r.recover(tmp_path,activation,'c'*40,'b'*40,['A\t'+str(second)])
    assert len(writes)==1 and writes[0][2]['admission_number']==2
    monkeypatch.setattr(r.subprocess,'check_output',lambda args,**kwargs:'' if 'log' in args else raw)
    with pytest.raises(r.screen.ScreenError):r.recover(tmp_path,activation,'c'*40,'b'*40,['A\t'+str(second)])
    assert len(writes)==1
