"""Gunicorn WSGI entrypoint.

The application factory is required to return a fully bound app. There is no
blank-app fallback because that previously hid broken blueprint wiring.
"""

from backend.app_factory import create_app


app = create_app()
