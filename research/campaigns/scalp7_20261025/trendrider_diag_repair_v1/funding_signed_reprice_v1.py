"""BingX signed funding & native snapshot cost reconciliation, no orders.

All public funding/contract raw REST artifacts were captured in one bounded
one-time source observation BEFORE this experiment was calculated. Historical
received-at of each funding rate is NOT available. Nothing is used as a
real-time decision feature; every funding cost is booked only on trade close.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

HERE = Path(__file__).resolve().parent
FROZEN_UNIFIED = Path(
    os.environ.get(
        "ZEL_UNIFIED_PREVIOUS_OWNER",
        str(
            Path(__file__).resolve().parent.parent
            / "trendrider_unified_causal_recovery_v1"
        ),
    )
)
PARENT_1H = Path(
    os.environ.get(
        "ZEL_TRENDRIDER_FROZEN_INPUT_ROOT",
        str(Path(__file__).resolve().parent.parent / "trendrider_two_stage_v1"),
    )
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_module(p: Path) -> Any:
    spec = importlib.util.spec_from_file_location("zel_fused_strict", p)
    if not spec or not spec.loader:
        raise RuntimeError("REPLAY_CODE_SOURCE_MISSING")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read_inputs(out: Path) -> tuple[dict, dict, dict]:
    fr = json.loads((out / "FUNDING_RECONCILIATION_FREEZE.json").read_text())
    current = json.loads(
        (out / "BINGX_PUBLIC_CONTRACT_FUNDING_RECEIPT_V1.json").read_text()
    )
    prev = json.loads((FROZEN_UNIFIED / "RESULT.json").read_text())
    if fr["schema"] != "zel.trendrider.signed_funding_side_cost_reconciliation.v1":
        raise RuntimeError("NOT_FROZEN")
    if (
        sha((out / "BINGX_PUBLIC_CONTRACT_FUNDING_RECEIPT_V1.json").read_bytes())
        != fr["public_source_manifest_sha256"]
    ):
        raise RuntimeError("SOURCE_PIN_CHANGED")
    if sha((FROZEN_UNIFIED / "RESULT.json").read_bytes()) != fr["parent_result_sha256"]:
        raise RuntimeError("PARENT_RESULT_CHANGED")
    if (
        sha((FROZEN_UNIFIED / "TRACES.json.gz").read_bytes())
        != fr["parent_traces_sha256"]
    ):
        raise RuntimeError("PARENT_TRACES_CHANGED")
    if (
        sha((PARENT_1H / "MARKET_1H_SNAPSHOT.json.gz").read_bytes())
        != prev["source_snapshot_gzip_sha256"]
    ):
        raise RuntimeError("BARS_CHANGED")
    assert current["failed"] is False and len(current["snapshots"]) == 12
    return fr, current, prev


def snapshots() -> dict[str, dict[str, dict]]:
    original = json.loads((PARENT_1H / "FREEZE.json").read_text())["inputs"]
    git = original["liquid6"]
    buf = subprocess.check_output(
        ["git", "-C", "/home/z/z", "show", git["git_commit"] + ":" + git["path"]]
    )
    if sha(buf) != git["sha256"]:
        raise RuntimeError("SOURCE_CHANGED_L")
    with zipfile.ZipFile(PARENT_1H / "delayed_prospective_40146310229.zip") as z:
        src = z.read(original["delayed_long"]["inner_path"])
    if sha(src) != original["delayed_long"]["sha256"]:
        raise RuntimeError("SOURCE_CHANGED_D")
    L = json.loads(buf)
    D = json.loads(src)
    return {"Liquid6": L["execution_snapshots"], "Delayed": D["execution_snapshots"]}


def public_funding(
    out: Path, meta: dict
) -> tuple[dict[str, list[tuple[int, float]]], dict[str, dict]]:
    rates = {}
    contracts = {}
    for symbol, paths in meta["snapshots"].items():
        assert set(paths) == {"contract", "funding"}
        for kind, desc in paths.items():
            buf = (out / desc["raw_file"]).read_bytes()
            if sha(buf) != desc["raw_sha256"]:
                raise RuntimeError("BINGX_RAW_SHA_CHANGED:" + symbol + ":" + kind)
            data = json.loads(buf)["data"]
            if kind == "contract":
                if len(data) != 1 or data[0]["symbol"] != symbol:
                    raise RuntimeError("CONTRACT_MISMATCH")
                if float(data[0]["takerFeeRate"]) != 0.0005:
                    raise RuntimeError("REPRICE_STANDARD_TAKER_MISMATCH")
                contracts[symbol] = data[0]
            else:
                t = sorted(
                    (int(x["fundingTime"]), float(x["fundingRate"]) * 10000)
                    for x in data
                )
                if len(t) != len(set(x[0] for x in t)):
                    raise RuntimeError("FUNDING_DUPLICATE")
                if any(y[0] <= x[0] for x, y in zip(t, t[1:])):
                    raise RuntimeError("FUNDING_NON_MONOTONE")
                if t[0][0] > 1789318800000 or t[-1][0] < 1792915200000:
                    raise RuntimeError("FULL_FROZEN_SOURCE_NOT_COVERED:" + symbol)
                rates[symbol] = t
    return rates, contracts


def funding_components(
    *,
    side: str,
    symbol: str,
    entry_ms: int,
    terminal_open_ms: int,
    effective_closed_at: int,
    funding: dict[str, list[tuple[int, float]]],
) -> tuple[float, float, float, dict]:
    if not entry_ms <= terminal_open_ms <= effective_closed_at:
        raise RuntimeError("TRADE_NONCAUSAL_TIMESTAMPS")
    sign = 1.0 if side == "long" else -1.0
    certain = []
    ambiguous = []
    for ts, rate in funding[symbol]:
        if entry_ms < ts < terminal_open_ms:
            certain.append(rate * sign)
        elif (
            ts == entry_ms or terminal_open_ms <= ts <= effective_closed_at
        ) and entry_ms <= ts <= effective_closed_at:
            ambiguous.append(rate * sign)
    certain_signed = sum(certain)
    # No negative funding cashflows credited if historical receipt time is not verified.
    ambiguous_pay = sum(max(x, 0.0) for x in ambiguous)
    pessimistic_pay = 2.0 * (sum(max(x, 0.0) for x in certain) + ambiguous_pay)
    assert pessimistic_pay >= 0
    return (
        certain_signed,
        ambiguous_pay,
        pessimistic_pay,
        {
            "funding_events_certain": len(certain),
            "funding_events_possible_boundary": len(ambiguous),
            "signed_certain_bps": certain_signed,
            "ambiguous_pay_only_bps": ambiguous_pay,
            "worst_payer_doubled_bps": pessimistic_pay,
        },
    )


def priced_leg(
    *,
    scenario: str,
    model: Any,
    kwargs: dict,
    market: dict,
    snaps: dict,
    funding: dict,
    additional_fee_instrument_bps: float,
) -> dict:
    raw = model_make_leg_original(**kwargs)
    trade = kwargs["original"]
    symbol = str(trade["symbol"])
    lane = str(trade["source_lane"])
    s = snaps[lane][symbol]
    if s["symbol"] != symbol or str(trade["cost_snapshot_sha"]) != s["snapshot_sha256"]:
        raise RuntimeError("SOURCE_COST_SNAPSHOT_IDENTITY_DRIFT")
    knownfee = float(s["fee_bps"]) + float(s["spread_bps"]) + float(s["impact_bps"])
    assert float(s["fee_bps"]) == 10.0 and knownfee >= 10.0
    certain, ambiguous, pessimistic, diag = funding_components(
        side=kwargs["side"],
        symbol=symbol,
        entry_ms=int(kwargs["entry_ts"]),
        terminal_open_ms=int(kwargs["terminal_open_ms"]),
        effective_closed_at=int(kwargs["terminal_effective_ms"]),
        funding=funding,
    )
    extra_h = 0
    if kwargs["kind"] == "PRIMARY_LONG":
        if kwargs["reason"].startswith("EXT_"):
            extra_h = max(
                0,
                (int(kwargs["terminal_open_ms"]) - int(trade["exit_ts"])) // 3_600_000,
            )
        buffer = 5.0 * math.ceil(extra_h / 8) if extra_h else 0.0
    elif kwargs["kind"] == "REVERSAL_SHORT":
        extra_h = max(
            1,
            math.ceil(
                (int(kwargs["terminal_effective_ms"]) - int(kwargs["entry_ts"]))
                / 3_600_000
            ),
        )
        buffer = 5.0 * math.ceil(extra_h / 8)
    else:
        raise RuntimeError("UNEXPECTED_SIDE_KIND")
    if scenario == "C1_SIGNED_FUNDING":
        cost_instrument_bps = (
            2 * knownfee + certain + ambiguous + buffer + additional_fee_instrument_bps
        )
    elif scenario == "C2_PESSIMISTIC_NO_CREDIT":
        cost_instrument_bps = (
            2 * knownfee + pessimistic + buffer + additional_fee_instrument_bps
        )
    else:
        raise RuntimeError("UNKNOWN_COST_SCENARIO")
    assert cost_instrument_bps > 0.0
    cost_scaled_cost2 = cost_instrument_bps / 3.0
    raw["modeled_cost_bps"] = cost_scaled_cost2 / 2
    raw["Net2_bps"] = raw["gross_bps"] - cost_scaled_cost2
    raw["funding_signed_cost_detail"] = diag
    raw["funding_repriced_mode"] = scenario
    raw["contract_fee_spread_impact_instrument_bps"] = knownfee
    raw["funding_buffer_instrument_bps"] = buffer
    raw["incremental_stress_instrument_bps"] = additional_fee_instrument_bps
    raw["funding_source_verified"] = True
    raw["historical_entry_received_at_verified"] = False
    return raw


model_make_leg_original: Any = None


@contextlib.contextmanager
def patched_price(
    model: Any,
    *,
    scenario: str,
    snaps: dict,
    funding: dict,
    contracts: dict,
    add_fee: float = 0.0,
) -> Iterator:
    global model_make_leg_original
    old = model.make_leg
    if model_make_leg_original is not None:
        raise RuntimeError("MODEL_ALREADY_PATCHED")
    model_make_leg_original = old

    def override(**kwargs):
        return priced_leg(
            scenario=scenario,
            model=model,
            kwargs=kwargs,
            market={},
            snaps=snaps,
            funding=funding,
            additional_fee_instrument_bps=add_fee,
        )

    try:
        model.make_leg = override
        yield
    finally:
        model.make_leg = old
        model_make_leg_original = None


def native_price_precision_audit(unified_stage: dict, contracts: dict) -> dict:
    count = __import__("collections").Counter()
    rounded_loss_bp = []
    for opp in unified_stage["admitted"]:
        sym = opp["symbol"]
        tick = Decimal(1).scaleb(-int(contracts[sym]["pricePrecision"]))
        if not opp["legs"]:
            continue
        long = opp["legs"][0]
        entry = Decimal(str(long["entry"]))
        risk = Decimal(str(opp["initial_long_r_bps"])) * Decimal(3) / Decimal(10000)
        old_sl = entry * (Decimal(1) - risk)
        if old_sl / tick != (old_sl / tick).to_integral_value():
            count["LONG_SEALED_SL_NOT_PRICE_PRECISION_ALIGNED"] += 1
        rounded = (old_sl / tick).to_integral_value(
            rounding=__import__("decimal").ROUND_FLOOR
        ) * tick
        rounded_loss_bp.append(
            float((old_sl - rounded) / entry * Decimal(10000) / Decimal(3))
        )
        if len(opp["legs"]) == 2:
            sh = opp["legs"][1]
            en = Decimal(str(sh["entry"]))
            stoprisk = (
                Decimal(str(sh["short_initial_r_bps"])) * Decimal(3) / Decimal(10000)
            )
            stop = en * (Decimal(1) + stoprisk)
            if stop / tick != (stop / tick).to_integral_value():
                count["SHORT_NATIVE_STOP_NOT_PRICE_PRECISION_ALIGNED"] += 1
            count["SHORTS"] += 1
    return {
        "counts": dict(count),
        "long_rounded_adverse_risk_bp_sum_if_same_fill": sum(rounded_loss_bp),
        "does_NOT_replace_native_stop_sim": True,
        "formal_gate": "HOLD_NATIVE_TICK_QUANTIZED_CAUSAL_STOP_REPLAY",
    }


def run(out: Path):
    freeze, meta, _ = read_inputs(out)
    funding, contracts = public_funding(out, meta)
    snaps = snapshots()
    model = load_module(FROZEN_UNIFIED / "fuse_and_recover.py")
    old = model.old_module()
    snapshot, bars = old.source(PARENT_1H)
    maps, ema = old.index_bars(bars)
    old_rows = old.original_inputs(
        PARENT_1H, json.loads((PARENT_1H / "FREEZE.json").read_text())
    )
    candidates, input_diag = model.build_candidates(old_rows, old, bars, maps)
    latest = max(int(x["ts_ms"]) for x in bars["BTC-USDT"])
    assert len(candidates) == 267
    result = {
        "schema": "zel.trendrider.real_public_signed_funding_reconciliation.v1",
        "freeze_sha256": sha((out / "FUNDING_RECONCILIATION_FREEZE.json").read_bytes()),
        "public_meta_sha256": sha(
            (out / "BINGX_PUBLIC_CONTRACT_FUNDING_RECEIPT_V1.json").read_bytes()
        ),
        "former_model_result_sha256": freeze["parent_result_sha256"],
        "funding_per_symbol": {
            s: {
                "T": len(data),
                "start": data[0][0],
                "end": data[-1][0],
                "negative_T": sum(v < 0 for _, v in data),
            }
            for s, data in funding.items()
        },
        "original_ledger_basis": "PUBLIC_MODEL_NATIVE_SPREAD_SNAPSHOT_NOT_HISTORICAL_RECORDED_FILL",
        "scenario_metrics": {},
        "trace_attribution": {},
        "counterfactual_authority": "DEVELOPMENT_HOLD",
        "order_calls": 0,
        "API_calls_this_reprice": 0,
        "G5_approval": False,
        "real_broker_funding_receipt": False,
    }
    for scenario in ("C1_SIGNED_FUNDING", "C2_PESSIMISTIC_NO_CREDIT"):
        for stress in (
            (0.0, 20.0, 40.0) if scenario == "C2_PESSIMISTIC_NO_CREDIT" else (0.0,)
        ):
            with patched_price(
                model,
                scenario=scenario,
                snaps=snaps,
                funding=funding,
                contracts=contracts,
                add_fee=stress,
            ):
                r = model.run_stage(candidates, bars, maps, ema, old, 4, latest)
            score = model.metrics_stage(r)
            label = scenario + ":" + str(int(stress)) + "bp_STRESS_EXTRA_ALL"
            result["scenario_metrics"][label] = score
            if stress == 0:
                result["trace_attribution"][label] = {
                    "funding_boundary_events_long": sum(
                        z["funding_signed_cost_detail"][
                            "funding_events_possible_boundary"
                        ]
                        for x in r["admitted"]
                        for z in x["legs"]
                        if z["side"] == "long"
                    ),
                    "funding_boundary_events_short": sum(
                        z["funding_signed_cost_detail"][
                            "funding_events_possible_boundary"
                        ]
                        for x in r["admitted"]
                        for z in x["legs"]
                        if z["side"] == "short"
                    ),
                    "sum_known_signed_long_bps": sum(
                        z["funding_signed_cost_detail"]["signed_certain_bps"]
                        for x in r["admitted"]
                        for z in x["legs"]
                        if z["side"] == "long"
                    ),
                    "sum_known_signed_short_bps": sum(
                        z["funding_signed_cost_detail"]["signed_certain_bps"]
                        for x in r["admitted"]
                        for z in x["legs"]
                        if z["side"] == "short"
                    ),
                    "sum_payer_worst": sum(
                        z["funding_signed_cost_detail"]["worst_payer_doubled_bps"]
                        for x in r["admitted"]
                        for z in x["legs"]
                    ),
                    "native_price_audit": native_price_precision_audit(r, contracts),
                }
            print(
                "SOURCE_COST_SCENARIO",
                label,
                "T",
                score["accepted_opportunities"],
                "Net2",
                round(score["Net2_sum_trade_bps"], 2),
                "PF",
                round(score["PF2_opportunity"] or 0, 3),
                "DD",
                round(score["DD2_realized_exit_leg_bps"], 2),
                "streak",
                score["max_loss_streak_opportunity"],
                flush=True,
            )
    # Stress historical signed pessimistic short +1h latency and leave PEPE
    orig_short = model.new_short_leg
    try:

        def delayed_short(**kw):
            params = dict(kw)
            params["trigger_j"] += 1
            return orig_short(**params)

        model.new_short_leg = delayed_short
        with patched_price(
            model,
            scenario="C2_PESSIMISTIC_NO_CREDIT",
            snaps=snaps,
            funding=funding,
            contracts=contracts,
        ):
            late = model.run_stage(candidates, bars, maps, ema, old, 4, latest)
    finally:
        model.new_short_leg = orig_short
    result["scenario_metrics"]["C2_PLUS_1H_SHORT_EXECUTION_DELAY"] = (
        model.metrics_stage(late)
    )
    no_pepe = [t for t in candidates if t["symbol"] != "1000PEPE-USDT"]
    with patched_price(
        model,
        scenario="C2_PESSIMISTIC_NO_CREDIT",
        snaps=snaps,
        funding=funding,
        contracts=contracts,
    ):
        cut = model.run_stage(no_pepe, bars, maps, ema, old, 4, latest)
    result["scenario_metrics"]["C2_NO_1000PEPE_REPLAY_FULL"] = model.metrics_stage(cut)
    payload = (
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    with (out / "FUNDING_REPRICE_RESULT.json").open("xb") as f:
        f.write(payload)
    print(
        "FUNDING_REPRICE_RECEIPT_SHA",
        sha(payload),
        "C2_NO_1000PEPE",
        round(
            result["scenario_metrics"]["C2_NO_1000PEPE_REPLAY_FULL"][
                "Net2_sum_trade_bps"
            ],
            3,
        ),
        "C2_PLUS1H",
        round(
            result["scenario_metrics"]["C2_PLUS_1H_SHORT_EXECUTION_DELAY"][
                "Net2_sum_trade_bps"
            ],
            3,
        ),
        flush=True,
    )
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=HERE)
    args = parser.parse_args()
    run(args.root)
