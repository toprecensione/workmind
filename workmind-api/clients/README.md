# Client Extensions

Domain-specific modules. Each client is a self-contained package:

```
clients/<name>/
├── __init__.py
├── models.py    # SQLAlchemy models (Base from app.db.base)
├── routes.py    # FastAPI router + ROUTE_PREFIX + SECTOR
├── tasks.py     # Celery tasks (optional)
└── skills/      # Custom skills (optional)
```

app/main.py auto-discovers and loads every clients/<name>/routes.py.
Frontend pages go in src/routes/(<name>)/, built with VITE_CLIENT=<name>.
