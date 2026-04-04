"""
WorkMind WSGI entry point for Gunicorn.

Usage:
    gunicorn -c scripts/gunicorn_conf.py wsgi:app
"""
from interface.web_ui import WorkMindUI

_ui = WorkMindUI(port=7860)
app = _ui._app
