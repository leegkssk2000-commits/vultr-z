import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.portfolio_binding import ARTIFACT_NAMES, build_portfolio_artifacts, load_or_refresh_artifact

SKELETON_PATCH = "V7_3_1_4_PORTFOLIO_READONLY_CONTRACT_SKELETON"


def _write_source(root: Path, payload: dict):
    path = root / "data" / "portfolio" / "portfolio_source_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_artifact(root: Path, kind: str, payload: dict):
    path = root / "data" / "portfolio" / ARTIFACT_NAMES[kind]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_sheets_csv(root: Path, source_ts_ms: str = ""):
    path = root / "data" / "sources" / "sheets_signal_latest.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "symbol,side,entry,mark,qty,lev,liq,TP,SL,entry_ts,rr,liq_warn,sl_ok,strategy,pos_pct,funding_8h_pct,dd_day_pct,dd_total_pct,liq_buffer_pct,source_ts_ms",
                f"BTCUSDT,long,104000,104500,0.01,4,92000,108000,101000,2026-05-02T00:00:00Z,2,0,1,Alpha,25,0.01,-0.6,-2.1,12.4,{source_ts_ms}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


async def _asgi_get(path: str) -> dict:
    from backend.zops_app_wrapper_v8_observability import app

    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app({"type": "http", "method": "GET", "path": path}, receive, send)
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return json.loads(body.decode("utf-8"))


class PortfolioBindingTest(unittest.TestCase):
    def test_existing_required_artifacts_are_served_before_source_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payloads = {
                "state": {"patch": "artifact_state", "status": "PASS"},
                "virtual": {"patch": "artifact_virtual", "status": "PASS", "virtual_equity": 10},
                "positions": {"patch": "artifact_positions", "positions": []},
                "pnl-bars": {"patch": "artifact_pnl_bars", "bars": []},
                "equity-curve": {"patch": "artifact_equity_curve", "equity_series": []},
            }
            for kind, payload in payloads.items():
                _write_artifact(root, kind, payload)

            for kind, expected in payloads.items():
                artifact = load_or_refresh_artifact(kind, root)
                self.assertEqual(artifact["patch"], expected["patch"])
                self.assertNotEqual(artifact.get("patch"), SKELETON_PATCH)
                self.assertTrue(artifact["portfolio_source_bound"])
                self.assertTrue(artifact["read_only"])
                self.assertFalse(artifact["execution_allowed"])
                self.assertFalse(artifact["mutation_allowed"])
                self.assertFalse(artifact["may_emit_to_bot"])
                labels = {row["label"] for row in artifact["source_inventory"]}
                self.assertIn(ARTIFACT_NAMES[kind], labels)

    def test_unusable_virtual_artifact_without_real_source_is_unbound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_artifact(root, "virtual", {"patch": "artifact_virtual", "virtual_equity": None})

            virtual = load_or_refresh_artifact("virtual", root)

            self.assertEqual(virtual["status"], "UNBOUND")
            self.assertFalse(virtual["portfolio_source_bound"])
            self.assertFalse(virtual["execution_allowed"])
            self.assertFalse(virtual["mutation_allowed"])
            self.assertFalse(virtual["may_emit_to_bot"])

    def test_sheets_csv_binds_mindata_when_virtual_artifact_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = _write_sheets_csv(root)
            _write_artifact(
                root,
                "virtual",
                {"patch": "V7_3_1_4_PORTFOLIO_READONLY_CONTRACT_SKELETON", "virtual_equity": None},
            )

            result = build_portfolio_artifacts(root)
            virtual = load_or_refresh_artifact("virtual", root)
            state = load_or_refresh_artifact("state", root)
            positions = load_or_refresh_artifact("positions", root)

            self.assertEqual(result["status"], "HARD_PAUSE")
            self.assertEqual(result["missing_fields"], ["wallet_balance"])
            self.assertTrue(virtual["portfolio_source_bound"])
            self.assertTrue(virtual["source_bound"])
            self.assertIsNone(virtual["wallet_balance"])
            self.assertEqual(virtual["missing_fields"], ["wallet_balance"])
            self.assertEqual(virtual["symbol"], "BTCUSDT")
            self.assertEqual(virtual["strategy"], "Alpha")
            self.assertEqual(virtual["price"], 104500)
            self.assertEqual(virtual["pos_pct"], 25)
            self.assertEqual(virtual["lev"], 4)
            self.assertEqual(virtual["entry_ts"], "2026-05-02T00:00:00Z")
            self.assertEqual(virtual["liq_price"], 92000)
            self.assertEqual(virtual["liq_buffer_pct"], 12.4)
            self.assertEqual(virtual["funding_8h_pct"], 0.01)
            self.assertEqual(virtual["DD_day_pct"], -0.6)
            self.assertEqual(virtual["DD_total_pct"], -2.1)
            self.assertEqual(state["primary_position"]["entry_price"], 104000)
            self.assertEqual(state["primary_position"]["qty"], 0.01)
            self.assertEqual(positions["positions"][0]["price"], 104500)
            self.assertEqual(positions["positions"][0]["leverage"], 4)
            self.assertEqual(positions["positions"][0]["source_ts_origin"], "file_mtime")
            self.assertEqual(positions["positions"][0]["source_ts_ms"], int(csv_path.stat().st_mtime * 1000))
            self.assertNotIn("positions[0].price", virtual["missing_fields"])
            self.assertNotIn("positions[0].liq_price", virtual["missing_fields"])
            self.assertFalse(virtual["execution_allowed"])
            self.assertFalse(virtual["mutation_allowed"])
            self.assertFalse(virtual["may_emit_to_bot"])

    def test_asgi_routes_serve_existing_artifacts_not_skeleton(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payloads = {
                "state": {"patch": "artifact_state"},
                "virtual": {"patch": "artifact_virtual", "virtual_equity": 10},
                "positions": {"patch": "artifact_positions"},
                "pnl-bars": {"patch": "artifact_pnl_bars"},
                "equity-curve": {"patch": "artifact_equity_curve"},
            }
            for kind, payload in payloads.items():
                _write_artifact(root, kind, payload)
            old_home = os.environ.get("Z_HOME")
            os.environ["Z_HOME"] = str(root)
            try:
                route_map = {
                    "state": "/api/portfolio/state",
                    "virtual": "/api/portfolio/virtual",
                    "positions": "/api/portfolio/positions",
                    "pnl-bars": "/api/portfolio/pnl-bars",
                    "equity-curve": "/api/portfolio/equity-curve",
                }
                for kind, path in route_map.items():
                    payload = asyncio.run(_asgi_get(path))
                    self.assertEqual(payload["patch"], payloads[kind]["patch"])
                    self.assertNotEqual(payload.get("patch"), SKELETON_PATCH)
                    self.assertTrue(payload["portfolio_source_bound"])
                    self.assertTrue(payload["read_only"])
                    self.assertFalse(payload["execution_allowed"])
                    self.assertFalse(payload["mutation_allowed"])
                    self.assertFalse(payload["may_emit_to_bot"])
            finally:
                if old_home is None:
                    os.environ.pop("Z_HOME", None)
                else:
                    os.environ["Z_HOME"] = old_home

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
                    "virtual_equity": 1000,
                    "wallet_balance": 995,
                    "totalWalletBalance": 1000,
                    "availableBalance": 750,
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
            self.assertTrue(state["portfolio_source_bound"])
            self.assertTrue(state["source_inventory"][0]["sha256"])
            self.assertTrue(state["source_inventory"][0]["ts_ms"])
            self.assertFalse(state["execution_allowed"])
            self.assertFalse(state["mutation_allowed"])
            self.assertFalse(state["may_emit_to_bot"])
            virtual = load_or_refresh_artifact("virtual", root)
            self.assertEqual(virtual["virtual_equity"], 1000)
            self.assertEqual(virtual["wallet_balance"], 995)
            self.assertEqual(virtual["totalWalletBalance"], 1000)
            self.assertEqual(virtual["availableBalance"], 750)

    def test_virtual_balance_only_source_is_bound_but_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_source(
                root,
                {
                    "virtual": {
                        "walletBalance": 44.5,
                        "totalWalletBalance": 45.0,
                        "availableBalance": 12.25,
                    }
                },
            )

            result = build_portfolio_artifacts(root)
            virtual = load_or_refresh_artifact("virtual", root)

            self.assertEqual(result["status"], "HARD_PAUSE")
            self.assertTrue(result["portfolio_source_bound"])
            self.assertEqual(virtual["wallet_balance"], 44.5)
            self.assertEqual(virtual["totalWalletBalance"], 45.0)
            self.assertEqual(virtual["availableBalance"], 12.25)
            self.assertIn("positions", result["missing_fields"])
            self.assertFalse(virtual["execution_allowed"])
            self.assertFalse(virtual["mutation_allowed"])
            self.assertFalse(virtual["may_emit_to_bot"])

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

    def test_source_inventory_uses_empty_strings_for_absent_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_portfolio_artifacts(Path(tmp))

            self.assertEqual(result["status"], "UNBOUND")
            self.assertFalse(result["portfolio_source_bound"])
            self.assertTrue(result["source_inventory"])
            self.assertTrue(all(row["sha256"] == "" for row in result["source_inventory"]))
            self.assertTrue(all(isinstance(row["sha256"], str) for row in result["source_inventory"]))

    def test_sqlite_paper_ledger_binds_real_pnl_and_keeps_position_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "db" / "z.sqlite"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db_path) as con:
                con.execute("CREATE TABLE trades(ts TEXT, symbol TEXT, strategy TEXT, pnl REAL)")
                con.execute(
                    "INSERT INTO trades(ts, symbol, strategy, pnl) VALUES(?,?,?,?)",
                    ("2026-05-07T00:00:00Z", "BTCUSDT", "Alpha", 12.5),
                )
                con.commit()

            result = build_portfolio_artifacts(root)
            virtual = load_or_refresh_artifact("virtual", root)

            self.assertTrue(result["portfolio_source_bound"])
            self.assertEqual(result["status"], "HARD_PAUSE")
            self.assertIn("positions", result["missing_fields"])
            self.assertEqual(virtual["virtual_asset_pnl"][0]["symbol"], "BTCUSDT")
            self.assertFalse(virtual["execution_allowed"])
            self.assertFalse(virtual["mutation_allowed"])
            self.assertFalse(virtual["may_emit_to_bot"])

    def test_portfolio_binding_stays_outside_ui_paths(self):
        changed = [
            Path("backend/portfolio_binding.py"),
            Path("backend/routers/portfolio.py"),
            Path("wsgi.py"),
            Path("backend/zops_app_wrapper_v8_observability.py"),
            Path("tests/test_portfolio_binding.py"),
            Path("scripts/smoke_portfolio_binding.py"),
        ]
        blocked = {"frontend", "static", "templates"}
        for path in changed:
            self.assertTrue(blocked.isdisjoint(path.parts))


if __name__ == "__main__":
    unittest.main()
