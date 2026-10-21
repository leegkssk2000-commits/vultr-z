"""Copy pinned inputs/code to a NEW attempt and apply the loader patch; never run it."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
BEFORE = 'a86934fed27bde13c94cf6bc11cdfca1169b6a024fa0048f2c4b68e4700dfb27'
AFTER = 'dd54d017df362f51e587fa5feaa215bb1bf711430f4e5b7e8cd3bd6fe3efdd57'
PATCH = '40fd99e17f2565abf33984865ceae4480a9ae83be99ea5539c244cd3fb3c6278'
CACHE = 'c62e037500dd5b6ccaeb309c250be7bf47d053b4d3527cdbda60bbaafbb05bf9'
FREEZE = '68e4b995419aea62e6362c01f8a54fd3455c556fde444f8877e8cf9547244b1a'
CODE_FREEZE = 'd0f0fa76917b76048924ff0045bd114c1067bc3151a31bc234fc1e7ccd595116'
PERSIST = '555687f5e999705579326a5b9dc08db75b0300c690bbccda77769cb3be2e6381'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(source_stage, attempt_dir):
    old = Path(source_stage).resolve()
    new = Path(attempt_dir).absolute()
    if new.exists() or new.is_symlink() or new.resolve().is_relative_to(old):
        raise ValueError('ATTEMPT_MUST_BE_NEW_AND_OUTSIDE_ORIGINAL_STAGE')
    patch = (HERE / 'guarded_once.patch').read_bytes()
    if sha(patch) != PATCH:
        raise ValueError('PATCH_SHA_CHANGED')
    if not shutil.which('patch'):
        raise ValueError('EXISTING_PATCH_COMMAND_REQUIRED_NO_INSTALL_PERFORMED')
    expected = {'guarded_once.py': BEFORE, 'INPUT_CACHE.json': CACHE,
                'FREEZE.json': FREEZE, 'CODE_FREEZE.json': CODE_FREEZE,
                'persist_addonly.py': PERSIST}
    pins_raw = (old / 'CODE_FREEZE.json').read_bytes()
    if sha(pins_raw) != CODE_FREEZE:
        raise ValueError('ORIGINAL_CODE_FREEZE_CHANGED')
    expected.update(json.loads(pins_raw)['sha256'])
    cache_raw = (old / 'INPUT_CACHE.json').read_bytes()
    if sha(cache_raw) != CACHE:
        raise ValueError('ORIGINAL_CACHE_CHANGED')
    expected.update({r['path']: r['sha256'] for r in json.loads(cache_raw)['symbols'].values()})
    contents = {}
    for name, digest in expected.items():
        if Path(name).name != name:
            raise ValueError('EXPECTED_SINGLE_LEVEL_INPUT_PATH')
        raw = (old / name).read_bytes()
        if sha(raw) != digest:
            raise ValueError('ORIGINAL_FILE_CHANGED:' + name)
        contents[name] = raw
    # Preflight finished. Never copy STARTED, results, failure evidence or locks.
    new.mkdir(parents=False, exist_ok=False)
    for name, raw in contents.items():
        with (new / name).open('xb') as handle:
            handle.write(raw)
    result = subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'],
                            input=patch, cwd=new, capture_output=True, check=True)
    if sha((new / 'guarded_once.py').read_bytes()) != AFTER:
        raise ValueError('PATCHED_LOADER_SHA_MISMATCH')
    for name, raw in contents.items():
        if (old / name).read_bytes() != raw:
            raise ValueError('SOURCE_CHANGED_DURING_COPY:' + name)
        if name != 'guarded_once.py' and (new / name).read_bytes() != raw:
            raise ValueError('COPIED_FILE_CHANGED:' + name)
    receipt = {'state': 'PREPARED_NOT_STARTED', 'source_stage': str(old),
               'attempt_dir': str(new), 'patch_sha256': PATCH,
               'original_loader_sha256': BEFORE, 'patched_loader_sha256': AFTER,
               'copied_file_original_sha256': expected,
               'original_STARTED_and_logs_preserved': True,
               'guards_started': 0, 'economic_runs': 0,
               'publication_warning': 'persist_addonly.py is unchanged and has the OLD result prefix; economic owner must separately bind new-attempt publication before running a guard/report.'}
    with (new / 'CONTEXT_ORDER_REPAIR_PREPARED.json').open('x') as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-stage', required=True)
    parser.add_argument('--attempt-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_stage, args.attempt_dir), indent=2))
