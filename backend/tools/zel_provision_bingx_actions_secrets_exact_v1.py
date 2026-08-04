from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_PROVISION_BINGX_ACTIONS_SECRETS_EXACT_V1"
SOURCE = Path("/etc/z-alimi/bingx.env")
TARGETS = ("BINGX_API_KEY", "BINGX_SECRET_KEY")


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def parse_source() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in SOURCE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key == "BINGX_API_KEY" and value:
            values["BINGX_API_KEY"] = value
        elif key in {"BINGX_API_SECRET", "BINGX_SECRET_KEY"} and value:
            values["BINGX_SECRET_KEY"] = value
    if not all(name in values for name in TARGETS):
        raise RuntimeError("AUTHORITATIVE_BINGX_PAIR_INCOMPLETE")
    return values


def validate(values: dict[str, str]) -> str:
    params = {"recvWindow": 5000, "timestamp": int(time.time() * 1000)}
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    signature = hmac.new(values["BINGX_SECRET_KEY"].encode(), query.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        f"https://open-api.bingx.com/openApi/swap/v2/user/commissionRate?{query}&signature={signature}",
        headers={
            "X-BX-APIKEY": values["BINGX_API_KEY"],
            "X-SOURCE-KEY": "BX-AI-SKILL",
            "User-Agent": VERSION,
        },
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = json.loads(response.read())
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"BINGX_READ_ONLY_VALIDATION_FAILED:{payload.get('code')}")
    return stable_sha(payload.get("data"))


def run(command: list[str], *, stdin: str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env or os.environ.copy(),
    )


def provision(repo: str, values: dict[str, str]) -> list[str]:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("GH_CLI_NOT_FOUND")
    auth = run([gh, "auth", "status", "--hostname", "github.com"])
    if auth.returncode != 0:
        raise RuntimeError("GH_AUTH_NOT_AVAILABLE_ON_VPS")
    for name in TARGETS:
        result = run([gh, "secret", "set", name, "--repo", repo], stdin=values[name])
        if result.returncode != 0:
            raise RuntimeError(f"GH_SECRET_SET_FAILED:{name}")
    listed = run([gh, "secret", "list", "--repo", repo, "--json", "name"])
    if listed.returncode != 0:
        raise RuntimeError("GH_SECRET_LIST_FAILED")
    names = sorted(
        str(row.get("name"))
        for row in json.loads(listed.stdout or "[]")
        if isinstance(row, dict) and row.get("name")
    )
    if not all(name in names for name in TARGETS):
        raise RuntimeError("GH_SECRET_NAME_VERIFICATION_FAILED")
    return [name for name in TARGETS if name in names]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    blocker = None
    verified_names: list[str] = []
    validation_sha = None
    try:
        values = parse_source()
        validation_sha = validate(values)
        verified_names = provision(args.repo, values)
        state = "PASS_BINGX_ACTIONS_SECRETS_PROVISIONED"
    except Exception as exc:
        state = "HOLD_BINGX_ACTIONS_SECRETS_PROVISION"
        blocker = f"{type(exc).__name__}:{exc}"
    receipt = {
        "schema_version": "zel.bingx.actions_secret_provision.exact.receipt.v1",
        "version": VERSION,
        "state": state,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "repository": args.repo,
        "source_path_sha256": stable_sha(str(SOURCE)),
        "source_aliases": ["BINGX_API_KEY", "BINGX_API_SECRET"],
        "read_only_validation_response_sha256": validation_sha,
        "verified_secret_names": verified_names,
        "secret_values_logged": False,
        "secret_values_artifacted": False,
        "protected_mutations": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "blocker": blocker,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": state, "verified_secret_names": verified_names, "blocker": blocker, "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    return 0 if state.startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
