from __future__ import annotations

from fastapi import FastAPI

from backend.bots import TeamManager, list_bots, registry_snapshot
from backend.engine.strategy_registry import get_active_strategies, get_strategy_spec
from backend.routers import router as package_router
from backend.state.z_state_manager import STATE_MANAGER
from backend.zops_opt.api_registry_v1 import include_zops_optimization_registry


def main() -> int:
    market = {
        "trend_score": 0.82,
        "confirm_score": 0.64,
        "breakout_score": 0.58,
        "drawdown_score": 0.31,
        "intuition_score": 0.78,
        "decay_pct": 0.04,
        "venue_health": "strong",
        "consensus": "high",
        "stale": False,
        "stale_ms": 0,
        "freeze_mode": False,
        "reconcile_status": "ok",
        "source": "fixture:/runtime_import_smoke",
        "source_ts": 1,
    }
    bots = list_bots()
    assert bots == ["LBot", "MBot", "OBot", "SBot"], bots
    snapshot = registry_snapshot()
    assert snapshot["execution_allowed"] is False
    assert snapshot["order_authority"] == "BLOCKED"
    teams = TeamManager(mode="paper").list_teams(market)
    assert len(teams) == 4, teams
    assert all(team.mode == "paper" for team in teams)
    assert all(team.decision_id for team in teams)

    active = get_active_strategies()
    assert active, active
    spec = get_strategy_spec(active[0].key)
    assert spec.get("key") == active[0].key, spec

    package_paths = {getattr(route, "path", "") for route in package_router.routes}
    assert "/api/frontend-compat/status" in package_paths, package_paths
    assert "/api/v1/health" in package_paths, package_paths
    state = STATE_MANAGER.snapshot()
    assert state["status"] == "ok", state

    app = FastAPI()
    report = include_zops_optimization_registry(app)
    assert report["ok"] is True, report
    mounted_or_existing = set(report.get("mounted", [])) | set(report.get("skipped_existing", []))
    assert "/api/optimization/*" in mounted_or_existing, report
    assert "/api/harness/visual/status" in mounted_or_existing, report

    print({
        "state": "PASS_RUNTIME_IMPORT_SMOKE",
        "bot_count": len(bots),
        "team_count": len(teams),
        "strategy_count": len(active),
        "package_route_count": len(package_paths),
        "zops_mount_count": len(report.get("mounted", [])),
        "execution_allowed": False,
        "order_authority": "BLOCKED",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
