from __future__ import annotations
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'tools'))
import r7a1a6c4_diag_common as c
import r7a1a6c4_diag_runtime as r


def test_contract_and_prior_shapes():
    contract={'official_stage':'R7.A1A6C4','read_only':True,'service_mutation_allowed':False,'repair_allowed':False,'minimum_observe_seconds':60}
    assert c.contract_valid(contract)
    assert not c.contract_valid(dict(contract,repair_allowed=True))
    prior={'official_stage':'R7.A1A6C3B','state':'HOLD','target_change_count':2,'protected_change_count':0,'blockers':['ACTUAL_TARGET_CHANGE_DURING_TRACE','EXACT_VERIFY_AFTER_TRACE_FAILED']}
    assert c.prior_valid(prior)
    assert not c.prior_valid(dict(prior,protected_change_count=1))


def test_redaction_and_normalized_json():
    text='TOKEN=abc Authorization: Bearer xyz password=hunter 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd'
    out=c.redact(text)
    assert 'abc' not in out and 'hunter' not in out and 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcd' not in out
    assert c.normalized_json_hash(b'{"a":1,"b":2}')==c.normalized_json_hash(b'{\n"b":2,"a":1\n}')


def test_fingerprint_detects_atomic_replace(tmp_path:Path):
    p=tmp_path/'x.json'; p.write_text('{"v":1}'); before=c.snap((p,))
    q=tmp_path/'q'; q.write_text('{"v":2}'); q.replace(p); after=c.snap((p,)); changes=c.diff(before,after)
    assert changes and changes[0]['before']['inode']!=changes[0]['after']['inode'] and changes[0]['before']['sha256']!=changes[0]['after']['sha256']


def test_origin_exact_and_normalized(tmp_path:Path):
    raw=b'{"a":1,"b":2}\n'; exact=tmp_path/'exact.json'; exact.write_bytes(raw)
    normalized=tmp_path/'normalized.json'; normalized.write_text(json.dumps({'b':2,'a':1},indent=2))
    result=r.find_origin(raw,(tmp_path,))
    assert any(x['path']==str(exact) for x in result['exact_sha_matches'])
    assert any(x['path']==str(normalized) for x in result['normalized_json_matches'])


def test_correlation_proves_open_fd_and_strong_source():
    refs=[{'path':'/opt/writer.py','matched_terms':['view_contract_latest.json']}]
    proc={'pid':7,'unit':'writer.service','exe':'/usr/bin/python3','cwd':'/opt','command':'python3 /opt/writer.py','relevant_fds':['3:/var/www/z-os-alimi/api/view_contract_latest.json']}
    result=r.correlate(refs,{'units':[]},[proc],{'change_events':[]},[])
    assert result['proven'] and result['strong']
