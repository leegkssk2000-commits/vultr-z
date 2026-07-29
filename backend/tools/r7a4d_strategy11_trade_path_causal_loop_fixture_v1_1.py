from __future__ import annotations

from backend.research import strategy11_pre_shadow_path_optimize_planner_v1_1 as planner
from backend.tools import r7a4d_strategy11_trade_path_causal_loop_fixture_v1 as core

core.build_plan = planner.build_plan

if __name__ == "__main__":
    raise SystemExit(core.main())
