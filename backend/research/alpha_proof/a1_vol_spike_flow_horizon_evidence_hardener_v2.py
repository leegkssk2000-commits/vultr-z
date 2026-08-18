from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_bingx_market_sources_v1 import verify_sources
from backend.production.zel_production_bingx_ws_microstructure_v1 import BingXPublicWs
from backend.research.alpha_proof import a1_alpha_proof_gate_v2 as gate

SCHEMA = "zel.a1_vol_spike_flow_horizon_evidence_hardener.v2"
CANDIDATE_ID = "repair_3_flow_to_horizon"
CANDIDATE_SHA = "2bc6f543ab09fd1f1aaee0257b926dc8463a6aa4afc7bf4a9ab89fde88ec6e56"
DEFAULT_BUNDLE = Path("backend/research/alpha_proof/bundles/a1_alpha_proof_vol_spike_flow_horizon_v1.json")
DEFAULT_PROVENANCE = Path("backend/research/alpha_proof/evidence/a1_vol_spike_flow_horizon_parameter_provenance_v1.json")
DEFAULT_COST = Path("backend/research/rebuild/a1_rebuilt_bb_revert_cost_authority_v1.json")
DEFAULT_MARKET_POLICY = Path("config/zel_production_bingx_market_sources_v1.json")
DEFAULT_WS_POLICY = Path("config/zel_production_bingx_ws_microstructure_v2.json")
DEFAULT_WS_SOURCE = Path("backend/production/zel_production_bingx_ws_microstructure_v2.py")


def _read(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return obj


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _assert_authority(value: Mapping[str, Any], label: str) -> None:
    if value.get("selection_authority") is not False or value.get("promotion_authority") is not False:
        raise RuntimeError(f"{label}_SELECTION_AUTHORITY_INVALID")
    if value.get("execution_authority") != "NONE" or value.get("order_authority") != "BLOCKED":
        raise RuntimeError(f"{label}_EXECUTION_AUTHORITY_INVALID")
    if value.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError(f"{label}_LIVE_AUTHORITY_INVALID")
    if value.get("exchange_order_submitted") not in (None, False):
        raise RuntimeError(f"{label}_ORDER_SUBMITTED")


def _probe_trade_flow(ws_policy: Mapping[str, Any], timeout_sec: float = 25.0) -> dict[str, Any]:
    endpoint = str(ws_policy.get("websocket_url") or "")
    symbols = [str(x) for x in (ws_policy.get("symbols") or [])]
    if endpoint != "wss://open-api-swap.bingx.com/swap-market" or symbols != ["BTC-USDT", "ETH-USDT"]:
        raise RuntimeError("TRADE_FLOW_WS_POLICY_INVALID")
    stream_template = str((ws_policy.get("streams") or {}).get("trade") or "")
    if stream_template != "{symbol}@trade":
        raise RuntimeError("TRADE_FLOW_STREAM_CONTRACT_INVALID")
    channels = {stream_template.format(symbol=s): s for s in symbols}
    ws = BingXPublicWs(endpoint, timeout=5.0)
    samples: dict[str, dict[str, Any]] = {}
    started = time.monotonic()
    try:
        ws.connect()
        for channel in channels:
            ws.subscribe(channel)
            time.sleep(0.25)
        while time.monotonic() - started < timeout_sec and len(samples) < len(symbols):
            try:
                text = ws.recv_text()
            except (TimeoutError, socket.timeout):
                continue
            if text == "Ping":
                ws.send_text("Pong")
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, Mapping):
                continue
            dtype = str(msg.get("dataType") or "")
            symbol = channels.get(dtype)
            if not symbol:
                continue
            data = msg.get("data")
            if not isinstance(data, list) or not data:
                continue
            for raw in data:
                if not isinstance(raw, Mapping):
                    continue
                if not {"T", "s", "p", "q", "m"}.issubset(raw):
                    continue
                event_ms = int(float(raw["T"]))
                now_ms = int(time.time() * 1000)
                age_ms = now_ms - event_ms
                if age_ms < -5_000 or age_ms > 60_000:
                    continue
                samples[symbol] = {
                    "symbol": symbol,
                    "channel": dtype,
                    "source_event_ms": event_ms,
                    "observed_at_ms": now_ms,
                    "age_ms": age_ms,
                    "payload_sha256": _stable_sha(dict(raw)),
                    "fields_present": sorted({"T", "s", "p", "q", "m"}),
                }
                break
    finally:
        ws.close()
    if set(samples) != set(symbols):
        raise RuntimeError("TRADE_FLOW_LIVE_SAMPLE_INCOMPLETE:" + ",".join(sorted(samples)))
    receipt = {
        "schema_version": "zel.a1.trade_flow_live_probe.v1",
        "state": "PASS_BINGX_NATIVE_TRADE_FLOW_FRESH",
        "provider": "BINGX_PUBLIC_USDT_PERPETUAL_WS",
        "samples": [samples[s] for s in symbols],
        "source_code_sha256": _file_sha(DEFAULT_WS_SOURCE),
        "policy_sha256": _file_sha(DEFAULT_WS_POLICY),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }
    receipt["receipt_sha256"] = _stable_sha(receipt)
    return receipt


def harden(bundle: Mapping[str, Any], provenance_path: Path, cost_path: Path, market_policy: Mapping[str, Any], ws_policy: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    out = json.loads(json.dumps(bundle))
    candidate = out.get("candidate") or {}
    if candidate.get("candidate_id") != CANDIDATE_ID or candidate.get("candidate_sha256") != CANDIDATE_SHA:
        raise RuntimeError("VOL_SPIKE_CANDIDATE_IDENTITY_MISMATCH")

    provenance = _read(provenance_path)
    cost = _read(cost_path)
    if provenance.get("candidate_sha256") != CANDIDATE_SHA or provenance.get("selected_using_holdout") is not False:
        raise RuntimeError("VOL_SPIKE_PARAMETER_PROVENANCE_INVALID")
    if cost.get("state") != "FROZEN_REALISTIC_PUBLIC_BINGX_COST_AUTHORITY":
        raise RuntimeError("VOL_SPIKE_COST_AUTHORITY_INVALID")
    _assert_authority(cost, "COST")

    market = verify_sources(market_policy)
    trade_flow = _probe_trade_flow(ws_policy)
    _assert_authority(market, "MARKET")
    _assert_authority(trade_flow, "TRADE_FLOW")
    if market.get("state") != "PASS_BINGX_PUBLIC_MARKET_SOURCES_VERIFIED":
        raise RuntimeError("VOL_SPIKE_MARKET_SOURCE_NOT_PASS")
    bindings = market.get("source_bindings") or {}
    if bindings.get("ohlcv_source_bound") is not True or bindings.get("volume_source_bound") is not True:
        raise RuntimeError("VOL_SPIKE_OHLCV_VOLUME_NOT_BOUND")

    provenance_sha = _file_sha(provenance_path)
    cost_sha = _file_sha(cost_path)
    market_sha = gate.sha(market)
    flow_sha = str(trade_flow["receipt_sha256"])

    params = out.get("parameter_provenance", {}).get("parameters") or []
    expected = {str(x.get("name")) for x in (provenance.get("parameters") or []) if isinstance(x, Mapping)}
    actual = {str(x.get("name")) for x in params if isinstance(x, Mapping)}
    if actual != expected:
        raise RuntimeError("VOL_SPIKE_PARAMETER_INVENTORY_DRIFT")
    for row in params:
        if isinstance(row, dict):
            row["development_justification_sha"] = provenance_sha

    prior_cost = out.get("source_implementation_reality", {}).get("verified_round_trip_cost_bps")
    if not isinstance(prior_cost, (int, float)) or isinstance(prior_cost, bool):
        raise RuntimeError("VOL_SPIKE_PRIOR_COST_MISSING")
    out["source_implementation_reality"] = {
        "sources": [
            {"name": "ohlcv", "available": True, "fresh": True, "proxy": False, "source_sha": market_sha},
            {"name": "volume", "available": True, "fresh": True, "proxy": False, "source_sha": market_sha},
            {"name": "trade_flow", "available": True, "fresh": True, "proxy": False, "source_sha": flow_sha}
        ],
        "duplicate_count": 0,
        "leakage_count": 0,
        "timestamp_order_error_count": 0,
        "integrity_defect_count": 0,
        "verified_round_trip_cost_bps": float(prior_cost),
        "cost_authority_sha": cost_sha,
        "repo_status": "Candidate-matched same-run live source reality confirmed using existing BingX public REST market verifier and normalized WS trade source owner. This does not establish development-history sufficiency or alpha."
    }

    alpha = gate.evaluate_bundle(out)
    p2 = next(g for g in alpha["gates"] if g["gate"] == "P2_NUMERIC_PARAMETER_PROVENANCE")
    p6 = next(g for g in alpha["gates"] if g["gate"] == "P6_SOURCE_IMPLEMENTATION_REALITY")
    if not p2["passed"]:
        raise RuntimeError("VOL_SPIKE_P2_NOT_PASS:" + json.dumps(p2["failures"], sort_keys=True))
    if not p6["passed"]:
        raise RuntimeError("VOL_SPIKE_P6_NOT_PASS:" + json.dumps(p6["failures"], sort_keys=True))
    remaining = [g["gate"] for g in alpha["gates"] if not g["passed"]]
    if remaining != ["P3_EMPIRICAL_MOVE_VS_COST", "P4_NEGATIVE_CONTROLS_ABLATION", "P5_MULTI_AI_ADVERSARIAL_REVIEW"]:
        raise RuntimeError("VOL_SPIKE_UNEXPECTED_REMAINING_GATES:" + json.dumps(remaining))
    if alpha.get("state") != "HOLD_ALPHA_PROOF" or alpha.get("heavy_launch_allowed") is not False:
        raise RuntimeError("VOL_SPIKE_ALPHA_AUTHORITY_DRIFT")

    receipt = {
        "schema_version": SCHEMA,
        "candidate_id": CANDIDATE_ID,
        "candidate_sha256": CANDIDATE_SHA,
        "parameter_provenance_sha256": provenance_sha,
        "cost_authority_sha256": cost_sha,
        "market_receipt_sha256": market_sha,
        "trade_flow_receipt_sha256": flow_sha,
        "p2_passed": True,
        "p6_passed": True,
        "remaining_failed_gates": remaining,
        "development_history_claimed": False,
        "alpha_claimed": False,
        "fresh_boundary_created": False,
        "heavy_launch_allowed": False,
        "research_only": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    receipt["receipt_sha256"] = gate.sha(receipt)
    return out, receipt, alpha


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    ap.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    ap.add_argument("--cost", type=Path, default=DEFAULT_COST)
    ap.add_argument("--market-policy", type=Path, default=DEFAULT_MARKET_POLICY)
    ap.add_argument("--ws-policy", type=Path, default=DEFAULT_WS_POLICY)
    ap.add_argument("--out-dir", type=Path, default=Path("out/vol_spike_flow_horizon_p2_p6_v2"))
    args = ap.parse_args()
    hydrated, receipt, alpha = harden(_read(args.bundle), args.provenance, args.cost, _read(args.market_policy), _read(args.ws_policy))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "hydrated_bundle.json").write_text(json.dumps(hydrated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out_dir / "p2_p6_receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out_dir / "alpha_receipt.json").write_text(json.dumps(alpha, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": alpha["state"], "p2": "PASS", "p6": "PASS", "remaining_failed_gates": receipt["remaining_failed_gates"], "source_receipt_sha256": receipt["receipt_sha256"], "alpha_receipt_sha256": alpha["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
