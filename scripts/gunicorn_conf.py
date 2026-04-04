"""Gunicorn configuration for WorkMind."""
import os

bind = "127.0.0.1:7860"
workers = 2
threads = 4
timeout = 120
preload_app = True
accesslog = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "gunicorn_access.log")
errorlog = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "gunicorn_error.log")
loglevel = "info"
