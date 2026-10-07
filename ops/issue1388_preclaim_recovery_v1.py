"""Bounded admission recovery; no signals, fills or economic calculation."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from ops import issue1388_alpha_screen_v1 as screen

ROOT_PATH = 'research/campaigns/scalp7_20261007/issue1388_internet_alpha_v1/'
ORIGINAL_COMMIT = '480290711f92d81c86a07b06a12e15d2e08153cb'
ORIGINAL_RUN = 37678407116
ORIGINAL_JOB = 112988159998
JOB_NAME = 'cheap-screen-003'
EXECUTION_REF = 'refs/heads/research-execution-consumptions/issue1388-cheap-btc-shock-1h-v1'
RESULT_REF = 'refs/heads/research-results/issue1388-cheap-btc-shock-1h-v1'


def get(route: str, *, absent: bool = False):
    request = Request('https://api.github.com/repos/leegkssk2000-commits/vultr-z' + route,
                      headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ZEL-readonly-admission-proof'})
    try:
        with urlopen(request, timeout=30) as response:
            value = json.load(response)
    except HTTPError as exc:
        if absent and exc.code == 404:
            return None
        raise screen.ScreenError('RECOVERY_API_UNCONFIRMED_' + str(exc.code)) from None
    if absent:
        raise screen.ScreenError('RECOVERY_RECORD_ALREADY_EXISTS')
    if not isinstance(value, dict):
        raise screen.ScreenError('RECOVERY_API_OBJECT_REQUIRED')
    return value


def verify_unstarted(run: dict, job: dict, expected_head: str, run_id: int, job_id: int) -> None:
    if (run.get('id') != run_id or run.get('head_sha') != expected_head
            or run.get('event') != 'push' or run.get('run_attempt') != 1
            or run.get('status') != 'completed' or run.get('conclusion') != 'cancelled'):
        raise screen.ScreenError('RECOVERY_PRIOR_RUN_NOT_PROVEN')
    if (job.get('id') != job_id or job.get('run_id') != run_id or job.get('run_attempt') != 1
            or job.get('name') != JOB_NAME or job.get('status') != 'completed'
            or job.get('conclusion') != 'cancelled' or job.get('runner_id') != 0
            or job.get('runner_name') != '' or job.get('steps') != []):
        raise screen.ScreenError('RECOVERY_PRIOR_JOB_NOT_ZERO_STEP')


def recover(root: Path, activation_path: Path, head: str, parent: str, changed: list[str]) -> str:
    if os.environ.get('GITHUB_RUN_ATTEMPT') != '1' or os.environ.get('GITHUB_EVENT_NAME') != 'push':
        raise screen.ScreenError('RECOVERY_FIRST_PUSH_ONLY')
    paths = [ROOT_PATH + 'RECOVERY_004_' + str(n) + '.json' for n in (1, 2)]
    if len(changed) != 1 or changed[0] not in ['A\t' + p for p in paths]:
        raise screen.ScreenError('RECOVERY_CHANGED_PATH_OR_LIFETIME_CAP')
    path = changed[0][2:]
    number = paths.index(path) + 1
    value = screen.read_json(root / path)
    activation_raw = activation_path.read_bytes()
    original_raw = subprocess.check_output(['git', 'show', ORIGINAL_COMMIT + ':' + ROOT_PATH + 'ACTIVATION_004.json'], cwd=root)
    if activation_raw != original_raw or activation_path.as_posix() != ROOT_PATH + 'ACTIVATION_004.json':
        raise screen.ScreenError('RECOVERY_ORIGINAL_ACTIVATION_DRIFT')
    if (value.get('schema') != 'zel.issue1388.preclaim_admission_recovery.v1'
            or value.get('admission_number') != number or value.get('economic_consumed') != 0
            or value.get('original_activation_commit') != ORIGINAL_COMMIT
            or value.get('activation_file_sha256') != hashlib.sha256(original_raw).hexdigest()
            or value.get('order_authority') != 'BLOCKED'):
        raise screen.ScreenError('RECOVERY_BINDING')
    if number == 1:
        expected_head, prior_run, prior_job = ORIGINAL_COMMIT, ORIGINAL_RUN, ORIGINAL_JOB
    else:
        commits = subprocess.check_output(['git', 'log', '--diff-filter=A', '--format=%H', parent, '--', paths[0]], cwd=root, text=True).splitlines()
        if len(commits) != 1:
            raise screen.ScreenError('RECOVERY_FIRST_ADMISSION_HISTORY_UNCONFIRMED')
        expected_head = commits[0]
        prior_run, prior_job = value.get('prior_run_id'), value.get('prior_job_id')
        if type(prior_run) is not int or type(prior_job) is not int or prior_run == ORIGINAL_RUN:
            raise screen.ScreenError('RECOVERY_SECOND_PRIOR_BINDING')
    run = get('/actions/runs/' + str(prior_run))
    jobs = get('/actions/runs/' + str(prior_run) + '/jobs?filter=all&per_page=100')['jobs']
    matches = [j for j in jobs if j.get('id') == prior_job]
    if len(matches) != 1:
        raise screen.ScreenError('RECOVERY_PRIOR_JOB_UNCONFIRMED')
    verify_unstarted(run, matches[0], expected_head, prior_run, prior_job)
    current_run_id = int(os.environ['GITHUB_RUN_ID'])
    current = get('/actions/runs/' + str(current_run_id))
    if current.get('head_sha') != head or current.get('event') != 'push' or current.get('run_attempt') != 1:
        raise screen.ScreenError('RECOVERY_CURRENT_RUN_BINDING')
    profile = screen.PROFILES[screen.BTC_SHOCK_ID]
    if (profile['execution_ref'], profile['result_ref']) != (EXECUTION_REF, RESULT_REF):
        raise screen.ScreenError('RECOVERY_ORIGINAL_PERMANENT_REF_DRIFT')
    for ref in (EXECUTION_REF, RESULT_REF):
        get('/git/ref/' + ref.removeprefix('refs/'), absent=True)
    admission_ref = 'refs/heads/research-admission-consumptions/issue1388-btc-shock-004-' + str(number)
    get('/git/ref/' + admission_ref.removeprefix('refs/'), absent=True)
    record = {'schema': value['schema'], 'admission_number': number, 'economic_consumed': 0,
              'original_activation_commit': ORIGINAL_COMMIT, 'activation_file_sha256': value['activation_file_sha256'],
              'prior_run_id': prior_run, 'prior_job_id': prior_job, 'prior_head': expected_head,
              'current_run_id': current_run_id, 'current_head': head, 'order_authority': 'BLOCKED'}
    commit = screen.create_record(admission_ref, 'ADMISSION.json', record, head)
    if get('/git/ref/' + admission_ref.removeprefix('refs/')).get('object', {}).get('sha') != commit:
        raise screen.ScreenError('RECOVERY_ADMISSION_READBACK')
    return commit
