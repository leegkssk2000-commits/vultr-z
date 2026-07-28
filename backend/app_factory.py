"""Explicit Flask application factory for the deployed WSGI surface.

This module intentionally has no scheduler, trading, database-write, or execution
side effects at import time. Runtime workers only bind read-only HTTP blueprints.
Background loops require a separately verified service owner.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import Flask
from flask_cors import CORS

from backend.routers.portfolio import bp as portfolio_bp
from frontend.dashboard import bp as dashboard_bp


APP_FACTORY_VERSION = "ZEL_APP_FACTORY_V1"


def _register_once(app: Flask, blueprint: Any, *, url_prefix: str | None = None) -> None:
    if blueprint.name not in app.blueprints:
        app.register_blueprint(blueprint, url_prefix=url_prefix)


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    CORS(app)
    if config:
        app.config.update(dict(config))

    _register_once(app, dashboard_bp, url_prefix="/")
    _register_once(app, portfolio_bp)

    app.config.update(
        ZEL_APP_FACTORY_VERSION=APP_FACTORY_VERSION,
        ZEL_BACKGROUND_SCHEDULER_STARTED=False,
        ZEL_EXECUTION_AUTHORITY="NONE",
        ZEL_ORDER_AUTHORITY="BLOCKED",
    )
    return app
