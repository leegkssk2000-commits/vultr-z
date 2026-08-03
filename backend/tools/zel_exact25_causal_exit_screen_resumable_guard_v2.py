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

VERSION = "ZEL_EXACT25_CAUSAL_EXIT_SCREEN_RESUMABLE_GUARD_V2"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
PRODUCER_RELATIVE_PATH = Path("tools/q4r3_exact25_dedicated_shadow_producer.py")
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
    value = json.loads(path.read_text(encoding="utf-8"))
    return stable_sha(strip_volatile(value))


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


def resolve_producer_path(source_root: Path) -> Path:
    producer_path = source_root / PRODUCER_RELATIVE_PATH
    if producer_path.is_symlink() or not producer_path.is_file():
        raise RuntimeError(f"PRODUCER_INPUT_MISSING_OR_INVALID:{producer_path}")
    return producer_path


def build_input_manifest(
    *,
    base_runner_path: Path,
    screen_path: Path,
    engine_path: Path,
    policy_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_root: Path,
    source_owner_path: Path,
    route_path: Path,
    commit_sha: str,
) -> dict[str, Any]:
    commit = commit_sha.strip().lower()
    if not SHA1_RE.fullmatch(commit):
        raise RuntimeError("COMMIT_SHA40_REQUIRED")
    producer_path = resolve_producer_path(source_root)
    terminal_files = {
        "report.json": file_sha(terminal_root / "report.json"),
        "trades.jsonl.gz": file_sha(terminal_root / "trades.jsonl.gz"),
    }
    manifest = {
        "schema_version": "zel.exact25.replay_input_manifest.v2",
        "version": VERSION,
        "commit_sha": commit,
        "code": {
            "guard_sha256": file_sha(Path(__file__).resolve()),
            "base_runner_sha256": file_sha(base_runner_path),
            "screen_sha256": file_sha(screen_path),
            "engine_sha256": file_sha(engine_path),
            "producer_relative_path": PRODUCER_RELATIVE_PATH.as_posix(),
            "producer_sha256": file_sha(producer_path),
            "policy_sha256": file_sha(policy_path),
        },
        "semantic_receipts": {
            "source_owner_sha256": semantic_json_sha(source_owner_path),
            "route_sha256": semantic_json_sha(route_path),
        },
        "terminal_files": terminal_files,
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
        1
        for row in rows
        if str(row.get("exit_reason") or row.get("reason") or "unknown").strip().lower()
        in {"", "unknown", "none", "null"}
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


def install_guards(base: Any, input_manifest: Mapping[str, Any]) -> None:
    original_checkpoint_payload = base.checkpoint_payload
    original_heartbeat = base.heartbeat
    original_baseline_body = base.baseline_body
    original_candidate_body = base.candidate_body
    original_build_receipt = base.build_receipt

    def checkpoint_payload_guard(*, kind: str, fingerprint: str, body: Mapping[str, Any]) -> dict[str, Any]:
        payload = original_checkpoint_payload(kind=kind, fingerprint=fingerprint, body=body)
        payload.update(SAFETY)
        payload["checkpoint_sha256"] = stable_sha(
            {key: value for key, value in payload.items() if key != "checkpoint_sha256"}
        )
        return payload

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
        receipt.update(SAFETY)
        receipt["receipt_sha256"] = stable_sha(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
        return receipt

    base.row_integrity = row_integrity
    base.checkpoint_payload = checkpoint_payload_guard
    base.heartbeat = heartbeat_guard
    base.baseline_body = baseline_body_guard
    base.candidate_body = candidate_body_guard
    base.build_receipt = build_receipt_guard


def run_guarded(
    *,
    base_runner_path: Path,
    screen_path: Path,
    engine_path: Path,
    policy_path: Path,
    source_root: Path,
    data_root: Path,
    terminal_root: Path,
    source_owner_path: Path,
    route_path: Path,
    checkpoint_dir: Path,
    heartbeat_out: Path | None,
    input_manifest_out: Path,
    commit_sha: str,
    out: Path,
) -> dict[str, Any]:
    base = load_module(base_runner_path, f"zel_causal_resumable_base_{os.getpid()}")
    screen = base.load_module(screen_path, f"zel_causal_screen_guarded_{os.getpid()}")
    policy = base.read_json(policy_path)
    source_owner = base.read_json(source_owner_path)
    route = base.read_json(route_path)
    base.validate_external_receipts(source_owner, route)

    input_manifest = build_input_manifest(
        base_runner_path=base_runner_path,
        screen_path=screen_path,
        engine_path=engine_path,
        policy_path=policy_path,
        source_root=source_root,
        data_root=data_root,
        terminal_root=terminal_root,
        source_owner_path=source_owner_path,
        route_path=route_path,
        commit_sha=commit_sha,
    )
    atomic_write_json(input_manifest_out, input_manifest)
    fingerprint = stable_sha(
        {
            "schema_version": "zel.exact25.causal_exit_screen.input_fingerprint.v2",
            "input_manifest_sha256": input_manifest["manifest_sha256"],
            "strategy_id": policy["strategy_id"],
            "axis_id": policy["axis_id"],
        }
    )
    install_guards(base, input_manifest)

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
    engine = screen.load_module(
        engine_path, f"zel_causal_exit_engine_guarded_{os.getpid()}"
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
                    screen,
                    engine,
                    policy,
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
                        screen,
                        engine,
                        policy,
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
            screen,
            policy,
            baseline,
            candidates,
            fingerprint=fingerprint,
            checkpoint_dir=checkpoint_dir,
            source_owner=source_owner,
            route=route,
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
            "exit_reason": "take_profit",
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
    ]
    integrity = row_integrity(rows)
    assert integrity["missing_identity_count"] == 1
    assert integrity["duplicate_trade_count"] == 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = root / "data"
        terminal = root / "terminal"
        source_root = root / "source"
        producer = source_root / PRODUCER_RELATIVE_PATH
        data.mkdir()
        terminal.mkdir()
        producer.parent.mkdir(parents=True)
        (data / "manifest.json").write_text('{"x":1}\n', encoding="utf-8")
        (terminal / "report.json").write_text('{"state":"PASS"}\n', encoding="utf-8")
        (terminal / "trades.jsonl.gz").write_bytes(b"trades")
        producer.write_text("PRODUCER_V1\n", encoding="utf-8")
        base_runner = root / "base.py"
        screen = root / "screen.py"
        engine = root / "engine.py"
        policy = root / "policy.json"
        source_owner = root / "source_owner.json"
        route = root / "route.json"
        for path, content in (
            (base_runner, "BASE\n"),
            (screen, "SCREEN\n"),
            (engine, "ENGINE\n"),
            (policy, '{}\n'),
            (source_owner, '{"state":"PASS","generated_at":"a","receipt_sha256":"b"}\n'),
            (route, '{"state":"PASS","generated_at":"a","receipt_sha256":"b"}\n'),
        ):
            path.write_text(content, encoding="utf-8")
        first_tree = hash_tree(data)
        os.utime(data / "manifest.json", None)
        second_tree = hash_tree(data)
        assert first_tree["tree_sha256"] == second_tree["tree_sha256"]
        (data / "manifest.json").write_text('{"x":2}\n', encoding="utf-8")
        third_tree = hash_tree(data)
        assert first_tree["tree_sha256"] != third_tree["tree_sha256"]
        (data / "manifest.json").write_text('{"x":1}\n', encoding="utf-8")
        first_manifest = build_input_manifest(
            base_runner_path=base_runner,
            screen_path=screen,
            engine_path=engine,
            policy_path=policy,
            source_root=source_root,
            data_root=data,
            terminal_root=terminal,
            source_owner_path=source_owner,
            route_path=route,
            commit_sha="a" * 40,
        )
        os.utime(producer, None)
        timestamp_only_manifest = build_input_manifest(
            base_runner_path=base_runner,
            screen_path=screen,
            engine_path=engine,
            policy_path=policy,
            source_root=source_root,
            data_root=data,
            terminal_root=terminal,
            source_owner_path=source_owner,
            route_path=route,
            commit_sha="a" * 40,
        )
        assert first_manifest["manifest_sha256"] == timestamp_only_manifest["manifest_sha256"]
        producer.write_text("PRODUCER_V2\n", encoding="utf-8")
        changed_manifest = build_input_manifest(
            base_runner_path=base_runner,
            screen_path=screen,
            engine_path=engine,
            policy_path=policy,
            source_root=source_root,
            data_root=data,
            terminal_root=terminal,
            source_owner_path=source_owner,
            route_path=route,
            commit_sha="a" * 40,
        )
        assert first_manifest["code"]["producer_sha256"] != changed_manifest["code"]["producer_sha256"]
        assert first_manifest["manifest_sha256"] != changed_manifest["manifest_sha256"]
        source_owner.write_text(
            json.dumps({"state": "PASS", "generated_at": "c", "receipt_sha256": "d"}),
            encoding="utf-8",
        )
        assert first_manifest["semantic_receipts"]["source_owner_sha256"] == semantic_json_sha(source_owner)
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-runner", type=Path)
    parser.add_argument("--screen", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--terminal-root", type=Path)
    parser.add_argument("--source-owner", type=Path)
    parser.add_argument("--route", type=Path)
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
        args.engine,
        args.policy,
        args.source_root,
        args.data_root,
        args.terminal_root,
        args.source_owner,
        args.route,
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
        engine_path=args.engine.resolve(),
        policy_path=args.policy.resolve(),
        source_root=args.source_root.resolve(),
        data_root=args.data_root.resolve(),
        terminal_root=args.terminal_root.resolve(),
        source_owner_path=args.source_owner.resolve(),
        route_path=args.route.resolve(),
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
