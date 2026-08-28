#!/usr/bin/env python3
"""Stage-independent orchestrator for the approved 2026-08-28 research roadmap.

The repository already persists authoritative composite receipts for TrendMA fresh
OOS, the C-grade pair nursery, and the Top5 fixed-RR shadow.  This runner binds to
those receipts by default instead of requiring six artificial raw JSON fragments.

Explicit CLI/environment bindings remain supported for diagnostics.  An explicit
bad path never falls back silently.  A missing logical child is reported as HOLD,
not as a workflow failure, and does not prevent unrelated stages from running.
No strategy/selection/promotion/order/live state is mutated here.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
DEFAULT_ROADMAP = ROOT / "z_next_roadmap_20260828_v1.json"

BINDINGS = {
    "trendma_candidate": "Z_TRENDMA_CANDIDATE",
    "nursery_parent_a": "Z_NURSERY_PARENT_A",
    "nursery_parent_b": "Z_NURSERY_PARENT_B",
    "nursery_child": "Z_NURSERY_CHILD",
    "rr_parent": "Z_RR_PARENT",
    "rr_child": "Z_RR_CHILD",
}

TRENDMA_RECEIPT = ROOT / "a1_top6_trend_ma_macd_fresh_oos_latest.json"
NURSERY_RECEIPT = REPO / "backend/research/architecture_factory/a1_c_grade_pair_nursery_latest.json"
RR_RECEIPT = ROOT / "a1_top5_fixed_rr_payoff_shadow_latest.json"

AUTO_SOURCES = {
    "trendma_candidate": TRENDMA_RECEIPT,
    "nursery_parent_a": NURSERY_RECEIPT,
    "nursery_parent_b": NURSERY_RECEIPT,
    "nursery_child": NURSERY_RECEIPT,
    "rr_parent": RR_RECEIPT,
    "rr_child": RR_RECEIPT,
}

RAW_KEYS = {
    "trendma_candidate": {
        "trades", "net_pnl_bps", "net_expectancy_bps", "profit_factor",
        "payoff", "drawdown_bps", "top10_profit_concentration",
    },
    "nursery_parent_a": {"net_expectancy_bps", "profit_factor", "drawdown_bps"},
    "nursery_parent_b": {"net_expectancy_bps", "profit_factor", "drawdown_bps"},
    "nursery_child": {
        "trades", "net_pnl_bps", "net_expectancy_bps", "profit_factor",
        "payoff", "drawdown_bps",
    },
    "rr_parent": {
        "trades", "win_rate", "net_pnl_bps", "net_expectancy_bps",
        "profit_factor", "payoff", "drawdown_bps",
    },
    "rr_child": {
        "trades", "win_rate", "net_pnl_bps", "net_expectancy_bps",
        "profit_factor", "payoff", "drawdown_bps",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _safe_authority(value: dict[str, Any]) -> bool:
    execution = value.get("execution_authority")
    order = value.get("order_authority")
    live = value.get("live_trade_authority")
    selection = value.get("selection_authority")
    promotion = value.get("promotion_authority")
    return (
        execution in {None, "NONE"}
        and order in {None, "BLOCKED"}
        and live in {None, "BLOCKED"}
        and selection in {None, False}
        and promotion in {None, False}
    )


def _inspect(role: str, path: Path, mode: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "role": role,
        "env": BINDINGS[role],
        "mode": mode,
        "path": str(path),
        "status": "HOLD_SOURCE_MISSING",
        "reason": "source file missing",
    }
    if not path.is_file():
        if mode == "explicit":
            base["status"] = "HOLD_INVALID_EXPLICIT"
            base["reason"] = "explicit path does not exist; auto fallback forbidden"
        return base
    try:
        value = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        base["status"] = "HOLD_INVALID_EXPLICIT" if mode == "explicit" else "HOLD_SOURCE_INVALID"
        base["reason"] = str(exc)
        return base

    schema = str(value.get("schema_version") or "")
    base["schema_version"] = schema or None
    base["source_state"] = value.get("state")
    if not _safe_authority(value):
        base["status"] = "HOLD_SOURCE_UNSAFE_AUTHORITY"
        base["reason"] = "source receipt exposes non-research authority"
        return base

    if RAW_KEYS[role].issubset(value.keys()):
        base["status"] = "READY_RAW"
        base["reason"] = "explicit/raw metric contract satisfied"
        return base

    if role == "trendma_candidate" and schema == "zel.a1.top6.trend_ma_macd.fresh_oos.v1":
        if value.get("strategy_id") == "trend_ma_macd" and value.get("candidate_axis") == "LONG_ONLY_ENTRY_SIDE_QUALIFIER":
            base["status"] = "READY_COMPOSITE"
            base["reason"] = "authoritative TrendMA fresh-OOS receipt"
            return base

    if role.startswith("nursery_") and schema == "zel.a1.c_grade_pair_nursery.v1":
        pairs = value.get("pairs") if isinstance(value.get("pairs"), list) else []
        results = value.get("pair_results") if isinstance(value.get("pair_results"), list) else []
        if role in {"nursery_parent_a", "nursery_parent_b"} and len(pairs) >= 1:
            base["status"] = "READY_COMPOSITE"
            base["reason"] = "authoritative nursery receipt contains C-pair context"
            return base
        has_child = bool(value.get("c_to_b_upgrades")) or any(
            isinstance(row, dict) and bool(row.get("metrics")) for row in results
        )
        if role == "nursery_child" and has_child:
            base["status"] = "READY_COMPOSITE"
            base["reason"] = "nursery receipt contains executable child economics"
        elif role == "nursery_child":
            base["status"] = "HOLD_SOURCE_MISSING"
            base["reason"] = "nursery ran, but generator produced no executable child economics"
        return base

    if role.startswith("rr_") and schema == "zel.a1.top5.fixed_rr_payoff_shadow.v1":
        lanes = value.get("lanes") if isinstance(value.get("lanes"), list) else []
        if role == "rr_parent" and lanes and all(isinstance(x.get("base_metrics"), dict) for x in lanes if isinstance(x, dict)):
            base["status"] = "READY_COMPOSITE"
            base["reason"] = "authoritative RR receipt contains frozen parent metrics"
            return base
        if role == "rr_child" and lanes and any(isinstance(x, dict) and x.get("cells") for x in lanes):
            base["status"] = "READY_COMPOSITE"
            base["reason"] = "authoritative RR receipt contains shadow child cells"
            return base

    base["status"] = "HOLD_SCHEMA_MISMATCH"
    base["reason"] = f"source does not satisfy role contract: {role}"
    return base


def _resolve_binding(role: str, cli_value: str | None) -> dict[str, Any]:
    env_name = BINDINGS[role]
    raw = cli_value if cli_value not in {None, ""} else os.environ.get(env_name, "")
    if raw and raw.strip():
        return _inspect(role, Path(raw).expanduser(), "explicit")
    return _inspect(role, AUTO_SOURCES[role], "auto")


def _validate_roadmap(path: Path) -> dict[str, bool]:
    roadmap = _read_json(path)
    checks = {
        "state_active": roadmap.get("state") == "ACTIVE",
        "latest_only_required": roadmap.get("latest_only_ssot_required") is True,
        "parent_mutation_blocked": roadmap.get("parent_mutation") is False,
        "old_history_union_blocked": roadmap.get("old_history_union") is False,
        "execution_none": roadmap.get("execution_authority") == "NONE",
        "order_blocked": roadmap.get("order_authority") == "BLOCKED",
        "live_blocked": roadmap.get("live_trade_authority") == "BLOCKED",
    }
    if not all(checks.values()):
        raise ValueError(f"roadmap authority/integrity check failed: {checks}")
    return checks


def _run(script: str, argv: list[str]) -> None:
    cmd = [sys.executable, str(ROOT / script), *argv]
    completed = subprocess.run(cmd, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"stage failed rc={completed.returncode}: {' '.join(cmd)}")


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_ready(binding: dict[str, Any]) -> bool:
    return str(binding.get("status", "")).startswith("READY_")


def _all_explicit(bindings: dict[str, dict[str, Any]], roles: list[str]) -> bool:
    return all(bindings[r].get("mode") == "explicit" for r in roles)


def _all_auto(bindings: dict[str, dict[str, Any]], roles: list[str]) -> bool:
    return all(bindings[r].get("mode") == "auto" for r in roles)


def _trendma_stage(bindings: dict[str, dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    b = bindings["trendma_candidate"]
    if not _is_ready(b):
        return {"state": "HOLD_TRENDMA_BINDING", "binding_status": b["status"], "reason": b["reason"]}
    source = Path(b["path"])
    value = _read_json(source)
    if b["status"] == "READY_COMPOSITE":
        return {
            "state": value.get("state", "HOLD_TRENDMA_RECEIPT_UNKNOWN"),
            "source": str(source),
            "source_schema": value.get("schema_version"),
            "candidate_axis": value.get("candidate_axis"),
            "native_fresh_T": value.get("post_boundary_native_T"),
            "child_fresh_T": value.get("post_boundary_long_child_T"),
            "target_T": value.get("target_fresh_closed_T"),
            "next": value.get("next"),
            "reused_authoritative_receipt": True,
        }
    out = out_dir / "01_trendma_macd_rescue.json"
    _run("z_trendma_macd_rescue_one_axis_v1.py", ["--candidate", str(source), "--out", str(out)])
    result = _read_json(out)
    return {"state": result.get("state", "UNKNOWN"), "artifact": str(out), "reused_authoritative_receipt": False}


def _nursery_stage(bindings: dict[str, dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    roles = ["nursery_parent_a", "nursery_parent_b", "nursery_child"]
    if _all_auto(bindings, roles):
        source = Path(bindings["nursery_parent_a"]["path"])
        if not source.is_file():
            return {"state": "HOLD_NURSERY_BINDING", "reason": "authoritative nursery receipt missing"}
        value = _read_json(source)
        return {
            "state": value.get("state", "HOLD_NURSERY_RECEIPT_UNKNOWN"),
            "source": str(source),
            "source_schema": value.get("schema_version"),
            "eligible_c_material_count": value.get("eligible_c_material_count"),
            "pair_count_this_run": value.get("pair_count_this_run"),
            "c_to_b_upgrade_count": value.get("c_to_b_upgrade_count"),
            "provider": value.get("provider"),
            "next": value.get("next"),
            "reused_authoritative_receipt": True,
        }
    if not _all_explicit(bindings, roles):
        return {"state": "HOLD_NURSERY_MIXED_BINDING_MODE", "reason": "partial explicit override cannot be mixed with composite auto receipt"}
    if not all(_is_ready(bindings[r]) and bindings[r]["status"] == "READY_RAW" for r in roles):
        return {
            "state": "HOLD_NURSERY_BINDING",
            "bindings": {r: bindings[r]["status"] for r in roles},
            "reason": "all three explicit nursery roles must satisfy raw metric contracts",
        }
    out = out_dir / "02_material_nursery_cxc_to_b.json"
    _run(
        "z_material_nursery_cxc_to_b_v1.py",
        [
            "--parent-a", bindings["nursery_parent_a"]["path"],
            "--parent-b", bindings["nursery_parent_b"]["path"],
            "--child", bindings["nursery_child"]["path"],
            "--out", str(out),
        ],
    )
    result = _read_json(out)
    return {"state": result.get("state", "UNKNOWN"), "artifact": str(out), "reused_authoritative_receipt": False}


def _rr_stage(bindings: dict[str, dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    roles = ["rr_parent", "rr_child"]
    if _all_auto(bindings, roles):
        source = Path(bindings["rr_parent"]["path"])
        if not source.is_file():
            return {"state": "HOLD_RR_BINDING", "reason": "authoritative RR receipt missing"}
        value = _read_json(source)
        lanes = value.get("lanes") if isinstance(value.get("lanes"), list) else []
        pass_count = sum(int(x.get("pass_count") or 0) for x in lanes if isinstance(x, dict))
        return {
            "state": value.get("state", "HOLD_RR_RECEIPT_UNKNOWN"),
            "source": str(source),
            "source_schema": value.get("schema_version"),
            "cells": value.get("cells"),
            "lane_count": len(lanes),
            "strict_pass_count": pass_count,
            "strict_upgrade_present": pass_count > 0,
            "reused_authoritative_receipt": True,
        }
    if not _all_explicit(bindings, roles):
        return {"state": "HOLD_RR_MIXED_BINDING_MODE", "reason": "partial explicit override cannot be mixed with composite auto receipt"}
    if not all(_is_ready(bindings[r]) and bindings[r]["status"] == "READY_RAW" for r in roles):
        return {
            "state": "HOLD_RR_BINDING",
            "bindings": {r: bindings[r]["status"] for r in roles},
            "reason": "both explicit RR roles must satisfy raw metric contracts",
        }
    out = out_dir / "03_top5_rr_shadow.json"
    _run(
        "z_top5_rr_grid_shadow_gate_v1.py",
        ["--parent", bindings["rr_parent"]["path"], "--child", bindings["rr_child"]["path"], "--out", str(out)],
    )
    result = _read_json(out)
    return {"state": result.get("state", "UNKNOWN"), "artifact": str(out), "reused_authoritative_receipt": False}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roadmap", default=str(DEFAULT_ROADMAP))
    ap.add_argument("--trendma-candidate")
    ap.add_argument("--nursery-parent-a")
    ap.add_argument("--nursery-parent-b")
    ap.add_argument("--nursery-child")
    ap.add_argument("--rr-parent")
    ap.add_argument("--rr-child")
    ap.add_argument("--out-dir", default=os.environ.get("Z_OUT_DIR", "artifacts/z_next_roadmap_auto"))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    summary_path = out_dir / "summary.json"
    binding_path = out_dir / "binding_report.json"
    summary: dict[str, Any] = {
        "schema_version": "zel.next_roadmap.auto.v2",
        "state": "STARTED",
        "roadmap": str(args.roadmap),
        "latest_only_ssot_required": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "stages": {},
    }

    try:
        summary["roadmap_checks"] = _validate_roadmap(Path(args.roadmap))
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        summary["state"] = "FAIL_ROADMAP_INTEGRITY"
        summary["error"] = str(exc)
        _write(summary_path, summary)
        print(json.dumps({"state": summary["state"], "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2

    bindings = {
        role: _resolve_binding(role, getattr(args, role))
        for role in BINDINGS
    }
    report = {
        "schema_version": "zel.next_roadmap.binding_report.v2",
        "binding_count": len(bindings),
        "ready_count": sum(_is_ready(x) for x in bindings.values()),
        "hold_count": sum(not _is_ready(x) for x in bindings.values()),
        "explicit_fallback_forbidden": True,
        "bindings": bindings,
    }
    _write(binding_path, report)
    summary["bindings"] = bindings
    summary["binding_report"] = str(binding_path)

    stage_errors: dict[str, str] = {}
    for name, runner in (
        ("trendma_rescue", _trendma_stage),
        ("cxc_nursery", _nursery_stage),
        ("top5_rr_shadow", _rr_stage),
    ):
        try:
            summary["stages"][name] = runner(bindings, out_dir)
        except (ValueError, json.JSONDecodeError, OSError, RuntimeError, KeyError, TypeError) as exc:
            stage_errors[name] = str(exc)
            summary["stages"][name] = {"state": "HOLD_STAGE_ERROR", "error": str(exc)}

    trend_state = str(summary["stages"]["trendma_rescue"].get("state") or "")
    summary["stages"]["donor_demotion"] = {
        "state": "DONOR_ONLY_REQUIRED" if trend_state in {"FAIL_DEMOTE_TO_DONOR_ONLY", "FAIL_TOP6_FRESH_OOS"} else "NOT_REQUIRED_OR_PENDING",
        "mutation_performed": False,
        "reason": "read-only runner never mutates donor registry",
    }

    nursery = summary["stages"]["cxc_nursery"]
    rr = summary["stages"]["top5_rr_shadow"]
    summary["promotion_candidate_present"] = bool(
        trend_state in {"PASS_TOP6_RESCUE", "PASS_TOP6_FRESH_OOS"}
        or int(nursery.get("c_to_b_upgrade_count") or 0) > 0
        or rr.get("strict_upgrade_present") is True
        or nursery.get("state") == "PASS_GRADE_B_MATERIAL"
        or rr.get("state") == "PASS_RR_SHADOW_CHILD"
    )
    summary["stage_error_count"] = len(stage_errors)
    summary["stage_errors"] = stage_errors
    summary["state"] = "COMPLETE_PASS_OR_HOLD"
    _write(summary_path, summary)
    print(json.dumps({
        "state": summary["state"],
        "ready_bindings": report["ready_count"],
        "hold_bindings": report["hold_count"],
        "stage_errors": len(stage_errors),
        "summary": str(summary_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
