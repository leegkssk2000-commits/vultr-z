from flask import Flask
from flask_cors import CORS

from app import create_app
from backend.routers.portfolio import bp as portfolio_bp


app = create_app()
if app is None:
    app = Flask(__name__)
    CORS(app)

if "portfolio_api" not in app.blueprints:
    app.register_blueprint(portfolio_bp)
