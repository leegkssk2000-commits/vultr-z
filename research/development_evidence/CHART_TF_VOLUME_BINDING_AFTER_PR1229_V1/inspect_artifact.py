"""Hash original artifact members without decoding any price or OOS rows."""
import argparse,hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
PREFIX='research/data/g5a_stage_v1/'

def inspect(directory):
    audit=json.loads((HERE/'ARTIFACT_AUDIT.json').read_text())
    expected={x['path'].removeprefix(PREFIX):x for x in audit['original_committed_files']}
    root=Path(directory);actual={str(p.relative_to(root)):p for p in root.rglob('*') if p.is_file()}
    if set(actual)!=set(expected):raise ValueError('ARTIFACT_MEMBER_SET_DIFFERS_FROM_ORIGINAL_COMMIT:'+repr(sorted(set(actual)^set(expected))))
    members=[]
    for name,path in sorted(actual.items()):
        if path.is_symlink():raise ValueError('UNEXPECTED_SYMLINK')
        raw=path.read_bytes();blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if len(raw)!=expected[name]['bytes'] or blob!=expected[name]['git_blob']:raise ValueError('ORIGINAL_ARTIFACT_MEMBER_BYTES_CHANGED:'+name)
        digest=hashlib.sha256(raw).hexdigest()
        if name=='development_manifest.json' and digest!=audit['manifest_sha256']:raise ValueError('CANONICAL_MANIFEST_MISMATCH')
        members.append(dict(path=name,bytes=len(raw),git_blob=blob,sha256=digest,contents_decoded=False))
    return dict(status='ORIGINAL_ARTIFACT_EQUALS_ORIGINAL_COMMITTED_OUTPUTS',artifact_id=audit['artifact']['id'],
      original_run_id=audit['original_run']['run_id'],original_commit=audit['manifest_first_commit'],
      observed_file_count=len(members),members=members,extra_members=[],
      price_rows_decoded=0,unused_oos_rows_decoded=0,economic_executions=0,market_requests=0,
      volume_basis_verified=False,interpretation='Actual retained artifact has exactly the28committed normalized/source-cost files. No extra lossless OHLCV page body or schema receipt is present. Unit authority is not inferred from hashes.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);x=p.parse_args()
    print(json.dumps(inspect(x.directory),sort_keys=True,indent=2))
