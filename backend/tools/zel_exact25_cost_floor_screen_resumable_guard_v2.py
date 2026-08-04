from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "ZEL_EXACT25_COST_FLOOR_SCREEN_RESUMABLE_GUARD_V3_MINIMUM_FIX"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PRODUCER_RELATIVE = Path("tools/q4r3_exact25_dedicated_shadow_producer.py")
UNKNOWN_EXIT_VALUES = {"", "unknown", "none", "null"}
VOLATILE_KEYS = {
    "generated_at",
    "updated_at",
    "created_at",
    "receipt_sha256",
    "checkpoint_sha256",
}
SAFETY = {
    "protected_mutations": 0,
    "canonical_mutated": False,
    "registry_mutated": False,
    "runtime_mutated": False,
    "formal_ledger_mutated": False,
    "shadow_mutated": False,
    "paper_mutated": False,
    "live_mutated": False,
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "action": "hold",
}


def stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def strip_volatile(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): strip_volatile(item)
            for key, item in value.items()
            if str(key) not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [strip_volatile(item) for item in value]
    return value


def semantic_json_sha(path: Path) -> str:
    return stable_sha(strip_volatile(json.loads(path.read_text(encoding="utf-8"))))


def hash_tree(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise RuntimeError(f"INPUT_TREE_MISSING:{root}")
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise RuntimeError(f"SYMLINK_INPUT_FORBIDDEN:{path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total_bytes += size
        files.append({"path": relative, "bytes": size, "sha256": file_sha(path)})
    if not files:
        raise RuntimeError(f"INPUT_TREE_EMPTY:{root}")
    return {
        "root_name": root.name,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
        "tree_sha256": stable_sha(files),
    }


def validate_live_producer_binding(
    source_root: Path,
    source_owner: Mapping[str, Any],
    *,
    expected_manifest_sha: str | None = None,
) -> str:
    producer_candidate = source_root / PRODUCER_RELATIVE
    if producer_candidate.is_symlink():
        raise RuntimeError(f"LIVE_PRODUCER_UNRESOLVED_SYMLINK:{producer_candidate}")
    producer_path = producer_candidate.resolve()
    if not producer_path.is_file():
        raise RuntimeError(f"LIVE_PRODUCER_MISSING:{producer_path}")

    receipt_path_text = str(source_owner.get("producer_path") or "").strip()
    receipt_sha = str(source_owner.get("producer_sha256") or "").strip().lower()
    checks = source_owner.get("checks")
    if not receipt_path_text:
        raise RuntimeError("SOURCE_OWNER_PRODUCER_PATH_MISSING")
    if not SHA256_RE.fullmatch(receipt_sha):
        raise RuntimeError("SOURCE_OWNER_PRODUCER_SHA_INVALID")
    if not isinstance(checks, Mapping) or checks.get("producer_path_not_symlink") is not True:
        raise RuntimeError("SOURCE_OWNER_PRODUCER_SYMLINK_CHECK_NOT_PASS")
    receipt_path = Path(receipt_path_text).resolve()
    if receipt_path != producer_path:
        raise RuntimeError("SOURCE_OWNER_LIVE_PRODUCER_PATH_MISMATCH")

    actual_sha = file_sha(producer_path)
    if actual_sha != receipt_sha:
        raise RuntimeError("SOURCE_OWNER_LIVE_PRODUCER_SHA_MISMATCH")
    if expected_manifest_sha is not None and actual_sha != expected_manifest_sha:
        raise RuntimeError("INPUT_MANIFEST_LIVE_PRODUCER_SHA_MISMATCH")
    return actual_sha


def build_input_manifest(
    *,
    base_runner_path: Path,
    screen_path: Path,
    indicator_helper_path: Path,
    engine_path: Path,
    policy_path: Path,
    data_root: Path,
    terminal_root: Path,
    source_owner_path: Path,
    cost_audit_path: Path,
    commit_sha: str,
) -> dict[str, Any]:
    commit = commit_sha.strip().lower()
    if not SHA1_RE.fullmatch(commit):
        raise RuntimeError("COMMIT_SHA40_REQUIRED")
    source_owner = json.loads(source_owner_path.read_text(encoding="utf-8"))
    producer_sha = str(source_owner.get("producer_sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(producer_sha):
        raise RuntimeError("SOURCE_OWNER_PRODUCER_SHA_INVALID")
    manifest = {
        "schema_version": "zel.exact25.replay_input_manifest.v3",
        "version": VERSION,
        "commit_sha": commit,
        "code": {
            "guard_sha256": file_sha(Path(__file__).resolve()),
            "base_runner_sha256": file_sha(base_runner_path),
            "screen_sha256": file_sha(screen_path),
            "indicator_helper_sha256": file_sha(indicator_helper_path),
            "engine_producer_sha256": file_sha(engine_path),
            "source_owner_producer_sha256": producer_sha,
            "policy_sha256": file_sha(policy_path),
        },
        "semantic_receipts": {
            "source_owner_sha256": semantic_json_sha(source_owner_path),
            "cost_audit_sha256": semantic_json_sha(cost_audit_path),
        },
        "terminal_files": {
            "report.json": file_sha(terminal_root / "report.json"),
            "trades.jsonl.gz": file_sha(terminal_root / "trades.jsonl.gz"),
        },
        "historical_data": hash_tree(data_root),
    }
    manifest["manifest_sha256"] = stable_sha(manifest)
    return manifest


def finite(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return parsed == parsed and parsed not in (float("inf"), float("-inf"))


def normalized_exit_reason(row: Mapping[str, Any]) -> str:
    for key in ("exit_reason", "reason", "close_reason"):
        raw = row.get(key)
        if raw is None:
            continue
        value = str(raw).strip().lower()
        if value:
            return value
    return "unknown"


def row_integrity(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    identities: list[str] = []
    missing_identity_count = 0
    for row in rows:
        event_id = str(row.get("event_id") or "").strip()
        position_id = str(row.get("position_id") or "").strip()
        identity = event_id or position_id
        if not identity:
            missing_identity_count += 1
        else:
            identities.append(identity)
    duplicate_count = len(identities) - len(set(identities))
    unknown_exit_count = sum(
        1 for row in rows if normalized_exit_reason(row) in UNKNOWN_EXIT_VALUES
    )
    required_cost_fields = (
        "fee",
        "slippage",
        "funding_pnl_estimate_usdt",
        "realized_R_including_funding_estimate",
    )
    missing_cost_lineage_count = sum(
        1
        for row in rows
        if any(not finite(row.get(field)) for field in required_cost_fields)
    )
    return {
        "trade_count": len(rows),
        "identity_count": len(identities),
        "missing_identity_count": missing_identity_count,
        "duplicate_trade_count": duplicate_count,
        "unknown_exit_count": unknown_exit_count,
        "missing_cost_lineage_count": missing_cost_lineage_count,
        "cost_lineage_complete": missing_cost_lineage_count == 0,
    }


def install_guards(
    base: Any,
    input_manifest: Mapping[str, Any],
    *,
    source_root: Path,
    source_owner: Mapping[str, Any],
) -> None:
    original_checkpoint_payload = base.checkpoint_payload
    original_validate_checkpoint = base.validate_checkpoint
    original_baseline_body = base.baseline_body
    original_candidate_body = base.candidate_body
    original_build_receipt = base.build_receipt
    expected_producer_sha = str(
        input_manifest["code"]["source_owner_producer_sha256"]
    )

    def checkpoint_payload_guard(*, kind: str, fingerprint: str, body: Mapping[str, Any]) -> dict[str, Any]:
        payload = original_checkpoint_payload(kind=kind, fingerprint=fingerprint, body=body)
        payload.update(SAFETY)
        payload["checkpoint_sha256"] = stable_sha(
            {key: value for key, value in payload.items() if key != "checkpoint_sha256"}
        )
        return payload

    def validate_checkpoint_guard(
        path: Path, *, fingerprint: str, kind: str
    ) -> dict[str, Any]:
        validate_live_producer_binding(
            source_root,
            source_owner,
            expected_manifest_sha=expected_producer_sha,
        )
        return original_validate_checkpoint(
            path, fingerprint=fingerprint, kind=kind
        )

    def heartbeat_guard(
        path: Path | None,
        *,
        state: str,
        fingerprint: str,
        completed: Sequence[str],
        current: str | None,
        expected_count: int,
        error: str | None = None,
    ) -> None:
        if path is None:
            return
        payload = {
            "schema_version": base.HEARTBEAT_SCHEMA,
            "version": VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "input_fingerprint": fingerprint,
            "input_manifest_sha256": input_manifest["manifest_sha256"],
            "completed_units": list(completed),
            "completed_count": len(completed),
            "expected_count": expected_count,
            "current_unit": current,
            "error": error,
            **SAFETY,
        }
        payload["receipt_sha256"] = stable_sha(payload)
        atomic_write_json(path, payload)

    def baseline_body_guard(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_baseline_body(*args, **kwargs)
        baseline_integrity = result["baseline_integrity"]
        immutable_integrity = result["immutable_integrity"]
        result["baseline_parity"]["missing_identity_zero"] = (
            int(baseline_integrity.get("missing_identity_count") or 0) == 0
        )
        result["baseline_parity"]["immutable_missing_identity_zero"] = (
            int(immutable_integrity.get("missing_identity_count") or 0) == 0
        )
        if not all(result["baseline_parity"].values()):
            raise RuntimeError(f"BASELINE_PARITY_FAIL:{result['baseline_parity']}")
        return result

    def candidate_body_guard(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_candidate_body(*args, **kwargs)
        integrity = result["integrity"]
        if int(integrity.get("missing_identity_count") or 0) != 0:
            result["operational_integrity_pass"] = False
            result["w1_pass"] = False
            blockers = list(result.get("w1_blockers") or [])
            if "MISSING_IDENTITY" not in blockers:
                blockers.append("MISSING_IDENTITY")
            result["w1_blockers"] = blockers
        return result

    def build_receipt_guard(*args: Any, **kwargs: Any) -> dict[str, Any]:
        receipt = original_build_receipt(*args, **kwargs)
        receipt["version"] = VERSION
        receipt["input_manifest_sha256"] = input_manifest["manifest_sha256"]
        receipt["input_manifest_file_count"] = input_manifest["historical_data"]["file_count"]
        receipt["input_manifest_total_bytes"] = input_manifest["historical_data"]["total_bytes"]
        receipt["live_producer_sha256"] = expected_producer_sha
        receipt["live_producer_revalidated_before_checkpoint_reuse"] = True
        receipt.update(SAFETY)
        receipt["receipt_sha256"] = stable_sha(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
        return receipt

    base.row_integrity = row_integrity
    base.checkpoint_payload = checkpoint_payload_guard
    base.validate_checkpoint = validate_checkpoint_guard
    base.heartbeat = heartbeat_guard
    base.baseline_body = baseline_body_guard
    base.candidate_body = candidate_body_guard
    base.build_receipt = build_receipt_guard


def run_guarded(
    *,
    base_runner_path: Path,
    screen_path: Path,
    indicator_helper_path: Path,
    engine_path: Path,
    policy_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_root: Path,
    source_owner_path: Path,
    cost_audit_path: Path,
    checkpoint_dir: Path,
    heartbeat_out: Path | None,
    input_manifest_out: Path,
    commit_sha: str,
    out: Path,
) -> dict[str, Any]:
    base = load_module(base_runner_path, f"zel_cost_resumable_base_{os.getpid()}")
    cost_screen = load_module(screen_path, f"zel_cost_screen_guarded_{os.getpid()}")
    policy = base.read_json(policy_path)
    source_owner = base.read_json(source_owner_path)
    cost_audit = base.read_json(cost_audit_path)
    base.validate_external_receipts(source_owner, cost_audit)
    validate_live_producer_binding(source_root, source_owner)

    input_manifest = build_input_manifest(
        base_runner_path=base_runner_path,
        screen_path=screen_path,
        indicator_helper_path=indicator_helper_path,
        engine_path=engine_path,
        policy_path=policy_path,
        data_root=data_root,
        terminal_root=terminal_root,
        source_owner_path=source_owner_path,
        cost_audit_path=cost_audit_path,
        commit_sha=commit_sha,
    )
    atomic_write_json(input_manifest_out, input_manifest)
    fingerprint = stable_sha(
        {
            "schema_version": "zel.exact25.cost_floor_screen.input_fingerprint.v3",
            "input_manifest_sha256": input_manifest["manifest_sha256"],
            "strategy_id": policy["strategy_id"],
            "axis_id": policy["axis_id"],
        }
    )
    install_guards(
        base,
        input_manifest,
        source_root=source_root,
        source_owner=source_owner,
    )

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    expected_count = 1 + len(policy["candidate_configs"])
    completed: list[str] = []
    base.heartbeat(
        heartbeat_out,
        state="STARTING",
        fingerprint=fingerprint,
        completed=completed,
        current=None,
        expected_count=expected_count,
    )
    engine = cost_screen.screen.load_module(
        engine_path, f"zel_cost_floor_engine_guarded_{os.getpid()}"
    )
    try:
        baseline_path = base.checkpoint_path(checkpoint_dir, "baseline")
        if baseline_path.exists():
            baseline = base.validate_checkpoint(
                baseline_path, fingerprint=fingerprint, kind="baseline"
            )
        else:
            baseline = base.run_with_heartbeat(
                lambda: base.baseline_body(
                    cost_screen,
                    engine,
                    policy,
                    engine_path,
                    source_root,
                    data_root,
                    terminal_root,
                ),
                heartbeat_out=heartbeat_out,
                fingerprint=fingerprint,
                completed=completed,
                current="baseline",
                expected_count=expected_count,
            )
            atomic_write_json(
                baseline_path,
                base.checkpoint_payload(
                    kind="baseline", fingerprint=fingerprint, body=baseline
                ),
            )
        completed.append("baseline")
        base.heartbeat(
            heartbeat_out,
            state="CHECKPOINT_COMMITTED",
            fingerprint=fingerprint,
            completed=completed,
            current="baseline",
            expected_count=expected_count,
        )

        candidates: list[dict[str, Any]] = []
        for ordinal, config in enumerate(policy["candidate_configs"], 1):
            unit = f"candidate-{ordinal:02d}"
            path = base.checkpoint_path(checkpoint_dir, "candidate", ordinal)
            if path.exists():
                body = base.validate_checkpoint(path, fingerprint=fingerprint, kind=unit)
            else:
                body = base.run_with_heartbeat(
                    lambda config=config: base.candidate_body(
                        cost_screen,
                        engine,
                        policy,
                        engine_path,
                        source_root,
                        data_root,
                        baseline,
                        config,
                    ),
                    heartbeat_out=heartbeat_out,
                    fingerprint=fingerprint,
                    completed=completed,
                    current=unit,
                    expected_count=expected_count,
                )
                if body.get("config_sha256") != stable_sha(config):
                    raise RuntimeError(f"CANDIDATE_CONFIG_SHA_MISMATCH:{ordinal}")
                atomic_write_json(
                    path,
                    base.checkpoint_payload(
                        kind=unit, fingerprint=fingerprint, body=body
                    ),
                )
            candidates.append(dict(body))
            completed.append(unit)
            base.heartbeat(
                heartbeat_out,
                state="CHECKPOINT_COMMITTED",
                fingerprint=fingerprint,
                completed=completed,
                current=unit,
                expected_count=expected_count,
            )

        receipt = base.build_receipt(
            cost_screen,
            policy,
            baseline,
            candidates,
            fingerprint=fingerprint,
            checkpoint_dir=checkpoint_dir,
            source_owner=source_owner,
            cost_audit=cost_audit,
        )
        atomic_write_json(out, receipt)
        base.heartbeat(
            heartbeat_out,
            state="PASS",
            fingerprint=fingerprint,
            completed=completed,
            current=None,
            expected_count=expected_count,
        )
        return receipt
    except Exception as exc:
        base.heartbeat(
            heartbeat_out,
            state="FAIL",
            fingerprint=fingerprint,
            completed=completed,
            current=None,
            expected_count=expected_count,
            error=f"{type(exc).__name__}:{exc}",
        )
        raise


def self_test() -> int:
    rows = [
        {
            "event_id": "a",
            "close_reason": " TAKE_PROFIT ",
            "fee": 1.0,
            "slippage": 0.1,
            "funding_pnl_estimate_usdt": 0.0,
            "realized_R_including_funding_estimate": 1.0,
        },
        {
            "event_id": "",
            "position_id": "",
            "exit_reason": "stop_loss",
            "fee": 1.0,
            "slippage": 0.1,
            "funding_pnl_estimate_usdt": 0.0,
            "realized_R_including_funding_estimate": -1.0,
        },
        {
            "event_id": "c",
            "fee": 1.0,
            "slippage": 0.1,
            "funding_pnl_estimate_usdt": 0.0,
            "realized_R_including_funding_estimate": -1.0,
        },
    ]
    integrity = row_integrity(rows)
    assert normalized_exit_reason(rows[0]) == "take_profit"
    assert integrity["missing_identity_count"] == 1
    assert integrity["duplicate_trade_count"] == 0
    assert integrity["unknown_exit_count"] == 1
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "data"
        data.mkdir()
        (data / "manifest.json").write_text('{"x":1}\n', encoding="utf-8")
        first = hash_tree(data)
        os.utime(data / "manifest.json", None)
        second = hash_tree(data)
        assert first["tree_sha256"] == second["tree_sha256"]
        (data / "manifest.json").write_text('{"x":2}\n', encoding="utf-8")
        third = hash_tree(data)
        assert first["tree_sha256"] != third["tree_sha256"]
        receipt = root / "receipt.json"
        receipt.write_text(
            json.dumps({"state": "PASS", "generated_at": "a", "receipt_sha256": "b"}),
            encoding="utf-8",
        )
        sha_a = semantic_json_sha(receipt)
        receipt.write_text(
            json.dumps({"state": "PASS", "generated_at": "c", "receipt_sha256": "d"}),
            encoding="utf-8",
        )
        assert sha_a == semantic_json_sha(receipt)

        source_root = root / "source"
        producer = source_root / PRODUCER_RELATIVE
        producer.parent.mkdir(parents=True)
        producer.write_text("# producer\n", encoding="utf-8")
        producer_sha = file_sha(producer)
        source_owner = {
            "producer_path": str(producer.resolve()),
            "producer_sha256": producer_sha,
            "checks": {"producer_path_not_symlink": True},
        }
        assert validate_live_producer_binding(source_root, source_owner) == producer_sha
        target = source_root / "producer-target.py"
        target.write_text("# target\n", encoding="utf-8")
        producer.unlink()
        producer.symlink_to(target)
        try:
            validate_live_producer_binding(source_root, source_owner)
        except RuntimeError as exc:
            assert "LIVE_PRODUCER_UNRESOLVED_SYMLINK" in str(exc)
        else:
            raise AssertionError("producer symlink must be rejected")
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-runner", type=Path)
    parser.add_argument("--screen", type=Path)
    parser.add_argument("--indicator-helper", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--source-owner", type=Path)
    parser.add_argument("--cost-audit", type=Path)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--heartbeat-out", type=Path)
    parser.add_argument("--input-manifest-out", type=Path)
    parser.add_argument("--commit-sha")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    required = (
        args.base_runner,
        args.screen,
        args.indicator_helper,
        args.engine,
        args.policy,
        args.source_root,
        args.data_root,
        args.terminal_root,
        args.source_owner,
        args.cost_audit,
        args.checkpoint_dir,
        args.input_manifest_out,
        args.commit_sha,
        args.out,
    )
    if any(value is None for value in required):
        parser.error("all runtime arguments except heartbeat-out are required")
    receipt = run_guarded(
        base_runner_path=args.base_runner.resolve(),
        screen_path=args.screen.resolve(),
        indicator_helper_path=args.indicator_helper.resolve(),
        engine_path=args.engine.resolve(),
        policy_path=args.policy.resolve(),
        source_root=args.source_root.resolve(),
        data_root=args.data_root.resolve(),
        terminal_root=args.terminal_root.resolve(),
        source_owner_path=args.source_owner.resolve(),
        cost_audit_path=args.cost_audit.resolve(),
        checkpoint_dir=args.checkpoint_dir.resolve(),
        heartbeat_out=args.heartbeat_out.resolve() if args.heartbeat_out else None,
        input_manifest_out=args.input_manifest_out.resolve(),
        commit_sha=str(args.commit_sha),
        out=args.out.resolve(),
    )
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "strategy_id": receipt["strategy_id"],
                "candidate_count": receipt["candidate_count"],
                "survivor": receipt["survivor"],
                "input_manifest_sha256": receipt["input_manifest_sha256"],
                "protected_mutations": receipt["protected_mutations"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
