"""Fail-closed verification for this frozen, read-only G5 witness packet."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath


def strict_json(text):
    def reject(value):
        raise ValueError("NONFINITE_JSON:" + value)
    return json.loads(text, parse_constant=reject)


def verify(root, manifest):
    root = Path(root).resolve()
    if manifest.get("formal_pass_authority") is not False:
        raise ValueError("FORMAL_AUTHORITY_NOT_FALSE")
    if manifest.get("g5a_rows_reusable_for_g5b") is not False:
        raise ValueError("G5B_REUSE_NOT_FALSE")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("EMPTY_INPUT_MANIFEST")
    seen, hashes = set(), {}
    for item in files:
        name = item["path"]
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts or str(path) != name:
            raise ValueError("UNSAFE_INPUT_PATH:" + name)
        if name in seen:
            raise ValueError("DUPLICATE_INPUT_PATH:" + name)
        seen.add(name)
        source = (root / name).resolve()
        if not source.is_relative_to(root):
            raise ValueError("INPUT_SYMLINK_ESCAPE:" + name)
        raw = source.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != item["sha256"] or len(raw) != item["bytes"]:
            raise ValueError("INPUT_BYTES_MISMATCH:" + name)
        if source.suffix == ".json":
            strict_json(raw.decode("utf-8"))
        elif source.suffix == ".jsonl":
            for line in raw.decode("utf-8").splitlines():
                if line.strip():
                    strict_json(line)
        hashes[name] = actual
    return hashes


def external_output(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.is_relative_to(root):
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_SOURCE_CHECKOUT")
    if output.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW_DIRECTORY")
    return output
