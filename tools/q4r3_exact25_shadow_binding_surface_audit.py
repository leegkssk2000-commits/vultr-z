from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

EXPECTED_25: Tuple[str, ...] = (
    "alpha_combo", "anchor_vwap_trend", "bb_revert", "break_and_continue",
    "ema_ribbon_scalp", "fvg_revert", "grid_rebalance", "keltner_trend",
    "liquidity_sweep", "mfi_rsi_div", "obv_trend", "pivot_reversal",
    "range_fade", "rbreaker_like", "rsi_swing_fail", "scalp_snap",
    "session_bias", "squeeze_break", "sr_levels", "supertrend_pullback",
    "trend_ma_macd", "trend_rider", "turtle_trend", "vol_spike_fade",
    "vwap_revert",
)

SCAN_ROOTS = ("backend", "tools", "scripts", "services", "systemd", "config", "configs", "data")
EXCLUDED_PARTS = {
    ".git", ".venv", "venv", "env", "node_modules", "site-packages",
    "dist-packages", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "build", "dist", "runtime_results",
}
TEXT_SUFFIXES = {".py", ".sh", ".service", ".timer", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt"}
MAX_FILE_BYTES = 2 * 1024 * 1024

CATEGORY_TOKENS: Mapping[str, Mapping[str, int]] = {
    "market_data": {
        "ohlcv": 3, "candles": 2, "fetch_ohlcv": 5, "market_snapshot": 3,
        "websocket": 2, "bingx": 1, "dataframe": 1, "close": 1,
    },
    "strategy_runner": {
        "strategy_id": 1, "owner_module": 3, "importlib": 2, "strategy(": 3,
        "risk_action": 2, "shadow": 2, "manifest": 2, "candidate": 1,
    },
    "open_writer": {
        "entry_ts": 3, "entry_price": 2, "stop_price": 3, "initial_risk_usdt": 6,
        "owner_sha256": 3, "position_id": 2, "append": 1, "jsonl": 2,
    },
    "close_r_writer": {
        "exit_ts": 3, "close_ts": 3, "realized_pnl_usdt": 5, "realized_r": 7,
        "initial_risk_usdt": 5, "fee": 1, "slippage": 1, "append": 1, "jsonl": 2,
    },
    "epoch_or_ledger": {
        "epoch_id": 4, "ledger": 3, "pre_exact25": 3, "exact25_edge_v1": 5,
        "mfe_r": 3, "mae_r": 3, "time_exposure": 2, "regime": 1,
    },
}

REQUIRED_EDGE_FIELDS = (
    "strategy_id", "owner_sha256", "symbol", "side", "regime",
    "entry_ts", "exit_ts", "entry_price", "stop_price",
    "initial_risk_usdt", "realized_pnl_usdt", "realized_R",
    "fee", "slippage", "latency_ms", "MFE_R", "MAE_R",
    "time_exposure_min", "epoch_id",
)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_text(text: str) -> str:
    return text.lower().replace("-", "_")


def score_categories(text: str) -> Dict[str, Dict[str, Any]]:
    normalized = normalize_text(text)
    result: Dict[str, Dict[str, Any]] = {}
    for category, weighted_tokens in CATEGORY_TOKENS.items():
        hits = sorted(token for token in weighted_tokens if token in normalized)
        score = sum(weighted_tokens[token] for token in hits)
        result[category] = {"score": score, "hits": hits}
    return result


def is_strong(category: str, score: int) -> bool:
    thresholds = {
        "market_data": 6,
        "strategy_runner": 7,
        "open_writer": 9,
        "close_r_writer": 12,
        "epoch_or_ledger": 7,
    }
    return score >= thresholds[category]


def iter_scan_files(root: Path) -> Iterable[Path]:
    for root_name in SCAN_ROOTS:
        start = root / root_name
        if not start.exists():
            continue
        for current, dirs, files in os.walk(start):
            dirs[:] = [name for name in dirs if name not in EXCLUDED_PARTS]
            current_path = Path(current)
            for name in files:
                path = current_path / name
                if path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if 0 < size <= MAX_FILE_BYTES:
                    yield path


def token_line_numbers(text: str, tokens: Sequence[str], limit_per_token: int = 5) -> Dict[str, List[int]]:
    result: Dict[str, List[int]] = defaultdict(list)
    normalized_lines = [normalize_text(line) for line in text.splitlines()]
    for line_no, line in enumerate(normalized_lines, 1):
        for token in tokens:
            if token in line and len(result[token]) < limit_per_token:
                result[token].append(line_no)
    return dict(result)


def scan_source_surfaces(root: Path) -> Dict[str, List[Dict[str, Any]]]:
    surfaces: Dict[str, List[Dict[str, Any]]] = {category: [] for category in CATEGORY_TOKENS}
    for path in iter_scan_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        relative = str(path.relative_to(root)).replace("\\", "/")
        category_scores = score_categories(text)
        for category, details in category_scores.items():
            score = int(details["score"])
            if score <= 0:
                continue
            hits = list(details["hits"])
            surfaces[category].append({
                "path": relative,
                "score": score,
                "strong": is_strong(category, score),
                "hits": hits,
                "lines": token_line_numbers(text, hits),
                "sha256": sha256_file(path),
            })
    for category in surfaces:
        surfaces[category].sort(key=lambda item: (item["strong"], item["score"], item["path"]), reverse=True)
        surfaces[category] = surfaces[category][:50]
    return surfaces


def run_command(args: Sequence[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, check=False,
    )


def systemd_inventory() -> List[Dict[str, Any]]:
    result = run_command(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager"], timeout=30)
    if result.returncode != 0:
        return []
    interesting = re.compile(r"(?i)(q4r3|shadow|strategy|worker|orchestrat|watch|ledger|journal|zel|lbot)")
    units: List[Dict[str, Any]] = []
    for raw in result.stdout.splitlines():
        parts = raw.split()
        if not parts:
            continue
        unit = parts[0]
        if not interesting.search(unit):
            continue
        show = run_command([
            "systemctl", "show", unit, "--no-pager",
            "-p", "ActiveState", "-p", "SubState", "-p", "MainPID", "-p", "FragmentPath",
        ])
        props: Dict[str, str] = {}
        for line in show.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                props[key] = value
        fragment = props.get("FragmentPath", "")
        units.append({
            "unit": unit,
            "active_state": props.get("ActiveState"),
            "sub_state": props.get("SubState"),
            "main_pid": int(props.get("MainPID") or 0),
            "fragment_path": fragment,
            "is_forward_r_watcher": bool(re.search(r"(?i)(forward.*r|persistent.*write.*watch)", unit + " " + fragment)),
        })
    units.sort(key=lambda item: (item["is_forward_r_watcher"], item["active_state"] == "active", item["unit"]), reverse=True)
    return units


def process_inventory(root: Path) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    proc = Path("/proc")
    if not proc.exists():
        return found
    root_resolved = root.resolve()
    for child in proc.iterdir():
        if not child.name.isdigit():
            continue
        try:
            raw = (child / "cmdline").read_bytes()
        except OSError:
            continue
        repo_paths: List[str] = []
        for piece in (part.decode("utf-8", errors="ignore") for part in raw.split(b"\0") if part):
            if not piece.startswith(str(root)):
                continue
            try:
                relative = str(Path(piece).resolve().relative_to(root_resolved)).replace("\\", "/")
            except Exception:
                continue
            repo_paths.append(relative)
        if repo_paths:
            found.append({"pid": int(child.name), "repo_paths": sorted(set(repo_paths))})
    found.sort(key=lambda item: item["pid"])
    return found


def validate_manifest(root: Path, manifest_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "path": str(manifest_path),
        "exists": manifest_path.is_file(),
        "valid_json": False,
        "exact_25": False,
        "unique_25": False,
        "all_hashes_match": False,
        "all_contract_pass": False,
        "all_shadow_flags_false": False,
        "all_paper_flags_false": False,
        "all_live_flags_false": False,
        "runtime_binding_status": None,
        "errors": [],
    }
    if not manifest_path.is_file():
        result["errors"].append("manifest_missing")
        return result
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["errors"].append(f"manifest_json_error:{type(exc).__name__}")
        return result
    result["valid_json"] = True
    entries = payload.get("strategies") if isinstance(payload, Mapping) else None
    if not isinstance(entries, list):
        result["errors"].append("strategies_not_list")
        return result
    ids = [str(entry.get("strategy_id") or "") for entry in entries if isinstance(entry, Mapping)]
    result["exact_25"] = len(entries) == 25 and set(ids) == set(EXPECTED_25)
    result["unique_25"] = len(ids) == len(set(ids)) == 25
    hashes_ok = True
    for entry in entries:
        if not isinstance(entry, Mapping):
            hashes_ok = False
            continue
        owner_path = root / str(entry.get("owner_path") or "")
        expected_hash = str(entry.get("owner_sha256") or "")
        if not owner_path.is_file() or not expected_hash or sha256_file(owner_path) != expected_hash:
            hashes_ok = False
    result["all_hashes_match"] = hashes_ok
    result["all_contract_pass"] = all(bool(entry.get("contract_pass")) for entry in entries if isinstance(entry, Mapping))
    result["all_shadow_flags_false"] = all(not bool(entry.get("enabled_for_shadow")) for entry in entries if isinstance(entry, Mapping))
    result["all_paper_flags_false"] = all(not bool(entry.get("enabled_for_paper")) for entry in entries if isinstance(entry, Mapping))
    result["all_live_flags_false"] = all(not bool(entry.get("enabled_for_live")) for entry in entries if isinstance(entry, Mapping))
    result["runtime_binding_status"] = payload.get("runtime_binding_status")
    result["manifest_sha256"] = sha256_file(manifest_path)
    return result


def strong_count(surfaces: Mapping[str, Sequence[Mapping[str, Any]]], category: str) -> int:
    return sum(bool(item.get("strong")) for item in surfaces.get(category, []))


def decide(manifest: Mapping[str, Any], surfaces: Mapping[str, Sequence[Mapping[str, Any]]], units: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    manifest_gate = all(bool(manifest.get(key)) for key in (
        "valid_json", "exact_25", "unique_25", "all_hashes_match", "all_contract_pass",
        "all_shadow_flags_false", "all_paper_flags_false", "all_live_flags_false",
    ))
    counts = {category: strong_count(surfaces, category) for category in CATEGORY_TOKENS}
    active_watchers = [unit for unit in units if unit.get("is_forward_r_watcher") and unit.get("active_state") == "active"]
    gaps: List[str] = []
    if not manifest_gate:
        gaps.append("manifest_gate_failed")
    if counts["market_data"] == 0:
        gaps.append("authoritative_market_data_surface_unresolved")
    if counts["strategy_runner"] == 0:
        gaps.append("shadow_strategy_runner_surface_unresolved")
    if counts["open_writer"] == 0:
        gaps.append("initial_risk_open_writer_unresolved")
    if counts["close_r_writer"] == 0:
        gaps.append("realized_r_close_writer_unresolved")
    if not active_watchers:
        gaps.append("active_forward_r_watcher_not_confirmed")

    if not gaps:
        verdict = "EXACT25_SHADOW_BINDING_SURFACE_READY"
        next_action = "BUILD_ROLLBACK_GUARDED_SHADOW_ONLY_SIDECAR_AND_EXACT25_EDGE_V1_EPOCH"
    elif manifest_gate and counts["strategy_runner"] > 0 and (counts["open_writer"] == 0 or counts["close_r_writer"] == 0):
        verdict = "EXACT25_READY_WRITER_LINEAGE_GAPS_REMAIN"
        next_action = "TRACE_ONLY_TOP_RUNTIME_WRITERS_BEFORE_SHADOW_BIND"
    else:
        verdict = "EXACT25_SHADOW_BINDING_SURFACE_GAPS_REMAIN"
        next_action = "RESOLVE_REPORTED_BINDING_GAPS_WITHOUT_RUNTIME_MUTATION"
    return {
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "manifest_gate": manifest_gate,
        "strong_candidate_counts": counts,
        "active_forward_r_watcher_count": len(active_watchers),
        "active_forward_r_watchers": active_watchers,
        "gaps": gaps,
    }


def run(root: Path, manifest_path: Path, output_dir: Path) -> Dict[str, Any]:
    manifest = validate_manifest(root, manifest_path)
    surfaces = scan_source_surfaces(root)
    units = systemd_inventory()
    processes = process_inventory(root)
    decision = decide(manifest, surfaces, units)
    result = {
        "schema": "q4r3_exact25_shadow_binding_surface_audit_v1",
        "status": "PASS_Q4R3_EXACT25_SHADOW_BINDING_SURFACE_AUDIT",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **decision,
        "manifest": manifest,
        "source_surfaces": surfaces,
        "systemd_units": units,
        "runtime_processes": processes,
        "measurement_epoch_design": {
            "preexisting_data_label": "PRE_EXACT25",
            "new_epoch_id": "EXACT25_EDGE_V1",
            "historical_r_backfill_allowed": False,
            "forward_rows_only": True,
            "required_fields": list(REQUIRED_EDGE_FIELDS),
            "comparison_metrics": [
                "expectancy_R", "profit_factor", "max_drawdown_R", "MFE_R", "MAE_R",
                "net_R_after_fee_slippage", "regime_stability", "confidence_interval",
            ],
        },
        "proposed_binding_sequence": [
            "freeze PRE_EXACT25 ledger namespace",
            "create read-only exact25 manifest loader",
            "enable shadow flag only; keep paper/live/order false",
            "emit owner_sha256 and epoch_id on every signal/open/close event",
            "bind authoritative initial-risk open writer",
            "bind authoritative realized-R close writer",
            "run one-cycle dry-run without writes",
            "run short shadow canary with duplicate and lineage guards",
            "expand to exact-25 forward measurement only after canary pass",
        ],
        "safety": {
            "read_only": True,
            "production_files_modified": False,
            "manifest_modified": False,
            "runtime_registry_bound": False,
            "paper_live_order_modified": False,
            "persistent_forward_r_watcher_modified": False,
            "raw_trade_rows_published": False,
            "credentials_published": False,
        },
    }
    atomic_json(output_dir / "q4r3_exact25_shadow_binding_surface_audit_latest.json", result)
    atomic_json(output_dir / "q4r3_exact25_shadow_binding_plan_latest.json", {
        "verdict": decision["verdict"],
        "action": "HOLD",
        "next_action": decision["next_action"],
        "gaps": decision["gaps"],
        "measurement_epoch_design": result["measurement_epoch_design"],
        "proposed_binding_sequence": result["proposed_binding_sequence"],
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/z/z"))
    parser.add_argument("--manifest", type=Path, default=Path("/home/z/z/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root.resolve(), args.manifest.resolve(), args.output_dir.resolve())
    print(json.dumps({
        "status": result["status"],
        "verdict": result["verdict"],
        "gaps": result["gaps"],
        "strong_candidate_counts": result["strong_candidate_counts"],
        "active_forward_r_watcher_count": result["active_forward_r_watcher_count"],
        "next_action": result["next_action"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
