from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import zel_alpha_combo_validation_chain_v1 as base

VERSION = "ZEL_ALPHA_UNATTENDED_CHAMPION_V2"
SCHEMA = "zel.alpha.unattended_champion.receipt.v2"
STATE_SCHEMA = "zel.alpha.unattended_champion.state.v2"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def stable_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def optional_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def normalized_config(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "stop_mult": metric(value.get("stop_mult"), 0.65),
        "time_stop_bars_15m": (
            int(value["time_stop_bars_15m"])
            if value.get("time_stop_bars_15m") is not None
            else None
        ),
        "trail_activate_r": optional_number(value.get("trail_activate_r")),
        "trail_atr_mult": optional_number(value.get("trail_atr_mult")),
        "breakeven_r": optional_number(value.get("breakeven_r")),
        "partial_r": optional_number(value.get("partial_r")),
        "partial_fraction": optional_number(value.get("partial_fraction")),
    }


def config_sha(config: Mapping[str, Any]) -> str:
    return stable_sha(normalized_config(config))


def build_exit_spec(
    alpha: Any,
    baseline: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    interval: str,
    variant_id: str,
) -> Any:
    cfg = normalized_config(config)
    base_exit = alpha.multi.exact._exit_from(baseline["candidate"])
    factor = 15 if interval == "1m" else 1
    time_stop = cfg["time_stop_bars_15m"]
    return replace(
        base_exit,
        exit_id=f"ALPHA_UNATTENDED_{variant_id}_{interval}",
        stop_mult=float(cfg["stop_mult"]),
        time_stop_bars=(int(time_stop) * factor if time_stop is not None else None),
        trail_activate_r=cfg["trail_activate_r"],
        trail_atr_mult=cfg["trail_atr_mult"],
        breakeven_r=cfg["breakeven_r"],
        partial_r=cfg["partial_r"],
        partial_fraction=cfg["partial_fraction"],
    )


def loss_contract(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, bool]:
    gate = policy["candidate_selection_gate"]
    loss = row.get("loss_metrics") if isinstance(row.get("loss_metrics"), Mapping) else {}
    stress = row.get("stress") if isinstance(row.get("stress"), Mapping) else {}
    stress_loss = stress.get("loss_metrics") if isinstance(stress.get("loss_metrics"), Mapping) else {}
    return {
        "normal_worst": metric(loss.get("normal_worst_net_loss_R"), -math.inf)
        >= float(gate["normal_worst_net_loss_R_min"]),
        "normal_breaches": int(loss.get("loss_cap_breach_count") or 0)
        <= int(gate["loss_cap_breach_count_max"]),
        "stress_worst": metric(stress_loss.get("normal_worst_net_loss_R"), -math.inf)
        >= float(gate["stress_worst_net_loss_R_min"]),
        "stress_breaches": int(stress_loss.get("loss_cap_breach_count") or 0)
        <= int(gate["loss_cap_breach_count_max"]),
    }


def champion_gate(row: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    gate = policy["absolute_champion_gate"]
    loss = row.get("loss_metrics") if isinstance(row.get("loss_metrics"), Mapping) else {}
    stress = row.get("stress") if isinstance(row.get("stress"), Mapping) else {}
    stress_loss = stress.get("loss_metrics") if isinstance(stress.get("loss_metrics"), Mapping) else {}
    parity = row.get("parity") if isinstance(row.get("parity"), Mapping) else {}
    checks = {
        "sample": int(row.get("trade_count") or 0) >= int(gate["minimum_trade_count"]),
        "net_positive": metric(row.get("net_return_pct_sum"), -math.inf)
        >= float(gate["minimum_net_return_pct_sum"]),
        "win_rate": metric(row.get("win_rate_pct"), -math.inf)
        >= float(gate["minimum_win_rate_pct"]),
        "profit_factor": metric(row.get("net_profit_factor"), -math.inf)
        >= float(gate["minimum_profit_factor"]),
        "payoff": metric(row.get("payoff_ratio"), -math.inf)
        >= float(gate["minimum_payoff_ratio"]),
        "drawdown": metric(row.get("max_drawdown_pct"), math.inf)
        <= float(gate["maximum_drawdown_pct"]),
        "positive_windows": metric(row.get("positive_windows_pct"), -math.inf)
        >= float(gate["minimum_positive_windows_pct"]),
        "normal_worst": metric(loss.get("normal_worst_net_loss_R"), -math.inf)
        >= float(gate["normal_worst_net_loss_R_min"]),
        "normal_breaches": int(loss.get("loss_cap_breach_count") or 0)
        <= int(gate["loss_cap_breach_count_max"]),
        "stress_worst": metric(stress_loss.get("normal_worst_net_loss_R"), -math.inf)
        >= float(gate["stress_worst_net_loss_R_min"]),
        "stress_breaches": int(stress_loss.get("loss_cap_breach_count") or 0)
        <= int(gate["loss_cap_breach_count_max"]),
        "parity": (
            parity.get("state") == "PASS"
            if bool(gate.get("parity_required", True))
            else True
        ),
        "duplicates": int(parity.get("duplicate_trade_count") or 0)
        <= int(gate["duplicate_trade_count_max"]),
    }
    return {"pass": all(checks.values()), "checks": checks}


def objective_values(row: Mapping[str, Any]) -> dict[str, float]:
    return {
        "net": metric(row.get("net_return_pct_sum"), -math.inf),
        "profit_factor": metric(row.get("net_profit_factor"), -math.inf),
        "payoff": metric(row.get("payoff_ratio"), -math.inf),
        "win_rate": metric(row.get("win_rate_pct"), -math.inf),
        "drawdown": metric(row.get("max_drawdown_pct"), math.inf),
        "positive_windows": metric(row.get("positive_windows_pct"), 0.0),
    }


def quality_score(row: Mapping[str, Any]) -> float:
    value = objective_values(row)
    return (
        value["net"] * 5.0
        + value["profit_factor"] * 12.0
        + value["payoff"] * 5.0
        + value["win_rate"] * 0.35
        - value["drawdown"] * 4.0
        + value["positive_windows"] * 0.05
    )


def candidate_gate(
    candidate: Mapping[str, Any],
    control: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    gate = policy["candidate_selection_gate"]
    candidate_obj = objective_values(candidate)
    control_obj = objective_values(control)
    retention = int(candidate.get("trade_count") or 0) / max(
        1, int(control.get("trade_count") or 0)
    ) * 100.0
    improvements = {
        "net": candidate_obj["net"] > control_obj["net"] + 1e-12,
        "profit_factor": candidate_obj["profit_factor"]
        > control_obj["profit_factor"] + 1e-12,
        "payoff": candidate_obj["payoff"] > control_obj["payoff"] + 1e-12,
        "win_rate": candidate_obj["win_rate"] > control_obj["win_rate"] + 1e-12,
        "drawdown": candidate_obj["drawdown"] < control_obj["drawdown"] - 1e-12,
    }
    loss_checks = loss_contract(candidate, policy)
    parity = candidate.get("parity") if isinstance(candidate.get("parity"), Mapping) else {}
    checks = {
        "sample": int(candidate.get("trade_count") or 0)
        >= int(gate["minimum_trade_count"]),
        "retention": retention >= float(gate["minimum_retention_pct"]),
        "parity": parity.get("state") == "PASS",
        "duplicates": int(parity.get("duplicate_trade_count") or 0) == 0,
        "loss_contract": all(loss_checks.values()),
        "net_nonworse": candidate_obj["net"] >= control_obj["net"] - 1e-12,
        "profit_factor_nonworse": candidate_obj["profit_factor"]
        >= control_obj["profit_factor"] - 1e-12,
        "win_rate_floor": candidate_obj["win_rate"]
        >= control_obj["win_rate"]
        - float(gate["maximum_win_rate_degradation_pct_points"]),
        "payoff_floor": candidate_obj["payoff"]
        >= control_obj["payoff"] - float(gate["maximum_payoff_degradation"]),
        "multiobjective": sum(improvements.values())
        >= int(gate["minimum_improved_objectives"]),
        "score_improved": quality_score(candidate) > quality_score(control) + 1e-12,
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "retention_pct": retention,
        "improvements": improvements,
        "quality_score": quality_score(candidate),
        "control_quality_score": quality_score(control),
    }


def config_for_axis(
    control: Mapping[str, Any],
    axis: Mapping[str, Any],
    value: Any,
) -> dict[str, Any]:
    config = normalized_config(control)
    field = str(axis["field"])
    config[field] = value
    paired_field = axis.get("paired_field")
    if paired_field and config.get(str(paired_field)) is None:
        config[str(paired_field)] = axis.get("paired_default")
    return normalized_config(config)


def compact_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    loss = row.get("loss_metrics") if isinstance(row.get("loss_metrics"), Mapping) else {}
    stress = row.get("stress") if isinstance(row.get("stress"), Mapping) else {}
    stress_loss = stress.get("loss_metrics") if isinstance(stress.get("loss_metrics"), Mapping) else {}
    return {
        "variant_id": row.get("variant_id"),
        "config": row.get("config"),
        "config_sha256": row.get("config_sha256"),
        "trade_count": row.get("trade_count"),
        "win_rate_pct": row.get("win_rate_pct"),
        "net_return_pct_sum": row.get("net_return_pct_sum"),
        "net_profit_factor": row.get("net_profit_factor"),
        "payoff_ratio": row.get("payoff_ratio"),
        "max_drawdown_pct": row.get("max_drawdown_pct"),
        "positive_windows_pct": row.get("positive_windows_pct"),
        "normal_worst_net_loss_R": loss.get("normal_worst_net_loss_R"),
        "normal_loss_cap_breach_count": loss.get("loss_cap_breach_count"),
        "stress_worst_net_loss_R": stress_loss.get("normal_worst_net_loss_R"),
        "stress_loss_cap_breach_count": stress_loss.get("loss_cap_breach_count"),
        "parity": row.get("parity"),
        "champion_gate": row.get("champion_gate"),
        "candidate_gate": row.get("candidate_gate"),
        "quality_score": row.get("quality_score"),
    }


def evaluate_config(
    *,
    alpha: Any,
    baseline: Mapping[str, Any],
    strategy: Any,
    gate: Any,
    surgery: Any,
    symbols: Sequence[str],
    data_root: Path,
    manifest: Mapping[str, Any],
    funding: Mapping[str, list[dict[str, Any]]],
    config: Mapping[str, Any],
    variant_id: str,
) -> dict[str, Any]:
    files = [
        row
        for row in manifest.get("files", [])
        if isinstance(row, Mapping) and row.get("kind") == "market"
    ]
    normal_a: list[dict[str, Any]] = []
    normal_b: list[dict[str, Any]] = []
    stress: list[dict[str, Any]] = []
    stop_mult = metric(config.get("stop_mult"), 0.65)
    for file_row in files:
        symbol = str(file_row["symbol"])
        if symbol not in symbols:
            continue
        interval = str(file_row["interval"])
        window_id = str(file_row["window_id"])
        frame = base.frame_csv(data_root / str(file_row["path"]))
        exit_spec = build_exit_spec(
            alpha,
            baseline,
            config,
            interval=interval,
            variant_id=variant_id,
        )
        kwargs = dict(
            alpha=alpha,
            strategy=strategy,
            gate=gate,
            surgery=surgery,
            exit_spec=exit_spec,
            frame=frame,
            funding=funding,
            symbol=symbol,
            interval=interval,
            window_id=window_id,
            variant_id=variant_id,
            warmup_bars=240,
        )
        normal_a.extend(base.replay_one(**kwargs, stress=False))
        normal_b.extend(base.replay_one(**kwargs, stress=False))
        stress.extend(base.replay_one(**kwargs, stress=True))
    metrics = base.variant_metrics(alpha, normal_a, stress, stop_mult)
    parity = base.ledger_sha(normal_a) == base.ledger_sha(normal_b)
    duplicates = len(normal_a) - len(
        {str(row.get("trade_id")) for row in normal_a}
    )
    metrics.update(
        {
            "variant_id": variant_id,
            "config": normalized_config(config),
            "config_sha256": config_sha(config),
            "parity": {
                "state": "PASS" if parity and duplicates == 0 else "HOLD",
                "duplicate_trade_count": duplicates,
            },
            "quality_score": None,
            "raw_trade_rows_published": False,
            "raw_prices_published": False,
        }
    )
    metrics["quality_score"] = quality_score(metrics)
    return metrics


def choose_axis(
    policy: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    epoch: int,
) -> Mapping[str, Any]:
    axes = [row for row in policy.get("axes", []) if isinstance(row, Mapping)]
    if not axes:
        raise RuntimeError("AXIS_CATALOG_EMPTY")
    requested = str((previous or {}).get("next_axis_id") or "")
    for axis in axes:
        if str(axis.get("axis_id")) == requested:
            return axis
    return axes[epoch % len(axes)]


def fingerprint(
    *,
    data_root: Path,
    baseline_path: Path,
    authority_root: Path,
    policy_path: Path,
) -> str:
    return stable_sha(
        {
            "data_manifest_sha256": file_sha(data_root / "manifest.json"),
            "baseline_summary_sha256": file_sha(baseline_path),
            "multiobjective_summary_sha256": file_sha(authority_root / "summary.json"),
            "policy_sha256": file_sha(policy_path),
        }
    )


def self_test(policy: Mapping[str, Any]) -> int:
    control = normalized_config(policy["initial_control"])
    axis = policy["axes"][0]
    candidate = config_for_axis(control, axis, axis["values"][0])
    assert candidate[axis["field"]] == axis["values"][0]
    assert config_sha(control) != config_sha(candidate)
    fake = {
        "trade_count": 120,
        "net_return_pct_sum": 5.0,
        "win_rate_pct": 60.0,
        "net_profit_factor": 2.5,
        "payoff_ratio": 2.2,
        "max_drawdown_pct": 3.0,
        "positive_windows_pct": 100.0,
        "loss_metrics": {
            "normal_worst_net_loss_R": -0.7,
            "loss_cap_breach_count": 0,
        },
        "stress": {
            "loss_metrics": {
                "normal_worst_net_loss_R": -0.72,
                "loss_cap_breach_count": 0,
            }
        },
        "parity": {"state": "PASS", "duplicate_trade_count": 0},
    }
    assert champion_gate(fake, policy)["pass"] is True
    print("PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--alpha-root", type=Path)
    parser.add_argument("--baseline-summary", type=Path)
    parser.add_argument("--multiobjective-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--previous-state", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    policy = read_json(args.policy)
    if args.self_test:
        return self_test(policy)
    required = (
        args.alpha_root,
        args.baseline_summary,
        args.multiobjective_root,
        args.data_root,
        args.out,
    )
    if any(value is None for value in required):
        parser.error("alpha-root, baseline-summary, multiobjective-root, data-root and out are required")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    alpha_root = args.alpha_root.resolve()
    baseline_path = args.baseline_summary.resolve()
    authority_root = args.multiobjective_root.resolve()
    data_root = args.data_root.resolve()
    current_fingerprint = fingerprint(
        data_root=data_root,
        baseline_path=baseline_path,
        authority_root=authority_root,
        policy_path=args.policy.resolve(),
    )

    previous: dict[str, Any] | None = None
    if args.previous_state and args.previous_state.is_file():
        value = read_json(args.previous_state)
        if value.get("schema_version") == STATE_SCHEMA:
            previous = value
    if previous and previous.get("data_fingerprint") != current_fingerprint:
        previous = None

    safety = policy["safety"]
    if previous and previous.get("champion_found") is True:
        receipt = {
            "schema_version": SCHEMA,
            "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "state": "PASS_ALPHA_CHAMPION_ALREADY_SEALED_FOR_RESEARCH_HOLDBACK",
            "strategy_id": "alpha_combo",
            "data_fingerprint": current_fingerprint,
            "champion": previous.get("best_metrics"),
            "champion_config": previous.get("best_config"),
            "champion_found": True,
            "next": "WAIT_SEALED_HOLDBACK_AND_NEW_FORWARD_CONFIRMATION",
            **safety,
        }
        write_json(out / "latest.json", receipt)
        write_json(out / "state.json", previous)
        print(json.dumps({"state": receipt["state"], "champion_found": True}, sort_keys=True))
        return 0

    epoch = int((previous or {}).get("epoch") or 0)
    no_improvement = int((previous or {}).get("no_improvement_epochs") or 0)
    control_config = normalized_config(
        (previous or {}).get("best_config") or policy["initial_control"]
    )
    tested = set(str(value) for value in (previous or {}).get("tested_config_sha256", []))
    axis = choose_axis(policy, previous, epoch)
    axis_id = str(axis["axis_id"])

    alpha = base.load_alpha(alpha_root)
    baseline, strategy, gate, surgery, symbols = base.load_authorities(
        alpha,
        alpha_root,
        baseline_path,
        authority_root,
    )
    manifest = read_json(data_root / "manifest.json")
    if (
        manifest.get("state") != "PASS_HISTORICAL_OOS_DATA_READY"
        or manifest.get("forward_overlap_count") != 0
    ):
        raise RuntimeError("DATA_B_AUTHORITY_INVALID")
    funding = base.load_funding(data_root, symbols)

    control = evaluate_config(
        alpha=alpha,
        baseline=baseline,
        strategy=strategy,
        gate=gate,
        surgery=surgery,
        symbols=symbols,
        data_root=data_root,
        manifest=manifest,
        funding=funding,
        config=control_config,
        variant_id="CONTROL_CURRENT",
    )
    control["champion_gate"] = champion_gate(control, policy)
    control["candidate_gate"] = None

    candidates: list[dict[str, Any]] = []
    for ordinal, value in enumerate(axis.get("values", []), 1):
        config = config_for_axis(control_config, axis, value)
        digest = config_sha(config)
        if digest == config_sha(control_config) or digest in tested:
            continue
        variant_id = f"E{epoch + 1:02d}_{axis_id}_{ordinal:02d}"
        row = evaluate_config(
            alpha=alpha,
            baseline=baseline,
            strategy=strategy,
            gate=gate,
            surgery=surgery,
            symbols=symbols,
            data_root=data_root,
            manifest=manifest,
            funding=funding,
            config=config,
            variant_id=variant_id,
        )
        row["champion_gate"] = champion_gate(row, policy)
        row["candidate_gate"] = candidate_gate(row, control, policy)
        candidates.append(row)
        tested.add(digest)

    champions = [row for row in [control, *candidates] if row["champion_gate"]["pass"]]
    champions.sort(key=quality_score, reverse=True)
    champion = champions[0] if champions else None
    eligible = [row for row in candidates if row["candidate_gate"]["pass"]]
    eligible.sort(key=quality_score, reverse=True)
    improved = eligible[0] if eligible else None

    if champion is not None:
        best = champion
        champion_found = True
        no_improvement = 0
        state = "PASS_ALPHA_ABSOLUTE_CHAMPION_GATE"
        next_step = "CREATE_NEW_SEALED_HOLDBACK_THEN_W2_W3_CONFIRMATION"
    elif improved is not None:
        best = improved
        champion_found = False
        no_improvement = 0
        state = "PASS_ALPHA_UNATTENDED_EPOCH_IMPROVED"
        next_step = "CONTINUE_NEXT_GEMINI_SELECTED_SINGLE_AXIS"
    else:
        best = control
        champion_found = False
        no_improvement += 1
        state = "HOLD_ALPHA_UNATTENDED_EPOCH_NO_IMPROVEMENT"
        next_step = "CONTINUE_NEXT_GEMINI_SELECTED_SINGLE_AXIS"

    autonomy = policy["autonomy"]
    next_epoch = epoch + 1
    converged = (
        next_epoch >= int(autonomy["maximum_epochs_per_data_fingerprint"])
        or no_improvement >= int(autonomy["maximum_no_improvement_epochs"])
    ) and not champion_found
    if converged:
        state = "WAIT_NEW_DATA_FINGERPRINT_ALPHA_CHAMPION_NOT_FOUND"
        next_step = "WAIT_NEW_IMMUTABLE_DATA_THEN_RESET_SEARCH"

    axes = [row for row in policy["axes"] if isinstance(row, Mapping)]
    axis_position = next(
        (index for index, row in enumerate(axes) if str(row["axis_id"]) == axis_id),
        0,
    )
    deterministic_next_axis = str(axes[(axis_position + 1) % len(axes)]["axis_id"])
    best_config = normalized_config(best["config"])
    best_metrics = compact_metrics(best)
    state_payload = {
        "schema_version": STATE_SCHEMA,
        "version": VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "strategy_id": "alpha_combo",
        "data_fingerprint": current_fingerprint,
        "epoch": next_epoch,
        "last_axis_id": axis_id,
        "next_axis_id": deterministic_next_axis,
        "best_config": best_config,
        "best_config_sha256": config_sha(best_config),
        "best_metrics": best_metrics,
        "champion_found": champion_found,
        "converged": converged,
        "no_improvement_epochs": no_improvement,
        "tested_config_sha256": sorted(tested),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
    }
    receipt = {
        "schema_version": SCHEMA,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "strategy_id": "alpha_combo",
        "data_fingerprint": current_fingerprint,
        "epoch": next_epoch,
        "axis_id": axis_id,
        "control": compact_metrics(control),
        "candidate_count": len(candidates),
        "candidates": [compact_metrics(row) for row in candidates],
        "selected_improvement": compact_metrics(improved) if improved else None,
        "champion": compact_metrics(champion) if champion else None,
        "champion_found": champion_found,
        "converged": converged,
        "no_improvement_epochs": no_improvement,
        "deterministic_next_axis_id": deterministic_next_axis,
        "remaining_axis_ids": [str(row["axis_id"]) for row in axes],
        "absolute_champion_gate": policy["absolute_champion_gate"],
        "candidate_selection_gate": policy["candidate_selection_gate"],
        "source_authority": policy["authority"],
        "data_manifest_sha256": file_sha(data_root / "manifest.json"),
        "baseline_summary_sha256": file_sha(baseline_path),
        "multiobjective_summary_sha256": file_sha(authority_root / "summary.json"),
        "raw_canonical_exact25_used_as_control": False,
        "time54_time60_authority_restored": True,
        "raw_trade_rows_published": False,
        "raw_prices_published": False,
        "canonical_mutated": False,
        "registry_mutated": False,
        "runtime_mutated": False,
        "formal_ledger_mutated": False,
        "selection_authority": False,
        "promotion_authority": False,
        "shadow_start_allowed": False,
        "paper_allowed": False,
        "live_allowed": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "action": "hold",
        "next": next_step,
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    state_payload["last_receipt_sha256"] = receipt["receipt_sha256"]
    write_json(out / "latest.json", receipt)
    write_json(out / "state.json", state_payload)
    print(
        json.dumps(
            {
                "state": state,
                "epoch": next_epoch,
                "axis": axis_id,
                "candidate_count": len(candidates),
                "selected": (improved or {}).get("variant_id"),
                "champion_found": champion_found,
                "best_net": best_metrics.get("net_return_pct_sum"),
                "best_wr": best_metrics.get("win_rate_pct"),
                "best_pf": best_metrics.get("net_profit_factor"),
                "best_payoff": best_metrics.get("payoff_ratio"),
                "next": next_step,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
