"""Fresh-process STEP7 execution of a signed immutable source snapshot.

The independently administered OS, Python standard library and this dispatcher
are trusted. This is not a sandbox for hostile host administrators. Parent
callback globals are never an executable input to the child. No source data,
credentials, environment variables, site packages or caller import path are
copied. Only the statically resolved Python source closure is staged.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile

TIMEOUT_SECONDS = 120
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
SCHEMA = 'zel.step7.isolated_source_snapshot.v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot(producer):
    """Capture source bytes now, before authentication/read, never live globals.

    Static backend imports (including imports inside functions) are closed over.
    A dynamic dependency absent from this finite snapshot cannot resolve through
    the original checkout: the child has only snapshot + isolated stdlib paths.
    """
    root = Path(__file__).resolve().parents[3]
    primary = Path(sys.modules[producer.__module__].__file__).resolve()
    pending = [(producer.__module__, primary), (__name__, Path(__file__).resolve())]
    files, visited = {}, set()
    while pending:
        name, path = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        if not path.is_file() or path.suffix != '.py':
            raise ValueError('WORKER_PYTHON_SOURCE_REQUIRED')
        relative = Path(*name.split('.'))
        relative = relative / '__init__.py' if path.name == '__init__.py' else relative.with_suffix('.py')
        raw = path.read_bytes()
        files[relative.as_posix()] = raw
        for parent in relative.parents:
            if parent == Path('.'):
                continue
            init = root / parent / '__init__.py'
            if init.is_file():
                pending.append(('.'.join(parent.parts), init))
        for node in ast.walk(ast.parse(raw)):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    raise ValueError('WORKER_RELATIVE_IMPORT_REQUIRES_EXPLICIT_BINDING')
                if node.module:
                    imports = [node.module] + [node.module + '.' + alias.name for alias in node.names]
            for imported in imports:
                if not imported.startswith('backend.'):
                    continue
                target = root.joinpath(*imported.split('.')).with_suffix('.py')
                if not target.is_file():
                    target = root.joinpath(*imported.split('.')) / '__init__.py'
                if target.is_file():
                    pending.append((imported, target))
    manifest = {'schema': SCHEMA,
                'producer': producer.__module__ + ':' + producer.__qualname__,
                'files': {name: _digest(raw) for name, raw in sorted(files.items())},
                'runtime': {'implementation': sys.implementation.name,
                            'version': list(sys.version_info[:3]),
                            'executable_sha256': _digest(Path(sys.executable).read_bytes()),
                            'stdlib_trust': 'INDEPENDENT_VALIDATOR_HOST_ADMINISTERED'},
                'timeout_seconds': TIMEOUT_SECONDS, 'max_output_bytes': MAX_OUTPUT_BYTES,
                'environment': {'LC_ALL': 'C.UTF-8'}, 'python_flags': ['-I', '-S', '-B']}
    return manifest, files


def snapshot_identity(prepared):
    manifest, _ = prepared
    return _digest(canonical(manifest)), manifest['producer']


@contextmanager
def staged(prepared):
    manifest, files = prepared
    with tempfile.TemporaryDirectory(prefix='step7-worker-') as name:
        root = Path(name)
        for relative, raw in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o400)
        (root / 'manifest.json').write_bytes(canonical(manifest))
        (root / 'manifest.json').chmod(0o400)
        yield root, snapshot_identity(prepared)[0]


def run(prepared, raw):
    """Execute a finite child and validate its single JSON dictionary result."""
    with staged(prepared) as (root, expected):
        worker = root / 'backend/research/rebuild/step7_isolated_worker_v1.py'
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen([sys.executable, '-I', '-S', '-B', str(worker),
                                        '--child', str(root), expected],
                                       stdin=subprocess.PIPE, stdout=output, stderr=errors,
                                       cwd=root, env=prepared[0]['environment'], start_new_session=True, close_fds=True)
            try:
                process.communicate(raw, timeout=prepared[0]['timeout_seconds'])
            except BaseException:
                # Includes cancellation/timeout. Kill only this owned process
                # group, reap it, and let the authority journal remain consumed.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                raise
            if process.returncode:
                raise ValueError('ISOLATED_WORKER_FAILED_NO_RETRY')
            output.seek(0)
            result = output.read(prepared[0]['max_output_bytes'] + 1)
            if len(result) > prepared[0]['max_output_bytes']:
                raise ValueError('ISOLATED_WORKER_OUTPUT_LIMIT')
            try:
                value = json.loads(result, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
            except (ValueError, UnicodeError) as exc:
                raise ValueError('ISOLATED_WORKER_INVALID_JSON') from exc
            if type(value) is not dict:
                raise ValueError('ISOLATED_WORKER_DICTIONARY_REQUIRED')
            return value


def _child(root, expected):
    root = Path(root)
    manifest_bytes = (root / 'manifest.json').read_bytes()
    if _digest(manifest_bytes) != expected:
        raise ValueError('WORKER_MANIFEST_CHANGED')
    manifest = json.loads(manifest_bytes)
    if manifest.get('schema') != SCHEMA:
        raise ValueError('WORKER_MANIFEST_SCHEMA')
    if manifest['runtime']['executable_sha256'] != _digest(Path(sys.executable).read_bytes()):
        raise ValueError('WORKER_RUNTIME_CHANGED')
    if (not (sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode)
            or dict(os.environ) != manifest['environment']):
        raise ValueError('WORKER_ENVIRONMENT_NOT_ISOLATED')
    for relative, expected_sha in manifest['files'].items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('WORKER_SOURCE_PATH_ESCAPE')
        if _digest(path.read_bytes()) != expected_sha:
            raise ValueError('WORKER_SOURCE_CHANGED')
    resource.setrlimit(resource.RLIMIT_FSIZE, (manifest['max_output_bytes'], manifest['max_output_bytes']))
    # -I -S removed current directory, PYTHONPATH and sitecustomize/user packages.
    # Only our signed source snapshot is added, never the parent checkout.
    sys.path.insert(0, str(root))
    module, name = manifest['producer'].split(':')
    callback = getattr(importlib.import_module(module), name)
    result = callback(sys.stdin.buffer.read())
    sys.stdout.buffer.write(canonical(result))


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--child':
        raise SystemExit('CONTROLLED_CHILD_ENTRY_REQUIRED')
    _child(sys.argv[2], sys.argv[3])
