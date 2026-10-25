"""Extract pinned Git objects for read-only audits; no strategy execution/network API."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name("SOURCE_MANIFEST.json").read_text())
    objects = []
    for item in manifest["objects"]:
        role = Path(item["role"])
        if role.is_absolute() or ".." in role.parts:
            raise ValueError("UNSAFE_OUTPUT_ROLE")
        spec = item["commit"] + ":" + item["path"]
        raw = subprocess.check_output(["git", "-C", str(args.repo), "show", spec])
        blob = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", spec], text=True).strip()
        if (hashlib.sha256(raw).hexdigest() != item["sha256"]
                or len(raw) != item["bytes"] or blob != item["git_blob"]):
            raise ValueError("PIN_MISMATCH:" + item["role"])
        objects.append((role, raw))
    args.destination.mkdir(parents=True, exist_ok=False)
    for role, raw in objects:
        target = args.destination / role
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(raw)
    print(json.dumps({"state": "EXACT_SAVED_GIT_OBJECTS_MATERIALIZED", "objects": len(objects),
                      "economic_runs": 0, "destination": str(args.destination.resolve())}))


if __name__ == "__main__":
    main()
