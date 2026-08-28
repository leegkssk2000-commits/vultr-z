#!/usr/bin/env python3
"""Fail-fast orchestrator for the approved 2026-08-28 research roadmap.

This runner wires existing read-only evaluators together. It never mutates a
strategy, selection registry, promotion registry, order authority, or live state.
No-promotion/HOLD is a valid research result and exits zero. Missing/invalid
bindings or stage execution errors exit non-zero.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_ROADMAP = ROOT / "z_next_roadmap_20260828_v1.json"

BINDINGS = {
    "trendma_candidate": "Z_TRENDMA_CANDIDATE",
    "nursery_parent_a": "Z_NURSERY_PARENT_A",
    "nursery_parent_b": "Z_NURSERY_PARENT_B",
    "nursery_child": "Z_NURSERY_CHILD",
    "rr_parent": "Z_RR_PARENT",
    "rr_child": "Z_RR_CHILD",
}


def _resolve(cli_value: str | None, env_name: str) -> Path:
    raw = cli_value or os.environ.get(env_name, "")
    if not raw.strip():
        raise ValueError(f"missing binding: {env_name}")
    path = Path(raw).expanduser()
    if not path.is_file():
        raise ValueError(f"binding does not exist or is not a file: {env_name}={path}")
    return path


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _validate_roadmap(path: Path) -> dict:
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


def _write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


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
    summary = {
        "schema_version": "zel.next_roadmap.auto.v1",
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
        resolved = {
            key: _resolve(getattr(args, key), env_name)
            for key, env_name in BINDINGS.items()
        }
        summary["bindings"] = {key: str(path) for key, path in resolved.items()}

        trend_out = out_dir / "01_trendma_macd_rescue.json"
        _run(
            "z_trendma_macd_rescue_one_axis_v1.py",
            ["--candidate", str(resolved["trendma_candidate"]), "--out", str(trend_out)],
        )
        trend = _read_json(trend_out)
        trend_state = trend.get("state", "UNKNOWN")
        summary["stages"]["trendma_rescue"] = {"state": trend_state, "artifact": str(trend_out)}
        summary["stages"]["donor_demotion"] = {
            "state": "DONOR_ONLY_REQUIRED" if trend_state == "FAIL_DEMOTE_TO_DONOR_ONLY" else "NOT_REQUIRED",
            "mutation_performed": False,
            "reason": "No donor-registry mutation authority is bound to this read-only runner.",
        }

        nursery_out = out_dir / "02_material_nursery_cxc_to_b.json"
        _run(
            "z_material_nursery_cxc_to_b_v1.py",
            [
                "--parent-a", str(resolved["nursery_parent_a"]),
                "--parent-b", str(resolved["nursery_parent_b"]),
                "--child", str(resolved["nursery_child"]),
                "--out", str(nursery_out),
            ],
        )
        nursery = _read_json(nursery_out)
        summary["stages"]["cxc_nursery"] = {
            "state": nursery.get("state", "UNKNOWN"),
            "artifact": str(nursery_out),
        }

        rr_out = out_dir / "03_top5_rr_shadow.json"
        _run(
            "z_top5_rr_grid_shadow_gate_v1.py",
            ["--parent", str(resolved["rr_parent"]), "--child", str(resolved["rr_child"]), "--out", str(rr_out)],
        )
        rr = _read_json(rr_out)
        summary["stages"]["top5_rr_shadow"] = {
            "state": rr.get("state", "UNKNOWN"),
            "artifact": str(rr_out),
        }

        states = [v.get("state") for v in summary["stages"].values()]
        summary["state"] = "COMPLETE_PASS_OR_HOLD"
        summary["promotion_candidate_present"] = any(
            state in {"PASS_TOP6_RESCUE", "PASS_GRADE_B_MATERIAL", "PASS_RR_SHADOW_CHILD"}
            for state in states
        )
        _write_summary(summary_path, summary)
        print(json.dumps({"state": summary["state"], "summary": str(summary_path)}, sort_keys=True))
        return 0
    except (ValueError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        summary["state"] = "FAIL_FAST"
        summary["error"] = str(exc)
        _write_summary(summary_path, summary)
        print(json.dumps({"state": "FAIL_FAST", "error": str(exc), "summary": str(summary_path)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
