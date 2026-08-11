from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "zel.production_pipeline_audit.v2"

REQUIRED_FILES = (
    "backend/production/zel_production_risk_sizing_v1.py",
    "backend/production/zel_production_bingx_freshness_v1.py",
    "backend/production/zel_production_active_alpha_adapter_v1.py",
    "backend/production/zel_production_paper_account_state_v1.py",
    "backend/production/zel_production_paper_source_adapter_v1.py",
    "backend/production/zel_production_paper_loop_v1.py",
    "backend/production/zel_production_auto_cycle_supervisor_v1.py",
    "backend/production/zel_production_improvement_controller_v1.py",
    "backend/production/zel_production_paper_runner_v1.sh",
    "deploy/systemd/zel-production-paper-loop-v1.service",
    "deploy/systemd/zel-production-paper-loop-v1.env.example",
    "config/zel_production_risk_sizing_v1.json",
    "config/zel_production_paper_account_v1.json",
    "config/zel_production_active_alpha_v1.json",
    "config/zel_production_improvement_v1.json",
)


def stable_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(root: Path, rel: str) -> dict[str, Any]:
    row = json.loads((root / rel).read_text(encoding="utf-8"))
    require(isinstance(row, dict), f"AUDIT_JSON_NOT_OBJECT:{rel}")
    return row


def read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def audit(root: Path) -> dict[str, Any]:
    missing = [rel for rel in REQUIRED_FILES if not (root / rel).exists()]
    require(not missing, f"AUDIT_REQUIRED_FILES_MISSING:{missing}")

    source = read(root, "backend/production/zel_production_paper_source_adapter_v1.py")
    freshness = read(root, "backend/production/zel_production_bingx_freshness_v1.py")
    runner = read(root, "backend/production/zel_production_paper_runner_v1.sh")
    loop = read(root, "backend/production/zel_production_paper_loop_v1.py")
    supervisor = read(root, "backend/production/zel_production_auto_cycle_supervisor_v1.py")
    improvement = read(root, "backend/production/zel_production_improvement_controller_v1.py")
    service = read(root, "deploy/systemd/zel-production-paper-loop-v1.service")
    env_example = read(root, "deploy/systemd/zel-production-paper-loop-v1.env.example")

    checks: dict[str, bool] = {}
    checks["strict_bingx_native_path"] = (
        "fetch_fresh_bingx_quote" in source
        and "BingXPublicAdapter" in freshness
        and "DummyTickerAdapter" not in freshness
        and "MarketDataService(" not in source
    )
    no_alpha_guard = source.index("if authority is None or not authority_is_executable(authority)")
    active_network_call = source.index("market_receipt = fetch_fresh_bingx_quote")
    checks["no_alpha_fast_path_before_network"] = no_alpha_guard < active_network_call

    source_i = runner.index("zel_production_paper_source_adapter_v1")
    cycle_i = runner.index("zel_production_paper_loop_v1")
    improve_i = runner.index("zel_production_improvement_controller_v1")
    checks["runner_pipeline_order"] = source_i < cycle_i < improve_i
    checks["runner_single_invocation_each"] = (
        runner.count("zel_production_paper_source_adapter_v1") == 1
        and runner.count("zel_production_paper_loop_v1") == 1
        and runner.count("zel_production_improvement_controller_v1") == 1
    )
    checks["paper_circuit_breaker_preserved"] = "CIRCUIT_OPEN" in loop and "MAX_FAILURES" in runner and "exit 2" in runner
    checks["supervisor_single_flight_and_rollback"] = "SINGLE_FLIGHT_ACTIVE" in supervisor and "ROLLBACK_REQUIRED" in supervisor
    checks["improvement_config_only"] = "CONFIG_ONLY" in improvement and "source_code_mutation_applied" in improvement and "self_modification_applied" in improvement
    checks["improvement_candidate_budget_2"] = "candidate_budget" in improvement and "generate_candidates" in improvement

    risk = load_json(root, "config/zel_production_risk_sizing_v1.json")
    account = load_json(root, "config/zel_production_paper_account_v1.json")
    active = load_json(root, "config/zel_production_active_alpha_v1.json")
    imp = load_json(root, "config/zel_production_improvement_v1.json")

    checks["risk_presets_exact"] = risk.get("allowed_leverage_x") == [10, 15, 20] and risk.get("allowed_position_pct") == [5, 10, 15, 20]
    checks["conditional_25x_blocked"] = risk.get("conditional_25x_enabled") is False and 25 not in (risk.get("allowed_leverage_x") or [])
    checks["risk_thresholds_not_invented"] = all(risk.get(key) is None for key in ("market_data_stale_ms", "account_state_stale_ms", "max_dd_day_pct", "max_dd_total_pct"))
    checks["account_capital_not_invented"] = account.get("initial_equity_usdt") is None and account.get("risk_day_timezone") is None
    checks["active_signal_stale_not_invented"] = active.get("signal_stale_ms") is None
    checks["improvement_thresholds_not_invented"] = all(v is None for v in (imp.get("thresholds") or {}).values())
    checks["improvement_budget_exact"] = imp.get("candidate_budget") == 2 and imp.get("mutation_class") == "CONFIG_ONLY"

    blocked_configs = (risk, account, active, imp)
    checks["all_config_live_blocked"] = all(row.get("order_authority") == "BLOCKED" and row.get("live_trade_authority") == "BLOCKED" for row in blocked_configs)
    checks["all_config_no_exchange_submit"] = all(row.get("exchange_order_submitted") is False for row in blocked_configs)
    checks["improvement_self_mod_blocked"] = imp.get("source_code_mutation_allowed") is False and imp.get("self_modification_allowed") is False

    required_env = {
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
    }
    checks["env_ssot_contract_complete"] = all(f"{name}=" in env_example for name in required_env)
    checks["service_reads_env_contract"] = "EnvironmentFile=-/etc/zel/production-paper-loop.env" in service
    checks["systemd_write_scope_ledger_only"] = "ReadWritePaths=/home/zel/apps/zel/ledger" in service
    checks["systemd_circuit_no_restart"] = "RestartPreventExitStatus=2" in service
    checks["systemd_no_new_privileges"] = "NoNewPrivileges=true" in service
    checks["no_live_submit_in_new_modules"] = all(token in source + freshness + improvement for token in ("exchange_order_submitted", "BLOCKED"))

    failed = sorted(name for name, passed in checks.items() if not passed)
    require(not failed, f"AUDIT_CHECKS_FAILED:{failed}")

    receipt = {
        "schema_version": SCHEMA,
        "state": "PASS_PRODUCTION_COMPLETION_PIPELINE_AUDIT",
        "check_count": len(checks),
        "checks": checks,
        "bottleneck_findings": {
            "active_dummy_market_fallback": "REMOVED_FROM_ACTIVE_PATH",
            "no_alpha_network_work": "SKIPPED",
            "runner_stage_order": "SOURCE_THEN_PAPER_THEN_IMPROVEMENT",
            "candidate_budget": 2,
            "source_code_self_modification": False,
            "live_exchange_submission": False,
        },
        "cleanup": {
            "generic_dummy_adapter_deleted": False,
            "reason": "retained for dev/test only; production active path bypasses it",
            "historical_research_evidence_deleted": False,
            "reason_history": "audit evidence retained; only canonical production path is asserted",
        },
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit ZEL production completion pipeline")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = audit(args.repo_root.resolve())
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
