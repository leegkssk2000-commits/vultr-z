from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_BINGX_READONLY_SECRET_CONNECTOR_V1"
KEY_PAIRS = (
    ("BINGX_API_KEY", "BINGX_SECRET_KEY"),
    ("BINGX_KEY", "BINGX_SECRET"),
    ("BINGX_APIKEY", "BINGX_SECRETKEY"),
)
ENV_FILE_CANDIDATES = (
    ".env",
    "backend/.env",
    "config/.env",
    "/etc/zel/zel.env",
    "/etc/zel/bingx.env",
    "/etc/default/zel",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def parse_env_bytes(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        try:
            values[key.decode("utf-8")] = value.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return values


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    pattern = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def extract_pair(values: dict[str, str]) -> tuple[str, str, str] | None:
    for api_name, secret_name in KEY_PAIRS:
        api_key = values.get(api_name, "").strip()
        secret = values.get(secret_name, "").strip()
        if api_key and secret:
            return api_key, secret, f"{api_name}+{secret_name}"
    return None


def process_candidates() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return rows
    for item in proc.iterdir():
        if not item.name.isdigit():
            continue
        try:
            values = parse_env_bytes((item / "environ").read_bytes())
            pair = extract_pair(values)
            if not pair:
                continue
            api_key, secret, key_names = pair
            cmdline = (item / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
            rows.append(
                {
                    "source_type": "PROCESS_ENV",
                    "source_id": item.name,
                    "key_names": key_names,
                    "command_sha256": hashlib.sha256(cmdline.encode()).hexdigest(),
                    "credential_pair_sha256": hashlib.sha256((api_key + "\0" + secret).encode()).hexdigest(),
                    "api_key": api_key,
                    "secret": secret,
                }
            )
        except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
            continue
    return rows


def env_file_candidates(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in ENV_FILE_CANDIDATES:
        path = Path(raw) if raw.startswith("/") else root / raw
        if not path.is_file():
            continue
        try:
            values = parse_env_text(path.read_text(encoding="utf-8", errors="replace"))
            pair = extract_pair(values)
            if not pair:
                continue
            api_key, secret, key_names = pair
            stat = path.stat()
            rows.append(
                {
                    "source_type": "ENV_FILE",
                    "source_id": str(path),
                    "key_names": key_names,
                    "mode": oct(stat.st_mode & 0o777),
                    "uid": stat.st_uid,
                    "credential_pair_sha256": hashlib.sha256((api_key + "\0" + secret).encode()).hexdigest(),
                    "api_key": api_key,
                    "secret": secret,
                }
            )
        except (PermissionError, OSError):
            continue
    return rows


def runner_candidate() -> list[dict[str, Any]]:
    pair = extract_pair(dict(os.environ))
    if not pair:
        return []
    api_key, secret, key_names = pair
    return [
        {
            "source_type": "RUNNER_ENV",
            "source_id": "CURRENT_PROCESS",
            "key_names": key_names,
            "credential_pair_sha256": hashlib.sha256((api_key + "\0" + secret).encode()).hexdigest(),
            "api_key": api_key,
            "secret": secret,
        }
    ]


def safe_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for row in rows:
        clean.append({key: value for key, value in row.items() if key not in {"api_key", "secret", "credential_pair_sha256"}})
    return clean


def select_credentials(root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[str]]:
    candidates = runner_candidate() + process_candidates() + env_file_candidates(root)
    errors: list[str] = []
    unique: dict[str, dict[str, Any]] = {}
    for row in candidates:
        digest = str(row["credential_pair_sha256"])
        unique.setdefault(digest, row)
    if not unique:
        errors.append("BINGX_READ_ONLY_CREDENTIALS_MISSING")
        return None, candidates, errors
    if len(unique) > 1:
        errors.append("BINGX_READ_ONLY_CREDENTIALS_CONFLICT")
        return None, candidates, errors
    selected = next(iter(unique.values()))
    return selected, candidates, errors


def classify_failure(text: str) -> str:
    upper = text.upper()
    if "CREDENTIALS_MISSING" in upper:
        return "HOLD_BINGX_READ_ONLY_CREDENTIALS_MISSING"
    if "BINGX_ERROR" in upper:
        return "HOLD_BINGX_READ_ONLY_API_REJECTED"
    if any(token in upper for token in ("URLERROR", "TIMEOUT", "NETWORK", "NAME OR SERVICE", "CONNECTION")):
        return "HOLD_BINGX_READ_ONLY_NETWORK_FAILURE"
    return "HOLD_BINGX_READ_ONLY_COLLECTOR_FAILURE"


def connect(root: Path, lookback_days: int) -> dict[str, Any]:
    selected, candidates, errors = select_credentials(root)
    base: dict[str, Any] = {
        "schema_version": "zel.bingx.readonly_secret_connector.receipt.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "credential_candidate_count": len(candidates),
        "credential_sources": safe_view(candidates),
        "selected_source": None if selected is None else {
            key: value
            for key, value in selected.items()
            if key not in {"api_key", "secret", "credential_pair_sha256"}
        },
        "methods_allowed": ["GET"],
        "private_write_endpoints_allowed": False,
        "credentials_persisted": False,
        "raw_order_ids_persisted": False,
        "active_data_b_1m_mutated": False,
        "canonical_strategy_files_mutated": False,
        "formal_ledger_mutated": False,
        "runtime_registry_mutated": False,
        "shadow_started": False,
        "paper_started": False,
        "live_enabled": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    if selected is None:
        base.update(
            {
                "state": "HOLD_BINGX_READ_ONLY_CREDENTIALS_MISSING" if "BINGX_READ_ONLY_CREDENTIALS_MISSING" in errors else "HOLD_BINGX_READ_ONLY_CREDENTIALS_CONFLICT",
                "errors": errors,
                "collector_receipt": {},
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base
    collector = root / "backend/tools/zel_bingx_execution_evidence_collector_v1.py"
    if not collector.is_file():
        base.update(
            {
                "state": "HOLD_BINGX_READ_ONLY_COLLECTOR_MISSING",
                "errors": ["BINGX_READ_ONLY_COLLECTOR_MISSING"],
                "collector_receipt": {},
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base
    env = dict(os.environ)
    env["BINGX_API_KEY"] = str(selected["api_key"])
    env["BINGX_SECRET_KEY"] = str(selected["secret"])
    with tempfile.TemporaryDirectory(prefix="zel_bingx_readonly_") as tmp:
        out_dir = Path(tmp)
        process = subprocess.run(
            [sys.executable, str(collector), "--out-dir", str(out_dir), "--lookback-days", str(lookback_days)],
            cwd=str(root),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
            check=False,
        )
        if process.returncode != 0:
            state = classify_failure(process.stdout[-4000:])
            base.update(
                {
                    "state": state,
                    "errors": [state],
                    "collector_receipt": {},
                    "collector_returncode": process.returncode,
                }
            )
            base["receipt_sha256"] = stable_sha(base)
            return base
        receipt_path = out_dir / "receipt.json"
        if not receipt_path.is_file():
            base.update(
                {
                    "state": "HOLD_BINGX_READ_ONLY_RECEIPT_MISSING",
                    "errors": ["BINGX_READ_ONLY_RECEIPT_MISSING"],
                    "collector_receipt": {},
                }
            )
            base["receipt_sha256"] = stable_sha(base)
            return base
        raw_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        collector_receipt = {
            "state": raw_receipt.get("state"),
            "source": raw_receipt.get("source"),
            "evidence_sha256": raw_receipt.get("evidence_sha256"),
            "coverage": raw_receipt.get("coverage"),
            "files": raw_receipt.get("files"),
            "methods_used": raw_receipt.get("methods_used"),
            "credentials_persisted": raw_receipt.get("credentials_persisted"),
            "raw_order_ids_persisted": raw_receipt.get("raw_order_ids_persisted"),
            "execution_authority": raw_receipt.get("execution_authority"),
            "order_authority": raw_receipt.get("order_authority"),
        }
        valid = (
            collector_receipt["state"] == "PASS_BINGX_READ_ONLY_EVIDENCE_COLLECTED"
            and collector_receipt["methods_used"] == ["GET"]
            and collector_receipt["credentials_persisted"] is False
            and collector_receipt["raw_order_ids_persisted"] is False
            and collector_receipt["execution_authority"] == "NONE"
            and collector_receipt["order_authority"] == "BLOCKED"
        )
        base.update(
            {
                "state": "PASS_BINGX_READ_ONLY_SECRET_CONNECTED" if valid else "HOLD_BINGX_READ_ONLY_RECEIPT_INVALID",
                "errors": [] if valid else ["BINGX_READ_ONLY_RECEIPT_INVALID"],
                "collector_receipt": collector_receipt,
                "collector_returncode": process.returncode,
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base


def self_test() -> None:
    original = dict(os.environ)
    try:
        for pair in KEY_PAIRS:
            for key in pair:
                os.environ.pop(key, None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = connect(root, 1)
            assert row["state"] == "HOLD_BINGX_READ_ONLY_CREDENTIALS_MISSING", row
            assert row["credentials_persisted"] is False
            assert row["order_authority"] == "BLOCKED"
    finally:
        os.environ.clear()
        os.environ.update(original)
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not 1 <= args.lookback_days <= 90:
        parser.error("lookback-days must be 1..90")
    row = connect(args.root.resolve(), args.lookback_days)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.stdout or not args.out:
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
