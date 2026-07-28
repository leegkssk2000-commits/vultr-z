from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class AppLifecycleFactoryTest(unittest.TestCase):
    def test_factory_returns_bound_app_without_importing_scheduler(self):
        import sys

        sys.modules.pop("engine.core_loop", None)
        from backend.app_factory import create_app

        app = create_app({"TESTING": True})
        self.assertIsNotNone(app)
        self.assertIn("dashboard_bp", app.blueprints)
        self.assertIn("portfolio_api", app.blueprints)
        self.assertNotIn("engine.core_loop", sys.modules)
        self.assertFalse(app.config["ZEL_BACKGROUND_SCHEDULER_STARTED"])
        self.assertEqual(app.config["ZEL_EXECUTION_AUTHORITY"], "NONE")
        self.assertEqual(app.config["ZEL_ORDER_AUTHORITY"], "BLOCKED")

    def test_dashboard_is_single_route_and_read_only_when_db_missing(self):
        from backend.app_factory import create_app

        with tempfile.TemporaryDirectory() as directory:
            missing_db = str(Path(directory) / "missing.sqlite")
            with patch.dict(os.environ, {"Z_DASHBOARD_DB_PATH": missing_db}, clear=False):
                app = create_app({"TESTING": True})
                client = app.test_client()

                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.get("/healthz").status_code, 200)
                summary = client.get("/api/summary")
                self.assertEqual(summary.status_code, 200)
                payload = summary.get_json()
                self.assertEqual(payload["trades"], 0)
                self.assertFalse(payload["db_bound"])
                self.assertTrue(payload["read_only"])

                root_rules = [rule for rule in app.url_map.iter_rules() if rule.rule == "/"]
                self.assertEqual(len(root_rules), 1)

    def test_wsgi_has_no_blank_app_fallback(self):
        import wsgi

        self.assertIsNotNone(wsgi.app)
        self.assertIn("dashboard_bp", wsgi.app.blueprints)
        self.assertIn("portfolio_api", wsgi.app.blueprints)


if __name__ == "__main__":
    unittest.main()
