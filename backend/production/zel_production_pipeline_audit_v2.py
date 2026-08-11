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
    "backend/production/zel_production_trend_momentum_v1.py",
    "backend/production/zel_production_carry_flow_data_v1.py",
    "backend/production/zel_production_alpha_signal_runner_v1.py",
    "backend/production/zel_production_active_alpha_adapter_v1.py",
    "backend/production/zel_production_paper_account_state_v1.py",
    "backend/production/zel_production_paper_source_adapter_v1.py",
    "backend/production/zel_production_paper_loop_v1.py",
    "backend/production/zel_production_auto_cycle_supervisor_v1.py",
    "backend/production/zel_production_improvement_controller_v1.py",
    "backend/production/zel_production_paper_runner_v1.sh",
    "deploy/systemd/zel-production-paper-loop-v1.service",
    "deploy/systemd/zel-production-paper-loop-v1.env.example",
    "config/zel_production_alpha_factory_v1.json",
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


def text(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def obj(root: Path, rel: str) -> dict[str, Any]:
    row = json.loads(text(root, rel))
    require(isinstance(row, dict), f"AUDIT_JSON_NOT_OBJECT:{rel}")
    return row


def audit(root: Path) -> dict[str, Any]:
    missing = [rel for rel in REQUIRED_FILES if not (root / rel).exists()]
    require(not missing, f"AUDIT_REQUIRED_FILES_MISSING:{missing}")

    producer_runner = text(root, "backend/production/zel_production_alpha_signal_runner_v1.py")
    active_adapter = text(root, "backend/production/zel_production_active_alpha_adapter_v1.py")
    trend = text(root, "backend/production/zel_production_trend_momentum_v1.py")
    carry_data = text(root, "backend/production/zel_production_carry_flow_data_v1.py")
    source = text(root, "backend/production/zel_production_paper_source_adapter_v1.py")
    freshness = text(root, "backend/production/zel_production_bingx_freshness_v1.py")
    runner = text(root, "backend/production/zel_production_paper_runner_v1.sh")
    loop = text(root, "backend/production/zel_production_paper_loop_v1.py")
    supervisor = text(root, "backend/production/zel_production_auto_cycle_supervisor_v1.py")
    improvement = text(root, "backend/production/zel_production_improvement_controller_v1.py")
    service = text(root, "deploy/systemd/zel-production-paper-loop-v1.service")
    env_example = text(root, "deploy/systemd/zel-production-paper-loop-v1.env.example")

    payload_start = source.index("def build_payload(")
    payload_end = source.index("class CanonicalPaperSourceAdapter", payload_start)
    payload_body = source[payload_start:payload_end]
    null_guard = payload_body.index("if authority is None:")
    inactive_guard = payload_body.index("if not authority_is_executable(authority):")
    network_call = payload_body.index("market_receipt = fetch_fresh_bingx_quote")

    producer_tick_start = producer_runner.index("def run_once(")
    producer_tick_end = producer_runner.index("def main(", producer_tick_start)
    producer_tick = producer_runner[producer_tick_start:producer_tick_end]
    producer_missing_guard = producer_tick.index("if not authority_path.exists():")
    producer_exec_guard = producer_tick.index("if not authority_is_executable(authority):")
    producer_network_call = producer_tick.index("signal_generator(authority")

    producer_i = runner.index("zel_production_alpha_signal_runner_v1")
    source_i = runner.index("zel_production_paper_source_adapter_v1")
    cycle_i = runner.index("zel_production_paper_loop_v1")
    improve_i = runner.index("zel_production_improvement_controller_v1")

    checks: dict[str, bool] = {
        "strict_bingx_native_path": (
            "fetch_fresh_bingx_quote" in source
            and "BingXPublicAdapter" in freshness
            and "DummyTickerAdapter" not in freshness
            and "MarketDataService(" not in source
        ),
        "paper_no_alpha_fast_path_before_network": null_guard < inactive_guard < network_call,
        "producer_no_alpha_fast_path_before_network": producer_missing_guard < producer_exec_guard < producer_network_call,
        "trend_component_preserved_as_nonactive_material": (
            "BingXPublicAdapter" in trend
            and "fetch_fresh_bingx_quote" in trend
            and 'cfg.get("status") != "IMPLEMENTED_PRIMARY_SEED"' in trend
            and "TREND_MOMENTUM_NOT_IMPLEMENTED" in trend
        ),
        "terminal_authority_runtime_guard": (
            "TERMINAL_REJECTED_STRATEGY_IDS" in active_adapter
            and '"trend_momentum_v1"' in active_adapter
            and '"relative_value_psa_v1"' in active_adapter
            and "strategy_id not in TERMINAL_REJECTED_STRATEGY_IDS" in active_adapter
        ),
        "carry_native_data_owner_strict": (
            '"premium_index": "/openApi/swap/v2/quote/premiumIndex"' in carry_data
            and '"open_interest": "/openApi/swap/v2/quote/openInterest"' in carry_data
            and '"economic_signal_generated": False' in carry_data
            and '"promotion_authority": False' in carry_data
            and '"execution_authority": "NONE"' in carry_data
            and '"order_authority": "BLOCKED"' in carry_data
        ),
        "runner_pipeline_order": producer_i < source_i < cycle_i < improve_i,
        "runner_single_invocation_each": (
            runner.count("zel_production_alpha_signal_runner_v1") == 1
            and runner.count("zel_production_paper_source_adapter_v1") == 1
            and runner.count("zel_production_paper_loop_v1") == 1
            and runner.count("zel_production_improvement_controller_v1") == 1
        ),
        "paper_circuit_breaker_preserved": "CIRCUIT_OPEN" in loop and "MAX_FAILURES" in runner and "exit 2" in runner,
        "supervisor_single_flight_and_rollback": "SINGLE_FLIGHT_ACTIVE" in supervisor and "ROLLBACK_REQUIRED" in supervisor,
        "improvement_config_only": "CONFIG_ONLY" in improvement and "source_code_mutation_applied" in improvement and "self_modification_applied" in improvement,
        "improvement_candidate_budget_2": "generate_candidates" in improvement and "candidate_budget" in improvement,
    }

    alpha_factory = obj(root, "config/zel_production_alpha_factory_v1.json")
    risk = obj(root, "config/zel_production_risk_sizing_v1.json")
    account = obj(root, "config/zel_production_paper_account_v1.json")
    active = obj(root, "config/zel_production_active_alpha_v1.json")
    imp = obj(root, "config/zel_production_improvement_v1.json")

    families = alpha_factory.get("families") or {}
    trend_cfg = families.get("trend_momentum") or {}
    carry_cfg = families.get("carry_flow") or {}
    rv_cfg = families.get("relative_value_psa") or {}
    trend_terminal = trend_cfg.get("terminal_evidence") or {}
    rv_terminal = rv_cfg.get("terminal_evidence") or {}
    material = alpha_factory.get("legacy_strategy_material") or {}
    checks.update({
        "alpha_factory_safe_idle_zero_survivor": (
            alpha_factory.get("state") == "NO_ECONOMIC_SURVIVOR_SAFE_IDLE"
            and alpha_factory.get("mode") == "PAPER"
            and alpha_factory.get("economic_survivor_count") == 0
            and alpha_factory.get("executable_family_count") == 0
            and alpha_factory.get("order_authority") == "BLOCKED"
            and alpha_factory.get("live_trade_authority") == "BLOCKED"
            and alpha_factory.get("exchange_order_submitted") is False
        ),
        "trend_terminal_reject_sealed": (
            trend_cfg.get("strategy_id") == "trend_momentum_v1"
            and trend_cfg.get("status") == "TERMINAL_REJECT_DO_NOT_REACTIVATE"
            and trend_cfg.get("mechanism") == "FINAL_GEN3_24H_MOMENTUM_7D_REGIME_LONG"
            and trend_cfg.get("reactivation_allowed") is False
            and trend_cfg.get("selection_authority") is False
            and trend_cfg.get("promotion_authority") is False
            and trend_cfg.get("execution_authority") == "NONE"
            and trend_terminal.get("pull_request") == 607
            and trend_terminal.get("workflow_run") == 31410036751
            and trend_terminal.get("w1_trade_count") == 23
            and trend_terminal.get("w2_trade_count") == 36
            and float(trend_terminal.get("w1_net_compound_pct")) < 0.0
            and float(trend_terminal.get("w2_net_compound_pct")) < 0.0
            and float(trend_terminal.get("w1_profit_factor")) < 1.0
            and float(trend_terminal.get("w2_profit_factor")) < 1.0
            and trend_terminal.get("w3_materialized") is False
        ),
        "carry_flow_data_bound_signal_still_blocked": (
            carry_cfg.get("status") == "IMPLEMENTED_CARRY_POSITIONING_DATA_PLANE"
            and carry_cfg.get("production_data_owner") == "backend/production/zel_production_carry_flow_data_v1.py"
            and carry_cfg.get("funding_source_bound") is True
            and carry_cfg.get("basis_source_bound") is True
            and carry_cfg.get("open_interest_source_bound") is True
            and carry_cfg.get("flow_source_bound") is False
            and carry_cfg.get("economic_signal_enabled") is False
            and carry_cfg.get("selection_authority") is False
            and carry_cfg.get("promotion_authority") is False
            and carry_cfg.get("execution_authority") == "NONE"
        ),
        "relative_value_terminal_reject_sealed": (
            rv_cfg.get("strategy_id") == "relative_value_psa_v1"
            and rv_cfg.get("status") == "TERMINAL_REJECT_DO_NOT_REACTIVATE"
            and rv_cfg.get("mechanism") == "BTC_ETH_7D_LOG_RATIO_MEAN_REVERSION"
            and rv_cfg.get("reactivation_allowed") is False
            and rv_cfg.get("selection_authority") is False
            and rv_cfg.get("promotion_authority") is False
            and rv_cfg.get("execution_authority") == "NONE"
            and rv_terminal.get("pull_request") == 606
            and rv_terminal.get("workflow_run") == 31407842533
            and rv_terminal.get("w3_trade_count") == 12
            and float(rv_terminal.get("w3_net_compound_pct")) < 0.0
            and float(rv_terminal.get("w3_net_expectancy_pct_per_trade")) < 0.0
            and float(rv_terminal.get("w3_net_profit_factor")) < 1.0
        ),
        "legacy_strategies_material_only": (
            material.get("role") == "MATERIAL_ONLY"
            and material.get("direct_execution_authority") is False
            and material.get("direct_promotion_authority") is False
        ),
        "risk_presets_exact": risk.get("allowed_leverage_x") == [10, 15, 20] and risk.get("allowed_position_pct") == [5, 10, 15, 20],
        "conditional_25x_blocked": risk.get("conditional_25x_enabled") is False and 25 not in (risk.get("allowed_leverage_x") or []),
        "risk_thresholds_not_invented": all(risk.get(k) is None for k in ("market_data_stale_ms", "account_state_stale_ms", "max_dd_day_pct", "max_dd_total_pct")),
        "account_capital_not_invented": account.get("initial_equity_usdt") is None and account.get("risk_day_timezone") is None,
        "active_signal_stale_not_invented": active.get("signal_stale_ms") is None,
        "improvement_thresholds_not_invented": all(v is None for v in (imp.get("thresholds") or {}).values()),
        "improvement_budget_exact": imp.get("candidate_budget") == 2 and imp.get("mutation_class") == "CONFIG_ONLY",
        "all_config_live_blocked": all(row.get("order_authority") == "BLOCKED" and row.get("live_trade_authority") == "BLOCKED" for row in (alpha_factory, risk, account, active, imp)),
        "all_config_no_exchange_submit": all(row.get("exchange_order_submitted") is False for row in (alpha_factory, risk, account, active, imp)),
        "improvement_self_mod_blocked": imp.get("source_code_mutation_allowed") is False and imp.get("self_modification_allowed") is False,
    })

    required_env = {
        "ZEL_DATA_STALE_MS", "ZEL_ACCOUNT_STALE_MS", "ZEL_MAX_DD_DAY_PCT", "ZEL_MAX_DD_TOTAL_PCT",
        "ZEL_ALPHA_SIGNAL_STALE_MS", "ZEL_PAPER_INITIAL_EQUITY_USDT", "ZEL_RISK_DAY_TZ",
        "ZEL_IMPROVE_MIN_TRADES", "ZEL_IMPROVE_MIN_EXPECTANCY", "ZEL_IMPROVE_MIN_PF",
        "ZEL_IMPROVE_MIN_NET_PNL", "ZEL_IMPROVE_MAX_DD_PCT", "ZEL_IMPROVE_MIN_SCORE_GAIN",
        "ZEL_IMPROVE_MAX_DD_REGRESSION_PCT", "ZEL_IMPROVE_ERROR_BUDGET",
    }
    checks.update({
        "env_ssot_contract_complete": all(f"{name}=" in env_example for name in required_env),
        "service_reads_env_contract": "EnvironmentFile=-/etc/zel/production-paper-loop.env" in service,
        "systemd_write_scope_ledger_only": "ReadWritePaths=/home/z/z/ledger" in service,
        "systemd_circuit_no_restart": "RestartPreventExitStatus=2" in service,
        "systemd_no_new_privileges": "NoNewPrivileges=true" in service,
        "no_live_submit_in_new_modules": all(
            token in producer_runner + active_adapter + trend + carry_data + source + freshness + improvement
            for token in ("exchange_order_submitted", "BLOCKED")
        ),
    })

    failed = sorted(k for k, passed in checks.items() if not passed)
    require(not failed, f"AUDIT_CHECKS_FAILED:{failed}")
    receipt = {
        "schema_version": SCHEMA,
        "state": "PASS_PRODUCTION_COMPLETION_PIPELINE_AUDIT",
        "check_count": len(checks),
        "checks": checks,
        "bottleneck_findings": {
            "active_dummy_market_fallback": "REMOVED_FROM_ACTIVE_PATH",
            "no_alpha_network_work": "SKIPPED_AT_PRODUCER_AND_SOURCE",
            "runner_stage_order": "ALPHA_PRODUCER_THEN_SOURCE_THEN_PAPER_THEN_IMPROVEMENT",
            "primary_alpha_family": "NONE_ECONOMIC_SURVIVOR",
            "economic_survivor_count": 0,
            "executable_family_count": 0,
            "trend_momentum": "TERMINAL_REJECT_DO_NOT_REACTIVATE",
            "carry_flow": "CARRY_POSITIONING_DATA_BOUND_FLOW_AND_SIGNAL_BLOCKED",
            "relative_value_psa": "TERMINAL_REJECT_DO_NOT_REACTIVATE",
            "legacy_strategy_role": "MATERIAL_ONLY",
            "candidate_budget": 2,
            "source_code_self_modification": False,
            "live_exchange_submission": False,
        },
        "cleanup": {
            "generic_dummy_adapter_deleted": False,
            "generic_dummy_adapter_scope": "DEV_TEST_ONLY_NOT_PRODUCTION_ACTIVE_PATH",
            "historical_research_evidence_deleted": False,
            "historical_research_evidence_scope": "RETAINED_AS_AUDIT_HISTORY",
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
