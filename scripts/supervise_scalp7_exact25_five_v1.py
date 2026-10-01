"""Finite sequential supervisor; existing executions are never restarted."""

import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("/home/z/z/runtime/g4_exact25_model_closure_v1_20260926")
BATCH = RUNTIME / "five_authorized_20261001"
WORKER = ROOT / "scripts/run_scalp7_exact25_five_authorized_v1.py"
lock = (RUNTIME / "exact25_five_supervisor.lock").open("a+")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
request = json.loads(
    (
        ROOT
        / "research/campaigns/scalp7_20260920/model_closure_v1/PREPARED_EXECUTION_REQUEST.json"
    ).read_text()
)


def active_worker():
    for p in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            args = p.read_bytes().split(b"\0")
        except (OSError, ProcessLookupError):
            continue
        if any(arg.endswith(WORKER.name.encode()) for arg in args):
            return True
    return False


print(
    json.dumps({"supervisor_pid": os.getpid(), "mode": "FINITE_NO_RETRY"}), flush=True
)
for row in request["identities"]:
    label, key = row["label"], row["identity"]
    while True:
        with sqlite3.connect(
            (RUNTIME / "candidate_registry.sqlite3").as_uri() + "?mode=ro", uri=True
        ) as db:
            claim = db.execute(
                "SELECT state FROM claims WHERE identity_key=?", (key,)
            ).fetchone()
        if claim is None:
            raise SystemExit("MISSING_RESERVED_IDENTITY:" + label)
        state = claim[0]
        running = active_worker()
        if state == "COMPLETED":
            if running:
                time.sleep(2)
                continue
            print(label + " RECOVERED_COMPLETED", flush=True)
            break
        if state == "RUNNING":
            if not running:
                raise SystemExit("INTERRUPTED_NO_AUTOMATIC_RESTART:" + label)
            time.sleep(10)
            continue
        if state != "RESERVED" or running:
            raise SystemExit(
                "BLOCKED_EXISTING_STATE_OR_OTHER_WORKER:" + label + ":" + state
            )
        if list((BATCH / "results").glob(label + ".json*")):
            raise SystemExit("EXISTING_RESULT_OR_PARTIAL:" + label)
        with (BATCH / "logs" / (label + ".log")).open("x") as log:
            completed = subprocess.run(
                [sys.executable, "-u", str(WORKER), label],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        if completed.returncode:
            raise SystemExit(
                "FAILED_NO_RETRY:" + label + ":" + str(completed.returncode)
            )
print("FIVE_EXISTING_IDENTITIES_COMPLETE_NO_ADDITIONAL_EXECUTION", flush=True)
