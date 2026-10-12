"""Saved fill/mark tampering checks; fixtures never enter a market loader."""

from __future__ import annotations

import copy
import importlib.util
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/verify_scalp7_sr_continuous_two_arithmetic_v1.py"
)
SPEC = importlib.util.spec_from_file_location("sr_two_independent", SCRIPT)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def fixture():
    episode = "independent-fixture:BTC:0"
    policy = {
        "risk_fraction": 0.0025,
        "notional_fraction": 0.10,
        "capital_unit": "USDT",
        "quantity_unit": "BASE",
        "gap_notional_policy": "REJECT_ABOVE_RESERVED_NOTIONAL",
    }
    order = {
        "position_episode_id": episode,
        "symbol": "BTC",
        "side": 1,
        "qty_base": 1,
        "qty_policy": policy,
        "reserved_notional_usdt": 100,
        "reference_entry_price": 100,
        "protective_stop": 97.5,
        "planned_stop_risk_usdt": 2.5,
        "identity": "independent-fixture",
        "session_end_ms": 86_400_000,
        "reference_edge": 100,
        "signal": {"reference_id": "BTC:-86400000"},
    }
    ledger = [
        {
            "type": "FILL",
            "fill_id": "open",
            "ts_ms": 0,
            "available_ts_ms": 60_000,
            "symbol": "BTC",
            "side": 1,
            "effect": "OPEN",
            "position_episode_id": episode,
            "qty_base": 1,
            "fill_price": 100,
            "fee_usdt": 0.1,
        },
        {
            "type": "FILL",
            "fill_id": "close",
            "ts_ms": 60_000,
            "available_ts_ms": 120_000,
            "symbol": "BTC",
            "side": 1,
            "effect": "CLOSE",
            "position_episode_id": episode,
            "qty_base": 1,
            "fill_price": 105,
            "fee_usdt": 0.105,
        },
    ]
    window = {
        "name": "fixture_segment",
        "kind": "VALIDATION",
        "start_ts_ms": 0,
        "end_ts_ms": 3_600_000,
    }
    binding = {
        "identity_key": "independent-fixture",
        "binding_sha256": "fixture-binding",
        "initial_cash_usdt": 1000,
        "cost": {"per_side_rates": {"BTC": 0.001}},
        "windows": [window],
        "code_closure": {
            "backend/research/rebuild/scalp7_exact25_reference_models_v1.py": (
                "340e219fbf97a95f25b0414f588a12429f3978f05c7fbdd1108e30c68696c6d3"
            )
        },
    }
    segment = {
        "raw_start_ts_ms": 0,
        "evaluation_start_ts_ms": 0,
        "evaluation_end_ts_ms": 3_600_000,
    }
    contract = {"decision_minutes": 30, "symbols": ["BTC"]}
    result = {
        "identity_key": binding["identity_key"],
        "binding_sha256": binding["binding_sha256"],
        "fresh_T": 0,
        "unknown_execution_count": 0,
        "execution": {
            "ledger": ledger,
            "executions": [{"order": order, "state": "CLOSED"}],
        },
        "cost_scenarios": {},
    }
    for multiplier in (1, 2):
        fees = 0.205 * multiplier
        entry_fee = 0.1 * multiplier
        final_equity = 1005 - fees
        snapshots, curve = [], []
        for stamp in (0, 1_800_000, 3_600_000):
            opened = stamp == 0
            equity = 1000 - entry_fee if opened else final_equity
            positions = (
                [
                    {
                        "position_episode_id": episode,
                        "symbol": "BTC",
                        "side": 1,
                        "remaining_qty_base": 1,
                        "avg_entry_price": 100,
                    }
                ]
                if opened
                else []
            )
            snapshots.append(
                {
                    "ts_ms": stamp,
                    "prices": {
                        "BTC": {
                            "ts_ms": stamp,
                            "price_basis": "LAST_PRICE",
                            "price": 100 if opened else 105,
                        }
                    },
                    "positions": positions,
                    "realized_gross_cum_usdt": 0 if opened else 5,
                    "fees_cum_usdt": entry_fee if opened else fees,
                    "funding_received_cum_usdt": 0,
                    "external_flow_usdt": 0,
                }
            )
            curve.append(
                {
                    "ts_ms": stamp,
                    "cash_usdt": equity,
                    "unrealized_usdt": 0,
                    "equity_usdt": equity,
                    "peak_equity_usdt": 1000 if opened else equity,
                    "drawdown_pct": 0.01 * multiplier if opened else 0,
                }
            )
        stored_episode = {
            "episode_id": episode,
            "symbol": "BTC",
            "side": 1,
            "entry_ts_ms": 0,
            "quantity": 1,
            "entry_value": 100,
            "remaining": 0,
            "gross_usdt": 5,
            "cost_usdt": fees,
            "closed": True,
            "exit_ts_ms": 60_000,
            "outcome_available_ts_ms": 120_000,
            "net_reference_usdt": 5 - fees,
        }
        saved_window = {
            **window,
            "T_resolved": 1,
            "T_per_day_resolved": 24,
            "WR_resolved_pct": 100,
            "gross_resolved_usdt": 5,
            "net_resolved_reference_usdt": 5 - fees,
            "net_per_trade_resolved_reference_usdt": 5 - fees,
            "PF_resolved_reference": None,
            "PF_no_losses": True,
            "MaxLS_resolved": 0,
            "cross_boundary_or_open_count": 0,
            "carry_in_count": 0,
            "complete_window": True,
            "net_complete_reference_usdt": 5 - fees,
            "actual_historical_net_usdt": None,
            "funding_status": "UNKNOWN_NOT_ZERO",
            "DD_pct": 0.01 * multiplier,
        }
        result["cost_scenarios"][str(multiplier) + "x"] = {
            "episodes": [stored_episode],
            "windows": [saved_window],
            "account": {
                "snapshots": snapshots,
                "valuation": {
                    "curve": curve,
                    "initial_cash_usdt": 1000,
                    "max_drawdown_pct": 0.01 * multiplier,
                },
            },
            "account_status": "REFERENCE_COST_LAST_PRICE_NAV_FUNDING_UNKNOWN",
        }
    return result, binding, segment, contract


def run_child(data):
    check = audit.Audit()
    report, compact = audit.audit_child(*data, check, "fixture")
    return report, compact, check


def test_independent_quantity_cost_net_two_scenarios_and_grid():
    report, _, check = run_child(fixture())
    assert check.errors == []
    first, second = (report["cost_scenarios"][k] for k in ("1x", "2x"))
    assert first["metrics"]["T_resolved"] == second["metrics"]["T_resolved"] == 1
    assert first["metrics"]["cost_resolved_reference_usdt"] == Decimal("0.205")
    assert second["metrics"]["cost_resolved_reference_usdt"] == Decimal("0.410")
    assert first["metrics"]["net_resolved_reference_usdt"] == Decimal("4.795")
    assert second["metrics"]["net_resolved_reference_usdt"] == Decimal("4.590")
    assert first["nav"]["whole_segment_sample_grid_complete"] is True
    assert first["metrics"]["actual_historical_net_usdt"] is None


@pytest.mark.parametrize(
    "mutation",
    ["fee", "quantity", "gross", "net2x", "mark_grid", "mark_value", "unit", "unknown"],
)
def test_changed_saved_fill_or_account_cannot_pass(mutation):
    data = fixture()
    result = data[0]
    if mutation == "fee":
        result["execution"]["ledger"][0]["fee_usdt"] = 0.5
    elif mutation == "quantity":
        result["execution"]["ledger"][0]["qty_base"] = 2
    elif mutation == "gross":
        result["cost_scenarios"]["1x"]["episodes"][0]["gross_usdt"] = 7
    elif mutation == "net2x":
        result["cost_scenarios"]["2x"]["windows"][0][
            "net_resolved_reference_usdt"
        ] = 4.795
    elif mutation == "mark_grid":
        result["cost_scenarios"]["1x"]["account"]["snapshots"][1]["ts_ms"] += 1
    elif mutation == "mark_value":
        result["cost_scenarios"]["1x"]["account"]["snapshots"][0]["prices"]["BTC"][
            "price"
        ] = 101
    elif mutation == "unit":
        result["execution"]["ledger"][0]["quantity_unit"] = "CONTRACT"
    else:
        result["execution"]["executions"][0].update(
            state="UNRESOLVED",
            unresolved_observed_ts_ms=60_000,
            unresolved_from_ts_ms=0,
        )
        result["unknown_execution_count"] = 1
    _, _, check = run_child(data)
    assert check.error_count > 0


def test_grid_keeps_segment_boundaries_without_filling_gap():
    segment = {"raw_start_ts_ms": 4 * 60_000, "evaluation_end_ts_ms": 64 * 60_000}
    assert audit.sample_grid(segment, 30) == [240_000, 1_800_000, 3_600_000, 3_840_000]


def test_terminal_endpoint_dd_sensitivity_is_separate():
    curve = [
        {"ts_ms": 0, "equity_usdt": Decimal(1000)},
        {"ts_ms": 30, "equity_usdt": Decimal(1100)},
        {"ts_ms": 60, "equity_usdt": Decimal(900)},
    ]
    assert audit.dd_interval(curve, 1000, 0, 60) == 0
    assert audit.dd_interval(curve, 1000, 0, 61) == Decimal(20000) / Decimal(1100)


def test_winner_damage_absence_and_incomplete_stay_explicit():
    parent = {
        "complete": True,
        "keys": {"p": ("BTC", 1, "prior-day", 1, Decimal(100))},
        "cohort": [{"episode_id": "p", "net_reference_usdt": Decimal(5)}],
    }
    child = {
        "complete": True,
        "keys": {},
        "cohort": [],
        "episodes": [],
        "execution_states": {},
    }
    damage = audit.winner_damage(parent, child)
    measured = damage["complete_window_metrics"]
    assert measured["parent_winners"] == 1 and measured["child_absent_same_setup"] == 1
    assert measured["child_zero_same_setup"] == 0
    assert measured["winner_net_delta_usdt"] == -5
    child["complete"] = False
    partial = audit.winner_damage(parent, child)
    assert partial["complete_window_metrics"] is None
    assert (
        partial["closed_cohort_diagnostics"]["category_counts"][
            "NO_SAVED_ADMITTED_CHILD_ORDER"
        ]
        == 1
    )


def test_duplicate_opportunity_is_rejected_without_profitable_selection():
    parent = {
        "complete": True,
        "keys": {"p": ("same",), "p2": ("same",)},
        "cohort": [
            {"episode_id": "p", "net_reference_usdt": Decimal(5)},
            {"episode_id": "p2", "net_reference_usdt": Decimal(-1)},
        ],
    }
    damage = audit.winner_damage(
        parent,
        {
            "complete": True,
            "keys": {},
            "cohort": [],
            "episodes": [],
            "execution_states": {},
        },
    )
    assert damage["complete_window_metrics"] is None
    diagnostic = damage["closed_cohort_diagnostics"]
    assert diagnostic["ambiguous_parent_winner_match_count"] == 1
    assert diagnostic["opportunities"][0]["parent_admitted_episode_ids"] == ["p", "p2"]


def test_zero_trades_have_no_fabricated_winrate_pf_streak():
    stats = audit.core["cohort_stats"]([])
    assert stats["T_resolved"] == 0
    assert stats["WR_resolved_pct"] is None
    assert stats["PF_resolved_reference"] is None
    assert stats["MaxLS_resolved"] is None


def test_relocation_and_gzip_representation_only_parity_exception():
    report = {
        "status": "PASS",
        "segments": {"Net": 5},
        "inputs": {
            "SR_CONTROL": {
                "result_path": "a",
                "result_storage_sha256": "gzip-a",
                "freeze_path": "f-a",
                "result_sha256": "raw-stable",
            },
            "verifier_sha256": "fixed-verifier",
        },
    }
    relocated = copy.deepcopy(report)
    relocated["inputs"]["SR_CONTROL"].update(
        result_path="b", result_storage_sha256="gzip-b", freeze_path="f-b"
    )
    assert audit.substantive(relocated) == audit.substantive(report)
    relocated["segments"]["Net"] = 50
    assert audit.substantive(relocated) != audit.substantive(report)


@pytest.mark.parametrize("kind", ["OPEN", "UNRESOLVED", "BOUNDARY", "NO_FILL"])
def test_incomplete_winner_diagnostics_do_not_zero_unknown_or_boundary(kind):
    key = ("BTC", 1, "causal-prior-day", 86_400_000, Decimal(100))
    parent = {
        "complete": False,
        "keys": {"p": key},
        "cohort": [{"episode_id": "p", "net_reference_usdt": Decimal(5)}],
    }
    child = {
        "complete": False,
        "keys": {"c": key},
        "cohort": [],
        "episodes": [],
        "execution_states": {"c": ("EXPIRED", False)},
    }
    expected = "CHILD_ADMITTED_NO_FILL_TERMINAL"
    if kind in {"OPEN", "UNRESOLVED"}:
        child["episodes"] = [{"episode_id": "c", "closed": False}]
        child["execution_states"]["c"] = ("UNRESOLVED", kind == "UNRESOLVED")
        expected = "CHILD_OPEN_OR_UNRESOLVED"
    elif kind == "BOUNDARY":
        child["episodes"] = [{"episode_id": "c", "closed": True}]
        child["execution_states"]["c"] = ("CLOSED", False)
        expected = "CHILD_BOUNDARY_EXCLUDED_CLOSED"
    result = audit.winner_damage(parent, child)
    assert result["complete_window_metrics"] is None
    item = result["closed_cohort_diagnostics"]["opportunities"][0]
    assert item["child_category"] == expected
    assert item["child_resolved_cohort_net_usdt"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "risk_fraction",
        "notional_fraction",
        "capital_unit",
        "quantity_unit",
        "gap_notional_policy",
        "missing_field",
        "extra_field",
        "self_consistent_fractions",
    ],
)
def test_saved_order_cannot_redefine_frozen_producer_policy(mutation):
    data = fixture()
    order = data[0]["execution"]["executions"][0]["order"]
    policy = order["qty_policy"]
    if mutation == "missing_field":
        del policy["capital_unit"]
    elif mutation == "extra_field":
        policy["saved_override"] = True
    elif mutation == "self_consistent_fractions":
        policy.update(risk_fraction=0.005, notional_fraction=0.20)
        # The old calculation would still accept qty=1 and planned risk=2.5.
        capital = audit.number(order["reserved_notional_usdt"]) / audit.number(
            policy["notional_fraction"]
        )
        quantity = min(
            capital * audit.number(policy["risk_fraction"]) / Decimal("2.5"),
            capital * audit.number(policy["notional_fraction"]) / Decimal(100),
        )
        assert quantity == order["qty_base"]
    else:
        policy[mutation] = {
            "risk_fraction": 0.005,
            "notional_fraction": 0.05,
            "capital_unit": "CONTRACT",
            "quantity_unit": "CONTRACT",
            "gap_notional_policy": "ALLOW_ABOVE_RESERVED_NOTIONAL",
        }[mutation]
    _, _, check = run_child(data)
    assert any("quantity_policy.frozen_literal" in e["field"] for e in check.errors)


@pytest.mark.parametrize("mutation", ["freeze_hash", "producer_source"])
def test_policy_source_authentication_cannot_be_self_declared(mutation):
    data = fixture()
    if mutation == "freeze_hash":
        data[1]["code_closure"][audit.QTY_POLICY_SOURCE] = "0" * 64
        _, _, check = run_child(data)
    else:
        raw = (audit.ROOT / audit.QTY_POLICY_SOURCE).read_bytes()
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / audit.QTY_POLICY_SOURCE
            source.parent.mkdir(parents=True)
            source.write_bytes(raw + b"\n# altered producer\n")
            with patch.object(audit, "ROOT", root):
                _, _, check = run_child(data)
    assert any("quantity_policy.producer_" in e["field"] for e in check.errors)


@pytest.mark.parametrize(
    "case", ["CONTROL_COHORT", "CONTROL_OTHER", "RETEST_COHORT", "RETEST_OTHER"]
)
def test_nonwinner_duplicate_opportunities_remain_ambiguous(case):
    winner_key = ("BTC", 1, "winning-day", 1, Decimal(100))
    duplicate_key = ("ETH", -1, "other-day", 2, Decimal(200))
    parent = {
        "complete": True,
        "keys": {"p": winner_key},
        "cohort": [{"episode_id": "p", "net_reference_usdt": Decimal(5)}],
        "episodes": [],
        "execution_states": {},
    }
    child = {
        "complete": True,
        "keys": {},
        "cohort": [],
        "episodes": [],
        "execution_states": {},
    }
    arm = "SR_CONTROL" if case.startswith("CONTROL") else "SR_RETEST"
    source = parent if arm == "SR_CONTROL" else child
    source["keys"].update(d2=duplicate_key, d1=duplicate_key)
    if case.endswith("COHORT"):
        source["cohort"].extend(
            [
                {"episode_id": "d2", "net_reference_usdt": Decimal(-2)},
                {"episode_id": "d1", "net_reference_usdt": Decimal(-1)},
            ]
        )
    damage = audit.winner_damage(parent, child)
    assert damage["complete_pair_window"] is True
    assert damage["complete_window_metrics"] is None
    assert damage["unknown_reason"] == "AMBIGUOUS_CAUSAL_OPPORTUNITY"
    diagnostic = damage["closed_cohort_diagnostics"]
    assert diagnostic["ambiguous_parent_winner_match_count"] == 0
    assert diagnostic["ambiguous_admitted_opportunity_count"] == 1
    assert diagnostic["ambiguous_admitted_opportunities"] == [
        {
            "arm": arm,
            "opportunity_key": list(duplicate_key),
            "admitted_episode_ids": ["d1", "d2"],
        }
    ]


def test_duplicate_same_key_in_both_arms_keeps_all_ids_without_winners():
    key = ("BTC", 1, "causal-day", 1, Decimal(100))
    pair = [
        {
            "complete": True,
            "keys": {"a": key, "b": key},
            "cohort": [],
            "episodes": [],
            "execution_states": {},
        }
        for _ in range(2)
    ]
    damage = audit.winner_damage(*pair)
    assert damage["complete_window_metrics"] is None
    diagnostic = damage["closed_cohort_diagnostics"]
    assert diagnostic["parent_resolved_winner_count"] == 0
    assert diagnostic["ambiguous_admitted_opportunity_count"] == 2
    assert diagnostic["ambiguous_admitted_opportunities"] == [
        {"arm": arm, "opportunity_key": list(key), "admitted_episode_ids": ["a", "b"]}
        for arm in ("SR_CONTROL", "SR_RETEST")
    ]
