"""One previously reserved identity; no allocation, retry, or model changes."""

from __future__ import annotations
import argparse
import importlib
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
run_authorized = importlib.import_module(
    "backend.research.rebuild.scalp7_exact25_model_runner_v1"
).run_authorized

SCOPE = "G4_EXACT25_SOURCE_TO_CODE_IMPLEMENTATION_AFTER_FINAL_REVIEW_V1"
OWNER = "WORK_ROOT_EXACT25_FIVE_SINGLE_OWNER"
RUNTIME = Path("/home/z/z/runtime/g4_exact25_model_closure_v1_20260926")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "label",
    choices=["ST_CONTROL", "ST_TRAIL", "SR_CONTROL", "SR_RETEST", "NOISE_BASELINE"],
)
a = parser.parse_args()
lock = (RUNTIME / "exact25_five_execution.lock").open("a+")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
request = json.loads(
    (
        ROOT
        / "research/campaigns/scalp7_20260920/model_closure_v1/PREPARED_EXECUTION_REQUEST.json"
    ).read_text()
)
row = next(x for x in request["identities"] if x["label"] == a.label)
binding = json.loads((ROOT / row["freeze_path"]).read_text())
assert binding["identity_key"] == row["identity"]
print(
    json.dumps(
        {
            "label": a.label,
            "pid": os.getpid(),
            "at": datetime.now(timezone.utc).isoformat(),
            "event": "CALL_RESERVED_IDENTITY",
        }
    ),
    flush=True,
)
result = run_authorized(
    binding,
    expected_binding_sha256=row["binding_sha256"],
    registry_path=RUNTIME / "candidate_registry.sqlite3",
    scope=SCOPE,
    owner=OWNER,
    output_path=RUNTIME / "five_authorized_20261001/results" / (a.label + ".json"),
)
print(
    json.dumps(
        {
            "label": a.label,
            "at": datetime.now(timezone.utc).isoformat(),
            "event": "COMPLETED",
            "unknown": result["unknown_execution_count"],
        }
    ),
    flush=True,
)
