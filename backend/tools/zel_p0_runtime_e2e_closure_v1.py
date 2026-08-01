from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def load_module(name: str, filename: str) -> Any:
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def run_closure(out_dir: Path, receipt_path: Path) -> dict[str, Any]:
    replay = load_module("zel_replay_v2_e2e", "zel_historical_oos_exact25_replay_v2.py")
    dag = load_module("zel_dag_e2e", "zel_pre_shadow_receipt_dag_v1.py")
    alpha = load_module("zel_alpha_e2e", "zel_alpha_lap_v2_economic_adapter_v1.py")
    bingx = load_module("zel_bingx_e2e", "zel_bingx_execution_calibration_adapter_v1.py")
    component = load_module("zel_component_e2e", "zel_component_counterfactual_attribution_v1.py")

    out_dir.mkdir(parents=True, exist_ok=True)
    fixture = out_dir / "fixture"
    fixture.mkdir(parents=True, exist_ok=True)

    # 1) Replay durability: checkpoint write/load, stale-fingerprint rejection,
    # invalid checkpoint quarantine, progress, atomic terminal files and SHA manifest.
    replay_root = out_dir / "replay_v2"
    checkpoints = replay_root / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    fingerprint = sha_text("p0-runtime-e2e-input")
    strategy_result = {
        "strategy_id": "fixture_strategy_01",
        "strategy_call_count": 3,
        "signal_count": 2,
        "valid_entry_count": 1,
        "open_count": 0,
        "censored_open_at_window_end": 0,
        "error_count": 0,
    }
    valid_cp = replay.checkpoint_path(checkpoints, strategy_result["strategy_id"])
    replay.save_checkpoint(valid_cp, fingerprint, strategy_result)
    loaded = replay.load_checkpoint(valid_cp, fingerprint, strategy_result["strategy_id"])
    if loaded != strategy_result:
        raise RuntimeError("CHECKPOINT_ROUNDTRIP_FAILED")
    if replay.load_checkpoint(valid_cp, sha_text("different"), strategy_result["strategy_id"]) is not None:
        raise RuntimeError("STALE_FINGERPRINT_ACCEPTED")

    invalid_cp = checkpoints / "invalid.json.gz"
    invalid_cp.write_bytes(b"not-gzip")
    replay.quarantine_invalid(invalid_cp)
    quarantined = list(checkpoints.glob("invalid.json.gz.invalid.*"))
    if len(quarantined) != 1:
        raise RuntimeError("INVALID_CHECKPOINT_NOT_QUARANTINED")

    replay.write_progress(
        replay_root / "progress.json",
        "p0-e2e",
        fingerprint,
        replay.now_iso(),
        __import__("time").monotonic(),
        5,
        ["s1", "s2", "s3"],
        [],
        "RUNNING",
        "s3",
    )
    progress = json.loads((replay_root / "progress.json").read_text())
    if progress["completed_units"] != 3 or progress["progress_pct"] != 60.0:
        raise RuntimeError("PROGRESS_HEARTBEAT_INVALID")

    replay.atomic_json(replay_root / "report.json", {
        "state": "PASS",
        "interval": "fixture",
        "replay": {"strategy_count_completed": 25, "strategy_failure_count": 0, "error_count": 0},
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    })
    replay.atomic_json(replay_root / "summary.json", {
        "state": "PASS",
        "strategy_count_completed": 25,
        "strategy_failure_count": 0,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
    })
    (replay_root / "scoreboard.csv").write_text("strategy_id,state\nfixture,PASS\n", encoding="utf-8")

    class TraceEngine:
        @staticmethod
        def parse_epoch(value: Any) -> float:
            return float(value or 0.0)

    replay.atomic_trades(
        replay_root / "trades.jsonl.gz",
        [{"event_id": "e1", "exit_ts": 1, "realized_R": 0.5}],
        TraceEngine(),
    )
    terminal_names = ["report.json", "summary.json", "scoreboard.csv", "trades.jsonl.gz", "progress.json"]
    artifact_manifest = replay.artifact_manifest(replay_root, terminal_names, fingerprint)
    replay.atomic_json(replay_root / "artifact_manifest.json", artifact_manifest)
    replay.atomic_json(replay_root / "terminal_receipt.json", {
        "state": "PASS_REPLAY_V2_TERMINAL_E2E",
        "input_fingerprint": fingerprint,
        "checkpoint_roundtrip": True,
        "stale_fingerprint_rejected": True,
        "invalid_checkpoint_quarantined": True,
        "artifact_manifest_sha256": replay.sha256_path(replay_root / "artifact_manifest.json"),
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    })
    for name in terminal_names + ["artifact_manifest.json", "terminal_receipt.json"]:
        path = replay_root / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"ATOMIC_TERMINAL_MISSING:{name}")
    with gzip.open(replay_root / "trades.jsonl.gz", "rt", encoding="utf-8") as handle:
        if len([line for line in handle if line.strip()]) != 1:
            raise RuntimeError("TRADES_GZIP_INVALID")

    # 2) BingX calibration actual CLI-equivalent file path.
    bingx_input = fixture / "bingx_sanitized.json"
    write_json(bingx_input, {
        "commission": {"makerCommissionRate": 0.0002, "takerCommissionRate": 0.0005},
        "transactions": [
            {"type": "REALIZED_PNL", "amount": 10.0},
            {"type": "TRADING_FEE", "amount": -1.0},
            {"type": "FUNDING_FEE", "amount": -0.2},
            {"type": "INSURANCE_CLEAR liquidation", "amount": -2.0},
        ],
        "orders": [
            {"side": "BUY", "requested_price": 100.0, "average_fill_price": 100.1,
             "order_created_at": 1000, "first_fill_at": 1001, "final_fill_at": 1002, "status": "FILLED"},
            {"side": "SELL", "requested_price": 101.0, "average_fill_price": 100.9,
             "order_created_at": 2000, "first_fill_at": 2001, "final_fill_at": 2001.5, "status": "FILLED"},
        ],
    })
    bingx_receipt = bingx.calibrate(bingx_input)
    bingx.atomic_json(out_dir / "bingx_calibration.json", bingx_receipt)
    if bingx_receipt["state"] != "PASS_BINGX_EXECUTION_CALIBRATION_EVIDENCE":
        raise RuntimeError("BINGX_CALIBRATION_E2E_FAILED")
    if bingx_receipt["application_allowed"] is not False:
        raise RuntimeError("BINGX_APPLICATION_AUTHORITY_LEAK")

    # 3) Component attribution actual paired file analysis across every component.
    context = {
        "opportunity_id": "op1",
        "timestamp": "2026-01-01T00:00:00Z",
        "symbol": "BTCUSDT",
        "regime": "trend",
        "cost_model_sha256": sha_text("cost"),
        "risk_budget": "1R",
        "data_manifest_sha256": sha_text("data"),
    }
    base_path = fixture / "component_base.jsonl"
    variants_path = fixture / "component_variants.jsonl"
    base_path.write_text(json.dumps({**context, "net_R": 0.5}) + "\n", encoding="utf-8")
    variant_lines = []
    for index, name in enumerate(component.COMPONENTS):
        delta = 0.0 if name == "ZLICE" else (index + 1) / 100.0
        variant_lines.append(json.dumps({
            **context,
            "component": name,
            "net_R": 0.5 + delta,
            "counterfactual_id": f"cf.{name.lower()}",
            "bundle_sha256": sha_text(name),
        }))
    variants_path.write_text("\n".join(variant_lines) + "\n", encoding="utf-8")
    component_receipt = component.analyze(base_path, variants_path)
    component.atomic_json(out_dir / "component_attribution.json", component_receipt)
    if component_receipt["state"] != "PASS_COMPONENT_COUNTERFACTUAL_ATTRIBUTION":
        raise RuntimeError("COMPONENT_ATTRIBUTION_E2E_FAILED")
    if component_receipt["paired_count"] != len(component.COMPONENTS):
        raise RuntimeError("COMPONENT_PAIR_COUNT_INVALID")
    if component_receipt["components"]["ZLICE"]["delta_net_R"] != 0.0:
        raise RuntimeError("ZLICE_DIRECT_DELTA_NONZERO")

    # 4) Alpha Lap challenger registration plus paired Champion/Challenger comparison.
    keys = (
        "strategy_sha256", "method_sha256", "skill_sha256", "team_sha256",
        "zbot_sha256", "lico_sha256", "zico_sha256", "zlice_sha256",
        "risk_model_sha256", "cost_model_sha256", "bundle_sha256",
    )
    hashes = {key: sha_text(key) for key in keys}
    top3_path = fixture / "top3.json"
    champion_registry_path = fixture / "champions.json"
    write_json(top3_path, {"bundles": [{"strategy_id": "s1", "slot_id": "slot1", "rank": 1, **hashes}]})
    write_json(champion_registry_path, {"slots": [{"slot_id": "slot1", "bundle_sha256": sha_text("old")}]})
    alpha_registry = alpha.register_challengers(top3_path, champion_registry_path)
    alpha.atomic_json(out_dir / "alpha_challengers.json", alpha_registry)
    if alpha_registry["state"] != "PASS_ALPHA_LAP_CHALLENGERS_REGISTERED":
        raise RuntimeError("ALPHA_REGISTER_E2E_FAILED")

    champion_trace = fixture / "champion.jsonl"
    challenger_trace = fixture / "challenger.jsonl"
    alpha_context = {
        "opportunity_id": "alpha-op1",
        "timestamp": "2026-01-01T01:00:00Z",
        "symbol": "BTCUSDT",
        "regime": "trend",
        "cost_model_sha256": sha_text("alpha-cost"),
        "risk_budget": "1R",
    }
    champion_trace.write_text(json.dumps({**alpha_context, "net_R": -0.5}) + "\n", encoding="utf-8")
    challenger_trace.write_text(json.dumps({**alpha_context, "net_R": 1.0}) + "\n", encoding="utf-8")
    alpha_compare = alpha.paired_compare(champion_trace, challenger_trace)
    alpha.atomic_json(out_dir / "alpha_paired_compare.json", alpha_compare)
    if alpha_compare["state"] != "PASS_ALPHA_LAP_PAIRED_COMPARISON":
        raise RuntimeError("ALPHA_PAIRED_E2E_FAILED")

    # 5) Full 13-stage receipt DAG with exact predecessor/stage SHA bindings.
    dag_root = out_dir / "dag_results"
    receipts: dict[str, Path] = {}
    for stage in dag.STAGES:
        stage_id = str(stage["id"])
        path = dag_root / str(stage["path"])
        if stage_id == "DATA_B_TERMINAL":
            payload = {
                "state": "PASS",
                "single_owner_proved": True,
                "intervals": {"1m": {"error_count": 0, "report_sha256": replay.sha256_path(replay_root / "report.json")}},
                "source_mode": "ISOLATED_P0_RUNTIME_E2E",
            }
        elif stage_id == "ALPHA_LAP_CHALLENGERS":
            payload = dict(alpha_registry)
        else:
            allowed = list(stage.get("states") or [])
            state = allowed[0] if allowed else "PASS_TRADE_METHOD_COVERAGE_E2E"
            payload = {
                "state": state,
                "source_mode": "ISOLATED_P0_RUNTIME_E2E",
                "source_receipt_sha256": replay.sha256_path(replay_root / "terminal_receipt.json"),
            }
        payload.update({
            "selection_authority": False,
            "promotion_authority": False,
            "live_enabled": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        })
        dag.write_receipt(path, payload)
        receipts[stage_id] = path
        requires = list(stage.get("requires") or [])
        if requires:
            predecessor_id = requires[-1]
            binding = dag.binding_path(dag_root, stage_id)
            dag.write_receipt(binding, {
                "state": "PASS_STAGE_LINEAGE_BOUND",
                "stage_id": stage_id,
                "predecessor_stage_id": predecessor_id,
                "predecessor_receipt_sha256": dag.sha256_path(receipts[predecessor_id]),
                "stage_receipt_sha256": dag.sha256_path(path),
                "promotion_authority": False,
                "execution_authority": "NONE",
                "order_authority": "BLOCKED",
                "action": "hold",
            })

    dag_receipt = dag.evaluate(dag_root)
    dag.atomic_json(out_dir / "dag_complete.json", dag_receipt)
    if dag_receipt["state"] != "PASS_PRE_SHADOW_DAG_COMPLETE":
        raise RuntimeError(f"DAG_E2E_FAILED:{dag_receipt['first_blocked_stage']}")
    if dag_receipt["passed_stage_count"] != len(dag.STAGES):
        raise RuntimeError("DAG_STAGE_COUNT_INVALID")

    closure = {
        "schema_version": "zel.p0.runtime_e2e_closure.v1",
        "generated_at": replay.now_iso(),
        "state": "PASS_P0_RUNTIME_E2E_CLOSURE",
        "scope": "ISOLATED_FILE_IO_AND_RECEIPT_CHAIN",
        "production_data_b_1m_terminal_claimed": False,
        "checks": {
            "checkpoint_roundtrip": True,
            "stale_fingerprint_rejected": True,
            "invalid_checkpoint_quarantine": True,
            "atomic_terminal_file_count": 7,
            "artifact_manifest_terminal_complete": artifact_manifest["terminal_complete"],
            "bingx_calibration_state": bingx_receipt["state"],
            "component_attribution_state": component_receipt["state"],
            "component_pair_count": component_receipt["paired_count"],
            "alpha_registration_state": alpha_registry["state"],
            "alpha_paired_state": alpha_compare["state"],
            "dag_state": dag_receipt["state"],
            "dag_passed_stage_count": dag_receipt["passed_stage_count"],
        },
        "artifacts": {
            "replay_terminal_receipt_sha256": replay.sha256_path(replay_root / "terminal_receipt.json"),
            "replay_artifact_manifest_sha256": replay.sha256_path(replay_root / "artifact_manifest.json"),
            "bingx_receipt_sha256": bingx.sha256_path(out_dir / "bingx_calibration.json"),
            "component_receipt_sha256": component.sha256_path(out_dir / "component_attribution.json"),
            "alpha_registry_sha256": alpha.sha256_path(out_dir / "alpha_challengers.json"),
            "alpha_compare_sha256": alpha.sha256_path(out_dir / "alpha_paired_compare.json"),
            "dag_receipt_sha256": dag.sha256_path(out_dir / "dag_complete.json"),
        },
        "safety": {
            "canonical_strategy_mutated": False,
            "formal_ledger_mutated": False,
            "runtime_registry_written": False,
            "shadow_started": False,
            "paper_started": False,
            "live_enabled": False,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "action": "hold",
        },
        "next": "WAIT_PRODUCTION_DATA_B_1M_TERMINAL_THEN_VALIDATE_REAL_RECEIPT_DAG",
    }
    write_json(receipt_path, closure)
    return closure


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        result = run_closure(root / "out", root / "latest.json")
        assert result["state"] == "PASS_P0_RUNTIME_E2E_CLOSURE", result
        assert result["checks"]["dag_passed_stage_count"] == 13, result
        assert result["safety"]["execution_authority"] == "NONE", result
    print(json.dumps({"state": "PASS_SELF_TEST"}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir")
    parser.add_argument("--receipt")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.out_dir or not args.receipt:
        parser.error("out-dir and receipt are required")
    result = run_closure(Path(args.out_dir), Path(args.receipt))
    print(json.dumps({"state": result["state"], "dag": result["checks"]["dag_state"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
