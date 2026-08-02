from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "ZEL_BINGX_READONLY_SECRET_CONNECTOR_V2"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def import_resolver(root: Path):
    tools = root / "backend/tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import zel_bingx_private_history_fetch_v1 as resolver
    return resolver


def safe_candidate(row: dict[str, str], state: str, error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_type": row.get("source_type"),
        "source_ref": row.get("source_ref"),
        "key_name": row.get("key_name"),
        "secret_name": row.get("secret_name"),
        "fingerprint": row.get("fingerprint"),
        "verification_state": state,
    }
    if error:
        result["safe_error"] = error[:400]
    return result


def run_collector(root: Path, api_key: str, secret: str, lookback_days: int) -> tuple[dict[str, Any], int, str]:
    collector = root / "backend/tools/zel_bingx_execution_evidence_collector_v1.py"
    if not collector.is_file():
        return {}, 127, "COLLECTOR_MISSING"
    env = dict(os.environ)
    env["BINGX_API_KEY"] = api_key
    env["BINGX_SECRET_KEY"] = secret
    with tempfile.TemporaryDirectory(prefix="zel_bingx_readonly_v2_") as tmp:
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
        receipt_path = out_dir / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else {}
        return receipt, process.returncode, process.stdout[-2000:]


def connect(root: Path, lookback_days: int) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "zel.bingx.readonly_secret_connector.receipt.v2",
        "version": VERSION,
        "generated_at": now_iso(),
        "methods_allowed": ["GET"],
        "private_write_endpoints_allowed": False,
        "credentials_persisted": False,
        "raw_order_ids_persisted": False,
        "private_history_persisted": False,
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
    try:
        resolver = import_resolver(root)
        candidates = resolver.discover_candidates()
    except Exception as exc:
        base.update(
            {
                "state": "HOLD_BINGX_CREDENTIAL_RESOLVER_FAILURE",
                "credential_candidate_count": 0,
                "verified_candidate_count": 0,
                "credential_sources": [],
                "selected_source": None,
                "errors": [f"RESOLVER_FAILURE:{type(exc).__name__}"],
                "collector_receipt": {},
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base

    verified: list[dict[str, str]] = []
    source_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            resolver.signed_request(
                candidate["key"],
                candidate["secret"],
                resolver.ALLOWED["commission"],
                {},
            )
            verified.append(candidate)
            source_rows.append(safe_candidate(candidate, "PASS_COMMISSION_GET"))
        except Exception as exc:
            safe = resolver.safe_error(exc, candidate["key"], candidate["secret"])
            source_rows.append(safe_candidate(candidate, "REJECTED_COMMISSION_GET", safe))

    base["credential_candidate_count"] = len(candidates)
    base["verified_candidate_count"] = len(verified)
    base["credential_sources"] = source_rows
    if not candidates:
        base.update(
            {
                "state": "HOLD_BINGX_READ_ONLY_CREDENTIALS_MISSING",
                "selected_source": None,
                "errors": ["BINGX_READ_ONLY_CREDENTIALS_MISSING"],
                "collector_receipt": {},
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base
    if not verified:
        base.update(
            {
                "state": "HOLD_BINGX_READ_ONLY_NO_VERIFIED_CREDENTIAL",
                "selected_source": None,
                "errors": ["NO_CANDIDATE_PASSED_COMMISSION_GET"],
                "collector_receipt": {},
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base
    if len(verified) > 1:
        base.update(
            {
                "state": "HOLD_BINGX_READ_ONLY_MULTIPLE_VERIFIED_CREDENTIALS",
                "selected_source": None,
                "errors": ["MULTIPLE_CANDIDATES_PASSED_COMMISSION_GET"],
                "collector_receipt": {},
            }
        )
        base["receipt_sha256"] = stable_sha(base)
        return base

    selected = verified[0]
    base["selected_source"] = safe_candidate(selected, "PASS_COMMISSION_GET")
    receipt, returncode, output = run_collector(
        root,
        selected["key"],
        selected["secret"],
        lookback_days,
    )
    collector_receipt = {
        "state": receipt.get("state"),
        "source": receipt.get("source"),
        "evidence_sha256": receipt.get("evidence_sha256"),
        "coverage": receipt.get("coverage"),
        "files": receipt.get("files"),
        "methods_used": receipt.get("methods_used"),
        "credentials_persisted": receipt.get("credentials_persisted"),
        "raw_order_ids_persisted": receipt.get("raw_order_ids_persisted"),
        "execution_authority": receipt.get("execution_authority"),
        "order_authority": receipt.get("order_authority"),
    }
    valid = (
        returncode == 0
        and collector_receipt["state"] == "PASS_BINGX_READ_ONLY_EVIDENCE_COLLECTED"
        and collector_receipt["methods_used"] == ["GET"]
        and collector_receipt["credentials_persisted"] is False
        and collector_receipt["raw_order_ids_persisted"] is False
        and collector_receipt["execution_authority"] == "NONE"
        and collector_receipt["order_authority"] == "BLOCKED"
    )
    base.update(
        {
            "state": "PASS_BINGX_READ_ONLY_SECRET_CONNECTED" if valid else "HOLD_BINGX_READ_ONLY_COLLECTOR_FAILURE",
            "errors": [] if valid else [f"COLLECTOR_FAILURE:{returncode}:{hashlib.sha256(output.encode()).hexdigest()[:12]}"],
            "collector_receipt": collector_receipt,
            "collector_returncode": returncode,
        }
    )
    base["receipt_sha256"] = stable_sha(base)
    return base


def self_test() -> None:
    base = {
        "state": "HOLD",
        "methods_allowed": ["GET"],
        "private_write_endpoints_allowed": False,
        "credentials_persisted": False,
        "raw_order_ids_persisted": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    }
    assert base["methods_allowed"] == ["GET"]
    assert base["private_write_endpoints_allowed"] is False
    assert base["credentials_persisted"] is False
    assert base["raw_order_ids_persisted"] is False
    assert base["execution_authority"] == "NONE" and base["order_authority"] == "BLOCKED"
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
