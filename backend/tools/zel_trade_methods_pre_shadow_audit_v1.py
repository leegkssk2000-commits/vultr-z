from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "ZEL_TRADE_METHODS_PRE_SHADOW_AUDIT_V1"
CORE_FILES = ("types.py", "policy.py", "profiles.py", "resolver.py", "__init__.py")
PERSONAL_SOURCE_NAMES = (
    "트레이딩 방법론.txt",
    "trade_methods_personal.md",
    "trade_methods_personal.txt",
)
SKIP_DIR_NAMES = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__",
    "runtime", "runtime_results", "data", "backups", "backup", "archive",
    "quarantine", "_quarantine", "imported_zips",
}
METHOD_MARKERS = {
    "types.py": ("TradeSkill", "MethodRiskMode", "TradeMethodPlan"),
    "policy.py": (
        "BASE_TP_R", "FALLBACK_TP_R", "LONG_BEAM_CAP_R",
        "SKILL_PERMISSION_POLICY", "COST_SLIPPAGE_POLICY",
        "DRAWDOWN_POLICY", "COMBO_FILTER_POLICY",
    ),
    "profiles.py": ("METHOD_PROFILE_RISK_BINDINGS",),
    "resolver.py": ("resolve_trade_method_plan",),
    "__init__.py": ("resolve_trade_method_plan", "TradeMethodPlan"),
}
METHOD_FAMILIES = {
    "scalping": (
        "scalp", "ema_ribbon", "volume_spike", "bollinger", "gorilla",
        "supertrend", "adx", "pivot", "hma", "micro",
    ),
    "trend": ("trend", "ema", "macd", "alligator", "ribbon"),
    "breakout": ("breakout", "squeeze", "liquidity_sweep", "pivot"),
    "reversal": ("revert", "reversal", "countertrend", "fractal", "sr_levels"),
    "pullback": ("pullback", "retracement", "fractal", "ema_ribbon"),
    "exit": ("partial", "trailing", "runner", "mfe", "time_stop", "breakeven"),
    "risk": ("risk", "stop", "drawdown", "cost", "slippage", "funding"),
    "sizing": ("scale_in", "pyramiding", "dca", "average_down", "water_add"),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    process = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
    )
    return {"returncode": process.returncode, "output_tail": process.stdout[-4000:]}


def bounded_files(roots: Iterable[Path], max_files: int = 30_000) -> Iterable[Path]:
    seen = 0
    for root in roots:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if name not in SKIP_DIR_NAMES]
            for name in files:
                seen += 1
                if seen > max_files:
                    return
                yield Path(current) / name


def find_personal_sources(root: Path) -> list[dict[str, Any]]:
    search_roots = [root, Path("/opt/zel"), Path("/var/www")]
    result: list[dict[str, Any]] = []
    target_names = {name.casefold() for name in PERSONAL_SOURCE_NAMES}
    for path in bounded_files(search_roots):
        if path.name.casefold() not in target_names:
            continue
        try:
            stat = path.stat()
            result.append({
                "path": str(path),
                "name": path.name,
                "size_bytes": stat.st_size,
                "sha256": sha256_path(path),
            })
        except OSError:
            continue
    return sorted(result, key=lambda item: item["path"])


def inspect_trade_methods(root: Path) -> dict[str, Any]:
    package = root / "backend" / "trade_methods"
    files: dict[str, Any] = {}
    missing_files: list[str] = []
    missing_markers: dict[str, list[str]] = {}
    for name in CORE_FILES:
        path = package / name
        if not path.is_file():
            missing_files.append(name)
            files[name] = {"exists": False}
            continue
        text = read_text(path)
        absent = [marker for marker in METHOD_MARKERS[name] if marker not in text]
        if absent:
            missing_markers[name] = absent
        files[name] = {
            "exists": True,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_path(path),
            "marker_count": len(METHOD_MARKERS[name]) - len(absent),
            "marker_expected": len(METHOD_MARKERS[name]),
        }

    compile_result = {"returncode": 1, "output_tail": "CORE_FILES_MISSING"}
    import_result = {"returncode": 1, "output_tail": "CORE_FILES_MISSING"}
    if not missing_files:
        python = root / ".venv" / "bin" / "python"
        if not python.is_file():
            python = root / "venv" / "bin" / "python"
        if python.is_file():
            compile_result = run(str(python), "-m", "py_compile", *[str(package / name) for name in CORE_FILES])
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root)
            import_result = run(
                str(python),
                "-c",
                (
                    "import backend.trade_methods as m;"
                    "assert hasattr(m,'resolve_trade_method_plan');"
                    "assert hasattr(m,'TradeMethodPlan');"
                    "print('PASS_TRADE_METHOD_IMPORT')"
                ),
                cwd=root,
                env=env,
            )

    return {
        "package_path": str(package),
        "package_exists": package.is_dir(),
        "files": files,
        "missing_files": missing_files,
        "missing_markers": missing_markers,
        "h74tm8_markers_complete": not missing_files and not missing_markers,
        "compile_ok": compile_result["returncode"] == 0,
        "compile_output_tail": compile_result["output_tail"],
        "import_ok": import_result["returncode"] == 0,
        "import_output_tail": import_result["output_tail"],
    }


def strategy_inventory(root: Path) -> dict[str, Any]:
    manifest_paths = (
        root / "backend" / "config" / "q4r3_canonical_strategy_owner_manifest_v1.json",
        Path("/opt/zel/forward-expansion-v1/source/backend/config/q4r3_canonical_strategy_owner_manifest_v1.json"),
    )
    manifest = next((path for path in manifest_paths if path.is_file()), None)
    strategies: list[dict[str, Any]] = []
    if manifest:
        try:
            payload = json.loads(read_text(manifest))
            for row in payload.get("strategies") or []:
                if isinstance(row, dict):
                    strategies.append({
                        "strategy_id": row.get("strategy_id"),
                        "owner_path": row.get("owner_path"),
                        "owner_sha256": row.get("owner_sha256"),
                    })
        except Exception as exc:
            return {
                "manifest_path": str(manifest),
                "manifest_error": f"{type(exc).__name__}:{exc}",
                "strategy_count": 0,
                "strategies": [],
                "family_coverage": {},
            }

    searchable = " ".join(
        f"{row.get('strategy_id','')} {row.get('owner_path','')}".lower() for row in strategies
    )
    coverage = {
        family: {
            "covered": any(token in searchable for token in tokens),
            "matched_tokens": [token for token in tokens if token in searchable],
        }
        for family, tokens in METHOD_FAMILIES.items()
    }
    return {
        "manifest_path": str(manifest) if manifest else None,
        "strategy_count": len(strategies),
        "strategies": strategies,
        "family_coverage": coverage,
    }


def component_inventory(root: Path) -> dict[str, Any]:
    expected = {
        "bots": root / "canonical" / "bots",
        "teams": root / "canonical" / "teams",
        "skills": root / "canonical" / "skills",
        "zbot": root / "canonical" / "zbot.py",
        "zico": root / "canonical" / "zico.py",
        "lico": root / "canonical" / "lico.py",
        "zlice": root / "canonical" / "zlice.py",
    }
    return {
        name: {"path": str(path), "exists": path.exists()}
        for name, path in expected.items()
    }


def audit(root: Path) -> dict[str, Any]:
    methods = inspect_trade_methods(root)
    personal_sources = find_personal_sources(root)
    strategies = strategy_inventory(root)
    components = component_inventory(root)

    blockers: list[str] = []
    if not methods["package_exists"]:
        blockers.append("TRADE_METHODS_PACKAGE_MISSING")
    if not methods["h74tm8_markers_complete"]:
        blockers.append("H74TM8_POLICY_MARKERS_INCOMPLETE")
    if not methods["compile_ok"]:
        blockers.append("TRADE_METHODS_COMPILE_FAIL")
    if not methods["import_ok"]:
        blockers.append("TRADE_METHODS_IMPORT_OR_EXPORT_FAIL")
    if not personal_sources:
        blockers.append("PERSONAL_TRADING_METHOD_MASTER_NOT_FOUND_ON_VPS")
    if strategies["strategy_count"] != 25:
        blockers.append(f"STRATEGY_COUNT_NOT_EXACT25:{strategies['strategy_count']}")

    missing_families = [
        family for family, row in strategies["family_coverage"].items() if not row["covered"]
    ]
    if missing_families:
        blockers.append("METHOD_FAMILY_COVERAGE_GAPS:" + ",".join(sorted(missing_families)))

    state = "PASS_TRADE_METHODS_PRE_SHADOW_STRUCTURE" if not blockers else "HOLD_TRADE_METHODS_PRE_SHADOW_GAPS"
    return {
        "schema_version": "zel.trade_methods.pre_shadow.audit.v1",
        "version": VERSION,
        "generated_at": now_iso(),
        "state": state,
        "root": str(root),
        "trade_methods": methods,
        "personal_method_sources": personal_sources,
        "personal_method_source_expected_names": list(PERSONAL_SOURCE_NAMES),
        "strategy_inventory": strategies,
        "component_inventory": components,
        "blockers": blockers,
        "required_automatic_chain": [
            "PERSONAL_METHOD_SOURCE_INTAKE_AND_NORMALIZATION",
            "METHOD_TO_EXISTING_STRATEGY_AND_SKILL_COVERAGE",
            "MISSING_METHOD_RESEARCH_ONLY_IMPLEMENTATION",
            "DATA_B_15M_AND_1M_METHOD_REPLAY",
            "COST_LATENCY_SPREAD_FILL_STRESS_FOR_SCALPING",
            "W2_NEW_FORWARD_CONFIRMATION",
            "W3_TEMPORAL_DURABILITY",
            "COMPONENT_V3_BOT_TEAM_SKILL_ADVISOR_ABLATION",
            "ZICO_FAULT_RECOVERY_AND_IDEMPOTENCY_GATE",
            "LICO_REALISTIC_FILL_AND_CAPACITY_GATE",
            "ZLICE_EXACT_LINEAGE_AND_ATTRIBUTION_GATE",
            "PRE_SHADOW_RELEASE_GATE",
        ],
        "user_configuration_required": False,
        "canonical_strategy_files_mutated": False,
        "canonical_trade_methods_mutated": False,
        "canonical_registry_mutated": False,
        "shadow_start_allowed": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "paper_enabled": False,
        "live_enabled": False,
        "action": "hold",
    }


def self_test() -> None:
    assert "scalping" in METHOD_FAMILIES
    assert "resolve_trade_method_plan" in METHOD_MARKERS["resolver.py"]
    assert len(CORE_FILES) == 5
    print(json.dumps({"state": "PASS_SELF_TEST", "version": VERSION}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/home/z/z")
    parser.add_argument("--out")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.out:
        parser.error("--out is required")
    result = audit(Path(args.root).resolve())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "blockers": result["blockers"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
