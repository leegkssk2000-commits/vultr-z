from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "zel.production_vps_preflight.v2"
REQUIRED_ENV_KEYS = (
    "ZEL_DATA_STALE_MS",
    "ZEL_ACCOUNT_STALE_MS",
    "ZEL_MAX_DD_DAY_PCT",
    "ZEL_MAX_DD_TOTAL_PCT",
    "ZEL_ALPHA_SIGNAL_STALE_MS",
    "ZEL_PAPER_INITIAL_EQUITY_USDT",
    "ZEL_RISK_DAY_TZ",
    "ZEL_IMPROVE_MIN_TRADES",
    "ZEL_IMPROVE_MIN_EXPECTANCY",
    "ZEL_IMPROVE_MIN_PF",
    "ZEL_IMPROVE_MIN_NET_PNL",
    "ZEL_IMPROVE_MAX_DD_PCT",
    "ZEL_IMPROVE_MIN_SCORE_GAIN",
    "ZEL_IMPROVE_MAX_DD_REGRESSION_PCT",
    "ZEL_IMPROVE_ERROR_BUDGET",
)
SEARCH_BASES = (Path("/root"), Path("/home"), Path("/opt"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def systemctl(*args: str) -> tuple[int, str]:
    proc = subprocess.run(["systemctl", *args], text=True, capture_output=True, check=False)
    return proc.returncode, (proc.stdout or "").strip()


def _find_files(pattern: str) -> list[Path]:
    roots = [str(path) for path in SEARCH_BASES if path.exists()]
    if not roots:
        return []
    proc = subprocess.run(
        ["find", *roots, "-maxdepth", "7", "-type", "f", "-path", pattern, "-print"],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    return [Path(line.strip()) for line in (proc.stdout or "").splitlines() if line.strip()]


def discover_roots(preferred: Path, expected_files: dict[str, str]) -> tuple[Path | None, list[dict[str, Any]]]:
    candidates: set[Path] = set()
    if preferred.is_dir():
        candidates.add(preferred.resolve())

    for config in _find_files("*/.git/config"):
        try:
            text = config.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "vultr-z" in text:
            candidates.add(config.parent.parent.resolve())

    for marker in _find_files("*/backend/engine/market_data_service.py"):
        try:
            candidates.add(marker.parents[2].resolve())
        except IndexError:
            pass

    for marker in _find_files("*/backend/production/zel_production_spine_v1.py"):
        try:
            candidates.add(marker.parents[2].resolve())
        except IndexError:
            pass

    scored: list[dict[str, Any]] = []
    for root in sorted(candidates, key=str):
        existing = sum(1 for rel in expected_files if (root / rel).is_file())
        exact = sum(
            1
            for rel, expected_sha in expected_files.items()
            if (root / rel).is_file() and sha256_file(root / rel) == expected_sha
        )
        git_match = False
        config = root / ".git" / "config"
        if config.is_file():
            try:
                git_match = "vultr-z" in config.read_text(encoding="utf-8", errors="replace")
            except OSError:
                git_match = False
        scored.append(
            {
                "root": str(root),
                "expected_files_present": existing,
                "exact_master_matches": exact,
                "git_remote_matches_repo": git_match,
                "score": exact * 100 + existing * 10 + (1 if git_match else 0),
            }
        )

    if not scored:
        return None, []
    ranked = sorted(scored, key=lambda row: (-int(row["score"]), str(row["root"])))
    if len(ranked) > 1 and ranked[0]["score"] == ranked[1]["score"]:
        return None, ranked
    return Path(str(ranked[0]["root"])), ranked


def parse_env_presence(path: Path) -> tuple[bool, list[str], list[str]]:
    if not path.exists():
        return False, list(REQUIRED_ENV_KEYS), []
    found: dict[str, bool] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in REQUIRED_ENV_KEYS:
            found[key] = bool(value.strip())
    missing = [key for key in REQUIRED_ENV_KEYS if key not in found]
    empty = [key for key in REQUIRED_ENV_KEYS if key in found and not found[key]]
    return True, missing, empty


def audit(preferred_root: Path, manifest_path: Path, env_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = manifest.get("files") or {}
    if not isinstance(expected_files, dict) or not expected_files:
        raise RuntimeError("PREFLIGHT_MANIFEST_INVALID")

    root, root_candidates = discover_roots(preferred_root, expected_files)
    if root is None:
        result = {
            "schema_version": SCHEMA,
            "state": "HOLD_VPS_ROOT_AUTHORITY_UNRESOLVED",
            "preferred_root": str(preferred_root),
            "selected_root": None,
            "root_candidates": root_candidates,
            "blockers": ["VPS_REPOSITORY_ROOT_UNRESOLVED"],
            "mutation_performed": False,
            "exchange_order_submitted": False,
            "live_trade_authority": "BLOCKED",
        }
        result["receipt_sha256"] = stable_sha(result)
        return result

    file_results: dict[str, Any] = {}
    parity_ok = True
    for rel, expected_sha in sorted(expected_files.items()):
        path = root / rel
        exists = path.is_file()
        actual_sha = sha256_file(path) if exists else None
        match = bool(exists and actual_sha == expected_sha)
        parity_ok = parity_ok and match
        file_results[rel] = {"exists": exists, "sha256_match": match}

    env_exists, env_missing, env_empty = parse_env_presence(env_path)
    env_ready = bool(env_exists and not env_missing and not env_empty)
    ledger = root / "ledger"
    ledger_ready = ledger.is_dir() and os.access(ledger, os.W_OK)

    rc_fragment, fragment_path_raw = systemctl("show", "zel-production-paper-loop-v1.service", "-p", "FragmentPath", "--value")
    fragment_path = Path(fragment_path_raw) if rc_fragment == 0 and fragment_path_raw else None
    unit_exists = bool(fragment_path and fragment_path.is_file())
    expected_unit_sha = manifest.get("systemd_unit_sha256")
    installed_unit_sha = sha256_file(fragment_path) if unit_exists and fragment_path else None
    unit_parity = bool(unit_exists and expected_unit_sha and installed_unit_sha == expected_unit_sha)

    _rc_enabled, enabled_raw = systemctl("is-enabled", "zel-production-paper-loop-v1.service")
    _rc_active, active_raw = systemctl("is-active", "zel-production-paper-loop-v1.service")
    service_enabled = enabled_raw == "enabled"
    service_active = active_raw == "active"

    import_ready = False
    import_error = None
    try:
        proc = subprocess.run(
            [
                "python3",
                "-c",
                "import backend.production.zel_production_risk_sizing_v1,"
                "backend.production.zel_production_bingx_freshness_v1,"
                "backend.production.zel_production_active_alpha_adapter_v1,"
                "backend.production.zel_production_improvement_controller_v1; print('PASS')",
            ],
            cwd=root,
            env={**os.environ, "PYTHONPATH": str(root)},
            text=True,
            capture_output=True,
            check=False,
        )
        import_ready = proc.returncode == 0 and "PASS" in (proc.stdout or "")
        if not import_ready:
            import_error = (proc.stderr or "").strip()[-500:]
    except Exception as exc:
        import_error = f"{type(exc).__name__}:{exc}"

    blockers: list[str] = []
    if not parity_ok:
        blockers.append("DEPLOYED_SOURCE_NOT_MASTER_PARITY")
    if not env_ready:
        blockers.append("PAPER_ENV_SSOT_NOT_READY")
    if not ledger_ready:
        blockers.append("LEDGER_PATH_NOT_WRITABLE")
    if not unit_parity:
        blockers.append("SYSTEMD_UNIT_NOT_MASTER_PARITY")
    if not service_enabled:
        blockers.append("PAPER_SERVICE_NOT_ENABLED")
    if not service_active:
        blockers.append("PAPER_SERVICE_NOT_ACTIVE")
    if not import_ready:
        blockers.append("PRODUCTION_IMPORT_NOT_READY")

    state = "PASS_VPS_PRODUCTION_PAPER_READY" if not blockers else "HOLD_VPS_PRODUCTION_DEPLOYMENT_REQUIRED"
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "preferred_root": str(preferred_root),
        "selected_root": str(root),
        "root_candidates": root_candidates,
        "source_file_count": len(file_results),
        "source_parity": parity_ok,
        "files": file_results,
        "env": {
            "path_exists": env_exists,
            "required_key_count": len(REQUIRED_ENV_KEYS),
            "missing_keys": env_missing,
            "empty_keys": env_empty,
            "values_redacted": True,
            "ready": env_ready,
        },
        "ledger_writable": ledger_ready,
        "systemd": {
            "fragment_exists": unit_exists,
            "unit_sha256_match": unit_parity,
            "enabled": service_enabled,
            "active": service_active,
        },
        "python_import_ready": import_ready,
        "python_import_error": import_error,
        "blockers": blockers,
        "mutation_performed": False,
        "exchange_order_submitted": False,
        "live_trade_authority": "BLOCKED",
    }
    result["receipt_sha256"] = stable_sha(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/home/zel/apps/zel"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--env", type=Path, default=Path("/etc/zel/production-paper-loop.env"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.manifest, args.env)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
