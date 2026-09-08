"""Review fix: mandatory raw linkage after the unchanged saved verifier."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import verify_saved as saved
from raw_link import validate_raw_link
OLD_MANIFEST_SHA = '4b5d9269cba3e03d867ff7ff4487e3be439ba7570c7ff2fd96b1e42eb4038d39'

def verify(root=saved.HERE, expected_manifest_sha=None):
    root = Path(root)
    raw_manifest = (root/'REVIEW_HASHES.json').read_bytes()
    if expected_manifest_sha is None or hashlib.sha256(raw_manifest).hexdigest() != expected_manifest_sha:
        raise ValueError('REVIEW_MANIFEST_DRIFT')
    for name, digest in json.loads(raw_manifest).items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise ValueError('REVIEW_FILE_DRIFT:' + name)
    base = saved.verify(root, OLD_MANIFEST_SHA)
    context = saved.read(root/'NORMALIZATION_CONTEXT.json')
    spec = saved.read(root/'SPEC.json')
    links = {}
    for kind in saved.KINDS:
        target = root/'results'/kind
        result = json.loads(gzip.decompress((target/'RESULT.json.gz').read_bytes()))
        engine = json.loads(gzip.decompress((target/'RAW_ENGINE.json.gz').read_bytes()))
        links[kind] = validate_raw_link(result, engine, context, spec)
    return {'status': 'PRESERVED_RESULTS_AND_INDEPENDENT_RAW_LINK_VERIFIED',
            'saved': base, 'raw_links': links, 'economic_replays': 0}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(expected_manifest_sha=args.manifest_sha256), indent=2))
