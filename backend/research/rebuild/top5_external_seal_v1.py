"""Verify durable receipt files and blocked authority without running a new trial."""
import json
from pathlib import Path
from backend.research.rebuild import top5_external_repair_v1 as r

def verify():
    value=json.loads((r.ROOT/r.OUTPUT/'durable_receipt.json').read_text())
    r.old.probe.verify_seal(value,'REMOTE_SEAL')
    for path,sha in value['files_sha256'].items():
        if r.old.file_sha(r.ROOT/path)!=sha:raise RuntimeError('DURABLE_RECEIPT_PARITY:'+path)
    r.verify_previous()
    for key,v in r.old.probe.DEV_AUTH.items():
        if value[key]!=v:raise RuntimeError('DURABLE_AUTHORITY:'+key)
    if value['new_Gemini_video_requests']!=0:raise RuntimeError('UNVERIFIED_GENERATION_CREDIT')
    return value

if __name__=='__main__':
    v=verify();print(json.dumps({'state':'PASS_DURABLE_TOP5_EVIDENCE_PARITY','receipt_sha256':v['receipt_sha256'],'files':len(v['files_sha256']),'research_completion':'LOCAL_SOURCE_RESEARCH_AND_ECONOMICS_COMPLETE; NEW_GEMINI_VIDEO_NOT_RUN'},sort_keys=True))
