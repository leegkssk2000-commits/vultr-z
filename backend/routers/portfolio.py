"""Flask routes for read-only portfolio artifacts."""

from __future__ import annotations

from flask import Blueprint, jsonify

from backend.portfolio_binding import load_or_refresh_artifact


bp = Blueprint("portfolio_api", __name__)


@bp.route("/api/portfolio/state")
def portfolio_state():
    return jsonify(load_or_refresh_artifact("state"))


@bp.route("/api/portfolio/virtual")
def portfolio_virtual():
    return jsonify(load_or_refresh_artifact("virtual"))


@bp.route("/api/portfolio/positions")
def portfolio_positions():
    return jsonify(load_or_refresh_artifact("positions"))


@bp.route("/api/portfolio/pnl-bars")
def portfolio_pnl_bars():
    return jsonify(load_or_refresh_artifact("pnl-bars"))


@bp.route("/api/portfolio/equity-curve")
def portfolio_equity_curve():
    return jsonify(load_or_refresh_artifact("equity-curve"))
