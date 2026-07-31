from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

SAFE = {
    "research_only": True,
    "promotion_authority": False,
    "protected_mutations": 0,
    "canonical_mutated": False,
    "registry_mutated": False,
    "execution_allowed": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "runtime_bound": False,
    "shadow_start_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
}


def strict_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"NONFINITE:{value}")))


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def stable_sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def assert_safety(row: Mapping[str, Any], *, allow_missing: bool = False) -> None:
    for key, expected in SAFE.items():
        if key not in row and allow_missing:
            continue
        if row.get(key) != expected:
            raise RuntimeError(f"SAFETY_MISMATCH:{key}:{row.get(key)!r}:{expected!r}")


def load_native(native_root: Path, contract: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    native = strict_json(native_root / "native-out" / "status.json")
    shared = strict_json(native_root / "shared-w1" / "status.json")
    manifest_path = native_root / "shared-w1" / "data" / "manifest.json"
    manifest = strict_json(manifest_path)
    expected = contract["w1"]
    if native.get("state") != expected["native_required_state"]:
        raise RuntimeError(f"NATIVE_STATE:{native.get('state')}")
    if native.get("one_shot_completed") is not True:
        raise RuntimeError("NATIVE_ONE_SHOT_INCOMPLETE")
    assert_safety(native, allow_missing=True)
    assert_safety(shared, allow_missing=True)
    manifest_sha = file_sha(manifest_path)
    if native.get("source_w1_manifest_sha256") != manifest_sha:
        raise RuntimeError("NATIVE_MANIFEST_SHA_MISMATCH")
    if shared.get("W1_manifest_sha256") != manifest_sha:
        raise RuntimeError("SHARED_MANIFEST_SHA_MISMATCH")
    if manifest.get("state") != "PASS" or manifest.get("blockers") != []:
        raise RuntimeError("W1_MANIFEST_NOT_PASS")
    if manifest.get("window_id") != "W1":
        raise RuntimeError("W1_WINDOW_ID")
    if int(manifest.get("evaluation_bars") or 0) != int(expected["required_evaluation_bars"]):
        raise RuntimeError("W1_EVALUATION_BARS")
    if int(manifest.get("warmup_bars") or 0) != int(expected["required_warmup_bars"]):
        raise RuntimeError("W1_WARMUP_BARS")
    if len(manifest.get("files") or []) != int(expected["required_symbol_count"]):
        raise RuntimeError("W1_SYMBOL_COUNT")
    exact_end = str(expected["exact_end_utc"]).replace("Z", "+00:00")
    if str(manifest.get("evaluation_end")) != exact_end:
        raise RuntimeError(f"W1_EXACT_END:{manifest.get('evaluation_end')}:{exact_end}")
    return native, shared, manifest, manifest_path


def native_receipt(native_root: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    native, shared, manifest, manifest_path = load_native(native_root, contract)
    payload = {
        "schema_version": "zel.w1.durable_receipt.v1",
        "state": "PASS_DURABLE_NATIVE_RECEIPT_READY",
        "release_tag": contract["w1"]["native_durable_release_tag"],
        "source_w1_run_id": str(native["source_w1_run_id"]),
        "source_w1_head_sha": str(native["source_w1_head_sha"]),
        "source_w1_manifest_sha256": file_sha(manifest_path),
        "native_status_sha256": file_sha(native_root / "native-out" / "status.json"),
        "shared_status_sha256": file_sha(native_root / "shared-w1" / "status.json"),
        "manifest_window_id": manifest["window_id"],
        "evaluation_start": manifest["evaluation_start"],
        "evaluation_end": manifest["evaluation_end"],
        "evaluation_bars": int(manifest["evaluation_bars"]),
        "warmup_bars": int(manifest["warmup_bars"]),
        "symbol_count": len(manifest["files"]),
        **SAFE,
    }
    payload["receipt_sha256"] = stable_sha(payload)
    return payload


def trade_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [number(row.get("net_return_pct")) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gross_loss = abs(sum(losses))
    return {
        "trade_count": len(rows),
        "win_rate_pct": 100.0 * len(wins) / len(rows) if rows else 0.0,
        "net_return_pct_sum": sum(values),
        "profit_factor": sum(wins) / gross_loss if gross_loss > 1e-12 else (999.0 if wins else 0.0),
        "max_drawdown_pct": drawdown,
    }


def validate_trades(rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    required = list(contract["component_authority"]["required_trade_fields"])
    output: list[dict[str, Any]] = []
    blockers: list[str] = []
    identities: set[tuple[str, ...]] = set()
    for index, source in enumerate(rows):
        row = dict(source)
        missing = [key for key in required if row.get(key) is None]
        if missing:
            blockers.append(f"TRADE_{index}_MISSING:{','.join(missing)}")
            continue
        identity = (
            str(row["window_id"]), str(row["symbol"]), str(row.get("side") or "LONG"),
            str(row["entry_ts"]), str(row["exit_ts"]),
        )
        if identity in identities:
            blockers.append(f"DUPLICATE_TRADE:{identity}")
            continue
        identities.add(identity)
        if not isinstance(row.get("features"), Mapping):
            blockers.append(f"TRADE_{index}_FEATURES_NOT_OBJECT")
            continue
        output.append(row)
    return output, blockers


def bind_authority(
    native_root: Path,
    ema_status_path: Path,
    v3_root: Path,
    contract: Mapping[str, Any],
    out: Path,
) -> dict[str, Any]:
    native, _shared, manifest, manifest_path = load_native(native_root, contract)
    manifest_sha = file_sha(manifest_path)
    ema = strict_json(ema_status_path)
    v3 = strict_json(v3_root / "status.json")
    assert_safety(ema, allow_missing=True)
    assert_safety(v3, allow_missing=True)
    if ema.get("state") not in set(contract["terminal_states"]["ema"]):
        raise RuntimeError(f"EMA_NOT_TERMINAL:{ema.get('state')}")
    if ema.get("source_w1_manifest_sha256") != manifest_sha:
        raise RuntimeError("EMA_MANIFEST_SHA_MISMATCH")
    if v3.get("state") not in set(contract["terminal_states"]["v3"]):
        raise RuntimeError(f"V3_NOT_TERMINAL:{v3.get('state')}")
    if v3.get("source_w1_manifest_sha256") != manifest_sha:
        raise RuntimeError("V3_MANIFEST_SHA_MISMATCH")
    use_candidate = v3.get("state") == contract["component_authority"]["pass_candidate_state"]
    trade_name = contract["component_authority"]["candidate_trade_file"] if use_candidate else contract["component_authority"]["control_trade_file"]
    selected = strict_json(v3_root / trade_name)
    rows, blockers = validate_trades(selected.get("trades") or [], contract)
    selected_variant = str(v3.get("variant_id") if use_candidate else "NO_CHANGE_CONTROL")
    state = "PASS_W1_EXACT_AUTHORITY_BINDER" if rows and not blockers else "WAIT_EXACT_LEDGER_BINDING"
    stats = trade_stats(rows)
    claim = contract["claim_policy"]
    if stats["trade_count"] < int(claim["hypothesis_review_min_trades"]):
        economic_state = "LOW_SAMPLE_HOLD"
    elif stats["trade_count"] < int(claim["component_efficacy_min_trades"]):
        economic_state = "HYPOTHESIS_ONLY_HOLD"
    else:
        economic_state = "READY_COMPONENT_EFFICACY_REPLAY"
    source_result_sha = str(v3.get("result_sha256") or stable_sha(v3))
    authority_exact_sha = stable_sha({
        "manifest_sha": manifest_sha,
        "selected_variant": selected_variant,
        "selected_trade_sha": stable_sha(rows),
        "source_result_sha": source_result_sha,
    })
    ledger = {"strategy_id": contract["component_authority"]["strategy_id"], "trades": rows}
    summary = {
        "schema_version": "zel.component.dynamic_summary.v1",
        "state": state,
        "strategy_id": contract["component_authority"]["strategy_id"],
        "strategy_variant": selected_variant,
        "authority": "READ_ONLY_BASELINE_EVIDENCE_NO_EXECUTION",
        "baseline": stats,
        "symbols": sorted({str(row["symbol"]) for row in rows}),
        "authority_exact_summary_sha256": authority_exact_sha,
        "selected_authority_result_sha256": source_result_sha,
        "source_w1_manifest_sha256": manifest_sha,
        "source_native_run_id": str(native["source_w1_run_id"]),
        "source_ema_state": ema["state"],
        "source_v3_state": v3["state"],
        "selection_reason": "V3_PASS_CANDIDATE" if use_candidate else "V3_NONPASS_RETAIN_CONTROL",
        **SAFE,
    }
    target = out / "component-authority" / contract["component_authority"]["strategy_id"]
    write_json(target / "baseline_trades.json", ledger)
    write_json(target / "summary.json", summary)
    authority = {
        "schema_version": contract["component_authority"]["schema_version"],
        "state": state,
        "economic_state": economic_state,
        "strategy_id": contract["component_authority"]["strategy_id"],
        "selected_variant": selected_variant,
        "source_w1_manifest_sha256": manifest_sha,
        "source_native_run_id": str(native["source_w1_run_id"]),
        "source_native_head_sha": str(native["source_w1_head_sha"]),
        "source_ema_state": ema["state"],
        "source_v3_state": v3["state"],
        "trade_count": stats["trade_count"],
        "trade_ledger_file_sha256": file_sha(target / "baseline_trades.json"),
        "summary_file_sha256": file_sha(target / "summary.json"),
        "authority_exact_summary_sha256": authority_exact_sha,
        "selected_authority_result_sha256": source_result_sha,
        "blockers": blockers,
        "component_dispatch_allowed": state == "PASS_W1_EXACT_AUTHORITY_BINDER",
        "performance_claim_allowed": False,
        **SAFE,
    }
    write_json(out / "component-authority" / "authority.json", authority)
    receipt = native_receipt(native_root, contract)
    project = {
        "schema_version": "zel.project_state.v1",
        "state": "PASS_W1_CONTROL_PLANE_CLOSED" if state == "PASS_W1_EXACT_AUTHORITY_BINDER" else state,
        "structure_state": "PASS_CONTROL_PLANE" if state == "PASS_W1_EXACT_AUTHORITY_BINDER" else "HOLD_CONTROL_PLANE",
        "economic_state": economic_state,
        "master_or_source_head_sha": str(native["source_w1_head_sha"]),
        "w1": {
            "manifest_sha256": manifest_sha,
            "evaluation_start": manifest["evaluation_start"],
            "evaluation_end": manifest["evaluation_end"],
            "evaluation_bars": manifest["evaluation_bars"],
            "symbol_count": len(manifest["files"]),
            "native_state": native["state"],
            "ema_state": ema["state"],
            "v3_state": v3["state"],
        },
        "component_authority": authority,
        "durable_native_receipt": receipt,
        "next": "DISPATCH_COMPONENT_AUTONOMY_V3" if authority["component_dispatch_allowed"] else "HOLD_FIX_EXACT_LEDGER_BINDING",
        **SAFE,
    }
    project["project_state_sha256"] = stable_sha(project)
    write_json(out / "project_state_latest.json", project)
    write_json(out / "durable_native_receipt.json", receipt)
    return project


def static_audit(args: argparse.Namespace) -> dict[str, Any]:
    contract = strict_json(args.contract)
    texts = {name: Path(path).read_text(encoding="utf-8") for name, path in {
        "accelerator": args.accelerator,
        "native_gate": args.native_gate,
        "v3_workflow": args.v3_workflow,
        "component_workflow": args.component_workflow,
        "control_workflow": args.control_workflow,
        "component_wrapper": args.component_wrapper,
        "notifier": args.notifier,
    }.items()}
    authority_registry = strict_json(args.authority_registry)
    findings: list[str] = []
    checks = {
        "PRE_FINAL_PREFLIGHT_SCHEDULE_MISSING": "'32 8 1 8 *'" in texts["accelerator"],
        "ACCELERATOR_DIRECT_V3_DISPATCH_RESIDUE": "V3_SURVIVOR_OVERLAY" not in texts["accelerator"],
        "NATIVE_DURABLE_RELEASE_NOT_BOUND": "durable_completion_release_tag" in texts["native_gate"],
        "V3_COMPUTE_SHA_NOT_PINNED": contract["pinned_authorities"]["v3_compute"]["head_sha"] in texts["v3_workflow"],
        "V3_MUTABLE_COMPUTE_REF_RESIDUE": "ref: ${{ env.COMPUTE_REF }}" not in texts["v3_workflow"],
        "DYNAMIC_AUTHORITY_INPUT_NOT_BOUND": "authority_artifact" in texts["component_workflow"] and "authority.json" in texts["component_workflow"],
        "CONTROL_PLANE_RELEASE_NOT_BOUND": contract["w1"]["control_plane_durable_release_tag"] in texts["control_workflow"],
        "COMPONENT_CLAIM_GATES_NOT_BOUND": all(token in texts["component_wrapper"] for token in (
            "HYPOTHESIS_ONLY_HOLD", "BONFERRONI", "order_stable", "exact_skill_replay_required",
        )),
        "STATE_AWARE_NOTIFIER_NOT_BOUND": "project_state_latest.json" in texts["notifier"] and "state/final.json" in texts["notifier"],
        "AUTHORITY_REGISTRY_NOT_PINNED": all(
            (row.get("status") == "PENDING_MASTER_MERGE" and not row.get("head_sha"))
            or (row.get("head_sha") and row.get("status") in {"ACTIVE_PINNED","ACTIVE_PINNED_ISOLATED_CHECKOUT","LEGACY_BASELINE_PROVENANCE"})
            for row in authority_registry.get("authorities", [])
        ),
    }
    for code, passed in checks.items():
        if not passed:
            findings.append(code)
    result = {
        "schema_version": "zel.control_plane.static_audit.v1",
        "state": "PASS_ZEL_CONTROL_PLANE_HARDENING_AUDIT" if not findings else "HOLD_ZEL_CONTROL_PLANE_HARDENING_REPAIR_REQUIRED",
        "finding_count": len(findings),
        "findings": findings,
        "checks": checks,
        **SAFE,
    }
    result["report_sha256"] = stable_sha(result)
    return result


def fixture(out: Path, contract: Mapping[str, Any]) -> None:
    native = out / "fixture-native"
    manifest = {
        "state": "PASS", "blockers": [], "window_id": "W1",
        "evaluation_start": "2026-07-27T08:45:00+00:00",
        "evaluation_end": "2026-08-01T08:30:00+00:00",
        "evaluation_bars": 480, "warmup_bars": 220,
        "files": [{"symbol": value, "path": f"data/{value}.csv", "sha256": "fixture"} for value in ("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","LINKUSDT")],
    }
    write_json(native / "shared-w1" / "data" / "manifest.json", manifest)
    manifest_sha = file_sha(native / "shared-w1" / "data" / "manifest.json")
    write_json(native / "shared-w1" / "status.json", {"state": "PASS", "blockers": [], "W1_manifest_sha256": manifest_sha, **SAFE})
    write_json(native / "native-out" / "status.json", {
        "state": "PASS_W1_NATIVE_PRIMARY_CHAIN", "blockers": [], "one_shot_completed": True,
        "source_w1_manifest_sha256": manifest_sha, "source_w1_run_id": "fixture-run",
        "source_w1_head_sha": "f" * 40, **SAFE,
    })
    ema = out / "ema-status.json"
    write_json(ema, {"state": "W1_LOW_SAMPLE_HOLD", "source_w1_manifest_sha256": manifest_sha, **SAFE})
    v3 = out / "fixture-v3"
    rows = []
    for index in range(24):
        rows.append({
            "window_id": f"F{1+index//8}", "symbol": "BTCUSDT" if index % 2 == 0 else "SOLUSDT",
            "entry_ts": f"2026-01-{1+index:02d}T00:00:00+00:00",
            "exit_ts": f"2026-01-{1+index:02d}T01:00:00+00:00",
            "net_return_pct": 0.2 if index % 3 else -0.1, "mfe_r": 1.0, "mae_r": 0.3,
            "bars_held": 4, "signal_ts": f"2026-01-{1+index:02d}T00:00:00+00:00",
            "features": {"trend_ema20_50": True}, "side": "LONG",
        })
    write_json(v3 / "status.json", {
        "state": "HOLD_W1_LOW_SAMPLE", "source_w1_manifest_sha256": manifest_sha,
        "variant_id": "INT3_MAX_CHASE_DIST_ATR_RELAX", "result_sha256": "a"*64, **SAFE,
    })
    write_json(v3 / "control_trades.json", {"trades": rows})
    write_json(v3 / "candidate_trades.json", {"trades": rows})
    project = bind_authority(native, ema, v3, contract, out / "fixture-out")
    assert project["state"] == "PASS_W1_CONTROL_PLANE_CLOSED"
    assert project["economic_state"] == "HYPOTHESIS_ONLY_HOLD"
    print("PASS_ZEL_CONTROL_PLANE_HARDENING_FIXTURE", project["project_state_sha256"])


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    seal = sub.add_parser("seal-native")
    seal.add_argument("--contract", required=True)
    seal.add_argument("--native-root", required=True)
    seal.add_argument("--out", required=True)
    bind = sub.add_parser("bind")
    bind.add_argument("--contract", required=True)
    bind.add_argument("--native-root", required=True)
    bind.add_argument("--ema-status", required=True)
    bind.add_argument("--v3-root", required=True)
    bind.add_argument("--out", required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--contract", required=True)
    audit.add_argument("--accelerator", required=True)
    audit.add_argument("--native-gate", required=True)
    audit.add_argument("--v3-workflow", required=True)
    audit.add_argument("--component-workflow", required=True)
    audit.add_argument("--control-workflow", required=True)
    audit.add_argument("--component-wrapper", required=True)
    audit.add_argument("--notifier", required=True)
    audit.add_argument("--authority-registry", required=True)
    audit.add_argument("--out", required=True)
    test = sub.add_parser("fixture")
    test.add_argument("--contract", required=True)
    test.add_argument("--out", required=True)
    args = parser.parse_args()
    contract = strict_json(args.contract)
    if args.mode == "seal-native":
        write_json(args.out, native_receipt(Path(args.native_root), contract))
    elif args.mode == "bind":
        bind_authority(Path(args.native_root), Path(args.ema_status), Path(args.v3_root), contract, Path(args.out))
    elif args.mode == "audit":
        write_json(args.out, static_audit(args))
    else:
        fixture(Path(args.out), contract)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
