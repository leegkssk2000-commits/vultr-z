from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools/q4r3_team_advisor_r41_validate_lico_sgrade_gap_audit.py"
spec = importlib.util.spec_from_file_location("r41_lico_audit", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def write_r36(path: Path, state: str = "PASS", ready: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": state, "report": {"sgrade_ready_count": ready}}), encoding="utf-8")


def full_surface_body() -> str:
    return """
from dataclasses import dataclass
@dataclass
class LicoContextEnvelope: pass
source_registry = {'cf:market': 1, 'sheets:policy': 1}
source_ids = ('cf:market', 'sheets:policy')
source_parity = True
source_consensus = consensus_score = source_confidence = 1.0
freshness = 'FRESH'
stale = False
source_age_ms = 1
order_book = l2 = best_bid = best_ask = mark_price = index_price = funding_rate = trade_stream = 1
venue_health = 'normal'
bingx = reject_rate = disconnect = feed_latency = latency_ms = 0
spread_bps = slippage_bps = market_impact = depth = execution_cost = fee_r = funding_r = 0
order_book_walking = book_walk = partial_fill = filled_qty = no_fill = queue_model = first_fill_ts = final_fill_ts = 0
maker_fee = taker_fee = funding = liquidation = liq_buffer = 0
stress_scenario = capital_stress = liquidity_stress = execution_degradation = volatility_shock = 0
team_context = alphateam = betateam = gammateam = deltateam = selected_team = 0
position_id = decision_id = strategy_id = method_id = skill_id = evidence_ids = contract_version = 'x'
actual_vs_simulated = fill_price_error_bps = fill_latency_error_ms = partial_fill_match = net_r_gap = calibration = 0
fail_closed = abstain = runtime_enabled = order_enabled = False
hold = route_change = execution_authority = 'none'
lico_manifest = 'canonical/lico'
"""


def write_owner(root: Path, body: str, name: str = "context.py") -> Path:
    path = root / "canonical/lico" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_complete_fixture_is_structure_ready(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_owner(root, full_surface_body())
    r36 = tmp_path / "r36.json"
    write_r36(r36)
    payload = module.analyze(root, r36)
    assert payload["state"] == "PASS"
    assert payload["report"]["canonical_owner_count"] == 1
    assert payload["report"]["missing_surface_count"] == 0


def test_missing_consensus_and_fill_model_hold(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    body = full_surface_body()
    body = body.replace("source_consensus = consensus_score = source_confidence = 1.0", "")
    body = body.replace("order_book_walking = book_walk = partial_fill = filled_qty = no_fill = queue_model = first_fill_ts = final_fill_ts = 0", "")
    write_owner(root, body)
    r36 = tmp_path / "r36.json"
    write_r36(r36)
    payload = module.analyze(root, r36)
    assert payload["state"] == "HOLD"
    assert "source_consensus" in payload["report"]["missing_surfaces"]
    assert "realistic_fill_model" in payload["report"]["missing_surfaces"]


def test_partial_fill_match_is_not_fill_engine(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    body = full_surface_body().replace(
        "order_book_walking = book_walk = partial_fill = filled_qty = no_fill = queue_model = first_fill_ts = final_fill_ts = 0",
        "",
    )
    write_owner(root, body)
    r36 = tmp_path / "r36.json"
    write_r36(r36)
    payload = module.analyze(root, r36)
    assert "realistic_fill_model" in payload["report"]["missing_surfaces"]


def test_backup_lico_tree_is_excluded(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_owner(root, full_surface_body())
    backup = root / "backend/_backup_phase2a_lico_20260427/canonical/lico/context.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(full_surface_body(), encoding="utf-8")
    r36 = tmp_path / "r36.json"
    write_r36(r36)
    payload = module.analyze(root, r36)
    assert payload["report"]["candidate_count"] == 1
    assert payload["report"]["canonical_owner_count"] == 1


def test_generic_exchange_adapter_is_not_lico_candidate(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_owner(root, full_surface_body())
    adapter = root / "backend/engine/exchange_adapter_bingx.py"
    adapter.parent.mkdir(parents=True, exist_ok=True)
    adapter.write_text(
        "spread_bps = slippage_bps = mark_price = funding_rate = latency_ms = 0\n",
        encoding="utf-8",
    )
    r36 = tmp_path / "r36.json"
    write_r36(r36)
    payload = module.analyze(root, r36)
    paths = {item["path"] for item in payload["report"]["candidates"]}
    assert str(adapter) not in paths
    assert payload["report"]["forbidden_hit_count"] == 0


def test_duplicate_canonical_owner_blocks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_owner(root, full_surface_body(), "context.py")
    write_owner(root, full_surface_body(), "adapter.py")
    r36 = tmp_path / "r36.json"
    write_r36(r36)
    payload = module.analyze(root, r36)
    assert payload["state"] == "HOLD"
    assert "LICO_DUPLICATE_CANONICAL_OWNER" in payload["blockers"]


def test_r36_is_mandatory(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    write_owner(root, full_surface_body())
    r36 = tmp_path / "r36.json"
    write_r36(r36, state="HOLD", ready=0)
    payload = module.analyze(root, r36)
    assert payload["state"] == "HOLD"
    assert "R36_FOUR_TEAM_SGRADE_LOCK_NOT_PROVEN" in payload["blockers"]
