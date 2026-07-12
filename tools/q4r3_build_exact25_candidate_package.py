from __future__ import annotations

import argparse
import ast
import hashlib
import html
import importlib
import inspect
import json
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import pandas as pd

EXPECTED_25: Tuple[str, ...] = (
    "alpha_combo",
    "anchor_vwap_trend",
    "bb_revert",
    "break_and_continue",
    "ema_ribbon_scalp",
    "fvg_revert",
    "grid_rebalance",
    "keltner_trend",
    "liquidity_sweep",
    "mfi_rsi_div",
    "obv_trend",
    "pivot_reversal",
    "range_fade",
    "rbreaker_like",
    "rsi_swing_fail",
    "scalp_snap",
    "session_bias",
    "squeeze_break",
    "sr_levels",
    "supertrend_pullback",
    "trend_ma_macd",
    "trend_rider",
    "turtle_trend",
    "vol_spike_fade",
    "vwap_revert",
)

RECOVERED_SOURCES = {
    "ema_ribbon_scalp": "runtime_results/q4r3/strategy_history_recovery_registry_authority/candidate_sources/ema_ribbon_scalp/01_other_working_path_fbc7ca7d54cd.py",
    "vol_spike_fade": "runtime_results/q4r3/strategy_history_recovery_registry_authority/candidate_sources/vol_spike_fade/01_other_working_path_e6f7842731aa.py",
}

SNAPSHOT_SOURCE_ROOT = Path("runtime_results/q4r3/strategy_source_snapshot/source")
OUTPUT_ROOT = Path("runtime_results/q4r3/exact25_candidate_package")
REQUIRED_OUTPUT_KEYS = {
    "side",
    "action",
    "size",
    "entry",
    "sl",
    "tp",
    "pyramiding",
    "why",
    "skill",
    "confidence",
    "tags",
    "indicators",
}
DANGEROUS_CALL_SUFFIXES = {
    "create_order",
    "cancel_order",
    "send_order",
    "place_order",
    "submit_order",
    "write_text",
    "write_bytes",
    "json.dump",
    "requests.post",
    "requests.put",
    "requests.delete",
}


@dataclass
class StrategyCheck:
    strategy_id: str
    source_path: str
    owner_module: str
    owner_sha256: str
    ast_ok: bool
    import_ok: bool
    strategy_callable: bool
    signature_ok: bool
    invalid_input_contract_ok: bool
    hard_risk_gate_contract_ok: bool
    lbot_adapter_found: bool
    short_core_guard_found: bool
    dangerous_call_hits: List[str]
    issues: List[str]

    @property
    def pass_contract(self) -> bool:
        return not self.issues

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "source_path": self.source_path,
            "owner_module": self.owner_module,
            "owner_sha256": self.owner_sha256,
            "ast_ok": self.ast_ok,
            "import_ok": self.import_ok,
            "strategy_callable": self.strategy_callable,
            "signature_ok": self.signature_ok,
            "invalid_input_contract_ok": self.invalid_input_contract_ok,
            "hard_risk_gate_contract_ok": self.hard_risk_gate_contract_ok,
            "lbot_adapter_found": self.lbot_adapter_found,
            "short_core_guard_found": self.short_core_guard_found,
            "dangerous_call_hits": self.dangerous_call_hits,
            "issues": self.issues,
            "pass_contract": self.pass_contract,
        }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def ensure_package(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    init = path / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")


def patch_ema_ribbon_scalp(text: str) -> Tuple[str, List[str]]:
    old = '''    if in_long and can_add_more:\n        long_add = pullback_long_add and long_reclaim and not failed_long\n        long_reduce = failed_long\n\n    if in_short and can_add_more:\n        short_add = pullback_short_add and short_reclaim and not failed_short\n        short_reduce = failed_short\n'''
    new = '''    if in_long:\n        long_reduce = failed_long\n        if can_add_more:\n            long_add = pullback_long_add and long_reclaim and not failed_long\n\n    if in_short:\n        short_reduce = failed_short\n        if can_add_more:\n            short_add = pullback_short_add and short_reclaim and not failed_short\n'''
    if old not in text:
        raise RuntimeError("EMA_REDUCE_GUARD_PATCH_ANCHOR_MISSING")
    patched = text.replace(old, new, 1)
    return patched, ["reduce_remains_available_after_max_add_count"]


def patch_vol_spike_fade(text: str) -> Tuple[str, List[str]]:
    config_anchor = "    max_pyramiding: int = 2\n\n    water_add_extension_atr: float = 1.80\n"
    config_replacement = "    max_pyramiding: int = 2\n    enable_water_add: bool = False\n\n    water_add_extension_atr: float = 1.80\n"
    if config_anchor not in text:
        raise RuntimeError("VOL_WATER_ADD_CONFIG_PATCH_ANCHOR_MISSING")
    patched = text.replace(config_anchor, config_replacement, 1)

    long_anchor = "        long_water_add = long_fade_setup and body_atr >= cfg.water_add_extension_atr\n"
    short_anchor = "        short_water_add = short_fade_setup and body_atr >= cfg.water_add_extension_atr\n"
    if long_anchor not in patched or short_anchor not in patched:
        raise RuntimeError("VOL_WATER_ADD_GATE_PATCH_ANCHOR_MISSING")
    patched = patched.replace(
        long_anchor,
        "        long_water_add = cfg.enable_water_add and long_fade_setup and body_atr >= cfg.water_add_extension_atr\n",
        1,
    )
    patched = patched.replace(
        short_anchor,
        "        short_water_add = cfg.enable_water_add and short_fade_setup and body_atr >= cfg.water_add_extension_atr\n",
        1,
    )
    return patched, ["water_add_default_disabled_until_high_risk_route_promotion"]


def copy_snapshot_package(repo_root: Path, package_root: Path) -> None:
    snapshot_root = repo_root / SNAPSHOT_SOURCE_ROOT
    for relative in (Path("backend/strategies"), Path("backend/engine")):
        source = snapshot_root / relative
        destination = package_root / relative
        if not source.is_dir():
            raise RuntimeError(f"SNAPSHOT_SOURCE_DIRECTORY_MISSING:{source}")
        shutil.copytree(source, destination, dirs_exist_ok=True)

    ensure_package(package_root / "backend")
    ensure_package(package_root / "backend/strategies")
    ensure_package(package_root / "backend/engine")


def install_recovered_sources(repo_root: Path, package_root: Path) -> Dict[str, Any]:
    decisions: Dict[str, Any] = {}
    for strategy_id, relative_source in RECOVERED_SOURCES.items():
        source = repo_root / relative_source
        if not source.is_file():
            raise RuntimeError(f"RECOVERY_SOURCE_MISSING:{source}")
        original = source.read_text(encoding="utf-8")
        original_sha = hashlib.sha256(original.encode("utf-8")).hexdigest()
        if strategy_id == "ema_ribbon_scalp":
            patched, patches = patch_ema_ribbon_scalp(original)
        elif strategy_id == "vol_spike_fade":
            patched, patches = patch_vol_spike_fade(original)
        else:
            raise RuntimeError(f"UNSUPPORTED_RECOVERY_TARGET:{strategy_id}")
        destination = package_root / "backend" / "strategies" / f"{strategy_id}.py"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(patched, encoding="utf-8")
        decisions[strategy_id] = {
            "source": relative_source,
            "source_sha256": original_sha,
            "candidate_path": str(destination.relative_to(repo_root)).replace("\\", "/"),
            "candidate_sha256": sha256_file(destination),
            "patches": patches,
        }
    return decisions


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def dangerous_calls(tree: ast.AST) -> List[str]:
    hits: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_name(node.func)
        if name in DANGEROUS_CALL_SUFFIXES or any(name.endswith(f".{suffix}") for suffix in DANGEROUS_CALL_SUFFIXES):
            hits.append(name)
        if name == "open" and len(node.args) >= 2:
            mode = node.args[1]
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(flag in mode.value for flag in ("w", "a", "+", "x")):
                hits.append(f"open:{mode.value}")
    return sorted(set(hits))


@contextmanager
def isolated_candidate_import(package_root: Path) -> Iterator[None]:
    original_path = list(sys.path)
    removed = {name: module for name, module in list(sys.modules.items()) if name == "backend" or name.startswith("backend.")}
    for name in removed:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(package_root))
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == "backend" or name.startswith("backend."):
                sys.modules.pop(name, None)
        sys.modules.update(removed)
        sys.path[:] = original_path


def verify_strategy(package_root: Path, strategy_id: str) -> StrategyCheck:
    path = package_root / "backend" / "strategies" / f"{strategy_id}.py"
    issues: List[str] = []
    ast_ok = False
    import_ok = False
    strategy_callable = False
    signature_ok = False
    invalid_input_contract_ok = False
    hard_risk_gate_contract_ok = False
    lbot_adapter_found = False
    short_core_guard_found = False
    danger: List[str] = []

    if not path.is_file():
        return StrategyCheck(
            strategy_id=strategy_id,
            source_path=str(path),
            owner_module=f"backend.strategies.{strategy_id}",
            owner_sha256="",
            ast_ok=False,
            import_ok=False,
            strategy_callable=False,
            signature_ok=False,
            invalid_input_contract_ok=False,
            hard_risk_gate_contract_ok=False,
            lbot_adapter_found=False,
            short_core_guard_found=False,
            dangerous_call_hits=[],
            issues=["source_missing"],
        )

    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
        ast_ok = True
        danger = dangerous_calls(tree)
    except SyntaxError as exc:
        issues.append(f"ast_error:{exc.lineno}:{exc.msg}")
        tree = ast.Module(body=[], type_ignores=[])

    if danger:
        issues.append("direct_side_effect_calls")

    lbot_adapter_found = any(
        isinstance(node, ast.ClassDef)
        and any(isinstance(base, (ast.Name, ast.Attribute)) and dotted_name(base).endswith("LBotStrategyBase") for base in node.bases)
        for node in ast.walk(tree)
    )
    if not lbot_adapter_found:
        issues.append("lbot_adapter_missing")

    short_core_guard_found = "short_signal_generated_but_core_is_long_only" in text or "side == \"short\"" not in text
    if not short_core_guard_found:
        issues.append("short_core_guard_missing")

    module = None
    try:
        with isolated_candidate_import(package_root):
            module = importlib.import_module(f"backend.strategies.{strategy_id}")
            import_ok = True
            strategy_fn = getattr(module, "strategy", None)
            strategy_callable = callable(strategy_fn)
            if not strategy_callable:
                issues.append("strategy_callable_missing")
            else:
                signature = inspect.signature(strategy_fn)
                names = set(signature.parameters)
                signature_ok = {"df", "state", "risk_action"}.issubset(names)
                if not signature_ok:
                    issues.append("strategy_signature_incomplete")
                try:
                    invalid = strategy_fn(pd.DataFrame(), state=None, risk_action="hold")
                    invalid_input_contract_ok = (
                        isinstance(invalid, Mapping)
                        and REQUIRED_OUTPUT_KEYS.issubset(set(invalid))
                        and str(invalid.get("action")) == "hold"
                        and float(invalid.get("size") or 0.0) == 0.0
                    )
                except Exception as exc:
                    invalid_input_contract_ok = False
                    issues.append(f"invalid_input_exception:{type(exc).__name__}")
                if not invalid_input_contract_ok and not any(item.startswith("invalid_input_exception") for item in issues):
                    issues.append("invalid_input_contract_failed")

                try:
                    blocked = strategy_fn(pd.DataFrame(), state=None, risk_action="block")
                    hard_risk_gate_contract_ok = (
                        isinstance(blocked, Mapping)
                        and str(blocked.get("action")) == "hold"
                        and float(blocked.get("size") or 0.0) == 0.0
                    )
                except Exception as exc:
                    hard_risk_gate_contract_ok = False
                    issues.append(f"risk_gate_exception:{type(exc).__name__}")
                if not hard_risk_gate_contract_ok and not any(item.startswith("risk_gate_exception") for item in issues):
                    issues.append("hard_risk_gate_contract_failed")
    except Exception as exc:
        issues.append(f"import_error:{type(exc).__name__}:{str(exc)[:120]}")

    return StrategyCheck(
        strategy_id=strategy_id,
        source_path=str(path.relative_to(package_root.parent.parent.parent)).replace("\\", "/"),
        owner_module=f"backend.strategies.{strategy_id}",
        owner_sha256=sha256_file(path),
        ast_ok=ast_ok,
        import_ok=import_ok,
        strategy_callable=strategy_callable,
        signature_ok=signature_ok,
        invalid_input_contract_ok=invalid_input_contract_ok,
        hard_risk_gate_contract_ok=hard_risk_gate_contract_ok,
        lbot_adapter_found=lbot_adapter_found,
        short_core_guard_found=short_core_guard_found,
        dangerous_call_hits=danger,
        issues=issues,
    )


def build_manifest(checks: Sequence[StrategyCheck], recovery: Mapping[str, Any]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    for check in sorted(checks, key=lambda item: item.strategy_id):
        restored = check.strategy_id in recovery
        entries.append(
            {
                "strategy_id": check.strategy_id,
                "owner_module": check.owner_module,
                "owner_path": f"backend/strategies/{check.strategy_id}.py",
                "candidate_source_path": check.source_path,
                "owner_sha256": check.owner_sha256,
                "owner_kind": "canonical_recovered_reviewed" if restored else "canonical_existing_reviewed",
                "enabled_for_shadow": True,
                "enabled_for_paper": False,
                "enabled_for_live": False,
                "entry_contract_version": "q4r3.strategy.signal.v1",
                "risk_writer_contract_version": "q4r3.forward_r.writer.v1",
                "source_decision_refs": (
                    [recovery[check.strategy_id]["source"]] if restored else ["q4r3_strategy_canonical_owner_matrix_latest.json"]
                ),
                "contract_pass": check.pass_contract,
            }
        )
    return {
        "schema": "q4r3_canonical_strategy_owner_manifest_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "authority_rule": "ONE_OWNER_PER_STRATEGY_EXACTLY_25_NO_DYNAMIC_FALLBACK",
        "strategy_count": len(entries),
        "dynamic_fallback_allowed": False,
        "runtime_binding_status": "NOT_BOUND_CANDIDATE_ONLY",
        "order_authority": "blocked",
        "execution_authority": "none",
        "strategies": entries,
    }


def render_html(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result.get("checks", []):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('strategy_id')))}</td>"
            f"<td>{'PASS' if item.get('pass_contract') else 'GAP'}</td>"
            f"<td>{html.escape(', '.join(item.get('issues') or []) or '-')}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Q4R3 Exact-25 Contract</title>"
        "<style>body{font-family:Arial,sans-serif;background:#111;color:#eee;margin:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #444;padding:8px;text-align:left}th{background:#222}</style>"
        "</head><body>"
        f"<h1>{html.escape(str(result.get('verdict')))}</h1>"
        f"<p>Contract pass: {result.get('contract_pass_count')}/25</p>"
        "<table><thead><tr><th>Strategy</th><th>Status</th><th>Issues</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )


def run(repo_root: Path, output_root: Path) -> Dict[str, Any]:
    package_root = output_root / "source"
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    copy_snapshot_package(repo_root, package_root)
    recovery = install_recovered_sources(repo_root, package_root)

    checks = [verify_strategy(package_root, strategy_id) for strategy_id in EXPECTED_25]
    manifest = build_manifest(checks, recovery)
    manifest_path = output_root / "manifest" / "q4r3_canonical_strategy_owner_manifest_v1.json"
    atomic_json(manifest_path, manifest)

    contract_pass_count = sum(check.pass_contract for check in checks)
    exact_25 = len(checks) == 25 and len({check.strategy_id for check in checks}) == 25
    all_sources_present = all(check.owner_sha256 for check in checks)
    recovered_two_present = all((package_root / "backend" / "strategies" / f"{name}.py").is_file() for name in RECOVERED_SOURCES)

    if exact_25 and all_sources_present and recovered_two_present and contract_pass_count == 25:
        verdict = "EXACT25_CANDIDATE_PACKAGE_READY_FOR_STAGED_ACTIVE_APPLY"
        next_action = "STAGED_APPLY_TWO_CANONICALS_AND_MANIFEST_WITH_ROLLBACK_GUARD"
    else:
        verdict = "EXACT25_CANDIDATE_PACKAGE_CONTRACT_GAPS_REMAIN"
        next_action = "PATCH_ONLY_REPORTED_CONTRACT_GAPS_THEN_RERUN_HARNESS"

    result: Dict[str, Any] = {
        "schema": "q4r3_exact25_candidate_package_contract_v1",
        "status": "PASS_Q4R3_EXACT25_CANDIDATE_PACKAGE_BUILD",
        "verdict": verdict,
        "action": "HOLD",
        "next_action": next_action,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expected_strategy_count": 25,
        "exact_25": exact_25,
        "all_sources_present": all_sources_present,
        "recovered_two_present": recovered_two_present,
        "contract_pass_count": contract_pass_count,
        "contract_gap_count": 25 - contract_pass_count,
        "manifest_path": str(manifest_path.relative_to(repo_root)).replace("\\", "/"),
        "recovery_decisions": recovery,
        "checks": [check.to_dict() for check in checks],
        "safety": {
            "candidate_package_only": True,
            "active_backend_modified": False,
            "runtime_registry_bound": False,
            "paper_live_order_modified": False,
            "persistent_forward_r_watcher_modified": False,
            "water_add_default_enabled": False,
        },
    }
    atomic_json(output_root / "q4r3_exact25_candidate_package_contract_latest.json", result)
    atomic_json(
        output_root / "q4r3_exact25_candidate_patch_plan_latest.json",
        {
            "verdict": verdict,
            "action": "HOLD",
            "restore_targets": recovery,
            "manifest_path": result["manifest_path"],
            "contract_gaps": [check.to_dict() for check in checks if not check.pass_contract],
            "active_apply_status": "NOT_APPLIED",
        },
    )
    (output_root / "q4r3_exact25_candidate_package_contract_latest.html").write_text(render_html(result), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = repo_root / output_root
    result = run(repo_root, output_root)
    print(
        json.dumps(
            {
                "status": result["status"],
                "verdict": result["verdict"],
                "contract_pass_count": result["contract_pass_count"],
                "contract_gap_count": result["contract_gap_count"],
                "next_action": result["next_action"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
