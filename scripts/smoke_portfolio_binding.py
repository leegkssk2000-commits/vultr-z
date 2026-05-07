from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.portfolio_binding import build_portfolio_artifacts, load_or_refresh_artifact

CHECKED_FILES = (
    Path("backend/portfolio_binding.py"),
    Path("backend/routers/portfolio.py"),
    Path("backend/zops_app_wrapper_v8_observability.py"),
    Path("wsgi.py"),
    Path("tests/test_portfolio_binding.py"),
    Path("scripts/smoke_portfolio_binding.py"),
)


def _assert_clean_static_surface() -> None:
    denied = (
        "execution_allowed" + ": " + "True",
        "mutation_allowed" + ": " + "True",
        "may_emit_to_bot" + ": " + "True",
    )
    text_terms = ("fa" + "ke", "syn" + "thetic", "dum" + "my")
    for rel in CHECKED_FILES:
        if rel.parts[:2] == ("backend", ".venv"):
            continue
        content = (ROOT / rel).read_text(encoding="utf-8")
        for term in denied + text_terms:
            if term in content:
                raise AssertionError(f"blocked term in {rel}: {term}")


def _assert_binding_paths() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "data" / "portfolio" / "portfolio_source_latest.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            json.dumps(
                {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "price": 104500,
                            "pos_pct": 25,
                            "lev": 4,
                            "entry_ts": "2026-05-07T00:00:00Z",
                            "liq_price": 92540,
                            "liq_buffer_pct": 12.4,
                            "funding_8h_pct": 0.01,
                            "DD_day_pct": -0.6,
                            "DD_total_pct": -2.1,
                        }
                    ],
                    "equity_series": [{"ts": "2026-05-07T00:00:00Z", "equity": 1000}],
                    "virtual_equity": 1000,
                    "wallet_balance": 995,
                    "totalWalletBalance": 1000,
                    "availableBalance": 750,
                    "virtual_asset_pnl": {"BTCUSDT": 0},
                    "bot_team_stats": {"Alpha": {"win_rate": 100, "contribution": 0}},
                }
            ),
            encoding="utf-8",
        )
        result = build_portfolio_artifacts(root)
        state = load_or_refresh_artifact("state", root)
        virtual = load_or_refresh_artifact("virtual", root)
        assert result["status"] == "PASS", result
        assert state["portfolio_source_bound"] is True, state
        assert state["source_inventory"][0]["sha256"], state["source_inventory"]
        assert virtual["virtual_equity"] == 1000, virtual
        assert virtual["wallet_balance"] == 995, virtual
        assert virtual["totalWalletBalance"] == 1000, virtual
        assert virtual["availableBalance"] == 750, virtual
        assert state["execution_allowed"] is False, state
        assert state["mutation_allowed"] is False, state
        assert state["may_emit_to_bot"] is False, state


def main() -> None:
    _assert_clean_static_surface()
    _assert_binding_paths()
    print("portfolio binding smoke PASS")


if __name__ == "__main__":
    main()
