#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import tempfile
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"COUNTERFACTUAL_INTEGRITY_PATCH_ANCHOR_INVALID:{label}:{count}")
    return source.replace(old, new, 1)


def apply_patch(source: str) -> str:
    if "GROSS_LOSS_CAP_AUDIT_V1" in source:
        raise RuntimeError("COUNTERFACTUAL_TOOL_ALREADY_PATCHED")

    source = replace_once(
        source,
        '''TOL = 1e-9


''',
        '''TOL = 1e-9
GROSS_LOSS_CAP_AUDIT_V1 = True
CAPITAL_RISK_AND_PRICE_RISK_DENOMINATORS_SEPARATED = True


''',
        "MARKER",
    )
    source = replace_once(
        source,
        '''def trade_r_values(trade: dict[str, Any]) -> tuple[float, float, float, float]:
    risk_pct = max(finite(trade.get("raw_r_distance_pct")), 1e-12)
    gross_r = finite(trade.get("gross_pnl_pct")) / risk_pct
    net_r = finite(trade.get("net_pnl_pct")) / risk_pct
    mfe_r = finite(trade.get("mfe_pct")) / risk_pct
    mae_r = abs(finite(trade.get("mae_pct"))) / risk_pct
    return gross_r, net_r, mfe_r, mae_r
''',
        '''def trade_r_values(trade: dict[str, Any]) -> tuple[float, float, float, float]:
    price_risk_pct = max(finite(trade.get("raw_r_distance_pct")), 1e-12)
    capital_risk_pct = max(finite(trade.get("risk_capital_pct"), price_risk_pct), 1e-12)
    gross_r = finite(trade.get("gross_pnl_pct")) / capital_risk_pct
    net_r = finite(trade.get("pnl_r"), finite(trade.get("net_pnl_pct")) / capital_risk_pct)
    mfe_r = finite(trade.get("mfe_pct")) / price_risk_pct
    mae_r = abs(finite(trade.get("mae_pct"))) / price_risk_pct
    return gross_r, net_r, mfe_r, mae_r
''',
        "R_DENOMINATORS",
    )
    source = replace_once(
        source,
        '''        "max_realized_loss_r_abs": round(max(net_losses, default=0.0), 10),
''',
        '''        "gross_max_realized_loss_r_abs": round(max(gross_losses, default=0.0), 10),
        "net_max_realized_loss_r_abs": round(max(net_losses, default=0.0), 10),
''',
        "GROSS_NET_LOSS_FIELDS",
    )
    source = replace_once(
        source,
        '''        and finite(metrics.get("max_realized_loss_r_abs")) <= 0.75 + 1e-7
''',
        '''        and finite(metrics.get("gross_max_realized_loss_r_abs")) <= 0.75 + 1e-7
''',
        "GROSS_LOSS_GATE",
    )
    source = replace_once(
        source,
        '''    if len(entries) != 25 or len(target_ids) != 12 or len(costs) != 3 or len(perturbations) != 2:
        blockers.append(f"EXECUTION_MATRIX_SHAPE_INVALID:{len(entries)}:{len(target_ids)}:{len(costs)}:{len(perturbations)}")
''',
        '''    if len(entries) != 25 or len(target_ids) != 12 or len(costs) != 3 or len(perturbations) != 2:
        blockers.append(f"EXECUTION_MATRIX_SHAPE_INVALID:{len(entries)}:{len(target_ids)}:{len(costs)}:{len(perturbations)}")
    if "cost_profile_0" not in costs or "perturbation_0" not in perturbations:
        blockers.append("BASELINE_AXIS_MISSING")
''',
        "BASELINE_AXIS_GUARD",
    )
    source = replace_once(
        source,
        '''    for row in expanded_candidates:
        try:
            protected_inputs.append(root / stress_runner.safe_repo_path(str(row.get("source_path") or "")))
        except Exception as exc:
            blockers.append(f"EXPANDED_SOURCE_PATH_INVALID:{type(exc).__name__}:{exc}")
    protected_inputs = list(dict.fromkeys(canonical_paths + protected_inputs))
''',
        '''    for row in expanded_candidates:
        try:
            protected_inputs.append(root / stress_runner.safe_repo_path(str(row.get("source_path") or "")))
        except Exception as exc:
            blockers.append(f"EXPANDED_SOURCE_PATH_INVALID:{type(exc).__name__}:{exc}")
    for row in market_entries:
        try:
            protected_inputs.append(root / stress_runner.safe_repo_path(str(row.get("path") or "")))
        except Exception as exc:
            blockers.append(f"FROZEN_MARKET_SOURCE_PATH_INVALID:{type(exc).__name__}:{exc}")
    protected_inputs = list(dict.fromkeys(canonical_paths + protected_inputs))
''',
        "PROTECT_FROZEN_MARKET",
    )
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    patched = apply_patch(input_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent, prefix=f".{output_path.name}.", delete=False
    ) as handle:
        handle.write(patched)
        temp_path = Path(handle.name)
    temp_path.replace(output_path)
    py_compile.compile(str(output_path), doraise=True)
    print("STATE=PASS_COUNTERFACTUAL_EXPANSION_INTEGRITY_PATCH")
    print("GROSS_LOSS_CAP_AND_NET_PAYOFF_SEPARATED=true")
    print("CAPITAL_RISK_AND_PRICE_RISK_DENOMINATORS_SEPARATED=true")
    print("FROZEN_MARKET_SOURCE_INTEGRITY_GUARDED=true")
    print("RC=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
