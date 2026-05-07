import json
import tempfile
import unittest
from pathlib import Path

from backend.portfolio_binding import ARTIFACT_NAMES, build_portfolio_artifacts, load_or_refresh_artifact


def _write_source(root: Path, payload: dict):
    path = root / "data" / "portfolio" / "portfolio_source_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class PortfolioBindingTest(unittest.TestCase):
    def test_artifacts_are_refreshed_from_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_source(
                root,
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
                    "virtual_asset_pnl": {"BTCUSDT": 0},
                    "bot_team_stats": {"Alpha": {"win_rate": 100, "contribution": 0}},
                },
            )

            result = build_portfolio_artifacts(root)

            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["hold"])
            self.assertEqual(result["missing_fields"], [])
            for name in ARTIFACT_NAMES.values():
                self.assertTrue((root / "data" / "portfolio" / name).is_file())
            state = load_or_refresh_artifact("state", root)
            self.assertNotEqual(state.get("reason"), "portfolio_artifact_missing")
            self.assertFalse(state["execution_allowed"])
            self.assertFalse(state["mutation_allowed"])
            self.assertFalse(state["may_emit_to_bot"])

    def test_missing_fields_hold_without_filling_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_source(root, {"positions": [{"symbol": "BTCUSDT", "price": 104500}]})

            result = build_portfolio_artifacts(root)
            positions = load_or_refresh_artifact("positions", root)

            self.assertEqual(result["status"], "HARD_PAUSE")
            self.assertTrue(result["hold"])
            self.assertIn("positions[0].pos_pct", result["missing_fields"])
            self.assertIn("equity_series", result["missing_fields"])
            self.assertNotIn("pos_pct", positions["positions"][0])
            self.assertFalse(positions["execution_allowed"])
            self.assertFalse(positions["mutation_allowed"])
            self.assertFalse(positions["may_emit_to_bot"])

    def test_portfolio_binding_stays_outside_ui_paths(self):
        changed = [
            Path("backend/portfolio_binding.py"),
            Path("backend/routers/portfolio.py"),
            Path("wsgi.py"),
            Path("tests/test_portfolio_binding.py"),
        ]
        blocked = {"frontend", "static", "templates"}
        for path in changed:
            self.assertTrue(blocked.isdisjoint(path.parts))


if __name__ == "__main__":
    unittest.main()
